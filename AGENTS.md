# AI Context Entry Point

This repository is a small Flask app for a Halloween party signup, costume contest, karaoke queue, and live display.

Start future repo work by reading these persistent context files:

- `ai-context/PROJECT_OVERVIEW.md` - purpose, runtime assumptions, state model, and app flow.
- `ai-context/FEATURES.md` - all supported user/admin/live-display features.
- `ai-context/FILE_INVENTORY.md` - file-by-file purpose and ownership map.
- `ai-context/ARCHITECTURE.md` - route map, data structures, frontend behavior, and extension guidance.
- `ai-context/GITHUB_ACTIONS_EC2_DEPLOYMENT_PLAN.md` - active AWS deployment plan using GitHub Actions, AWS CLI, SSM, Vault, and existing EC2/nginx infrastructure.
- `ai-context/GITHUB_ACTIONS_DEPLOYMENT_IMPLEMENTATION_PROGRESS.md` - durable progress tracker for deployment implementation and remaining external setup.

Important working notes:

- The app stores Halloween event data in Redis DB `1` using the `halloween:` key prefix, with process-local state as a runtime cache.
- The root route redirects to `/live-display`; attendee-facing flow begins at `/halloween`.
- Admin controls are protected through `/admin/login`.
- Live-display clients update through `/api/display-updates` server-sent events and periodically poll `/api/display-data`.
- Production deploys run `halloween-party.service` behind nginx on `127.0.0.1:8081`.
- Do not disrupt GoodVines when working on deployment: do not restart GoodVines services, edit GoodVines source directories, or change GoodVines nginx server blocks.
- Keep changes compact and consistent with the existing Flask/Jinja/static-file structure unless a larger refactor is explicitly requested.
