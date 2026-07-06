# Vault Admin Token Recovery

Do not store or print the Vault admin/root token in this repository, chat, logs,
or GitHub Actions output.

The current GoodVines services EC2 keeps the original Vault init material
locally at:

```text
/root/goodvines-vault-init.json
```

The Vault admin/root token is the `root_token` field in that JSON file. It can
be used from the services EC2 when an operator needs to update Halloween secrets
such as `appsecrets/halloween_app.admin_password`.

## Preferred Operator Pattern

- Use SSM to run Vault commands on the services EC2.
- Read `root_token` from `/root/goodvines-vault-init.json` inside the SSM
  command.
- Do not echo the token or secret values.
- Use `VAULT_ADDR=http://127.0.0.1:8200` on the services EC2.
- Write back the full KV v1 secret with `vault kv put`, preserving existing
  keys.
- Restart only `halloween-party` on the API EC2 after changing runtime app
  secrets.

## Verification

Verified during the July 2026 deployment work:

- `/root/goodvines-vault-init.json` exists on services EC2
  `i-09308adf7f1d6d0cd`.
- The `root_token` can authenticate with `vault token lookup`.
- The token can read `appsecrets/halloween_app`.
- The `appsecrets` mount is KV v1, so use KV v1-compatible commands; metadata
  operations are not supported.

## Related Paths

- Halloween app secret: `appsecrets/halloween_app`
- Halloween Redis secret: `appsecrets/halloween_redis`
- Halloween GitHub checkout secret: `appsecrets/halloween_github`
- Vault design context: `ai-context/VAULT_SECRETS_DESIGN.md`
