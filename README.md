# AlertFlow

I built this because alert fatigue is a real problem. Same alert firing 50 times, going to the wrong person, at 3am. This is my attempt at a simple routing engine that sits in front of your monitoring tools and does the boring work of deduplication, routing, and escalation.

## What it does

Accepts webhooks from Prometheus and PagerDuty, figures out if it's seen the alert before (Redis, 5 minute window), routes it to the right team based on configurable rules, and escalates based on severity. SEV1 pages immediately. SEV2 waits 5 minutes — maybe it resolves itself. SEV3 waits 15.

There's a dashboard API if you want to see what's happening.

## Stack

- Python + FastAPI — the API layer
- Redis — deduplication (fingerprint TTL window)
- PostgreSQL — alert storage, routing rules, escalation policies
- Docker — local Redis + Postgres without the mess
- Alembic — database migrations

## Run it locally

```bash
# Start the databases
docker-compose up -d

# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Seed some routing rules
python3 seed.py

# Start the server
uvicorn app.main:app --reload
```

API docs at http://localhost:8000/docs once it's running.

## How routing works

Rules are checked in priority order. First match wins. A rule can match on severity, service name, team, or any combination. Leave a field blank and it matches anything.