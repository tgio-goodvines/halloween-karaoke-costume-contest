# Redis Migration Plan

This file tracks the in-progress refactor from process-memory state in
`main.py` to Redis-backed Halloween event state. Keep this checklist updated as
work lands so future sessions can resume after context compaction.

## Migration Goal

Move every attendee, admin, voting, contest, karaoke, and live-display state
feature from module-level process memory to Redis, while keeping the current
compact Flask/Jinja structure until a larger refactor is explicitly requested.

Redis remains the only persistence target for Halloween app event state. Do not
add SQL.

## Current Local Redis Target

Local development uses the existing Homebrew Redis service:

```bash
HALLOWEEN_REDIS_HOST=127.0.0.1
HALLOWEEN_REDIS_PORT=6379
HALLOWEEN_REDIS_DB=1
HALLOWEEN_REDIS_USERNAME=<local-redis-acl-user>
HALLOWEEN_REDIS_PASSWORD=<local-redis-acl-password>
HALLOWEEN_REDIS_PREFIX=halloween
HALLOWEEN_REDIS_URL=redis://<local-redis-acl-user>:<local-redis-acl-password>@127.0.0.1:6379/1
```

The local ACL credentials are in `/opt/homebrew/etc/redis.conf`. Do not commit
the actual local password.

## Target State Document

Store the full application state as one JSON document at `halloween:state`:

```json
{
  "schema_version": 1,
  "costume_signups": [],
  "karaoke_signups": [],
  "costume_votes": [],
  "registered_users": {},
  "submitted_costume_votes": [],
  "contest_state": {},
  "karaoke_state": {},
  "live_display_override": null,
  "display_update_version": 0,
  "updated_at": "2026-07-05T00:00:00Z"
}
```

Use DB `1` and the `halloween:` key prefix locally and in AWS.

## Implementation Phases

### Phase 1: Redis Foundation

Status: complete

- [x] Add Redis config helper that reads `HALLOWEEN_REDIS_URL` first.
- [x] Add fallback config from `HALLOWEEN_REDIS_HOST`, `PORT`, `DB`,
  `USERNAME`, `PASSWORD`, and `PREFIX`.
- [x] Add Redis client setup with short timeouts and `decode_responses=True`.
- [x] Add key helper such as `redis_key("state") -> halloween:state`.
- [x] Add local connection verification against `127.0.0.1:6379`, DB `1`.

### Phase 2: State Serialization

Status: complete

- [x] Add dataclass serializers/deserializers for `CostumeSignup` and
  `KaraokeSignup`.
- [x] Add `snapshot_state()` for the canonical JSON state shape.
- [x] Add `apply_state_snapshot(data)` to hydrate current globals.
- [x] Ensure `submitted_costume_votes` round-trips as a sorted/list form.
- [x] Ensure `ensure_costume_votes_alignment()` runs after load.

### Phase 3: Startup Load And Save

Status: complete

- [x] On startup, connect to Redis and load `halloween:state`.
- [x] If state is missing, initialize Redis from current defaults.
- [x] Save `halloween:state` after state initialization.
- [x] Keep process globals as a cache during this migration step.

### Phase 4: Persist Existing Mutations

Status: complete

- [x] Save after attendee check-in/login updates `registered_users`.
- [x] Save and broadcast after costume signup.
- [x] Save and broadcast after karaoke signup.
- [x] Save after all admin add/update/delete/reorder actions.
- [x] Save after contest start, winner lock/show/restore, and karaoke start.
- [x] Save after voting submission and one-vote tracking.

### Phase 5: Redis Locking

Status: complete

- [x] Add short-lived state lock at `halloween:lock:state`.
- [x] Reload latest Redis state under lock before every mutation.
- [x] Save and release lock safely after mutation.
- [x] Queue state-changing requests server-side by waiting for the lock instead
  of asking users to retry.

### Phase 6: Redis Pub/Sub Display Updates

Status: complete

- [x] Store latest display update version in
  `halloween:display:update-version`.
- [x] Publish display update messages on `halloween:display:pubsub`.
- [x] Start a local background subscriber to notify SSE clients in each process.
- [x] Keep `/api/display-data` polling as fallback.

### Phase 7: Backup And Export

Status: complete

- [x] Add `halloween:state:backup:<timestamp>` helper with event-window TTL.
- [x] Back up on contest start, winner lock, karaoke start, and manual export.
- [x] Add admin JSON export routes. Important: `/admin` is still unauthenticated,
  so exports inherit that existing caveat until admin auth is implemented.

### Phase 8: Tests

Status: complete

- [x] Add serialization round-trip coverage.
- [x] Add Redis state initialization/load/save coverage.
- [x] Add signup persistence coverage.
- [x] Add voting persistence and one-vote coverage.
- [x] Add admin reorder vote-alignment coverage.
- [x] Add display payload/update-version coverage.
- [x] Add admin backup/export route coverage.

## Progress Log

- 2026-07-06: Created this persistent migration plan before beginning code
  changes. Local Redis target is authenticated Homebrew Redis on
  `127.0.0.1:6379`, DB `1`, with `halloween:` key prefix.
- 2026-07-06: Completed Phase 1 in `main.py`. Added Redis config parsing,
  prefixed key helper, Redis client construction with short timeouts, and
  verified `redis_key("state") == "halloween:state"` plus an authenticated ping
  against local Redis DB `1`.
- 2026-07-06: Completed Phases 2 and 3 in `main.py`. Added dataclass
  serializers, canonical `snapshot_state()`, `apply_state_snapshot(data)`,
  Redis load/save helpers, and startup initialization. Verified authenticated
  local startup creates/loads `halloween:state`; development imports fall back
  to process memory if Redis is unavailable.
- 2026-07-06: Completed Phase 4 first persistence pass. `broadcast_display_update()`
  now persists state/display version, attendee login saves `registered_users`,
  and public costume/karaoke signups now broadcast and save. Verified with a
  Flask test-client smoke test against local Redis using temporary prefix
  `halloween-test-codex`: one costume, one karaoke signup, one registered user,
  and display update version `2` were persisted.
- 2026-07-06: Completed Phase 5 in `main.py`. Added Flask request hooks that
  acquire `halloween:lock:state` for state-changing POST endpoints, reload
  latest Redis state before route mutation code, persist after the response, and
  release the lock safely. Initial implementation returned HTTP `503` on lock
  contention, but this was revised because users should not have to retry
  signups or ballots.
- 2026-07-06: Revised Phase 5 lock contention behavior. Lock acquisition now
  waits server-side until `halloween:lock:state` is available, while the lock
  lease still expires after 10 seconds to recover from crashed workers.
- 2026-07-06: Completed Phase 6 in `main.py`. `broadcast_display_update()` now
  persists state/version, publishes a JSON message to
  `halloween:display:pubsub`, and still notifies local SSE clients. Each app
  process starts a daemon Redis subscriber that ignores its own messages,
  reloads `halloween:state` for messages from other instances, and wakes local
  SSE clients. Local Redis ACL needed channel permission (`&*` for this local
  user; `&halloween:*` is the narrower production-style requirement), which was
  added to `/opt/homebrew/etc/redis.conf`. Verified publish payload delivery
  with temporary prefix `halloween-test-pubsub`, and verified a remote-style
  pub/sub message reloads local process state with temporary prefix
  `halloween-test-pubsub-reload`.
- 2026-07-06: Completed Phase 7 in `main.py`. Added 30-day TTL Redis state
  backups under `halloween:state:backup:<timestamp>:<reason>`, with backups on
  contest start, winner lock, karaoke start, and manual state export. Added
  JSON download routes for `/admin/export/state`,
  `/admin/export/costume-results`, and `/admin/export/karaoke-lineup`. These are
  admin-scoped routes but inherit the current `/admin` authentication caveat.
- 2026-07-06: Completed Phase 8 by adding `tests/test_redis_state.py`. The
  suite uses an in-memory Redis fake so it does not require local Redis
  credentials or a running Redis service. Coverage includes state serialization,
  Redis load/save initialization, public costume and karaoke signup persistence,
  voting persistence with one-vote protection, admin costume reorder vote
  alignment, display payload/update-version publishing, and admin JSON
  backup/export routes. Verified with
  `python3 -m unittest discover -s tests` and
  `python3 -m py_compile main.py tests/test_redis_state.py`.
