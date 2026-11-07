from sqlalchemy import create_engine, text, inspect
from app.migrations import runner

def test_additive_migration_adds_nullable_columns_and_preserves_existing_rows(monkeypatch, tmp_path):
    old_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with old_engine.begin() as conn:
        conn.execute(text("CREATE TABLE mortgage_applications (id INTEGER PRIMARY KEY, reference TEXT)"))
        conn.execute(text("INSERT INTO mortgage_applications (id, reference) VALUES (1, 'OLD-REF')"))
        conn.execute(text("CREATE TABLE reviewers (id INTEGER PRIMARY KEY, email TEXT)"))
        conn.execute(text("CREATE TABLE banks (id INTEGER PRIMARY KEY, name TEXT, code TEXT, status TEXT, contact_email TEXT)"))
        conn.execute(text("INSERT INTO banks (id, name, code, status, contact_email) VALUES (1, 'Legacy Bank', 'LEGACY', 'APPROVED', 'ops@legacy.example')"))
        conn.execute(text("CREATE TABLE policy_documents (id INTEGER PRIMARY KEY, title TEXT)"))
        conn.execute(text("CREATE TABLE application_documents (id INTEGER PRIMARY KEY, category TEXT)"))
    monkeypatch.setattr(runner, "engine", old_engine)
    runner.run_migrations()
    cols = {c["name"] for c in inspect(old_engine).get_columns("mortgage_applications")}
    assert "bank_id" in cols
    assert {"kyc_status", "kyc_verified_by", "kyc_verified_at", "kyc_note"}.issubset(cols)
    with old_engine.connect() as conn:
        assert conn.execute(text("SELECT id, reference FROM mortgage_applications")).one() == (1, "OLD-REF")
        assert conn.execute(text("SELECT kyc_status, kyc_note FROM mortgage_applications WHERE id = 1")).one() == ("PENDING", "")  # legacy rows default to PENDING, never NULL
    assert "bank_id" in {c["name"] for c in inspect(old_engine).get_columns("reviewers")}
    assert "bank_id" in {c["name"] for c in inspect(old_engine).get_columns("policy_documents")}
    bank_cols = {c["name"] for c in inspect(old_engine).get_columns("banks")}
    assert {"institution_type", "ifsc_code"}.issubset(bank_cols)
    with old_engine.connect() as conn:
        assert conn.execute(text("SELECT name, code, status, institution_type, ifsc_code FROM banks WHERE id = 1")).one() == ("Legacy Bank", "LEGACY", "APPROVED", "Other", "")
    with old_engine.connect() as conn:
        indexes = set(conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='banks'")).scalars())
    assert {"uq_banks_normalized_name", "uq_banks_normalized_contact_email"}.issubset(indexes)
    assert {"verification_status", "verified_by", "verified_at", "verification_note"}.issubset({c["name"] for c in inspect(old_engine).get_columns("application_documents")})
    old_engine.dispose()


def test_migration_preserves_legacy_normalized_bank_duplicates(monkeypatch, tmp_path):
    old_engine = create_engine(f"sqlite:///{tmp_path / 'duplicate-banks.db'}")
    with old_engine.begin() as conn:
        conn.execute(text("CREATE TABLE banks (id INTEGER PRIMARY KEY, name TEXT, code TEXT, status TEXT, contact_email TEXT)"))
        conn.execute(text("INSERT INTO banks (id, name, code, status, contact_email) VALUES (1, 'Legacy Bank', 'LEGACY1', 'APPROVED', 'same@legacy.example')"))
        conn.execute(text("INSERT INTO banks (id, name, code, status, contact_email) VALUES (2, ' legacy bank ', 'LEGACY2', 'PENDING', 'SAME@LEGACY.EXAMPLE')"))
    monkeypatch.setattr(runner, "engine", old_engine)
    runner.run_migrations()
    with old_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM banks")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM sqlite_master WHERE type='index' AND name IN ('uq_banks_normalized_name','uq_banks_normalized_contact_email')")).scalar_one() == 0
    old_engine.dispose()
