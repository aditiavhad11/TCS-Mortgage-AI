"""Send ONE real test email with the SMTP settings from backend/.env.  Usage: python scripts/test_smtp.py you@example.com"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.config import settings
from app.services.mailer import send_email, smtp_configured, OTPDeliveryError
if len(sys.argv) != 2: sys.exit("Usage: python scripts/test_smtp.py recipient@example.com")
if not smtp_configured(): sys.exit("SMTP_HOST is empty in backend/.env - OTPs will only print to the console.")
try:
    send_email(sys.argv[1], f"{settings.app_name}: SMTP test", "SMTP is configured correctly. OTP emails will be delivered.")
    print(f"OK: test email sent to {sys.argv[1]} via {settings.smtp_host}:{settings.smtp_port}")
except OTPDeliveryError as e:
    sys.exit(f"FAILED: {e}")
