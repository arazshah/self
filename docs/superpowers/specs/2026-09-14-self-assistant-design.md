# Self Assistant — Product and Technical Specification

## Goal

Build a private, Persian-speaking personal assistant delivered through a Bale bot. The user sends free-form voice or text; the system transcribes, classifies, extracts tasks/reminders/ideas/decisions and self-reported feelings, sends Solar Hijri-aware reminders, and provides daily and weekly reports. It must never execute payments, send external messages, or make decisions without explicit human action.

## Scope

The first release is a multi-user-capable but privacy-isolated service. Each Bale private chat maps to exactly one application user and has its own entries, extracted records, reminders, reports, and dashboard session. The owner may give the bot to other people; no user receives a list, search result, ID, or report belonging to another user.

The current static website content in the repository is out of scope and may be removed from the deployed application. Git history may remain intact.

## User experience

### Input

- Accept private-chat voice messages and text messages from Bale.
- Reject or ignore group/channel messages.
- Reply quickly with a receipt while asynchronous processing continues.
- For each processed entry, show a compact summary of extracted items with buttons for confirm, edit, keep-only-as-note, and delete.

### Ten categories

1. `task` — one-off or multi-step work.
2. `reminder` — something to remember at a date/time.
3. `follow_up` — call, message, or follow-up with a person.
4. `finance` — bill/payment information recorded for later action only.
5. `appointment` — meeting, doctor, class, delivery, or commitment.
6. `project` — professional/personal project, next step, blocker, decision.
7. `idea` — software, content, business, learning, or other idea.
8. `errand` — purchase, repair, government/office work, or outside task.
9. `decision` — problem, options, trade-offs, and an optional suggestion.
10. `reflection` — self-reported emotion, concern, satisfaction, habit, or relationship context.

An entry may produce multiple records. Every extracted record must retain source-entry ID, evidence text, confidence, and confirmation status.

### Solar Hijri scheduling

- Understand Persian Solar Hijri dates, relative expressions, weekdays, and common informal forms.
- Store the original phrase and the resolved UTC timestamp.
- Use `Asia/Tehran` as the default timezone; keep timezone per user setting.
- Ask a short clarification when day/year/time is ambiguous.
- Send a reminder once at or after the due time, with a retry-safe delivery record.
- Allow the user to snooze, complete, edit, or cancel a reminder.

### Daily and weekly reports

Daily report covers the previous local calendar day. Weekly report covers the user-configured week boundary. Reports must distinguish:

- facts directly stated by the user;
- model interpretation;
- optional suggestions.

Reflection output is observational only. It may say “طبق گفتهٔ خودت، دیروز خسته و نگران بودی؛ دلیل‌هایی که گفتی...” but must not diagnose, score, or claim treatment. Suggestions are optional and clearly labeled as suggestions.

### Decision support

For decisions, the assistant may summarize the problem, list options, identify stated constraints, compare trade-offs, and suggest a small next step. It must not finalize the decision, contact anyone, purchase anything, or call an external API on the user’s behalf.

### Dashboard

Serve a Persian RTL dashboard at `https://self.araz.me` showing only the authenticated user’s:

- daily and weekly reports;
- entries and transcripts;
- records grouped by category;
- reminders and statuses;
- ideas and decision notes;
- settings for timezone, report time, week start, and raw-audio retention.

The dashboard login link is requested from the Bale bot. The bot generates a cryptographically random, hashed, single-use token bound to the Bale user and sends a link to `APP_BASE_URL/auth/claim/<token>`. The token expires after 10 minutes, is consumed transactionally, and then redirects to a secure session-cookie dashboard.

## Architecture

```text
Bale private chat
    ↓ webhook
FastAPI ingress + user/chat isolation + idempotency
    ↓ SQLite-backed job state
Background processing loop
    ↓
AvalAI transcription → AvalAI structured extraction
    ↓
Validated records → reminders/reports → Bale notification
    ↑
FastAPI dashboard with one-time-link session
```

### Components

- `bale`: update parsing, webhook verification/path secret, file download, message sending, callback handling.
- `ingestion`: idempotent receipt of updates and creation of entries/jobs.
- `ai`: AvalAI transcription and structured extraction adapters.
- `domain`: category records, date resolution, validation, confirmation state transitions.
- `scheduler`: due reminders and daily/weekly digest jobs with SQLite-safe claiming.
- `auth`: one-time dashboard links, session cookies, logout, expiry, and CSRF protection for mutations.
- `dashboard`: authenticated HTML/JSON routes and RTL templates.
- `storage`: SQLAlchemy/SQLite models, migrations or startup schema creation, and user-scoped repositories.

## Data isolation requirements

- The stable tenant key is the Bale private `chat_id`.
- Every data table containing user data has `user_id`; repositories require `user_id` as an explicit argument.
- Authentication middleware resolves `session.user_id`; handlers never accept a client-supplied user ID for normal reads/writes.
- All read and write queries include the authenticated user scope.
- Callback buttons carry opaque record IDs; handlers re-check ownership before mutation.
- One-time tokens store only a hash, user ID, expiry, consumed timestamp, and creation metadata.
- No transcript/audio/LLM payload is written to ordinary application logs.

## AvalAI integration

Use an OpenAI-compatible HTTP client with `https://api.avalai.ir/v1` as the configurable base URL.

- Transcription uses `/audio/transcriptions` with the configured `AVALAI_TRANSCRIBE_MODEL` and `language=fa`.
- Extraction and report generation use the configured text model.
- Extraction uses JSON Schema/structured output when the selected AvalAI route supports it; otherwise the response is parsed and validated with Pydantic before persistence.
- The system must handle refusal, incomplete output, malformed JSON, timeout, rate limit, and provider outage without creating unverified reminders.
- Model name, schema version, and validation outcome are stored as non-sensitive processing metadata.
- Raw provider payloads are not persisted by default.

## Configuration

Required Coolify environment variables:

```text
BALE_BOT_TOKEN
BALE_WEBHOOK_SECRET
AVALAI_API_KEY
AVALAI_TRANSCRIBE_MODEL
AVALAI_TEXT_MODEL
SESSION_SECRET
APP_BASE_URL=https://self.araz.me
DATABASE_PATH=/data/self.sqlite3
```

Optional:

```text
DEFAULT_TIMEZONE=Asia/Tehran
RAW_AUDIO_RETENTION_HOURS=24
DAILY_DIGEST_HOUR=8
LOG_LEVEL=INFO
```

The application must fail fast with a clear startup error when required secrets are missing. Secrets must never be committed or displayed.

## Security and privacy

- HTTPS is mandatory for webhook and dashboard.
- Use secure, HttpOnly, SameSite cookies with a bounded session lifetime.
- Use a dedicated random webhook path/secret and verify the request before parsing expensive content.
- Restrict processing to private chats and rate-limit users.
- Normalize and size-limit downloaded audio before passing it to AvalAI.
- Delete raw audio according to retention setting; transcript deletion must also remove derived records, embeddings, reports, jobs, and sessions where applicable.
- Redact secrets and personal content from error logs.
- No automatic financial action, external messaging, or arbitrary LLM tool execution.
- Dashboard mutation endpoints require CSRF protection and ownership checks.

## Non-goals

- Therapy, medical diagnosis, mental-health scoring, or emergency monitoring.
- Automatic payment, calling, messaging, shopping, or calendar mutation.
- Group-chat processing.
- Multi-user sharing, team workspaces, or admin browsing of users’ private content.
- Perfect memory or fully autonomous life management.

## Acceptance criteria

1. A private Bale voice message is processed once even if the webhook is retried.
2. A second user cannot read or mutate the first user’s entries, reminders, reports, or tokens.
3. A Persian Solar Hijri reminder is sent at the correct user-local time and only once.
4. Ambiguous dates result in a clarification request rather than a guessed reminder.
5. A daily report includes only the selected user’s previous-day records.
6. A weekly report includes only the selected user’s configured week.
7. A one-time dashboard link expires, is single-use, and cannot be used by another Bale user.
8. AvalAI failures leave the entry recoverable and do not create unconfirmed actions.
9. The application starts in Coolify using only environment-provided secrets and a persistent SQLite volume.
10. All high-risk operations remain suggestions or reminders and require explicit user action.
