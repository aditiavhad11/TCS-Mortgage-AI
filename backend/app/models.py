from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
def now(): return datetime.now(timezone.utc)
class Customer(Base):
    __tablename__="customers"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    full_name: Mapped[str]=mapped_column(String(160))
    email: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    mobile: Mapped[str]=mapped_column(String(30))
    password_hash: Mapped[str]=mapped_column(String(255))
    is_verified: Mapped[bool]=mapped_column(Boolean,default=False)
    is_active: Mapped[bool]=mapped_column(Boolean,default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    applications: Mapped[list["MortgageApplication"]]=relationship(back_populates="customer",cascade="all, delete-orphan")
class MortgageApplication(Base):
    __tablename__="mortgage_applications"
    bank_id: Mapped[int|None] = mapped_column(ForeignKey("banks.id"), nullable=True, index=True)
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    reference: Mapped[str]=mapped_column(String(24),unique=True,index=True)
    customer_id: Mapped[int]=mapped_column(ForeignKey("customers.id"),index=True)
    status: Mapped[str]=mapped_column(String(40),default="DRAFT")
    lender_name: Mapped[str]=mapped_column(String(160),default="")
    product_name: Mapped[str]=mapped_column(String(160),default="")
    property_address: Mapped[str]=mapped_column(Text,default="")
    property_value: Mapped[float]=mapped_column(Float,default=0)
    requested_loan: Mapped[float]=mapped_column(Float,default=0)
    annual_income: Mapped[float]=mapped_column(Float,default=0)
    monthly_debt: Mapped[float]=mapped_column(Float,default=0)
    interest_rate: Mapped[float]=mapped_column(Float,default=8.5)
    tenure_years: Mapped[int]=mapped_column(Integer,default=20)
    customer_notes: Mapped[str]=mapped_column(Text,default="")
    form_data_json: Mapped[str]=mapped_column(Text,default="{}")
    consents_json: Mapped[str]=mapped_column(Text,default="{}")
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
    submitted_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    # Reviewer-attested KYC outcome (no external identity-verification provider is integrated).
    kyc_status: Mapped[str]=mapped_column(String(30),default="PENDING")   # PENDING | VERIFIED | REJECTED | NEEDS_REVIEW
    kyc_verified_by: Mapped[str|None]=mapped_column(String(255),nullable=True)
    kyc_verified_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    kyc_note: Mapped[str]=mapped_column(Text,default="")
    # Automatic reviewer assignment bookkeeping. status PENDING_ASSIGNMENT == "Awaiting Reviewer Assignment".
    awaiting_assignment: Mapped[bool]=mapped_column(Boolean,default=False,index=True)
    assignment_attempts: Mapped[int]=mapped_column(Integer,default=0)
    last_assignment_attempt_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    archived_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True,index=True)
    customer: Mapped["Customer"]=relationship(back_populates="applications")
    documents: Mapped[list["ApplicationDocument"]]=relationship(back_populates="application",cascade="all, delete-orphan")
class ApplicationDocument(Base):
    __tablename__="application_documents"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    application_id: Mapped[int]=mapped_column(ForeignKey("mortgage_applications.id"),index=True)
    category: Mapped[str]=mapped_column(String(80))
    original_filename: Mapped[str]=mapped_column(String(255))
    stored_filename: Mapped[str]=mapped_column(String(255),unique=True)
    content_type: Mapped[str]=mapped_column(String(100))
    size_bytes: Mapped[int]=mapped_column(Integer)
    extracted_text: Mapped[str]=mapped_column(Text,default="")
    edited_text: Mapped[str|None]=mapped_column(Text,nullable=True)
    extracted_fields_json: Mapped[str]=mapped_column(Text,default="{}")
    corrected_fields_json: Mapped[str]=mapped_column(Text,default="{}")
    field_correction_history_json: Mapped[str]=mapped_column(Text,default="[]")
    extraction_status: Mapped[str]=mapped_column(String(40),default="PENDING")
    extraction_message: Mapped[str]=mapped_column(Text,default="")
    category_match_status: Mapped[str]=mapped_column(String(30),default="UNVERIFIED")
    category_selected_at_upload: Mapped[str|None]=mapped_column(String(80),nullable=True)
    detected_category: Mapped[str|None]=mapped_column(String(80),nullable=True)
    category_match_confidence: Mapped[float|None]=mapped_column(Float,nullable=True)
    category_match_reason: Mapped[str]=mapped_column(Text,default="")
    verification_status: Mapped[str]=mapped_column(String(30),default="PENDING")
    verified_by: Mapped[str|None]=mapped_column(String(255),nullable=True)
    verified_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    verification_note: Mapped[str]=mapped_column(Text,default="")
    analysis_status: Mapped[str]=mapped_column(String(20),default="NOT_ANALYSED")
    analysis_result_json: Mapped[str]=mapped_column(Text,default="{}")
    analysis_error: Mapped[str]=mapped_column(Text,default="")
    analysis_input_hash: Mapped[str]=mapped_column(String(64),default="")
    analysis_started_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    analysis_completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    analysis_duration_ms: Mapped[int|None]=mapped_column(Integer,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    application: Mapped["MortgageApplication"] = relationship(back_populates="documents")

class ApplicationDocumentChunk(Base):
    """Persistent, application-scoped OCR evidence chunks with optional NVIDIA embeddings."""
    __tablename__ = "application_document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "source_variant", "chunk_index"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("application_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    source_variant: Mapped[str] = mapped_column(String(40), default="ORIGINAL_OCR")
    source_filename: Mapped[str] = mapped_column(String(255))
    source_category: Mapped[str] = mapped_column(String(80))
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embed_model: Mapped[str] = mapped_column(String(120), default="")
class VerificationCode(Base):
    __tablename__="verification_codes"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    email: Mapped[str]=mapped_column(String(255),index=True)
    code_hash: Mapped[str]=mapped_column(String(255))
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    used: Mapped[bool]=mapped_column(Boolean,default=False)
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class PasswordResetToken(Base):
    __tablename__="password_reset_tokens"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    account_type: Mapped[str]=mapped_column(String(30),index=True)
    account_id: Mapped[int]=mapped_column(Integer,index=True)
    token_hash: Mapped[str]=mapped_column(String(64),unique=True,index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    used_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)


class Reviewer(Base):
    __tablename__ = "reviewers"
    bank_id: Mapped[int|None] = mapped_column(ForeignKey("banks.id"), nullable=True, index=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    bank_code: Mapped[str] = mapped_column(String(80), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    specialisation: Mapped[str] = mapped_column(String(60), default="GENERAL_MORTGAGE_REVIEW")
    max_active_assignments: Mapped[int] = mapped_column(Integer, default=10)
    # Self-service availability (e.g. on leave). Inactive/unavailable reviewers never receive new applications.
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    last_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ReviewerInvitation(Base):
    __tablename__ = "reviewer_invitations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("reviewers.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class ReviewAssignment(Base):
    __tablename__ = "review_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("mortgage_applications.id"), unique=True, index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("reviewers.id"), index=True)
    assigned_by: Mapped[str] = mapped_column(String(255), default="bootstrap")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ReviewEvent(Base):
    __tablename__ = "review_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("mortgage_applications.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("reviewers.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlatformAdmin(Base):
    __tablename__ = "platform_admins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_email: Mapped[str] = mapped_column(String(255), index=True)
    actor_role: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(100), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class PolicyDocument(Base):
    __tablename__ = "policy_documents"
    bank_id: Mapped[int|None] = mapped_column(ForeignKey("banks.id"), nullable=True, index=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    policy_version: Mapped[str] = mapped_column(String(80), default="1.0")
    category: Mapped[str] = mapped_column(String(100), default="General")
    content: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    customer_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    customer_summary: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str|None] = mapped_column(String(255), nullable=True)
    stored_filename: Mapped[str|None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PolicyChunk(Base):
    """Chunked policy text with an optional NVIDIA embedding (JSON list of floats) for vector search."""
    __tablename__ = "policy_chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policy_documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding_json: Mapped[str|None] = mapped_column(Text, nullable=True)
    embed_model: Mapped[str] = mapped_column(String(120), default="")
    audience: Mapped[str] = mapped_column(String(20), default="INTERNAL")
    page_number: Mapped[int|None] = mapped_column(Integer, nullable=True)


class Bank(Base):
    __tablename__ = "banks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    institution_type: Mapped[str] = mapped_column(String(40), default="Other")
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    contact_person: Mapped[str] = mapped_column(String(160), default="")
    contact_phone: Mapped[str] = mapped_column(String(30), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    license_number: Mapped[str] = mapped_column(String(80), default="")
    ifsc_code: Mapped[str] = mapped_column(String(11), default="")
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str|None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class BankDocument(Base):
    __tablename__ = "bank_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class BankAdmin(Base):
    __tablename__ = "bank_admins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    bank: Mapped["Bank"] = relationship()

class BankInvitation(Base):
    __tablename__ = "bank_invitations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("mortgage_applications.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    model_id: Mapped[str] = mapped_column(String(160), default="")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class CustomerNotification(Base):
    __tablename__ = "customer_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("mortgage_applications.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(80), default="INFO")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AdminNotification(Base):
    __tablename__="admin_notifications"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    fingerprint: Mapped[str]=mapped_column(String(180),unique=True,index=True)
    title: Mapped[str]=mapped_column(String(180))
    message: Mapped[str]=mapped_column(Text,default="")
    category: Mapped[str]=mapped_column(String(50),index=True)
    severity: Mapped[str]=mapped_column(String(20),default="INFO")
    resource_type: Mapped[str]=mapped_column(String(80),default="")
    resource_id: Mapped[str]=mapped_column(String(100),default="")
    read_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    deleted_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,index=True)


class AssignmentEvent(Base):
    __tablename__ = "assignment_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("mortgage_applications.id"), index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("reviewers.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReviewerNotification(Base):
    __tablename__ = "reviewer_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("reviewers.id"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("mortgage_applications.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(80), default="INFO")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class BankAdminNotification(Base):
    """Bank-scoped operational notification state; assignment events remain the immutable source."""
    __tablename__="bank_admin_notifications"
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    bank_id: Mapped[int]=mapped_column(ForeignKey("banks.id"),index=True)
    fingerprint: Mapped[str]=mapped_column(String(180),unique=True,index=True)
    title: Mapped[str]=mapped_column(String(180))
    message: Mapped[str]=mapped_column(Text,default="")
    category: Mapped[str]=mapped_column(String(50),index=True)
    severity: Mapped[str]=mapped_column(String(20),default="INFO")
    resource_type: Mapped[str]=mapped_column(String(80),default="application")
    resource_id: Mapped[str]=mapped_column(String(100),default="")
    read_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    archived_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,index=True)
