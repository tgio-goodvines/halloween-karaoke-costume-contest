# Admin Workspace UX Progress

## Goal

Replace the previous single, very long `/admin` document with a compact control-room home and focused admin workspaces. The change keeps important party-night actions reachable without scrolling past unrelated forms or repeated record editors, particularly on phones.

## Implemented 2026-07-26

### Admin information architecture

- `/admin` is the **Tonight** control room. It contains RSVP, bar, costume, and karaoke status cards plus direct next-action links. It intentionally excludes long lists and edit forms.
- `/admin/guests` contains RSVP management, static party details, and RSVP updates/email recipient selection.
- `/admin/public` contains landing-page selection, party-date experience mode, RSVP party code/hint, RSVP host notification recipient, and live-display WiFi values.
- `/admin/program` contains costume contest controls and a compact link to the
  dedicated karaoke operations workspace.
- `/admin/games?game=<game-key>` contains a compact five-game status selector
  and one detailed game console. The selected console includes lifecycle and
  current-round controls, progress, results/display operations, configuration,
  bounded data inspection, simulation, export, and confirmed reset.
- `/admin/karaoke` contains YouTube connection/playlist health, host review,
  attention recovery, approved run of show, synchronization/history, and
  sticky stage controls.
- `/admin/bar` contains bar-operation metrics and bartender tipping settings; the live queue remains in `/bartender`.
- `/admin/menu` contains menu item CRUD.
- `/admin/accounts` contains account creation, account updates, password resets, and bartender role assignment.

The route continues to use the existing `admin_portal` POST action handler, so existing CSRF validation, Redis persistence, and mutation behavior are preserved. Each form posts to its focused URL automatically.

Standard admin POST submissions update the workspace in place. Stable browser-
tab state preserves the selected query, action-relative viewport position,
expanded disclosures, and logical focus. Specialized or non-enhanced forms use
the same state for navigation/reload restoration.

### Responsive behavior

- Admin workspace navigation is a visible horizontal chip rail rather than a second stack of cards. It is sticky on mobile and may scroll horizontally; each chip remains touch-sized.
- The Games selector is a second, task-specific rail beneath the workspace
  navigation. It is five columns on desktop and independently scrollable and
  sticky on phones.
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

### Party Games verification (2026-08-05)

- Browser-verified `/admin/games` at 1280px and `390x844` with no horizontal
  overflow.
- Browser-verified the enable control, participant count/status update, and
  the minimum-two-participant start validation.
- Browser-verified `/party` and `/party/games` enrollment/submission at
  `390x844`, plus anonymous clue data and the third game count on
  `/live-display` at phone and desktop widths.
- Browser console reported no errors or warnings during the final live-display
  check.
- Re-verified the expanded five-game admin registry at 1280px with document
  width matching the viewport and no browser errors. Browser QA exercised MMF
  and prompt-game enablement, two anonymous attendee opt-ins, both game starts,
  and opening a Fill in the Blank response round.

### YouTube karaoke workspace verification (2026-07-30)

- Browser-verified `/admin/karaoke` at normal desktop and `390x844`.
- Verified the workspace rail remains horizontally scrollable on phones, the
  connection/metrics cards collapse cleanly, and the stage rail becomes the
  first normal-flow section.
- Verified the attendee `/party/karaoke` guided search/selection layout at
  `390x844`, including hidden pagination before results and a full-width empty
  selection prompt.

- `python -m pytest` — 70 passing tests.
- `python -m compileall main.py` — passed.
- Browser-checked the Tonight and Program workspaces at desktop and 390×844.
- Confirmed every workspace returns `200`, invalid workspace paths return `404`, and the mobile document width equals the viewport width.

## Extension Rules

- Place new admin controls in one existing workspace, or create a new focused workspace only when it represents a distinct operational job.
- Keep `/admin` as a summary/action hub; do not reintroduce full lists or settings forms there.
- Use disclosure for an individual edit record or explicitly destructive action, not as the primary means of navigating unrelated controls.
- Keep mobile repeated items as rows; reserve elevated cards for a workspace boundary, an urgent status, or media-rich attendee content.
