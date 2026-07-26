# Admin Workspace UX Progress

## Goal

Replace the previous single, very long `/admin` document with a compact control-room home and focused admin workspaces. The change keeps important party-night actions reachable without scrolling past unrelated forms or repeated record editors, particularly on phones.

## Implemented 2026-07-26

### Admin information architecture

- `/admin` is the **Tonight** control room. It contains RSVP, bar, costume, and karaoke status cards plus direct next-action links. It intentionally excludes long lists and edit forms.
- `/admin/guests` contains RSVP management, static party details, and RSVP updates/email recipient selection.
- `/admin/public` contains landing-page selection, party-date experience mode, RSVP party code/hint, RSVP host notification recipient, and live-display WiFi values.
- `/admin/program` contains costume contest controls, karaoke controls, vote status, and both lineup management surfaces.
- `/admin/bar` contains bar-operation metrics and bartender tipping settings; the live queue remains in `/bartender`.
- `/admin/menu` contains menu item CRUD.
- `/admin/accounts` contains account creation, account updates, password resets, and bartender role assignment.

The route continues to use the existing `admin_portal` POST action handler, so existing CSRF validation, Redis persistence, and mutation behavior are preserved. Each form posts to its focused URL automatically.

### Responsive behavior

- Admin workspace navigation is a visible horizontal chip rail rather than a second stack of cards. It is sticky on mobile and may scroll horizontally; each chip remains touch-sized.
- The Tonight status grid becomes flat, separated operational rows on phone widths. Repeated admin editors are flat list rows until an individual editor is expanded.
- The admin shell, nav, and home surface explicitly allow shrinking below their intrinsic desktop width. This prevents horizontal page overflow at 390px.
- Program controls now expose only valid next actions. Reset actions are placed in a descriptive danger disclosure instead of appearing beside normal party-night actions.

### Attendee organization refinements

- The party dashboard now shows the three most recent costume and karaoke entries with counts and a link to the dedicated list page, rather than duplicating complete lineups in the hub.
- RSVP updates show the three newest cards first; earlier updates remain available under an explicit disclosure.
- Costume and karaoke signup pages show eight entries initially and disclose the remaining public list when necessary.
- Menu and order-history pages link directly to one another from their headers.
- Costume-voting submit remains visible at the bottom of the viewport while a guest works through a long ballot.

## Verification

- `python -m pytest` — 70 passing tests.
- `python -m compileall main.py` — passed.
- Browser-checked the Tonight and Program workspaces at desktop and 390×844.
- Confirmed every workspace returns `200`, invalid workspace paths return `404`, and the mobile document width equals the viewport width.

## Extension Rules

- Place new admin controls in one existing workspace, or create a new focused workspace only when it represents a distinct operational job.
- Keep `/admin` as a summary/action hub; do not reintroduce full lists or settings forms there.
- Use disclosure for an individual edit record or explicitly destructive action, not as the primary means of navigating unrelated controls.
- Keep mobile repeated items as rows; reserve elevated cards for a workspace boundary, an urgent status, or media-rich attendee content.
