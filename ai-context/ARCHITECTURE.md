# Architecture Notes

## Route Map

- `GET /` -> redirects to `live_display`.
- `GET /live-display` -> renders `templates/display.html` with rotation entries, counts, and override state.
- `GET /api/display-updates` -> server-sent events stream keyed by `display_update_version`.
- `GET /api/display-data` -> JSON payload for live-display refreshes.
- `GET /halloween` -> attendee dashboard; requires `session.user_id` and `session.username`.
- `GET|POST /halloween/login` -> session check-in; stores a generated `user_id` and provided `username`.
- `GET|POST /admin` -> admin dashboard and all admin mutations.
- `GET /admin/export/state` -> JSON export of current Redis-backed app state.
- `GET /admin/export/costume-results` -> JSON export of costume contest scores.
- `GET /admin/export/karaoke-lineup` -> JSON export of karaoke lineup.
- `GET|POST /costume-signup` -> public costume signup form.
- `GET|POST /karaoke-signup` -> public karaoke signup form.
- `GET|POST /costume-voting` -> logged-in one-ballot-per-session voting while contest is open.

`app.url_map.strict_slashes = False` allows both trailing and non-trailing slash route variants.

## Main Server Components

`main.py` is the entire backend. Its main responsibilities are:

- Flask app setup and route definitions.
- Dataclasses: `CostumeSignup`, `KaraokeSignup`.
- Global in-memory stores and event state.
- Display update broadcasting via `threading.Condition`.
- Scoreboard construction, ranking, and winner card creation.
- Rotation-entry construction for the live display.
- Form validation and admin actions.

The app uses Flask sessions for attendee identity, but session identity is only meaningful while the process-level `registered_users` dictionary still contains the generated `user_id`.

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

`static/slides.js` is independent and rotates `.slide` elements on the attendee dashboard every 6 seconds.

## Template Responsibilities

- `base.html`: shared shell, title, CSS include, header nav, signed-in user, footer, script block.
- `index.html`: attendee dashboard, contest status banners, event highlights, signup summaries.
- `halloween_login.html`: simple check-in form.
- `costume_signup.html`: costume entry form and submitted costume list.
- `karaoke_signup.html`: karaoke entry form and submitted karaoke lineup.
- `costume_voting.html`: complete ballot form and post-vote state.
- `admin.html`: all admin actions and live contest/karaoke state.
- `display.html`: standalone live-display page without `base.html`.

## Known Constraints And Risks

- No persistence: process restart clears all event data.
- No admin authentication.
- No CSRF protection.
- No tests are present.
- No database migrations or app factory pattern.
- Vote identity depends on Flask session plus the in-memory `registered_users` map.
- `/costume-voting` appends ratings by index, so costume reorder/delete during active voting can affect interpretation of existing votes.
- The karaoke display JavaScript has support for a lineup list, but the current `display.html` markup includes only the countdown panel inside the karaoke override section.
- `main.py` runs on port 80 in debug mode when executed directly.

## Extension Guidance

- Keep small changes in the existing single-file Flask style unless asked to refactor.
- If adding durable event data, introduce a clear persistence layer before expanding globals further.
- If changing contest voting, protect vote/index alignment carefully.
- If changing live-display payloads, update both `build_rotation_entries()`/override payloads and `static/display.js`.
- If adding admin actions, call `broadcast_display_update()` whenever display-relevant state changes.
- If adding template pages, extend `base.html` unless the page is a full-screen display mode.
