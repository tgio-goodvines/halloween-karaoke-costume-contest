# Adaptive Live Display Implementation Progress

## Status

Implemented and verified locally on August 10, 2026. The live display now uses
a single fixed viewport with no page scrolling and a focused `/admin/display`
control room. Production deployment status should be updated in the release
section after the GitHub Actions run completes.

## TV Layout

- Header: existing event title remains centered at the top with compact costume,
  karaoke, and enabled-game counts.
- Left stage: independently rotates data for every enabled game. Active games
  sort ahead of ended/signup games; an admin may pin one game.
- Center stage: remains the visual focus and rotates source-grouped system and
  custom cards. It supports images, CTAs, WiFi details, scoreboards, karaoke
  countdown/lineup data, event spotlights, host pause/previous/next, and pins.
- Right stage: shows privacy-safe received/in-progress drink orders only while
  orders exist. A temporary pickup notice replaces the queue presentation when
  a drink completes; additional notices wait in FIFO order.
- Footer: shows receiver-confirmed jukebox Now Playing, progress, status, and Up
  Next. It retains the MusicKit receiver controls expected by `dj-display.js`.
- Adaptive behavior: absent left, right, or footer regions are removed from the
  grid and center stage expands into the reclaimed width/height. All regions
  are clipped/fitted inside `100dvh`; the document never scrolls.

## Admin Control Room

`/admin/display` now provides:

- live center/left/right/footer status;
- previous, pause, resume, and next center-card controls;
- a selector to spotlight any currently available center card;
- automatic/always/hidden modes for game, bar, and music regions;
- center and game intervals, queue size, ready-alert duration, and density;
- enable/disable and ordering controls for portal, custom, costume, karaoke,
  game, bar, and update center sources;
- game pin/resume controls and ready-alert dismissal;
- custom-card create/edit/delete/reorder/show-now controls with optional image,
  CTA link/label, duration, enabled flag, and start/end schedule.

## State And Payload

Redis schema version `9` adds:

- `display_config` for source order/visibility, intervals, region modes, pinned
  game, queue size, alert duration, and density;
- `display_runtime` for center index, pause/pin state, and revision;
- `display_custom_cards` for ordered scheduled cards;
- `live_display_notice_queue` for sequential ready alerts.

`build_display_layout()` supplies `header`, `center`, `games`, `bar`, `music`,
and `density`. `/api/display-data` keeps legacy top-level fields for existing
consumers. SSE continues to trigger immediate full-layout refreshes and the
30-second poll remains as fallback.

## Privacy And Resilience

- Costume contact information and drink-order email/user identifiers are not
  included in the TV payload.
- URLs are normalized through the existing safe image/link helpers.
- Missing/expired pinned cards fall back to the normal center index.
- Multiple drink-ready events queue instead of replacing one another.
- Client renderers write external state with `textContent`; structured markup is
  created locally.

## Verification

- `python -m py_compile main.py`
- bundled Node syntax checks for `static/display.js` and `static/dj-display.js`
- `python -m pytest -q`: 139 tests and 11 subtests passed
- `git diff --check`
- populated browser QA at 1920×1080, 1366×768, 1280×720, and 1024×768:
  document width/height exactly matched viewport, body overflow was hidden, and
  every visible region fit its assigned track
- adaptive collapse at 1280×720: hiding games, bar, and music expanded center
  to 1266×656 with no scrolling
- `/admin/display` QA at 1366×768 and 390×844: no horizontal document overflow;
  all 110 form controls remained in the document and mobile intrinsic-width
  clipping was corrected
- bartender completion produced a visible right-stage pickup alert while center,
  games, title, and music remained visible
- browser console produced no warnings or errors

## Release

- Branch: `codex/adaptive-live-display`
- Commit: pending
- GitHub Actions deployment: pending
- Production health and authenticated-route checks: pending
