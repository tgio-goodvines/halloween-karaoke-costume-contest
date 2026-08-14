# Admin Games Workspace Reorganization

## Objective

Keep party-game operations usable as game configuration and event data grow,
and prevent admin actions from returning the operator to the top of a workspace.

## Implemented 2026-08-14

### Selected-game workspace

- `/admin/games?game=<game-key>` now renders one detailed game console at a
  time. Invalid or omitted keys select Two Truths and a Lie.
- A compact five-game selector keeps phase, simulation status, and player counts
  visible for the complete lineup. On phones it becomes a sticky horizontal
  rail beneath the main admin workspace navigation.
- The selected console is organized by operational priority: lifecycle/current
  round, progress, results/display, configuration, data inspection, test tools,
  and reset.
- Lifecycle and current-round actions remain exposed. Large prompt decks, MMF
  configuration, participant statements, raw guesses, test tools, and reset
  actions use focused disclosures.
- Scoreboards render the first 20 rows and Two Truths inspection tables render
  at most 50 rows. The aggregate game export remains the source for complete
  datasets.

### Data construction

- Every admin workspace receives lightweight summaries for all five games.
- Detailed statistics, prompt/round configuration, participants, guesses,
  winners, and simulation data are built only for the game selected on
  `/admin/games`.
- Non-Games admin workspaces no longer build a full Two Truths detail model just
  to display Games navigation counts.

### In-place admin actions

- Standard same-origin admin POST forms are progressively enhanced with
  `fetch`. The existing Flask action handler, CSRF validation, persistence, and
  complete HTML response remain the source of truth and the no-JavaScript
  fallback.
- After a successful action, the returned `.admin-panel` replaces the current
  panel without a browser navigation. Success and validation messages are
  included in the replacement.
- The controller records stable view keys, the selected URL query, open
  disclosures, the action anchor's viewport offset, and the pressed control.
  It restores the anchor after layout and font settling and returns focus to the
  same or logical replacement control.
- Toggle counterparts are explicitly paired for enable/disable and
  pause/resume controls. Repeated previous/next and result-presentation actions
  remain on the same control.
- Specialized Karaoke actions retain their existing API controller. Reloads
  requested by its external-state polling save and restore the same stable view
  state. DJ helpers reinitialize or retarget themselves after an admin-panel
  replacement.
- Network, authorization, or invalid HTML responses fail visibly in the current
  workspace. Redirects to authentication remain full navigation by design.

## Files

- `main.py` — lightweight game summaries, selected detail construction, and
  selected-game query handling.
- `templates/_admin_games.html` — game selector and the selected operational
  console.
- `templates/admin.html` — includes the Games partial and enables inline admin
  updates.
- `static/preserve-scroll.js` — stable view-state persistence and progressive
  admin-panel replacement.
- `static/styles.css` — selected-game hierarchy and responsive selector rail.
- `static/dj-admin.js`, `static/dj-admin-status.js`, and
  `static/karaoke-admin.js` — compatibility with panel replacement or
  view-preserving reloads.

## Verification

- Full Python test suite: 143 tests and 16 subtests passed.
- Python compilation passed for `main.py` and `party_games.py`.
- Bundled Node syntax checks passed for all changed JavaScript files.
- Browser QA verified:
  - five selector entries and exactly one detailed game console;
  - query-backed game selection;
  - enable/disable and prompt toggles without URL navigation;
  - one-pixel-or-less anchor movement after visible repeated actions;
  - open prompt-deck preservation and logical focus restoration;
  - Display pause/resume controls outside the Games workspace;
  - `390x844` layout with document width equal to the viewport and an
    independently scrollable five-game rail; and
  - no browser console warnings or errors.

## Extension Rules

- Add a game to `GAME_CATALOG`; do not add another always-rendered admin
  console.
- Give dynamic records and disclosures stable `data-view-key` values.
- Keep normal admin POST behavior functional without JavaScript.
- Mark a form `data-full-navigation` only when leaving or downloading from the
  current workspace is intentional.
- Do not store view state in Redis or the Flask session; it is browser-tab UI
  state and belongs in `sessionStorage`.
