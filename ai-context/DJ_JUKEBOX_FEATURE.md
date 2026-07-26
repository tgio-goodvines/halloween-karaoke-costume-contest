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
- `GET /api/dj/catalog-search?q=` — authenticated Apple Music catalog search
  used by the DJ form. The developer token remains server-side.
- `GET /api/dj/musickit-token` — returns a short-lived developer token only to
  the authenticated live display/admin browser; never returns the Media
  Services private key.
- `POST /api/dj/receiver-state` — authenticated JSON heartbeat and command
  acknowledgement from `static/dj-display.js`. It requires the normal CSRF
  token through `X-CSRF-Token` outside testing mode.

`/api/display-data` contains a `dj` object. `templates/display.html` renders a
persistent Now Playing dock that stays visible below the display header while
normal rotation, karaoke/costume overrides, and drink-ready notices continue.

## Redis State

Schema version 4 stores DJ data inside the canonical `halloween:state` JSON
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
  readiness, confirmed playback state/current song, elapsed position, and the
  latest receiver error.

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

This prevents the historical control failure mode where a button press was
shown as playback even though the display had not received it or browser audio
had not been unlocked. MusicKit startup is deferred until the Apple library has
loaded, and client errors are normalized so the UI never reports `undefined`.

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
pending commands, failed-command error retention, reset acknowledgement and
playlist preservation, confirmed Now Playing payloads, and JSON CSRF/admin
authorization. Run:

```bash
python -m compileall main.py
python -m pytest
```
