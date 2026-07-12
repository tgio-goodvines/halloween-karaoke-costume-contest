# File Inventory

## Tracked Source Files

| File | Purpose |
| --- | --- |
| `main.py` | Flask app entrypoint, route definitions, Redis-backed state cache/serialization, independent RSVP list, RSVP party-code validation, RSVP confirmation/update emails, RSVP calendar `.ics` generation, RSVP/registered-user email recipient collection, SES account welcome/update/reset email sending, password reset token lifecycle, food/drink menu and drink ordering, specialty drink limits, drink history/reorder, bartender tip settings, bartender roles/order queue, editable party details/map address, live-display WiFi settings, role-based session auth, configurable public landing, CSRF, admin actions, voting logic, scoreboard helpers, live-display JSON/SSE APIs. |
| `requirements.txt` | Python dependency declaration; includes Flask 3.x, redis-py for Redis state, boto3 for SES email, and gunicorn for production. |
| `.github/workflows/deploy-aws.yml` | GitHub Actions workflow that validates the app and deploys merged `main` commits to the existing API EC2 ASG through AWS CLI and SSM. |
| `deploy/ec2_deploy_from_github.sh` | SSM-run EC2 deployment script that fetches the Vault-stored GitHub deploy key, checks out the exact commit SHA, installs the Halloween release, restarts only `halloween-party`, validates nginx, and checks GoodVines health. |
| `deploy/start_halloween.sh` | systemd start wrapper that authenticates to Vault using AWS IAM auth, exports Halloween app/Redis/email secrets, and execs gunicorn. |
| `deploy/halloween-party.service` | systemd unit for running the Halloween Flask app through gunicorn on `127.0.0.1:8081`. |
| `deploy/nginx-halloween.conf` | nginx host-routing config for `tnq-halloween.com` and `www.tnq-halloween.com`, including SSE-friendly proxy settings. |
| `deploy/validate_goodvines_health.sh` | Local EC2 health helper that verifies the existing GoodVines app through nginx using the `appg-v.com` Host header. |
| `.env.example` | Example local Redis environment values for the existing `127.0.0.1:6379` ACL-protected Redis, DB `1`, the `halloween` prefix, live-display WiFi defaults, and Halloween email update settings. |
| `tests/test_redis_state.py` | Unit tests for Redis-backed state serialization, load/save behavior, route persistence, voting, admin reorder alignment, food/drink ordering, specialty drink limits, drink history/reorder, bartender tipping, bartender priority sorting, bartender roles/order status transitions, display update publishing, and JSON exports using an in-memory Redis fake. |
| `static/styles.css` | Shared dark lab-terminal Halloween design system for attendee/admin pages, including scanline texture, serif headings, mono controls, square glowing panels, header menu, single logout action, menu cards, order cards, bartender tip disclosures, and bartender queue. |
| `static/bartender.js` | Bartender queue polling refresh that fetches the authenticated `/api/bartender-queue` fragment and swaps it in when the queue version changes. |
| `static/display.css` | Dedicated large-format live-display styles aligned with the dark lab-terminal design system, including square display cards, event override cards, top-layer drink-ready notices, CTA layout, scoreboard layout, and karaoke display panels. |
| `static/display.js` | Live-display client logic: card rotation, API polling, SSE reconnects, event override rendering, temporary notice rendering with optional images, scoreboard rendering, karaoke countdown and panel rotation. |
| `static/slides.js` | Dashboard event-highlight slide rotation. |
| `templates/base.html` | Shared attendee/admin layout with header menu navigation, signed-in identity, single logout action, footer, and script block. |
| `templates/index.html` | Attendee dashboard for `/party`: contest banners, ready drink notices, recent drink order cards, welcome callout, slides, costume and karaoke summaries. |
| `templates/menu.html` | Attendee food/drink menu for `/party/menu`, including menu images, availability, specialty/standard badges, drink ordering, and recent order statuses. |
| `templates/drink_history.html` | Attendee full drink order history for `/party/drink-history`, including account-scoped order records, reorder controls, and per-order bartender tip QR/payment disclosure. |
| `templates/bartender.html` | Bartender/admin page shell for `/bartender`, with messages and the live-refresh queue container. |
| `templates/_bartender_queue.html` | Shared bartender queue fragment with drink images/placeholders, specialty sequence and extra-request notes, recipe reference, status transition forms, and completed order history. |
| `templates/rsvp.html` | Public RSVP landing page with RSVP prompt, party-code field on the RSVP form, party details, Google Maps embed/directions button, newest-to-oldest update cards, confirmation state, and optional portal account links. |
| `templates/halloween_login.html` | Public attendee account sign-in form. |
| `templates/halloween_register.html` | Public attendee account registration form. |
| `templates/email/rsvp_update.html` | Dark lab-terminal styled HTML email body for admin-posted RSVP update notifications. |
| `templates/email/rsvp_confirmation.html` | Dark lab-terminal styled HTML email body for RSVP confirmation messages with party details and calendar links. |
| `templates/email/account_welcome.html` | Dark lab-terminal styled HTML email body for party account creation welcome messages. |
| `templates/email/drink_order_placed.html` | Dark lab-terminal styled HTML email body for drink order confirmations with estimated ready time. |
| `templates/email/drink_order_ready.html` | Dark lab-terminal styled HTML email body for notifying attendees their drink is ready. |
| `templates/password_reset_request.html` | Email entry form for requesting a party account password reset link. |
| `templates/password_reset_form.html` | New-password form for valid password reset links and invalid/expired link feedback. |
| `templates/email/password_reset.html` | Dark lab-terminal styled HTML email body for one-time password reset links. |
| `templates/email/_components.html` | Shared inline-safe HTML email macros for the refined lab-terminal shell, buttons, and detail tables used by generated email templates. |
| `templates/costume_signup.html` | Costume signup form and submitted costume list. |
| `templates/karaoke_signup.html` | Karaoke signup form and submitted karaoke lineup. |
| `templates/costume_voting.html` | Costume voting ballot and one-vote confirmation state. |
| `templates/admin_login.html` | Admin password form for `/admin/login`. |
| `templates/admin.html` | Admin dashboard for public landing, party-code controls, live-display WiFi settings, RSVP list, party detail/map address editing, RSVP update posting/removal, food/drink menu CRUD with images/recipes/specialty/orderable controls, bartender tip settings, bartender role assignment, entry CRUD/reordering, contest controls, vote tally, winner state, and karaoke launch. |
| `templates/display.html` | Standalone full-screen live-display page and initial JSON bootstrap, including event override markup and top-layer notice image markup for drink-ready cards. |

## Untracked Local Files Present During Review

These files are present locally but not tracked by Git at the time this context was created:

| File | Purpose |
| --- | --- |
| `.python-version` | Local Python version pin, `3.11.9`. |
| `.DS_Store` | macOS folder metadata; binary, not app source. |
| `.idea/.gitignore` | PyCharm default ignore entries for shelf and workspace metadata. |
| `.idea/halloween-karaoke-costume-contest.iml` | PyCharm module file pointing at Python 3.11 SDK `venv-halloween`. |
| `.idea/misc.xml` | PyCharm project root manager and SDK metadata. |
| `.idea/modules.xml` | PyCharm module registration. |
| `.idea/vcs.xml` | PyCharm Git mapping. |
| `.idea/workspace.xml` | PyCharm local workspace/run/debug metadata, including a `main.py` run config and breakpoint. |
| `.idea/inspectionProfiles/Project_Default.xml` | PyCharm inspection profile, including ignored PEP8 naming rule N801. |
| `.idea/inspectionProfiles/profiles_settings.xml` | PyCharm inspection profile settings. |

## Generated Context Files

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Future-agent entry point with high-signal repo notes. |
| `ai-context/PROJECT_OVERVIEW.md` | Durable summary of app purpose, runtime, flows, state model, and design. |
| `ai-context/UI_UX_DESIGN_SYSTEM.md` | Durable current UI/UX visual design system notes for the lab-terminal Halloween style, palette, typography, surfaces, controls, and live-display alignment. |
| `ai-context/FEATURES.md` | Durable catalog of supported attendee, admin, contest, karaoke, display, and styling features. |
| `ai-context/ARCHITECTURE.md` | Durable route map, data flow, frontend behavior, constraints, and extension guidance. |
| `ai-context/FILE_INVENTORY.md` | Durable file-by-file inventory. |
| `ai-context/FOOD_DRINK_BAR_FEATURE.md` | Durable implementation notes for menu items, drink orders, bartender role, emails, estimates, and live-display ready overrides. |
| `ai-context/AWS_EXISTING_INFRA_HOSTING_PLAN.md` | Hosting plan for reusing the existing GoodVines ALB/EC2 infrastructure for `tnq-halloween.com`. |
| `ai-context/AWS_IMPLEMENTATION_CHECKLIST.md` | Step-by-step AWS, nginx, systemd, DNS, TLS, deploy, and smoke-test checklist. |
| `ai-context/AWS_LAUNCH_TEMPLATE_HALLOWEEN_BOOTSTRAP.md` | Launch template version 2 bootstrap details for installing Halloween automatically on replacement API EC2 instances. |
| `ai-context/APP_HARDENING_FOR_AWS.md` | App changes needed before public AWS exposure, including gunicorn, admin auth, persistence, and secrets. |
| `ai-context/NO_SQL_DATA_POLICY.md` | Explicit policy that Halloween must not use SQL and should persist state in Redis. |
| `ai-context/REDIS_CONNECTION_REQUIREMENTS.md` | Redis connection requirements for using the existing GoodVines services EC2 Redis instance without key collisions. |
| `ai-context/REDIS_STATE_DESIGN.md` | Redis key, locking, pub/sub, backup, and persistence design for Halloween event state. |
| `ai-context/REDIS_MIGRATION_PLAN.md` | Durable progress tracker for the in-progress process-memory to Redis refactor. |
| `ai-context/REDIS_ENHANCEMENT_IMPLEMENTATION_PLAN.md` | Durable progress tracker for schema v2, ID-keyed ballots, auth/CSRF, and Redis interaction enhancements. |
| `ai-context/RESPONSIVE_UX_PROGRESS.md` | Completed responsive UX implementation tracker for live display browser scaling, attendee mobile optimization, admin mobile disclosure forms, and verification results. |
| `ai-context/STYLING_REFINEMENT_PROGRESS.md` | Progress and implementation notes for the attached-wireframe styling refinement across pages, live display, and generated emails. |
| `ai-context/GITHUB_ACTIONS_EC2_DEPLOYMENT_PLAN.md` | Active GitHub Actions plan for deploying merged `main` commits to the existing EC2 ASG through AWS CLI and SSM, without S3 or GoodVines disruption. |
| `ai-context/GITHUB_ACTIONS_DEPLOYMENT_IMPLEMENTATION_PROGRESS.md` | Durable progress tracker for the GitHub Actions deployment implementation, validation status, and external setup requirements. |
| `ai-context/GITLAB_AWS_DEPLOYMENT_DESIGN.md` | Legacy GitLab CI/CD design; superseded by the GitHub Actions deployment plan. |
| `ai-context/VAULT_ADMIN_TOKEN_RECOVERY.md` | Operator-only recovery note for using the services EC2 Vault init material without storing or printing root-token secrets. |
| `ai-context/VAULT_SECRETS_DESIGN.md` | Design for obtaining Halloween app secrets from the existing GoodVines Vault using AWS IAM auth. |

## Repository Organization

```text
.
├── AGENTS.md
├── .github/
│   └── workflows/
│       └── deploy-aws.yml
├── ai-context/
│   ├── ARCHITECTURE.md
│   ├── APP_HARDENING_FOR_AWS.md
│   ├── AWS_EXISTING_INFRA_HOSTING_PLAN.md
│   ├── AWS_IMPLEMENTATION_CHECKLIST.md
│   ├── AWS_LAUNCH_TEMPLATE_HALLOWEEN_BOOTSTRAP.md
│   ├── FEATURES.md
│   ├── FILE_INVENTORY.md
│   ├── FOOD_DRINK_BAR_FEATURE.md
│   ├── GITHUB_ACTIONS_DEPLOYMENT_IMPLEMENTATION_PROGRESS.md
│   ├── GITHUB_ACTIONS_EC2_DEPLOYMENT_PLAN.md
│   ├── GITLAB_AWS_DEPLOYMENT_DESIGN.md
│   ├── NO_SQL_DATA_POLICY.md
│   ├── PROJECT_OVERVIEW.md
│   ├── UI_UX_DESIGN_SYSTEM.md
│   ├── REDIS_ENHANCEMENT_IMPLEMENTATION_PLAN.md
│   ├── REDIS_CONNECTION_REQUIREMENTS.md
│   ├── REDIS_MIGRATION_PLAN.md
│   ├── REDIS_STATE_DESIGN.md
│   ├── RESPONSIVE_UX_PROGRESS.md
│   ├── VAULT_ADMIN_TOKEN_RECOVERY.md
│   └── VAULT_SECRETS_DESIGN.md
├── deploy/
│   ├── ec2_deploy_from_github.sh
│   ├── halloween-party.service
│   ├── nginx-halloween.conf
│   ├── start_halloween.sh
│   └── validate_goodvines_health.sh
├── main.py
├── .env.example
├── requirements.txt
├── static/
│   ├── display.css
│   ├── display.js
│   ├── slides.js
│   └── styles.css
├── tests/
│   └── test_redis_state.py
└── templates/
    ├── admin.html
    ├── admin_login.html
    ├── bartender.html
    ├── base.html
    ├── costume_signup.html
    ├── costume_voting.html
    ├── display.html
    ├── drink_history.html
    ├── email/
    │   ├── drink_order_placed.html
    │   └── drink_order_ready.html
    ├── halloween_login.html
    ├── halloween_register.html
    ├── index.html
    ├── karaoke_signup.html
    ├── menu.html
    └── rsvp.html
```
