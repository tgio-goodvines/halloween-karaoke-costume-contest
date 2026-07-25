# Karaoke YouTube Stage Progress

## Goal

Implement a complete karaoke YouTube workflow:

- Attendees can search YouTube while signing up and choose a result that fills
  the song submission fields.
- Karaoke signups persist YouTube video metadata and embeddable/playability
  status.
- Admin can see video readiness, stage any singer, start playable videos, open
  YouTube from the live-display stage card, advance to the next singer, and
  stop/restore karaoke display mode.
- Live display always supports a karaoke stage card and can switch to maximized
  embedded video while keeping the party title visible.

## Progress

- 2026-07-25: Created this tracker before implementation.
- 2026-07-25: Implemented backend YouTube URL parsing, search result
  formatting, video verification, signup metadata persistence, admin karaoke
  stage/video/next controls, attendee search-and-fill UI, live-display
  karaoke stage mode, maximized YouTube iframe mode, and stage-card Open
  YouTube action.
- 2026-07-25: Added `.env.example` entry for `HALLOWEEN_YOUTUBE_API_KEY`
  and optional Vault startup export from `deploy/start_halloween.sh` field
  `youtube_api_key`.
- 2026-07-25: Added focused tests for common YouTube URL parsing, selected
  YouTube metadata persistence, mocked search results, admin stage/play/next
  flow, and blocking unverified video playback.
- 2026-07-25: Verification passed: `python -m unittest
  tests.test_redis_state`, `python -m py_compile main.py`, bundled Node
  `--check` for `static/karaoke-search.js` and `static/display.js`.
- 2026-07-25: Added admin YouTube API key setup controls. Admin can open the
  Google API Credentials console, paste a YouTube Data API v3 key, validate it
  through a server-side YouTube API call, enable it as a runtime override, and
  clear that override back to the deployed environment/Vault key.
- 2026-07-25: Enhanced attendee YouTube search results with visible thumbnails,
  duration badges, explicit `Preview` controls, inline embedded previews, and
  separate `Use this song` selection controls.

## Implementation Notes

- Keep the existing `youtube_link` field backward-compatible for old Redis
  state and tests.
- Do not expose the YouTube API key to browser JavaScript. Browser UI calls a
  Flask JSON endpoint; Flask calls YouTube when
  `HALLOWEEN_YOUTUBE_API_KEY` is configured.
- The live-display `Open YouTube` action belongs on the stage card so a host can
  open a dedicated YouTube tab from the cast/display browser without exposing
  the admin console.
- Embeddable status is a readiness signal, not a perfect playback guarantee;
  live display must gracefully fall back to the stage card if playback is
  blocked or fails.

## Completed Behavior

- Attendee `/party/karaoke` now has a YouTube search panel. Selecting a result
  fills visible song/title fields plus hidden YouTube video metadata before
  normal form submission. Results show thumbnails and can expand an inline
  embedded preview before selection.
- `GET /api/youtube-search` is available to signed-in regular users on party
  day and admins. It requires `HALLOWEEN_YOUTUBE_API_KEY`; without it, the
  endpoint returns a JSON configuration error and manual signup still works.
- Admin `/admin` Public Access controls include YouTube karaoke search setup.
  The app can validate and activate a pasted API key for the running process,
  but durable production persistence remains `youtube_api_key` in Vault or
  `HALLOWEEN_YOUTUBE_API_KEY` in the environment.
- Karaoke signups persist:
  `youtube_video_id`, `youtube_watch_url`, `youtube_embed_status`,
  `youtube_title`, `youtube_channel`, `youtube_thumbnail_url`,
  `youtube_duration`, and `youtube_last_checked_at`, while preserving the
  legacy `youtube_link` field.
- Admin karaoke rows show readiness badges and per-singer controls:
  `Set Stage` and `Start Song`. `Start Song` is disabled unless the signup is
  marked `verified_embeddable`.
- Admin top karaoke controls show the staged singer, `Return to Stage Card`,
  and `Next Singer`.
- Live display supports `karaoke_stage` overrides. Intro mode shows a large
  now-singing card with an `Open YouTube` link when a safe YouTube watch URL is
  present. Video mode maximizes an embedded YouTube iframe while keeping the
  party title/header visible.
