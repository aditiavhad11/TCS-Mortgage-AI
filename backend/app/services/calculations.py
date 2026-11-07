def emi_monthly(principal, annual_rate_percent, tenure_years):
    if principal<=0 or tenure_years<=0: return 0.0
    n=tenure_years*12; r=annual_rate_percent/1200
    if r==0: return round(principal/n,2)
    f=(1+r)**n
    return round(principal*r*f/(f-1),2)
def estimate_metrics(property_value,requested_loan,annual_income,monthly_debt,annual_rate_percent,tenure_years):
    emi=emi_monthly(requested_loan,annual_rate_percent,tenure_years)
    ltv=requested_loan/property_value*100 if property_value>0 else None
    monthly_income=annual_income/12 if annual_income>0 else 0
    dti=(monthly_debt+emi)/monthly_income*100 if monthly_income>0 else None
    return {"estimated_monthly_emi_inr":round(emi,2),"loan_to_value_percent":round(ltv,2) if ltv is not None else None,"debt_to_income_percent":round(dti,2) if dti is not None else None,"disclaimer":"Illustrative estimates only; not a credit decision or loan approval."}

def format_inr(value, decimals=0):
    """Format a number in Indian digit grouping with the rupee sign, e.g. 1234567 -> ₹12,34,567."""
    if value is None: return "—"
    v=round(float(value),decimals);neg=v<0;whole,_,frac=f"{abs(v):.{decimals}f}".partition(".")
    if len(whole)>3:
        head,tail=whole[:-3],whole[-3:];groups=[]
        while len(head)>2: groups.insert(0,head[-2:]);head=head[:-2]
        if head: groups.insert(0,head)
        whole=",".join(groups+[tail])
    return ("-" if neg else "")+"₹"+whole+("."+frac if decimals else "")
