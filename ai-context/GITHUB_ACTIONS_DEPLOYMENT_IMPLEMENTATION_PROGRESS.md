# GitHub Actions Deployment Implementation Progress

## Objective

Implement deployment from GitHub Actions to the existing GoodVines API EC2
hosts. Merges to `main` should deploy the exact merged commit through AWS CLI
and SSM.

## Guardrails

- No S3, ECS, ECR, CodeDeploy, or new hosting infrastructure.
- Do not restart or modify GoodVines services.
- Do not edit GoodVines source directories.
- Do not change ALB, Route53, ACM, ASG capacity, or target group defaults during
  app deploys.
- Halloween runtime secrets must come from Vault on EC2.
- Halloween state must use Redis DB `1` with the `halloween:` key prefix.
- Halloween must not use SQL.

## Repository Facts

- Local repo: `/Users/tgionfriddo/halloween-karaoke-costume-contest`
- Branch: `main`
- GitHub remote: `git@github.com:tgio-goodvines/halloween-karaoke-costume-contest.git`
- Flask entrypoint: `main:app`
- Production local port: `127.0.0.1:8081`
- Halloween health API: `/health`
- Public domain: `tnq-halloween.com`
- GoodVines health guardrail:
  `curl -fsS -H 'Host: appg-v.com' http://127.0.0.1/health`

## Status

- GitHub Actions deployment plan exists:
  `ai-context/GITHUB_ACTIONS_EC2_DEPLOYMENT_PLAN.md`.
- GitLab deployment context is marked legacy.
- Added `.github/workflows/deploy-aws.yml`.
- Added `deploy/ec2_deploy_from_github.sh`.
- Added `deploy/start_halloween.sh`.
- Added `deploy/halloween-party.service`.
- Added `deploy/nginx-halloween.conf`.
- Added `deploy/validate_goodvines_health.sh`.
- Added `gunicorn` to `requirements.txt`.
- Local bash syntax validation passed for deploy scripts.
- Local no-write Python syntax validation passed for `main.py`.
- GitHub Actions YAML parsed successfully with Ruby YAML.
- `git diff --check` passed.
- Local pytest run was not completed because the available local Python did not
  have `pytest` installed; the GitHub Actions workflow installs `pytest` before
  running tests.
- Stored the provided fine-grained GitHub token in Vault path
  `appsecrets/halloween_github.token`.
- Stored `appsecrets/halloween_github.repo_url` as the HTTPS GitHub repo URL and
  `appsecrets/halloween_github.username` as `x-access-token`.
- Verified the API EC2 can read the GitHub token secret through Vault AWS IAM
  auth.
- Verified the API EC2 can use the Vault-stored token with `git ls-remote`
  against the Halloween repo without printing the token.
- Updated `deploy/ec2_deploy_from_github.sh` to prefer
  `appsecrets/halloween_github.token` over SSH deploy-key auth.
- Updated `.github/workflows/deploy-aws.yml` default repo URL to HTTPS.
- Created AWS IAM OIDC provider:
  `arn:aws:iam::152923357640:oidc-provider/token.actions.githubusercontent.com`.
- Created AWS IAM role:
  `arn:aws:iam::152923357640:role/HalloweenGithubActionsDeployRole`.
- Attached inline policy `HalloweenSsmDeployPolicy` allowing ASG/target-health
  reads plus SSM send/read operations needed for deploy.
- Set GitHub repository variable `AWS_ROLE_TO_ASSUME` to the Halloween deploy
  role ARN using the Vault-stored GitHub token.
- Created Halloween runtime Vault secrets:
  - `appsecrets/halloween_app`
  - `appsecrets/halloween_redis`
- `appsecrets/halloween_app` must include `secret_key` and `admin_password`;
  attendee account passwords are stored as hashes in Redis app state.
- Verified the API EC2 can read required fields from both Halloween runtime
  secret paths through Vault AWS IAM auth.

## External Setup Required

- GitHub Actions AWS access is configured through OIDC with
  `AWS_ROLE_TO_ASSUME=arn:aws:iam::152923357640:role/HalloweenGithubActionsDeployRole`.
- The workflow still supports the older `AWS_ACCESS_KEY_ID` and
  `AWS_SECRET_ACCESS_KEY` secrets pattern as a fallback if OIDC is removed.
- No GitHub deploy key registration is needed now; deployment uses the
  Vault-stored fine-grained token over HTTPS.

## Scaling and Recovery Note

API ASG replacement nodes now bootstrap Halloween from launch-template
user-data.

- Launch template: `goodvines-api-lt`
- Launch template ID: `lt-0f899847971a77126`
- Halloween bootstrap version: `2`
- ASG `goodvines-api-asg` is pinned to launch template version `2`.
- Version description:
  `goodvines api bootstrap with halloween app install`

The version 2 user-data keeps the existing GoodVines bootstrap flow, then runs
`install_halloween_app` after `start_services`. The Halloween bootstrap:

- creates a dedicated `halloween` system user/group,
- reads `appsecrets/halloween_github` from Vault via AWS IAM auth,
- clones/fetches the Halloween repo over HTTPS with the Vault-stored token,
- installs a release under `/opt/halloween/releases/<sha>`,
- points `/opt/halloween/current` at that release,
- installs `halloween-party.service`,
- installs `/etc/nginx/conf.d/halloween.conf`,
- restarts only `halloween-party`,
- validates nginx before reload,
- reloads nginx,
- verifies `Host: tnq-halloween.com` routes to Halloween, and
- verifies `Host: appg-v.com` still routes to GoodVines health.

Event state persists in Redis DB `1` with the `halloween:` prefix. Replacement
nodes should install the app automatically, while the event state survives in
Redis.

Important nuance: launch-template bootstrap fetches the current Halloween
`main` branch at instance boot time. The GitHub Actions workflow still deploys
the exact merged commit SHA for normal deployments.

Post-update verification on 2026-07-06:

- ASG `goodvines-api-asg` is pinned to launch template version `2`.
- Current instance `i-0573ac280edafdfe0` remained `InService` and `Healthy`.
- `https://appg-v.com/health` returned `{"online":"true"}`.
- `https://tnq-halloween.com/live-display` returned HTTP `200`.

## First Deployment Result

- Initial pushed workflow run `28765387717` failed in validation because pytest
  could not import `main`.
- Follow-up workflow run `28765460043` passed validation but failed the EC2
  deploy because the post-reload nginx host-routing smoke test was too eager.
- Final workflow run `28765586567` succeeded after adding a retry around the
  nginx host-routing smoke test.
- Deployed commit:
  `9a42b422e46216c456c456689eebe2ff7767d6c6`.
- EC2 verification on `i-0573ac280edafdfe0` confirmed:
  - `halloween-party` is active.
  - `nginx` is active.
  - `/opt/halloween/current` points to
    `/opt/halloween/releases/9a42b422e46216c456c456689eebe2ff7767d6c6`.
  - `http://127.0.0.1:8081/live-display` returns successfully.
  - `Host: tnq-halloween.com` through local nginx returns successfully.
  - `Host: appg-v.com` through local nginx returns successfully.
- Public smoke tests confirmed:
  - `https://tnq-halloween.com/live-display` returns HTTP `200`.
  - `https://www.tnq-halloween.com/live-display` returns HTTP `200`.
  - `https://appg-v.com/health` returns `{"online":"true"}`.

## Latest Repository Updates

After the successful deployment, the repo received follow-up commits on `main`
to document and harden deployment knowledge:

- `2d32704` added the GitHub Actions EC2 deployment workflow and deploy scripts.
- `1e39b66` fixed the workflow test import path with `pytest.ini`.
- `9a42b42` added retry behavior around the nginx host-routing smoke test.
- `c765134` recorded the successful public deployment result with `[skip ci]`.
- `504a752` documented launch template version `2` Halloween bootstrap behavior
  with `[skip ci]`.

Pending local update:

- Added a real Halloween `/health` JSON API that pings Redis and returns `503`
  in production when Redis is unreachable.
- Updated EC2 deploy and GitHub Actions public smoke checks to probe Halloween
  `/health` instead of `/live-display`, while preserving the GoodVines
  `appg-v.com/health` guardrail.

Current durable deployment context should be read from this file,
`ai-context/GITHUB_ACTIONS_EC2_DEPLOYMENT_PLAN.md`, and
`ai-context/AWS_LAUNCH_TEMPLATE_HALLOWEEN_BOOTSTRAP.md`.
