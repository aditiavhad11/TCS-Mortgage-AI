"""Text extraction: embedded PDF text (PyMuPDF) per page, Tesseract OCR for scanned pages / images.

Original OCR output is stored in ApplicationDocument.extracted_text and is never overwritten;
customer corrections live in edited_text.
"""
from pathlib import Path
import io
from PIL import Image, ImageSequence
import pytesseract
from app.config import settings
SUPPORTED={".pdf",".png",".jpg",".jpeg",".tif",".tiff"}
MIN_PAGE_TEXT=30       # fewer characters than this on a PDF page => treat page as scanned
MAX_CHARS=1000000

def _ocr_image(img: Image.Image) -> str:
    if img.mode not in ("RGB","L"): img=img.convert("RGB")
    return pytesseract.image_to_string(img).strip()

def extract_text(path:Path):
    """Return (text, status, message). status: COMPLETED | NEEDS_REVIEW | FAILED | UNSUPPORTED."""
    path=Path(path);ext=path.suffix.lower()
    if ext not in SUPPORTED: return "","UNSUPPORTED","Unsupported file type."
    if settings.tesseract_cmd: pytesseract.pytesseract.tesseract_cmd=settings.tesseract_cmd
    try:
        if ext==".pdf":
            import fitz  # PyMuPDF (imported lazily so image OCR works without it)
            doc=fitz.open(path)
            if doc.needs_pass:
                doc.close()
                return "","NEEDS_REVIEW","This PDF is password-protected. Upload an unencrypted PDF to extract its policy text."
            parts=[];embedded=ocr_pages=0;ocr_error=None
            for i,page in enumerate(doc):
                if i>=settings.ocr_max_pages: parts.append(f"[Pages beyond {settings.ocr_max_pages} were not processed]");break
                t=page.get_text("text").strip()
                if len(t)>=MIN_PAGE_TEXT: parts.append(f"[PAGE {i+1}]\n{t}");embedded+=1;continue
                try:
                    pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
                    o=_ocr_image(Image.open(io.BytesIO(pix.tobytes("png"))));ocr_pages+=1
                    parts.append(f"[PAGE {i+1}]\n{o or t}" if (o or t) else "")
                except Exception as e: ocr_error=type(e).__name__;parts.append(t)
            text="\n\n".join(x for x in parts if x).strip()
            if not text: return "","NEEDS_REVIEW",("Scanned PDF OCR unavailable: "+ocr_error) if ocr_error else "No readable text found."
            msg=f"{embedded} page(s) from embedded text, {ocr_pages} page(s) via Tesseract OCR."
            status="COMPLETED"
            if ocr_error: status,msg="NEEDS_REVIEW",msg+f" Some pages could not be OCR'd ({ocr_error}); check Tesseract installation."
            return text[:MAX_CHARS],status,msg
        img=Image.open(path);frames=[]
        for i,fr in enumerate(ImageSequence.Iterator(img)):  # multi-page TIFF support
            if i>=settings.ocr_max_pages: break
            frames.append(f"[PAGE {i+1}]\n{_ocr_image(fr.copy())}")
        text="\n\n".join(f for f in frames if f).strip()
        return (text[:MAX_CHARS],"COMPLETED","Image processed using Tesseract.") if text else ("","NEEDS_REVIEW","No readable text found.")
    except pytesseract.TesseractNotFoundError: return "","NEEDS_REVIEW","Tesseract is not installed or TESSERACT_CMD is wrong; OCR unavailable."
    except Exception as e: return "","FAILED",f"Extraction failed: {type(e).__name__}: {str(e)[:150]}"
