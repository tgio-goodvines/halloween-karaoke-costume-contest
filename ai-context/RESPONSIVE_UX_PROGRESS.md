# Responsive UX Progress

## Goal

Improve the live display, attendee flow, and admin portal so they work cleanly
in normal browser windows and on mobile phone browsers.

## Implementation Order

1. Live display dynamic scaling and card fit.
2. Attendee mobile navigation, forms, and summaries.
3. Admin mobile hierarchy and entry management.
4. Browser viewport verification and test run.

## Current Findings

- `templates/display.html` renders one dominant live card, but the layout needs
  explicit browser-size modes beyond the original TV/projector shape.
- `static/display.css` uses large viewport-driven type and card spacing that can
  feel oversized or clip in normal browser windows.
- `static/display.js` contains karaoke lineup rotator logic, but
  `templates/display.html` only includes the countdown panel markup.
- Shared attendee/admin pages use `templates/base.html` and `static/styles.css`.
  The existing mobile nav stacks every link, consuming vertical space.
- `templates/admin.html` exposes every edit form at once, which creates a long
  and dense phone experience.

## Progress

- Complete: live display scaling.
  - Added display sizing CSS variables and browser-height/width breakpoints.
  - Added long/dense display card classes from `static/display.js`.
  - Added overflow wrapping and safer scoreboard/karaoke text behavior.
  - Added missing karaoke rotator and lineup markup in `templates/display.html`.
- Complete: attendee mobile optimization.
  - Replaced stacked mobile nav with compact disclosure navigation.
  - Shortened nav labels and hid the signed-in helper text on phone widths.
  - Added mobile-safe form sizing for signup, login, voting, and admin inputs.
  - Added one-column mobile layouts and safer list wrapping.
- Complete: admin mobile optimization.
  - Converted add-entry controls into collapsed disclosure rows.
  - Converted existing entry editors into collapsed per-entry disclosure rows.
  - Added touch-friendly admin action grids and safer narrow grid behavior.
- Complete: verification.
  - `python -m compileall main.py` passed.
  - `python -m pytest` passed with 12 tests.
  - Browser-verified no horizontal overflow for live display at 1366x768,
    1024x768, and 390x844.
  - Browser-verified mobile login, costume signup, and admin at 390x844.
  - Local verification used process-memory state because Redis authentication was
    unavailable in this environment.

## Follow-Up Notes

- The admin page still contains a lot of necessary controls, but the default
  mobile state now keeps add/edit forms collapsed so the host can scan sections
  quickly.
- If future work adds more admin controls, prefer extending the disclosure
  pattern rather than adding more always-open form panels.

## 2026 Lab-Terminal Redesign Verification

- Rechecked the redesigned UI at a 390x844 mobile viewport after the
  lab-terminal styling pass.
- Verified no horizontal overflow on public pages: `/rsvp`, `/party/login`,
  `/party/register`, `/party/password-reset`, and `/admin/login`.
- Verified no horizontal overflow on logged-in attendee pages: `/party`,
  `/party/menu`, `/party/costumes`, and `/party/karaoke`.
- Verified no horizontal overflow on admin/bartender/display pages: `/admin`,
  `/bartender`, and `/live-display`.
- Verified `/rsvp` remains standalone without the header menu.
- Verified non-RSVP mobile pages retain the compact `Menu` disclosure and that
  opening the menu does not create horizontal overflow.
- Verified admin add/edit disclosure rows remain collapsed by default on mobile.
- Corrected the redesigned mobile card group so phone-width panels retain the
  square lab-panel shape instead of reverting to rounded cards.
