# Adaptive Live Display Implementation Progress

## Status

Implemented, verified, and deployed on August 10, 2026 (August 11 UTC). The
live display now uses a single fixed viewport with no page scrolling and a
focused `/admin/display` control room.

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

Schema version `10` extends `display_config` with per-card visibility for
generated game winner/outcome and final-score cards. These cards use stable IDs,
remain available after attendee game disablement, and have explicit Show Now
and Include/Hide controls in `/admin/display`.

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
- Implementation commit: `f783aa69f6039d5ee1d74a193bba0f26004860c1`
- GitHub Actions deployment run `31450359365` completed successfully.
- `https://tnq-halloween.com/health` and the `www` hostname returned
  `status="ok"` with Redis DB 1 available.
- `https://appg-v.com/health` remained online after deployment.
- Production served the new adaptive `static/display.js` markers.
- Anonymous requests to `/live-display` and `/admin/display` returned the
  expected `302` redirect to `/admin/login`.

## Rotation Follow-up

On August 10, 2026, a production follow-up found that DJ receiver heartbeats
could refresh the layout more frequently than the configured center/game
intervals. Each refresh cleared and restarted both client timers, so displays
with an active receiver could appear permanently stuck on one card and game.

`static/display.js` now binds each timer to its current entry and preserves the
deadline across SSE/poll refreshes. Pause, pin, spotlight, hidden-region, and
entry-change states still cancel or replace the relevant timer immediately.
Browser verification with five-second receiver heartbeats confirmed that a
four-second center rotation advanced through four cards while a five-second
game rotation cycled all three enabled games over fourteen seconds.

The custom-card library now exposes an explicit `Edit Card` affordance on every
saved card. Opening it reveals all text, media, CTA, duration, schedule, and
visibility fields plus a clearly labeled `Save Card Changes` action. A browser
save test confirmed the updated headline persisted and appeared back in the
library.

## Space Utilization And Informational Density (2026-08-14)

The three-stage display now uses the interior of visible cards more
productively instead of treating adaptive layout as column collapse alone.

- Center entries support optional `kind`, `facts`, `steps`, and `action`
  structures while preserving the original primary/secondary/tertiary payload
  fields. System action cards show live participation facts, three-step phone
  instructions, and direct party routes. Winner cards include a compact top
  three preview when final scores exist.
- The left game stage shows phase-specific instructions and a persistent phone
  action. Prompt-response cards use the prompt as context, the current
  anonymous response as the secondary message, and a complete read/vote flow
  instead of duplicating the response in an extra row.
- The right bar stage now includes queue positions, mixing/waiting counts,
  recent average prep time, available-drink count, a featured available drink,
  an order route, and pickup guidance. Drink-ready notices retain queue status
  and can show the safe notice detail lines already present in the payload.
- `static/display.js` classifies visible panels as sparse, dense, or
  ultra-dense by measuring their rendered fit content. Sparse center/side cards
  receive a larger presentation treatment; dense cards progressively compact
  and hide optional modules. Overflow checks use both panel and inner-content
  measurements so clipped grid children are still detected.
- `static/display.css` uses container-relative sizing inside the center and
  side stages. Type and spacing therefore respond to the width actually
  assigned to a card, not only the browser viewport.

No new persisted state or schema migration is required. All added display data
is derived from existing contest, karaoke, game, menu, and drink-order state.
The bar payload remains privacy-safe: email, account IDs, recipes, and other
private operational fields are not exposed.

Verification covers the enriched payload/markup and populated three-stage
browser layouts at 1920x1080, 1366x768, 1280x720, and 1024x768. At every size,
the document matched the viewport and every visible region remained within its
fixed no-scroll track.

## Generated Status And Feature Artwork (2026-08-24)

- Every game-stage status record now carries its original game illustration.
  Ended records with a positive winner switch to a dedicated completed-game
  trophy variant. Winner/outcome center cards and winner presentation slides use
  the same dedicated art; neutral final-score cards retain original game art.
- The bar rail has a generated bar fallback and switches to a featured drink or
  ready-order item image when available.
- Karaoke center cards use generated karaoke art. The DJ footer initializes
  with generated jukebox art and replaces it with confirmed album artwork when
  available.
- Images remain optional at render time: client error handlers remove failed
  media without hiding the underlying live status or results.

## Full-Card Live Artwork Treatment (2026-08-28)

- Game illustrations are atmospheric full-card backgrounds on the live display,
  not bordered thumbnails. This covers the left game-status rail, Party Games
  join card, winner/outcome and final-score cards, host Show Now overrides, and
  previous/next result-presentation slides.
- Image-bearing center cards now default to full-card background treatment.
  Explicit payload markers document the intended treatment for game, karaoke,
  menu/bar, and custom-announcement cards, while `media_tone` selects bounded
  feature, video, custom, or game contrast profiles. Only a deliberate
  `media_treatment: "foreground"` opt-in can restore a split image treatment.
- Karaoke signup, queued-performer, Up Next, Now Singing, completion, and kickoff
  countdown cards all use full backgrounds. YouTube thumbnails receive a darker
  video veil; manual entries fall back to the generated karaoke illustration.
- The right bar rail uses its featured drink or generated bar illustration as
  an edge-to-edge panel background. Drink-ready notices reuse that layer with
  the ordered drink image when available and a stronger centered text veil.
- Image-bearing custom announcements default to the same full-card treatment,
  preventing newly created display cards from silently returning to thumbnails.
- Confirmed DJ album art remains a foreground square because the music footer is
  a status dock and the cover identifies the active track; it is not a card.
- Edge-to-edge cover images use restrained opacity, desaturation, and layered
  black/red gradients. Text and result modules render above the artwork;
  winner/spotlight art receives a modest visibility lift.
- Background art is decorative (`alt=""`/`aria-hidden`) and failed loads fall
  back to the standard dark neon panel without an empty media region.
- Background media consumes no measured layout height and remains available in
  dense, ultra-dense, and narrow layouts. Bar and drink-ready artwork is no
  longer removed by density or narrow-screen thumbnail suppression rules.
- Verification passed with 194 Python tests plus 21 subtests, 17 dependency-free
  JavaScript tests, Python/JavaScript syntax checks, deploy-script validation,
  and local browser inspection of karaoke and bar background cards at the
  standard 1440x900 live-display viewport. The document remained no-scroll and
  browser console inspection reported no errors.

## Left-Stage Vertical Composition (2026-08-29)

- The independently rotating game rail now uses its full available height as a
  three-zone composition: game identity and phase at the top, the current live
  focus in a flexible middle region, and metrics/instructions/phone action
  anchored above the rotation footer.
- Game-stage payloads carry a derived `presentation` type plus `focus_label`,
  `focus_items`, and `feature_text` fields. Signup, active play, mystery clues,
  prompts, blind responses, reveals, and final results can therefore share one
  renderer without repeating the same content in several modules.
- Two Truths clue statements render as a dedicated focus list instead of being
  duplicated as primary copy and instructions. Prompt-game response cards keep
  the prompt as context and place the blind response in its own highlighted
  focus surface. Ended prompt games no longer rotate stale round responses.
- The top and bottom zones use restrained dark veils over the existing
  full-card artwork. Required live focus, metrics, and action content retain
  priority while dense and ultra-dense classes compact optional instructions.
- These changes are isolated to `build_game_stage_entries()` and the left-stage
  markup, renderer, and styles. Center rotation, bar rail, and DJ footer
  behavior are unchanged, and no persisted state or schema migration is
  required.
- Focused verification passed for left-stage payload structure, privacy,
  enriched display markup, Python compilation, JavaScript syntax, and all 17
  dependency-free JavaScript tests. Browser QA at 1440x900, 1280x720, and
  1024x768 confirmed top/bottom anchoring, zero rail/document overflow, and no
  browser warnings or errors. The full Python run reached 191 passing tests and
  21 passing subtests; four unrelated drink-history/navigation assertions were
  temporarily failing against concurrent bar/menu consolidation work.

## Dynamic Bar Stage And Pickup Retention (2026-08-29)

- The right stage now derives a `notice`, `queue`, or `idle` presentation. An
  active queue keeps the existing queue-first organization and rotates one
  available food/drink promotion in the bottom zone.
- With no active queue, retained completed orders occupy the middle while menu
  promotions rotate above and below them. Menu-only state uses all three
  vertical zones; history-only state stays visible; the rail collapses only
  when notice, queue, completed history, and available menu are all empty.
- Promotion input contains every available food and drink item, including
  view-only/non-orderable drinks. Unavailable items are excluded. Rotation uses
  a stable key so five-second SSE refreshes do not restart the interval.
- Drink-ready notices fill the complete right stage for their temporary
  duration with a vivid neon-red background and assertive alert semantics.
  Queued notices remain FIFO and do not interrupt the center/event stage.
- Schema 19 adds an optional `picked_up_at` timestamp. Attendees can acknowledge
  pickup from the dashboard, My Orders, or privacy-safe live status. The ready
  emphasis ends after acknowledgement (or the existing five-minute window),
  while completed order history remains intact for the night.
- Local browser QA at 1440x900 and 1280x720 verified the notice,
  queue-independent rotation, history-plus-menu, menu-only, and fixed no-scroll
  compositions. The full neon treatment was tuned against computed browser
  styles; reduced-motion mode disables its pulse.
- Final verification passed with 215 Python tests plus 21 subtests, all 17
  dependency-free JavaScript tests, Python/JavaScript syntax checks, and
  whitespace validation.

## Queue-Visible Completed History (2026-08-29)

- Completed Tonight is no longer suppressed by an active queue. It renders
  immediately after queue/overflow content with two rows in queue mode and
  three rows in idle mode.
- History rotation now runs whenever completed records exceed the current
  capacity. With both queue and history present, promotional cards, action text,
  and summary facts yield first to keep the fixed rail no-scroll.
- Browser verification at 1280×720 showed two active and two completed drinks in
  the right stage with zero document overflow.
