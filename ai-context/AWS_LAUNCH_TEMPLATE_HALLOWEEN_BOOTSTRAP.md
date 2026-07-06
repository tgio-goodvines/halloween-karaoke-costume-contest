# AWS Launch Template Halloween Bootstrap

## Purpose

The Halloween app must survive API EC2 replacement and ASG scale-out without
requiring a manual deployment immediately after each new instance comes online.
To support that, the GoodVines API launch template now bootstraps Halloween
after the normal GoodVines user-data flow starts the existing services.

## AWS Resources

- ASG: `goodvines-api-asg`
- Launch template: `goodvines-api-lt`
- Launch template ID: `lt-0f899847971a77126`
- Active ASG launch template version: `2`
- Version description:
  `goodvines api bootstrap with halloween app install`

The ASG is pinned to explicit version `2`. It is not relying on `$Latest`.

## Bootstrap Order

Launch template version `2` preserves the existing GoodVines API bootstrap and
adds `install_halloween_app` after `start_services`.

The Halloween bootstrap:

- creates a dedicated `halloween` system user/group,
- creates `/opt/halloween`, `/opt/halloween/app`,
  `/opt/halloween/releases`, and `/var/log/halloween-party`,
- authenticates to Vault using AWS IAM auth,
- reads the GitHub token and repo URL from `appsecrets/halloween_github`,
- clones/fetches the Halloween repo over HTTPS using a temporary `GIT_ASKPASS`,
- checks out the current `main` branch at boot time,
- creates `/opt/halloween/releases/<sha>` from `git archive`,
- creates a Python venv and installs `requirements.txt`,
- installs `halloween-party.service`,
- installs `/etc/nginx/conf.d/halloween.conf`,
- updates `/opt/halloween/current`,
- starts/restarts only `halloween-party`,
- verifies Halloween locally on `127.0.0.1:8081/health`,
- runs `nginx -t` before reloading nginx,
- reloads nginx, and
- checks both Halloween host routing and GoodVines host routing locally.

## GoodVines Isolation

The bootstrap does not modify or restart the GoodVines application service.
The only shared component touched is nginx, and nginx is reloaded only after
`nginx -t` succeeds.

Before the bootstrap completes, it verifies:

- `Host: tnq-halloween.com` routes to Halloween locally, and
- `Host: appg-v.com` still returns GoodVines health locally.

## Runtime State

Halloween does not use SQL. Event state is stored in Redis DB `1` with the
`halloween:` key prefix, so EC2 replacement should not erase Halloween event
data.

## Deployment Relationship

Launch-template bootstrap installs the current Halloween `main` branch when a
new API instance boots. Normal application updates still come from GitHub
Actions, which deploys the exact merged commit SHA to currently running API
instances through SSM.

## Verification Recorded

After pinning `goodvines-api-asg` to launch template version `2`:

- existing API instance `i-0573ac280edafdfe0` remained `InService` and
  `Healthy`,
- target group `goodvines-api-http` remained `healthy`,
- `https://appg-v.com/health` returned `{"online":"true"}`, and
- `https://tnq-halloween.com/live-display` returned HTTP `200`.

No forced instance replacement was performed during this update. That avoided
unnecessary risk to the live GoodVines API while still ensuring future
replacement instances use the Halloween-aware launch template.
