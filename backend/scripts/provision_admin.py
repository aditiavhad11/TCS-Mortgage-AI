"""Provision the sole Platform Admin from backend/.env without a password."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, func
from app.database import Base, engine, SessionLocal
from app.models import PlatformAdmin
from app.config import settings

def main():
 email=settings.initial_admin_email.strip().casefold()
 if not email or "@" not in email:
  raise SystemExit("Set a valid INITIAL_ADMIN_EMAIL in backend/.env first.")
 Base.metadata.create_all(bind=engine)
 with SessionLocal() as db:
  row=db.scalar(select(PlatformAdmin).where(func.lower(PlatformAdmin.email) == email))
  if row:
   print("Configured Platform Admin already exists.")
   return
  db.add(PlatformAdmin(full_name=settings.initial_admin_name.strip() or "Platform Admin", email=email, password_hash="otp-only", is_active=True))
  db.commit()
  print("Configured Platform Admin provisioned.")
if __name__ == "__main__": main()
