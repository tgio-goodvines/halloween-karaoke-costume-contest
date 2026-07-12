# Food, Drink, And Bartender Feature

## Routes

- `GET|POST /party/menu`: regular attendee menu page. Guests can view food and drink cards with images. Available drinks can be ordered; food is view-only.
- `GET|POST /bartender`: bartender queue. Requires a `bartender` session role or an admin session. Admins can use the same view.
- `/admin`: includes menu management, bar operations summary, bartender-view link, and user role assignment.

## State

The Redis state document stores these additional schema-v2-compatible keys:

- `menu_items`: list of food/drink dictionaries with `id`, `name`, `category`, `description`, `image_url`, `recipe`, `available`, and `created_at`.
- `drink_orders`: list of drink order dictionaries with attendee/account snapshot, menu item snapshot, `status`, `estimated_ready_at`, `created_at`, `started_at`, `completed_at`, and `completed_seconds`.
- `user_accounts[normalized_username]["roles"]`: account roles. Existing accounts hydrate to at least `["regular"]`; admins can add/remove `bartender`.

Drink orders snapshot `item_name`, `item_image_url`, and `recipe` at order time so active orders are not changed unexpectedly by later menu edits.

## Order Lifecycle

Statuses are `received`, `in_progress`, and `complete`.

`completed_seconds` measures prep duration from `started_at` to `completed_at`, falling back to `created_at` if the order is completed without being started first. Estimates use recent completed prep durations, defaulting to 8 minutes when there is no history, multiplied by active queue depth.

## Email

The existing Halloween SES settings are reused for order placed and drink ready emails:

- `templates/email/drink_order_placed.html`
- `templates/email/drink_order_ready.html`

Do not alter GoodVines SES identities or sender addresses.

## Live Display

Completing a drink creates `live_display_override` with `type="drink_ready"`, attendee name, drink name, `image_url`, and an `expires_at` timestamp. `/live-display` and `/api/display-data` clean up expired overrides. `static/display.js` renders the image in the general override layout and applies drink-specific styling.

## Templates And Styling

- `templates/menu.html`: attendee menu and recent order cards.
- `templates/bartender.html`: active bartender queue, recipe reference, status forms, and recent completed orders.
- `templates/admin.html`: menu CRUD with image URL preview, availability toggle, recipes, user bartender role assignment, and bar operations summary.
- `static/styles.css`: menu cards, order cards, bartender cards, admin image previews, and responsive behavior.
- `static/display.css`: drink-ready override image layout.

## Tests

`tests/test_redis_state.py` covers state round-trip, menu image persistence, attendee drink ordering, food-order rejection, bartender authorization, bartender status transitions, ready email sending, and live-display drink-ready override payloads.
