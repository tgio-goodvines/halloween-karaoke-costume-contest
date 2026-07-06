# AWS Implementation Checklist

This checklist turns the hosting plan into implementation steps for deploying
the Halloween Flask app on the existing GoodVines EC2/ALB stack.

## Phase 1: Prepare the App

- Add `gunicorn` to `requirements.txt`.
- Change local development behavior so `python main.py` does not require port
  `80`; use `PORT` from the environment with a default like `8081`.
- Keep production startup outside `main.py`; systemd should run gunicorn.
- Load app secrets from Vault using AWS IAM auth.
- Add admin authentication before exposing `/admin`.
- Add Redis-backed persistence before event use.

Recommended minimum persistence:

- Store event state in Redis DB `1` at key `halloween:state`.
- Use key prefix `halloween:` for every key.
- Persist:
  - `costume_signups`
  - `karaoke_signups`
  - `costume_votes`
  - `registered_users`
  - `submitted_costume_votes`
  - `live_display_override`
  - `contest_state`
  - `karaoke_state`
  - `display_update_version`
- Load state from Redis at process startup.
- Save state to Redis after every mutation that currently changes module-level globals.
- Use a Redis lock for state mutations.
- Publish display updates through Redis pub/sub.
- Keep one gunicorn worker until shared persistence or locking is mature.

## Phase 2: Add EC2 Runtime Files

Add deploy/runtime files to this repo or to the GoodVines deployment automation:

- `deploy/halloween-party.service`
- `deploy/nginx-halloween.conf` or an update to the existing nginx config
- Optional install script such as `deploy/install_halloween_app.sh`

Systemd unit intent:

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

Operational notes:

- App and Redis secrets should come from Vault using AWS IAM auth.
- Keep `workers=1` while the app uses in-process globals.
- If using SSE heavily, keep nginx buffering disabled for `/api/display-updates`.

## Phase 3: Configure nginx Host Routing

Update nginx on the API EC2 instance so hostnames split correctly:

- Existing GoodVines hostname routes stay pointed to the current API service.
- `tnq-halloween.com` and `www.tnq-halloween.com` route to
  `http://127.0.0.1:8081`.
- Add a specific location for `/api/display-updates` with:
  - `proxy_http_version 1.1`
  - `proxy_buffering off`
  - `proxy_cache off`
  - long `proxy_read_timeout`

Validation commands on EC2:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -fsS -H 'Host: tnq-halloween.com' http://127.0.0.1/
curl -fsS -H 'Host: appg-v.com' http://127.0.0.1/health
```

## Phase 4: Configure AWS DNS and TLS

Route53:

- Domain registration requested through Route53 Domains for `tnq-halloween.com`.
  - Operation ID: `1e3da58e-f0c6-4bf7-a6e5-db7a2fcb71c9`
  - Registration status at implementation time: `SUCCESSFUL`
  - Domain status: `ACTIVE`
  - Auto-renew: enabled
  - Privacy protection: enabled for registrant, admin, and tech contacts
  - Expiration date: `2027-07-05`
- Hosted zone created for `tnq-halloween.com`.
  - Hosted zone ID: `Z07720593G0YFC0VM1DDL`
  - Nameservers:
    - `ns-1539.awsdns-00.co.uk`
    - `ns-452.awsdns-56.com`
    - `ns-1451.awsdns-53.org`
    - `ns-699.awsdns-23.net`
- `A` alias for `tnq-halloween.com` points to `goodvines-api-alb`.
- `A` alias for `www.tnq-halloween.com` points to `goodvines-api-alb`.

ACM:

- Public certificate requested in `us-east-1`.
  - Certificate ARN: `arn:aws:acm:us-east-1:152923357640:certificate/2fcce000-b07d-48ae-91ae-36e691f131ea`
  - Domains: `tnq-halloween.com`, `www.tnq-halloween.com`
- DNS validation records added to Route53.
- Certificate status: `ISSUED`.
- TLS validation confirmed for:
  - `https://tnq-halloween.com`
  - `https://www.tnq-halloween.com`

ALB:

- New certificate attached to the existing HTTPS listener:
  `arn:aws:elasticloadbalancing:us-east-1:152923357640:listener/app/goodvines-api-alb/44b2be9b89d688bf/342054c40ca2eb4c`
  - Halloween certificate ARN: `arn:aws:acm:us-east-1:152923357640:certificate/2fcce000-b07d-48ae-91ae-36e691f131ea`
  - Existing `appg-v.com` certificate remains the default certificate.
- Explicit host-header rules were added for `tnq-halloween.com` and
  `www.tnq-halloween.com` on both HTTP and HTTPS listeners.
  - HTTP listener rule ARN: `arn:aws:elasticloadbalancing:us-east-1:152923357640:listener-rule/app/goodvines-api-alb/44b2be9b89d688bf/0213bfadc84beed1/33bef507e90719e4`
  - HTTPS listener rule ARN: `arn:aws:elasticloadbalancing:us-east-1:152923357640:listener-rule/app/goodvines-api-alb/44b2be9b89d688bf/342054c40ca2eb4c/1810bd67340f266c`
- No new target group is required for the nginx host-routing plan; both rules
  forward to `goodvines-api-http`.

Suggested AWS validation commands:

```bash
aws route53 list-hosted-zones
aws acm describe-certificate --region us-east-1 --certificate-arn <new-cert-arn>
aws elbv2 describe-listeners --region us-east-1 --load-balancer-arn arn:aws:elasticloadbalancing:us-east-1:152923357640:loadbalancer/app/goodvines-api-alb/44b2be9b89d688bf
```

## Phase 5: Deploy and Smoke Test

On the EC2 API node:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now halloween-party
sudo systemctl status halloween-party --no-pager
curl -fsS http://127.0.0.1:8081/live-display
curl -fsS -H 'Host: tnq-halloween.com' http://127.0.0.1/live-display
```

From the public internet:

```bash
curl -I https://tnq-halloween.com/live-display
curl -I https://www.tnq-halloween.com/live-display
```

Manual browser checks:

- `/` redirects to `/live-display`.
- `/halloween/login` accepts attendee check-in.
- `/costume-signup` can create a costume entry.
- `/karaoke-signup` can create a karaoke entry.
- `/admin` is password protected.
- Admin changes update `/live-display`.
- SSE updates work through `/api/display-updates`.

## Phase 6: Event-Day Operating Notes

Before guests arrive:

- Confirm the ASG has exactly one live API target unless shared persistence has
  been implemented.
- Confirm the Halloween app service is running.
- Confirm Redis DB `1` is reachable and `halloween:state` can be read/written.
- Confirm `/admin` password works.
- Open `/live-display` on the TV/projector.
- Submit one test costume and one test karaoke entry.
- Remove test data if needed.

During the event:

- Avoid restarting the EC2 instance.
- Avoid deploying GoodVines changes that reload nginx or restart all local app
  services unless necessary.
- Avoid scaling the ASG above one node unless the Halloween app has shared
  persistence and routing behavior has been tested.

After the event:

- Export `halloween:state` from Redis if results should be preserved.
- Disable the Halloween systemd service if the app should go offline.
- Optionally leave DNS/cert in place for future years, or remove the hosted zone
  if avoiding ongoing Route53 hosted zone cost matters.
