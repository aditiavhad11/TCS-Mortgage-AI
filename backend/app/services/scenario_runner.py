from sqlalchemy import select
from app.models import ApplicationDocument
from app.services.scenarios import run_scenario, SCENARIOS
APP_FIELDS=["property_value","requested_loan","annual_income","monthly_debt","interest_rate","tenure_years","lender_name","product_name"]
def run_for_application(db, app, name, body):
    """Uses the reviewer/customer-visible text (edited text if present, else original OCR) of the application's documents."""
    if name not in SCENARIOS: raise ValueError(f"Unknown scenario '{name}'. Use one of {list(SCENARIOS)}.")
    texts={}
    for d in db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id==app.id)).all():
        t=d.edited_text if d.edited_text is not None else d.extracted_text
        if t and t.strip(): texts.setdefault(d.category,[]).append(t)
    inputs=body.model_dump(); inputs["income_years"]=[y for y in inputs.get("income_years",[])]
    return run_scenario(name,{k:getattr(app,k) for k in APP_FIELDS},texts,inputs)
