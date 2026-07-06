# AI Context Entry Point

This repository is a small Flask app for a Halloween party signup, costume contest, karaoke queue, and live display.

Start future repo work by reading these persistent context files:

- `ai-context/PROJECT_OVERVIEW.md` - purpose, runtime assumptions, state model, and app flow.
- `ai-context/FEATURES.md` - all supported user/admin/live-display features.
- `ai-context/FILE_INVENTORY.md` - file-by-file purpose and ownership map.
- `ai-context/ARCHITECTURE.md` - route map, data structures, frontend behavior, and extension guidance.

Important working notes:

- The app stores all event data in process memory in `main.py`; restarting the Flask process clears signups, votes, sessions, contest state, and live-display overrides.
- The root route redirects to `/live-display`; attendee-facing flow begins at `/halloween`.
- Admin controls are currently unauthenticated at `/admin`.
- Live-display clients update through `/api/display-updates` server-sent events and periodically poll `/api/display-data`.
- Keep changes compact and consistent with the existing Flask/Jinja/static-file structure unless a larger refactor is explicitly requested.
