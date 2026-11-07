"""Re-run the AUTOMATIC assignment engine for submitted applications (operations/support use).
Reviewers cannot be picked by hand: the engine selects an eligible, available same-bank reviewer by workload.
Run from backend:  python scripts/assign_application.py            # retry every application awaiting assignment
                   python scripts/assign_application.py --application-id 1
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import Base, engine, SessionLocal
from app.migrations.runner import run_migrations
from app.models import MortgageApplication
from app.services.assignment import auto_assign_application, retry_pending_assignments

p = argparse.ArgumentParser(); p.add_argument("--application-id", type=int); args = p.parse_args()
Base.metadata.create_all(bind=engine); run_migrations()
with SessionLocal() as db:
    if args.application_id:
        a = db.get(MortgageApplication, args.application_id)
        if not a: raise SystemExit("Application not found.")
        if a.status == "DRAFT": raise SystemExit("Draft applications are never assigned; the customer must submit first.")
        row = auto_assign_application(db, a); db.commit()
        print(f"{a.reference}: assigned to reviewer id {row.reviewer_id}" if row else f"{a.reference}: status {a.status} (no eligible reviewer yet)")
    else:
        n = retry_pending_assignments(db); db.commit(); print(f"Newly assigned: {n}")
