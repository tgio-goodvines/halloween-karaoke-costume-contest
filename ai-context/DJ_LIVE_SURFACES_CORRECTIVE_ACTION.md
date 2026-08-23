# DJ Live Surfaces Corrective Action

## Status

Implemented and verified on August 23, 2026.

## Root Cause

The MusicKit receiver and Redis state correctly identified the confirmed song,
but the attendee surfaces did not share the receiver-aware rendering path.
`/party/jukebox` refreshed title and list text without replacing artwork, while
the `/party` Jukebox card, `/admin` DJ summary, and `/admin/display` music
summary were server-rendered snapshots. The artwork element was also omitted
when the first render had no cover, so later songs had no image target to
update. This allowed audio, song text, and cover art to describe different
queue items after Next or natural track advancement.

## Corrective Design

1. Keep `dj_state.receiver.current_song_id` and its resolved MusicKit queue as
   the canonical playback source.
2. Add one shared client renderer for all lightweight DJ summaries.
3. Update song identity, title, artist/album, status, artwork, request count,
   receiver state, and music visibility from one normalized payload.
4. Preserve an initially hidden artwork target, replace its `src` and `alt`
   together, and clear it when the confirmed song has no artwork or playback is
   empty.
5. Reject late responses by request sequence and monotonic display version.
6. Use five-second polling plus visibility refresh for attendee pages. Keep SSE
   limited to authenticated admin summaries because the production Gunicorn
   process has one worker and eight threads.

## Implemented Surfaces

- `/party` Jukebox overview
- `/party/jukebox` Now Playing, playlist, and personal pending requests
- `/admin` DJ receiver summary
- `/admin/display` Music Footer summary

The existing `/admin/dj` signal path/current/up-next workspace and
`/live-display` MusicKit receiver remain on their established dedicated live
clients.

## Verification

- Python route/template/state regression suite
- Dependency-free Node renderer tests
- CI syntax and Node test gates
- Browser transition test: Song A/artwork A → Song B/artwork B → Song C/no
  artwork → stopped/empty
- Visual inspection of the party dashboard and attendee Jukebox

All four updated surfaces followed the confirmed receiver state, old artwork
was removed on no-artwork/empty transitions, and the display workspace changed
between Visible and Collapsed without a page reload.
