# Architecture Notes

## Route Map

- `GET /` -> redirects to the admin-configured public landing target; defaults
  to `/rsvp`.
- `GET /health` -> JSON health API for service and Redis readiness; returns
  `503` in production if Redis cannot be reached.
- `GET /live-display` -> renders `templates/display.html` with the adaptive region layout bootstrap; requires an `admin` role session.
- `GET /api/display-updates` -> server-sent events stream keyed by `display_update_version`; requires an `admin` role session.
- `GET /api/display-data` -> JSON payload for live-display refreshes; requires an `admin` role session.
- `GET|POST /rsvp` -> public RSVP landing page; shows party details, an
  independent RSVP form, admin-editable party info cards, Google Maps location
  embed, and RSVP updates without a party-code gate. Successful RSVPs are saved
  to the host-visible RSVP list and do not create attendee accounts. RSVP
  submissions require the admin-configured party code as a form field plus an
  email contact, and do not show a guest opt-in checkbox for update emails.
  Successful RSVPs send a confirmation email with RSVP details and calendar
  links when email is enabled, and also send a host notification email to the
  admin-configurable RSVP notification recipient when configured. The RSVP page
  is intentionally standalone and hides the shared header menu/site navigation
  even when a signed-in party user visits it directly.
- `GET /rsvp/calendar/<rsvp_id>` -> returns a downloadable `.ics` calendar
  invite for a saved RSVP using the random RSVP ID.
- `GET /party` -> attendee dashboard; requires a `regular` role session plus
  `session.user_id` and `session.username`. Before the calendar date of
  `HALLOWEEN_PARTY_START`, Event Highlights stays logistics-focused with party
  date/time, directions/map address, rideshare suggestions, potluck/overview
  details, host updates, and a light preview that costume contest, games, and
  karaoke happen later in the night. Event-night signup/menu/drink/voting
  summaries are hidden. On the party date, it shows the normal event-night
  dashboard.
- `GET|POST /party/menu` -> signed-in consolidated Menu & Orders workspace with
  query-backed `view=menu|orders` views. It preserves menu ordering and
  specialty rules, groups account-scoped order history by live status, supports
  reorder, and shows one bartender-tip callout when enabled. Successful orders
  and reorders redirect to the My Orders view. Attendee access redirects to
  `/party` until the party date.
- `GET|POST /party/drink-history` -> compatibility route. GET redirects to
  `/party/menu?view=orders`; temporary POST handling uses the shared
  account-scoped reorder helper and then redirects to the canonical view.
- `GET /api/party/bar-queue` -> party-day regular-attendee JSON endpoint with a
  deterministic version, aggregate active/mixing/waiting counts, average prep
  label, and only the current account's active/recent-ready order details and
  approximate queue positions. It excludes other attendee identities, recipes,
  and operational actions. `static/bar-status.js` polls it every five seconds.
- `GET|POST /bartender` -> bartender/admin drink order queue with image and
  recipe reference; transitions orders to `in_progress` or `complete`. Active
  queue sorting keeps in-progress orders first, then normal/included orders,
  then first-come-first-served 4th+ specialty requests.
- `GET /api/bartender-queue` -> bartender/admin JSON endpoint that returns the
  rendered queue fragment plus a queue version. `static/bartender.js` polls it
  every few seconds so new drink orders appear on `/bartender` without a full
  page reload.
- `GET|POST /party/login` -> public attendee account sign-in form; validates a
  Redis-stored password hash and grants the `regular` role.
- `GET|POST /party/password-reset` -> public account recovery request form;
  accepts an email address, always returns a generic response, and sends a
  one-time reset email when a matching account exists.
- `GET|POST /party/password-reset/<token>` -> validates a reset token and lets
  the user choose a new password; tokens are hashed in stored state, expire
  after 45 minutes, and are marked used after a successful reset.
- `GET|POST /party/register` -> public attendee account creation form; stores a
  password hash in Redis app state, sends a welcome email when email is enabled,
  and grants the `regular` role.
- `GET|POST /party/account` -> authenticated attendee account workspace. It
  shows the account level, stored account roles, active session permissions,
  profile details, and creation date; the attendee can update their own
  display name/email or change their password after current-password
  verification without changing the stable account ID.
- `POST /logout` -> clears the current browser session regardless of regular/admin role.
- `POST /party/logout` and `POST /admin/logout` -> compatibility aliases for
  the single logout behavior.
- `GET|POST /admin/login` -> password-backed admin session login; grants the `admin` role.
- `GET|POST /admin` -> concise **Tonight** admin control-room dashboard and all
  admin mutations. Focused workspaces are available at `/admin/guests`,
  `/admin/public`, `/admin/program`, `/admin/games`, `/admin/dj`, `/admin/bar`,
  `/admin/menu`, and `/admin/accounts`; they share the existing POST action
  handler. `/admin/games?game=<game-key>` builds one detailed game view plus
  lightweight summaries for the selector; other admin workspaces receive only
  the summaries. `/admin/public`
  also owns the session-local role-view demo action; it can only reduce the
  effective roles, so protected views match the selected demo role.
- `static/preserve-scroll.js` progressively enhances standard same-origin admin
  POST forms by fetching the existing full response and replacing only the
  `.admin-panel`. Stable view keys preserve the action anchor, selected URL,
  disclosures, and focus. The normal form request remains the no-JavaScript
  fallback.
- `GET /api/dj/catalog-search` -> authenticated Apple Music catalog search;
  the developer token stays server-side.
- `GET /api/dj/musickit-token` -> authenticated developer-token endpoint for
  the display-side MusicKit Web receiver.
- `GET /party/jukebox`, `GET /api/party/jukebox-data`,
  `GET /api/party/jukebox/catalog-search`, and
  `POST /party/jukebox/requests` -> attendee-authenticated party-day jukebox,
  safe playback/playlist data, catalog search, and request submission.
- `POST /api/dj/receiver-state` -> authenticated, CSRF-protected receiver
  heartbeat/player state/command acknowledgement endpoint. Explicit receiver
  errors persist until a successful clear, so heartbeats cannot hide a failed
  Apple Music pairing or command.
- `GET /admin/export/state` -> JSON export of current Redis-backed app state.
- `GET /admin/export/costume-results` -> JSON export of costume contest scores.
- `GET /admin/export/karaoke-lineup` -> JSON export of karaoke lineup.
- `GET /admin/export/games` -> admin-only JSON export of the Redis-backed game
  registry and finalized results. MMF and prompt-game account keys are replaced
  with admin-selected public identities and game anonymity flags; MMF individual ballots
  are replaced with completion counts plus aggregate results.
- `GET|POST /party/costumes` -> attendee costume signup form, available on
  the party date and redirected to `/party` before then.
- `GET /party/games` -> party-day Games workspace for enabled games. The
  selected `game` query activates one of five catalog tabs; signup, active,
  round, voting, and final-result views are server-selected from Redis state.
- `POST /party/games/two-truths-and-a-lie/opt-in|submission` and
  `POST /party/games/two-truths-and-a-lie/guesses/<submission_id>` ->
  CSRF-protected, account-bound enrollment, clue submission/update, and guess
  upsert actions with phase and ownership checks.
- `POST /party/games/<game_slug>/join` -> attendee enrollment for MMF and the
  three prompt/vote games. The game-level admin setting determines whether every
  player appears under a signed-in name or generated anonymous alias.
- `POST /party/games/murder-marry-fuck/answers` -> saves one validated
  three-action MMF round ballot for an enrolled player while active.
- `POST /party/games/<game_slug>/response|vote` -> upserts one blind
  response or non-self vote for the current Fill in the Blank, Bad Advice, or
  Wrong Answers round.
- `GET|POST /party/karaoke` -> attendee karaoke signup form, available on the
  party date and redirected to `/party` before then. With YouTube karaoke
  enabled, the three-step flow collects song-card metadata first, searches for
  an exact version, preserves the user's song/artist independently from
  YouTube metadata, requires server-verified video metadata, and creates a
  pending workflow entry.
- `GET /api/party/karaoke-data` -> regular-user-authenticated, attendee-safe
  live status for `/party` and `/party/karaoke`. It returns the signed-in
  requester's or registered co-singer's entries, derived stage status, safe
  public current/next metadata and lineup, and the display update version;
  playlist operation details, history, and credentials are excluded.
- `POST /api/party/karaoke/entries/<entry_id>/dismiss-completion` ->
  CSRF-protected, participant-only acknowledgement of one exact completed
  performance. The submitted completion identifier must still match current
  server state, preventing a stale page from dismissing a later re-completion.
  Returns refreshed attendee state so the next eligible song appears
  immediately.
- `GET /api/party/karaoke/search` -> deliberate, cached, quota-budgeted
  normalized YouTube search for signed-in attendees. Structured
  `song_title`/`artist` parameters become the canonical
  `{song title} {artist} karaoke` query; the legacy `q` parameter remains
  available for compatibility.
- `POST /party/karaoke/<entry_id>/cancel|replace` -> requester-owned pending
  request recovery actions.
- `GET|POST /admin/karaoke` -> dedicated host queue, run-of-show, and stage
  workspace.
- `/api/admin/karaoke/*` -> admin-only search, approval, retry, replacement,
  rejection, removal, playlist setup/order synchronization, connection test,
  and reconciliation endpoints.
- `POST /api/admin/karaoke/reset` -> exact-confirmation bulk reset. `combined`
  mode backs up state, deletes only stored app-managed playlist item IDs
  outside the Redis mutation lock, and clears the local lineup after all
  deletions succeed. Partial failures persist retry targets and block competing
  queue changes; `local` mode is the explicit manual-cleanup fallback.
- `GET /admin/karaoke/youtube/connect|callback` and
  `POST /admin/karaoke/youtube/disconnect` -> OAuth authorization lifecycle
  with session state validation and dedicated Vault refresh-token persistence.
- `GET|POST /party/costumes/vote` -> logged-in one-ballot-per-session voting
  on the party date while the costume contest is started, voting is open, and
  no winner is locked.
- Legacy attendee paths redirect to the canonical `/party` paths:
  `/halloween`, `/halloween/login`, `/halloween/register`,
  `/costume-signup`, `/karaoke-signup`, and `/costume-voting`.

`app.url_map.strict_slashes = False` allows both trailing and non-trailing slash route variants.

## Main Server Components

`youtube_karaoke.py` isolates all Google-specific behavior from Flask/Redis:
YouTube URL parsing, normalized metadata, safe API errors, bounded HTTP
timeouts, public search, OAuth channel/playlist operations, consent-flow
construction, and the narrow KV v1 refresh-token store.

External playlist writes use a two-phase state protocol. The first short Redis
lock records a UUID operation/revision and pending status, the lock is released
for the YouTube call, and a second short lock applies the result only if the
operation still matches. Playlist-item notes contain a stable
`halloween-karaoke:<signup-id>:<revision>` marker so retry and reconciliation
do not duplicate an uncertain insert.

Bulk karaoke clearing follows the same no-network-under-lock rule and stores
its operation ID, target item IDs, counts, backup key, status, and failure
details in `youtube_karaoke.clear_operation`. The clear target is derived only
from each signup's persisted `workflow.playlist_item_id`; foreign/manual
playlist items are intentionally outside its deletion scope.

`party_games.py` is the pure game-domain boundary: default registry state,
normalization of persisted submissions/guesses/results and admin-controlled
game identity modes, anonymous statement ordering, identity scoring, tied winner
calculation, and admin statistics.
`main.py` retains route authorization, Redis locking/persistence, backups, and
display-update broadcasts.

`main.py` is the entire backend. Its main responsibilities are:

- Flask app setup and route definitions.
- Dataclasses: `CostumeSignup`, `KaraokeSignup`. Karaoke records canonically
  store one to four `{account_id, name}` singer snapshots; schema-13 and older
  single-name records normalize to one custom singer while the derived `name`
  label remains in serialized payloads for compatibility.
- Redis-backed state serialization/hydration, with process-local global caches.
- Food/drink menu management, specialty drink limit enforcement, drink order
  lifecycle, bartender role checks, prep-time estimates, bartender tip settings,
  and drink notification emails.
- RSVP confirmation/update recipient collection, account welcome email,
  password reset email, and Amazon SES email sending when enabled.
- Display update broadcasting via `threading.Condition`.
- Scoreboard construction, ranking, and winner card creation.
- Rotation-entry construction for the live display.
- Form validation and admin actions.

The app uses Flask sessions for role and attendee identity. Regular attendee
accounts live in Redis app state as `user_accounts`; active session display
names are also tracked in `registered_users` by account ID. Schema 16 stores a
top-level, stable-user-ID keyed `karaoke_completion_acknowledgements` ledger.
Each user's bounded map records entry ID to dismissed `completed_at`; timestamp
matching prevents an old acknowledgement from suppressing a later
re-completion. Schema-15 nested account maps migrate into the ledger on load,
and dismissal no longer depends on a second username/account lookup after the
session participant has been authorized.

Navigation is the union of active session roles: a mixed regular/bartender/admin
session exposes the destinations for each represented role. Menu and Drink
History share one `Menu & Orders` item, while Bartender remains a separate
bartender/admin-only item. Attendee sign-in
refreshes the account-derived regular/bartender roles while retaining an active
admin role in the same browser session.

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

`/api/display-updates` streams the current version to connected browsers, then waits for changes. The browser does not use the version value semantically; every SSE message triggers a full layout refresh in `static/display.js`.

`static/display.js` also polls `/api/display-data` every 30 seconds as a fallback.

## Rotation Entry Model

`build_display_layout()` returns `header`, `center`, `games`, `bar`, `music`, and
`density` regions. `/api/display-data` also retains the legacy top-level
`entries`, `override`, counts, and `dj` fields for compatibility.

`build_rotation_entries()` produces the ordered center-card list. Display entries can contain:

- `category`: small heading.
- `primary`: main card text.
- `secondary`: supporting text.
- `kind`: optional semantic layout type such as `access`, `action`, `profile`,
  `status`, `result`, `scoreboard`, or `announcement`.
- `facts`: optional privacy-safe label/value tiles derived from current event
  state.
- `steps`: optional ordered phone-participation or game-play instructions.
- `action`: optional display-only label and party URL callout.
- `tertiary`: optional footnote/detail text.
- `cta`: boolean for signup-instruction layout.
- `link` and `link_label`: optional external link.
- `cta_details`: admin-configurable WiFi and signup portal details.
- `scoreboard`: structured top-score rows.
- `id`, `source`, and `duration_seconds`: stable operator pin target, source
  grouping, and optional per-card rotation duration.

`build_game_stage_entries()` produces privacy-safe per-game summaries, current
clues/prompts/responses, and ended results for an independent left-stage
rotation. `build_bar_stage()` exposes only public active-order fields plus the
current/queued ready alerts. It also derives queue positions, mixing/waiting
counts, average prep time, available-drink count, a featured public menu item,
and order/pickup guidance without exposing email, account IDs, or recipes.
`build_music_footer()` provides receiver-confirmed
Now Playing and Up Next data from `dj_state.receiver.queue_order` and
`current_queue_index`, never from a predicted saved-playlist position.
`attendee_jukebox_state()` exposes the same confirmed current song through a
privacy-safe payload with `update_version`. `dj-live-widgets.js` normalizes that
payload and `/api/display-data`, rejects out-of-order refreshes, and atomically
updates text and artwork on the party dashboard, attendee jukebox, admin home,
and display workspace. Attendee pages poll every five seconds plus on tab
visibility; admin summaries also subscribe to the existing authenticated SSE
signal. Public attendee SSE is intentionally avoided so the single-worker,
eight-thread production process cannot be exhausted by long-lived guest
connections.
The DJ admin workspace consumes the same derived songs, places playback
controls beneath them, and gates those controls on live receiver,
authorization, audio, and pending-command readiness. Approved attendee songs
carry a persisted priority lifecycle. `build_dj_queue_plan()` prepends the FIFO
priority lane for Play/Shuffle while preserving a separate regular base order;
`build_active_dj_queue_order()` preserves the confirmed current song and
rebuilds only its remainder. A revisioned `sync_priority_queue` command uses
MusicKit `playNext(..., true)` on the display and is acknowledged only after
the resolved remainder matches. Offline/busy requests remain dirty until a
ready receiver heartbeat can reconcile them. Region modes are `auto`, `always`, or `hidden`;
the client toggles layout classes so unused tracks disappear and center grows.

The center rotation is grouped and ordered by `display_config.source_order`;
each source may be disabled independently. Its defaults include WiFi/app sign-in,
costume and karaoke signup/entries, game signup/final results, drink-order
promotion, and live-update explanation cards. The WiFi values come from
Redis-backed `display_settings`, defaulting to
`HALLOWEEN_DISPLAY_WIFI_NETWORK` and `HALLOWEEN_DISPLAY_WIFI_PASSWORD`; blank
values hide either row. Current game data, clues/prompts, voting responses, and
phase metrics instead rotate independently in `layout.games`. Host-controlled
`game_presentation` overrides walk MMF aggregate action totals or revealed
prompt winners with previous/next center-stage controls; only the admin-selected
public identity enters result payloads, and individual MMF ballots
never enter display payloads. Admin
stop/reset actions clear matching live-display event overrides without deleting
signup lineups. Starting costume stops active karaoke event mode, and starting
karaoke closes active costume voting so costume/karaoke do not compete for the
static event card. Drink-ready notices are a separate right-stage queue and do
not replace an active contest/karaoke/winner center card. `build_rotation_entries()` intentionally
returns party-night cards even before `HALLOWEEN_PARTY_START` so hosts can
stage and test the live display ahead of the event.

Ended game result cards are derived from finalized `games_state` results with
stable `games:<game-key>-winner` and `games:<game-key>-scores` IDs. They remain
available independently of attendee game enablement. Per-card inclusion is
stored in `display_config.game_result_card_enabled`; `/admin/display` can show
either card immediately or include/hide it from normal center rotation. Games
with no positive score receive a No Winner outcome card instead of silently
omitting the result.

`build_simulated_game_state()` creates deterministic completed test data for
all five engines. The admin action backs up Redis, preserves MMF trio and prompt
configuration, avoids party-account creation, marks the state as simulated,
and refuses to overwrite non-simulated participants.

The attendee portal has a related but separate date gate: `party_day_has_arrived()`
uses the persisted `event_experience_mode` first, then compares the local date
of `HALLOWEEN_PARTY_START` to the current date when the mode is `auto`. Admins
can force `pre_party` or `party_day` from `/admin` to test attendee UX states.
Before the effective party date, `/party/menu`, `/party/costumes`, and
`/party/karaoke` redirect to `/party`, and `base.html` hides Menu & Orders, Costume,
Karaoke, and Voting links. On the effective party date, those links/routes
become available. Voting still depends on `costume_voting_is_visible()`, which
also requires the admin contest state to have started/open voting with no
locked winner.

## Frontend Responsibilities

`static/karaoke-live-status.js` owns attendee karaoke status refresh on
`/party` and `/party/karaoke`. It polls `/api/party/karaoke-data` every five
seconds and on visibility, rejects stale responses with
`display_update_version`, updates personal alerts/workflows and the safe public
lineup, reconciles personal cards by stable entry ID, submits completion
dismissals with the session CSRF token, and changes the browser title for Up
Next or Called states. Attendee karaoke deliberately does not open long-lived
SSE connections.

`templates/display.html` renders initial display state and embeds JSON in:

- `#entries-data`
- `#override-data`
- `#notice-override-data`

`static/display.js` then owns:

- Parsing initial entries, event override state, and temporary notice override
  state.
- Applying display entries to the card DOM.
- Switching between default, CTA, and scoreboard layouts.
- Rendering structured fact grids, action steps, game instructions, bar
  summaries, featured items, and pickup details.
- Measuring inner content occupancy and applying sparse/dense/ultra-dense
  classes; `static/display.css` combines those classes with container-relative
  type sizing so cards can expand as well as compact.
- Applying costume/winner styling classes.
- Rotating cards every 8 seconds.
- Fetching latest display data.
- Connecting and reconnecting to SSE updates.
- Rendering event override content.
- Rendering drink-ready notice images above event overrides or normal rotation.
- Running karaoke countdown timers and karaoke panel rotation.
- Scaling live-display cards for normal desktop/laptop browser windows and
  narrow browser widths.

`static/slides.js` is independent and rotates `.slide` elements on the attendee dashboard every 6 seconds. The server chooses the slide set: pre-party RSVP details/updates before the party date, and event-night slides on the party date. When bartender tipping is enabled, the party-day slides include a tip prompt with the configured QR/payment image and payment handles.

## Template Responsibilities

- `base.html`: shared shell, title, CSS include, header menu with signed-in
  identity and single logout action, footer, and script block. Regular attendee
  Menu & Orders/Costume/Karaoke/Voting links are hidden until the party
  date.
- `index.html`: attendee dashboard, contest status banners, event highlights,
  drink order status cards, and signup summaries. It renders pre-party RSVP
  details/updates before the party date and event-night sections on the party
  date. Completed ready-drink notices are shown for 5 minutes after
  `completed_at`; older completed orders remain in drink history.
- `menu.html`: consolidated Menu & Orders shell with summary chips, query-backed
  view rail, privacy-safe live queue summary, and selected catalog/history
  partial.
- `_menu_catalog.html`: attendee food/drink cards, badges, availability, and
  drink-order forms.
- `_personal_drink_orders.html`: status-grouped account-bound order history,
  reorder controls, and the single bartender-tip callout.
- `drink_history.html`: retired template retained only until compatibility
  cleanup; the route no longer renders it.
- `bartender.html`: bartender/admin drink order page shell with a live-refresh
  queue container.
- `_bartender_queue.html`: shared bartender queue fragment with image, specialty
  sequence labels, extra specialty availability notes, recipe reference, and
  completed order history.
- `halloween_login.html`: attendee account sign-in form.
- `halloween_register.html`: attendee account registration form.
- `costume_signup.html`: costume entry form and submitted costume list.
- `_karaoke_singers.html`: reusable one-to-four singer fieldset with registered
  attendee choices, a custom-name path, and server-restored row state.
- `karaoke_signup.html`: multi-singer, song-details-first three-step exact-video
  search/selection and review, direct-link fallback, live requester/co-singer
  workflow status, pending-owner recovery, and synchronized public lineup.
- `admin_karaoke.html`: dedicated YouTube connection, review, run-of-show,
  reconciliation/history, and stage-control workspace.
- `_karaoke_workflow.html`: shared media and seven-step workflow macros.
- `karaoke-singers.js`: reusable singer-row add/remove/custom-name behavior,
  duplicate checks, accessibility status, and combined singer-label updates.
- `karaoke.js`: attendee song-detail validation, canonical search, pagination,
  stale-result/selection invalidation, multi-singer exact-video review, and
  direct-link fallback.
- `karaoke-admin.js`: asynchronous playlist mutations, admin replacement
  search, playlist loading, and background state refresh.
- `costume_voting.html`: complete ballot form and post-vote state.
- `admin_login.html`: admin password form when production admin auth is configured.
- `rsvp.html`: standalone guest RSVP landing page with RSVP prompt, RSVP form
  party-code field, party details, Google Maps directions/embed,
  newest-to-oldest update cards, and optional portal account links.
- `admin.html`: workspace-based admin control room. `/admin` provides
  tonight-at-a-glance cards and next actions; focused guest, public-info,
  program, bar, menu, and account workspaces selectively render the existing
  management controls and POST actions. `/admin/display` contains adaptive
  region/timing/source controls, run-of-show actions, game pinning, notice
  dismissal, and scheduled custom-card CRUD. Individual add/edit records remain
  disclosure rows to keep mobile scanning manageable.
- `dj-admin.js`: Apple Music catalog search and add-song form hydration.
- `dj-live-widgets.js`: shared confirmed-song renderer for attendee and compact
  admin summaries, including artwork lifecycle, stale-response protection,
  five-second refresh, visibility refresh, and optional authenticated SSE.
- `display.html`: standalone live-display page without `base.html`; includes the
  fixed title/header, independent left/center/right stages, CTA/scoreboard/
  karaoke markup, and conditional DJ footer.
- `dj-queue-state.js`: pure MusicKit catalog/library identifier and queue-order
  normalization shared by the browser receiver and dependency-free Node tests.
- `dj-display.js`: display-side MusicKit receiver, load-safe pairing,
  MusicKit-resolved queue capture, event-confirmed track transitions,
  persistent error reporting, reset acknowledgement, serialized command
  acknowledgements/heartbeats, and Now Playing dock updates.
- `email/*.html`: generated HTML email bodies for RSVP confirmation/update,
  host RSVP notification, account welcome, password reset, and drink order
  notifications. These use email-client-safe inline CSS aligned with the dark
  lab-terminal visual system.

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
- Halloween outbound email uses the separate SES domain identity
  `tnq-halloween.com` and must not change existing GoodVines SES identities
  such as `appg-v.com` or `goodvines.app`.

## Extension Guidance

- Keep small changes in the existing single-file Flask style unless asked to refactor.
- If adding durable event data, introduce a clear persistence layer before expanding globals further.
- If changing contest voting, protect vote/index alignment carefully.
- If changing live-display payloads, update the relevant region builder,
  `build_display_layout()`, `templates/display.html`, and `static/display.js`.
- Drink-ready live-display overrides are temporary and include `expires_at`; keep
  server-side cleanup in `/live-display` and `/api/display-data` if adding more
  temporary override types.
- If adding admin actions, call `broadcast_display_update()` whenever display-relevant state changes.
- If adding template pages, extend `base.html` unless the page is a full-screen display mode.

## Results And Recognition Architecture (Schema 17)

- `recognition.py` contains normalization and derived-achievement logic; route,
  archive snapshot, and Redis mutation orchestration remains in `main.py`.
- `event_editions`, `result_archives`, and `recognition_credits` are serialized
  in the canonical state document. Current game/contest state is intentionally
  independent from durable archives so reset operations cannot erase history.
- `safe_game_status_view()` is the only source for attendee live game payloads
  and archived game summaries. Do not place participant maps, account IDs,
  blind-response authors, or MMF ballots in that view.
- `GET /party/results` renders the initial safe snapshot; authenticated
  `GET /api/party/games-data` refreshes it every five seconds with no-store
  caching. It uses polling rather than another long-lived production SSE stream.
- `upsert_game_result_archive()` runs after every completed-game finalization;
  `upsert_costume_result_archive()` runs after winner lock. Both leave an
  official archive immutable when current state is reset or simulated again.
- `publish_result_archive()` rejects simulation, marks the draft official, and
  creates source-referenced idempotent winner credits only for valid linked
  accounts. Public payloads always remove internal `winner_links`.
- Achievement progress is derived at read time from active credits and distinct
  event IDs. Revocation preserves the audit row but removes it from derivation.
- Account deletion clears stable links from credits, result archives, and
  costume entries while retaining historical name/public-identity snapshots.

## Live-Display Media Treatment

- `static/display-media.js` provides the browser/Node-compatible media contract:
  any center-stage entry with `image_url` uses background treatment unless it
  explicitly opts into `media_treatment: "foreground"`.
- Derived game, karaoke, menu/bar, and custom-card payloads still declare the
  background treatment for clarity. `media_tone` selects bounded feature,
  video, custom, or game contrast profiles in `static/display.css`.
- The right bar rail and drink-ready notice share one decorative edge-to-edge
  background layer. Confirmed DJ album art stays foreground because it identifies
  the active track in a status dock rather than a content card.
- Media treatment remains derived display data. It does not change Redis schema
  or persisted display configuration.

## Schema 18 Wrap-Up Architecture

- `party_wrapup.py` owns pure pristine reset, snapshot/back-up sanitation,
  detailed archive construction, and wrap-up/delivery normalization.
- `recap_analytics.py` owns frozen playlist order, recap result projections,
  aggregate analytics, email bar view models, and deterministic sample data.
- Schema 18 adds `event_wrapups`, `game_data_archives`, and `test_email_audit`.
  Older snapshots normalize these to empty values without side effects.
- A wrap-up freezes public results, playlist, analytics, roster, personal
  summaries, achievements, retention policies, and per-recipient outcomes.
- SES calls release the request Redis lock first. Attempt/outcome writes use
  short explicit locks, so successful recipients remain recorded if another fails.
- Cleanup resets active games, applies history retention, sanitizes retained
  full-state backups, and leaves the frozen recap ledger intact.
- Historical exports strip winner links, attendee IDs, delivery destinations,
  private MMF ballots, and blind-voter authorship.
