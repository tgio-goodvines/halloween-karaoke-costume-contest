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

- Complete: attendee karaoke live status.
  - Added responsive personal status banners to `/party` and `/party/karaoke`.
  - Urgent Called/Up Next alerts stack cleanly on phones, stage badges wrap
    beneath long lineup labels, and polling updates do not disturb the signup
    form.
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

## YouTube Karaoke Responsive Verification (2026-07-30)

- Verified the dedicated `/admin/karaoke` workspace at desktop and `390x844`.
- Verified `/party/karaoke` search, fallback disclosure, selection form, and
  personal/public queue sections at `390x844`.
- Added compact vertical workflow steps on phones and a seven-marker compact
  attendee stepper.
- Corrected hidden pagination, empty-selection grid width, finder summary
  spacing, and mobile search-control stacking during browser QA.

## Party Games Responsive Verification (2026-08-05)

- Moved the game area directly below the party welcome panel and replaced the
  compact status callout with responsive, illustrated, game-specific cards.
- Added illustrated game-page heroes, one-column phone cards, reduced-motion
  behavior, and a unified five-card admin registry.
- Verified the party-day Games dashboard callout, opt-in prompt, statement
  form, confirmation state, and `/admin/games` workspace at `390x844`.
- Verified document width equals the viewport for attendee and admin game
  pages.
- Verified the live display at `390x844` and 1280px after adding its game
  participant metric and anonymous clue cards; no console errors or horizontal
  overflow were present.
- Expanded the same responsive Games shell with horizontally scrollable tabs,
  single-column phone ballot/response grids, disclosure-based prompt/MMF admin
  configuration, and touch-sized voting choices for four additional games.
- Desktop browser QA at 1280px confirmed the expanded admin and attendee pages
  match viewport width. Authenticated route-render tests cover active MMF,
  prompt submission, and prompt voting branches that are otherwise expensive
  to stage manually.

## 2026-07-26 Scrolling Performance Safeguards

- The shared attendee/admin pages use a distinct performance profile from the
  live display. They disable the fixed CRT overlays and backdrop blurs that
  force expensive repainting during scroll.
- Repeated cards use `content-visibility: auto` plus an intrinsic size so
  off-screen sections are skipped until approaching the viewport.
- On phone widths, repeated cards simplify to flat, bordered rows. This keeps
  long menus, RSVP lists, queues, and admin pages responsive.
- Keep rich animated/blurred effects scoped to `/live-display`; it is a
  presentation surface rather than a scrolling workspace.
- Do not remove the body-page class in `templates/base.html`: it activates the
  performance profile. Admin and bartender endpoints receive `admin-page`;
  all other shared-page endpoints receive `attendee-page` unless a template
  explicitly supplies `body_class`.

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

## Menu & Orders Consolidation Verification (2026-08-29)

- Consolidated Browse Menu and My Orders under `/party/menu` with a two-item
  server-rendered rail; the separate bartender/admin operational page and
  dropdown item remain unchanged.
- Added compact summary cards and a privacy-safe live bar panel with aggregate
  totals plus only the current account's order status/position.
- The rail becomes sticky and touch-safe on phones, summary cards collapse to
  one column at 390px, queue rows switch to one column, and menu/order cards
  retain the existing repeated-card performance safeguards.
- Browser-verified Browse Menu and My Orders at 1280×800 and 390×844. Document
  width matched viewport width, menu cards were one column on phone, no
  bartender forms/recipes/other-guest identity appeared, and live five-second
  polling produced no new console errors after the test server stabilized.
