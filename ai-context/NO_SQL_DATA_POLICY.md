# No-SQL Data Policy

The Halloween app must not use PostgreSQL or any SQL database for its own event
state.

Earlier planning considered Postgres as an option because GoodVines already runs
PostgreSQL on the services EC2 instance. That path is now intentionally rejected
for the Halloween app.

## Required Persistence Direction

Use Redis for Halloween app state.

The app should store signups, votes, registered attendees, admin state, live
display state, locks, and optional session/rate-limit data in the existing
GoodVines Redis service, isolated with:

- its own Redis logical database number, and
- a strict `halloween:` key prefix.

Do not add:

- SQLAlchemy
- psycopg
- Flask-SQLAlchemy
- Alembic
- SQL migrations
- Postgres roles, schemas, or tables for Halloween

## Existing SQL Infrastructure Still Exists

GoodVines still uses PostgreSQL on the private services EC2. That does not mean
Halloween should use it.

Relevant GoodVines SQL details only matter as "do not touch" context:

- PostgreSQL host: `172.31.118.0`
- PostgreSQL port: `5432`
- GoodVines database: `gvdb`
- GoodVines app role: `goodvines_app`
- GoodVines Vault secret: `appsecrets/postgres`

The Halloween app must not read `appsecrets/postgres` and must not create a
`halloween_postgres` secret.

## Redis Is the Halloween Database

Use Redis as the Halloween app's database for this event app.

Recommended Redis isolation:

- Redis host: `172.31.118.0`
- Redis port: `6379`
- Redis logical DB: `1`
- Redis key prefix: `halloween:`
- Vault secret path: `appsecrets/halloween_redis`

GoodVines should continue using its existing Redis conventions and keys. The
Halloween app must never write unprefixed Redis keys.

## Consequences

Redis is fast and simple, but it is not the same durability model as Postgres.
Implementation must account for that:

- Store all event state in a compact Redis data model.
- Keep periodic state snapshots if event results matter after the party.
- Verify Redis persistence settings before relying on Redis as the only event
  record.
- Provide an admin/export path or operator command to export final results.

For this app's short-lived party use case, Redis-only persistence is acceptable
as long as the operational tradeoff is explicit.

## Context Files to Read

For implementation, read these files together:

- `ai-context/REDIS_CONNECTION_REQUIREMENTS.md`
- `ai-context/REDIS_STATE_DESIGN.md`
- `ai-context/VAULT_SECRETS_DESIGN.md`
- `ai-context/GITLAB_AWS_DEPLOYMENT_DESIGN.md`
