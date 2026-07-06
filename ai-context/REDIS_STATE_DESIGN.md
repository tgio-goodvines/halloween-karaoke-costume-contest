# Redis State Design

Redis is the persistence layer for the Halloween app. The app should not use SQL.

## Redis Database Isolation

Use the existing GoodVines Redis service, but isolate Halloween data with its own
logical Redis DB and prefix.

Required defaults:

```bash
HALLOWEEN_REDIS_HOST=172.31.118.0
HALLOWEEN_REDIS_PORT=6379
HALLOWEEN_REDIS_DB=1
HALLOWEEN_REDIS_PREFIX=halloween
```

The Redis URL equivalent is:

```bash
redis://default:<password>@172.31.118.0:6379/1
```

Local development should use the existing Homebrew Redis service on
`127.0.0.1:6379`, DB `1`, with the same `halloween:` key prefix and ACL
credentials from `/opt/homebrew/etc/redis.conf`:

```bash
HALLOWEEN_REDIS_HOST=127.0.0.1
HALLOWEEN_REDIS_PORT=6379
HALLOWEEN_REDIS_DB=1
HALLOWEEN_REDIS_USERNAME=<local-redis-acl-user>
HALLOWEEN_REDIS_PASSWORD=<local-redis-acl-password>
HALLOWEEN_REDIS_PREFIX=halloween
HALLOWEEN_REDIS_URL=redis://<local-redis-acl-user>:<local-redis-acl-password>@127.0.0.1:6379/1
```

Do not commit the local Redis ACL password to repo files.

Still prefix all keys with `halloween:` even when using DB `1`. The logical DB
protects against accidental browsing/collision, while the prefix protects
against future Redis DB consolidation or tooling mistakes.

## Core Key Layout

Recommended minimal state model:

```text
halloween:state
halloween:state:backup:<timestamp>
halloween:display:update-version
halloween:display:pubsub
halloween:lock:state
halloween:rate-limit:<scope>:<client-id>
halloween:session:<session-id>
```

### `halloween:state`

Store the complete application state as one JSON document. This is the fastest
and lowest-risk migration from the current module-level globals.

Shape:

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

Use JSON serialization that round-trips the existing dataclass state cleanly.

### `halloween:lock:state`

Use a short-lived Redis lock for state mutations so concurrent requests do not
overwrite each other.

Suggested behavior:

- `SET halloween:lock:state <token> NX EX 10`
- Only the lock holder writes `halloween:state`
- Release with a compare-and-delete Lua script or a safe lock helper
- If lock acquisition fails, retry briefly or return a friendly busy error

### `halloween:display:pubsub`

Publish live-display updates on every state mutation that currently calls
`broadcast_display_update()`.

Redis ACL users must include a channel pattern that permits this pub/sub
channel, for example `&halloween:*`. Key patterns such as `~halloween:*` do not
grant channel access by themselves.

Message shape:

```json
{
  "version": 42,
  "reason": "admin-update"
}
```

Every app process should subscribe to this channel and notify its local SSE
clients.

### `halloween:display:update-version`

Store the latest display update version as an integer. This lets new processes
catch up after restart.

## Runtime State Flow

On startup:

1. Load secrets from Vault.
2. Connect to Redis DB `1`.
3. Read `halloween:state`.
4. If missing, initialize default state and write it.
5. Start Redis pub/sub listener for display events.

On mutation:

1. Acquire `halloween:lock:state`.
2. Load latest `halloween:state`.
3. Apply mutation.
4. Increment `display_update_version` if display-relevant.
5. Write `halloween:state`.
6. Optionally write a timestamped backup.
7. Publish to `halloween:display:pubsub`.
8. Release the lock.

On read:

- Read from in-memory cache if the process owns a freshly loaded copy.
- Re-read from Redis before admin/voting mutations.
- `/api/display-data` should reflect Redis-backed state.

## Backup and Export

Because Redis is the database, add a simple export path.

Recommended admin-only routes or operator commands:

- export current `halloween:state` as JSON
- export final costume results
- export final karaoke lineup

Implemented export routes:

- `/admin/export/state`
- `/admin/export/costume-results`
- `/admin/export/karaoke-lineup`

These currently inherit the existing `/admin` authentication caveat; add admin
auth before public exposure.

Recommended automatic backup behavior:

- Write `halloween:state:backup:<timestamp>` at major lifecycle events:
  - contest start
  - voting close/winner lock
  - karaoke start
  - manual admin export
- Set backup TTL long enough to cover the event and cleanup window, for example
  30 days.

## Redis Persistence Requirement

Before relying on Redis for event records, verify server persistence settings on
the services EC2.

Useful checks:

```bash
redis-cli -h 172.31.118.0 -p 6379 -a '<password>' --no-auth-warning CONFIG GET appendonly
redis-cli -h 172.31.118.0 -p 6379 -a '<password>' --no-auth-warning CONFIG GET save
```

If Redis persistence is not enabled or not acceptable, the app must at least
provide export/backup commands and event-day operators should export final state.

Do not solve durability by adding SQL.

## Multi-Node Behavior

Redis-backed state lets multiple API EC2 nodes run the Halloween app without
splitting signups/votes across processes.

Caveats:

- SSE connections are still local to each app process.
- Redis pub/sub is required so updates handled by one node notify displays
  connected to another node.
- Polling `/api/display-data` remains a useful fallback.
- Use one gunicorn worker until Redis locking and pub/sub are fully tested.

## Dependencies

Add:

```text
redis>=5.0,<6.0
```

Optional for server-side sessions:

```text
Flask-Session>=0.8,<1.0
```

Do not add SQL dependencies.
