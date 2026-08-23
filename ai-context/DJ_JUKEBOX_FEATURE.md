# DJ Jukebox Feature

## Purpose

The DJ workspace lets an authenticated admin create and manage one Apple Music
playlist while the authenticated live-display browser acts as the only playback
receiver. Audio is emitted by the device connected to the TV/speakers, not by
the admin browser.

The design intentionally separates a requested command from confirmed playback.
An admin button only creates a pending Redis command. The live-display receiver
must acknowledge success or failure before the admin console reports it as
complete.

## Routes

- `GET|POST /admin/dj` — DJ workspace. Playlist CRUD, order changes,
  individual-song play, start-from-beginning, shuffle-and-play, previous,
  pause, stop, next, and visible command/receiver state flow.
- `GET /api/dj/catalog-search?q=&offset=` — authenticated Apple Music catalog
  search used by the DJ form. It returns eight songs per page plus an optional
  numeric `next_offset`; the developer token remains server-side.
- `GET /api/dj/musickit-token` — returns a short-lived developer token only to
  the authenticated live display/admin browser; never returns the Media
  Services private key.
- `POST /api/dj/receiver-state` — authenticated JSON heartbeat and command
  acknowledgement from `static/dj-display.js`. It requires the normal CSRF
  token through `X-CSRF-Token` outside testing mode.
- `GET /party/jukebox` — attendee party-day jukebox with confirmed Now Playing,
  playlist, catalog search, and personal pending requests.
- `GET /api/party/jukebox-data`, `GET /api/party/jukebox/catalog-search`, and
  `POST /party/jukebox/requests` — attendee-authenticated safe state, catalog
  search, and CSRF-protected request submission endpoints.

## Catalog Search

Both the DJ workspace and attendee jukebox use one combined **Song title or
artist** field. Apple Music catalog search matches either value, while entering
both terms narrows the results without adding two competing controls.

Results are shown eight at a time with Previous/Next controls. The server uses
Apple's pagination only as a signal that another page exists, then exposes a
bounded numeric `offset` to the browser. It never accepts or follows an
Apple-provided next URL from a client request. This keeps the developer-token
request server-side and prevents the search endpoint from becoming a URL proxy.

`/api/display-data` contains the compatibility `dj` object plus an adaptive
`layout.music` region. `templates/display.html` renders Now Playing, playback
progress, receiver/audio state, and Up Next in the footer. In automatic mode
the footer collapses when it has no meaningful playback/receiver state, letting
the center stage reclaim its height.

## Redis State

Schema version 5 stores DJ data inside the canonical `halloween:state` JSON
document:

- `dj_playlist`: ordered song dictionaries with stable app IDs, Apple Music
  catalog song ID, title, artist, album, artwork, duration, explicit flag,
  enabled flag, and timestamp.
- `dj_state.desired`: the most recently requested playback status, song,
  playlist order, and shuffle mode.
- `dj_state.current_command`: the pending command with a UUID and monotonic
  revision. A pending command has not yet been confirmed by the display.
- `dj_state.last_command`: the final success/failure acknowledgement and any
  error message. Failed commands remain visible until the next command or
  reset; routine heartbeats cannot erase their diagnostics.
- `dj_state.last_reset`: an audit record for the latest reset request and its
  pending, acknowledged, or failed display acknowledgement.
- `dj_state.receiver`: receiver identity, heartbeat, Apple Music/audio
  readiness, confirmed playback state/current song, MusicKit-resolved local
  queue order/current index/revision, elapsed position, and the latest receiver
  error. The resolved queue is distinct from `dj_state.desired.queue_order` so
  a skipped or library-backed MusicKit item cannot silently move display state
  onto a different song.
- `dj_song_requests`: pending attendee requests with requester identity,
  timestamp, and normalized Apple Music song metadata.

## Attendee Song Requests

Attendees can keep up to three pending requests and cannot request the same
Apple Music song twice while it is pending. The admin DJ workspace resolves a
request explicitly: approval atomically removes it and inserts an enabled
playlist song at a random saved-playlist position; rejection removes it without
changing the playlist. Neither decision sends a receiver command or changes the
active MusicKit queue, preserving confirmed current playback.

The receiver becomes visually `offline` after 20 seconds without a heartbeat.
The admin flow marks a pending command as `timed out` after 8 seconds without
an acknowledgement, but retains it for a possible late display response. A
failed command is rendered failed—not confirmed—until the operator sends a new
command or resets the workflow.

## State Flow

The DJ workspace always renders these four stages:

1. **Admin request** — saved command revision in Redis.
2. **Live display** — receiver heartbeat is current or offline.
3. **Apple Music** — authorization state/error reported by the display.
4. **Audio output** — actual playback state and whether the display has been
   locally enabled for browser audio.

Directly below the signal path, the workspace renders receiver-confirmed
**Current Song** and **Up Next** cards from the resolved MusicKit queue. The
playback controls sit beneath those cards and remain disabled until the display
heartbeat is current, Apple Music is authorized, audio is enabled, and no
command is already awaiting acknowledgement. Playlist editing and the reset
workflow remain available independently.

When the display has completed Apple authorization and unlocked audio, the idle
path is intentionally all green: **Admin request: Ready**, **Live display:
Connected**, **Apple Music: Authorized**, and **Audio output: Ready**. Playback
is not required for this healthy armed state.

This prevents the historical control failure mode where a button press was
shown as playback even though the display had not received it or browser audio
had not been unlocked. MusicKit startup is deferred until the Apple library has
loaded, and client errors are normalized so the UI never reports `undefined`.
The display only reports Apple Music as authorized after MusicKit confirms an
authenticated user; a cancelled or absent Apple sign-in can resolve without an
exception and is therefore explicitly treated as a pairing failure.
The first **Enable DJ Audio** click on a freshly loaded display clears any stale
MusicKit browser authorization and requires a newly issued Music User Token, so
the operator receives Apple’s account/consent flow instead of a false-ready
state.

The DJ admin workspace subscribes to the existing display-update stream and
also polls the display-state API every five seconds. Receiver pairing,
authorization, playback, reset, and command acknowledgements therefore update
in-place without an admin-page refresh.

The receiver captures MusicKit's resolved Queue after `setQueue()`, listens for
`nowPlayingItemDidChange`, and treats that event—not a predicted application
queue position—as playback confirmation. Catalog songs and library-backed
items map through direct IDs plus `catalogId`/`reportingId`. Next/Previous wait
up to seven seconds for a changed song or queue index before failing visibly.
Natural track advancement reports the same resolved queue/current index to
Redis. Receiver reports are serialized so an older heartbeat cannot overwrite
a newer track-change report.

## MusicKit Setup

The display must be opened in an admin-authenticated browser on the device
attached to party audio. That browser uses the visible **Enable DJ Audio**
button once to authorize the host Apple Music account and unlock browser audio.
Remote controls cannot safely bypass that browser gesture.

Store MusicKit settings in Vault at `appsecrets/halloween_app`; the deployment
wrapper reads them into process environment variables:

- `apple_music_developer_token` — optional pre-signed developer token, or
- `apple_music_team_id`, `apple_music_key_id`, and
  `apple_music_private_key` — server-side ES256 signing inputs.
- `apple_music_storefront` — optional; defaults to `us`.
- `apple_music_web_origin` — optional canonical HTTPS origin for MusicKit Web;
  defaults to `HALLOWEEN_PUBLIC_BASE_URL` (`https://tnq-halloween.com`).

The configured storefront is returned with the authenticated developer token
and supplied to MusicKit’s web-player configuration. The live display and
catalog search must use the same country code; production currently uses `us`.
When the app signs its developer token, it includes the canonical web origin
claim. This is required for the display browser to exchange an Apple Music
authorization for a user storefront; a pre-signed replacement token must carry
the same claim.

Never store the Media Services `.p8` key in Redis, templates, browser storage,
Git, or chat. The display browser’s Apple Music user authorization is handled
by MusicKit and is not persisted server-side.

## Operational Recovery

- **Receiver offline:** open or refresh `/live-display` on the TV device.
- **Needs authorization/audio enable:** press Enable DJ Audio on the TV and
  complete the Apple Music prompt there.
- **Command failed/timed out:** the workspace displays the receiver’s message;
  correct setup and resend the desired command.
- **Reset DJ Workflow:** use the confirmed danger action in `/admin/dj` to stop
  the receiver and clear transient playback, command, pairing/status, and error
  data while preserving the playlist. If the TV is offline, reset stays pending
  and completes on its next connection. Browser-managed Apple authorization is
  not revoked; use **Enable DJ Audio** again after reset.
- **Song unavailable:** use the playlist entry editor to replace its Apple
  Music catalog ID, then play the corrected song.

## Verification

`tests/test_redis_state.py` covers DJ state serialization, playlist CRUD,
readiness-gated commands, resolved queue/current/up-next views, failed-command
error retention, reset acknowledgement and playlist preservation, confirmed
Now Playing payloads, and JSON CSRF/admin authorization.
`tests/test_dj_queue_state.js` covers catalog/library identifier resolution,
resolved queue order, unknown placeholders, and confirmation boundaries. Run:

```bash
python -m compileall main.py
python -m pytest
node --test tests/test_dj_queue_state.js
```
