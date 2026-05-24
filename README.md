# AlertFlow

I built this because alert fatigue is a real problem. Same alert firing 50 times, going to the wrong person, at 3am. AlertFlow sits between your monitoring tools and your engineers — it deduplicates, routes, and escalates so the right person gets paged once, not 47 times.

## Why I Built This

Alert fatigue is a real thing. I've seen setups where the same alert fires 60 times 
because Prometheus retries every 30 seconds. By the time someone looks at it, 
there's a wall of identical notifications and nobody knows which one to act on.

The other problem is routing. Most teams have one big #alerts channel that 
everything goes into. A disk warning from a dev box and a production database 
outage look identical at 3am.

I wanted something simple that sits in the middle — catches duplicates, 
figures out who actually owns the problem, and only wakes someone up 
if it's worth waking them up.

---

## How It Works — Pipeline Overview

Prometheus or PagerDuty sends a webhook
↓
Normalize → convert to internal format (AlertCreate)
↓
Fingerprint → MD5 hash of sorted labels
↓
Redis check → seen this fingerprint in last 5 min?
YES → mark as deduplicated, stop here
NO  → save to PostgreSQL, continue
↓
Routing engine → loop rules in priority order, first match wins
↓
Escalation → fire or schedule notification based on severity
↓
Slack → formatted message with severity, service, team, routed_to
↓
Dashboard → live counts and alert list at /ui

Two sources go in. One normalized pipeline handles both. The source stops mattering after normalization.

---

Two sources go in. One normalized pipeline handles both. The source stops mattering after normalization.

---

## Approach

### Deduplication with Redis SET NX

The whole dedup system is one Redis command:

```bash
SET alertflow:dedup:{fingerprint} "1" EX 300 NX
```

- `NX` — only set if key doesn't exist (atomic check + set, no race condition)
- `EX 300` — key expires automatically after 5 minutes, no cleanup needed
- If it sets → new alert. If it doesn't → duplicate, skip routing.

I chose Redis over a database-based approach because it's in-memory (sub-millisecond), the TTL handling is built in, and SET NX gives you atomicity for free.

### Routing with Priority-Ordered Rules

Rules are stored in PostgreSQL and checked in priority order. First match wins. Each rule can match on severity, service name, team, or any combination — leave a field blank and it matches anything.

Priority 10  — SEV1 → platform-oncall        (checked first)
Priority 20  — payments service → payments-team
Priority 30  — infra team → infra-oncall
Priority 999 — catch-all → default-oncall    (checked last)

Adding a new rule is a database insert. No code changes, no deploys.

### Escalation by Severity

SEV1 → Slack, 0 second wait    (page immediately)
SEV2 → Slack, 5 minute wait    (might self-resolve)
SEV3 → Slack, 15 minute wait   (check in the morning)
SEV4 → Slack, 0 second wait    (just log it)

Delayed notifications use `asyncio.create_task()` — the webhook response returns immediately and the notification fires in the background after the wait period.

### Slack Notifications

Real notifications via Slack incoming webhook. Uses Block Kit format:

🔴 SEV1 — Checkout service failing
Service          Team
checkout         payments
Routed To        Source
platform-oncall  prometheus
Alert ID: 453aa46c-efa2-4cbf-aba6-dd7b6f26c4c2

Falls back to terminal print if `SLACK_WEBHOOK_URL` is not set.

### Frontend Dashboard

Single HTML file served at `/ui`. No React, no build tools — just HTML, CSS, and vanilla JS talking directly to the API.

- Live stat cards — total, routed, deduplicated, active dedup windows
- Severity bars with color indicators (red/amber/blue/green)
- Noisiest services list
- Recent alerts table with filter buttons (All / Routed / Deduped / Active)
- Auto-refreshes every 30 seconds
- Green pulsing dot shows live API connection

---

## Key Results

Tested end-to-end with real webhook payloads:

| Test | Input | Result |
|------|-------|--------|
| SEV1 postgres alert | critical severity, job=postgres | routed to platform-oncall, Slack notified |
| payments warning | warning severity, job=payments | routed to payments-team, Slack notified |
| Same alert again | identical labels as above | deduplicated=true, routing skipped |
| PagerDuty disk alert | warning via PagerDuty webhook | routed to default-oncall via catch-all |

Dashboard after testing:
```json
{
  "total_alerts": 11,
  "by_status": { "routed": 9, "deduplicated": 2 },
  "by_severity": { "SEV1": 8, "SEV2": 2, "SEV3": 1 },
  "active_dedup_windows": 0
}
```

---

## Where It Works

- High-volume alert environments where the same alert fires repeatedly
- Teams that route alerts manually today and want to automate it
- Anyone running Prometheus Alertmanager or PagerDuty
- Small to medium teams — the priority rule system is simple enough to manage without extra tooling

---

## Where It Breaks

Being honest about the limitations:

- **No persistent escalation** — delayed notifications use `asyncio.create_task()` which dies if the process restarts. A Celery worker with Redis as broker would fix this.
- **No alert resolution flow** — when Prometheus sends `endsAt`, AlertFlow doesn't currently mark alerts resolved or clear the Redis fingerprint.
- **No auth on ingest endpoints** — anyone who can reach the server can POST alerts. Needs an API key check before going anywhere near production.
- **Single process** — no horizontal scaling story yet. One instance, one event loop.

---

## Stack

| Tool | Version | Role |
|------|---------|------|
| Python | 3.13 | Language |
| FastAPI | latest | Web framework + Swagger UI |
| Redis | 7 | Deduplication fingerprint store |
| PostgreSQL | 15 | Alert storage, routing rules, policies |
| SQLAlchemy | latest | ORM — async queries |
| Alembic | latest | Database migrations |
| Pydantic | v2 | Request validation + settings |
| Docker | — | Local Redis + PostgreSQL |
| uvicorn | — | ASGI server |
| Slack | — | Real-time alert notifications via incoming webhook |

---

## Project Structure

app/
├── main.py               FastAPI app + router registration + static files
├── config.py             pydantic-settings reads .env
├── models/
│   ├── alert.py          Alert table + enums + Pydantic schemas
│   └── policy.py         EscalationPolicy + RoutingRule tables
├── routers/
│   ├── ingest.py         POST /ingest/prometheus and /ingest/pagerduty
│   └── dashboard.py      GET /dashboard/summary, /alerts, /alerts/{id}
├── services/
│   ├── dedup.py          Redis SET NX deduplication
│   ├── routing.py        Priority rule matching engine
│   └── escalation.py     Severity-based notification + real Slack webhook
└── db/
├── database.py       Async engine + session factory
└── migrations/       Alembic migration files
static/
└── dashboard.html        Frontend dashboard — served at /ui

---

## Run It Locally

```bash
# Start Redis and PostgreSQL
docker-compose up -d

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create database tables
alembic upgrade head

# Seed routing rules and escalation policies
python3 seed.py

# Start the server
uvicorn app.main:app --reload
```

- API docs at **http://localhost:8000/docs**
- Live dashboard at **http://localhost:8000/ui**

---

## Environment Variables

```bash
DATABASE_URL=postgresql+asyncpg://alertflow:alertflow@localhost:5433/alertflow
REDIS_URL=redis://localhost:6379
DEDUP_WINDOW_SECONDS=300
APP_ENV=development
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

---

## API Endpoints

POST /ingest/prometheus          Prometheus Alertmanager webhook
POST /ingest/pagerduty           PagerDuty Events API v2 webhook
GET  /dashboard/summary          Counts by status, severity, service + Redis stats
GET  /dashboard/alerts           Alert list — filter by status/severity/service/team
GET  /dashboard/alerts/{id}      Full alert details including raw labels
GET  /ui                         Frontend dashboard
GET  /docs                       Interactive Swagger UI

---

## Things I Learned Building This

**Redis SET NX saved me from overengineering.** My first instinct was to build 
a dedup check using PostgreSQL with a timestamp query. Then I remembered SET NX 
exists — one atomic command, built-in expiry, nothing to clean up. 
Took 10 lines of code instead of 50.

**Async SQLAlchemy has sharp edges.** The greenlet dependency, asyncpg vs psycopg2 
for migrations vs runtime, session lifecycle in FastAPI dependencies — none of 
this is obvious from the docs. Got bitten by all three.

**Alembic from the start is worth it.** I almost skipped migrations and just used 
create_all(). Glad I didn't. When I needed to check if tables existed, 
I had a proper history instead of guessing.

**Slack silently dropped the attachments format.** Terminal said the webhook 
returned 200. Nothing showed up in Slack. Spent 20 minutes debugging before 
realizing modern Slack ignores legacy attachments entirely. Block Kit only.

**CORS bites you when you open HTML files directly.** Browser blocks fetch() 
calls to localhost from a file:// URL. Serving the dashboard through FastAPI's 
StaticFiles was the clean fix — one endpoint, no separate server.

## What's Next

✅ Wire up real Slack notifications
✅ Build a frontend dashboard
✅ Add API key authentication
✅ Add alert resolution endpoint
⬜ Replace asyncio.create_task() with Celery
✅ Write pytest tests

---

## License

MIT
