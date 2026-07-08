# AI Context Entry Point

This repository is a small Flask app for a Halloween party signup, costume contest, karaoke queue, and live display.

Start future repo work by reading these persistent context files:

- `ai-context/PROJECT_OVERVIEW.md` - purpose, runtime assumptions, state model, and app flow.
- `ai-context/FEATURES.md` - all supported user/admin/live-display features.
- `ai-context/FILE_INVENTORY.md` - file-by-file purpose and ownership map.
- `ai-context/ARCHITECTURE.md` - route map, data structures, frontend behavior, and extension guidance.
- `ai-context/RESPONSIVE_UX_PROGRESS.md` - completed responsive UX work for live display, attendee mobile views, and admin mobile views.
- `ai-context/GITHUB_ACTIONS_EC2_DEPLOYMENT_PLAN.md` - active AWS deployment plan using GitHub Actions, AWS CLI, SSM, Vault, and existing EC2/nginx infrastructure.
- `ai-context/GITHUB_ACTIONS_DEPLOYMENT_IMPLEMENTATION_PROGRESS.md` - durable progress tracker for deployment implementation and remaining external setup.
- `ai-context/AWS_LAUNCH_TEMPLATE_HALLOWEEN_BOOTSTRAP.md` - launch template version 2 details for automatic Halloween install on replacement API EC2 instances.
- `ai-context/VAULT_ADMIN_TOKEN_RECOVERY.md` - operator-only note for using the services EC2 Vault init file without printing or committing root-token material.

Important working notes:

- The app stores Halloween event data in Redis DB `1` using the `halloween:` key prefix, with process-local state as a runtime cache.
- The root route redirects to `/live-display`; attendee-facing flow begins at `/party`.
- Attendees register/sign in through Redis-backed accounts at `/party/register` and `/party/login`; the single logout action is `/logout` and clears the current browser session regardless of role.
- Admin controls and the live display are protected through `/admin/login`; live-display clients still update through `/api/display-updates` server-sent events and periodically poll `/api/display-data`.
- Header logout is a single button tucked inside the `Menu` disclosure; do not add separate regular/admin logout controls.
- Production deploys run `halloween-party.service` behind nginx on `127.0.0.1:8081`.
- Responsive UX updates are complete: live-display cards scale for normal browser windows, attendee/admin pages are mobile-oriented, and admin add/edit forms are collapsed disclosure rows by default.
- GitHub Actions deployment to EC2 has succeeded, and future API ASG replacement instances should bootstrap Halloween automatically from launch template version `2`.
- Do not disrupt GoodVines when working on deployment: do not restart GoodVines services, edit GoodVines source directories, or change GoodVines nginx server blocks.
- Keep changes compact and consistent with the existing Flask/Jinja/static-file structure unless a larger refactor is explicitly requested.
