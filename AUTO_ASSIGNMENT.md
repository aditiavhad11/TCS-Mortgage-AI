# Automatic Reviewer Assignment

## Flow
Customer submits (`POST /applications/{id}/submit`) → backend assigns an eligible same-bank reviewer in the **same transaction** →
application status `ASSIGNED`, reviewer + customer notified, assignment persisted → reviewer sees it in `/reviewer/applications` →
Bank Admin monitors via `/bank-admin/dashboard`, `/bank-admin/applications`, `/bank-admin/assignment-history` (read-only).

## Rules (code: `backend/app/services/assignment.py`)
| Requirement | Implementation |
|---|---|
| Only after real submission | `DRAFT` is never assigned; the engine is called only from `submit` (plus retries of already-submitted apps) |
| Eligibility | same bank (approved), `is_active`, `is_available` (reviewer self-service toggle), active load < `max_active_assignments` |
| Selection | general reviewers first → lowest workload → longest since last assignment → lowest id (deterministic, no LLM) |
| Workload | active assignments on unfinished applications only (completed/closed reviews free capacity) |
| No duplicates / races | `UNIQUE(application_id)`, per-attempt SAVEPOINT, reviewer-row lock + capacity re-check, idempotent re-entry |
| No reviewer / any error | submission kept, `status=PENDING_ASSIGNMENT`, `awaiting_assignment=true`, label **Awaiting Reviewer Assignment** |
| Safe retry | on reviewer create / activate / become available / review completed, plus a background loop (`ASSIGNMENT_RETRY_INTERVAL_SECONDS`, default 60) |
| History | `assignment_events` (ASSIGNED, PENDING_ASSIGNMENT, REASSIGNMENT_REQUIRED, RESUBMITTED) with timestamps + audit log |
| Notifications | `reviewer_notifications` (new), customer notifications, Bank Admin dashboard counters + recent activity feed (UI polls every 15 s) |
| No manual assignment | Bank Admin and Platform Admin assignment endpoints return 403 |

## New / changed API
- `PATCH /reviewer/availability?available=true|false`, `GET /reviewer/notifications`, `POST /reviewer/notifications/{id}/read`, `POST /reviewer/notifications/read-all`, `/reviewer/me` (+load, availability, unread)
- `GET /bank-admin/assignment-history[?application_id=]`; dashboard adds `awaiting_assignment`, `available_reviewers`, `status_counts`, `recent_assignment_activity`
- DB: `reviewers.is_available/last_assigned_at`, `mortgage_applications.awaiting_assignment/assignment_attempts/last_assignment_attempt_at`, table `reviewer_notifications` (additive migration in `migrations/runner.py`)
- `scripts/assign_application.py` now re-runs the automatic engine (it no longer lets an operator pick a reviewer).

## Tests
`backend/tests/test_auto_assignment_workflow.py` (+ existing `test_assignment.py`): draft skipped, availability, balancing, capacity, idempotency, error fallback,
background retry, thread race, and the full API workflow (submit → assigned → reviewer sees + notified → Bank Admin monitors, manual assign 403).
Run: `cd backend && python -m pytest -q`
