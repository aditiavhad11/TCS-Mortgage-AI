import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.mkdtemp(prefix="mortgage_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("UPLOADS_DIR", f"{_tmp}/uploads")
os.environ["NVIDIA_API_KEY"] = ""          # unit/API tests must never hit the network
os.environ["ENVIRONMENT"] = "development"
os.environ["PBKDF2_ITERATIONS"] = "1000"      # fast hashing for tests only; production requires >= 210000
os.environ["ADMIN_OTP_REQUIRED"] = "false"    # legacy single-step admin login for older tests; OTP flow is covered in test_admin_otp_kyc.py
os.environ["JWT_SECRET_KEY"] = "unit-test-only-secret-key-at-least-32-bytes-long"
os.environ["SMTP_HOST"] = ""                # keep OTP tests isolated from real mail providers
os.environ["SMTP_PORT"] = "587"
os.environ["SMTP_USERNAME"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["SMTP_FROM"] = ""
os.environ["SMTP_USE_SSL"] = "false"
