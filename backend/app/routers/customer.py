from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.database import get_db
from app.dependencies import current_customer
from app.models import Customer, CustomerNotification, MortgageApplication
from app.schemas import NotificationReadIn
from app.services.audit import record

router = APIRouter(tags=["Customer workspace"])

@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user: Customer = Depends(current_customer)):
    rows = db.scalars(select(CustomerNotification).where(CustomerNotification.customer_id == user.id).order_by(CustomerNotification.created_at.desc()).limit(100)).all()
    return [{"id": n.id, "application_id": n.application_id, "title": n.title, "message": n.message, "event_type": n.event_type,
             "read": n.read_at is not None, "created_at": n.created_at.isoformat()} for n in rows]

@router.patch("/notifications/{notification_id}")
def mark_notification(notification_id: int, data: NotificationReadIn, db: Session = Depends(get_db), user: Customer = Depends(current_customer)):
    n = db.scalar(select(CustomerNotification).where(CustomerNotification.id == notification_id, CustomerNotification.customer_id == user.id))
    if not n:
        raise HTTPException(404, "Notification not found.")
    n.read_at = datetime.now(timezone.utc) if data.read else None
    record(db, user.email, "CUSTOMER", "NOTIFICATION_READ" if data.read else "NOTIFICATION_UNREAD", "notification", n.id)
    db.commit()
    return {"id": n.id, "read": n.read_at is not None}

@router.delete("/notifications/{notification_id}")
def delete_notification(notification_id: int, db: Session = Depends(get_db), user: Customer = Depends(current_customer)):
    n = db.scalar(select(CustomerNotification).where(CustomerNotification.id == notification_id, CustomerNotification.customer_id == user.id))
    if not n:
        raise HTTPException(404, "Notification not found.")
    notification_id = n.id
    record(db, user.email, "CUSTOMER", "NOTIFICATION_DELETED", "notification", notification_id)
    db.delete(n)
    db.commit()
    return {"id": notification_id, "deleted": True}

@router.get("/customer/dashboard")
def customer_dashboard(db: Session = Depends(get_db), user: Customer = Depends(current_customer)):
    apps = db.scalars(select(MortgageApplication).where(MortgageApplication.customer_id == user.id)).all()
    notifications = db.scalars(select(CustomerNotification).where(CustomerNotification.customer_id == user.id, CustomerNotification.read_at.is_(None))).all()
    statuses = {}
    for app in apps:
        statuses[app.status] = statuses.get(app.status, 0) + 1
    return {"customer": {"id": user.id, "full_name": user.full_name, "email": user.email, "mobile": user.mobile, "is_verified": user.is_verified},
            "total_applications": len(apps), "status_counts": statuses,
            "draft_count": sum(1 for a in apps if a.status == "DRAFT"),
            "unread_notifications": len(notifications),
            "last_updated": max((a.updated_at.isoformat() for a in apps), default=None)}
