# TCS Mortgage AI — Consolidated Phases 1–7

React + Vite (JavaScript) · FastAPI · SQLAlchemy · SQLite default (PostgreSQL-compatible) · PyMuPDF/Tesseract OCR · NVIDIA Nemotron LLM and NVIDIA embeddings · policy RAG.

Four role-specific entry points:
- Customer: `/`
- Reviewer: `/reviewer`
- Bank Admin: `/bank-admin`
- Platform Admin: `/admin`

AI output is assistive only and must never make a final lending decision. Review `IMPLEMENTATION_STATUS.md` for verified checks and external-service limitations.

## 1. Prerequisites

- Python 3.11+
- Node.js 20+ and npm
- Tesseract OCR for scanned images/PDF pages (Windows: install Tesseract and set `TESSERACT_CMD`; embedded-text PDFs can work without it)
- NVIDIA API key for live Nemotron inference and embedding calls. The key belongs only in `backend/.env`.

## 2. Backend — Windows PowerShell

From the extracted `TCS_Mortgage_AI` directory:

```powershell
Set-Location .\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Before the **first** server start, set in `backend/.env`:
- `JWT_SECRET_KEY` to a random secret (at least 32 characters for production; use a strong random value in development too).
- `INITIAL_ADMIN_NAME`, `INITIAL_ADMIN_EMAIL`, and `INITIAL_ADMIN_PASSWORD` (password at least 8 characters).
- `NVIDIA_API_KEY` if live AI is required; keep it out of frontend files and source control.
- `NVIDIA_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b` and `NVIDIA_EMBED_MODEL=nvidia/nemotron-3-embed-1b`; model access and embedding compatibility must be verified with the key.
- `TESSERACT_CMD` if Tesseract is not on PATH.

Start the API:

```powershell
uvicorn app.main:app --reload --port 8000
```

On first start only, the backend creates the initial Platform Admin from `INITIAL_ADMIN_*` **if and only if no Platform Admin exists**. It never overwrites an existing admin. After verifying you can sign in at `http://127.0.0.1:5173/admin`, remove the bootstrap password values from `.env` and restart the API. There is no routine admin-provisioning command required.

Open API docs at `http://127.0.0.1:8000/docs`.

## 3. Frontend — second PowerShell window

```powershell
Set-Location .\frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open `http://127.0.0.1:5173`. In development, one-time codes are printed in the backend console only when SMTP is not configured; the UI explicitly labels that as development-console delivery. When `SMTP_HOST` is configured, customer registration OTP and Platform Admin OTP are delivered through SMTP. Email delivery still requires testing against your actual SMTP account.

## 4. Bank onboarding workflow

1. Sign in to `/admin` as Platform Admin.
2. Open **Banks & Bank Admins**, register the bank, then approve it.
3. Create a Bank Admin invitation. The API returns a one-time token valid for 48 hours. The app does **not** claim to email it; copy/share it through a secure channel.
4. The invitee opens `/bank-admin`, chooses **Accept invitation token**, sets a password (8+ characters), then signs in.
5. Bank Admin can see only their bank-scoped applications, reviewers, and bank policies; they cannot use Platform Admin endpoints.
6. Customers choose an approved bank from the lender selector when approved banks exist.

## 5. Tests and verification

```powershell
Set-Location .\backend
python -m pytest -q
python scripts\smoke_check.py
python scripts\verify_nvidia.py
```

The NVIDIA verification script makes real network calls. Live inference is not verified just because the API key is configured. To run the frontend production build:

```powershell
Set-Location .\frontend
npm run build
```

Install frontend dependencies with `npm install` first. A failed build caused by missing `vite` means dependencies are absent; it is not a successful build.

## 6. Database migrations and data safety

Startup runs SQLAlchemy `create_all()` for new tables and a small additive migration runner for legacy tables. The additive migration adds customer account-active state, application form/consent JSON fields, document structured-extraction/correction-history fields, OTP creation timestamps, and the existing bank-scoping fields without dropping tables or rows. New analysis-run and customer-notification tables are created by SQLAlchemy metadata. Existing legacy records are preserved. Back up your database before upgrades. No database reset is required.

For PostgreSQL, set `DATABASE_URL` appropriately and use a database user with schema-alter permissions for the first migrated startup. The included additive runner is intentionally small; for larger production schema evolution, adopt a versioned Alembic migration chain before deployment.

## 7. Feature map

| Area | Location |
|---|---|
| Customer auth/application/document workflow | `backend/app/routers/{auth,applications,documents,customer}.py`; `frontend/src/CustomerPortal.jsx` |
| Reviewer workflow | `backend/app/routers/reviewer.py`; `frontend/src/ReviewerPortal.jsx` |
| Platform Admin, bank approval/invitations | `backend/app/routers/admin.py`; `frontend/src/AdminPortal.jsx` |
| Bank Admin login, bank-scoped staff/apps/policies | `backend/app/routers/bank_admin.py`; `frontend/src/BankAdminPortal.jsx` |
| Role token and PBKDF2 password hashing (legacy scrypt/bcrypt hashes verify and upgrade on next login) | `backend/app/security.py` |
| Platform Admin password + OTP sign-in | `backend/app/routers/admin.py` (`/admin/login`, `/admin/login/verify-otp`); OTP delivery in `backend/app/services/mailer.py` |
| KYC status, document-linked verification, approval gate | `backend/app/routers/reviewer.py` (`POST /reviewer/applications/{id}/kyc`); `MortgageApplication.kyc_*` |
| Additive migration | `backend/app/migrations/runner.py` |
| OCR, labelled field extraction/corrections, reviewer verification, PDF receipt | `backend/app/services/ocr.py`; `ApplicationDocument.extracted_text`, `extracted_fields_json`, `corrected_fields_json`, correction history; `GET /api/v1/applications/{id}/receipt.pdf` |
| Deterministic financial calculations and scenarios | `backend/app/services/calculations.py`, `scenarios.py` |
| NVIDIA Nemotron, NeMo Guardrails and embedding client | `backend/app/services/nvidia.py`; `backend/app/guardrails/config.yml`; `backend/app/guardrails/rails.co`; `POST /api/v1/admin/ai/verify` |
| Global and bank-specific policy RAG | `backend/app/services/policy_rag.py`; `PolicyDocument.bank_id`; `PolicyChunk` |
| Application-document OCR RAG | `backend/app/services/document_rag.py`; `ApplicationDocumentChunk`; scoped by application ID |
| Audit trail | `backend/app/services/audit.py`; `GET /api/v1/admin/audit-logs` |

## 8. Known external dependencies / limitations

- Live NVIDIA chat and embedding calls require a valid key, model entitlement, outbound network, and successful `POST /api/v1/admin/ai/verify`.
- Customer document analysis and policy Q&A, Reviewer policy Q&A, and Bank Admin policy Q&A run through the shared NeMo Guardrails 0.24.1 self-check input/output rails before returning Nemotron results. The guardrail configuration uses the existing NVIDIA model and key from backend settings; no additional guardrail secrets or environment variables are required. Guardrail configuration/check failures stop protected inference. Embedding/indexing and the Platform Admin provider-connectivity diagnostic are not conversational AI responses and remain outside these rails.
- OCR for scanned documents requires local Tesseract; real document quality varies.
- Customer registration OTP uses SMTP when configured; in development without SMTP, it is explicitly delivered to the backend console. Real email delivery is **not verified against a live mail server** in this checkpoint. OTP expiry, attempt limits and resend cooldown are enforced by the API.
- KYC is a reviewer-attested checklist over documents in the `KYC` category; no government/bureau/identity-verification service is integrated.
- Bank invitation tokens are generated for secure manual delivery; automatic email delivery is not configured.
- Customer Panel now has a six-step application wizard, persistent draft data, server-side submission validation, all 11 displayed document categories, structured OCR field suggestions/correction history, persisted analysis runs, dashboard/status summaries, notifications and profile mobile updates. OCR extraction uses conservative labelled-text patterns after the OCR pipeline; it does not guarantee that every layout will produce structured fields. PDF receipt and document verification have API tests, but representative mortgage PDFs, all scenarios and real-browser end-to-end behavior must still be checked in the target Windows environment before production approval.
- This environment may not have npm dependencies or network access; only report the frontend build as passing after `npm run build` succeeds.

## 9. Security configuration (passwords, Platform Admin OTP, KYC)

- **Passwords:** every account type (customer, reviewer, Bank Admin, Platform Admin) requires at least **8** characters (single constant `MIN_PASSWORD_LENGTH` in `backend/app/config.py`). Hashes are PBKDF2-HMAC-SHA256 (`PBKDF2_ITERATIONS`, default 600000; production refuses to start below 210000). Existing scrypt/bcrypt hashes keep working and are re-hashed to PBKDF2 at the user's next successful sign-in. An 8-character minimum is weaker than the previous 10/12; the lockout (5 failures / 15 minutes) is in-process only, so put a shared rate limiter in front of multi-worker deployments.
- **Platform Admin OTP:** `POST /admin/login` validates the password and issues a 6-digit code (expires after `OTP_EXPIRY_MINUTES`, single use, 5 attempts, then lockout) without returning a token; `POST /admin/login/verify-otp` returns the token. Development prints the code to the console. Outside development, set `SMTP_HOST` (+ `SMTP_*`), otherwise the API refuses to start; set `ADMIN_OTP_REQUIRED=false` only as a deliberate, documented exception.
- **Password recovery:** Customers, Reviewers, and Bank Admins can request a one-time email reset link through `/api/v1/auth/password-reset/request`; completion uses `/api/v1/auth/password-reset/complete`. Links expire after `PASSWORD_RESET_EXPIRY_MINUTES` (default 30), are stored as token digests, and are single-use. SMTP must be configured to deliver reset links. Platform Admin remains on its existing password-plus-OTP sign-in flow and is not included in this recovery endpoint.
- **KYC:** the reviewer records `VERIFIED`, `REJECTED` or `NEEDS_REVIEW` per application. `VERIFIED` is accepted only when at least one `KYC`-category document exists and every one is individually verified. **Recommending approval is blocked until KYC is `VERIFIED`** (decline, escalate and request-documents are not). A new KYC upload, or a customer edit of verified text, resets the dependent verification to `PENDING`. Existing applications are migrated with `kyc_status = PENDING`.

## Troubleshooting

- `ModuleNotFoundError: openai`: activate the backend virtual environment and run `python -m pip install -r requirements.txt`. The API can load without the optional import, but NVIDIA endpoints explicitly fail until the client dependency is installed.
- `503` for NVIDIA: set `NVIDIA_API_KEY`, install requirements, restart, and run the real verification endpoint/script.
- Scanned PDFs need Tesseract; set `TESSERACT_CMD` if it is not on PATH.
- CORS errors: `FRONTEND_ORIGIN` must exactly match the browser origin.
- If you already have a database, back it up before starting the updated app. Migration is additive and does not reset data.

See `IMPLEMENTATION_STATUS.md` for the current verified checkpoint and exact remaining acceptance work.


## First Platform Admin setup (no CLI account creation)

1. Copy `backend/.env.example` to `backend/.env` if you have not already done so.
2. Set `INITIAL_ADMIN_EMAIL` to the email address you will use as Platform Admin. You do not need to set `INITIAL_ADMIN_PASSWORD` for UI setup.
3. Start the backend and frontend using the commands above, then open `http://127.0.0.1:5173/admin`.
4. If the database has no Platform Admin, choose **First-time Platform Admin setup**, enter the configured email, name and a password of at least 8 characters. The API accepts this only once and only for the configured email.
5. Sign in. If OTP is enabled, enter the code delivered by SMTP; in development without SMTP the code is printed in the backend terminal.

If an admin already exists, first-time setup is disabled and normal sign-in must be used. Never expose the backend development console or share OTPs.

## Customer Panel implementation checkpoint (2026-10-20)

The Customer Panel has a responsive six-step application wizard, customer-owned draft persistence, approved-bank selection, backend-authoritative submission checks, the 11 requested document categories, structured OCR fields, original/corrected value separation, correction history, persisted NVIDIA analysis runs, customer-safe policy-summary retrieval, dashboard/status counts, recent activity, notifications, profile mobile updates, and submission confirmation.

The customer-facing policy retrieval path indexes only the customer-safe summary explicitly enabled by a Bank Admin. Internal policy text remains in the reviewer/internal audience index and is not returned by customer RAG. If no customer-safe summary is relevant, the UI says so rather than exposing internal policies.

Uploaded PDF/image text is extracted by PyMuPDF/Tesseract with page markers, split into overlapping text chunks, and stored in the same relational database as persistent JSON NVIDIA embeddings (`nvidia/nemotron-3-embed-1b`). Original OCR and customer-corrected text are indexed separately; corrected text remains labelled unverified. Retrieval is restricted to the authorized application, returns filename/category/page/variant metadata, and uses lexical retrieval when embeddings are unavailable. Document updates replace that document's chunks. Active bank/global policy excerpts are retrieved separately and passed to Nemotron document-analysis context; policy Q&A passes its retrieved excerpts directly to Nemotron, while reviewer valuation, income/tax, and terms scenarios return policy evidence separately from deterministic findings. Policy citations retain bank, version, title, and excerpt provenance; no-result states are explicit.

Automatic reviewer assignment is deterministic. The current schema supports one primary reviewer per application: a general mortgage reviewer is preferred, capacity is enforced, pending assignments are retried when reviewers become available, and assignment events are persisted. Manual Platform Admin assignment is disabled. A multi-specialist task model is not implemented in this Customer Panel checkpoint.

See `AUTO_ASSIGNMENT.md` for the full automatic-assignment design (availability, notifications, retry, history, Bank Admin monitoring).

### Customer Panel verification notes

- Backend tests are run with `python -m pytest -q` from `backend/`.
- The current execution environment has no frontend `node_modules`; `npm run build` cannot run until dependencies are installed by the project owner. No packages were installed during this work.
- Live NVIDIA inference remains unverified because `NVIDIA_API_KEY` is not configured in `backend/.env`. The app persists a failure status and does not fabricate a result when the model service is unavailable.
- SMTP delivery remains unverified against a real mail server. In development without SMTP, the UI explicitly states that the OTP is printed to the backend terminal; in production without SMTP, registration fails instead of claiming email delivery.
- Browser-based end-to-end testing and Windows target-environment validation remain required before production release.


## Email OTP setup (real email)
Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` in `backend/.env` (Gmail example in `.env.example`), restart the backend, then run `python scripts/test_smtp.py you@example.com`. Customer registration OTP, Platform Admin OTP, bank registration confirmations/decisions and Bank Admin activation links use this SMTP account. Without SMTP, OTPs print to the backend console in development only.

## Bank registration and approval
Banks self-register at `/bank-admin` ("Register a new bank": details + up to 5 documents) and stay PENDING. Platform Admin (Banks tab -> Review) approves, or rejects with a mandatory reason. Approval emails a one-time, 48-hour Bank Admin activation link to the registered contact.
