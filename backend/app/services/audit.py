from app.models import AuditLog

def record(db, email: str, role: str, action: str, resource_type: str, resource_id="", detail: str = ""):
    """Add an audit row to the session; the caller commits. Never put document contents or secrets in detail."""
    db.add(AuditLog(actor_email=(email or "unknown")[:255], actor_role=role, action=action, resource_type=resource_type, resource_id=str(resource_id), detail=(detail or "")[:4000]))
