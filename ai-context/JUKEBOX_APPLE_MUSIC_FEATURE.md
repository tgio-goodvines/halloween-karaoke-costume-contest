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
  cut each other off. Normal `/live-display` hides Apple Music host controls and
  status copy from attendees; `/live-display?host_controls=1` keeps a setup view
  for host authorization/start/skip. Live display CSS now locks the page to the
  viewport with no document scrolling.
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

## Design Notes

- The Flask/Redis app owns the canonical jukebox state and queue order. MusicKit is treated as the playback surface, not the source of truth.
- Attendee accounts do not authenticate with Apple Music and must never receive
  the MusicKit token endpoint. The host/admin authorizes Apple Music on the
  live-display browser, and attendees use that playback session indirectly by
  submitting app-owned requests.
- Browser audio autoplay still requires a user gesture; the host should open
  the admin-authorized live display once so MusicKit can authorize the Apple
  Music subscriber session, then use `/admin` DJ controls during the party.
- Chromecast audio should work when casting the Chrome tab containing `/live-display`; casting a full screen can keep audio on the computer on some platforms.
- YouTube remains unsuitable for audio-only playback because YouTube API policies do not allow separating or hiding the video/audio components.
- Apple Music catalog search and MusicKit playback require
  `HALLOWEEN_APPLE_MUSIC_DEVELOPER_TOKEN`; this app expects a pre-generated
  MusicKit developer token from environment/Vault rather than generating ES256
  JWTs locally.
- `HALLOWEEN_APPLE_MUSIC_STOREFRONT` defaults to `us`.
- In production, add `apple_music_developer_token` and optionally
  `apple_music_storefront` to the existing Halloween app Vault secret path.
