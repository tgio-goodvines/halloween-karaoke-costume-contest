# Live Display Cast Quality And TV Legibility Plan

## Status

Implemented in the local workspace on October 11, 2026. Automated and local
browser verification is complete; final acceptance on the party laptop,
casting receiver, Wi-Fi, and TV remains an operational rollout check.

Implemented changes include semantic DJ update broadcasts, region-signature
DOM reconciliation, decoded non-blanking media swaps, cast-safe static effects,
longer rotation intervals, TV-size side-rail typography, a three-row bar queue,
mutually exclusive game footer content, and the October 16 follow-up that
removed background artwork entirely and enforced one focal content mode per
card.

## Objective

Make `/live-display` remain visually stable and readable when a browser tab is
cast to a television. The corrected display should:

- stop repainting unchanged cards and artwork during routine data refreshes;
- give a casting encoder long stable periods instead of near-continuous large
  scene changes;
- preserve sharp text while cards and images update;
- make the game and bar rails readable from normal party viewing distance;
- retain the fixed, no-scroll adaptive layout and all existing privacy and
  host-control behavior.

Browser casting is a compressed video stream, so the app cannot guarantee a
bitrate or eliminate network/device limitations. It can, however, stop
creating unnecessary full-frame motion and high-frequency detail that makes
the encoder spend most of its time recovering from a refresh.

## Current Findings

### 1. Unchanged state causes repeated full-region repaints

The MusicKit receiver posts a heartbeat every five seconds. Every accepted
heartbeat currently calls `broadcast_display_update()`, increments the display
version, and produces an SSE event. `static/display.js` treats every SSE event
as a reason to fetch the complete layout and call every region renderer.

The renderers do not reconcile the new payload with the visible DOM:

- center, game, and bar media handlers hide the current image wrapper;
- the same image `src` is assigned again;
- structured facts, steps, queue rows, history, and promotions are rebuilt;
- fit classes are cleared and measured again;
- a second independent 30-second poll repeats the same full render.

This means an unchanged game or bar card can briefly lose and restore its
background on every receiver heartbeat. It also makes a large fraction of the
cast frame change even when only playback position or receiver freshness
changed.

### 2. Independent rotations leave very little visual settling time

The center cards, game rail, and bar promotion/history each have independent
timers. Their defaults are approximately eight, ten, and eight seconds, while
DJ state refreshes every five seconds. Even after timer-deadline preservation,
these independent updates can make some large part of the screen change every
few seconds. Full-card background artwork magnifies each change into a large
video-encoding event.

### 3. The live-display surface contains encoder-hostile detail

The display combines a full-screen four-pixel scanline texture, multiple
gradients/glows, filtered full-card photographs, animated center transitions,
an animated progress bar, and a pulsing ready state. These treatments look
reasonable on a directly attached display but create fine detail and continuous
pixel changes that tab casting must repeatedly encode.

The bundled game and feature images are large enough for their current display
areas (most are 1200-1672 pixels wide). Converting files alone will not solve
the casting symptom; the decoded image and how often/how much of it repaints are
the primary concerns.

### 4. Side-rail typography is below TV-viewing size

When both rails are visible, their grid share is small. At common browser
source sizes a rail is often only about 270-380 pixels wide. Current clamps can
resolve labels and secondary copy to roughly 8-14 CSS pixels, with primary game
copy around 13-18 pixels. Bar queue metadata and utility labels are similarly
small.

The `large` density option currently increases center-stage title and copy
tokens but does not establish larger side-rail tokens. Overflow fitting can
then apply `is-dense` or `is-ultra-dense`, shrinking side copy further or
hiding useful context.

### 5. Each side card carries too many simultaneous information groups

The game rail can show status, title, supporting copy, focus content, metrics,
steps, an action, and a rotation footer at once. The bar rail can combine an
active queue, overflow count, completed history, summary facts, promotions,
ordering guidance, pickup guidance, and background art. Font enlargement alone
would overflow these fixed-height rails. Content must be prioritized and
time-sliced rather than uniformly compressed.

## Corrective Design

### Phase 1: Stop refresh-induced visual churn

1. Separate receiver liveness from visible display change.
   - Continue persisting `last_seen_at` and playback position on accepted DJ
     heartbeats.
   - Compare a small visual/command fingerprint before and after the report.
   - Broadcast an SSE display update only when song identity, playback status,
     authorization/readiness, artwork, queue identity, command status, or
     another display-visible field changes.
   - Do not broadcast solely for `last_seen_at`, report reason, or ordinary
     playback-position movement. The existing DJ client can update its local
     progress without forcing unrelated regions to render.

2. Give display payload regions stable revision keys or deterministic hashes.
   - Track `header`, `center`, `games`, `bar`, and `music` independently.
   - On a fetched layout, invoke only the renderers whose visible signature
     changed.
   - Keep the 30-second poll as recovery, but make identical results a true
     no-op.

3. Add keyed DOM reconciliation inside the changing region.
   - Preserve nodes for unchanged queue/history/fact entries.
   - Do not clear fitting classes, restart progress, or rebuild structured
     markup when an entry ID and its render signature are unchanged.
   - Keep current timer deadlines and rotation indices exactly as today.

4. Replace the three repeated media implementations with one stable media
   swap helper.
   - If the requested URL matches the current URL, do nothing.
   - For a new URL, preload and `decode()` it before swapping.
   - Keep the old image visible until the new image is ready; never blank a
     card during loading.
   - Ignore stale load completions when a newer URL has been requested.
   - On failure, retain the existing image or fall back cleanly without a
     hide/show flash.

Primary files: `main.py`, `static/display.js`, `static/dj-display.js`, and a
small dependency-free display reconciliation/media helper with Node tests.

### Phase 2: Establish a cast-safe rendering profile

Use cast-safe behavior as the live display default; it also benefits HDMI and
projector output and avoids another operational setting.

1. Remove the full-screen scanline overlay from `/live-display` and eliminate
   continuously moving decorative pixels.
2. Replace the pulsing ready-stage glow with a strong static border/background.
   Retain urgency through scale, contrast, wording, and color.
3. Remove the center card fade/translate transition. Swap completed content in
   one frame after media decode so text is never temporarily blurred by video
   compression.
4. Keep the progress indicator static or update only a small, bounded segment;
   it must not trigger layout or full-card paint.
5. Reduce large-area CSS `filter` work on background photographs. Prefer a
   stable dark overlay and pre-tuned opacity. Text stays on an opaque or nearly
   opaque veil and is never filtered.
6. Self-host the two display fonts (or use a deliberate local system stack) and
   preload them in `display.html`, preventing late remote-font swaps on the
   party network.
7. Stop using rotating menu promotion art as the entire bar background during
   an active queue. Use one stable bar background for queue mode; change to a
   drink image only for the explicit ready notice.
8. Increase default display durations to create a meaningful stable window.
   Start with 15 seconds for center cards and 20 seconds for games; rotate bar
   history/promotions no faster than 20 seconds. Prefer one coordinated scene
   boundary over three unrelated large-area changes.

Primary files: `static/display.css`, `static/display.js`, `templates/display.html`,
font assets under `static/`, and the display timing defaults/admin copy in
`main.py` and `templates/admin.html`.

### Phase 3: Redesign the game rail for across-room reading

The game rail should present one decision or instruction at a time.

1. Introduce explicit TV type tokens for side rails rather than deriving all
   text from narrow container width.
   - At 1920x1080: rail title at least 30 px, primary/focus copy at least 24 px,
     secondary/action copy at least 20 px, and labels at least 16 px.
   - At 1280x720: rail title at least 24 px, primary copy at least 20 px,
     secondary/action copy at least 17 px, and labels at least 14 px.
   - `large` density must affect side rails as well as center stage.

2. Increase the minimum rail share at TV aspect ratios. Favor readable side
   stages over a very wide center card when both are visible.
3. Limit each game view to four visual groups:
   - compact phase/status;
   - game title;
   - one large current focus;
   - one footer group containing either two metrics, up to two short steps, or
     one action—not all three.
4. Split overflow-worthy material into additional timed entries. For example,
   a live-status entry can be followed by one instruction entry or one prompt
   response entry rather than stacking both.
5. Give fields an explicit priority. Fitting removes optional footer content
   before reducing type. Required title/focus copy never falls below the TV
   floor; if it still does not fit, clamp or paginate the content.
6. Remove low-value stage labels such as “Left stage” and verbose URL strings.
   Use a short action such as “Play on your phone” plus the memorable site
   host only where needed.

Primary files: `main.py` (`build_game_stage_entries()`),
`templates/display.html`, `static/display.js`, and `static/display.css`.

### Phase 4: Redesign the bar rail for across-room reading

Treat queue, history, menu promotion, and ready notice as distinct rail scenes
instead of one composite card.

1. Active queue scene:
   - show the heading and at most three large queue rows;
   - each row shows queue number/name, drink, and one short state;
   - show `+N waiting` for the remainder;
   - do not show completed history, summary tiles, promotions, and two action
     paragraphs at the same time.
2. Idle/history scene:
   - show up to three recently completed drinks with large names and pickup
     state;
   - alternate this scene with a single menu promotion when both exist.
3. Ready scene:
   - keep it full-height and dominant;
   - make the guest name and “drink ready” message the largest rail text;
   - retain no more than one supporting detail and one pickup instruction.
4. Use the same TV type floors as the game rail. Queue row names should be at
   least 22 px at 1080p/18 px at 720p; drink/status text should be at least
   18 px at 1080p/16 px at 720p.
5. Replace dynamic background promotion images in queue mode with stable art,
   allowing only the small text scene to change.

Primary files: `main.py` (`build_bar_stage()`), `templates/display.html`,
`static/display.js`, and `static/display.css`.

### Phase 5: Make fitting enforce priorities, not tiny text

1. Replace the current generic sparse/dense/ultra-dense response with
   region-specific fit policies.
2. Measure after fonts and the newly requested image have completed.
3. Apply this order when a side rail overflows:
   - remove optional decorative/tertiary content;
   - reduce row count;
   - clamp long copy or move it to a subsequent scene;
   - reduce gaps/padding within defined bounds;
   - never reduce required copy below the TV font floor.
4. Record a development-only diagnostic when required content still overflows,
   including viewport, region, entry ID, and measured dimensions.
5. Preserve `100dvh`, zero document scrolling, and adaptive region collapse.

## Verification Plan

### Automated regression coverage

Add dependency-free JavaScript tests for:

- identical payloads causing zero region renders and zero media `src` writes;
- a music-only change not rendering center, games, or bar;
- unchanged media remaining visible through heartbeat and fallback polls;
- new media swapping only after decode and stale loads being ignored;
- timers/deadlines surviving unrelated payload updates;
- side-rail content-budget selection and priority fallback;
- ready notices still preempting only the right rail;
- current privacy exclusions for games and drink orders.

Add Python tests for:

- ordinary DJ heartbeats persisting receiver freshness without incrementing the
  live-display version;
- visible receiver/song/command changes still broadcasting immediately;
- game and bar builders enforcing row/group limits;
- unchanged display API contracts and authorization.

### Browser layout matrix

Verify populated game + center + bar + DJ states at:

- 1920x1080;
- 1366x768;
- 1280x720;
- 1024x768 as the compact fallback.

For each viewport confirm:

- no document or region overflow;
- type floors from this plan are met in computed styles;
- no required text is hidden by dense classes;
- ready, queue, idle/history, signup, active, prompt/vote, and result scenes all
  fit;
- failed artwork leaves a clean, readable card;
- the browser console has no errors or layout-loop warnings.

### Cast-device acceptance test

Use the actual party laptop/browser, Wi-Fi, cast receiver, and TV. Compare the
same fixture through direct laptop rendering and browser-tab casting.

Run a ten-minute scripted sequence with:

1. two minutes of unchanged state with DJ heartbeats active;
2. center-card rotation;
3. game rotation and a phase/countdown update;
4. an active bar queue update;
5. one drink-ready notice with artwork;
6. a confirmed DJ song/artwork change.

Acceptance criteria:

- unchanged periods show no card flash, image blanking, or decorative motion;
- after a deliberate scene change, text is sharp on the next stable frame and
  does not remain macroblocked;
- no unrelated region visibly refreshes;
- game and bar primary text is readable from the intended party viewing
  position;
- every deliberate state change appears within the existing realtime
  expectation;
- direct display and cast display preserve the same content hierarchy.

Also record cast source resolution, browser zoom (100%), TV picture/overscan
mode, receiver model, and whether the browser is casting a tab or the whole
desktop. These are operational evidence, not substitutes for the app fixes.

## Recommended Implementation Order

1. Build deterministic fixtures and capture the current cast baseline.
2. Stop heartbeat broadcasts for non-visual DJ changes.
3. Add region signatures and no-op identical layouts.
4. Implement decoded, non-blanking media swaps.
5. Apply the cast-safe CSS profile and stable rotation cadence.
6. Redesign the game rail around one focus plus one footer group.
7. Split the bar rail into queue, history/promotion, and ready scenes.
8. Replace generic compaction with type-floor-aware priority fitting.
9. Complete automated, viewport, and real cast-device verification.
10. Update `LIVE_DISPLAY_ADAPTIVE_LAYOUT_PROGRESS.md`, `ARCHITECTURE.md`,
    `FEATURES.md`, and this file with the verified implementation and rollout
    result.

## Non-Goals And Guardrails

- Do not remove SSE or the 30-second recovery poll.
- Do not weaken admin authentication for display routes.
- Do not expose recipes, email addresses, account IDs, private ballots, game
  identities, or scavenger evidence on the TV payload.
- Do not make ready notices replace center-stage costume, karaoke, or game
  overrides.
- Do not add scrolling to the live display.
- Do not solve overflow by returning to sub-TV-size typography.
- Do not treat image recompression alone as the pixelation fix.
- Do not change GoodVines services, source, or nginx configuration.

## Completion Gate

The work is complete only when unchanged receiver heartbeats produce no visible
non-music repaint, the game and bar rails meet the documented type floors at
1080p and 720p, all fixed-viewport browser fixtures pass, and the real cast
sequence is judged stable and readable from the intended party viewing
position.
