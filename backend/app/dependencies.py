from fastapi import Depends,HTTPException
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Customer
from app.security import token_subject
bearer=HTTPBearer(auto_error=False)
def current_customer(credentials:HTTPAuthorizationCredentials|None=Depends(bearer),db:Session=Depends(get_db)):
    if not credentials: raise HTTPException(401,"Authentication required.")
    subject=token_subject(credentials.credentials)
    # Customer tokens carry a bare numeric subject; reviewer/admin tokens ("reviewer:1", "admin:1") must never be accepted here.
    if not subject or not str(subject).isdigit(): raise HTTPException(401,"Invalid or expired access token.")
    customer=db.get(Customer,int(subject))
    if not customer or not customer.is_verified or not customer.is_active: raise HTTPException(401,"Verified active customer account required.")
    return customer
