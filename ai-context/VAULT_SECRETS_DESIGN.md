# Vault Secrets Design

The Halloween app should obtain secrets the same way the GoodVines API does:
authenticate to the private Vault service with AWS IAM auth from the API EC2
role, read secrets from the `appsecrets` KV mount, cache them at app startup,
and never store secret values in the repo.

## Existing GoodVines Pattern

GoodVines runtime uses:

- Vault service on the private services EC2 instance.
- Vault address: `http://172.31.118.0:8200`
- Vault auth method on EC2: `aws`
- Vault AWS auth role: `goodvines-api`
- Vault mount: `appsecrets`
- KV version: v1
- API EC2 IAM role: `GoodVinesEC2SSMRole`
- Vault role binding:
  - `auth/aws/role/goodvines-api`
  - `bound_iam_principal_arn=arn:aws:iam::152923357640:role/GoodVinesEC2SSMRole`
- Policy: `goodvines-api-policy`
- Current policy grants read/list on:

```text
appsecrets/*
```

GoodVines app environment defaults:

```bash
VAULT_ADDR=http://172.31.118.0:8200
VAULT_AUTH_METHOD=aws
VAULT_AWS_AUTH_ROLE=goodvines-api
AWS_REGION=us-east-1
```

GoodVines code uses `boto3` and SigV4 to sign a `GetCallerIdentity` request,
posts the signed request to Vault `auth/aws/login`, receives a Vault token, and
uses that token to read KV secrets.

## Halloween Design Goal

Implement a small Halloween-specific Vault helper rather than importing
GoodVines app code.

The helper should:

- Use the same environment contract as GoodVines:
  - `VAULT_ADDR`
  - `VAULT_AUTH_METHOD`
  - `VAULT_AWS_AUTH_ROLE`
  - `AWS_REGION`
- Default to AWS IAM auth in EC2.
- Optionally support AppRole only for local/operator fallback if useful.
- Read only the Halloween app's expected secret paths.
- Cache secrets at startup.
- Fail loudly if required secrets are missing in AWS production.
- Avoid printing secret values in logs.

## Required Python Dependencies

Add these dependencies if implementing the same runtime pattern as GoodVines:

```text
boto3>=1.34,<2.0
botocore>=1.34,<2.0
hvac>=2.0,<3.0
```

GoodVines already uses `boto3`, `botocore`, and `hvac` for this purpose.

## Recommended Secret Paths

Use Halloween-specific secret paths under the existing `appsecrets` mount.

Recommended paths:

```text
appsecrets/halloween_app
appsecrets/halloween_redis
appsecrets/halloween_github
```

### `appsecrets/halloween_app`

Purpose: app-level secrets.

Recommended keys:

```json
{
  "secret_key": "<flask-session-secret>",
  "admin_password": "<admin-password>"
}
```

Optional future keys:

```json
{
  "csrf_secret": "<csrf-secret>",
  "basic_auth_password": "<temporary-basic-auth-password>"
}
```

### `appsecrets/halloween_redis`

Purpose: Redis credentials and namespace for required Halloween persistence.

Recommended keys:

```json
{
  "username": "default",
  "password": "<redis-password>",
  "host": "172.31.118.0",
  "port": "6379",
  "db": "1",
  "prefix": "halloween"
}
```

If the implementation deliberately shares the existing GoodVines Redis password,
copy the password value from `appsecrets/redis` into
`appsecrets/halloween_redis` rather than having the Halloween app read
`appsecrets/redis` directly. This keeps the app's secret contract explicit.

### `appsecrets/halloween_github`

Purpose: GitHub repo read credentials fetched by EC2 during SSM deploys.

Recommended keys:

```json
{
  "repo_url": "https://github.com/tgio-goodvines/halloween-karaoke-costume-contest.git",
  "username": "x-access-token",
  "token": "<fine-grained-read-only-github-token>"
}
```

This secret is for EC2-side repository checkout during deployment. GitHub
Actions should not store or print this token.

## Environment Contract

The systemd service should provide Vault connection settings, not raw app
secrets:

```ini
Environment=VAULT_ADDR=http://172.31.118.0:8200
Environment=VAULT_AUTH_METHOD=aws
Environment=VAULT_AWS_AUTH_ROLE=goodvines-api
Environment=AWS_REGION=us-east-1
Environment=APP_ENV=production
```

The app should then read actual app/DB/Redis secrets from Vault.

Avoid putting these values directly in systemd once Vault support exists:

```text
HALLOWEEN_APP_SECRET
HALLOWEEN_ADMIN_PASSWORD
HALLOWEEN_REDIS_PASSWORD
```

Those can remain local-development fallbacks, but production should prefer Vault.

## Runtime Secret API Shape

Recommended local module:

```text
secrets.py
```

Suggested public API:

```python
def get_secret(path: str) -> dict:
    ...

def get_app_secret() -> dict:
    return get_secret("halloween_app")

def get_redis_secret() -> dict:
    return get_secret("halloween_redis")

def get_github_secret() -> dict:
    return get_secret("halloween_github")
```

Because the app already has simple single-file shape, it is also acceptable to
put this helper in `main.py` initially, but a separate module keeps the route
file cleaner.

## AWS IAM Login Flow

Match GoodVines' AWS IAM auth flow:

1. Create a `boto3.Session(region_name=AWS_REGION)`.
2. Get current IAM credentials from instance metadata.
3. Build an AWS STS `GetCallerIdentity` request.
4. Sign it with `SigV4Auth`.
5. Base64 encode method, URL, body, and headers for Vault.
6. Write to `auth/aws/login` with role `VAULT_AWS_AUTH_ROLE`.
7. Store returned Vault token on the hvac client.
8. Read secrets from KV v1 mount `appsecrets`.

GoodVines reads KV v1 secrets like:

```python
client.secrets.kv.v1.read_secret(path=path, mount_point="appsecrets")["data"]
```

Halloween should do the same unless the Vault mount is upgraded later.

## Startup Behavior

On production startup:

- Log into Vault once.
- Load required secrets into an in-memory cache.
- Validate required keys.
- Configure Flask `secret_key` from `halloween_app.secret_key`.
- Configure admin auth from `halloween_app.admin_password`.
- Configure Redis from `halloween_redis`; Redis is the Halloween app database.

Required secret paths for initial public AWS deployment:

```text
halloween_app
halloween_redis
```

Optional secret path for EC2-side GitHub repo checkout:

```text
halloween_github
```

If production required secrets are missing, app startup should fail. Silent
fallback to development defaults is only acceptable for local development.

## Token Renewal

GoodVines starts a background token renewal thread. Halloween can copy this
pattern.

Recommended environment:

```bash
VAULT_TOKEN_RENEW_INTERVAL=3600
```

Behavior:

- Sleep for the renewal interval.
- Attempt `client.auth.token.renew_self()`.
- If renewal fails, attempt a fresh AWS IAM login.
- Log failures without printing token or secret values.

Because the app mostly reads secrets at startup, renewal is mainly useful for
future on-demand secret reads. It is still good to match GoodVines for
consistency.

## Local Development

Local development should not require AWS instance metadata.

Acceptable local options:

1. Use environment variables for local-only secrets:

```bash
HALLOWEEN_APP_SECRET=dev-secret
HALLOWEEN_ADMIN_PASSWORD=dev-password
```

2. Use AppRole if an operator provides:

```bash
VAULT_AUTH_METHOD=approle
VAULT_ROLE_ID=<role-id>
VAULT_SECRET_ID=<secret-id>
```

3. Use a local `.env` file that is ignored by Git.

Do not commit local secret values.

## Vault Provisioning Commands

Run these on the services EC2 with an appropriate Vault token:

```bash
vault kv put appsecrets/halloween_app \
  secret_key='<generated-flask-secret>' \
  admin_password='<generated-admin-password>'
```

```bash
vault kv put appsecrets/halloween_redis \
  username='default' \
  password='<redis-password>' \
  host='172.31.118.0' \
  port='6379' \
  db='1' \
  prefix='halloween'
```

If EC2 should fetch the GitHub repo with a fine-grained token:

```bash
vault kv put appsecrets/halloween_github \
  username='x-access-token' \
  token='<fine-grained-read-only-github-token>' \
  repo_url='https://github.com/tgio-goodvines/halloween-karaoke-costume-contest.git'
```

## Security Notes

- Keep the existing `appsecrets/*` read policy only if the same EC2 role is
  intentionally trusted to read all GoodVines and Halloween secrets.
- For tighter isolation later, create a dedicated Vault policy and role for the
  Halloween app.
- Never log Vault tokens, Redis passwords, Flask secret keys, admin passwords,
  or GitHub fine-grained tokens.
- Prefer generated high-entropy secrets.
- Rotate the admin password before each event if the app is reused.

## Implementation References

GoodVines files that define the current pattern:

- `goodvinesApi/resources/vault.py`
- `deploy/user-data-services.sh`
- `deploy/user-data-api.sh`
- `bash/configure_api_service_unit.sh`

The Halloween app should mirror the pattern, not depend on importing those files.
