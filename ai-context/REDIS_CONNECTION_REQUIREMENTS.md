# Redis Connection Requirements

This app currently does not use Redis. If the AWS-hosted version needs shared
ephemeral state, pub/sub, rate limiting, cross-node live-display notifications,
or server-side session support, reuse the existing GoodVines Redis service on
the private services EC2 instance.

## Existing Redis Infrastructure

Current GoodVines AWS inventory and repo scripts show this Redis topology:

- Redis runs on the private services EC2 instance.
- Services instance: `i-09308adf7f1d6d0cd`
- Services static private IP: `172.31.118.0`
- Redis port: `6379`
- Redis service name on Amazon Linux: `redis6`
- API EC2 instances reach Redis over the private VPC.
- API security group: `sg-03be330cf64f419b3`
- Services security group: `sg-0846a5ed29d30eeb7`
- Services SG already allows TCP `6379` from the API SG.
- Existing GoodVines Redis defaults:
  - `REDIS_HOST=172.31.118.0`
  - `REDIS_PORT=6379`
- Existing GoodVines API gets Redis credentials from Vault secret
  `appsecrets/redis`.

Network path for Halloween when hosted beside GoodVines:

```text
halloween-party.service on API EC2
  -> 172.31.118.0:6379
  -> services EC2 Redis
```

Redis must not be exposed publicly. No public inbound Redis rule is needed or
desired.

## Server Configuration Context

The GoodVines services bootstrap configures Redis to bind to localhost and the
services static private IP:

```text
bind 127.0.0.1 172.31.118.0
protected-mode yes
requirepass <vault-managed-password>
```

The Redis password is written into Vault during services bootstrap:

```text
appsecrets/redis
```

Expected keys:

```json
{
  "username": "default",
  "password": "<redis-password>"
}
```

## Recommended Halloween Environment Contract

Use Halloween-prefixed variables so this app can run beside GoodVines without
accidentally sharing unprefixed service settings.

Recommended variables:

```bash
HALLOWEEN_REDIS_HOST=172.31.118.0
HALLOWEEN_REDIS_PORT=6379
HALLOWEEN_REDIS_DB=1
HALLOWEEN_REDIS_USERNAME=default
HALLOWEEN_REDIS_PASSWORD=<from-secret-store>
HALLOWEEN_REDIS_PREFIX=halloween
```

Optional URL form:

```bash
HALLOWEEN_REDIS_URL=redis://default:<password>@172.31.118.0:6379/1
```

If both are supported, `HALLOWEEN_REDIS_URL` should take precedence, with the
individual fields as fallback.

Do not use unprefixed `REDIS_HOST`, `REDIS_PORT`, or `REDIS_PREFIX` in this app
unless intentionally matching GoodVines conventions. GoodVines already uses
those names.

## Local Development Redis

For local development, use the existing Homebrew Redis service on
`127.0.0.1:6379`. Do not run a separate Docker Redis service for this app unless
that decision is revisited explicitly.

Local machine context from July 2026:

- Homebrew Redis is already running on `127.0.0.1:6379`.
- That Homebrew Redis has the default user disabled and requires a named ACL
  user/password from `/opt/homebrew/etc/redis.conf`.
- The app-specific local Redis target is `127.0.0.1:6379`, DB `1`, prefix
  `halloween:`, using those ACL credentials.
- Redis pub/sub requires channel ACL access. The local Redis user must include a
  channel pattern such as `&*` (or at minimum `&halloween:*`) in addition to key
  access such as `~*`.
- Avoid committing the local Redis password into repo files.

Use these local environment values:

```bash
HALLOWEEN_REDIS_HOST=127.0.0.1
HALLOWEEN_REDIS_PORT=6379
HALLOWEEN_REDIS_DB=1
HALLOWEEN_REDIS_USERNAME=<local-redis-acl-user>
HALLOWEEN_REDIS_PASSWORD=<local-redis-acl-password>
HALLOWEEN_REDIS_PREFIX=halloween
HALLOWEEN_REDIS_URL=redis://<local-redis-acl-user>:<local-redis-acl-password>@127.0.0.1:6379/1
```

Validation commands:

```bash
redis-cli -h 127.0.0.1 -p 6379 --user '<local-redis-acl-user>' \
  -a '<local-redis-acl-password>' --no-auth-warning -n 1 ping
redis-cli -h 127.0.0.1 -p 6379 --user '<local-redis-acl-user>' \
  -a '<local-redis-acl-password>' --no-auth-warning -n 1 set halloween:connection-test ok ex 60
redis-cli -h 127.0.0.1 -p 6379 --user '<local-redis-acl-user>' \
  -a '<local-redis-acl-password>' --no-auth-warning -n 1 get halloween:connection-test
redis-cli -h 127.0.0.1 -p 6379 --user '<local-redis-acl-user>' \
  -a '<local-redis-acl-password>' --no-auth-warning ACL GETUSER '<local-redis-acl-user>'
```

## Secret Source

Preferred source on EC2:

- Vault at `VAULT_ADDR=http://172.31.118.0:8200`
- Vault auth method: `aws`
- Vault AWS auth role: `goodvines-api`
- Halloween Redis secret path: `appsecrets/halloween_redis`

The Halloween app should obtain Redis credentials through its own Vault helper,
matching the GoodVines AWS IAM auth pattern. See
`ai-context/VAULT_SECRETS_DESIGN.md`.

If the implementation deliberately shares the existing GoodVines Redis password,
copy that value into `appsecrets/halloween_redis` so the Halloween app still has
an explicit secret contract. Do not import the GoodVines app package just to read
Redis secrets.

## Python Dependency Requirements

If using Redis from Flask, add:

```text
redis>=5.0,<6.0
```

If using Flask sessions in Redis:

```text
Flask-Session>=0.8,<1.0
```

Use Redis directly unless server-side sessions are explicitly needed.

## Key Naming Requirements

All Halloween keys must be namespaced to avoid collision with GoodVines keys.

Recommended prefix:

```text
halloween:
```

Suggested key names:

```text
halloween:display:update-version
halloween:display:pubsub
halloween:rate-limit:<client-id>
halloween:session:<session-id>
halloween:lock:state
```

GoodVines uses Redis prefixes such as `auth`, so never write bare keys like
`user:*`, `access:*`, `session:*`, or `display:*` without a Halloween prefix.

## Appropriate Uses for Redis

Redis is useful for this app if:

- The API ASG may run more than one node during the event.
- Live-display updates should notify displays connected to different app
  processes or nodes.
- Admin operations need a short-lived distributed lock.
- You want server-side Flask sessions rather than signed cookie sessions.
- You want rate limiting for public forms or admin login.

Redis is the required database for this app. Because Redis has different
durability tradeoffs than SQL, configure export/backup behavior for final event
results. Do not add SQL for Halloween state.

## Recommended Redis Design for Multi-Node Display Updates

The current app uses an in-process `threading.Condition` for SSE updates. That
works only inside one Python process.

If the app can run on multiple API nodes or workers:

1. Keep the current `/api/display-data` polling fallback.
2. Publish display update events to Redis pub/sub whenever
   `broadcast_display_update()` is called.
3. Have each app process subscribe to the Redis channel and notify its local SSE
   clients.
4. Store the latest display update version in Redis so new processes can catch
   up.

Suggested channel/key:

```text
halloween:display:pubsub
halloween:display:update-version
```

The Redis user must have permission to publish and subscribe to the display
channel. With Redis ACLs, grant a channel pattern such as:

```text
&halloween:*
```

Keep the message payload small:

```json
{
  "version": 42,
  "reason": "admin-update"
}
```

## Connection Client Settings

Suggested redis-py client:

```python
redis.Redis(
    host=host,
    port=port,
    db=db,
    username=username,
    password=password,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
    health_check_interval=30,
)
```

Use short timeouts so a Redis outage does not hang attendee/admin requests
indefinitely.

## Failure Behavior

Decide behavior by Redis use case:

- For rate limiting: fail open during Redis outage so guests can still use the
  app.
- For display pub/sub: fall back to `/api/display-data` polling.
- For server-side sessions: fail closed with a friendly error because sessions
  cannot be trusted.
- For distributed locks: fail closed for admin state mutations.

Log Redis connection failures clearly.

## Validation Commands

From the services EC2:

```bash
redis-cli -h 172.31.118.0 -p 6379 -a '<password>' --no-auth-warning ping
```

Expected:

```text
PONG
```

From an API EC2 instance:

```bash
redis-cli -h 172.31.118.0 -p 6379 -a '<password>' --no-auth-warning ping
```

Check namespaced write/delete:

```bash
redis-cli -h 172.31.118.0 -p 6379 -a '<password>' --no-auth-warning \
  set halloween:connection-test ok ex 60
redis-cli -h 172.31.118.0 -p 6379 -a '<password>' --no-auth-warning \
  get halloween:connection-test
redis-cli -h 172.31.118.0 -p 6379 -a '<password>' --no-auth-warning \
  del halloween:connection-test
```

From AWS CLI, confirm the network side:

```bash
aws ec2 describe-security-groups --region us-east-1 --group-ids sg-0846a5ed29d30eeb7
aws ssm describe-instance-information --region us-east-1 --filters Key=InstanceIds,Values=i-09308adf7f1d6d0cd
```

## Decision Point

Redis is optional for the first single-node event deployment.

Use Redis if the implementation needs:

- cross-node live-display notifications,
- distributed locks,
- rate limiting,
- server-side sessions,
- or shared short-lived state.

Use Redis for core contest data. Do not add PostgreSQL, SQLAlchemy, or local JSON
as the primary persistence layer.
