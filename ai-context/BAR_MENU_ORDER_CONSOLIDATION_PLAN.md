# Menu And Drink Order History Consolidation Plan

## Implementation Status — Complete 2026-08-29

The revised scope is implemented. `/party/menu` now provides the Browse Menu
and My Orders views, `/party/drink-history` is a compatibility route, and the
shared dropdown exposes one `Menu & Orders` attendee item. The separate
`Bartender` item, `/bartender` page, protected fragment API, polling script,
recipes, queue actions, and admin links were preserved.

`/api/party/bar-queue` and `static/bar-status.js` provide five-second,
visibility-aware attendee updates using aggregate queue counts plus only the
signed-in account's active/recent-ready drink details and approximate position.
Automated verification passed with 196 tests and 21 subtests. Browser QA passed
at 1280×800 and 390×844 with no horizontal overflow, correct responsive rails,
no attendee-visible bartender controls/recipes/other-guest identity, and no new
console errors after the live polling server was stable.

## Revised Scope

Consolidate the attendee `Menu` and `Drink History` destinations into one
`Menu & Orders` workspace while preserving the bartender experience exactly as
its own role-restricted workflow.

The bartender dropdown item, `/bartender` page, operational queue controls,
queue fragment, and polling endpoint remain separate. Regular attendees still
must not gain access to bartender recipes, guest-identifying queue data, or
order-transition controls.

## Target Navigation

Update the shared dropdown as follows:

- Replace the attendee `Menu` and `Drink History` links with one
  `Menu & Orders` link.
- Keep the `Bartender` link unchanged and visible only to bartender/admin
  sessions.
- Keep the `Admin` link and the single logout action unchanged.

Use the existing attendee route as the canonical destination:

- `/party/menu` — consolidated Menu & Orders workspace.
- `/party/menu?view=menu` — browse food and drinks and place an order.
- `/party/menu?view=orders` — view active and historical personal orders,
  reorder eligible drinks, and reach the bartender tip page.

Keeping `/party/menu` canonical minimizes changes to existing emails, live
display CTAs, bookmarks, route protection, and party-day gating.

The old `/party/drink-history` route should remain as a compatibility route:

- `GET /party/drink-history` redirects to `/party/menu?view=orders`.
- Temporary legacy POST support should call the shared reorder logic and then
  redirect to `/party/menu?view=orders`; do not redirect a submitted POST in a
  way that loses or duplicates the action.

## Bartender Preservation Boundary

The following behavior is explicitly unchanged:

- The `Bartender` dropdown item remains separate and keeps its current
  bartender/admin visibility rule.
- `GET|POST /bartender` remains the bartender/admin operational page.
- `GET /api/bartender-queue` remains bartender/admin protected.
- `templates/bartender.html` remains the bartender page shell.
- `templates/_bartender_queue.html` retains active-order cards, recipes,
  priority notes, start/complete forms, and recent completions.
- `static/bartender.js` continues its three-second authenticated queue-fragment
  polling.
- Queue sorting, order transitions, prep-duration tracking, ready emails,
  live-display notices, and Redis persistence do not change.
- `/admin/bar` and `/admin/menu` remain separate focused admin workspaces.

No bartender operational markup or endpoint should be embedded in the attendee
page. Links from admin surfaces to the bartender queue continue to point to
`/bartender`.

## Consolidated Attendee Page Design

### 1. Shared Menu & Orders header

Restyle the current menu header into a shared workspace header:

- Page title: `Menu & Orders`.
- Short description: browse tonight's food and drinks, order from the bar, and
  track pickup status in one place.
- Retain the current menu feature artwork.
- Show compact, attendee-safe summary chips:
  - specialty included orders used;
  - the attendee's active order count;
  - the attendee's ready-for-pickup count;
  - approximate bar wait or average prep time.

Use the current modern dark-neon design system: rounded backlit surfaces,
Outfit/Figtree typography, red halo focus states, and the existing zinc/red
palette. Extend `static/styles.css`; do not add a UI dependency.

### 2. Internal view rail

Place a compact, server-rendered rail below the header:

- `Browse Menu`
- `My Orders` with a personal order-count badge when nonzero

The active link uses `aria-current="page"`. The rail works without JavaScript.
On phones it becomes a touch-safe horizontal/sticky rail using the established
admin/game workspace pattern.

Only the selected view should render its full repeated-card collection. This
avoids combining a long menu and complete order history into one expensive,
hard-to-scan mobile document.

### 3. Browse Menu view

Preserve current menu and ordering behavior while improving hierarchy:

- Keep drinks first because they are actionable; retain food as a separate
  view-only section.
- Preserve availability, standard/specialty, alcoholic/non-alcoholic, and
  orderable/bar-pickup badges.
- Use explicit action states: `Order Drink`, `Pick Up at Bar`, and
  `Unavailable`.
- Keep the specialty-drink allowance/status near the shared header instead of
  repeating it in multiple pages.
- After a successful order, redirect to `/party/menu?view=orders` so the guest
  sees confirmation and live status immediately.
- Provide a clear `Order another drink` link back to `view=menu`.

### 4. My Orders view

Move the existing drink-history functionality into the consolidated menu
template and group orders by current relevance:

1. `Ready for Pickup`
2. `Being Prepared`
3. `Order Received`
4. `Previous Orders`

Retain each order's item snapshot, status, estimated/completed time, drink
classification, specialty sequence, order ID, and reorder eligibility.

Reordering must remain scoped to `session.user_id` and must revalidate the
current menu item's availability/orderability and specialty limits at submit
time.

When tipping is enabled, show one bartender-support callout above completed
orders instead of repeating a tip button on every historical order. Keep
`/party/bartender-tip` as its existing focused page, but return users to
`/party/menu?view=orders`.

## Attendee-Safe Bar Queue Exposure

Expose useful queue status on the consolidated attendee workspace without
reusing or weakening the protected bartender API.

### Recommended attendee queue content

Show a compact `Bar Queue` status panel above the active Menu or My Orders
view with:

- total active-order count;
- approximate average prep time;
- counts currently `Being Prepared` and `Waiting`;
- each current user's active orders, status, estimate, and approximate number
  of orders ahead;
- a ready-for-pickup state when one of the user's orders completes.

Do not expose:

- other attendees' names, email addresses, account IDs, or full order history;
- drink recipes;
- start/complete controls;
- raw bartender queue HTML;
- internal specialty-priority notes about another attendee's order.

If an ambient queue visualization is desired, show anonymous ticket positions
or aggregate status counts only. The user's own orders may be labeled with the
drink name; other orders should be anonymous.

### Safe queue data contract

Add a regular-attendee, party-day-protected endpoint such as:

- `GET /api/party/bar-queue`

Return a small JSON payload containing:

- `queue_version`;
- `active_count`, `mixing_count`, and `waiting_count`;
- `average_prep_label`;
- account-scoped `personal_orders` with safe status/position fields only.

Compute position from the same sorted active-order sequence used by the
bartender queue so the two surfaces agree. Do not return the rendered
`_bartender_queue.html` fragment.

Add a small attendee script, for example `static/bar-status.js`, that:

- polls at five seconds rather than the bartender page's three seconds;
- pauses while the document is hidden and refreshes when visibility returns;
- rejects stale/out-of-order responses using `queue_version` or request order;
- updates only the queue summary and personal live-order cards;
- preserves the server-rendered initial state and remains useful when
  JavaScript is unavailable.

This keeps the protected bartender workflow isolated while giving attendees a
live view of bar progress.

## Route And Action Structure

Keep `/party/menu` in the existing regular-user protection and party-day gate.
Use an explicit action field for its two mutation types:

- `order_drink`
- `reorder_drink`

Extract the existing order and reorder bodies into shared helpers so the
canonical and temporary legacy routes do not duplicate validation.

Both actions must preserve:

- CSRF validation;
- account ownership checks;
- specialty-drink limits and after-11 PM rules;
- menu availability and orderability checks;
- unique order creation and snapshots;
- SES order confirmation;
- Redis persistence;
- post/redirect/get behavior.

Do not add bartender transitions to `/party/menu`; those continue posting only
to `/bartender`.

## Template And File Plan

### Primary changes

- `main.py`
  - accept `view=menu|orders` in `party_menu`;
  - build grouped attendee-order context;
  - share order/reorder helpers;
  - add the attendee-safe bar queue payload/endpoint;
  - retain all bartender routes and protections unchanged.
- `templates/base.html`
  - replace `Menu` and `Drink History` with one `Menu & Orders` link;
  - leave the bartender conditional/link unchanged.
- `templates/menu.html`
  - become the consolidated workspace shell;
  - render the shared header, safe queue summary, view rail, and selected view.
- Add `templates/_menu_catalog.html` for the existing drink/food catalog.
- Add `templates/_personal_drink_orders.html` for grouped personal orders.
- Add `static/bar-status.js` for safe attendee polling.
- `static/styles.css`
  - add narrowly scoped workspace rail, queue summary, summary chip, and order
    group styling;
  - reuse existing menu/order cards and mobile performance safeguards.

### Existing files retained

- Keep `templates/bartender.html` unchanged.
- Keep `templates/_bartender_queue.html` unchanged unless a separate bartender
  bug is discovered.
- Keep `static/bartender.js` unchanged.
- Retire `templates/drink_history.html` only after its route becomes a tested
  compatibility path.

### Link updates

- `templates/index.html`
  - combine the attendee `Menu` and `Bar` feature cards into one
    `Menu & Orders` card;
  - point ready-drink and history actions to `view=orders`.
- `templates/bartender_tip.html`
  - return to `/party/menu?view=orders`.
- Drink placed/ready emails
  - use `view=orders` for status links.
- Live-display bar CTA
  - continue pointing to `/party/menu` or explicitly `view=menu`.
- Admin bartender actions
  - continue pointing to `/bartender` without change.

## Implementation Sequence

### Phase 1: Consolidate route logic

- Extract shared order/reorder helpers.
- Add view normalization and grouped order context to `/party/menu`.
- Add safe legacy behavior for `/party/drink-history`.

### Phase 2: Build the combined attendee workspace

- Restructure `menu.html` and add catalog/order partials.
- Add the shared header, summary chips, view rail, and status-first order
  groups.
- Consolidate the tipping callout.

### Phase 3: Add safe queue visibility

- Add an account-scoped queue summary builder and attendee API.
- Render the initial safe status on the server.
- Add five-second visibility-aware polling for live updates.

### Phase 4: Update navigation and links

- Collapse the two attendee dropdown links into `Menu & Orders`.
- Combine attendee dashboard feature cards.
- Update ready-order, history, email, and tip links.
- Verify every bartender/admin link still goes to `/bartender`.

### Phase 5: Responsive refinement and verification

- Add scoped desktop/mobile styling.
- Run compilation, Python tests, and JavaScript syntax/tests.
- Browser-check attendee, bartender, admin, combined-role, and role-preview
  sessions at desktop and `390x844`.
- Update durable context documentation after implementation succeeds.

## Test Plan

Add or update tests for:

- The regular dropdown contains one `Menu & Orders` item and no separate
  `Drink History` item.
- Bartender/admin sessions still see a separate `Bartender` dropdown item.
- Regular attendees never see the bartender item or access `/bartender` and
  `/api/bartender-queue`.
- Role preview preserves the existing bartender hidden/access behavior.
- `/party/menu?view=menu` and `view=orders` render only permitted attendee
  content and retain party-day gating.
- Ordering, food-order rejection, specialty limits, order snapshots, email,
  and persistence remain unchanged.
- Order history remains account-scoped and reorder creates a unique new order.
- `/party/drink-history` GET redirects to `view=orders` and legacy POST support
  neither loses nor duplicates reorders.
- The attendee queue payload includes aggregates and only the signed-in user's
  order details.
- The attendee queue payload excludes other usernames, recipes, emails,
  account IDs, and operational forms/actions.
- Personal queue positions match the bartender queue's sorting rules.
- The bartender page still polls, starts, and completes orders and still sends
  ready email/display notices.
- Dashboard, email, tip, and live-display links point to the correct
  consolidated view while admin bartender links still use `/bartender`.
- The consolidated page has no horizontal overflow at desktop and `390x844`,
  the rail is keyboard accessible, and polling does not disturb scroll/focus.

## Acceptance Criteria

- `Menu` and `Drink History` become one attendee `Menu & Orders` destination.
- `Bartender` remains a separate dropdown item and a separate protected page.
- Attendees can browse, order, track current orders, review history, reorder,
  and reach tipping inside one shared workspace shell.
- The consolidated page shows live, privacy-safe bar queue status without
  exposing bartender-only data or controls.
- Bartender functionality, authorization, polling, recipes, priority sorting,
  transitions, emails, and live-display behavior remain unchanged.
- Old drink-history links continue to work.
- No Redis schema change is required.

## Deliberate Non-Goals

- Do not merge the bartender operational page into the attendee workspace.
- Do not remove or rename the bartender dropdown item.
- Do not expose the protected bartender queue fragment or API to attendees.
- Do not merge `/admin/bar` and `/admin/menu`.
- Do not change specialty limits, queue priority, prep estimates, order states,
  Redis schema, or live-display bar layout.
