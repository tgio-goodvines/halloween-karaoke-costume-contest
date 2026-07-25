# Jukebox Apple Music Feature

## Goal

Add a party jukebox backed by Apple Music/MusicKit on the live display:

- Admin can enable jukebox mode, configure request rules, create a base playlist, and moderate requests.
- Attendees can request songs from the party portal on the party date.
- Approved attendee requests are queued and randomly inserted into the upcoming playlist instead of simply appended.
- The live display can act as the Apple Music playback surface while preserving rotating party cards.
- If the app queue runs dry, hosts can use Apple Music Autoplay from a seed track/playlist as the fallback behavior.

## Implementation Progress

- 2026-07-25: Created this durable tracker before implementation.
- 2026-07-25: Implemented Redis-backed jukebox settings, playlist, requests,
  app-owned queue, now-playing state, queue regeneration, attendee request
  limits, explicit filtering, duplicate cooldown checks, and random insertion
  of approved requests.
- 2026-07-25: Added `/party/jukebox`, `/api/jukebox-search`,
  `/api/jukebox-state`, `/api/apple-music-token`, and
  `/api/jukebox/playback-event`.
- 2026-07-25: Added admin controls for enabling jukebox mode, request rules,
  Apple Music playlist search/add/remove/reorder, request
  approve/reject/skip, queue regeneration, and queue clearing.
- 2026-07-25: Added live-display Apple Music split mode with album art,
  host-only Connect/Start/Skip controls, queue rail, MusicKit loading, and
  playback-event sync back to Flask.
- 2026-07-25: Added focused tests and verification. Passed:
  `python -m unittest tests.test_redis_state`, `python -m py_compile main.py`,
  bundled Node `--check` for `static/display.js`,
  `static/jukebox-search.js`, and `static/jukebox-player.js`, plus route smoke
  rendering for `/admin`, `/live-display`, `/api/display-data`, and
  `/party/jukebox`.
- 2026-07-25: Added production start-wrapper exports for optional Vault fields
  `apple_music_developer_token` and `apple_music_storefront`.
- 2026-07-25: Clarified and tested the authorization boundary: attendees can
  search/request Apple Music tracks through the Halloween app, but only the
  admin/live-display browser can fetch the MusicKit token and authorize the
  host Apple Music playback session.
- 2026-07-25: Reorganized the live display around explicit idle/dashboard
  modes. When jukebox is enabled, Apple Music playback now lives in a dedicated
  left rail with now-playing and capped queue details, while the center keeps
  rotating party cards and the right rail rotates drink/costume/karaoke
  activity. Idle mode preserves the single large rotating card and scales short
  cards up with spotlight/mega sizing.
- 2026-07-25: Merged the left rail's now-playing and up-next areas into one
  unified jukebox display card so album/song/request/queue information does not
  cut each other off. `/live-display` hides persistent Apple Music host controls
  and status copy from attendees; paired displays show only the temporary
  MusicKit authorization modal when admin requests it. Live display CSS now
  locks the page to the viewport with no document scrolling.
- 2026-07-25: Added client-side jukebox card fitting in
  `static/jukebox-player.js`. After each render, the card measures its own
  scroll/client dimensions and progressively applies compact, micro, no-art,
  fewer-queue-row, and minimal modes so long song/artist/request content fits
  the assigned viewport region without clipping.
- 2026-07-25: Added admin-console DJ controls for Apple Music playback. Admin
  can send Connect, Play, Pause, Stop, and Skip commands from `/admin`; the
  admin-authorized live display polls the app-owned command state, executes the
  command through MusicKit, and acknowledges success/error through the existing
  playback event endpoint. Normal attendee-visible `/live-display` remains
  display-only with no Apple Music buttons.
- 2026-07-25: Local real-song testing with Apple Music credentials confirmed
  catalog search and app queueing work with real songs such as "Thriller".
  Playback commands reached the live display, but MusicKit calls could stall
  without a same-tab display gesture or when the browser/CDN context failed to
  expose MusicKit. Added cache-busted display scripts, a no-button click/key
  gesture arm path on the live display, MusicKit load detection, and timeouts
  around authorize/setQueue/play so admin sees an explicit error instead of a
  silent pending command.
- 2026-07-25: Tightened MusicKit authorization state after field testing.
  MusicKit being configured is not the same as Apple Music being authorized:
  `music.isAuthorized` must be true before admin Connect/Play can proceed.
  The live display now keeps showing the in-app host sign-in prompt until real
  authorization completes, and its message clarifies that Apple verification
  codes received on a phone must be entered in the Apple sign-in window on the
  display browser.
- 2026-07-25: Made admin DJ commands feel realtime on the live display.
  `static/display.js` now emits a browser event whenever the display SSE stream
  receives an update, and `static/jukebox-player.js` refreshes jukebox command
  state immediately from that event instead of waiting only for its 3-second
  fallback poll. MusicKit authorization must happen in the live-display tab
  that will play audio; admin only sends DJ commands into that tab.
- 2026-07-25: Added targeted admin Play Now controls for individual upcoming
  queue songs. Play commands can carry a `queue_item_id`, and the live display
  MusicKit controller sets Apple Music to that specific song instead of loading
  the full upcoming list. Approved requests still regenerate into the app-owned
  queue automatically; the admin Requests list identifies queued request
  position while rejected requests remain visible as request history. The live
  display jukebox card now shows only the active now-playing song, not upcoming
  queue rows.
- 2026-07-25: Removed persistent Connect/Start/Skip transport buttons from the
  live display. Admin is the only control surface for Connect, Play, Pause,
  Stop, Skip, and Play Now; the display may still show the Apple authorization
  prompt when MusicKit requires a gesture in the playback tab.
- 2026-07-25: Apple Music song search now paginates beyond the first 8 results.
  `/api/jukebox-search` accepts `limit` and `offset`, returns `has_more` and
  `next_offset`, and `static/jukebox-search.js` appends more result pages from
  a More Results button.
- 2026-07-25: Clarified and hardened the Apple Music DJ authorization UX after
  field testing showed the old admin sign-in flow could create a split
  MusicKit state between `/admin` and `/live-display`. The Jukebox tab now
  renders DJ Controls at the top. The live display owns MusicKit authorization
  and playback. `static/jukebox-player.js` now checks existing display
  authorization before showing the modal, displays progress while Apple sign-in
  opens, times out visibly, and posts `sync` or `command_error` back to admin.
- 2026-07-25: Implemented the final paired-display Apple Music workflow. Admin
  `Pair & Authorize Display` creates a short-lived, single-use display token,
  opens a playback-only `/live-display` session, and issues the display
  `connect` command; paired displays can fetch
  `/api/jukebox-state`, `/api/apple-music-token`, and post
  `/api/jukebox/playback-event` without receiving admin portal access. The
  admin Jukebox tab documents the procedure in-app: pair display, authorize
  Apple Music on the live display browser, add songs to the active playlist,
  approve requests into that playlist, then use DJ controls. The old visible
  Regenerate/Clear queue controls were replaced by `Reset Playlist` and
  `Restart Playlist`. The active playlist is the canonical running music queue
  source; adding/removing/reordering playlist songs regenerates the queue in
  realtime, approved requests are inserted into it, Reset rebuilds the queue
  without deleting playlist songs, and Restart resets playback state and sends
  a `restart_playlist` command to the paired display.
- 2026-07-25: Corrected paired-display UX so Pair & Authorize Display now both
  creates the playback-only display token and immediately issues a pending
  `connect` command. The newly opened paired display tab should render the
  Apple Music authorization modal without requiring the host to return to admin
  and press Connect separately.
- 2026-07-25: Fixed the paired-display authorization prompt disappearing after
  a split-second. The live display may probe MusicKit on load, but it no longer
  acknowledges or hides the `connect` authorization prompt from a background
  check. If MusicKit reports an existing authorization, the prompt stays open
  with a Confirm Connection button so the host keeps a visible same-tab action.
  Probe failures also leave the prompt open and retryable instead of turning the
  command into an immediate admin error.
- 2026-07-25: Fixed DJ commands not updating reliably after display
  authorization. Admin DJ controls now post to `/api/jukebox/dj-command` for
  immediate JSON feedback and then refresh the admin panel, while the normal
  `/admin` form path remains as a fallback. Both DJ command issuance and
  display playback acknowledgments are registered as Redis state mutations so
  pending/acknowledged/error command state persists consistently in production.
  The live display no longer posts `started` before MusicKit reports playback;
  it waits for `isPlaying` and reports a visible command error if Apple Music
  accepts the queue but does not actually start audio.

## Design Notes

- The Flask/Redis app owns the canonical jukebox state and queue order. MusicKit is treated as the playback surface, not the source of truth.
- The active playlist is the party's running music queue source. Admin-managed
  playlist songs plus approved requests generate the app-owned queue that the
  live-display MusicKit instance plays from.
- Admin Play Now queue commands intentionally bypass the upcoming list in
  MusicKit so hosts can jump to a specific approved request or playlist item.
- Keep admin as the only persistent DJ transport surface. Avoid reintroducing
  always-visible playback buttons on `/live-display`; use admin commands plus
  the display-tab authorization prompt when MusicKit/browser policy requires it.
- Attendee accounts do not authenticate with Apple Music and must never receive
  the MusicKit token endpoint. Only an admin session or a paired display
  session can fetch the MusicKit developer token. Attendees use playback
  indirectly by submitting app-owned requests for host approval.
- Browser audio autoplay still requires a user gesture in the playback tab.
  The host should press `Pair & Authorize Display` from `/admin`, use the new
  paired display tab on the TV/cast browser, then complete the Apple Music
  prompt on the live display itself. After that, admin DJ controls can play,
  pause, skip, reset, and restart the active playlist.
- Chromecast audio should work when casting the Chrome tab containing `/live-display`; casting a full screen can keep audio on the computer on some platforms.
- YouTube remains unsuitable for audio-only playback because YouTube API policies do not allow separating or hiding the video/audio components.
- Apple Music catalog search and MusicKit playback require
  `HALLOWEEN_APPLE_MUSIC_DEVELOPER_TOKEN`; this app expects a pre-generated
  MusicKit developer token from environment/Vault rather than generating ES256
  JWTs locally.
- `HALLOWEEN_APPLE_MUSIC_STOREFRONT` defaults to `us`.
- In production, add `apple_music_developer_token` and optionally
  `apple_music_storefront` to the existing Halloween app Vault secret path.
