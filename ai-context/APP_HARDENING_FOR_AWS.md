# App Hardening for AWS Hosting

The current app is intentionally simple and event-focused. Before routing a
public domain to it, make these targeted changes without turning the project
into a large production platform.

## Current Constraints

From the existing app context:

- `main.py` is the entire backend.
- App state lives in module-level globals.
- The app uses Flask sessions for attendee identity.
- `/admin` has no authentication.
- There is no CSRF protection.
- `python main.py` runs Flask debug mode on `0.0.0.0:80`.
- There are no tests.

These constraints are acceptable for local party use, but risky once the app is
publicly reachable.

## Required Before Public Exposure

### 1. Production Server

Do not run Flask debug mode in AWS.

Add `gunicorn` to `requirements.txt` and run:

```bash
gunicorn --workers 1 --threads 8 --bind 127.0.0.1:8081 main:app
```

Use one worker while state remains process-local. Multiple workers would create
multiple independent copies of the signup/vote state.

### 2. Admin Authentication

Add a simple password gate for `/admin`.

Minimum acceptable design:

- Add `HALLOWEEN_ADMIN_PASSWORD` environment variable.
- Store `session["is_admin"] = True` after password entry.
- Add `/admin/login` and `/admin/logout`.
- Require admin session for all `/admin` GET and POST actions.
- Do not hard-code the password in the repo.

Optional but recommended:

- Use `hmac.compare_digest()` for password comparison.
- Add a small delay or generic error message after failed login.

### 3. Redis Persistent State

The event should survive a process restart.

Required persistence:

- Redis at `172.31.118.0:6379`, logical DB `1`, with key prefix `halloween:`.
- Load state from Redis at startup.
- Save after every mutation.
- Use a Redis lock around state mutations.
- Publish display changes through Redis pub/sub.

State to persist:

- Costume signup dataclass records
- Karaoke signup dataclass records
- Costume votes
- Registered users
- Submitted voter IDs
- Contest state
- Karaoke state
- Live display override
- Display update version

Implementation detail:

- Add `to_dict()` / `from_dict()` helpers for dataclasses or dedicated serializer
  functions.
- Keep the JSON format explicit and versioned:

```json
{
  "schema_version": 1,
  "costume_signups": [],
  "karaoke_signups": [],
  "costume_votes": [],
  "registered_users": {},
  "submitted_costume_votes": [],
  "contest_state": {},
  "karaoke_state": {},
  "live_display_override": null,
  "display_update_version": 0
}
```

### 4. Vault Secret Loading

Load the Flask secret key and admin password from Vault in AWS.

The current fallback `dev-secret-key` should remain development-only. Without a
stable secret, sessions may break after restart. With a public known fallback,
session cookies are not trustworthy.

### 5. Host and Proxy Awareness

When running behind ALB and nginx:

- The Flask app should bind only to `127.0.0.1`.
- nginx should set `X-Forwarded-Proto` and `Host`.
- If URL generation or secure-cookie behavior becomes important, add
  `ProxyFix` from Werkzeug with a narrow trusted proxy configuration.

## Strongly Recommended

### CSRF Protection

For a one-night app, simple session auth may be enough, but admin POSTs are
state-changing and public internet exposure makes CSRF possible.

Lowest-friction improvement:

- Generate a session CSRF token for admin pages.
- Include it as a hidden field in admin forms.
- Validate it on admin POST.

### State Backup and Export

Add an admin-only export route or a simple CLI command to dump
`halloween:state` from Redis as JSON. This makes it easy to preserve contest
results after the party.

### Basic Tests

Add focused Flask test-client coverage for:

- Login/check-in flow
- Admin auth requirement
- Costume signup
- Karaoke signup
- Voting opens/closes
- One ballot per session
- Persistence load/save round trip
- `/api/display-data` payload shape

## Avoid During First AWS Deployment

- Do not add SQL or Postgres for Halloween state.
- Do not use multiple gunicorn workers until Redis locking and pub/sub are tested.
- Do not create a new ALB just for this app.
- Do not put admin credentials in source files.
- Do not leave Flask debug mode enabled.

## Minimal Code Change Map

Likely files to touch:

- `requirements.txt`
  - Add `gunicorn`.
- `main.py`
  - Add admin login/logout.
  - Add auth guard for `/admin`.
  - Add Vault secret loading.
  - Add Redis state load/save helpers.
  - Call save helper after every mutation.
  - Change local run port behavior.
- `templates/admin_login.html`
  - New admin password form.
- `templates/admin.html`
  - Add logout link and optional CSRF hidden fields.
- `templates/base.html`
  - Add admin login/logout navigation only if needed.
- `AGENTS.md`
  - Note AWS deployment assumptions after implementation.

## Deployment Compatibility Notes

The existing GoodVines deploy workflow temporarily scales the API ASG to two
instances during deploy. If the Halloween app is installed only on the current
node, a new node launched during a GoodVines deployment may not have the
Halloween app until bootstrap/deploy automation is updated.

Choose one:

- Treat Halloween hosting as event-only and avoid GoodVines deploys during the
  event.
- Add Halloween install/bootstrap steps to the API launch template or deploy
  workflow.
- Use Redis shared state and make each API node capable of running the app.

For lowest effort and lowest cost, the event-only path is acceptable if the
operational constraint is explicit.
