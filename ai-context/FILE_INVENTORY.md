# File Inventory

## Tracked Source Files

| File | Purpose |
| --- | --- |
| `main.py` | Flask app entrypoint, route definitions, Redis-backed state cache/serialization, RSVP/email/account/menu/bar/DJ behavior, schema-v6 YouTube karaoke workflow/state/routes, admin stage controls, role auth, CSRF, voting, and live-display JSON/SSE APIs. |
| `youtube_karaoke.py` | YouTube URL/metadata normalization, Google API search and playlist client, bounded timeout/error translation, OAuth flow, and dedicated Vault refresh-token store. |
| `party_games.py` | Five-game catalog, persisted-state normalization, anonymous alias generation, Two Truths scoring, MMF plurality scoring, shared prompt-response-voting results, ties, and statistics. |
| `requirements.txt` | Python dependencies including Flask, Redis, AWS/SES, Google YouTube/OAuth clients, hvac, and gunicorn. |
| `.github/workflows/deploy-aws.yml` | GitHub Actions workflow that validates the app and deploys merged `main` commits to the existing API EC2 ASG through AWS CLI and SSM. |
| `deploy/ec2_deploy_from_github.sh` | SSM-run EC2 deployment script that fetches the Vault-stored GitHub deploy key, checks out the exact commit SHA, installs the Halloween release, restarts only `halloween-party`, validates nginx, and checks GoodVines health. |
| `deploy/start_halloween.sh` | systemd start wrapper that authenticates to Vault, exports Halloween app/Redis/email/YouTube settings, and execs gunicorn. |
| `deploy/configure_youtube_vault.sh` | Services-EC2 operator script for the narrow YouTube Vault policy/role and disabled dedicated secret path. |
| `deploy/halloween-party.service` | systemd unit for gunicorn on `127.0.0.1:8081`, including non-secret YouTube Vault role/path settings. |
| `deploy/nginx-halloween.conf` | nginx host-routing config for `tnq-halloween.com` and `www.tnq-halloween.com`, including SSE-friendly proxy settings. |
| `deploy/validate_goodvines_health.sh` | Local EC2 health helper that verifies the existing GoodVines app through nginx using the `appg-v.com` Host header. |
| `.env.example` | Blank/local Redis, email, MusicKit, and YouTube karaoke environment examples. |
| `tests/test_redis_state.py` | Redis/state/route/security tests plus fake-backed YouTube search, workflow, playlist, reconciliation, ordering, stage, OAuth-state, migration, and secret-exclusion coverage. |
| `static/styles.css` | Shared dark lab-terminal Halloween design system for attendee/admin pages, including scanline texture, serif headings, mono controls, square glowing panels, header menu, single logout action, menu cards, order cards, bartender tip disclosures, and bartender queue. |
| `static/bartender.js` | Bartender queue polling refresh that fetches the authenticated `/api/bartender-queue` fragment and swaps it in when the queue version changes. |
| `static/display.css` | Dedicated large-format live-display styles aligned with the dark lab-terminal design system, including square display cards, event override cards, top-layer drink-ready notices, CTA layout, scoreboard layout, and karaoke display panels. |
| `static/display.js` | Live-display client logic: card rotation, API polling, SSE reconnects, event override rendering, temporary notice rendering with optional images, scoreboard rendering, karaoke countdown and panel rotation. |
| `static/dj-display.js` | Live-display MusicKit receiver: load-safe local audio pairing, retained authorization diagnostics, reset handling, Redis-command execution, heartbeat/acknowledgement reporting, and Now Playing dock updates. |
| `static/dj-admin.js` | Authenticated Apple Music catalog search and DJ add-song form hydration. |
| `static/dj-admin-status.js` | Live admin DJ status updater using authenticated display-state polling and SSE notifications; refreshes the signal-path UI without reloading forms. |
| `static/jukebox.js` | Attendee jukebox catalog search, request submission, and safe Now Playing/playlist polling. |
| `static/karaoke.js` | Attendee song-details-first YouTube search, pagination, stale-selection protection, exact-video review, and direct-link fallback. |
| `static/karaoke-admin.js` | Admin async playlist actions, replacement search, playlist loading, and workflow polling. |
| `static/slides.js` | Dashboard event-highlight slide rotation. |
| `templates/base.html` | Shared attendee/admin layout with header menu navigation, signed-in identity, single logout action, footer, and script block. |
| `templates/index.html` | Attendee dashboard for `/party`: contest banners, ready drink notices, recent drink order cards, welcome callout, slides, costume and karaoke summaries. |
| `templates/games.html` | Party-day five-game workspace with dynamic tabs, opt-in, MMF ten-round ballots, prompt responses/voting, Two Truths guessing, aggregate reveals, and final results. |
| `templates/_game_scoreboard.html` | Shared attendee winner and final-score table for every game engine. |
| `templates/jukebox.html` | Attendee party-day Jukebox page with confirmed Now Playing, playlist, catalog search, and personal pending requests. |
| `templates/menu.html` | Attendee food/drink menu for `/party/menu`, including menu images, availability, specialty/standard badges, drink ordering, and recent order statuses. |
| `templates/drink_history.html` | Attendee full drink order history for `/party/drink-history`, including account-scoped order records, reorder controls, and per-order bartender tip QR/payment disclosure. |
| `templates/bartender.html` | Bartender/admin page shell for `/bartender`, with messages and the live-refresh queue container. |
| `templates/_bartender_queue.html` | Shared bartender queue fragment with drink images/placeholders, specialty sequence and extra-request notes, recipe reference, status transition forms, and completed order history. |
| `templates/rsvp.html` | Public RSVP landing page with RSVP prompt, party-code field on the RSVP form, party details, Google Maps embed/directions button, newest-to-oldest update cards, confirmation state, and optional portal account links. |
| `templates/halloween_login.html` | Public attendee account sign-in form. |
| `templates/halloween_register.html` | Public attendee account registration form. |
| `templates/account.html` | Authenticated attendee account details, role/session-permission diagnostics, profile settings, and password-change forms. |
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
| `templates/karaoke_signup.html` | Attendee three-step song details, exact-video selection, and review flow plus personal workflow status/recovery and synchronized public lineup. |
| `templates/admin_karaoke.html` | Dedicated YouTube connection, review, attention, run-of-show, history, and stage operations workspace. |
| `templates/_karaoke_workflow.html` | Shared karaoke media and seven-step workflow macros. |
| `templates/costume_voting.html` | Costume voting ballot and one-vote confirmation state. |
| `templates/admin_login.html` | Admin password form for `/admin/login`. |
| `templates/admin.html` | Workspace-based admin control room and focused guest/public/program/bar/menu/account management views, preserving existing CSRF-protected admin actions. |
| `templates/display.html` | Standalone full-screen live-display page and initial JSON bootstrap, including event override markup and top-layer notice image markup for drink-ready cards. |
| `ai-context/DJ_JUKEBOX_FEATURE.md` | Durable DJ feature state model, routes, MusicKit/Vault setup, visual acknowledgement flow, and recovery procedure. |
| `ai-context/GAMES_FEATURE_IMPLEMENTATION_PROGRESS.md` | Durable Two Truths and a Lie lifecycle, Redis model, scoring, attendee/admin/display behavior, verification, and rollout progress. |
| `ai-context/ACCOUNT_MANAGEMENT_FEATURE.md` | Attendee account workspace behavior, access boundaries, persistence rules, and verification coverage. |
| `ai-context/ROLE_VIEW_PREVIEW_FEATURE.md` | Admin role-view demo behavior, safety boundary, and regression coverage. |

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
| `ai-context/ADMIN_WORKSPACE_UX_PROGRESS.md` | Admin workspace information architecture, responsive behavior, attendee list-compaction refinements, verification, and extension rules. |
| `ai-context/YOUTUBE_KARAOKE_IMPLEMENTATION_PLAN.md` | Planned YouTube karaoke search, exact-video request workflow, host approval, playlist synchronization, dedicated admin workspace, stage controls, manual official-YouTube playback, security, migration, rollout, and acceptance criteria. |
| `ai-context/YOUTUBE_KARAOKE_IMPLEMENTATION_PROGRESS.md` | Current YouTube karaoke implementation, verification, production prerequisites, guardrails, and rollout progress. |
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
│   ├── ADMIN_WORKSPACE_UX_PROGRESS.md
│   ├── YOUTUBE_KARAOKE_IMPLEMENTATION_PLAN.md
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
