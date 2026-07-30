# YouTube Karaoke Implementation Progress

## Objective

Add attendee exact-video YouTube karaoke requests, host approval and playlist
synchronization, a dedicated `/admin/karaoke` workspace, seven-step workflow
status, run-of-show/stage controls, and live-display singer cards. Playback
remains in the official YouTube website; no embedded player is included.

## Current Status

Repository implementation is complete on
`agent/youtube-karaoke-workflow`. Production configuration, authorization,
merge, and deployment remain in progress.

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
- Added dedicated `/admin/karaoke` connection health, playlist controls,
  metrics, admin search, pending review, attention recovery, run of show,
  ordering, history, and sticky stage controls.
- Added two-phase Redis mutations so no YouTube network request holds the
  shared state lock.
- Added signup/revision markers in playlist-item notes for idempotent retry and
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

## Verification Completed

- Python compile, shell syntax, and `git diff --check` passed.
- Full pytest suite passed: 115 tests.
- Coverage includes schema 1-5 migration, cache/quota, URL and
  video safety, attendee ownership, approval/retry/failure/reconciliation,
  playlist setup, replacement/removal, ordering, stage/display state, OAuth
  state, and credential exclusion.
- Browser QA completed for `/admin/karaoke` at desktop and `390x844`.
- Browser QA completed for `/party/karaoke` at `390x844`.
- Browser findings for hidden pagination, empty selection layout, finder
  spacing, and admin result styling were fixed.

## Production Work Still Required

1. Obtain explicit user approval for the narrow Vault role/policy change.
2. Run `deploy/configure_youtube_vault.sh` on services EC2 through SSM.
3. Sign into Google Cloud, enable/verify YouTube Data API v3, configure the
   OAuth consent screen, and create a web client with redirect
   `https://tnq-halloween.com/admin/karaoke/youtube/callback`.
4. Store the OAuth client ID/secret in the dedicated Vault path without
   printing or committing them.
5. Deploy with the feature disabled, authorize the host YouTube channel from
   `/admin/karaoke`, choose/create a private test playlist, and verify channel
   identity.
6. Run production search and playlist insert/move/delete/reconcile smoke tests.
7. Set `enabled=true`, restart only `halloween-party`, and repeat Halloween and
   GoodVines health checks.
8. Merge to `main`, verify GitHub Actions, and record the deployed commit/run.

## Guardrails

- Never print or commit API keys, OAuth client secrets, refresh/access tokens,
  Vault tokens, or admin credentials.
- Never change or restart GoodVines services.
- Never auto-delete foreign YouTube playlist items.
- Never report official YouTube website playback as app-confirmed playback.
- Keep the feature flag available as an event-night fallback.
