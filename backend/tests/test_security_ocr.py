import re, time
import pytest

def test_password_hash_roundtrip():
    from app.security import hash_password, verify_password
    h = hash_password("CorrectHorse-Battery1")
    assert h != "CorrectHorse-Battery1" and verify_password("CorrectHorse-Battery1", h)
    assert not verify_password("wrong", h) and not verify_password("x", "garbage")

def test_jwt_roles_and_tamper():
    from app.security import token_for, token_subject
    t = token_for(7); assert token_subject(t) == "7"
    assert token_subject(token_for("admin:3")) == "admin:3"
    assert token_subject(t[:-2] + "xx") is None and token_subject("not-a-token") is None

def test_lockout():
    from app.security import is_locked, note_failure, clear_failures
    k = "t:" + str(time.time())
    for _ in range(5): note_failure(k)
    assert is_locked(k); clear_failures(k); assert not is_locked(k)

def test_otp_pattern_accepts_six_digits():
    pytest.importorskip("email_validator")
    from app.schemas import OTPIn
    assert OTPIn(email="a@b.com", code="123456").code == "123456"
    with pytest.raises(Exception): OTPIn(email="a@b.com", code="12345a")

def test_production_requires_strong_secret():
    from app.config import Settings, validate_runtime
    with pytest.raises(RuntimeError): validate_runtime(Settings(environment="production", jwt_secret_key="development-only-change-me"))
    validate_runtime(Settings(environment="production", jwt_secret_key="x" * 40, pbkdf2_iterations=600_000, admin_otp_required=False, smtp_host="smtp.example.com"))

def _png_with_text(path, text):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 260), "white"); ImageDraw.Draw(img).text((30, 90), text, fill="black", font=ImageFont.load_default(size=44)); img.save(path)

def test_image_ocr_tesseract(tmp_path):
    pytest.importorskip("pytesseract")
    import shutil; 
    if not shutil.which("tesseract"): pytest.skip("tesseract binary not installed")
    from app.services.ocr import extract_text
    p = tmp_path / "scan.png"; _png_with_text(p, "Property value INR 4500000")
    text, status, msg = extract_text(p)
    assert status == "COMPLETED" and "4500000" in text.replace(",", "").replace(" ", "")

def test_unsupported_extension(tmp_path):
    from app.services.ocr import extract_text
    p = tmp_path / "x.exe"; p.write_bytes(b"x")
    assert extract_text(p)[1] == "UNSUPPORTED"
