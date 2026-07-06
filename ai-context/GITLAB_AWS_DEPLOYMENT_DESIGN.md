# GitLab AWS Deployment Design

Deploy the Halloween app with GitLab CI/CD, using AWS CLI and SSM to operate on
the existing GoodVines EC2 infrastructure. The app must obtain runtime secrets
from Vault on EC2 using AWS IAM auth, not from GitLab CI variables.

## Deployment Principles

- GitLab manages build/deploy orchestration.
- GitLab stores only deployment credentials and non-secret config needed to call
  AWS APIs.
- GitLab must not store Halloween app secrets such as Flask secret key, admin
  password, Redis password, or Vault tokens.
- EC2 instances obtain app secrets directly from Vault at runtime using the same
  AWS IAM auth pattern as GoodVines.
- Deployment connects to EC2 through AWS SSM, not public SSH.
- The Halloween app runs in parallel with GoodVines on each target API EC2 node.

## Existing AWS Targets

Current GoodVines AWS runtime:

- Region: `us-east-1`
- API ASG: `goodvines-api-asg`
- ALB: `goodvines-api-alb`
- Target group: `goodvines-api-http`
- Target group ARN: `arn:aws:elasticloadbalancing:us-east-1:152923357640:targetgroup/goodvines-api-http/c0e4914b65049592`
- API EC2 IAM instance profile: `GoodVinesEC2SSMProfile`
- API EC2 role: `GoodVinesEC2SSMRole`
- Vault: `http://172.31.118.0:8200`
- Redis: `172.31.118.0:6379`

GitLab should discover current API instances from the ASG at deploy time instead
of hard-coding instance IDs.

## GitLab CI/CD Variables

Required GitLab variables:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_REGION=us-east-1
API_ASG_NAME=goodvines-api-asg
API_TARGET_GROUP_ARN=arn:aws:elasticloadbalancing:us-east-1:152923357640:targetgroup/goodvines-api-http/c0e4914b65049592
DEPLOY_REF=main
```

Optional:

```text
HALLOWEEN_APP_DIR=/home/ec2-user/halloween-karaoke-costume-contest
HALLOWEEN_VENV_DIR=/home/ec2-user/halloween-karaoke-costume-contest/.venv
HALLOWEEN_SERVICE_NAME=halloween-party
```

Do not add these to GitLab variables:

```text
HALLOWEEN_APP_SECRET
HALLOWEEN_ADMIN_PASSWORD
HALLOWEEN_REDIS_PASSWORD
VAULT_TOKEN
```

## Required EC2 Runtime Environment

The Halloween systemd service should set Vault connection variables only:

```ini
Environment=VAULT_ADDR=http://172.31.118.0:8200
Environment=VAULT_AUTH_METHOD=aws
Environment=VAULT_AWS_AUTH_ROLE=goodvines-api
Environment=AWS_REGION=us-east-1
Environment=APP_ENV=production
```

Runtime secrets are loaded from Vault by the app:

- `appsecrets/halloween_app`
- `appsecrets/halloween_redis`

The app should not need GitLab-provided app secrets.

## SSM Deployment Flow

GitLab deploy job:

1. Configure AWS CLI credentials.
2. Resolve deployment commit SHA.
3. Discover InService ASG instance IDs.
4. Optionally sort healthy ALB targets first.
5. Send SSM command to each API instance.
6. On each instance:
   - ensure OS packages are present
   - clone or update the GitLab repo
   - create/update Python venv
   - install requirements
   - write/update systemd unit
   - write/update nginx host config
   - restart `halloween-party`
   - reload nginx
   - check local health/page response
7. Verify public ALB path after deploy.

## AWS CLI Discovery Commands

Discover ASG instances:

```bash
aws autoscaling describe-auto-scaling-groups \
  --region "$AWS_REGION" \
  --auto-scaling-group-names "$API_ASG_NAME" \
  --query "AutoScalingGroups[0].Instances[?LifecycleState=='InService'].InstanceId" \
  --output text
```

Discover healthy target IDs:

```bash
aws elbv2 describe-target-health \
  --region "$AWS_REGION" \
  --target-group-arn "$API_TARGET_GROUP_ARN" \
  --query "TargetHealthDescriptions[?TargetHealth.State=='healthy'].Target.Id" \
  --output text
```

Send an SSM deployment command:

```bash
aws ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$instance_id" \
  --document-name AWS-RunShellScript \
  --comment halloween-party-deploy \
  --parameters "commands=<json-array-of-shell-commands>" \
  --query 'Command.CommandId' \
  --output text
```

Poll command status:

```bash
aws ssm get-command-invocation \
  --region "$AWS_REGION" \
  --command-id "$command_id" \
  --instance-id "$instance_id"
```

## EC2 Commands Intent

The SSM command should perform the same work a human would do over SSH, but
without opening SSH publicly.

High-level script intent on each API EC2:

```bash
set -euo pipefail

APP_USER=ec2-user
APP_DIR=/home/ec2-user/halloween-karaoke-costume-contest
VENV_DIR="${APP_DIR}/.venv"
SERVICE_NAME=halloween-party

sudo -u "$APP_USER" git -C "$APP_DIR" fetch origin "$DEPLOY_REF" || true
if [ ! -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git clone --branch "$DEPLOY_REF" <gitlab-repo-url> "$APP_DIR"
else
  sudo -u "$APP_USER" git -C "$APP_DIR" checkout "$DEPLOY_SHA"
fi

sudo -u "$APP_USER" python3.11 -m venv "$VENV_DIR"
sudo -u "$APP_USER" "$VENV_DIR/bin/python" -m pip install --upgrade pip wheel
sudo -u "$APP_USER" "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

sudo install -d -o "$APP_USER" -g "$APP_USER" /var/lib/halloween-party
sudo install -m 0644 "$APP_DIR/deploy/halloween-party.service" /etc/systemd/system/halloween-party.service
sudo install -m 0644 "$APP_DIR/deploy/nginx-halloween.conf" /etc/nginx/conf.d/halloween.conf

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo nginx -t
sudo systemctl reload nginx

curl -fsS http://127.0.0.1:8081/live-display >/dev/null
curl -fsS -H 'Host: tnq-halloween.com' http://127.0.0.1/live-display >/dev/null
```

The exact commands should be represented as a JSON array for
`aws ssm send-command`.

## GitLab Repository Authentication

Choose one:

- Preferred: deploy with a GitLab deploy token stored in Vault and fetched by
  the EC2 instance during the SSM command.
- Alternative: use a read-only deploy key already present on the EC2 instance.
- Avoid storing a GitLab token directly in GitLab CI if the token is only needed
  by EC2.

If using Vault for the GitLab token, create:

```text
appsecrets/halloween_gitlab
```

Recommended keys:

```json
{
  "username": "deploy-token-user-or-oauth2",
  "token": "<gitlab-deploy-token>",
  "repo_url": "https://gitlab.com/<group>/<project>.git"
}
```

The SSM script can use the Vault CLI or the app's Vault helper pattern to fetch
that token on EC2. Do not print the token.

## Systemd Unit Requirements

The deployed service should run gunicorn locally:

```ini
[Unit]
Description=Halloween Karaoke Costume Contest
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/halloween-karaoke-costume-contest
Environment=PYTHONUNBUFFERED=1
Environment=APP_ENV=production
Environment=VAULT_ADDR=http://172.31.118.0:8200
Environment=VAULT_AUTH_METHOD=aws
Environment=VAULT_AWS_AUTH_ROLE=goodvines-api
Environment=AWS_REGION=us-east-1
ExecStart=/home/ec2-user/halloween-karaoke-costume-contest/.venv/bin/gunicorn --workers 1 --threads 8 --bind 127.0.0.1:8081 main:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## nginx Requirements

nginx should run both apps in parallel:

```text
appg-v.com        -> GoodVines API local port
tnq-halloween.com -> Halloween app at 127.0.0.1:8081
```

The Halloween server block must include an SSE-friendly config for
`/api/display-updates`:

```nginx
location /api/display-updates {
    proxy_pass http://127.0.0.1:8081;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Vault Provisioning by AWS CLI and SSM

Provisioning Vault secrets may require operator/root Vault access and should be
handled carefully.

Preferred approach:

- Use SSM to open an operator command session on the services EC2.
- Run Vault commands on the services EC2 with an appropriate Vault token.
- Store only generated Halloween secrets in Vault.

Example secret paths:

```bash
vault kv put appsecrets/halloween_app \
  secret_key='<generated-flask-secret>' \
  admin_password='<generated-admin-password>'

vault kv put appsecrets/halloween_redis \
  username='default' \
  password='<existing-or-dedicated-redis-password>' \
  host='172.31.118.0' \
  port='6379' \
  db='1' \
  prefix='halloween'

vault kv put appsecrets/halloween_gitlab \
  username='<deploy-token-username>' \
  token='<gitlab-deploy-token>' \
  repo_url='https://gitlab.com/<group>/<project>.git'
```

GitLab CI should not hold the Vault root token.

## Pipeline Skeleton

Suggested `.gitlab-ci.yml` shape:

```yaml
stages:
  - validate
  - deploy

validate:
  image: python:3.11
  stage: validate
  script:
    - python -m pip install --upgrade pip
    - python -m pip install -r requirements.txt
    - python -m py_compile main.py

deploy_production:
  image: amazon/aws-cli:2
  stage: deploy
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  script:
    - aws --version
    - ./deploy/gitlab_deploy_via_ssm.sh
```

Keep the complex SSM JSON construction in a script checked into the repo rather
than embedding it all in YAML.

## Verification

After deploy:

```bash
curl -fsS https://tnq-halloween.com/live-display
curl -fsS https://tnq-halloween.com/api/display-data
```

From EC2 through SSM:

```bash
systemctl status halloween-party --no-pager
journalctl -u halloween-party -n 100 --no-pager
curl -fsS http://127.0.0.1:8081/live-display
```

Redis validation:

```bash
redis-cli -h 172.31.118.0 -p 6379 -n 1 -a '<password>' --no-auth-warning ping
redis-cli -h 172.31.118.0 -p 6379 -n 1 -a '<password>' --no-auth-warning keys 'halloween:*'
```

## Failure Boundaries

- If GitLab cannot reach AWS APIs, deployment fails before touching EC2.
- If SSM is offline on an API instance, do not attempt SSH fallback unless an
  operator explicitly chooses it.
- If Vault is unreachable from EC2, app startup should fail rather than using
  unsafe default production secrets.
- If Redis is unreachable, the app should fail closed for state mutations and
  show a friendly error.
