# Project Overview

## Purpose

This repo contains a single-process Flask web app for "Qiana and Tony's 2nd Annual Halloween Party." It supports attendee check-in, costume contest signup and voting, karaoke signup, admin management, and a large-format live display for a TV/projector.

The app is optimized for a short-lived party environment, not durable production hosting. All signups, votes, logged-in guests, contest status, karaoke status, and live-display overrides are stored in module-level Python globals in `main.py`.

## Runtime

- Python version: `.python-version` pins `3.11.9`.
- Dependencies: `requirements.txt` requires `flask>=3.0,<4.0` and
  `redis>=5.0,<6.0`.
- Entrypoint: `main.py`.
- Local run behavior: `python main.py` starts Flask debug mode on `0.0.0.0:80`.
- Secret key: `HALLOWEEN_APP_SECRET`, falling back to `dev-secret-key`.

Because the app binds to port 80, local execution may require elevated privileges or a port change for development.

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

1. `/` redirects to `/live-display`.
2. `/live-display` shows rotating event cards and current signup counts.
3. Attendees visit `/halloween`, are redirected to `/halloween/login` if not checked in, then see the party dashboard.
4. Attendees can submit costume entries at `/costume-signup`.
5. Attendees can submit karaoke songs at `/karaoke-signup`.
6. Admins manage entries and event state at `/admin`.
7. When the admin starts the costume contest, `/costume-voting` becomes available to logged-in guests.
8. Each logged-in guest can submit one complete ballot, scoring every costume from 1 to 10.
9. Admins can lock the winner, show winner/live override cards, restore the rotating display, and start the karaoke countdown.

## State Model

The app has no database. The following globals in `main.py` are the source of truth:

- `costume_signups`: list of `CostumeSignup` dataclass instances.
- `karaoke_signups`: list of `KaraokeSignup` dataclass instances.
- `costume_votes`: list of vote lists, aligned by index with `costume_signups`.
- `registered_users`: maps session `user_id` to display name.
- `submitted_costume_votes`: set of `user_id` values that already voted.
- `live_display_override`: current full-screen override card, or `None`.
- `contest_state`: voting open/closed, winner lock, scoreboard card visibility.
- `karaoke_state`: whether karaoke has been started and current singer metadata.
- `display_update_version`: monotonic counter used by server-sent events.

The helper `ensure_costume_votes_alignment()` keeps `costume_votes` aligned when costume entries are added, removed, or reordered.

## Design Shape

This is intentionally a simple Flask/Jinja app:

- `main.py` defines routes, in-memory state, scoring helpers, and live-display API payloads.
- `templates/` contains Jinja templates for attendee, admin, voting, and display pages.
- `static/styles.css` styles normal attendee/admin pages.
- `static/display.css` styles the TV/live-display experience.
- `static/display.js` drives live-display rotation, override rendering, SSE updates, and polling.
- `static/slides.js` rotates dashboard highlight slides.

The visual style is dark Halloween-themed: black backgrounds, red accents, glowing borders, and large display typography.
