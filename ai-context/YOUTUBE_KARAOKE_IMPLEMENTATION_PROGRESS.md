# YouTube Karaoke Implementation Progress

## Objective

Add attendee exact-video YouTube karaoke requests, host approval and playlist
synchronization, a dedicated `/admin/karaoke` workspace, seven-step workflow
status, run-of-show/stage controls, and live-display singer cards. Playback
remains in the official YouTube website; no embedded player is included.

## Current Status

Implementation, Google/Vault configuration, host authorization, playlist
rehearsal, and production activation are complete as of 2026-07-30.
`appsecrets/halloween_youtube.enabled` is `true`.

Deployment record:

- Pull request: `#57`
- Feature commit: `a5c425da498f9857c946d2a5e01a443f521f5400`
- Squash-merged/deployed commit: `84f1395280056ef8258511487c8bcdaa81ee8750`
- Production activation fixes:
  - `f41fa68` keeps YouTube setup available while the feature flag is off.
  - `9be0c55` preserves the OAuth PKCE verifier through the callback.
  - `ff38607` authenticates the Vault client with the EC2 instance role.
  - `3d6a6f9` reconciles by stable playlist item ID/video/position when YouTube
    does not return an item note.
- Latest GitHub Actions run: `30556824163`
- Workflow result: success
- EC2 release:
  `/opt/halloween/releases/3d6a6f92be81bf4aa7492917d13fb721d53ababe`
- `halloween-party`: active
- Halloween public health: healthy with Redis DB `1`, prefix `halloween`
- GoodVines public health: `{"online":"true"}`
- `/admin/karaoke` redirects to admin login and `/party/karaoke` redirects to
  party login when unauthenticated.

## Completed Application Work

- Upgraded Redis state schema from `5` to `6`.
- Extended `KaraokeSignup` with requester identity, request time, normalized
  YouTube metadata, independent workflow dimensions, playlist operation state,
  bounded history, and stable migration behavior.
- Added non-secret `youtube_karaoke` connection/playlist/reconciliation state.
- Added `youtube_karaoke.py` as the mockable boundary for search, validation,
  OAuth-backed playlist operations, normalized errors, bounded HTTP timeouts,
  OAuth flow construction, and dedicated Vault refresh-token updates.
- Added deliberate Redis-cached search with global and per-account daily
  safety budgets plus direct-link fallback.
- Added attendee search, pagination, exact result selection, direct-link
  validation, pending workflow, replacement, cancellation, personal status,
  and synchronized public lineup.
- Refined attendee signup into a song-details-first three-step builder. The
  attendee chooses one to four singers and enters song/artist once, the app constructs
  `{song title} {artist} karaoke`, presents exact previewable versions, and
  shows a consolidated review card before submission. YouTube titles/channels
  no longer overwrite the attendee's song-card metadata, and editing the song
  details invalidates stale results or selections.
- Upgraded the current canonical Redis schema from `13` to `14` for structured
  one-to-four singer snapshots. The first singer defaults to the signed-in
  attendee; additional singers can be selected from registered account display
  names or entered as custom names. Legacy single-name records migrate to one
  custom singer, while the derived compatibility `name` remains available.
- Added a reusable attendee/admin singer editor with an Add Singer control,
  per-row removal, a four-person cap, custom-name toggling, duplicate checks,
  mobile layout, and server-side validation. Custom singers do not create
  accounts; the signed-in requester remains the request owner.
- Added structured `singers`, `singer_names`, and `singer_label` data to karaoke
  views/exports and propagated the full singer label through personal/public
  lineups, dashboard summaries, admin review/run-of-show/history/stage cards,
  center rotation, kickoff countdowns, call/on-stage/completion overrides, and
  operator messages.
- Added dedicated `/admin/karaoke` connection health, playlist controls,
  metrics, admin search, pending review, attention recovery, run of show,
  ordering, history, and sticky stage controls.
- Added a dedicated Queue Management danger zone with a downloadable backup,
  exact-phrase confirmation, five-step progress indicators, and an admin-only
  bulk-clear operation. The normal clear removes only playlist item IDs stored
  on app-managed karaoke records, then clears the lineup and stage state while
  preserving the connected channel, selected playlist, and unmatched/manual
  YouTube playlist items.
- Bulk-clear progress is persisted in Redis. Partial YouTube failures leave the
  operation in a visible attention state, block competing karaoke mutations,
  and support idempotent retry of the original target IDs. A separately
  confirmed local-only fallback clears app state while explicitly retaining
  unresolved YouTube playlist items.
- Added two-phase Redis mutations so no YouTube network request holds the
  shared state lock.
- Added signup/revision markers in playlist-item notes plus stable ID and
  conservative video/position matching for idempotent retry and
  uncertain-result reconciliation.
- Added karaoke call/on-stage/completion display transitions without embedded
  playback state.
- Public/dashboard/display lineups include only approved,
  playlist-synchronized entries when the feature is enabled.
- Preserved the legacy manual karaoke flow behind
  `HALLOWEEN_YOUTUBE_KARAOKE_ENABLED=false`.

## Deployment And Secret Work

- Added Google API/auth and hvac dependencies.
- Added blank local YouTube settings to `.env.example`.
- Updated `deploy/start_halloween.sh` to load the dedicated
  `appsecrets/halloween_youtube` KV v1 path.
- Preserved `appsecrets/halloween_app.youtube_api_key` as a migration fallback.
- Updated `deploy/halloween-party.service` with only non-secret YouTube Vault
  role/path settings.
- Added `deploy/configure_youtube_vault.sh` to create policy
  `halloween-api-policy`, AWS auth role `halloween-api`, and the
  disabled-by-default dedicated secret path.
- The policy grants only `create`, `read`, and `update` on
  `appsecrets/halloween_youtube`. It does not change `goodvines-api`, GoodVines
  secret paths, or GoodVines services.
- Provisioned `halloween-api-policy` and AWS auth role `halloween-api`, bound
  to `arn:aws:iam::152923357640:role/GoodVinesEC2SSMRole`.
- Google Cloud project: `partynmyhead` (`PartyNMyHead`).
- OAuth application: `Halloween Karaoke Queue`, external/production, with
  redirect
  `https://tnq-halloween.com/admin/karaoke/youtube/callback`.
- Authorized host channel: `Tony G`.
- Selected event playlist: `Halloween Karaoke 2026`, private,
  `PLZT-GM5JDYno`.
- OAuth client credentials and offline refresh token are stored only in
  `appsecrets/halloween_youtube`; no credential values are committed.

## Verification Completed

- Multi-singer regression coverage passes for registered/custom combinations,
  the four-person cap, duplicate and forged-account rejection, schema-13 legacy
  migration, admin roster editing, serialization/export, dashboard/admin cards,
  rotation cards, stage overrides, and kickoff countdown payloads.
- The full Python suite passes with 163 tests and 19 subtests. Python compile,
  JavaScript syntax checks, the DJ Node regression suites, and
  `git diff --check` pass.
- Browser QA passed for the manual and YouTube-enabled karaoke forms. It
  covered default requester selection, registered-attendee choices, custom
  singer fields, add/remove and renumbering, the four-row cap, duplicate
  validation, review-label updates, selected-video preservation after singer
  edits, the reusable admin editor, no console errors, and a 390x844 mobile
  layout with no horizontal overflow.
- Python compile, shell syntax, and `git diff --check` passed.
- Full pytest suite passed: 119 tests plus 5 subtests.
- Coverage includes schema 1-5 migration, cache/quota, URL and
  video safety, attendee ownership, approval/retry/failure/reconciliation,
  playlist setup, replacement/removal, ordering, stage/display state, OAuth
  state, and credential exclusion.
- Browser QA completed for `/admin/karaoke` at desktop and `390x844`.
- Browser QA completed for `/party/karaoke` at `390x844`.
- Browser findings for hidden pagination, empty selection layout, finder
  spacing, and admin result styling were fixed.
- Production connection test refreshed channel `Tony G`.
- Production admin search returned 8 verified results for a karaoke query.
- Reversible playlist rehearsal passed insert, update/reorder, and delete; the
  private playlist returned to its original zero-item baseline.
- Production reconciliation completed with no approved items missing.
- YouTube accepted `contentDetails.note` on writes but returned an empty note
  on reads for this channel. Reconciliation was hardened before enablement to
  prefer persisted playlist item IDs, then use unique video/position recovery.
- `/admin/karaoke` shows the connected channel, private selected playlist,
  workflow metrics, seven status steps, attention queue, host review, run of
  show, and stage controls.
- The pre-existing legacy manual request for Tony / “The One” is intentionally
  retained and shown as needing a replacement video; no attendee data was
  silently rewritten during activation.

## Event-Night Operations

- Use `/admin/karaoke` to resolve the retained legacy request, review incoming
  exact-video requests, approve/synchronize entries, and control stage status.
- Keep the official YouTube playlist open on the playback device; the app does
  not embed or claim control of YouTube playback.
- Use **Test Connection** and **Reconcile** before showtime. Reconciliation
  never deletes unmatched/foreign YouTube playlist items.
- Use **Queue Management** only for an event reset. Download the backup first,
  type the displayed confirmation phrase, and leave the page open while the
  five-step status advances. If YouTube reports a partial failure, use
  **Retry Clear**; use the local-only fallback only when the remaining playlist
  items will be cleaned up manually in YouTube.
- The dedicated Vault `enabled` field remains the rollback switch. Changing it
  requires restarting only `halloween-party.service`.

## Guardrails

- Never print or commit API keys, OAuth client secrets, refresh/access tokens,
  Vault tokens, or admin credentials.
- Never change or restart GoodVines services.
- Never auto-delete foreign YouTube playlist items.
- Never report official YouTube website playback as app-confirmed playback.
- Keep the feature flag available as an event-night fallback.
