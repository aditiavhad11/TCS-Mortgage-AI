# TCS Mortgage AI — Customer Panel Verification Report

**Checkpoint:** 2026-10-20  
**Scope:** Customer Panel and the backend connections needed for customer-owned applications, document processing, notifications, customer-safe policy retrieval, and automatic reviewer assignment. This does not claim that every portal in the platform has received a full rebuild.

## Requirement-by-requirement status

| Requirement area | Implementation/verification status | Evidence / limitation |
|---|---|---|
| Existing architecture | Preserved | React/Vite/JSX frontend; FastAPI, SQLAlchemy, SQLite, Pydantic backend; no TypeScript introduced. |
| Registration | Implemented and API-tested | Full name, mobile, email, password/confirmation validation, duplicate detection, hashed passwords, pending registration and email OTP. |
| Email OTP | Implemented; real SMTP unverified | Expiry, attempts and resend cooldown are enforced. Development console delivery is explicitly labelled. Production without SMTP fails closed. |
| Sign-in | Implemented and API-tested | Full name + password only; verified/active account check; duplicate-name ambiguity returns 409 instead of selecting an arbitrary account. |
| Dashboard | Implemented | Actual database-backed application/status counts, notifications, activity, requested amounts, dates, status and next-action hints. Refresh on focus and every 30 seconds. |
| Application form | Implemented | Six-step form for applicant, loan/income, repayment, property, documents and review/submit; draft persistence and resume; co-applicant conditional fields. |
| Approved lender selection | Implemented | UI lists approved banks; backend rejects an unknown/unapproved lender on submission. |
| Document categories | Implemented | All 11 requested categories appear in the UI; required/optional state is returned by backend requirements logic. |
| Upload validation | Implemented | Existing document service validates file type/size and application ownership; actual extraction state is shown. |
| OCR field presentation | Implemented with conservative extraction patterns | Labelled fields and source evidence are displayed instead of raw JSON. Extraction quality varies by document layout; OCR is not authenticity verification. |
| Original/corrected values | Implemented and API-tested | Original extracted fields remain separate from corrected values; correction history records actor/time/reason. Text correction no longer overwrites original structured extraction fields. |
| Save/resume draft | Implemented and API-tested | Draft fields and consent state persist in the database. Incomplete drafts are allowed; submission checks run server-side. |
| Submission validation | Implemented and API-tested | Required fields, supported choices, approved bank, consent, document presence/readability, numeric fields and duplicate state are checked by backend. |
| Submission confirmation | Implemented in UI | Confirmation dialog precedes backend submission. Success message appears only after backend success. |
| NVIDIA analysis | Real service call path implemented; live inference unverified | Proposed configured Nemotron model is called through backend. Structured-output/evidence validation is enforced; run/result/error is persisted. No mock result or silent LLM fallback. `NVIDIA_API_KEY` is not configured in this environment, so live inference could not be verified. |
| Analysis failure persistence | Implemented and API-tested | Missing configuration/service failures are stored as failed runs and returned as honest errors. |
| Numerical validation | Implemented | Backend computes EMI/LTV/DTI estimates and document-vs-declaration numerical comparisons; configured tolerance is not a lending eligibility threshold. |
| Cross-document comparisons | Implemented conservatively | Like-for-like extracted income/property/loan fields are compared; monthly and annual values are not treated as equivalent. Review periods/source evidence before conclusions. |
| Customer-facing RAG | Implemented with access boundary | Separate customer-summary index; only active policies explicitly marked customer-visible with a customer-safe summary can be retrieved. Internal policy chunks remain internal. NVIDIA embedding generation is not operationally verified without the API key. |
| Reviewer assignment | Implemented in backend integration | Automatic assignment, general-review preference, active status, configured capacity, same-bank scoping, pending state/retry, unique-assignment race guard, assignment events. Manual Platform Admin assignment endpoint is disabled. Current schema supports one primary reviewer, not separate specialist tasks. |
| Customer notifications | Implemented and API-tested | Notification list/read state, submission, assignment, review-request and analysis outcomes are persisted. |
| Profile settings | Implemented and API-tested | Mobile update; name/email remain read-only in the current profile flow. |
| Privacy/security | Implemented/tested in relevant API paths | Customer ownership checks, bank scoping, account number not collected by new UI and masked in responses, internal policy content excluded from customer RAG, no OTP/API secrets in customer responses. |
| Frontend source syntax | Parsed | All JavaScript/JSX files passed TypeScript compiler parser diagnostics. This is a syntax check, not a production bundle or browser test. |
| Backend tests | **70 passed, 3 skipped** at the last completed run | `python -m pytest -q` in `backend/`. Run again after final packaging. |
| Frontend production build | Not verified | `npm run build` failed because Vite is not installed in this workspace. Per instruction, dependencies were not installed. Run `npm install` in `frontend/`, then `npm run build`. |
| Real NVIDIA endpoint/model | Not verified | `python scripts/verify_nvidia.py` reported `NVIDIA_API_KEY is not set in backend/.env - nothing was verified.` |
| Real SMTP delivery | Not verified | Requires a real SMTP host/credentials and a successful delivery test. |
| Browser/UAT on Windows | Not verified | Requires running the app with installed frontend dependencies and configured external services. |

## Commands for the project owner

Backend (from `backend/`):

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Tests (from `backend/`):

```powershell
python -m pytest -q
```

Frontend (from `frontend/`):

```powershell
npm install
npm run build
npm run dev
```

Before live AI testing, set a valid NVIDIA-hosted API key and verify the configured model ID/endpoint with `python scripts/verify_nvidia.py`. Configure SMTP and test OTP delivery before treating email verification as production-ready.

## Known limitations that must not be represented as completed

1. Live Nemotron inference and NVIDIA embedding calls were not verified because the NVIDIA API key is absent.
2. Real SMTP delivery was not verified.
3. A frontend production build and browser end-to-end test were blocked by missing frontend dependencies.
4. OCR structured extraction is pattern-based and must be evaluated against representative real mortgage PDFs/images.
5. The existing workflow currently supports one primary reviewer per application. Multi-specialist task assignments require a separate task model/workflow.
6. Customer policy retrieval is limited to explicitly customer-visible summaries; no customer-visible summary means no policy excerpt is exposed.
