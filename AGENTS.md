# AI Context Entry Point

This repository is a small Flask app for a Halloween party signup, costume contest, karaoke queue, and live display.

Start future repo work by reading these persistent context files:

- `ai-context/PROJECT_OVERVIEW.md` - purpose, runtime assumptions, state model, and app flow.
- `ai-context/FEATURES.md` - all supported user/admin/live-display features.
- `ai-context/FILE_INVENTORY.md` - file-by-file purpose and ownership map.
- `ai-context/ARCHITECTURE.md` - route map, data structures, frontend behavior, and extension guidance.
- `ai-context/UI_UX_DESIGN_SYSTEM.md` - current lab-terminal visual design system, palette, typography, surfaces, and implementation notes.
- `ai-context/FOOD_DRINK_BAR_FEATURE.md` - food/drink menu, drink ordering, bartender role, order timing, emails, and live-display drink-ready override.
- `ai-context/RESPONSIVE_UX_PROGRESS.md` - completed responsive UX work for live display, attendee mobile views, and admin mobile views.
- `ai-context/GITHUB_ACTIONS_EC2_DEPLOYMENT_PLAN.md` - active AWS deployment plan using GitHub Actions, AWS CLI, SSM, Vault, and existing EC2/nginx infrastructure.
- `ai-context/GITHUB_ACTIONS_DEPLOYMENT_IMPLEMENTATION_PROGRESS.md` - durable progress tracker for deployment implementation and remaining external setup.
- `ai-context/AWS_LAUNCH_TEMPLATE_HALLOWEEN_BOOTSTRAP.md` - launch template version 2 details for automatic Halloween install on replacement API EC2 instances.
- `ai-context/VAULT_ADMIN_TOKEN_RECOVERY.md` - operator-only note for using the services EC2 Vault init file without printing or committing root-token material.

Important working notes:

- The app stores Halloween event data in Redis DB `1` using the `halloween:` key prefix, with process-local state as a runtime cache.
- The root route redirects to the admin-selected public landing page and defaults to `/rsvp`; attendee-facing portal flow continues at `/party` after separate registration/login.
- `/rsvp`, `/party/register`, and `/party/login` are public starting-flow pages and must not be hidden behind a party-code gate.
- The `/rsvp` page is a standalone public RSVP surface and must not show the header menu/site navigation; party details, map, and host updates are public. RSVP submission requires the admin-configured party code as a field on the RSVP form.
- `/rsvp` is an independent host RSVP list, not account creation; attendee portal accounts are created/signed in through Redis-backed accounts at `/party/register` and `/party/login`.
- RSVP and party account registration require an email address; there is no guest opt-in checkbox. Successful RSVP sends a confirmation email with RSVP details plus Google Calendar and `.ics` calendar links when email is enabled. Successful public RSVP also sends a host notification email to the admin-configurable RSVP notification recipient, defaulting to `tgio1129@gmail.com`, when email is enabled. Admin-posted RSVP updates can email deduplicated RSVP and registered-user recipients through SES when enabled.
- Creating a party account sends a SES welcome email when email is enabled; failures must not block account creation.
- Party account users can reset forgotten passwords through `/party/password-reset`; reset emails use SES, reset tokens are hashed before storage, expire after 45 minutes, and are single-use.
- Before the party date, `/party` shows pre-party RSVP details and host updates in Event Highlights and hides/blocks attendee menu, costume, karaoke, drink-order, and voting actions. On the party date, `/party` switches to the event-night dashboard.
- `/party/menu` lets signed-in attendees view food/drink menu cards with images and order available drinks on the party date; food is currently view-only.
- Admin can manage food/drink menu items, image URLs, availability, and drink recipes from `/admin`; bartender access is assigned to existing party accounts through account roles.
- `/bartender` is available to assigned bartenders and admins; drink orders move `received -> in_progress -> complete`, completion tracks prep duration, and estimates are based on recent completed prep times.
- Completing a drink order sends the ready email and creates a temporary live-display `drink_ready` override with the drink image; attendees also see ready drink cards on `/party`.
- Halloween outbound email uses the separate `tnq-halloween.com` SES identity and sender `no-reply@tnq-halloween.com`; do not change existing GoodVines SES identities or sender addresses for `appg-v.com` or `goodvines.app`.
- Admin controls can set the root landing target, replace the RSVP submission party code, configure the host RSVP notification email, edit RSVP party detail/map cards, and post RSVP updates; store only the party code hash, never plaintext.
- Before `HALLOWEEN_PARTY_START`, live-display rotation is limited to RSVP/static party info/update cards and should not show costume or karaoke signup entries.
- Admin controls and the live display are protected through `/admin/login`; live-display clients still update through `/api/display-updates` server-sent events and periodically poll `/api/display-data`.
- Header logout is a single button tucked inside the `Menu` disclosure; do not add separate regular/admin logout controls.
- Production deploys run `halloween-party.service` behind nginx on `127.0.0.1:8081`.
- Responsive UX updates are complete: live-display cards scale for normal browser windows, attendee/admin pages are mobile-oriented, and admin add/edit forms are collapsed disclosure rows by default.
- The active UI direction is the dark lab-terminal Halloween system documented in `ai-context/UI_UX_DESIGN_SYSTEM.md`; keep future page styling aligned with its square panels, mono controls, serif glowing headings, red/magenta/steel palette, and scanline texture.
- GitHub Actions deployment to EC2 has succeeded, and future API ASG replacement instances should bootstrap Halloween automatically from launch template version `2`.
- Do not disrupt GoodVines when working on deployment: do not restart GoodVines services, edit GoodVines source directories, or change GoodVines nginx server blocks.
- Keep changes compact and consistent with the existing Flask/Jinja/static-file structure unless a larger refactor is explicitly requested.
