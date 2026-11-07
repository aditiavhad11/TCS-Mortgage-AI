"""Password hashing (PBKDF2-HMAC-SHA256), JWT (PyJWT) and simple login lockout.

New hashes use PBKDF2. Hashes created by earlier phases (scrypt, bcrypt) still verify, and
``needs_rehash`` lets login routes upgrade them transparently after a successful sign-in.
"""
import base64, hashlib, hmac, os, time
from datetime import datetime, timedelta, timezone
import jwt
from app.config import settings

_PBKDF2 = "pbkdf2_sha256"

def hash_password(value: str) -> str:
    salt = os.urandom(16)
    iters = int(settings.pbkdf2_iterations)
    dk = hashlib.pbkdf2_hmac("sha256", value.encode(), salt, iters, dklen=32)
    return "%s$%d$%s$%s" % (_PBKDF2, iters, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())

def verify_password(value: str, hashed: str) -> bool:
    try:
        if hashed.startswith(_PBKDF2 + "$"):
            _, iters, salt, dk = hashed.split("$")
            calc = hashlib.pbkdf2_hmac("sha256", value.encode(), base64.b64decode(salt), int(iters), dklen=32)
            return hmac.compare_digest(calc, base64.b64decode(dk))
        if hashed.startswith("scrypt$"):  # legacy hashes from earlier checkpoints
            _, n, r, p, salt, dk = hashed.split("$")
            calc = hashlib.scrypt(value.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
            return hmac.compare_digest(calc, base64.b64decode(dk))
        if hashed.startswith("$2"):  # legacy bcrypt hashes from the earliest phases
            import bcrypt
            return bcrypt.checkpw(value.encode()[:72], hashed.encode())
    except Exception:
        return False
    return False

def needs_rehash(hashed: str) -> bool:
    """True for legacy (scrypt/bcrypt) hashes or PBKDF2 hashes below the configured iteration count."""
    try:
        if not hashed.startswith(_PBKDF2 + "$"):
            return True
        return int(hashed.split("$")[1]) < int(settings.pbkdf2_iterations)
    except Exception:
        return True

def _role(subject: str) -> str:
    s = str(subject)
    return "PLATFORM_ADMIN" if s.startswith("admin:") else "BANK_ADMIN" if s.startswith("bankadmin:") else "REVIEWER" if s.startswith("reviewer:") else "CUSTOMER"

def token_for(subject) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(subject), "role": _role(subject), "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}, settings.jwt_secret_key, algorithm="HS256")

def token_for_admin_otp(subject) -> str:
    """Issue an admin session only after the email OTP has been verified."""
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(subject), "role": "PLATFORM_ADMIN", "amr": ["email_otp"], "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}, settings.jwt_secret_key, algorithm="HS256")

def token_claims(token: str):
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None

def token_subject(token: str):
    claims = token_claims(token)
    return claims.get("sub") if claims else None

# --- brute-force protection (per-process; use a shared store such as Redis behind multiple workers) ---
_fail: dict[str, list[float]] = {}

def _recent(key: str) -> list[float]:
    cutoff = time.time() - settings.login_lockout_minutes * 60
    _fail[key] = [t for t in _fail.get(key, []) if t > cutoff]
    return _fail[key]

def is_locked(key: str) -> bool:
    return len(_recent(key)) >= settings.login_max_failures

def note_failure(key: str) -> None:
    _recent(key).append(time.time())

def clear_failures(key: str) -> None:
    _fail.pop(key, None)
