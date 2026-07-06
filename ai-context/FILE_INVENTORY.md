# File Inventory

## Tracked Source Files

| File | Purpose |
| --- | --- |
| `main.py` | Flask app entrypoint, route definitions, Redis-backed state cache/serialization, admin auth, CSRF, admin actions, voting logic, scoreboard helpers, live-display JSON/SSE APIs. |
| `requirements.txt` | Python dependency declaration; includes Flask 3.x and redis-py for the Redis migration. |
| `.env.example` | Example local Redis environment values for the existing `127.0.0.1:6379` ACL-protected Redis, DB `1`, and the `halloween` prefix. |
| `tests/test_redis_state.py` | Unit tests for Redis-backed state serialization, load/save behavior, route persistence, voting, admin reorder alignment, display update publishing, and JSON exports using an in-memory Redis fake. |
| `static/styles.css` | Shared Halloween-themed styles for attendee and admin pages. |
| `static/display.css` | Dedicated large-format live-display styles, override cards, CTA layout, scoreboard layout, and karaoke display panels. |
| `static/display.js` | Live-display client logic: card rotation, API polling, SSE reconnects, override rendering, scoreboard rendering, karaoke countdown and panel rotation. |
| `static/slides.js` | Dashboard event-highlight slide rotation. |
| `templates/base.html` | Shared attendee/admin layout with header navigation, signed-in user display, footer, and script block. |
| `templates/index.html` | Attendee dashboard for `/halloween`: contest banners, welcome callout, slides, costume and karaoke summaries. |
| `templates/halloween_login.html` | Check-in form for collecting a session username. |
| `templates/costume_signup.html` | Costume signup form and submitted costume list. |
| `templates/karaoke_signup.html` | Karaoke signup form and submitted karaoke lineup. |
| `templates/costume_voting.html` | Costume voting ballot and one-vote confirmation state. |
| `templates/admin_login.html` | Admin password form for `/admin/login`. |
| `templates/admin.html` | Admin dashboard for entry CRUD/reordering, contest controls, vote tally, winner state, and karaoke launch. |
| `templates/display.html` | Standalone full-screen live-display page and initial JSON bootstrap. |

## Untracked Local Files Present During Review

These files are present locally but not tracked by Git at the time this context was created:

| File | Purpose |
| --- | --- |
| `.python-version` | Local Python version pin, `3.11.9`. |
| `.DS_Store` | macOS folder metadata; binary, not app source. |
| `.idea/.gitignore` | PyCharm default ignore entries for shelf and workspace metadata. |
| `.idea/halloween-karaoke-costume-contest.iml` | PyCharm module file pointing at Python 3.11 SDK `venv-halloween`. |
| `.idea/misc.xml` | PyCharm project root manager and SDK metadata. |
| `.idea/modules.xml` | PyCharm module registration. |
| `.idea/vcs.xml` | PyCharm Git mapping. |
| `.idea/workspace.xml` | PyCharm local workspace/run/debug metadata, including a `main.py` run config and breakpoint. |
| `.idea/inspectionProfiles/Project_Default.xml` | PyCharm inspection profile, including ignored PEP8 naming rule N801. |
| `.idea/inspectionProfiles/profiles_settings.xml` | PyCharm inspection profile settings. |

## Generated Context Files

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Future-agent entry point with high-signal repo notes. |
| `ai-context/PROJECT_OVERVIEW.md` | Durable summary of app purpose, runtime, flows, state model, and design. |
| `ai-context/FEATURES.md` | Durable catalog of supported attendee, admin, contest, karaoke, display, and styling features. |
| `ai-context/ARCHITECTURE.md` | Durable route map, data flow, frontend behavior, constraints, and extension guidance. |
| `ai-context/FILE_INVENTORY.md` | Durable file-by-file inventory. |
| `ai-context/AWS_EXISTING_INFRA_HOSTING_PLAN.md` | Hosting plan for reusing the existing GoodVines ALB/EC2 infrastructure for `tnq-halloween.com`. |
| `ai-context/AWS_IMPLEMENTATION_CHECKLIST.md` | Step-by-step AWS, nginx, systemd, DNS, TLS, deploy, and smoke-test checklist. |
| `ai-context/APP_HARDENING_FOR_AWS.md` | App changes needed before public AWS exposure, including gunicorn, admin auth, persistence, and secrets. |
| `ai-context/NO_SQL_DATA_POLICY.md` | Explicit policy that Halloween must not use SQL and should persist state in Redis. |
| `ai-context/REDIS_CONNECTION_REQUIREMENTS.md` | Redis connection requirements for using the existing GoodVines services EC2 Redis instance without key collisions. |
| `ai-context/REDIS_STATE_DESIGN.md` | Redis key, locking, pub/sub, backup, and persistence design for Halloween event state. |
| `ai-context/REDIS_MIGRATION_PLAN.md` | Durable progress tracker for the in-progress process-memory to Redis refactor. |
| `ai-context/REDIS_ENHANCEMENT_IMPLEMENTATION_PLAN.md` | Durable progress tracker for schema v2, ID-keyed ballots, auth/CSRF, and Redis interaction enhancements. |
| `ai-context/GITLAB_AWS_DEPLOYMENT_DESIGN.md` | GitLab CI/CD design for deploying through AWS CLI and SSM to the existing EC2 ASG. |
| `ai-context/VAULT_SECRETS_DESIGN.md` | Design for obtaining Halloween app secrets from the existing GoodVines Vault using AWS IAM auth. |

## Repository Organization

```text
.
├── AGENTS.md
├── ai-context/
│   ├── ARCHITECTURE.md
│   ├── APP_HARDENING_FOR_AWS.md
│   ├── AWS_EXISTING_INFRA_HOSTING_PLAN.md
│   ├── AWS_IMPLEMENTATION_CHECKLIST.md
│   ├── FEATURES.md
│   ├── FILE_INVENTORY.md
│   ├── GITLAB_AWS_DEPLOYMENT_DESIGN.md
│   ├── NO_SQL_DATA_POLICY.md
│   ├── PROJECT_OVERVIEW.md
│   ├── REDIS_ENHANCEMENT_IMPLEMENTATION_PLAN.md
│   ├── REDIS_CONNECTION_REQUIREMENTS.md
│   ├── REDIS_MIGRATION_PLAN.md
│   ├── REDIS_STATE_DESIGN.md
│   └── VAULT_SECRETS_DESIGN.md
├── main.py
├── .env.example
├── requirements.txt
├── static/
│   ├── display.css
│   ├── display.js
│   ├── slides.js
│   └── styles.css
├── tests/
│   └── test_redis_state.py
└── templates/
    ├── admin.html
    ├── admin_login.html
    ├── base.html
    ├── costume_signup.html
    ├── costume_voting.html
    ├── display.html
    ├── halloween_login.html
    ├── index.html
    └── karaoke_signup.html
```
