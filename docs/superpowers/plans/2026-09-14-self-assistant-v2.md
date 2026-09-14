# Self Assistant v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reviewable Bale buttons, Persian date presentation, full owned CRUD, professional dashboard tabs, and complete daily/weekly reports.

**Architecture:** Keep FastAPI, SQLAlchemy and the single-process scheduler. Add soft-delete/version fields to the existing models, route all Bale callbacks through a small command dispatcher, and centralize Persian formatting in `time_utils.py`. Dashboard queries remain explicitly user-scoped and all external calls happen outside SQLite write transactions.

**Tech Stack:** FastAPI, SQLAlchemy 2, SQLite WAL, Jinja2, httpx, jdatetime, AvalAI, Bale Bot API.

**Spec:** `docs/superpowers/specs/2026-09-14-self-assistant-v2-design.md`

## Global Constraints

- Store instants in UTC; display user-facing dates and times in the user's timezone as Persian Solar Hijri.
- Never perform payments, external messages, or other irreversible actions automatically.
- Every read/write of user data must be scoped by `user_id`.
- Every POST dashboard mutation requires CSRF; every Bale callback requires chat ownership.
- Audio bytes are not persisted locally.
- Keep one Coolify replica while the scheduler is in-process.
- Use TDD: write a failing test, run it, implement the minimum, rerun the focused test, then the full suite.

### Task 1: Model and repository lifecycle support

**Files:**
- Modify: `app/models.py`
- Modify: `app/repositories.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:** Add `deleted_at` to Entry/ExtractedRecord/Reminder, `revision` to Entry, and repository methods `get_owned_entry`, `get_owned_record`, `update_entry_text`, `soft_delete_entry`, `soft_delete_record`, `soft_delete_reminder`, and `list_for_user(..., include_deleted=False)`.

- [ ] Write failing tests for owned CRUD, soft deletion, and revision increment.
- [ ] Run `pytest tests/test_lifecycle.py -q` and confirm missing-method/schema failure.
- [ ] Add nullable UTC `deleted_at` fields, Entry `revision`, and repository methods with owner predicates.
- [ ] Rerun focused tests, then `pytest -q`.
- [ ] Commit: `feat: add owned record lifecycle support`.

### Task 2: Central Persian display and input helpers

**Files:**
- Modify: `app/time_utils.py`
- Modify: `app/reports.py`
- Test: `tests/test_time_utils.py`

**Interfaces:** Add `format_persian_datetime(value, timezone_name)`, `format_persian_date(value, timezone_name)`, `format_persian_time(value, timezone_name)`, and `period_bounds(kind, reference, user)`.

- [ ] Write failing tests for Persian digits, date, time, and Tehran conversion.
- [ ] Run focused tests and confirm missing helper failure.
- [ ] Implement helpers using `jdatetime` and `ZoneInfo`; make report periods use them.
- [ ] Rerun focused and full tests.
- [ ] Commit: `feat: centralize Persian date presentation`.

### Task 3: Review and callback protocol for Bale

**Files:**
- Modify: `app/bale.py`
- Create: `app/bale_callbacks.py`
- Modify: `app/web.py`
- Test: `tests/test_bale_callbacks.py`

**Interfaces:** Add `callback_query` parsing, `answer_callback_query`, `edit_message_text`, and `build_entry_keyboard(entry_id, dashboard_url)`. Callback IDs use `entry:confirm:<id>`, `entry:edit:<id>`, `entry:delete:<id>`, `reminder:done:<id>`, `reminder:snooze:<id>`, and `reminder:cancel:<id>`.

- [ ] Write failing tests for callback parsing, keyboard shape, and owner rejection.
- [ ] Run focused tests and confirm missing protocol failure.
- [ ] Implement Bale methods and a dispatcher that checks callback chat ID against the owning user.
- [ ] Replace raw dashboard-link message with a button keyboard; keep one-time session URL as the URL button target.
- [ ] Rerun focused and full tests.
- [ ] Commit: `feat: add Bale review buttons and callbacks`.

### Task 4: Reprocess and CRUD service

**Files:**
- Create: `app/services.py`
- Modify: `app/pipeline.py`
- Modify: `app/web.py`
- Test: `tests/test_reprocess.py`

**Interfaces:** Add `reprocess_entry(session, entry_id, user_id, new_text, ai_client, notifier, now)` and `delete_entry(session, entry_id, user_id)`. Reprocessing soft-deletes old extracted records/reminders, increments revision, and invokes extraction again.

- [ ] Write failing tests for text correction causing a new category/date and for cross-user rejection.
- [ ] Run focused tests and confirm missing service failure.
- [ ] Implement the service with owner predicates and transaction boundaries before network calls.
- [ ] Connect dashboard edit/delete forms and Bale edit state to the service.
- [ ] Rerun focused and full tests.
- [ ] Commit: `feat: reprocess edited entries safely`.

### Task 5: Reminder mutations and Persian rendering

**Files:**
- Modify: `app/scheduler.py`
- Modify: `app/web.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/templates/report.html`
- Test: `tests/test_reminder_actions.py`

**Interfaces:** Add `snooze_reminder(session, reminder_id, user_id, until)`, `complete_reminder(...)`, and `cancel_reminder(...)`; render all reminder timestamps through Persian helpers.

- [ ] Write failing tests for complete, snooze-to-tomorrow, cancel, ownership, and Persian display.
- [ ] Run focused tests and confirm missing actions.
- [ ] Implement actions and wire both HTML forms and Bale callback dispatcher.
- [ ] Rerun focused and full tests.
- [ ] Commit: `feat: manage reminders from Bale and dashboard`.

### Task 6: Dashboard information architecture and category views

**Files:**
- Modify: `app/web.py`
- Modify: `app/reports.py`
- Modify: `app/templates/dashboard.html`
- Modify: `app/templates/base.html`
- Modify: `app/static/style.css`
- Test: `tests/test_dashboard_views.py`

**Interfaces:** Add scoped dashboard query helpers for `today`, `week`, `category`, and `all`; expose category metadata `{label, emoji}`.

- [ ] Write failing tests for today/week/category filters, emoji labels, and deleted-item exclusion.
- [ ] Run focused tests and confirm missing view behavior.
- [ ] Implement tab/filter query parameters and responsive RTL cards.
- [ ] Add edit/delete controls for Entries, Records, and Reminders.
- [ ] Rerun focused and full tests.
- [ ] Commit: `feat: add professional scoped dashboard views`.

### Task 7: Complete daily and weekly textual reports

**Files:**
- Modify: `app/reports.py`
- Modify: `app/jobs.py`
- Modify: `app/templates/report.html`
- Test: `tests/test_reports.py`

**Interfaces:** `build_digest` must include the Persian period label, entries with local timestamp, completed/open reminders, category groups, reflection evidence, and suggestion text.

- [ ] Write failing tests for previous-day/previous-week boundaries, Persian labels, completed reminders, and textual summaries.
- [ ] Run focused tests and confirm missing report fields.
- [ ] Implement deterministic aggregation from structured AvalAI records; preserve user wording as evidence and avoid diagnosis.
- [ ] Rerun focused and full tests.
- [ ] Commit: `feat: enrich Persian daily and weekly reports`.

### Task 8: Verification and deployment handoff

**Files:**
- Modify: `README.md`
- Modify: `Dockerfile`
- Test: full suite and container smoke test

- [ ] Run `pytest -q`, `ruff check app tests`, and `git diff --check`.
- [ ] Build the Docker image and verify `/health` in a one-container smoke test.
- [ ] Document button flow, edit flow, Persian date behavior, one-replica requirement, and Coolify redeploy instructions.
- [ ] Commit: `docs: document assistant v2 operations`.
- [ ] Push `master` and report exact commit and verification results.
