# GitHub Actions EC2 Deployment Plan

## Goal

Deploy the Halloween Flask app from GitHub to the existing GoodVines API EC2
fleet whenever code is merged to `main`.

Do not add S3, ECS, ECR, CodeDeploy, or new hosting infrastructure. Use the
tools already in the environment:

- GitHub Actions for CI/CD orchestration.
- AWS CLI from the GitHub runner.
- AWS SSM to run deployment commands on EC2.
- Git on EC2 to pull the merged `main` commit from GitHub.
- Vault on the services EC2 for runtime secrets.
- Existing ALB, ACM cert, Route53 records, API ASG, nginx, and Redis.

GoodVines must not be impacted by Halloween deployments.

## Current Hosting Model

Requests for the Halloween app should flow through the already configured AWS
edge:

```text
https://tnq-halloween.com
  -> goodvines-api-alb
  -> goodvines-api-http target group
  -> API EC2 port 80
  -> nginx host routing
  -> 127.0.0.1:8081
  -> halloween-party.service
```

Verified AWS/EC2 context:

- AWS account: `152923357640`
- Region: `us-east-1`
- API ASG: `goodvines-api-asg`
- API target group: `goodvines-api-http`
- Target group ARN: `arn:aws:elasticloadbalancing:us-east-1:152923357640:targetgroup/goodvines-api-http/c0e4914b65049592`
- API EC2 role/profile: `GoodVinesEC2SSMRole` / `GoodVinesEC2SSMProfile`
- nginx is active on the API EC2 and listens on port `80`
- `tnq-halloween.com` and `www.tnq-halloween.com` already resolve to the ALB
- ACM certificate for the Halloween domain is issued and attached to the ALB

## Deployment Strategy

GitHub Actions should not copy a packaged artifact to S3. Instead:

1. A merge to `main` triggers the workflow.
2. GitHub Actions validates the app.
3. GitHub Actions discovers current API EC2 instances from the ASG.
4. GitHub Actions sends an SSM command to each API instance.
5. Each EC2 instance pulls the exact merged commit from GitHub.
6. Each EC2 instance installs dependencies, updates only Halloween service/nginx
   files, restarts only `halloween-party`, validates nginx, and smoke tests both
   Halloween and GoodVines.

The deployment commit SHA should come from GitHub Actions:

```text
GITHUB_SHA
```

The EC2 script must deploy that exact SHA, not just whatever `main` points to at
script runtime.

## GitHub Repository Access From EC2

EC2 needs read access to the Halloween GitHub repo.

Chosen approach:

- Store the fine-grained read-only GitHub token in Vault on EC2.
- The SSM deploy script logs into Vault with AWS IAM auth.
- The script writes the token to a locked-down temporary file, uses it through a
  temporary `GIT_ASKPASS` helper for `git fetch`/`git checkout`, and removes it
  before exit.
- The token must have read-only repository contents access for this repo.

Vault path:

```text
appsecrets/halloween_github
```

Recommended keys:

```json
{
  "repo_url": "https://github.com/tgio-goodvines/halloween-karaoke-costume-contest.git",
  "username": "x-access-token",
  "token": "<fine-grained-read-only-token>"
}
```

Do not store the GitHub repo token in GitHub Actions secrets. Do not print the
token in SSM output.

## GitHub AWS Authentication

GitHub OIDC is configured for AWS access.

Configured role:

```text
arn:aws:iam::152923357640:role/HalloweenGithubActionsDeployRole
```

Configured GitHub repository variable:

```text
AWS_ROLE_TO_ASSUME=arn:aws:iam::152923357640:role/HalloweenGithubActionsDeployRole
```

The workflow also supports the older AWS access-key secret pattern as a fallback
if OIDC is removed later.

The GitHub deployment role or credentials should allow only:

- `autoscaling:DescribeAutoScalingGroups`
- `elasticloadbalancing:DescribeTargetHealth`
- `ssm:SendCommand`
- `ssm:GetCommandInvocation`
- `ssm:ListCommandInvocations`

Avoid broad EC2 mutation permissions. GitHub Actions should not modify ASG
capacity, ALB listener defaults, Route53, ACM, security groups, or GoodVines
resources during app deploys.

GitHub repository/environment variables:

```text
AWS_REGION=us-east-1
AWS_ROLE_TO_ASSUME=arn:aws:iam::152923357640:role/HalloweenGithubActionsDeployRole
API_ASG_NAME=goodvines-api-asg
API_TARGET_GROUP_ARN=arn:aws:elasticloadbalancing:us-east-1:152923357640:targetgroup/goodvines-api-http/c0e4914b65049592
HALLOWEEN_DOMAIN=tnq-halloween.com
HALLOWEEN_APP_PORT=8081
HALLOWEEN_SERVICE_NAME=halloween-party
HALLOWEEN_APP_DIR=/opt/halloween/app
HALLOWEEN_REPO_URL=https://github.com/tgio-goodvines/halloween-karaoke-costume-contest.git
```

Do not store app runtime secrets in GitHub:

```text
HALLOWEEN_APP_SECRET
HALLOWEEN_ADMIN_PASSWORD
HALLOWEEN_REDIS_PASSWORD
VAULT_TOKEN
```

Runtime secrets must be read by the EC2 app from Vault:

```text
appsecrets/halloween_app
appsecrets/halloween_redis
```

## Files To Add

Add these files to the Halloween repo:

```text
.github/workflows/deploy-aws.yml
deploy/ec2_deploy_from_github.sh
deploy/halloween-party.service
deploy/nginx-halloween.conf
deploy/start_halloween.sh
deploy/validate_goodvines_health.sh
```

Keep the workflow YAML thin. Put EC2 install, validation, and rollback logic in
`deploy/ec2_deploy_from_github.sh`.

## GitHub Actions Workflow Plan

Workflow: `.github/workflows/deploy-aws.yml`

Triggers:

```yaml
on:
  push:
    branches:
      - main
  workflow_dispatch:
```

Concurrency:

```yaml
concurrency:
  group: halloween-production-deploy
  cancel-in-progress: false
```

Jobs:

1. `validate`
   - Check out repo.
   - Set up Python 3.11.
   - Install dependencies.
   - Run tests.
   - Run `python -m py_compile main.py`.
   - Fail before touching AWS if validation fails.

2. `deploy`
   - Configure AWS credentials.
   - Discover `InService` instances from `goodvines-api-asg`.
   - Prefer instances currently healthy in `goodvines-api-http`.
   - Send an SSM command to each target API EC2 instance.
   - Pass the exact `GITHUB_SHA` and repo URL to the EC2 deploy script.
   - Poll SSM until success or failure.

3. `public-smoke-test`
   - Verify the Halloween domain after deploy:

```bash
curl -fsS https://tnq-halloween.com/live-display >/dev/null
curl -fsS https://www.tnq-halloween.com/live-display >/dev/null
```

   - Verify GoodVines is still healthy:

```bash
curl -fsS https://appg-v.com/health >/dev/null
```

## EC2 Deployment Script Plan

Script: `deploy/ec2_deploy_from_github.sh`

The script runs on the API EC2 instance through SSM.

Required behavior:

```bash
set -euo pipefail
```

Use a deploy lock:

```text
/var/lock/halloween-deploy.lock
```

Use isolated paths:

```text
/opt/halloween/app
/opt/halloween/releases/<commit-sha>
/opt/halloween/current
/opt/halloween/shared
/var/log/halloween-party
```

Recommended service user:

```text
halloween
```

If the first implementation uses `ec2-user`, keep all Halloween files under
`/opt/halloween` and do not write into GoodVines source directories.

Install flow:

1. Confirm nginx is active.
2. Confirm GoodVines is healthy before deployment:

```bash
curl -fsS -H 'Host: appg-v.com' http://127.0.0.1/health >/dev/null
```

3. Confirm port `8081` is either unused or owned by `halloween-party`.
4. Clone the GitHub repo if `/opt/halloween/app/.git` does not exist.
5. Fetch `origin main`.
6. Verify the requested deploy SHA exists.
7. Check out the exact deploy SHA in detached-head mode.
8. Copy or rsync the checked-out app into
   `/opt/halloween/releases/<commit-sha>`.
9. Create a Python venv inside that release.
10. Install `requirements.txt`.
11. Install only Halloween systemd and nginx files.
12. Repoint `/opt/halloween/current` to the new release.
13. Restart only `halloween-party`.
14. Run `nginx -t`.
15. Gracefully reload nginx only if config validation passes.
16. Check Halloween local health.
17. Check GoodVines local health again.

The deployment must never run `git pull` inside a GoodVines directory.

## Systemd Isolation

Unit name:

```text
halloween-party.service
```

Do not modify or restart GoodVines units.

The Halloween service should:

- Use `WorkingDirectory=/opt/halloween/current`.
- Bind gunicorn to `127.0.0.1:8081`.
- Use one worker initially.
- Set only non-secret Vault connection values in systemd.

Required environment:

```ini
Environment=PYTHONUNBUFFERED=1
Environment=APP_ENV=production
Environment=VAULT_ADDR=http://172.31.118.0:8200
Environment=VAULT_AUTH_METHOD=aws
Environment=VAULT_AWS_AUTH_ROLE=goodvines-api
Environment=AWS_REGION=us-east-1
```

Runtime secrets loaded by the app from Vault:

```text
appsecrets/halloween_app
appsecrets/halloween_redis
```

## nginx Isolation

Install only:

```text
/etc/nginx/conf.d/halloween.conf
```

Do not edit the existing GoodVines nginx config.

Halloween nginx config should only match:

```text
tnq-halloween.com
www.tnq-halloween.com
```

It should proxy to:

```text
http://127.0.0.1:8081
```

The `/api/display-updates` route must disable proxy buffering for SSE.

Because nginx is shared, reload it only after:

```bash
nginx -t
```

After reload, confirm GoodVines still answers:

```bash
curl -fsS -H 'Host: appg-v.com' http://127.0.0.1/health >/dev/null
```

## Redis and Vault Isolation

Halloween uses Redis as its database. It must not use SQL.

Redis target:

```text
172.31.118.0:6379
```

Required Halloween Redis contract:

- Vault path: `appsecrets/halloween_redis`
- Redis DB: `1`
- Key prefix: `halloween:`
- Pub/sub prefix: `halloween:`

Do not read GoodVines Redis secrets directly from app code. If sharing the same
Redis password is intentional, copy it into `appsecrets/halloween_redis`.

## GoodVines Non-Impact Rules

The GitHub Actions deployment must not:

- Restart the GoodVines service.
- Modify GoodVines systemd files.
- Modify GoodVines source directories.
- Modify GoodVines nginx server blocks.
- Change ASG desired/min/max capacity.
- Change ALB default listener actions.
- Change `appg-v.com` Route53 records.
- Change the `appg-v.com` ACM certificate.
- Flush Redis or write keys outside `halloween:*`.
- Touch SQL/Postgres.

The deployment may:

- Restart `halloween-party`.
- Install/update `/etc/nginx/conf.d/halloween.conf`.
- Gracefully reload nginx after validation.
- Read GoodVines `/health` for pre/post validation.

## Rollback Plan

Every deployment should preserve the previous release symlink target.

On failure:

1. Repoint `/opt/halloween/current` to the previous release.
2. Restart only `halloween-party`.
3. Restore previous `/etc/nginx/conf.d/halloween.conf` if it changed.
4. Run `nginx -t`.
5. Reload nginx only if valid.
6. Re-check GoodVines health.

## Implementation Phases

1. Add deploy files and local validation.
2. Configure GitHub Actions AWS access using OIDC.
   - Status: complete.
   - Role: `arn:aws:iam::152923357640:role/HalloweenGithubActionsDeployRole`.
3. Store the fine-grained GitHub token in
   `appsecrets/halloween_github.token`.
4. Add `.github/workflows/deploy-aws.yml` with `push` to `main` and
   `workflow_dispatch`.
5. Run a dry-run SSM command that checks nginx and GoodVines health without
   installing anything.
6. Run the first real deploy.
7. Confirm Halloween public routes work.
8. Confirm GoodVines health still passes.
9. Test rollback.

## Scaling and Recovery

This workflow deploys the Halloween app to currently running API EC2 instances.
If the API ASG replaces or scales out instances, each new instance needs the
workflow rerun after it becomes `InService`, unless Halloween bootstrap is added
to the API launch template/user-data or to the GoodVines bootstrap/deploy
process.

Redis DB `1` preserves Halloween event state across app restarts and EC2
replacement, but app binaries, `halloween-party.service`, and
`/etc/nginx/conf.d/halloween.conf` must still be installed on every active API
EC2 instance.

## Success Criteria

Deployment is successful when:

- A merge to `main` triggers GitHub Actions.
- GitHub Actions deploys the exact merged commit SHA.
- `halloween-party.service` is active on the API EC2.
- nginx routes `tnq-halloween.com` to `127.0.0.1:8081`.
- `https://tnq-halloween.com/live-display` returns the Halloween app.
- `https://appg-v.com/health` still passes.
- GoodVines was not restarted by the Halloween deploy.
- Halloween reads secrets from Vault and writes only Redis DB `1` keys with the
  `halloween:` prefix.
