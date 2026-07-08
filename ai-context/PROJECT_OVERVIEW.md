# Project Overview

## Purpose

This repo contains a Flask web app for "Qiana and Tony's 2nd Annual Halloween Party." It supports attendee check-in, costume contest signup and voting, karaoke signup, admin management, and a large-format live display for a TV/projector.

The app is optimized for a short-lived party environment. Event state is
persisted in Redis as a compact JSON document, with module-level Python globals
remaining as a process-local cache in `main.py`.

## Runtime

- Python version: `.python-version` pins `3.11.9`.
- Dependencies: `requirements.txt` requires `flask>=3.0,<4.0` and
  `redis>=5.0,<6.0`; production also uses `gunicorn`.
- Entrypoint: `main.py`.
- Local run behavior: `python main.py` starts Flask debug mode on `0.0.0.0:80`.
- Secret key: `HALLOWEEN_APP_SECRET`, falling back to `dev-secret-key`.
- UI access is role-based through Flask sessions. Regular attendees register
  accounts stored in Redis app state. Only the admin password is loaded from
  Vault through `HALLOWEEN_ADMIN_PASSWORD`; the live display uses the same admin
  session.

Because the app binds to port 80, local execution may require elevated privileges or a port change for development.

## Production Deployment

Merged `main` commits deploy through GitHub Actions to the existing GoodVines
API EC2 Auto Scaling Group using AWS OIDC, AWS CLI, and SSM. The production
service runs as `halloween-party.service` behind nginx on `127.0.0.1:8081`.
Runtime secrets come from Vault through AWS IAM auth.

Public routes are hosted at `tnq-halloween.com` and
`www.tnq-halloween.com`. GoodVines isolation is a hard guardrail: deployment
must not restart GoodVines services, edit GoodVines source directories, or
change GoodVines nginx server blocks.

API ASG replacement instances are covered by launch template version `2`, which
preserves the existing GoodVines bootstrap and then installs Halloween from the
current `main` branch. Normal GitHub Actions deploys still install the exact
merged commit SHA on currently running API instances.

## Local Redis Development

Use the existing local Homebrew Redis service while migrating app state to
Redis. It listens on `127.0.0.1:6379`, uses logical DB `1` for this app, and
requires ACL authentication.

Local Redis env defaults are documented in `.env.example`:

- `HALLOWEEN_REDIS_HOST=127.0.0.1`
- `HALLOWEEN_REDIS_PORT=6379`
- `HALLOWEEN_REDIS_DB=1`
- `HALLOWEEN_REDIS_USERNAME=<local-redis-acl-user>`
- `HALLOWEEN_REDIS_PASSWORD=<local-redis-acl-password>`
- `HALLOWEEN_REDIS_PREFIX=halloween`
- `HALLOWEEN_REDIS_URL=redis://<local-redis-acl-user>:<local-redis-acl-password>@127.0.0.1:6379/1`

At the time this context was updated, the ACL credentials were configured in
`/opt/homebrew/etc/redis.conf` with the default user disabled. Do not commit the
password into repo files; read it from that local config when needed.

```bash
redis-cli -h 127.0.0.1 -p 6379 --user '<local-redis-acl-user>' \
  -a '<local-redis-acl-password>' --no-auth-warning -n 1 ping
```

## User Flows

1. `/` redirects to the admin-configured public landing page, defaulting to
   `/rsvp`.
2. `/rsvp`, `/party/login`, and `/party/register` require the party code before
   guests can see RSVP, sign-in, or account creation forms.
3. `/live-display` redirects to `/admin/login` until the browser session has
   the `admin` role, then shows rotating event cards and current signup counts.
4. Attendees visit `/party`, are redirected to `/party/login` if not
   signed in, can create an account at `/party/register`, then see the
   party dashboard.
5. Attendees can submit costume entries at `/party/costumes`.
6. Attendees can submit karaoke songs at `/party/karaoke`.
7. Admins sign in at `/admin/login` and manage entries, public landing settings,
   party code settings, and event state at
   `/admin`.
8. When the admin starts the costume contest, `/party/costumes/vote` becomes available to logged-in guests.
9. Each logged-in guest can submit one complete ballot, scoring every costume from 1 to 10.
10. Admins can lock the winner, show winner/live override cards, restore the rotating display, and start the karaoke countdown.
11. Regular and admin sessions use one logout action in the header menu; it
    clears the current browser session regardless of role.

## State Model

Redis is the database. The canonical state document is stored at
`halloween:state` with schema version 2. The following globals in `main.py` are
the process-local cache:

- `costume_signups`: list of `CostumeSignup` dataclass instances with stable IDs.
- `karaoke_signups`: list of `KaraokeSignup` dataclass instances with stable IDs.
- `costume_ballots`: maps `user_id` to `{costume_id: score}`.
- `user_accounts`: maps normalized usernames to Redis-backed attendee account
  records with stable IDs and password hashes.
- `registered_users`: maps session `user_id` to display name.
- `submitted_costume_votes`: set of `user_id` values that already voted.
- `live_display_override`: current full-screen override card, or `None`.
- `landing_page_target`: admin-selected root redirect target, defaulting to
  `/rsvp`.
- `party_code_hash` and `party_code_hint`: invite-code gate settings for RSVP,
  attendee login, and attendee account creation. The code itself is not stored
  in plaintext.
- `contest_state`: voting open/closed, winner lock, scoreboard card visibility.
- `karaoke_state`: whether karaoke has been started and current singer metadata.
- `display_update_version`: monotonic counter used by server-sent events.

Schema version 1 Redis state with index-aligned `costume_votes` is upgraded on
load into ID-keyed `costume_ballots`.

## Design Shape

This is intentionally a simple Flask/Jinja app:

- `main.py` defines routes, in-memory state, scoring helpers, and live-display API payloads.
- `templates/` contains Jinja templates for attendee, admin, voting, and display pages.
- `static/styles.css` styles normal attendee/admin pages.
- `static/display.css` styles the TV/live-display experience.
- `static/display.js` drives live-display rotation, override rendering, SSE updates, and polling.
- `static/slides.js` rotates dashboard highlight slides.

The visual style is dark Halloween-themed: black backgrounds, red accents, glowing borders, and large display typography.
The responsive UX pass is complete: live-display cards scale for normal browser
windows, attendee pages use a compact menu nav with a single logout action,
touch-safe forms, and admin add/edit forms collapse into disclosure rows by
default on mobile-friendly layouts.
