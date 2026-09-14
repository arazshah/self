# Self Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the repository’s static site with a deployable FastAPI/SQLite Persian personal assistant that ingests Bale voice/text, uses AvalAI for transcription and structured understanding, schedules Solar Hijri-aware reminders, sends daily/weekly reports, and provides a strictly user-scoped dashboard through single-use Bale login links.

**Architecture:** A modular FastAPI service stores all user data in SQLite. A Bale webhook creates idempotent processing jobs; a background loop processes audio through AvalAI, validates structured extraction, persists domain records, and sends reports/reminders. A secure one-time token from the Bale bot establishes an HttpOnly dashboard session whose `user_id` scopes every repository query.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, httpx, python-multipart, jdatetime, itsdangerous or standard-library HMAC/secrets, Jinja2, pytest, pytest-asyncio, ruff, uvicorn.

**Spec:** `docs/superpowers/specs/2026-09-14-self-assistant-design.md`

## Global Constraints

- All user-visible text is Persian and dashboard layout is RTL.
- The stable tenant key is the Bale private `chat_id`.
- Every user-data query is scoped by authenticated `user_id`; no client-supplied user ID is trusted.
- Only private Bale chats are accepted.
- AvalAI keys and Bale tokens are environment variables only.
- Raw audio is deleted according to `RAW_AUDIO_RETENTION_HOURS`; default is 24 hours.
- LLM output is untrusted until schema parsing and application validation succeed.
- No automatic payment, external message, phone call, shopping, or calendar mutation is implemented.
- Reminder and report delivery must be idempotent.
- Production runs one Uvicorn worker because the first scheduler implementation is in-process and SQLite-backed.
- Existing static-site content is not part of the deployed application and may be deleted from the working tree while preserving Git history.

## File Map

Create the following focused files:

- `pyproject.toml` — dependencies, pytest, Ruff configuration.
- `.env.example` — non-secret configuration names and safe example values.
- `Dockerfile` — single-process production image.
- `.dockerignore` — excludes local data, caches, secrets, and tests from image context where appropriate.
- `README.md` — local setup, environment variables, Bale webhook setup, Coolify deployment, privacy model.
- `app/main.py` — FastAPI app factory, lifespan, router registration.
- `app/config.py` — typed settings and fail-fast validation.
- `app/db.py` — SQLite engine, session factory, transaction helper.
- `app/models.py` — SQLAlchemy models and indexes.
- `app/repositories.py` — user-scoped persistence operations.
- `app/schemas.py` — API/domain Pydantic schemas.
- `app/time_utils.py` — Solar Hijri parsing and timezone resolution.
- `app/auth.py` — single-use link and dashboard session service.
- `app/bale.py` — Bale HTTP adapter and update parsing.
- `app/ai.py` — AvalAI transcription/extraction/report adapter.
- `app/pipeline.py` — ingestion and asynchronous processing orchestration.
- `app/scheduler.py` — due reminders and digest scheduling.
- `app/reports.py` — daily/weekly report aggregation and rendering.
- `app/web.py` — webhook, dashboard, auth, and action routes.
- `app/templates/*.html` — RTL dashboard templates.
- `app/static/app.css` — compact RTL styling.
- `tests/conftest.py` — isolated in-memory/test SQLite app fixtures.
- `tests/test_config.py`, `tests/test_auth.py`, `tests/test_isolation.py`, `tests/test_time_utils.py`, `tests/test_bale.py`, `tests/test_ai.py`, `tests/test_pipeline.py`, `tests/test_scheduler.py`, `tests/test_reports.py`, `tests/test_web.py` — behavior tests.

### Task 1: Replace the static site with a testable Python service skeleton

**Files:**
- Delete: tracked static website files at repository root (`index.html`, `scripts.js`, `styles.css`, `CNAME`, `images/`, `posts/`, `references/`).
- Create: `pyproject.toml`, `app/__init__.py`, `app/main.py`, `tests/conftest.py`, `tests/test_health.py`, `.env.example`, `Dockerfile`, `.dockerignore`.

**Interfaces:**
- `create_app(settings: Settings | None = None) -> FastAPI`.
- `GET /health` returns `{"status":"ok"}` without authentication.

- [ ] **Step 1: Write the failing health test**

```python
def test_health_returns_ok(test_client):
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run `pytest tests/test_health.py -q` and verify it fails because `app.main` is missing.**
- [ ] **Step 3: Add the minimal FastAPI app factory and test fixture.**
- [ ] **Step 4: Run `pytest tests/test_health.py -q` and verify it passes.**
- [ ] **Step 5: Add dependency and container configuration without secrets.**
- [ ] **Step 6: Run `python -m compileall app` and `ruff check app tests`; both must exit 0.**
- [ ] **Step 7: Commit with `git add -A && git commit -m "chore: replace static site with FastAPI service skeleton"`.**

### Task 2: Add typed settings and SQLite persistence

**Files:**
- Create: `app/config.py`, `app/db.py`, `app/models.py`, `app/repositories.py`, `app/schemas.py`.
- Create: `tests/test_config.py`, `tests/test_storage.py`.
- Modify: `app/main.py`, `tests/conftest.py`.

**Interfaces:**
- `Settings.from_env() -> Settings`.
- `get_session() -> Iterator[Session]`.
- `init_db(engine) -> None`.
- `UserRepository.get_or_create_by_bale_chat(chat_id: int, ...) -> User`.
- `EntryRepository.create(user_id: int, ...) -> Entry`.
- `EntryRepository.list_for_user(user_id: int, ...) -> list[Entry]`.

Models must include `User`, `Entry`, `ExtractedRecord`, `Reminder`, `Digest`, `DashboardToken`, and `DashboardSession`. Add indexes on `(user_id, created_at)`, `(user_id, due_at, status)`, and unique `(user_id, source_message_id)`.

- [ ] **Step 1: Write failing tests for required environment validation, user creation, and entry scoping.**
- [ ] **Step 2: Run `pytest tests/test_config.py tests/test_storage.py -q`; verify failures are caused by missing settings/models.**
- [ ] **Step 3: Implement typed settings, SQLite engine, models, and user-scoped repositories.**
- [ ] **Step 4: Run the two test files and verify they pass.**
- [ ] **Step 5: Run the full current suite and verify no regression.**
- [ ] **Step 6: Commit with `git add app tests && git commit -m "feat: add scoped SQLite domain storage"`.**

### Task 3: Implement one-time dashboard authentication and isolation

**Files:**
- Create: `app/auth.py`, `tests/test_auth.py`, `tests/test_isolation.py`.
- Modify: `app/models.py`, `app/repositories.py`, `app/main.py`.

**Interfaces:**
- `create_dashboard_token(user_id: int, now: datetime) -> str`.
- `consume_dashboard_token(raw_token: str, now: datetime) -> int | None`.
- `create_session(user_id: int, now: datetime) -> str`.
- `get_authenticated_user(request: Request) -> User`.

Tokens must contain a random 32-byte secret stored only as a SHA-256 hash, expire after 10 minutes, be consumed inside a transaction, and be bound to the originating user. Sessions use a random opaque ID stored hashed in SQLite and an HttpOnly/Secure/SameSite=Lax cookie.

- [ ] **Step 1: Write failing tests for expiry, single use, wrong-user binding, logout, and cross-user repository access.**
- [ ] **Step 2: Run `pytest tests/test_auth.py tests/test_isolation.py -q` and verify red failures.**
- [ ] **Step 3: Implement token hashing, transactional consume, session cookie handling, and ownership checks.**
- [ ] **Step 4: Run the focused tests and verify green.**
- [ ] **Step 5: Add CSRF token validation for dashboard mutations and test rejection of missing/incorrect CSRF.**
- [ ] **Step 6: Commit with `git add app tests && git commit -m "feat: add single-use dashboard authentication"`.**

### Task 4: Implement the Bale adapter and webhook ingress

**Files:**
- Create: `app/bale.py`, `tests/test_bale.py`.
- Modify: `app/config.py`, `app/web.py`, `app/main.py`.

**Interfaces:**
- `BaleClient.send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> BaleMessage`.
- `BaleClient.get_file(file_id: str) -> BaleFile`.
- `BaleClient.download_file(file_path: str) -> bytes`.
- `parse_private_update(payload: dict) -> IncomingMessage | None`.
- `POST /bale/webhook/{webhook_secret}` returns `{"ok": true}`.

Accept text and voice fields, reject group/channel updates, enforce a maximum download size, deduplicate by Bale `update_id`/message ID, and return quickly after persisting an ingestion job. Add a `/dashboard` command that sends the one-time dashboard link using `APP_BASE_URL`.

- [ ] **Step 1: Write failing tests for private voice parsing, group rejection, dedupe, secret-path rejection, and dashboard-link generation.**
- [ ] **Step 2: Run `pytest tests/test_bale.py -q` and verify red.**
- [ ] **Step 3: Implement the adapter using `httpx.AsyncClient` and the minimal webhook route.**
- [ ] **Step 4: Run focused tests and verify green.**
- [ ] **Step 5: Add timeout, retry-after handling, and safe error messages that exclude tokens and transcripts.**
- [ ] **Step 6: Commit with `git add app tests && git commit -m "feat: receive private Bale messages"`.**

### Task 5: Add Persian date resolution and the reminder scheduler

**Files:**
- Create: `app/time_utils.py`, `app/scheduler.py`, `tests/test_time_utils.py`, `tests/test_scheduler.py`.
- Modify: `app/models.py`, `app/repositories.py`, `app/web.py`.

**Interfaces:**
- `resolve_persian_datetime(text: str, now: datetime, timezone: str) -> ResolvedDate`.
- `claim_due_reminders(now: datetime, limit: int) -> list[Reminder]`.
- `deliver_reminder(reminder_id: int) -> DeliveryResult`.
- `run_scheduler_once(now: datetime) -> SchedulerStats`.

Resolve explicit Solar Hijri dates, weekdays, relative phrases, and times. Return `needs_confirmation=True` for ambiguous dates. Preserve raw phrases and store UTC timestamps. Claim reminders transactionally, send each at most once, and support snooze/complete/cancel state transitions.

- [ ] **Step 1: Write failing tests for `۲۵ مهر`, `فردا`, `شنبهٔ آینده`, Tehran timezone conversion, ambiguity, and once-only delivery.**
- [ ] **Step 2: Run `pytest tests/test_time_utils.py tests/test_scheduler.py -q` and verify red.**
- [ ] **Step 3: Implement deterministic date parsing and SQLite-safe reminder claiming.**
- [ ] **Step 4: Run focused tests and verify green.**
- [ ] **Step 5: Add scheduler startup loop with one process/one worker guard.**
- [ ] **Step 6: Commit with `git add app tests && git commit -m "feat: add Solar Hijri reminders"`.**

### Task 6: Implement AvalAI transcription and structured extraction

**Files:**
- Create: `app/ai.py`, `tests/test_ai.py`.
- Modify: `app/config.py`, `app/pipeline.py`, `app/schemas.py`.

**Interfaces:**
- `AvalAIClient.transcribe(audio: bytes, filename: str) -> str`.
- `AvalAIClient.extract(transcript: str, now: datetime, timezone: str) -> ExtractionResult`.
- `AvalAIClient.generate_digest(entries: list[Entry], records: list[ExtractedRecord], period: Period) -> DigestDraft`.

Use `https://api.avalai.ir/v1`. Transcription calls `/audio/transcriptions` with `language=fa`; extraction uses the configured text model and JSON Schema where supported. Treat model output as untrusted. Validate `additionalProperties=False`, enum values, dates, confidence range, and evidence spans. Handle timeout, 4xx/5xx, malformed output, refusal, incomplete output, and rate limits without persisting unconfirmed reminders.

- [ ] **Step 1: Write failing tests using a fake transport for successful transcription, valid extraction, malformed JSON, refusal, and timeout.**
- [ ] **Step 2: Run `pytest tests/test_ai.py -q` and verify red.**
- [ ] **Step 3: Implement the AvalAI adapter, Pydantic schemas, and error mapping.**
- [ ] **Step 4: Run focused tests and verify green.**
- [ ] **Step 5: Add a fixture-driven evaluation set with Persian date, colloquial speech, bill, call, idea, and reflection examples.**
- [ ] **Step 6: Commit with `git add app tests && git commit -m "feat: integrate AvalAI understanding pipeline"`.**

### Task 7: Connect ingestion, confirmation, and reports

**Files:**
- Create: `app/pipeline.py`, `app/reports.py`, `tests/test_pipeline.py`, `tests/test_reports.py`.
- Modify: `app/bale.py`, `app/repositories.py`, `app/scheduler.py`, `app/web.py`.

**Interfaces:**
- `process_entry(entry_id: int) -> ProcessingResult`.
- `confirm_record(user_id: int, record_id: int) -> ExtractedRecord`.
- `build_daily_digest(user_id: int, local_date: date) -> DigestDraft`.
- `build_weekly_digest(user_id: int, start: date, end: date) -> DigestDraft`.

The pipeline downloads voice through Bale, transcribes through AvalAI, extracts records, resolves dates, asks clarification for ambiguity, persists source evidence, and sends a compact confirmation. Raw audio deletion is a separate successful-processing step. Daily/weekly digests aggregate only the selected user’s local-period data and label facts, interpretations, and suggestions.

- [ ] **Step 1: Write failing tests for a voice-to-record pipeline, retry without duplication, confirmation, daily user scoping, and weekly boundary.**
- [ ] **Step 2: Run focused tests and verify red.**
- [ ] **Step 3: Implement the pipeline and report builders using fake Bale/AvalAI ports.**
- [ ] **Step 4: Run focused tests and verify green.**
- [ ] **Step 5: Add scheduler jobs for daily and weekly reports and delivery idempotency.**
- [ ] **Step 6: Commit with `git add app tests && git commit -m "feat: process entries and send digests"`.**

### Task 8: Build the Persian RTL dashboard

**Files:**
- Create: `app/templates/base.html`, `app/templates/dashboard.html`, `app/templates/entries.html`, `app/templates/reminders.html`, `app/templates/settings.html`, `app/static/app.css`, `tests/test_web.py`.
- Modify: `app/web.py`, `app/main.py`.

**Interfaces:**
- `GET /auth/claim/{token}` consumes token and redirects to `/dashboard`.
- `GET /dashboard` shows current user’s latest digest and counts.
- `GET /entries`, `/reminders`, `/categories`, `/settings` are authenticated and user-scoped.
- `POST /reminders/{id}/complete`, `/snooze`, `/cancel` re-check ownership and CSRF.
- `POST /logout` clears the session.

Use server-rendered Jinja templates first. Do not expose raw database IDs as authorization; IDs are acceptable as opaque UI references only after ownership checks. Escape transcript/report HTML and render user content as text.

- [ ] **Step 1: Write failing tests for unauthenticated redirect, authenticated user view, cross-user denial, and reminder mutation CSRF/ownership.**
- [ ] **Step 2: Run `pytest tests/test_web.py -q` and verify red.**
- [ ] **Step 3: Implement routes, templates, RTL styling, and safe rendering.**
- [ ] **Step 4: Run focused tests and verify green.**
- [ ] **Step 5: Add a browser smoke test using FastAPI TestClient for login → dashboard → reminder completion.**
- [ ] **Step 6: Commit with `git add app tests && git commit -m "feat: add private RTL dashboard"`.**

### Task 9: Add deployment and operational documentation

**Files:**
- Modify: `Dockerfile`, `.env.example`, `README.md`, `app/main.py`.
- Create: `tests/test_deployment_config.py`.

Document Coolify deployment with:

- persistent volume mounted at `/data`;
- domain `self.araz.me` with HTTPS;
- one Uvicorn worker;
- health check `/health`;
- all required environment variables;
- webhook URL `https://self.araz.me/bale/webhook/<BALE_WEBHOOK_SECRET>`;
- no secrets in Git;
- backup and restore of SQLite;
- raw audio retention and deletion;
- migration/startup behavior.

- [ ] **Step 1: Write failing tests for missing-secret startup failure and safe `.env.example` contents.**
- [ ] **Step 2: Run `pytest tests/test_deployment_config.py -q` and verify red.**
- [ ] **Step 3: Implement container health/startup configuration and deployment documentation.**
- [ ] **Step 4: Run focused tests and verify green.**
- [ ] **Step 5: Build with `docker build -t self-assistant:test .` and verify exit 0.**
- [ ] **Step 6: Commit with `git add Dockerfile .dockerignore .env.example README.md app tests && git commit -m "docs: add Coolify deployment configuration"`.**

### Task 10: Full verification and publish to master

**Files:**
- Modify only files required by verification fixes.

- [ ] **Step 1: Run `pytest -q`; record total tests and failures.**
- [ ] **Step 2: Run `ruff check app tests` and `ruff format --check app tests`.**
- [ ] **Step 3: Run `python -m compileall app`.**
- [ ] **Step 4: Run `docker build -t self-assistant:final .`.**
- [ ] **Step 5: Inspect `git diff --check`, `git status --short`, and `git log --oneline -10`.**
- [ ] **Step 6: Verify no secret-looking value is tracked with `rg -n "(BALE_BOT_TOKEN|AVALAI_API_KEY|SESSION_SECRET|sk-[A-Za-z0-9])" --glob '!docs/**' --glob '!tests/fixtures/**' .`; only variable names and test placeholders may remain.**
- [ ] **Step 7: Push the verified commits to the user-requested branch with `git push origin master`.**
- [ ] **Step 8: Report the commit hash, test count, deployment variables, and any remaining manual Coolify steps.**

## Plan Self-Review

- Spec coverage: Bale ingestion is Task 4; AvalAI is Task 6; Solar Hijri reminders are Task 5; daily/weekly reports are Task 7; dashboard/token auth/isolation are Tasks 3 and 8; Coolify is Task 9; non-goals and security constraints are global constraints and Task 10.
- Dependency order is explicit: skeleton → storage → auth → Bale → dates → AI → pipeline/reports → dashboard → deployment → verification.
- No task permits automatic payments or external actions.
- All public UI mutations have both CSRF and ownership requirements.
- No placeholder implementation instructions remain; each task names files, interfaces, tests, commands, and expected outcomes.
