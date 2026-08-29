# Food, Drink, And Bartender Feature

## Routes

- `GET|POST /party/menu`: consolidated regular-attendee Menu & Orders workspace,
  available on the party date and redirected to `/party` before then.
  `view=menu` shows food/drink cards and ordering; `view=orders` groups the
  current account's Ready, Preparing, Received, and Previous orders and supports
  eligible reorders. Food remains view-only, and non-orderable drinks can be
  listed as bar-pickup/general availability.
- `GET|POST /party/drink-history`: compatibility route. GET redirects to
  `/party/menu?view=orders`; POST temporarily accepts legacy account-scoped
  reorder submissions through the same helper as the canonical route.
- `GET /api/party/bar-queue`: regular-attendee, party-day-protected JSON with
  aggregate active/mixing/waiting counts, average prep time, and only the
  current account's active/recent-ready order positions. It never exposes other
  guests' identities, recipes, or operational controls.
- `POST /party/drink-orders/<order_id>/pickup`: account-scoped, party-day pickup
  acknowledgement for completed orders. It supports dashboard and My Orders
  return contexts, rejects non-owners, and is idempotent.
- `GET|POST /bartender`: bartender queue. Requires a `bartender` session role or an admin session. Admins can use the same view.
- `GET /api/bartender-queue`: authenticated bartender/admin JSON endpoint
  returning the rendered queue fragment and a deterministic queue version for
  real-time bartender page refreshes.
- `/admin`: includes menu management, specialty/standard drink classification,
  bartender tip settings, bar operations summary, bartender-view link, and user
  role assignment.

## State

The Redis state document stores these menu/order keys; schema 19 adds durable
pickup acknowledgement:

- `menu_items`: list of food/drink dictionaries with `id`, `name`, `category`,
  `description`, `image_url`, `recipe`, `available`, `drink_type`
  (`standard`/`specialty`), `beverage_type`
  (`alcoholic`/`non_alcoholic`), `orderable`, and `created_at`.
- `drink_orders`: list of drink order dictionaries with attendee/account
  snapshot, menu item snapshot, `drink_type`, `beverage_type`, `orderable`,
  `specialty_sequence_number`, `specialty_extra_request`,
  `specialty_extra_window_open`, `status`, `estimated_ready_at`, `created_at`,
  `started_at`, `completed_at`, optional `picked_up_at`, and
  `completed_seconds`.
- `bartender_tip_settings`: admin-managed tip prompt settings with `enabled`,
  `display_name`, `note`, `image_url`, and optional `zelle`, `paypal`,
  `venmo`, and `cash_app` handles.
- `user_accounts[normalized_username]["roles"]`: account roles. Existing accounts hydrate to at least `["regular"]`; admins can add/remove `bartender`.

Drink orders snapshot `item_name`, `item_image_url`, `recipe`, drink
classification, and specialty sequence metadata at order time so active and
historical orders are not changed unexpectedly by later menu edits.

## Specialty Drink Rules

Attendees can order 3 specialty drinks from the bar during the main event
window. After 11:00 PM local party time, additional specialty drink requests are
allowed only while the drink remains available. Standard alcoholic and
non-alcoholic drinks do not count against the 3 specialty drink rule.

The bartender queue labels specialty orders with their sequence number. 4th+
specialty requests are marked as after-11 PM extra requests with an availability
check note. Active orders follow strict first-in, first-out arrival order. The
workspace exposes one Current Drink, one Up Next, and an ordered backlog; only
the current order can be started or completed, and completion requires it to be
in progress. An already-in-progress legacy drink remains current. The browser
refreshes the queue fragment every few seconds through
`/api/bartender-queue`, so newly placed attendee drink orders appear without a
manual page reload.

Admin-entered recipes normalize to one ingredient per line. Bartender Current,
Up Next, and backlog cards render those ingredients as lists while recipes stay
excluded from attendee and live-display payloads.

The attendee Menu & Orders workspace separately polls
`/api/party/bar-queue` every five seconds. It uses the same sorted active-order
sequence to calculate the current account's approximate positions, but returns
only aggregate totals and account-scoped order details. The attendee endpoint
does not reuse or weaken the bartender fragment/API.

## Order Lifecycle

Statuses are `received`, `in_progress`, and `complete`.

`completed_seconds` measures prep duration from `started_at` to `completed_at`, falling back to `created_at` if the order is completed without being started first. Estimates use recent completed prep durations, defaulting to 8 minutes when there is no history, multiplied by active queue depth.

Completed drink-ready notices appear on `/party` for 5 minutes after
`completed_at`, but completed orders remain visible permanently on
`/party/menu?view=orders`. Recent completed orders also appear as Ready for
Pickup in the consolidated live bar status. Attendees can acknowledge pickup
from the dashboard, My Orders, or that live status. Acknowledgement stores
`picked_up_at` and ends ready prominence without removing the completed order;
older unacknowledged orders remain in Previous Orders and can still be
acknowledged.

## Email

The existing Halloween SES settings are reused for order placed and drink ready emails:

- `templates/email/drink_order_placed.html`
- `templates/email/drink_order_ready.html`

Do not alter GoodVines SES identities or sender addresses.

## Live Display

Completing a drink creates a `drink_ready` notice with attendee name, drink
name, `image_url`, and a configurable expiration (default 10 seconds). The
current notice lives in `live_display_notice_override`; subsequent notices use
the bounded `live_display_notice_queue` and advance sequentially. The adaptive
display renders the current notice across the full right stage with a bright
neon red background without replacing the center rotation or an event
spotlight. With active orders, the queue layout remains primary while available
food/drink promotions rotate in the bottom zone. Without an active queue,
promotions occupy top/middle/bottom around retained completed-order history;
history-only layouts remain visible. The stage collapses only when no notice,
active queue, completed history, or available menu item exists.

## Templates And Styling

- `templates/menu.html`: consolidated attendee shell with summary chips,
  Browse Menu/My Orders rail, privacy-safe live bar status, and selected view.
- `templates/_menu_catalog.html`: food/drink catalog and order forms.
- `templates/_personal_drink_orders.html`: status-grouped full attendee order
  history, pickup acknowledgement, reorder buttons, and one bartender-tip
  callout.
- `templates/drink_history.html`: retired template; the legacy route redirects
  to the consolidated My Orders view.
- `templates/bartender.html`: bartender page shell and live queue container.
- `templates/_bartender_queue.html`: active bartender queue, recipe reference,
  status forms, and recent completed orders, shared by the full page and queue
  JSON endpoint.
- `templates/admin.html`: menu CRUD with image URL preview, availability toggle,
  specialty/standard drink controls, orderable toggle, recipes, bartender tip
  settings, user bartender role assignment, and bar operations summary.
- `static/styles.css`: menu cards, order cards, bartender cards, admin image previews, and responsive behavior.
- `static/bartender.js`: authenticated polling refresh for the bartender queue
  fragment.
- `static/bar-status.js`: five-second visibility-aware attendee polling for
  aggregate queue metrics and personal live orders, including safe pickup forms.
- `static/display.js`: keyed independent bar promotion/history rotation that
  survives regular SSE/poll refreshes.
- `static/display.css`: dynamic bar compositions and full-stage neon red
  drink-ready treatment.

## Tests

`tests/test_redis_state.py` covers state round-trip, party-date gating for the
attendee menu, menu image persistence, attendee drink ordering,
food-order rejection, bartender authorization, bartender status transitions,
specialty drink limit enforcement, consolidated order history/reorder behavior,
legacy route compatibility, privacy-safe attendee queue payloads, bartender
queue API refresh payloads, strict FIFO/current-only transitions, normalized
ingredient rendering, tip QR rendering, ready-notice expiry, ready email
sending, and live-display drink-ready override payloads. Bartender authorization
and operational behavior remain separately covered.

Schema-19 coverage additionally verifies pickup ownership/idempotence, retained
completed history, legacy pickup-field backfill, safe display history, menu
promotion inclusion/exclusion, and truly empty bar-stage collapse.

## Consolidation Verification (2026-08-29)

- `python -m compileall -q main.py party_games.py` passed.
- Full Python suite passed: 196 tests and 21 subtests.
- `static/bar-status.js` passed the bundled Node syntax check.
- Browser QA at 1280×800 and 390×844 confirmed both Menu & Orders views,
  account-scoped queue content, sticky mobile navigation, one-column phone
  cards, and no horizontal overflow.
- Regular-attendee navigation showed one Menu & Orders item and no Bartender or
  Drink History item. Automated combined-role coverage confirmed Bartender
  remains separately visible to bartender/admin sessions.
- No bartender operational forms, recipes, or other-guest identity appeared in
  the attendee page/API. Existing bartender queue/update tests remained green.
