# AlertFlow

I built this because alert fatigue is a real problem. Same alert firing 50 times, going to the wrong person, at 3am. AlertFlow sits between your monitoring tools and your engineers — it deduplicates, routes, and escalates so the right person gets paged once, not 47 times.

---

## Why I Built This

Most monitoring setups have the same issues:

- Prometheus re-sends every 30 seconds until the issue resolves — your engineer gets 60 pages for one problem
- Alerts go to a general channel instead of the team that owns the service
- A low severity disk warning wakes someone up at 3am the same way a database outage does
- No visibility into how many alerts are actually firing vs being swallowed

AlertFlow is my attempt to fix all four with a single service that sits in front of your alerting stack.

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
Dashboard API → live counts available at /dashboard/summary
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

SEV1 → PagerDuty, 0 second wait   (wake someone up)
SEV2 → Slack, 5 minute wait       (might self-resolve)
SEV3 → Slack, 15 minute wait      (check in the morning)
SEV4 → Email, 0 second wait       (just log it)

Delayed notifications use `asyncio.create_task()` — the webhook response returns immediately and the notification fires in the background after the wait period.

---

## Key Results

Tested end-to-end with real webhook payloads:

| Test | Input | Result |
|------|-------|--------|
| SEV1 postgres alert | critical severity, job=postgres | routed to platform-oncall via priority 10 rule |
| payments warning | warning severity, job=payments | routed to payments-team via priority 20 rule |
| Same alert again | identical labels as above | deduplicated=true, routing skipped |
| PagerDuty disk alert | warning via PagerDuty webhook | routed to default-oncall via catch-all rule |

Dashboard after 4 tests:

```json
{
  "total_alerts": 4,
  "by_status": { "routed": 3, "deduplicated": 1 },
  "by_severity": { "SEV1": 1, "SEV2": 2, "SEV3": 1 },
  "active_dedup_windows": 3
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
- **No alert resolution flow** — when Prometheus sends `endsAt`, AlertFlow doesn't currently mark alerts resolved or clear the Redis fingerprint. Same alert firing again after resolving might get deduplicated incorrectly.
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


## Project Structure

app/
├── main.py               FastAPI app + router registration
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
│   └── escalation.py     Severity-based notification scheduler
└── db/
├── database.py       Async engine + session factory
└── migrations/       Alembic migration files

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

API docs at **http://localhost:8000/docs**

---

## API Endpoints

POST /ingest/prometheus          Prometheus Alertmanager webhook
POST /ingest/pagerduty           PagerDuty Events API v2 webhook
GET  /dashboard/summary          Counts by status, severity, service + Redis stats
GET  /dashboard/alerts           Alert list — filter by status/severity/service/team
GET  /dashboard/alerts/{id}      Full alert details including raw labels
GET  /docs                       Interactive Swagger UI

---

## Learning Outcomes

Things I didn't fully appreciate before building this:

**Redis SET NX is underrated.** Most deduplication implementations I'd seen before used a read-then-write pattern with locks. SET NX does it in one atomic operation. No locks, no race conditions, TTL handled automatically.

**Async SQLAlchemy takes some getting used to.** The session management is different from the sync version. `get_db()` as a FastAPI dependency makes it clean once you understand the pattern, but the initial setup has a few gotchas — asyncpg, greenlet, engine configuration.

**Schema migrations from day one.** I set up Alembic before writing any application code. Every schema change went through a migration file. When I needed to verify the tables existed, I could check the migration history instead of guessing.

**Separation of concerns pays off early.** Keeping normalization, deduplication, routing, and escalation in separate files made debugging straightforward. When something broke, I knew exactly which file to look at.

**Port conflicts happen.** PostgreSQL defaulted to 5432 which was already in use on my machine. Docker made it a one-line fix in docker-compose.yml. Without containers that would have been a messy install conflict.

---

## What's Next

- [x] Wire up real Slack notifications in `fire_notification()`
- [ ] Add alert resolution endpoint — clear Redis fingerprint on resolve
- [ ] Replace `asyncio.create_task()` with Celery for reliable delayed escalations
- [ ] Add API key authentication on ingest endpoints
- [ ] Build a frontend dashboard — the API is ready, just needs a UI
- [ ] Write proper test coverage with pytest + FastAPI TestClient

---


