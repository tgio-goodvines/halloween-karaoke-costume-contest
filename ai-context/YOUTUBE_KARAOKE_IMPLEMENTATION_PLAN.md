# YouTube Karaoke Queue Implementation Plan

## Status

Implementation is merged and deployed to production behind the disabled
feature flag; production enablement is in progress.

Code, automated tests, deployment wiring, responsive browser QA, and the
operator provisioning script are complete. Production still requires:

- explicit approval to create the narrow `halloween-api` Vault AWS-auth
  role/policy,
- a signed-in Google Cloud session to create/verify the OAuth web client and
  consent configuration,
- host authorization of the intended YouTube channel,
- production insert/move/delete/reconcile smoke tests.

Live progress and operational handoff details are recorded in
`ai-context/YOUTUBE_KARAOKE_IMPLEMENTATION_PROGRESS.md`.

This plan adds attendee YouTube karaoke search and selection, host approval,
playlist synchronization, a dedicated `/admin/karaoke` operations workspace,
per-song workflow progress, and live-display singer cards.

The first implementation deliberately uses the official YouTube website for
playback in a separate browser tab. It does not include an embedded YouTube
player, browser extension, automatic tab switching, or remote playback
commands.

## Product Outcome

The Halloween app remains the source of truth for:

- the singer and requested song,
- the exact selected YouTube video,
- host approval,
- playlist synchronization status,
- run-of-show order,
- current and next singer,
- performance completion, skipping, and history, and
- live-display singer cards.

A dedicated playlist in the host's YouTube account is the playback projection
of the approved run of show. The playback computer stays signed into the host's
YouTube Premium account and uses two pinned tabs:

1. `/live-display` for singer introductions and party visuals.
2. The official YouTube playlist for video playback.

The operator switches tabs manually. The app must never claim that a video
started, paused, or completed based only on an admin action because it cannot
confirm official YouTube website playback.

## Scope

### Included

- Dedicated `/admin/karaoke` workspace and navigation badge.
- YouTube account connection, playlist selection/creation, health, and
  reconciliation controls.
- Server-side YouTube search for signed-in attendees and admins.
- YouTube URL/video ID validation as a fallback to search.
- Exact video metadata snapshots: title, channel, thumbnail, duration,
  availability, embeddability, age restriction, and regional restriction.
- Pending host-review queue.
- Approval, rejection, replacement, cancellation, and retry workflows.
- Adding, moving, and removing app-managed playlist items through the YouTube
  Data API.
- Seven-step workflow progress for every song.
- Needs-attention queue and operation history.
- Ordered approved run of show.
- Current/next singer stage controls.
- Live-display `up next`, `now singing`, and completion transitions.
- Redis persistence, schema migration, display-update broadcasts, tests,
  deployment secret loading, and an operator runbook.

### Explicitly excluded

- Embedded YouTube playback or the YouTube IFrame Player API.
- Automatic browser tab/window switching.
- A Chrome extension, browser automation, DOM clicking, or operating-system
  automation.
- Remote play, pause, seek, next, previous, volume, or playback
  acknowledgement for the official YouTube website.
- Treating YouTube Premium as an API entitlement.
- Downloading, caching, proxying, modifying, or otherwise redistributing
  YouTube video/audio.
- Bypassing embed, age, region, privacy, copyright, or account restrictions.

## Product Decisions

1. **Karaoke becomes its own admin job.**
   Add `karaoke` to `ADMIN_WORKSPACES`. Move detailed karaoke controls and the
   lineup editor out of `/admin/program`; leave a compact summary and direct
   link there and on `/admin`.

2. **The app lineup is authoritative.**
   The selected YouTube playlist mirrors approved entries. Manual changes made
   directly in YouTube are detected by reconciliation and are never silently
   adopted or deleted.

3. **Attendees select an exact video.**
   Free-text title and artist remain as human-readable fields, but a normal new
   request is not considered video-verified until a valid YouTube video ID has
   been selected and checked.

4. **Approval and playlist synchronization are separate facts.**
   A host can approve a request while its playlist insertion is pending or
   failed. The UI must not collapse these into one status.

5. **External writes are idempotent and reconcilable.**
   Every playlist write gets a stable operation ID and app marker. A timeout is
   an unknown result, not an automatic failure that is safe to repeat.

6. **Playback remains an operator action.**
   `Open current video` means open the official YouTube URL on the device where
   the admin pressed the button. It does not remotely change the TV.

7. **Search is deliberate, cached, and quota-limited.**
   Search runs only after an explicit submit, never on every keystroke. Direct
   URL validation remains available when the search budget is exhausted.

## User Experience

### Attendee karaoke page

Replace the current optional-link form with a guided request flow while keeping
the public lineup below it.

1. Prefill the signed-in account display name and allow an editable stage name.
2. Ask for a combined `Song title or artist` query.
3. Run search only when the attendee presses `Search YouTube`.
4. Show up to eight results per page. Each result displays:
   - unmodified thumbnail,
   - exact YouTube video title,
   - channel name,
   - duration,
   - availability warning when applicable,
   - `Preview on YouTube`, and
   - `Choose this version`.
5. Show a confirmation panel with the selected result and editable human
   `Song title` and `Artist` fields.
6. Submit the request as `Awaiting host approval`.
7. Show the attendee's own requests with workflow status and allow:
   - replacing or cancelling a pending request,
   - viewing an approved queue position, and
   - seeing rejection or sync-failure messaging without exposing internal API
     details.
8. Keep `Paste a YouTube link` as a secondary disclosure. Parse supported
   `youtube.com`, `youtu.be`, Shorts, and playlist-context URLs to one video ID;
   reject arbitrary hosts and malformed IDs.

Preserve the existing party-day gate. Attendees never authorize a Google
account and never receive the host playlist ID or OAuth credentials from a
search response.

### Dedicated admin workspace

`/admin/karaoke` is organized in this order:

1. **YouTube connection**
   - connected channel/account label,
   - authorization health,
   - selected event playlist, privacy, and official link,
   - last successful API call,
   - last reconciliation,
   - `Connect YouTube`, `Reconnect`, `Disconnect`, `Test connection`,
     `Choose playlist`, `Create event playlist`, and `Reconcile`.

2. **Tonight at a glance**
   - awaiting review,
   - needs attention,
   - playlist pending/failed,
   - ready,
   - current singer,
   - completed,
   - estimated remaining runtime, and
   - live-display status.

3. **Needs attention**
   - invalid, private, deleted, region-blocked, or changed videos,
   - revoked authorization,
   - missing playlist,
   - insertion/update/deletion timeout,
   - playlist item missing during reconciliation,
   - stale pending operation,
   - duplicate or orphan playlist projection, and
   - app order differing from YouTube order.

4. **Incoming requests**
   - media-rich request cards,
   - workflow stepper,
   - preview,
   - approve and synchronize,
   - choose replacement,
   - reject with a short reason, and
   - edit singer/song metadata.

5. **Run of show**
   - approved entries in authoritative order,
   - playlist sync and performance badges,
   - move up/down/top/end,
   - replace video,
   - retry,
   - remove,
   - per-entry history, and
   - global `Sync playlist order`.

6. **Stage controls**
   - current singer,
   - next ready singer,
   - `Show singer card`,
   - `Call next singer`,
   - `Mark on stage`,
   - `Complete and advance`,
   - `Skip`,
   - `Move to end`,
   - `Open current video on this device`,
   - `Open YouTube playlist`, and
   - `Restore live-display rotation`.

7. **Completed/rejected history**
   - completed performances,
   - skips and reasons,
   - rejected/cancelled requests, and
   - workflow and synchronization audit events.

The admin navigation chip shows a numeric badge for requests awaiting review.
An error badge takes precedence when any entry or the connection needs
attention. A `LIVE` label takes precedence while a singer is on stage.

### Responsive behavior

- Keep the existing sticky horizontal admin workspace rail.
- On phones, use flat queue rows with compact workflow summaries.
- Expand one request/lineup row at a time for media, full history, and secondary
  actions.
- Keep stage controls near the top on mobile and sticky in a right-side rail on
  wide screens.
- Reserve elevated/glowing panels for connection failure, needs-attention, and
  current-stage state.
- Do not rely on color alone; every status includes text and an icon.

## Workflow Model

### Seven user-facing steps

Every active entry renders:

```text
Submitted -> Video verified -> Approved -> Playlist synced
          -> Ready -> On stage -> Complete
```

Step visual states:

- `complete`: checkmark and success treatment,
- `current`: active glow,
- `waiting`: muted,
- `processing`: pulse plus action text,
- `attention`: warning icon and recovery action,
- `failed`: failure label and retry/replacement action, and
- `terminal`: rejected, cancelled, or skipped outside the normal progression.

### Stored status dimensions

Do not store a single overloaded status. Store independent normalized values:

```text
video_validation_status:
  pending | verified | failed | unavailable

approval_status:
  pending | approved | rejected | cancelled

playlist_sync_status:
  not_started | pending | synced | out_of_order | failed
  | removal_pending | removed

performance_status:
  waiting | called | on_stage | completed | skipped
```

Derived invariants:

- `Ready` requires approved + verified + playlist synced + performance waiting.
- An entry cannot be called/on-stage unless it is ready, except through an
  explicit admin `Allow manual playback` override recorded in history.
- Rejected/cancelled entries are not in the active run of show.
- Completed/skipped entries do not appear as next singer.
- Playlist failure never reverses host approval.
- `Mark on stage` records stage state only; it does not assert YouTube playback.

### Audit events

Append timestamped events with an actor type and actor ID/name where available:

```text
submitted
video_verification_started
video_verified
video_verification_failed
approved
rejected
video_replaced
playlist_insert_started
playlist_insert_confirmed
playlist_insert_unknown
playlist_insert_failed
playlist_order_update_started
playlist_order_confirmed
playlist_remove_started
playlist_remove_confirmed
reconciliation_started
reconciliation_completed
called_to_stage
performance_started
performance_completed
performance_skipped
moved_to_end
cancelled
```

Keep history bounded, for example the latest 100 events per entry, so event
state cannot grow without limit.

## Data Model And Migration

### Redis schema

Increment `STATE_SCHEMA_VERSION` from `5` to `6`.

Keep `KaraokeSignup` for a compact migration, but add normalized nested
structures rather than dozens of unrelated top-level fields. Use dataclass
`field(default_factory=...)` for mutable values.

Suggested persisted shape:

```json
{
  "id": "stable-signup-id",
  "requester_id": "party-account-id",
  "name": "Grace",
  "song_title": "Thriller",
  "artist": "Michael Jackson",
  "youtube_link": "https://www.youtube.com/watch?v=...",
  "requested_at": "2026-10-31T...",
  "youtube": {
    "video_id": "...",
    "title": "Exact YouTube title",
    "channel_id": "...",
    "channel_title": "Sing King",
    "thumbnail_url": "https://i.ytimg.com/...",
    "duration_seconds": 358,
    "privacy_status": "public",
    "embeddable": true,
    "age_restricted": false,
    "region_allowed": true,
    "last_verified_at": "..."
  },
  "workflow": {
    "video_validation_status": "verified",
    "approval_status": "approved",
    "playlist_sync_status": "synced",
    "performance_status": "waiting",
    "playlist_item_id": "...",
    "playlist_revision": 1,
    "operation_id": "",
    "operation_started_at": "",
    "last_sync_error_code": "",
    "last_sync_error_message": "",
    "approved_at": "...",
    "approved_by": "admin",
    "called_at": "",
    "started_at": "",
    "completed_at": ""
  },
  "history": []
}
```

Add a `youtube_karaoke` object to the canonical state:

```json
{
  "playlist_id": "",
  "playlist_title": "",
  "playlist_privacy": "",
  "channel_id": "",
  "channel_title": "",
  "connection_status": "not_configured",
  "last_connection_check_at": "",
  "last_connection_error": "",
  "last_reconciled_at": "",
  "last_reconciliation_summary": {},
  "search_budget_date": "",
  "search_calls_used": 0
}
```

Never put OAuth client secrets, refresh tokens, access tokens, or API keys in
this state object, JSON exports, display payloads, templates, logs, or browser
storage.

Extend `karaoke_state` with:

```json
{
  "party_started": false,
  "current_singer_id": null,
  "next_singer_id": null,
  "stage_mode": "standby"
}
```

### Migration behavior

- Preserve stable existing karaoke IDs, order, name, title, artist, and link.
- Extract a video ID from valid existing YouTube links.
- Existing records with a video ID become:
  - validation `pending`,
  - approval `pending`,
  - playlist `not_started`,
  - performance `waiting`.
- Existing records without a valid YouTube ID become `video unavailable` and
  appear in Needs attention; do not delete them.
- Do not automatically insert any migrated entry into the host playlist.
- Retain `current_singer_index` fallback loading for old snapshots, then persist
  `current_singer_id` and `next_singer_id`.
- Update karaoke JSON export with all non-secret workflow fields and history.
- Add tests that load schema versions 1-5 and persist them back as version 6.

## YouTube Integration

### Google project and account

- Create a Google Cloud project dedicated to this application.
- Enable YouTube Data API v3.
- Configure the OAuth consent screen for the host's personal-use integration.
- Publish the consent configuration rather than leaving it in Testing, whose
  refresh tokens for sensitive scopes expire after seven days.
- Configure the canonical production redirect:
  `https://tnq-halloween.com/admin/karaoke/youtube/callback`.
- Authorize only the host account that owns the intended YouTube channel.
- Verify the channel identity after consent so a Brand Account is not selected
  accidentally.
- Request only the minimum playlist-management scope accepted by
  `playlistItems.insert/update/delete`.

### Dependencies and client boundary

Add the official Google auth/API client libraries to `requirements.txt`.
Keep all Google-specific calls behind helpers so tests mock a narrow local
interface rather than the generated client:

```text
youtube_connection_status()
youtube_search_videos(query, page_token)
youtube_get_videos(video_ids)
youtube_list_owned_playlists(page_token)
youtube_create_playlist(title, privacy)
youtube_list_playlist_items(playlist_id)
youtube_insert_playlist_item(...)
youtube_move_playlist_item(...)
youtube_delete_playlist_item(...)
youtube_revoke_credentials()
```

Normalize Google exceptions into stable internal error codes and safe operator
messages. Log request IDs/status codes where available, never token material or
full credential objects.

Apply explicit connect/read/write timeouts. Treat network timeout after a write
as `unknown result` and reconcile before retry.

### Search and validation

- Search with `type=video`, the configured `regionCode`, safe search settings,
  and a maximum of eight results.
- After `search.list`, batch the returned IDs through `videos.list` to collect
  duration, status, content restrictions, and current metadata.
- Do not expose raw Google API responses to the browser.
- Cache normalized identical searches in Redis using keys such as
  `halloween:youtube-search:<sha256>` with a short TTL.
- Keep cache keys outside the canonical state snapshot and under the existing
  Halloween namespace.
- Track uncached daily search calls with a Redis counter and configurable
  safety ceiling below the Google project limit.
- Rate-limit uncached searches per account and IP without blocking cached
  results or direct URL validation.
- Return a clear quota message plus the paste-link fallback when the local
  safety ceiling is reached.
- Revalidate the selected video when submitted, approved, replaced, and during
  pre-party reconciliation.

### Playlist rules

- Use a dedicated app-managed playlist for the event.
- Default new event playlists to private; offer unlisted only through an
  explicit admin selection.
- Require manual playlist ordering.
- Insert only approved and verified entries.
- Set the playlist item position based on approved active run-of-show order,
  not the position among pending/rejected entries.
- Use a marker such as
  `halloween-karaoke:<signup-id>:<playlist-revision>` in the playlist item note
  when supported. Store the returned `playlistItem.id`.
- Allow the same YouTube video for multiple singers; idempotency is based on
  signup ID + revision, not video ID.
- Never automatically delete playlist items not marked/known as app-managed.

## OAuth And Secret Storage

Use a dedicated Vault KV v1 path:

```text
appsecrets/halloween_youtube
```

Suggested secret keys:

```text
api_key
oauth_client_id
oauth_client_secret
oauth_refresh_token
region_code
```

Production startup exports:

```text
HALLOWEEN_YOUTUBE_API_KEY
HALLOWEEN_YOUTUBE_CLIENT_ID
HALLOWEEN_YOUTUBE_CLIENT_SECRET
HALLOWEEN_YOUTUBE_REFRESH_TOKEN
HALLOWEEN_YOUTUBE_REGION_CODE
```

Add matching blank/local examples to `.env.example`. Access tokens remain
process-local and are refreshed as needed.

For an in-app `Connect/Reconnect` experience:

1. Add a Halloween-specific Vault AWS auth role and policy rather than changing
   GoodVines' existing role.
2. Grant the Halloween role read access only to its required app/Redis/YouTube
   paths and create/update access only to
   `appsecrets/halloween_youtube`.
3. Add a small Vault helper that authenticates with AWS IAM and performs a KV
   v1 read-modify-write of the dedicated YouTube secret.
4. Store an unpredictable OAuth `state` value in the admin session and verify
   it in the callback.
5. Request offline access and explicit consent on reconnect.
6. Preserve an existing refresh token if Google omits a new one.
7. Test the credentials and capture the selected channel before reporting
   `Connected`.
8. `Disconnect` requires confirmation, revokes the grant at Google, clears the
   Vault refresh token, and leaves playlist/workflow records intact.

Do not change, restart, or broaden access for GoodVines. If the narrow Vault
write role is not ready during early development, use a manually provisioned
refresh token and render `Reconnect requires operator setup`; do not fall back
to storing plaintext credentials in Redis.

## External Side-Effect Safety

The existing generic admin POST holds the Redis state lock for the request.
Do not perform potentially slow YouTube writes inside that generic path.

Create dedicated YouTube mutation endpoints that use explicit two-phase state
updates:

1. Acquire the Redis state lock.
2. Reload state and validate the requested transition.
3. Write `pending`, a UUID operation ID, revision, and start timestamp.
4. Persist and release the lock.
5. Call YouTube with a bounded timeout.
6. Reacquire the lock and reload state.
7. Apply the result only if the operation ID/revision still matches.
8. Append history, persist, broadcast the display update, and release.

If the client disconnects or the process dies between phases, the pending
operation remains visible. Reconciliation resolves it later.

### Idempotent insert

Before retrying an uncertain insertion:

1. List playlist items.
2. Look for the exact signup/revision marker.
3. If found, save its playlist item ID and mark synchronized.
4. Insert only when no matching marker exists.

### Replacement

Use a new playlist revision:

1. Validate the replacement video.
2. Insert the new revision at the intended position.
3. Confirm and store the new playlist item.
4. Delete the old playlist item.
5. If old deletion fails, keep the new revision authoritative and flag the old
   item as an orphan for reconciliation.

This ordering avoids losing the approved song.

### Removal

- Unsynced pending/rejected entries can leave the active queue immediately.
- A synced entry first becomes `removal_pending`.
- Remove the external playlist item, then mark it removed/cancelled.
- A failed removal remains in Needs attention and out of the ready queue until
  reconciled.

### Reordering

- Update local approved order first and mark affected items `out_of_order`.
- Send the minimum required YouTube position updates.
- Re-list the playlist after updates before marking the order synchronized.
- If some updates fail, keep local order authoritative and show the affected
  entries in Needs attention.

## Routes And Files

### Planned routes

Attendee:

```text
GET  /party/karaoke
POST /party/karaoke
GET  /api/party/karaoke/search
POST /party/karaoke/<entry_id>/cancel
POST /party/karaoke/<entry_id>/replace
```

Admin:

```text
GET  /admin/karaoke
POST /admin/karaoke
GET  /api/admin/karaoke-state
GET  /api/admin/karaoke/search
POST /api/admin/karaoke/entries/<entry_id>/approve
POST /api/admin/karaoke/entries/<entry_id>/reject
POST /api/admin/karaoke/entries/<entry_id>/retry
POST /api/admin/karaoke/entries/<entry_id>/replace
POST /api/admin/karaoke/entries/<entry_id>/remove
POST /api/admin/karaoke/reconcile
GET  /admin/karaoke/youtube/connect
GET  /admin/karaoke/youtube/callback
POST /admin/karaoke/youtube/disconnect
```

Keep simple lineup and stage actions in the existing CSRF-protected
`admin_portal` handler when they do not call YouTube. Put external YouTube
operations in dedicated endpoints with explicit two-phase locking.

### Planned source changes

- `main.py`
  - schema v6 and normalization,
  - YouTube configuration/client helpers,
  - search/cache/quota helpers,
  - OAuth/Vault helpers,
  - workflow transitions and derived view state,
  - routes, admin actions, reconciliation, and display payloads.
- `templates/karaoke_signup.html`
  - attendee search/selection/request status UI.
- `templates/admin.html`
  - add navigation/home summaries and remove detailed karaoke content from
    Program.
- `templates/admin_karaoke.html`
  - dedicated workspace shell and server-rendered fallback.
- `templates/_karaoke_admin_queue.html`
  - reusable incoming/run-of-show/history fragments.
- `static/karaoke.js`
  - attendee search, result selection, pagination, and progressive enhancement.
- `static/karaoke-admin.js`
  - live workflow refresh, async external actions, filters, and stage controls.
- `static/styles.css`
  - workflow stepper, status badges, responsive queue, stage rail, and
    needs-attention states aligned with the current design system.
- `templates/display.html`, `static/display.js`, `static/display.css`
  - karaoke call/current/complete card modes only; no player.
- `deploy/start_halloween.sh`
  - load optional YouTube secret fields from the dedicated Vault path.
- `deploy/halloween-party.service`
  - set only non-secret Vault path/role configuration when required.
- `.env.example`
  - local YouTube configuration placeholders and quota settings.
- `requirements.txt`
  - official Google auth/API client dependencies and Vault client if selected.
- `tests/test_redis_state.py`
  - persistence, route, transition, API-error, auth, and display regressions.
- `ai-context/*`
  - update feature, architecture, admin workspace, deployment, and runbook
    documentation only after implementation is complete.

Consider moving YouTube helpers to `youtube_karaoke.py` if `main.py` becomes
materially harder to navigate. Keep the rest of the app in its current
Flask/Jinja structure.

## Live Display And Manual Playback

Add display override types such as:

```text
karaoke_call
karaoke_now_singing
karaoke_complete
```

`Call next singer` should render a high-contrast card with:

- `Up next`,
- singer name,
- song and artist,
- optional YouTube thumbnail,
- queue position, and
- a short microphone-ready prompt.

`Mark on stage` may render `Now singing` if the operator intentionally switches
to the live-display tab, but the normal workflow is to switch to the official
YouTube tab for playback.

`Complete and advance` selects the next ready entry and can show a brief
completion/next-up card. Drink-ready notices must remain above karaoke event
overrides, preserving the current notice/event precedence.

Do not add a playback receiver to `/live-display` and do not add YouTube
playback state to `/api/display-data`.

## Implementation Phases

### Phase 0: External setup and feature flag

Tasks:

- Create the Google project, API credentials, OAuth consent configuration, and
  production redirect.
- Create the dedicated Vault path and, if using in-app reconnect, the narrow
  Halloween Vault role/policy.
- Add `HALLOWEEN_YOUTUBE_KARAOKE_ENABLED`, default false.
- Add a configuration health check and an admin-only diagnostic view.
- Establish a private test playlist separate from the real event playlist.

Exit criteria:

- Local/test code can make an authenticated `channels.list(mine=true)` call.
- Production can load YouTube credentials without printing them.
- With the flag off, current karaoke behavior and tests are unchanged.

### Phase 1: Schema v6 and workflow helpers

Tasks:

- Extend `KaraokeSignup` and `karaoke_state`.
- Add `youtube_karaoke` settings/state.
- Implement normalizers, transition guards, history, derived steps, and
  migration.
- Update exports and backup behavior.
- Add legacy snapshot and invalid-state tests.

Exit criteria:

- Versions 1-5 load without data loss.
- Version 6 round-trips all workflow fields.
- Invalid transitions are rejected and do not persist partial state.

### Phase 2: Read-only YouTube search and validation

Tasks:

- Add client abstraction, error normalization, search, `videos.list`
  enrichment, URL parsing, cache, throttling, and local daily budget.
- Add authenticated attendee/admin search endpoints.
- Test deleted/private/age-restricted/region-blocked/malformed results.

Exit criteria:

- Search never leaks credentials or raw API payloads.
- Repeated normalized queries use cache.
- Quota exhaustion leaves direct URL validation available.

### Phase 3: Attendee request experience

Tasks:

- Build result cards, preview links, selection confirmation, and paste-link
  fallback.
- Bind requests to the signed-in account while retaining an editable stage
  name.
- Add own-request pending/approved/rejected/sync status and allowed
  cancel/replace actions.
- Keep public lineup limited to approved active entries; do not expose rejected
  reasons or internal errors.

Exit criteria:

- A party-day attendee can select an exact verified video and see it awaiting
  approval.
- A pending request can be cancelled/replaced without affecting other entries.
- Pre-party route gating remains intact.

### Phase 4: Dedicated admin workspace

Tasks:

- Add workspace navigation, home/program summaries, attention badge, filters,
  connection panel, overview metrics, incoming queue, run of show, stage panel,
  and history.
- Implement the seven-step server-rendered workflow component.
- Add live refresh through the existing display-update SSE signal plus a safe
  admin-state endpoint.
- Preserve non-JavaScript form fallbacks.

Exit criteria:

- Desktop and 390px mobile layouts expose the same operational actions.
- The admin can distinguish pending, processing, synced, ready, active,
  completed, rejected, and failed records without opening every row.

### Phase 5: Approval and playlist synchronization

Tasks:

- Implement OAuth connect/reconnect/disconnect if the Vault write path is
  ready.
- Add playlist list/create/select/test controls.
- Implement two-phase approve/insert, retry, replacement, removal, ordering,
  and reconciliation.
- Add operation timeouts, stale-pending detection, idempotent markers, and
  audit history.
- Add test doubles for success, known failure, timeout/unknown, late retry, and
  duplicate marker recovery.

Exit criteria:

- Approval is not `Ready` until YouTube returns or reconciliation finds the
  playlist item.
- Retrying an uncertain insertion cannot create another item for the same
  signup revision.
- External failure is recoverable without editing Redis manually.

### Phase 6: Run of show, stage controls, and display cards

Tasks:

- Add call/on-stage/complete/skip/requeue transitions.
- Derive next singer from ready approved order.
- Add live-display karaoke card modes and SSE refresh.
- Add official YouTube playlist/current-video links labeled as local-device
  actions.
- Update the operator workflow copy for the two-tab setup.

Exit criteria:

- The admin can operate a complete show without editing the lineup form.
- The live-display tab always reflects current app stage state when selected.
- No UI implies that the app controls or confirms YouTube playback.

### Phase 7: Production deployment and runbook

Tasks:

- Update Vault secrets/role, start wrapper, environment examples, dependencies,
  launch-template bootstrap inputs if needed, and deployment documentation.
- Deploy behind the feature flag.
- Authorize the production host account and select/create the real playlist.
- Run reconciliation and a two-tab rehearsal on the actual TV/audio computer.
- Document token revocation, quota exhaustion, missing playlist, deleted video,
  sync failure, Redis outage, and manual-playback fallback recovery.

Exit criteria:

- GoodVines health is unchanged.
- Halloween health and Redis persistence remain healthy.
- A replacement API instance loads the YouTube configuration.
- The operator can complete the runbook without secret values appearing in
  terminal, SSM, application, or GitHub logs.

### Phase 8: Enablement

Tasks:

- Run the full automated suite and browser QA.
- Reconcile the production playlist.
- Enable the feature for admins first.
- Perform a small controlled attendee test.
- Enable attendee search after quota and error telemetry are confirmed.

Exit criteria:

- All acceptance scenarios pass.
- No unresolved `pending` or `failed` operations remain before the event.
- The manual two-tab playback rehearsal succeeds end to end.

## Verification Matrix

### Unit and state tests

- URL parsing for every supported YouTube URL form and hostile lookalike hosts.
- Metadata normalization, safe thumbnail URL handling, and duration parsing.
- Schema v1-5 migration and schema v6 round trip.
- Every allowed and rejected workflow transition.
- Derived stepper and needs-attention state.
- History bounds and actor metadata.
- Current/next singer selection after move/remove/skip/complete.

### API integration tests with fakes

- Search success, pagination, cache hit, account/IP throttling, and daily cap.
- Video missing/private/deleted/age/region cases.
- OAuth state mismatch, no refresh token, revoked token, and wrong channel.
- Playlist selection/creation.
- Insert/update/delete success.
- Known API failure.
- Timeout with later reconciliation success.
- Retry idempotency using signup/revision marker.
- Replacement with orphan old item.
- Foreign playlist item detection without automatic deletion.
- Manual YouTube reorder detected and local order retained.

### Authorization and security tests

- Attendee endpoints require `regular`.
- Admin state/mutations/OAuth routes require `admin`.
- POSTs require CSRF; OAuth callback requires matching OAuth state.
- Role preview cannot grant karaoke admin capability.
- Secrets never appear in API JSON, HTML, exports, logs captured by tests, or
  Redis snapshots.
- External image and link URLs are normalized and safely rendered.

### Browser and responsive tests

- Attendee search/select/submit/cancel/replace at desktop and 390px.
- Admin queue filtering and row disclosure at desktop and 390px.
- Processing animation followed by success/failure without full-page state
  ambiguity.
- Keyboard focus, labels, status text, reduced motion, and color-independent
  status.
- Background live-display tab catches up through SSE/polling when selected.
- Drink-ready notice precedence remains correct.

### Deployment smoke tests

- `python -m compileall main.py`
- `python -m pytest`
- Halloween `/health`
- every admin workspace returns `200`
- disabled-feature behavior
- authenticated YouTube connection test
- test-playlist insert/move/delete/reconcile
- public attendee search with no credential exposure
- GoodVines `https://appg-v.com/health`

## Acceptance Scenarios

1. An attendee searches, selects an exact video, submits it, and sees
   `Awaiting host approval`.
2. The admin approves it and sees processing advance through verified,
   approved, synced, and ready only after YouTube confirms insertion.
3. A timed-out insertion is reconciled without creating a duplicate.
4. The admin replaces an approved video without losing the lineup entry.
5. Reordering the run of show updates the local order immediately and reports
   YouTube order synchronization separately.
6. A deleted/private video moves to Needs attention and cannot be called ready.
7. A foreign playlist item is reported but not deleted automatically.
8. `Call next singer` updates the live-display card and stage state.
9. `Mark on stage` does not report playback confirmation.
10. `Complete and advance` selects the next ready singer.
11. Revoked OAuth credentials produce a connection-level recovery action while
    preserving lineup state.
12. Search quota exhaustion presents a direct-link fallback.
13. Redis or YouTube failure never produces a misleading success message.
14. The TV operator can run the full show with the official YouTube playlist
    tab and live-display tab.

## Operational Guardrails

- Never store or print OAuth refresh/access tokens.
- Never put the host's YouTube credentials in attendee-facing JavaScript.
- Never treat a network timeout as proof that a write failed.
- Never auto-delete unknown playlist items.
- Never replace local authoritative order from YouTube without explicit admin
  confirmation.
- Never hold the shared Redis state lock across a YouTube network call.
- Never enable attendee search without cache and a local quota ceiling.
- Never change or restart GoodVines services while deploying this feature.
- Back up Redis state before schema migration and before bulk reconciliation.
- Keep the feature flag available as an event-night fallback; disabling
  YouTube integration must preserve the existing manual karaoke lineup.

## Documentation To Update After Implementation

- `ai-context/PROJECT_OVERVIEW.md`
- `ai-context/FEATURES.md`
- `ai-context/ARCHITECTURE.md`
- `ai-context/FILE_INVENTORY.md`
- `ai-context/ADMIN_WORKSPACE_UX_PROGRESS.md`
- `ai-context/RESPONSIVE_UX_PROGRESS.md`
- `ai-context/VAULT_SECRETS_DESIGN.md`
- `ai-context/GITHUB_ACTIONS_DEPLOYMENT_IMPLEMENTATION_PROGRESS.md`
- `AGENTS.md`

Do not describe the feature as supported in `FEATURES.md` until the code,
production configuration, and end-to-end rehearsal are complete.
