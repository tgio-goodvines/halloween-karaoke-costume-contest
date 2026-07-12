# Food, Drink, And Bartender Feature

## Routes

- `GET|POST /party/menu`: regular attendee menu page, available on the party
  date and redirected to `/party` before then. Guests can view food and drink
  cards with images. Available orderable drinks can be ordered; food is
  view-only, and non-orderable drinks can be listed as bar-pickup/general
  availability.
- `GET|POST /party/drink-history`: regular attendee drink history page,
  available on the party date and redirected to `/party` before then. Shows all
  drink orders tied to the signed-in account, including old completed orders,
  and supports reordering currently available/orderable drinks.
- `GET|POST /bartender`: bartender queue. Requires a `bartender` session role or an admin session. Admins can use the same view.
- `/admin`: includes menu management, specialty/standard drink classification,
  bartender tip settings, bar operations summary, bartender-view link, and user
  role assignment.

## State

The Redis state document stores these additional schema-v2-compatible keys:

- `menu_items`: list of food/drink dictionaries with `id`, `name`, `category`,
  `description`, `image_url`, `recipe`, `available`, `drink_type`
  (`standard`/`specialty`), `beverage_type`
  (`alcoholic`/`non_alcoholic`), `orderable`, and `created_at`.
- `drink_orders`: list of drink order dictionaries with attendee/account
  snapshot, menu item snapshot, `drink_type`, `beverage_type`, `orderable`,
  `specialty_sequence_number`, `specialty_extra_request`,
  `specialty_extra_window_open`, `status`, `estimated_ready_at`, `created_at`,
  `started_at`, `completed_at`, and `completed_seconds`.
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
check note. Active bartender queue sorting keeps in-progress orders first, then
normal/included orders, then first-come-first-served 4th+ specialty requests.

## Order Lifecycle

Statuses are `received`, `in_progress`, and `complete`.

`completed_seconds` measures prep duration from `started_at` to `completed_at`, falling back to `created_at` if the order is completed without being started first. Estimates use recent completed prep durations, defaulting to 8 minutes when there is no history, multiplied by active queue depth.

Completed drink-ready notices appear on `/party` for 5 minutes after
`completed_at`, but completed orders remain visible permanently on
`/party/drink-history`.

## Email

The existing Halloween SES settings are reused for order placed and drink ready emails:

- `templates/email/drink_order_placed.html`
- `templates/email/drink_order_ready.html`

Do not alter GoodVines SES identities or sender addresses.

## Live Display

Completing a drink creates `live_display_override` with `type="drink_ready"`, attendee name, drink name, `image_url`, and an `expires_at` timestamp. `/live-display` and `/api/display-data` clean up expired overrides. `static/display.js` renders the image in the general override layout and applies drink-specific styling.

## Templates And Styling

- `templates/menu.html`: attendee menu and recent order cards.
- `templates/drink_history.html`: full attendee order history, reorder buttons,
  and per-order bartender tip disclosure with the configured QR/payment image.
- `templates/bartender.html`: active bartender queue, recipe reference, status forms, and recent completed orders.
- `templates/admin.html`: menu CRUD with image URL preview, availability toggle,
  specialty/standard drink controls, orderable toggle, recipes, bartender tip
  settings, user bartender role assignment, and bar operations summary.
- `static/styles.css`: menu cards, order cards, bartender cards, admin image previews, and responsive behavior.
- `static/display.css`: drink-ready override image layout.

## Tests

`tests/test_redis_state.py` covers state round-trip, party-date gating for the
attendee menu, menu image persistence, attendee drink ordering,
food-order rejection, bartender authorization, bartender status transitions,
specialty drink limit enforcement, order history/reorder behavior, bartender
priority sorting for 4th+ specialty requests, tip QR rendering, ready-notice
expiry, ready email sending, and live-display drink-ready override payloads.
