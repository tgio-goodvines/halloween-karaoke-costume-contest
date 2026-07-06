# AWS Existing Infrastructure Hosting Plan

## Goal

Host the Halloween karaoke and costume contest Flask app at a new domain such as
`tnq-halloween.com` with the lowest practical incremental AWS cost, while
reusing the existing GoodVines AWS infrastructure.

## Recommended Low-Cost Architecture

Reuse the current GoodVines public ALB and API EC2 Auto Scaling Group instead of
creating a new load balancer or new always-on instance.

Current infrastructure context from the GoodVines AWS inventory:

- AWS account: `152923357640`
- Region: `us-east-1`
- Existing ALB: `goodvines-api-alb`
- ALB ARN: `arn:aws:elasticloadbalancing:us-east-1:152923357640:loadbalancer/app/goodvines-api-alb/44b2be9b89d688bf`
- ALB DNS: `goodvines-api-alb-1034341134.us-east-1.elb.amazonaws.com`
- Existing target group: `goodvines-api-http`
- Target group ARN: `arn:aws:elasticloadbalancing:us-east-1:152923357640:targetgroup/goodvines-api-http/c0e4914b65049592`
- API ASG: `goodvines-api-asg`
- Current steady state: one `t3.micro` API node
- Current API instance at inventory time: `i-0573ac280edafdfe0`
- Current API private IP at inventory time: `172.31.138.202`
- API subnet: `subnet-0170cfe7ef10f70f9`
- API security group: `sg-03be330cf64f419b3`

## Routing Model

Use host-based routing at nginx on the EC2 instance, with the existing ALB still
forwarding HTTP/HTTPS to the API node on port `80`.

Live nginx status verified through AWS SSM:

- API instance `i-0573ac280edafdfe0` has nginx installed at `/usr/sbin/nginx`.
- nginx version on the API instance: `nginx/1.28.3`.
- nginx service state on the API instance: `enabled` and `active`.
- nginx listens on port `80` for IPv4 and IPv6.
- Services instance `i-09308adf7f1d6d0cd` does not have nginx installed.

The ALB does not need a separate target group if nginx handles the host split:

- `appg-v.com` and `www.appg-v.com` continue to route to the GoodVines API.
- `tnq-halloween.com` and `www.tnq-halloween.com` route to the Halloween Flask
  app running locally on the same EC2 instance.

Expected local process layout on the API node:

- GoodVines API: existing service, proxied by nginx to its current local port.
- Halloween app: new service, proxied by nginx to `127.0.0.1:8081`.

Example nginx intent:

```nginx
server {
    listen 80;
    server_name appg-v.com www.appg-v.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name tnq-halloween.com www.tnq-halloween.com;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

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
}
```

The SSE-specific block matters because `/api/display-updates` streams live
display updates.

## DNS and Certificate Plan

1. Register or delegate `tnq-halloween.com`.
2. Create a Route53 public hosted zone for `tnq-halloween.com`.
3. Point the registrar nameservers at the Route53 hosted zone.
4. Request an ACM certificate in `us-east-1` for:
   - `tnq-halloween.com`
   - `www.tnq-halloween.com`
5. Add ACM DNS validation records to the hosted zone.
6. Attach the issued certificate to the existing ALB HTTPS listener using SNI.
7. Create Route53 records:
   - `tnq-halloween.com A` alias to `goodvines-api-alb`
   - `www.tnq-halloween.com A` alias to `goodvines-api-alb`

## Cost Expectations

This plan is the lowest incremental AWS cost if the existing ALB and EC2 node
remain online for GoodVines anyway.

Expected incremental costs:

- Domain registration: annual registrar cost for `tnq-halloween.com`.
- Route53 hosted zone: roughly the hosted-zone monthly charge.
- Route53 alias queries to the ALB: no additional query charge for ALB alias
  records.
- ACM public certificate attached to ALB: no additional ACM certificate charge
  for a non-exported public cert used with integrated AWS services.
- ALB and EC2: no new fixed infrastructure if reusing the existing ALB and API
  EC2 capacity.
- Traffic: small marginal ALB LCU/data-transfer cost if party traffic is low.

Avoid these for the first implementation:

- A second ALB. That adds a meaningful fixed monthly load balancer cost.
- A separate always-on EC2 instance. That adds compute, EBS, snapshot, and patch
  surface.
- ECS/Fargate for this tiny app unless containerization becomes a broader goal.

## Fit and Constraints

This app is currently a single-process Flask app with in-memory state. Running
it on the existing single API node is cost-effective and simple, but there are
important operational constraints:

- If the process restarts, current party data is lost unless persistence is
  added.
- If the ASG replaces the API node, current party data is lost unless persistence
  is externalized to Redis.
- If the ASG temporarily scales to more than one node, in-memory app state will
  diverge between nodes unless Redis-backed shared persistence is implemented.
- `/admin` currently has no authentication.
- The app should not be run with Flask debug mode in production.
- The app should not bind directly to port `80`; run behind nginx on an
  unprivileged localhost port.

## Recommended Production Shape

- Run the app with gunicorn:

```bash
gunicorn --workers 1 --threads 8 --bind 127.0.0.1:8081 main:app
```

- Use `workers=1` while state remains in-process. Multiple workers would split
  state between worker processes.
- Use a systemd unit named something like `halloween-party.service`.
- Add Redis-backed persistence before the event.
- Load app, Redis, and deployment secrets from Vault using AWS IAM auth.
- Add admin authentication before exposing the site.
- Keep raw app secrets out of systemd and GitLab CI variables.

## Alternative Architectures

### S3 and CloudFront

This would be cheaper for a purely static website, but it does not fit the
current app because the app has Flask sessions, admin mutations, voting,
server-side state, and SSE live-display updates.

### Separate EC2 Instance

This isolates the party app from GoodVines but adds fixed monthly cost and more
operations work. Use only if isolation is more important than lowest cost.

### App Runner, ECS, or Lambda

These can be clean production options, but they are not the cheapest or simplest
incremental path given the existing ALB/EC2 infrastructure and the app's
short-lived event use case.
