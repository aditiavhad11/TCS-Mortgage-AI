from pathlib import Path
import secrets,io,json,re,hashlib,logging
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Form
from pydantic import BaseModel, Field, ConfigDict
from fastapi.responses import FileResponse, Response
from datetime import datetime, timezone
import fitz
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from sqlalchemy import delete, select
from PIL import Image
from app.config import settings
from app.database import get_db
from app.dependencies import current_customer
from app.models import Customer,MortgageApplication,ApplicationDocument,ApplicationDocumentChunk,CustomerNotification
from app.services.ocr import extract_text,SUPPORTED
from app.services.document_rag import index_document
from app.services.audit import record
from app.schemas import DocumentTextEditIn, DocumentFieldsEditIn
from app.services.nvidia import classify_document_category
router=APIRouter(prefix="/applications",tags=["Documents"])
logger=logging.getLogger(__name__)
MIN_CATEGORY_TEXT_CHARS=80
class CategoryConfirmationIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    category:str=Field(min_length=2,max_length=80)
    confirm:bool
CATEGORIES={"Mortgage Application","KYC","Income Proof / Salary Slip","Bank Statement","ITR","Sale / Purchase Agreement","Property Title","Property Valuation","Loan Agreement","Amortization Schedule","Terms / Disclosure"}
CATEGORY_LABELS={"Mortgage Application":"Mortgage Application","KYC":"KYC Documents — Identity/Address Proof","Income Proof / Salary Slip":"Income Proof / Salary Slips","Bank Statement":"Bank Statements","ITR":"Income Tax Returns (ITR)","Sale / Purchase Agreement":"Sale/Purchase Agreement","Property Title":"Property Title Documents","Property Valuation":"Property Valuation Report","Loan Agreement":"Loan Agreement","Amortization Schedule":"Amortization Schedule","Terms / Disclosure":"Terms & Conditions / Disclosure Documents"}
def _json(value, default):
    try:
        result=json.loads(value or "")
        return result if isinstance(result,type(default)) else default
    except (ValueError,TypeError): return default
def _structured_fields(text, category):
    """Extract conservative labelled OCR pairs; preserve exact evidence and page references."""
    specs = {
        "applicant_name": (r"applicant\s+name|customer\s+name|full\s+name|name", "text"),
        "gender": (r"gender|sex", "text"),
        "date_of_birth": (r"date\s+of\s+birth|birth\s+date|dob", "text"),
        "age": (r"age", "text"),
        "email": (r"email(?:\s+address)?", "text"),
        "mobile": (r"mobile(?:\s+number)?|phone(?:\s+number)?|contact\s+number", "text"),
        "employer_name": (r"employer(?:\s+name)?|company\s+name", "text"),
        "employment_type": (r"employment\s+type|type\s+of\s+employment", "text"),
        "occupation": (r"occupation|job\s+title|designation|profession", "text"),
        "employment_duration": (r"employment\s+duration|business\s+duration|years?\s+in\s+(?:service|business)", "text"),
        "annual_income": (r"annual\s+income|gross\s+income|reported\s+income", "number"),
        "total_income": (r"total\s+income", "number"),
        "monthly_income": (r"monthly\s+income|monthly\s+salary|salary\s+per\s+month", "number"),
        "gross_salary": (r"gross\s+salary", "number"),
        "net_salary": (r"net\s+salary|take\s+home(?:\s+salary)?", "number"),
        "other_income": (r"other\s+income|additional\s+income", "number"),
        "deductions": (r"total\s+deductions|deductions", "number"),
        "tax_paid": (r"tax\s+paid|income\s+tax", "number"),
        "assessment_year": (r"assessment\s+year|tax\s+year|ay", "text"),
        "salary_period": (r"salary\s+month|salary\s+period|pay\s+period", "text"),
        "statement_period": (r"bank\s+statement\s+period|statement\s+period|period", "text"),
        "opening_balance": (r"opening\s+balance", "number"),
        "closing_balance": (r"closing\s+balance", "number"),
        "total_credits": (r"total\s+credits|total\s+deposits", "number"),
        "total_debits": (r"total\s+debits|total\s+withdrawals", "number"),
        "salary_credits": (r"salary\s+credits|salary\s+credit", "number"),
        "recurring_commitments": (r"recurring\s+commitments|monthly\s+obligations|standing\s+instructions", "number"),
        "bank_name": (r"bank\s+name", "text"),
        "account_holder": (r"account\s+holder(?:\s+name)?|account\s+name", "text"),
        "account_number": (r"account\s+number|account\s+no", "text"),
        "ifsc": (r"ifsc(?:\s+code)?", "text"),
        "residential_address": (r"residential\s+address|permanent\s+address", "text"),
        "property_address": (r"property\s+address|address\s+of\s+property", "text"),
        "property_type": (r"property\s+type", "text"),
        "ownership_relationship": (r"ownership\s+(?:details|status|relationship)|owner(?:ship)?\s+name", "text"),
        "purchase_price": (r"purchase\s+price", "number"),
        "agreement_value": (r"registered\s+agreement\s+value|agreement\s+value|sale\s+consideration", "number"),
        "valuation_amount": (r"valuation\s+amount|market\s+value|assessed\s+value", "number"),
        "property_value": (r"property\s+value", "number"),
        "property_identifier": (r"property\s+(?:id|identifier|survey\s+number)|survey\s+number", "text"),
        "registration_number": (r"registration\s+(?:no|number)|document\s+number", "text"),
        "buyer_name": (r"buyer(?:\s+name)?|purchaser(?:\s+name)?", "text"),
        "seller_name": (r"seller(?:\s+name)?|vendor(?:\s+name)?|builder\s+name", "text"),
        "loan_amount": (r"requested\s+loan\s+amount|loan\s+amount|principal\s+amount", "number"),
        "down_payment": (r"down\s+payment|applicant\s+contribution", "number"),
        "loan_purpose": (r"loan\s+purpose|purpose\s+of\s+loan", "text"),
        "loan_type": (r"loan\s+type|mortgage\s+type", "text"),
        "loan_tenure": (r"loan\s+tenure|tenure|loan\s+term", "text"),
        "interest_rate": (r"interest\s+rate|rate\s+of\s+interest", "text"),
        "emi_amount": (r"emi|monthly\s+instalment|monthly\s+installment", "number"),
        "fees_charges": (r"fees\s+and\s+charges|processing\s+fee|total\s+charges", "text"),
        "agreement_date": (r"agreement\s+date|execution\s+date", "text"),
        # Do not also classify the "Date of Birth" label as a generic document date.
        "document_date": (r"document\s+date|statement\s+date|report\s+date|date(?!\s+of\s+birth)", "text"),
        "identity_document_type": (r"identity\s+document\s+type|id\s+proof\s+type", "text"),
        "identity_document_number": (r"aadhaar\s+(?:number|no)|pan\s+(?:number|no)|passport\s+(?:number|no)|voter\s+id\s+(?:number|no)|identity\s+number", "text"),
    }
    source = text or ""
    result = {}
    for key, (labels, value_type) in specs.items():
        if key == "residential_address" and category == "KYC":
            labels += r"|address"
        if key == "property_address" and category in {"Sale / Purchase Agreement", "Property Title", "Property Valuation", "Mortgage Application"}:
            labels += r"|address|location"
        pattern = rf"(?im)^[ \t]*(?:{labels})[ \t]*(?::[ \t]*|[ \t]*\n[ \t]*)(?P<value>[^\r\n]+)"
        matches = list(re.finditer(pattern, source))
        values = []
        for match in matches:
            raw = " ".join(match.group("value").strip().split())
            if not raw or raw.startswith("[") and raw.endswith("]"):
                continue
            if value_type == "number":
                number = re.search(r"-?[\d][\d,]*(?:\.\d+)?", raw)
                if not number:
                    continue
                try:
                    value = float(number.group(0).replace(",", ""))
                except ValueError:
                    continue
            else:
                value = raw[:400]
            preceding = source[:match.start()]
            page_matches = list(re.finditer(r"(?im)^\s*\[PAGE\s+(\d+)\]\s*$", preceding))
            values.append({"value": value, "evidence": match.group(0)[:300], "page_number": int(page_matches[-1].group(1)) if page_matches else None})
        # Email and IFSC can be identified without a printed label.
        if key == "email" and not values:
            for match in re.finditer(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", source):
                preceding = source[:match.start()]
                pages = list(re.finditer(r"(?im)^\s*\[PAGE\s+(\d+)\]\s*$", preceding))
                values.append({"value": match.group(0), "evidence": match.group(0), "page_number": int(pages[-1].group(1)) if pages else None})
        if key == "ifsc" and not values:
            for match in re.finditer(r"(?i)\b[A-Z]{4}0[A-Z0-9]{6}\b", source):
                preceding = source[:match.start()]
                pages = list(re.finditer(r"(?im)^\s*\[PAGE\s+(\d+)\]\s*$", preceding))
                values.append({"value": match.group(0).upper(), "evidence": match.group(0), "page_number": int(pages[-1].group(1)) if pages else None})
        if values:
            first = values[0]
            result[key] = {"value": first["value"], "source": "OCR", "evidence": first["evidence"], "page_number": first["page_number"]}
            if len(values) > 1:
                result[key]["alternates"] = values[1:]
    return result

EDITABLE={"DRAFT","DOCUMENTS_REQUESTED","ADDITIONAL_INFORMATION_REQUIRED"}
MEDIA={".pdf":"application/pdf",".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".tif":"image/tiff",".tiff":"image/tiff"}
def owned(db,aid,cid,writable=False):
    a=db.scalar(select(MortgageApplication).where(MortgageApplication.id==aid,MortgageApplication.customer_id==cid))
    if not a: raise HTTPException(404,"Application not found.")
    if writable and a.status not in EDITABLE: raise HTTPException(409,"Documents can only be changed while the application is a draft or additional information has been requested.")
    return a
def _analysis_state(d):
    """Accurate per-document state; ANALYSED turns NEEDS_REANALYSIS once the OCR/corrected text has changed."""
    st=d.analysis_status or "NOT_ANALYSED"
    if st=="ANALYSED":
        from app.routers.ai import _input_hash
        if d.analysis_input_hash!=_input_hash(d): return "NEEDS_REANALYSIS"
    return st
def out(d):
    return {"id":d.id,"application_id":d.application_id,"category":d.category,"category_label":CATEGORY_LABELS.get(d.category,d.category),"original_filename":d.original_filename,"content_type":d.content_type,"size_bytes":d.size_bytes,"extracted_text":d.extracted_text,"edited_text":d.edited_text,"extracted_fields":_json(getattr(d,"extracted_fields_json","{}"),{}),"corrected_fields":_json(getattr(d,"corrected_fields_json","{}"),{}),"field_correction_history":_json(getattr(d,"field_correction_history_json","[]"),[]),"extraction_status":d.extraction_status,"extraction_message":d.extraction_message,"category_check":{"status":d.category_match_status or "UNVERIFIED","selected_category":d.category_selected_at_upload or d.category,"detected_category":d.detected_category,"matches_selected_category":True if d.category_match_status=="MATCH" else False if d.category_match_status=="MISMATCH_PENDING" else None,"confidence":d.category_match_confidence,"reason":d.category_match_reason or ""},"category_match_status":d.category_match_status or "UNVERIFIED","detected_category":d.detected_category,"category_match_confidence":d.category_match_confidence,"category_match_reason":d.category_match_reason or "","verification_status":d.verification_status,"verified_by":d.verified_by,"verified_at":d.verified_at.isoformat() if d.verified_at else None,"verification_note":d.verification_note,"analysis_status":_analysis_state(d),"analysis_error":d.analysis_error or "","analysis_duration_ms":d.analysis_duration_ms,"analysis_completed_at":d.analysis_completed_at.isoformat() if d.analysis_completed_at else None,"analysis_result":_json(d.analysis_result_json,{}) if d.analysis_status=="ANALYSED" else None,"created_at":d.created_at.isoformat()}
def stored_path(d):
    folder=Path(settings.uploads_dir).resolve();p=(folder/d.stored_filename).resolve()
    if folder not in p.parents or not p.is_file(): raise HTTPException(404,"Stored file is unavailable.")
    return p
def file_response(d):
    return FileResponse(stored_path(d),media_type=MEDIA.get(Path(d.stored_filename).suffix.lower(),"application/octet-stream"),filename=d.original_filename,headers={"X-Content-Type-Options":"nosniff","Cache-Control":"private, no-store","Content-Security-Policy":"default-src 'none'"})
@router.get("/{aid}/documents")
def listing(aid:int,db:Session=Depends(get_db),u:Customer=Depends(current_customer)):
    owned(db,aid,u.id);return [out(d) for d in db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id==aid).order_by(ApplicationDocument.id)).all()]
@router.post("/{aid}/documents")
async def upload(aid:int,category:str=Form(...),file:UploadFile=File(...),db:Session=Depends(get_db),u:Customer=Depends(current_customer)):
    app_row=owned(db,aid,u.id,writable=True);ext=Path(file.filename or "").suffix.lower()
    if category not in CATEGORIES: raise HTTPException(422,"Unsupported document category.")
    if ext not in SUPPORTED: raise HTTPException(415,"Supported formats: PDF, PNG, JPG, JPEG, TIF, TIFF.")
    limit=settings.max_upload_size_mb*1024*1024;data=await file.read(limit+1)
    if not data: raise HTTPException(400,"Uploaded file is empty.")
    if len(data)>limit: raise HTTPException(413,f"File exceeds {settings.max_upload_size_mb} MB.")
    if ext==".pdf" and not data.startswith(b"%PDF"): raise HTTPException(415,"Invalid PDF signature.")
    if ext!=".pdf":
        try: Image.open(io.BytesIO(data)).verify()
        except Exception: raise HTTPException(415,"Invalid image file.")
    folder=Path(settings.uploads_dir).resolve();folder.mkdir(parents=True,exist_ok=True)
    stored=secrets.token_hex(16)+ext;(folder/stored).write_bytes(data)
    text,status,msg=await run_in_threadpool(extract_text,folder/stored)  # OCR is CPU-bound; keep the event loop free
    existing=db.scalar(select(ApplicationDocument).where(ApplicationDocument.application_id==aid,ApplicationDocument.original_filename==Path(file.filename or "upload").name[:255],ApplicationDocument.size_bytes==len(data)))
    fields=_structured_fields(text,category)
    category_check={"status":"UNVERIFIED","selected_category":category,"detected_category":None,"matches_selected_category":None,"confidence":None,"reason":""}
    if len((text or "").strip()) < MIN_CATEGORY_TEXT_CHARS:
        category_check["reason"]="There is not enough readable text to check the document category. Review the file or its OCR text and confirm the selected category manually."
    else:
        try:
            result=await classify_document_category(text,category,sorted(CATEGORIES))
            if result:
                category_check=result
            else:
                category_check["reason"]="The document category check returned an uncertain result. Review the document and confirm the selected category manually."
        except Exception as error:
            logger.warning("Document category check unavailable (%s).",type(error).__name__)
            category_check["reason"]="Automatic category checking is unavailable. Review the document and confirm the selected category manually."
    d=ApplicationDocument(application_id=aid,category=category,original_filename=Path(file.filename or "upload").name[:255],stored_filename=stored,content_type=file.content_type or "application/octet-stream",size_bytes=len(data),extracted_text=text,extraction_status=status,extraction_message=(msg+(" Possible duplicate filename/size detected; verify before relying on it." if existing else "")),category_match_status=category_check["status"],category_selected_at_upload=category,detected_category=category_check.get("detected_category"),category_match_confidence=category_check.get("confidence"),category_match_reason=category_check.get("reason", ""),extracted_fields_json=json.dumps(fields),corrected_fields_json="{}",field_correction_history_json="[]")
    db.add(d);db.flush()
    if category=="KYC" and app_row.kyc_status=="VERIFIED":  # new unreviewed KYC evidence invalidates the earlier attestation
        app_row.kyc_status="PENDING";app_row.kyc_note="Reset: a new KYC document was uploaded after KYC was verified."
    record(db,u.email,"CUSTOMER","DOCUMENT_UPLOADED","document",d.id,f"application={aid} category={category} status={status}")
    db.add(CustomerNotification(customer_id=u.id,application_id=aid,title="Document uploaded",message=f"{CATEGORY_LABELS.get(category,category)} was uploaded. Extraction status: {status}.",event_type="DOCUMENT_UPLOADED"))
    db.commit();db.refresh(d)
    if text.strip() and d.category_match_status!="MISMATCH_PENDING":
        rag_indexing=await index_document(db,d)
    else:
        rag_indexing={"document_id":d.id,"chunks":0,"embedded":0,"embedding_status":"category_mismatch_pending" if d.category_match_status=="MISMATCH_PENDING" else "no_extracted_text"}
    return {**out(d),"rag_indexing":rag_indexing}
@router.put("/{aid}/documents/{did}/category")
async def confirm_document_category(aid:int,did:int,payload:CategoryConfirmationIn,db:Session=Depends(get_db),u:Customer=Depends(current_customer)):
    owned(db,aid,u.id,writable=True)
    document=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not document: raise HTTPException(404,"Document not found.")
    if payload.confirm is not True: raise HTTPException(422,"Explicit category confirmation is required.")
    if payload.category not in CATEGORIES: raise HTTPException(422,"Unsupported document category.")
    if document.category_match_status=="MISMATCH_PENDING":
        if payload.category!=document.detected_category:
            raise HTTPException(409,"Choose the detected category or replace the uploaded file before continuing.")
    elif document.category_match_status=="UNVERIFIED":
        if payload.category!=document.category:
            raise HTTPException(409,"An unverified category check can only confirm the category selected during upload.")
    else:
        raise HTTPException(409,"This document category has already been confirmed or does not require confirmation.")
    previous=document.category
    document.category=payload.category
    document.category_match_status="CONFIRMED_BY_CUSTOMER"
    document.extracted_fields_json=json.dumps(_structured_fields(document.extracted_text or "",document.category))
    record(db,u.email,"CUSTOMER","DOCUMENT_CATEGORY_CONFIRMED","document",document.id,f"application={aid}; previous={previous}; confirmed={document.category}")
    db.commit();db.refresh(document)
    await index_document(db,document)
    return out(document)


@router.put("/{aid}/documents/{did}/text")
async def edit(aid:int,did:int,payload:DocumentTextEditIn,db:Session=Depends(get_db),u:Customer=Depends(current_customer)):
    app_row=owned(db,aid,u.id,writable=True)
    d=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not d: raise HTTPException(404,"Document not found.")
    d.edited_text=payload.edited_text  # extracted_text (original OCR evidence) is intentionally untouched
    if d.verification_status=="VERIFIED":  # changed evidence must be re-verified
        d.verification_status="PENDING";d.verification_note="Reset: extracted text was edited after verification."
        if d.category=="KYC" and app_row.kyc_status=="VERIFIED": app_row.kyc_status="PENDING";app_row.kyc_note="Reset: KYC document text was edited after KYC was verified."
    record(db,u.email,"CUSTOMER","DOCUMENT_TEXT_EDITED","document",d.id,f"application={aid} chars={len(payload.edited_text)}")
    # Keep extracted_fields_json immutable: editing the OCR text must not overwrite original extracted values.
    db.add(CustomerNotification(customer_id=u.id,application_id=aid,title="Extracted text corrected",message="Your correction was saved separately; original OCR evidence is preserved.",event_type="DOCUMENT_CORRECTED"))
    db.commit();db.refresh(d)
    rag_indexing=await index_document(db,d)
    return {**out(d),"rag_indexing":rag_indexing}

@router.put("/{aid}/documents/{did}/fields")
def edit_fields(aid:int,did:int,payload:DocumentFieldsEditIn,db:Session=Depends(get_db),u:Customer=Depends(current_customer)):
    app_row=owned(db,aid,u.id,writable=True)
    d=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not d: raise HTTPException(404,"Document not found.")
    original=_json(d.extracted_fields_json,{})
    current=_json(d.corrected_fields_json,{})
    history=_json(d.field_correction_history_json,[])
    allowed=set(original.keys()) | set(current.keys())
    if any(k not in allowed for k in payload.corrected_fields):
        raise HTTPException(422,"Only fields extracted from this document can be corrected.")
    now=datetime.now(timezone.utc).isoformat()
    for key,value in payload.corrected_fields.items():
        before=current.get(key,{}).get("value", original.get(key,{}).get("value"))
        current[key]={"value":value,"source":"CUSTOMER_CORRECTION","original_value":original.get(key,{}).get("value"),"edited":value != original.get(key,{}).get("value")}
        if value != before:
            history.append({"field":key,"previous_value":before,"original_ocr_value":original.get(key,{}).get("value"),"corrected_value":value,"actor_customer_id":u.id,"changed_at":now,"reason":payload.reason})
    d.corrected_fields_json=json.dumps(current)
    d.field_correction_history_json=json.dumps(history[-200:])
    if d.verification_status=="VERIFIED":
        d.verification_status="PENDING";d.verification_note="Reset: structured OCR fields were corrected after verification."
        if d.category=="KYC" and app_row.kyc_status=="VERIFIED": app_row.kyc_status="PENDING";app_row.kyc_note="Reset: KYC fields were corrected after verification."
    record(db,u.email,"CUSTOMER","DOCUMENT_FIELDS_CORRECTED","document",d.id,f"application={aid} fields={','.join(payload.corrected_fields.keys())}")
    db.add(CustomerNotification(customer_id=u.id,application_id=aid,title="Extracted fields updated",message="Your field corrections were saved. Original OCR values remain available for review.",event_type="DOCUMENT_CORRECTED"))
    db.commit();db.refresh(d);return out(d)
@router.get("/{aid}/documents/{did}/file")
def download(aid:int,did:int,db:Session=Depends(get_db),u:Customer=Depends(current_customer)):
    owned(db,aid,u.id)
    d=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not d: raise HTTPException(404,"Document not found.")
    record(db,u.email,"CUSTOMER","DOCUMENT_DOWNLOADED","document",d.id,f"application={aid}");db.commit();return file_response(d)

@router.delete("/{aid}/documents/{did}")
def remove_document(aid:int,did:int,db:Session=Depends(get_db),u:Customer=Depends(current_customer)):
    owned(db,aid,u.id,writable=True)
    d=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not d: raise HTTPException(404,"Document not found.")
    path=stored_path(d)
    record(db,u.email,"CUSTOMER","DOCUMENT_REMOVED","document",d.id,f"application={aid} category={d.category}")
    db.execute(delete(ApplicationDocumentChunk).where(ApplicationDocumentChunk.document_id==d.id))
    db.delete(d);db.commit()
    path.unlink(missing_ok=True)
    return {"id":did,"deleted":True}


@router.get("/{aid}/receipt.pdf")
def receipt(aid:int,db:Session=Depends(get_db),u:Customer=Depends(current_customer)):
    app=owned(db,aid,u.id)
    if app.status=="DRAFT": raise HTTPException(409,"Submit the application before downloading the submission receipt.")
    docs=db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id==aid).order_by(ApplicationDocument.category,ApplicationDocument.id)).all()
    customer=db.get(Customer,app.customer_id)
    pdf=fitz.open();page=pdf.new_page(width=595,height=842)
    y=54
    lines=["TCS MORTGAGE AI — APPLICATION RECEIPT", "", f"Reference: {app.reference}", f"Customer: {customer.full_name if customer else 'Unavailable'}", f"Customer email: {customer.email if customer else 'Unavailable'}", f"Status: {app.status}", f"KYC status: {app.kyc_status or 'PENDING'}", f"Lender: {app.lender_name}", f"Product: {app.product_name or 'Not specified'}", f"Requested loan: INR {app.requested_loan:,.2f}", f"Declared property value: INR {app.property_value:,.2f}", f"Submitted at: {app.submitted_at.isoformat() if app.submitted_at else 'Not recorded'}", "", "DOCUMENT CHECKLIST"]
    for line in lines:
        page.insert_text((48,y),line,fontname="helv",fontsize=14 if y==54 else 10,color=(0.12,0.16,0.20));y+=22 if y==54 else 17
    for d in docs:
        line=f"- {d.category}: {d.original_filename} | OCR: {d.extraction_status} | Verification: {d.verification_status}"
        if y>780: page=pdf.new_page(width=595,height=842);y=54
        page.insert_textbox(fitz.Rect(48,y,550,y+30),line,fontname="helv",fontsize=9,color=(0.12,0.16,0.20));y+=30
    if y>770: page=pdf.new_page(width=595,height=842);y=54
    page.insert_textbox(fitz.Rect(48,y+12,550,y+72),"This receipt confirms application submission details and uploaded-document metadata only. It is not a loan sanction or approval. Verify all extracted data and contact the bank for official status.",fontname="helv",fontsize=8,color=(0.3,0.3,0.3))
    data=pdf.tobytes();pdf.close()
    record(db,u.email,"CUSTOMER","APPLICATION_RECEIPT_DOWNLOADED","application",aid,app.reference);db.commit()
    return Response(content=data,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{app.reference}-receipt.pdf"',"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})
