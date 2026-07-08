# Architecture Notes

## Route Map

- `GET /` -> redirects to the admin-configured public landing target; defaults
  to `/rsvp`.
- `GET /health` -> JSON health API for service and Redis readiness; returns
  `503` in production if Redis cannot be reached.
- `GET /live-display` -> renders `templates/display.html` with rotation entries, counts, and override state; requires an `admin` role session.
- `GET /api/display-updates` -> server-sent events stream keyed by `display_update_version`; requires an `admin` role session.
- `GET /api/display-data` -> JSON payload for live-display refreshes; requires an `admin` role session.
- `GET|POST /rsvp` -> public RSVP landing page; requires the party code before
  showing party details and an independent RSVP form; successful RSVPs are saved
  to the host-visible RSVP list and do not create attendee accounts. Admin-editable
  party info cards and a Google Maps location embed are shown first, then RSVP
  updates are shown newest-to-oldest.
  Locked RSVP sessions show only the code prompt; party details, map, updates,
  and party navigation stay hidden until that browser session enters the correct
  code.
- `GET /party` -> attendee dashboard; requires a `regular` role session plus `session.user_id` and `session.username`.
- `GET|POST /party/login` -> attendee account sign-in; requires party-code
  verification before showing the login form, then validates a Redis-stored
  password hash and grants the `regular` role.
- `GET|POST /party/register` -> attendee account creation; requires party-code
  verification before showing the registration form, then stores a password hash
  in Redis app state and grants the `regular` role.
- `POST /logout` -> clears the current browser session regardless of regular/admin role.
- `POST /party/logout` and `POST /admin/logout` -> compatibility aliases for
  the single logout behavior.
- `GET|POST /admin/login` -> password-backed admin session login; grants the `admin` role.
- `GET|POST /admin` -> admin dashboard and all admin mutations.
- `GET /admin/export/state` -> JSON export of current Redis-backed app state.
- `GET /admin/export/costume-results` -> JSON export of costume contest scores.
- `GET /admin/export/karaoke-lineup` -> JSON export of karaoke lineup.
- `GET|POST /party/costumes` -> attendee costume signup form.
- `GET|POST /party/karaoke` -> attendee karaoke signup form.
- `GET|POST /party/costumes/vote` -> logged-in one-ballot-per-session voting while contest is open.
- Legacy attendee paths redirect to the canonical `/party` paths:
  `/halloween`, `/halloween/login`, `/halloween/register`,
  `/costume-signup`, `/karaoke-signup`, and `/costume-voting`.

`app.url_map.strict_slashes = False` allows both trailing and non-trailing slash route variants.

## Main Server Components

`main.py` is the entire backend. Its main responsibilities are:

- Flask app setup and route definitions.
- Dataclasses: `CostumeSignup`, `KaraokeSignup`.
- Redis-backed state serialization/hydration, with process-local global caches.
- Display update broadcasting via `threading.Condition`.
- Scoreboard construction, ranking, and winner card creation.
- Rotation-entry construction for the live display.
- Form validation and admin actions.

The app uses Flask sessions for role and attendee identity. Regular attendee
accounts live in Redis app state as `user_accounts`; active session display
names are also tracked in `registered_users` by account ID.

## Session Management

The app uses Flask's default signed-cookie session model. Each browser/profile
stores its own session cookie, and every request is authorized from only the
cookie sent with that request. Session fields currently include:

- `roles`: granted UI roles such as `regular` and `admin`.
- `user_id`: the Redis-backed attendee account ID for regular users.
- `username`: the attendee display name shown in the menu.
- `admin_authenticated`: legacy-compatible admin role marker.
- `csrf_token`: per-session token for POST forms outside testing mode.

Regular attendee accounts and password hashes live in Redis `user_accounts`;
Redis does not hold the active Flask session. Logging out posts to `/logout`,
which calls `session.clear()` and redirects to `/party/login`. That clears only
the current browser/profile cookie payload, so it does not remove Redis account
records and does not affect any other browser's session. The compatibility
routes `/party/logout`, `/admin/logout`, and `/halloween/logout` all execute the
same single-session logout behavior.

Templates display the signed-in name from the current request's session only.
Another attendee's name can appear only if the same browser/profile cookie is
being shared. Separate browsers, private windows, devices, or profiles have
separate session cookies. If the same attendee account signs in on multiple
devices, those devices have separate sessions, but voting remains account-bound
through `user_id` and `submitted_costume_votes`.

## Display Update Flow

Admin and voting actions that alter display-relevant state call `broadcast_display_update()`.

That function increments `display_update_version` and notifies `display_update_condition`.

`/api/display-updates` streams the current version to connected browsers, then waits for changes. The browser does not use the version value semantically; every SSE message triggers `fetchLatestEntries()` in `static/display.js`.

`static/display.js` also polls `/api/display-data` every 30 seconds as a fallback.

## Rotation Entry Model

`build_rotation_entries()` returns a list of dictionaries. Display entries can contain:

- `category`: small heading.
- `primary`: main card text.
- `secondary`: supporting text.
- `tertiary`: optional footnote/detail text.
- `cta`: boolean for signup-instruction layout.
- `link` and `link_label`: optional external link.
- `cta_details`: WiFi and signup portal details.
- `scoreboard`: structured top-score rows.

The base rotation always starts with signup instructions and event spotlight cards. Winner and scoreboard cards are appended when the relevant contest state is active. Costume and karaoke entries are then interleaved.

Before `HALLOWEEN_PARTY_START`, `build_rotation_entries()` returns only RSVP
prompt, static party detail cards, and admin-posted RSVP updates. Costume and
karaoke signup/event cards are withheld until the configured party start time.

## Frontend Responsibilities

`templates/display.html` renders initial display state and embeds JSON in:

- `#entries-data`
- `#override-data`

`static/display.js` then owns:

- Parsing initial entries and override state.
- Applying display entries to the card DOM.
- Switching between default, CTA, and scoreboard layouts.
- Applying costume/winner styling classes.
- Rotating cards every 8 seconds.
- Fetching latest display data.
- Connecting and reconnecting to SSE updates.
- Rendering override content.
- Running karaoke countdown timers and karaoke panel rotation.
- Scaling live-display cards for normal desktop/laptop browser windows and
  narrow browser widths.

`static/slides.js` is independent and rotates `.slide` elements on the attendee dashboard every 6 seconds.

## Template Responsibilities

- `base.html`: shared shell, title, CSS include, header menu with signed-in
  identity and single logout action, footer, and script block.
- `index.html`: attendee dashboard, contest status banners, event highlights, signup summaries.
- `halloween_login.html`: attendee account sign-in form.
- `halloween_register.html`: attendee account registration form.
- `costume_signup.html`: costume entry form and submitted costume list.
- `karaoke_signup.html`: karaoke entry form and submitted karaoke lineup.
- `costume_voting.html`: complete ballot form and post-vote state.
- `admin_login.html`: admin password form when production admin auth is configured.
- `rsvp.html`: standalone guest RSVP landing page with party-code unlock,
  RSVP prompt, party details, Google Maps directions/embed, newest-to-oldest update cards, RSVP
  form, and optional portal account links.
- `party_code_gate.html`: invite-code gate shown before direct login/register
  pages reveal their forms.
- `admin.html`: all admin actions, public landing/party-code settings, RSVP
  list, party detail/map address editing, RSVP update posting/removal, and live
  contest/karaoke state; add/edit entry forms are disclosure rows to keep mobile
  admin scanning manageable.
- `display.html`: standalone live-display page without `base.html`; includes
  default card, CTA, scoreboard, override, karaoke countdown, and karaoke lineup
  panel markup.

## Known Constraints And Risks

- Redis persistence is available and expected in production. If Redis is
  unavailable, the app falls back to process memory and a process restart clears
  signups, votes, sessions, contest state, and live-display overrides.
- UI route access is role-based through Flask sessions. Configure
  `HALLOWEEN_ADMIN_PASSWORD` for admin and display access; regular attendee
  accounts are created through `/party/register` and stored in Redis app
  state.
- CSRF protection is enforced for POST forms outside testing mode.
- Redis state and route persistence tests are present in `tests/test_redis_state.py`.
- No app factory pattern.
- Vote identity depends on Flask session plus the in-memory `registered_users` map.
- Costume votes are stored as ID-keyed ballots; destructive costume lineup changes are blocked while voting is open.
- `main.py` runs on port 80 in debug mode when executed directly.
- Production deploys are GitHub Actions -> AWS SSM -> EC2 and must preserve the
  GoodVines service. Do not use S3, ECS, ECR, CodeDeploy, or new hosting
  infrastructure for the current deployment path.

## Extension Guidance

- Keep small changes in the existing single-file Flask style unless asked to refactor.
- If adding durable event data, introduce a clear persistence layer before expanding globals further.
- If changing contest voting, protect vote/index alignment carefully.
- If changing live-display payloads, update both `build_rotation_entries()`/override payloads and `static/display.js`.
- If adding admin actions, call `broadcast_display_update()` whenever display-relevant state changes.
- If adding template pages, extend `base.html` unless the page is a full-screen display mode.
