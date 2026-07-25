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

## Design Notes

- The Flask/Redis app owns the canonical jukebox state and queue order. MusicKit is treated as the playback surface, not the source of truth.
- Attendee accounts do not authenticate with Apple Music and must never receive
  the MusicKit token endpoint. The host/admin authorizes Apple Music on the
  live-display browser, and attendees use that playback session indirectly by
  submitting app-owned requests.
- Browser audio autoplay still requires a user gesture; the live display should expose explicit Connect/Start controls.
- Chromecast audio should work when casting the Chrome tab containing `/live-display`; casting a full screen can keep audio on the computer on some platforms.
- YouTube remains unsuitable for audio-only playback because YouTube API policies do not allow separating or hiding the video/audio components.
- Apple Music catalog search and MusicKit playback require
  `HALLOWEEN_APPLE_MUSIC_DEVELOPER_TOKEN`; this app expects a pre-generated
  MusicKit developer token from environment/Vault rather than generating ES256
  JWTs locally.
- `HALLOWEEN_APPLE_MUSIC_STOREFRONT` defaults to `us`.
- In production, add `apple_music_developer_token` and optionally
  `apple_music_storefront` to the existing Halloween app Vault secret path.
