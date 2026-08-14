# Project Overview

## Purpose

This repo contains a Flask web app for "Qiana and Tony's 3rd Annual Halloween Party." It supports RSVP, attendee check-in, food/drink menu and drink ordering, costume contest signup and voting, karaoke signup, DJ playlist/playback controls, admin management, bartender operations, and a large-format live display for a TV/projector.

The app is optimized for a short-lived party environment. Event state is
persisted in Redis as a compact JSON document, with module-level Python globals
remaining as a process-local cache in `main.py`.

## Runtime

- Python version: `.python-version` pins `3.11.9`.
- Dependencies: `requirements.txt` requires Flask, redis-py, boto3, the Google
  API/OAuth clients, and hvac; production also uses gunicorn.
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
2. `/rsvp`, `/party/login`, and `/party/register` are public starting-flow pages
   with no party-code gate before the page renders.
3. `/rsvp` asks guests to RSVP, offers account creation/login as optional next
  steps, shows static party detail cards, renders a Google Maps embed and
  directions button when a map address is configured, then shows host update
  cards from newest to oldest. RSVP submissions require the admin-configured
  party code as a form field plus an email address, save independent entries
  for the admin RSVP list, and do not create attendee portal accounts. There is
  no guest opt-in checkbox for update emails.
  Successful RSVPs send a confirmation email with RSVP details plus Google
  Calendar and `.ics` calendar links when email is enabled. Successful public
  RSVPs also send a host notification email to the admin-configurable RSVP
  notification recipient, defaulting to `tgio1129@gmail.com`, when email is
  enabled.
4. `/live-display` redirects to `/admin/login` until the browser session has
   the `admin` role, then renders a fixed no-scroll TV shell. The title stays at
   the top, games rotate independently on the left, rotating cards retain the
   dominant center stage, active bar orders and temporary ready alerts occupy
   the right, and DJ information lives in the footer. Empty regions collapse
   and center stage grows automatically. The party-night experience remains
   available before `HALLOWEEN_PARTY_START` for host staging and testing.
5. Attendees visit `/party`, are redirected to `/party/login` if not
   signed in, can create an account at `/party/register`, or recover a
   forgotten account password through `/party/password-reset`, then see the
   party dashboard. Before the party date, `/party` keeps Event Highlights
   logistics-focused: party date/time, directions/map address, rideshare
   suggestions, potluck/overview details, and a light preview that costume
   contest, games, and karaoke happen later in the night. It hides event-night
   menu, costume, karaoke, drink-order, and voting navigation and should not
   promote party-night app actions before those routes are available. On the
   party date, `/party` switches to the event-night dashboard and may promote
   app usage, costume signup, karaoke signup, drink ordering, and live party
   updates. Admins can override this attendee experience gate from `/admin` for
   testing with Automatic, Pre-party, or Party day modes. Account creation sends
   a SES welcome email when email is enabled.
6. On the party date, attendees can submit costume entries at
   `/party/costumes`.
7. On the party date, attendees can search for and select an exact YouTube
   karaoke video at `/party/karaoke`, submit it for host approval, and track
   verification/approval/playlist/stage progress. The legacy optional-link flow
   remains available while the YouTube feature flag is disabled.
8. On the party date, attendees can view food and drink menu cards with images
   at `/party/menu` and order available/orderable drinks from the bar.
   Specialty drinks are limited to 3 included attendee orders; after 11:00 PM,
   4th+ specialty requests are allowed while supplies remain. `/party/drink-history`
   shows the signed-in attendee's full order history, supports reorder for
   currently available/orderable drinks, and shows a per-order bartender tip
   disclosure when admin tipping is enabled.
9. Signed-in attendees can open `/party/account` from the shared Menu at any
   time to view their account level, stored roles, active session permissions,
   display name, email, and creation date; they can update their own profile or
   password without changing their stable account ID.
10. Bartenders assigned from existing user accounts can manage drink orders at
   `/bartender`; admins can access the same view.
11. Admins sign in at `/admin/login` and manage RSVPs, entries, public landing settings,
    explicit party-code replacement/status/hint controls, live-display WiFi
    details, and event state at `/admin`. The Public Info workspace also offers
    a session-local role-view demo; navigation available only through extra real
    session roles is shown as Hidden and those role-only views are unavailable
    in the selected role view.
12. When the admin starts the costume contest, `/party/costumes/vote` and attendee voting navigation become available to logged-in guests; stopping or resetting the contest hides voting again.
13. Each logged-in guest can submit one complete ballot, scoring every costume from 1 to 10.
14. Admins can lock the winner, show winner/live override cards, restore the rotating display, and start the karaoke countdown.
15. Regular and admin sessions use one logout action in the header menu; it
    clears the current browser session regardless of role.

## State Model

Redis is the database. The canonical state document is stored at
`halloween:state` with schema version 10. The following globals in `main.py` are
the process-local cache:

- `costume_signups`: list of `CostumeSignup` dataclass instances with stable IDs.
- `karaoke_signups`: list of `KaraokeSignup` dataclass instances with stable
  IDs, requester identity, exact YouTube metadata, independent workflow state,
  playlist item/revision/operation metadata, and bounded history.
- `youtube_karaoke`: non-secret host channel, event playlist, connection, and
  reconciliation metadata. API keys and OAuth credentials never enter Redis.
- `costume_ballots`: maps `user_id` to `{costume_id: score}`.
- `user_accounts`: maps normalized usernames to Redis-backed attendee account
  records with stable IDs, password hashes, and roles such as `regular` and
  optional `bartender`.
- `password_reset_tokens`: maps SHA-256 reset-token hashes to account-bound
  reset records with email, created/expiration timestamps, and used timestamp.
  Plaintext reset tokens are only sent in the emailed link and are not stored.
- `menu_items`: admin-managed food/drink entries with stable IDs, category,
  description, image URL, optional drink recipe, availability, drink type
  (`standard`/`specialty`), beverage type (`alcoholic`/`non_alcoholic`),
  orderable flag, and created timestamp.
- `drink_orders`: attendee drink orders with account/menu snapshots, drink type,
  beverage type, specialty sequence/extra-request metadata, status, estimated
  ready time, created/started/completed timestamps, and completed prep duration.
- `bartender_tip_settings`: admin-managed bartender tip prompt settings with an
  enable flag, display name, note, QR/payment image URL, and optional Zelle,
  PayPal, Venmo, or Cash App handles.
- `registered_users`: maps session `user_id` to display name.
- `rsvp_signups`: independent host RSVP list entries with name, required email
  contact, guest count, note, created timestamp, and stable ID.
- `rsvp_updates`: admin-posted update cards with title, message, timestamp, and
  stable ID, displayed newest-to-oldest on `/rsvp` and in pre-party dashboard
  Event Highlights.
- `party_details`: admin-editable static RSVP cards for date, time, location,
  map address, and overview.
- `display_settings`: admin-editable live-display settings, currently WiFi
  network and password for the signup portal card. Defaults come from
  `HALLOWEEN_DISPLAY_WIFI_NETWORK` and `HALLOWEEN_DISPLAY_WIFI_PASSWORD`; blank
  values are allowed so the display can hide either row.
- `display_config`: source visibility/order, center/game intervals, region
  visibility modes, queue size, alert duration, density, pinned game, and
  per-card visibility for generated game winner/final-score cards.
- `display_runtime`: center index, pause/pin state, and revision used to push
  host run-of-show changes to connected displays.
- `display_custom_cards`: ordered, scheduled host-authored cards with optional
  image, CTA, start/end window, and per-card duration.
- `submitted_costume_votes`: set of `user_id` values that already voted.
- `live_display_event_override`: current full-screen event override card
  (`contest_start`, `winner`, or `karaoke_start`), or `None`.
- `live_display_notice_override`: current temporary notice card, currently
  `drink_ready`, or `None`. The legacy `live_display_override` snapshot field
  remains as the effective override for compatibility.
- `live_display_notice_queue`: bounded FIFO queue of subsequent drink-ready
  notices, shown sequentially instead of replacing an active pickup alert.
- `landing_page_target`: admin-selected root redirect target, defaulting to
  `/rsvp`.
- `event_experience_mode`: admin-selected attendee experience override,
  defaulting to `auto`; `pre_party` forces planning-mode portal/routes and
  `party_day` forces event-night portal/routes for testing.
- `party_code_hash` and `party_code_hint`: RSVP submission code settings. The
  code itself is not stored in plaintext.
- `rsvp_notification_email`: admin-configurable host notification recipient
  for new public RSVPs, defaulting to `tgio1129@gmail.com`; blank disables host
  RSVP notifications.
- `contest_state`: contest started/stopped, voting open/closed, winner lock, scoreboard card visibility.
- `karaoke_state`: whether karaoke has been started/stopped/reset and current singer metadata.
- `display_update_version`: monotonic counter used by server-sent events.
- `dj_playlist`: ordered Apple Music songs managed by admins.
- `dj_song_requests`: pending attendee Apple Music requests. Approval removes
  the request and inserts the song at a random saved-playlist position;
  rejection removes it without changing the playlist or current playback.
- `dj_state`: Redis-persisted desired command, acknowledgement, live-display
  heartbeat, MusicKit/audio readiness, confirmed player state, current song,
  retained failure details, and the latest DJ reset acknowledgement.
- `games_state`: five-game registry state. Two Truths and a Lie stores clues and
  identity guesses; Murder/Marry/F%$@ stores ten configurable public-figure
  trios, anonymous aliases, ballots, aggregate results, and presentation state;
  Fill in the Blank, Bad Advice Hotline, and Wrong Answers Only store independent
  prompt decks, submission/voting/reveal rounds, anonymous responses, votes,
  cumulative scores, presentation state, and explicit simulation metadata.
  Admin simulation builds deterministic completed games without creating party
  accounts and refuses to replace real participant data. MMF and prompt engines permit a
  one-player session; a single prompt response becomes a one-point solo
  spotlight while Two Truths retains its two-player minimum.

Drink orders move from `received` to `in_progress` to `complete`. Completed
orders track prep duration from `started_at` when available, and drink-ready
events create a temporary 10-second live-display notice with the drink image.
Drink notices render above active contest/karaoke/winner event overrides
without replacing them.

DJ commands share the Redis snapshot and display-update broadcast architecture.
The `/admin/dj` workspace visibly distinguishes an admin request from the
live-display receiver's confirmed player state. MusicKit signing material stays
in Vault at runtime; the Media Services private key and browser user token are
never stored in Redis.

The DJ reset workflow clears only transient control/playback/receiver state;
the curated `dj_playlist` is retained. A reset remains pending until the live
display acknowledges it, including when the TV is temporarily offline.

`HALLOWEEN_PARTY_START` controls attendee route availability and the dashboard
mode, but not the live display rotation. The live display is intentionally
party-night oriented before and during the event, rotating admin-configurable
WiFi/app access, costume, karaoke, drink-order, and live signup/update cards so
it can be tested and staged before guests arrive.

The attendee dashboard uses the calendar date from `HALLOWEEN_PARTY_START`.
Before that date, `/party` shows logistics-oriented Event Highlights and blocks
attendee access to `/party/menu`, `/party/costumes`, and `/party/karaoke`. On
the party date, those attendee routes and navigation links become available.
Costume voting remains separately admin-gated and only appears when the admin
starts/opens voting.

## RSVP Update Email

RSVP confirmations and admin-posted RSVP updates can send outbound email through
Amazon SES when `HALLOWEEN_EMAIL_UPDATES_ENABLED=true`. The intended sender is
`Qiana and Tony's Halloween Party <no-reply@tnq-halloween.com>`, configured via
`HALLOWEEN_EMAIL_FROM`, with `HALLOWEEN_PUBLIC_BASE_URL=https://tnq-halloween.com`.

The SES identity for `tnq-halloween.com` is separate from the existing
GoodVines SES identities. Do not modify `appg-v.com`, `goodvines.app`, or
GoodVines sender-address SES identities while working on Halloween email.
Recipients are deduplicated across RSVP entries and Redis-backed party account
emails, and delivery failures are logged/reported to admin without blocking the
RSVP update from being posted.

RSVP confirmation emails include the submitted name, guest count, email, note,
party date/time/location, an RSVP page link, a Google Calendar link, and a
download link to `/rsvp/calendar/<rsvp_id>`. That endpoint serves an `.ics`
calendar invite generated from `HALLOWEEN_PARTY_START` and the current
admin-editable party details; the random RSVP ID acts as the access token.

New public RSVPs also send a host notification email when email is enabled.
The recipient is managed from the admin Public Access panel, defaults to
`tgio1129@gmail.com`, is stored in Redis state as `rsvp_notification_email`,
and can be left blank to disable host notifications. Notification delivery
failures are logged and never block RSVP creation.

The same SES sender is used for account welcome emails and party account
password reset emails. Reset links are generated from random one-time tokens,
stored only as SHA-256 hashes in Redis-backed state, expire after 45 minutes,
and are marked used after a successful password change. Password reset request
responses are intentionally generic so the UI does not reveal whether an email
address is registered.

The same SES sender is used for drink order confirmation emails and drink-ready
emails when Halloween email sending is enabled. Generated HTML email templates
use email-safe inline styling aligned with the dark lab-terminal UI system.

Schema version 1 Redis state with index-aligned `costume_votes` is upgraded on
load into ID-keyed `costume_ballots`.

## Design Shape

This is intentionally a simple Flask/Jinja app:

- `main.py` defines routes, in-memory state, scoring helpers, and live-display API payloads.
- `templates/` contains Jinja templates for attendee, admin, voting, display pages,
  and generated HTML email bodies.
- `static/styles.css` styles normal attendee/admin pages.
- `static/display.css` styles the TV/live-display experience.
- `static/display.js` drives live-display rotation, override rendering, SSE updates, and polling.
- `static/slides.js` rotates dashboard highlight slides.
- `party_games.py` owns the game catalog, defaults, normalization, alias
  generation, MMF plurality scoring, shared prompt-vote scoring, Two Truths
  scoring, ties, and statistics while `main.py` keeps Flask routes, admin
  operations, presentation slides, and Redis integration.

The visual style is the dark lab-terminal Halloween system documented in
`ai-context/UI_UX_DESIGN_SYSTEM.md`: near-black backgrounds, red/magenta/steel
accents, CRT scanline texture, square glowing lab panels, mono controls, and
serif display headings.
The responsive UX pass is complete: live-display cards scale for normal browser
windows, attendee pages use a compact menu nav with a single logout action,
touch-safe forms, and admin add/edit forms collapse into disclosure rows by
default on mobile-friendly layouts.
