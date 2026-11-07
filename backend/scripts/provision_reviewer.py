"""Create a reviewer login for local development. Run from backend after activating venv.
Usage: python scripts/provision_reviewer.py --name "Review User" --email reviewer@example.com --bank BANK-DEMO
Prompts securely for password. This script creates no public reviewer-registration endpoint.
"""
import argparse, getpass, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.database import Base, engine, SessionLocal
from app.models import Reviewer
from app.security import hash_password
from app.config import MIN_PASSWORD_LENGTH
p=argparse.ArgumentParser(); p.add_argument('--name',required=True); p.add_argument('--email',required=True); p.add_argument('--bank',required=True); args=p.parse_args()
pw=getpass.getpass(f'Reviewer password (min {MIN_PASSWORD_LENGTH} chars): ')
if len(pw)<MIN_PASSWORD_LENGTH: raise SystemExit(f'Password must contain at least {MIN_PASSWORD_LENGTH} characters.')
Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
 email=args.email.strip().lower()
 if db.scalar(select(Reviewer).where(Reviewer.email==email)): raise SystemExit('Reviewer email already exists.')
 row=Reviewer(full_name=args.name.strip(),email=email,bank_code=args.bank.strip(),password_hash=hash_password(pw),is_active=True)
 db.add(row); db.commit(); print(f'Reviewer created: {email} | bank={args.bank}')
