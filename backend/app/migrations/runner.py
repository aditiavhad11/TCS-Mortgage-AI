"""Minimal additive migration runner for SQLite and PostgreSQL-compatible schemas.
Never drops tables, columns, or user data. New tables are created by SQLAlchemy metadata.
"""
from sqlalchemy import inspect, text
from app.database import engine

def run_migrations():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    additions = {
        "mortgage_applications": [("bank_id", "INTEGER"), ("kyc_status", "VARCHAR(30) DEFAULT 'PENDING'"), ("kyc_verified_by", "VARCHAR(255)"), ("kyc_verified_at", "DATETIME"), ("kyc_note", "TEXT DEFAULT ''"), ("form_data_json", "TEXT DEFAULT '{}'"), ("consents_json", "TEXT DEFAULT '{}'"), ("awaiting_assignment", "BOOLEAN DEFAULT 0"), ("assignment_attempts", "INTEGER DEFAULT 0"), ("last_assignment_attempt_at", "DATETIME"), ("archived_at", "DATETIME")],
        "banks": [("contact_person", "VARCHAR(160) DEFAULT ''"), ("contact_phone", "VARCHAR(30) DEFAULT ''"), ("address", "TEXT DEFAULT ''"), ("license_number", "VARCHAR(80) DEFAULT ''"), ("institution_type", "VARCHAR(40) DEFAULT 'Other'"), ("ifsc_code", "VARCHAR(11) DEFAULT ''"), ("rejection_reason", "TEXT DEFAULT ''"), ("decided_by", "VARCHAR(255)"), ("decided_at", "DATETIME")],
        "customers": [("is_active", "BOOLEAN DEFAULT 1"), ("created_at", "DATETIME")],
        "admin_notifications": [("deleted_at", "DATETIME")],
        "verification_codes": [("created_at", "DATETIME")],
        "reviewers": [("bank_id", "INTEGER"), ("specialisation", "VARCHAR(60) DEFAULT 'GENERAL_MORTGAGE_REVIEW'"), ("max_active_assignments", "INTEGER DEFAULT 10"), ("is_available", "BOOLEAN DEFAULT 1"), ("last_assigned_at", "DATETIME")],
        "policy_documents": [("bank_id", "INTEGER"), ("customer_visible", "BOOLEAN DEFAULT 0"), ("customer_summary", "TEXT DEFAULT ''"), ("source_filename", "VARCHAR(255)"), ("stored_filename", "VARCHAR(255)")],
        "policy_chunks": [("audience", "VARCHAR(20) DEFAULT 'INTERNAL'"), ("page_number", "INTEGER")],
        "application_documents": [("verification_status", "VARCHAR(30) DEFAULT 'PENDING'"), ("verified_by", "VARCHAR(255)"), ("verified_at", "DATETIME"), ("verification_note", "TEXT DEFAULT ''"), ("extracted_fields_json", "TEXT DEFAULT '{}'"), ("corrected_fields_json", "TEXT DEFAULT '{}'"), ("field_correction_history_json", "TEXT DEFAULT '[]'"), ("analysis_status", "VARCHAR(20) DEFAULT 'NOT_ANALYSED'"), ("analysis_result_json", "TEXT DEFAULT '{}'"), ("analysis_error", "TEXT DEFAULT ''"), ("analysis_input_hash", "VARCHAR(64) DEFAULT ''"), ("analysis_started_at", "DATETIME"), ("analysis_completed_at", "DATETIME"), ("analysis_duration_ms", "INTEGER"), ("category_match_status", "VARCHAR(30) DEFAULT 'UNVERIFIED'"), ("category_selected_at_upload", "VARCHAR(80)"), ("detected_category", "VARCHAR(80)"), ("category_match_confidence", "FLOAT"), ("category_match_reason", "TEXT DEFAULT ''")],
    }
    with engine.begin() as conn:
        for table, cols in additions.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in inspect(conn).get_columns(table)}
            for name, typ in cols:
                if name not in existing:
                    # Nullable columns preserve all existing rows. Foreign key enforcement for
                    # legacy SQLite tables is handled at application authorization boundaries.
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
        if "banks" in tables:
            bank_columns = {c["name"] for c in inspect(conn).get_columns("banks")}
            for column, index_name in (("name", "uq_banks_normalized_name"), ("contact_email", "uq_banks_normalized_contact_email")):
                if column not in bank_columns:
                    continue
                duplicate_groups = conn.execute(text(f"SELECT COUNT(*) FROM (SELECT lower(trim({column})) value FROM banks WHERE trim({column}) <> '' GROUP BY lower(trim({column})) HAVING COUNT(*) > 1)")).scalar_one()
                if not duplicate_groups:
                    conn.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON banks (lower(trim({column}))) WHERE trim({column}) <> ''"))
        # Existing records are intentionally not auto-mapped to a bank based on fuzzy names.
        # Platform Admin can approve/create banks; legacy records remain nullable until reviewed.
        if "mortgage_applications" in tables:
            # Legacy schemas may not have a status column. Only run this backfill when
            # both referenced columns exist; adding nullable columns above preserves rows.
            app_columns = {c["name"] for c in inspect(conn).get_columns("mortgage_applications")}
            if "archived_at" in app_columns:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mortgage_applications_archived_at ON mortgage_applications (archived_at)"))
            if {"status", "awaiting_assignment"}.issubset(app_columns):
                conn.execute(text("UPDATE mortgage_applications SET awaiting_assignment = 1 WHERE status = 'PENDING_ASSIGNMENT' AND (awaiting_assignment IS NULL OR awaiting_assignment = 0)"))
