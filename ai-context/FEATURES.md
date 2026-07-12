# Feature Inventory

## Public And Attendee Features

- `/` redirects to the admin-selected public landing target and defaults to
  `/rsvp`.
- RSVP landing page at `/rsvp` opens with an RSVP prompt, account creation/login
  alternatives, admin-editable static party detail cards, Google Maps location
  embed/directions button, and update cards.
- `/rsvp` is standalone and hides the shared header menu/site navigation even
  if a signed-in party user opens it directly.
- `/rsvp`, `/party/login`, and `/party/register` require the party code before
  RSVP, sign-in, or account creation forms are visible.
- Locked `/rsvp` sessions show only the code prompt; party details, map, and
  updates stay hidden until the current browser session enters the correct code.
- Successful RSVP adds an independent host-visible RSVP entry with name,
  required email contact, guest count, and note; it does not create an attendee
  account. There is no guest opt-in checkbox for update emails.
- Successful RSVP sends a confirmation email through SES when email is enabled;
  the email includes RSVP details, a Google Calendar link, and an `.ics`
  calendar download link.
- Party dashboard at `/party`.
- Redis-backed attendee account registration at `/party/register` requires an
  email address so registered users can receive RSVP-page host update emails.
- Successful party account creation sends a welcome email through SES when
  email is enabled; delivery failure does not block account creation.
- Password-backed attendee account sign-in at `/party/login`.
- Email-based password reset at `/party/password-reset` sends a one-time
  45-minute reset link without revealing whether the submitted email is
  registered.
- Food and drink menu at `/party/menu` shows admin-managed cards with images,
  descriptions, and availability.
- Signed-in attendees can order available drinks from `/party/menu`; food items
  are currently view-only.
- Attendees can see recent drink order statuses and dashboard ready-drink cards.
- A single logout action inside the shared header menu clears the current
  browser session regardless of role.
- Regular guest sessions can access attendee UI routes but not admin or live-display routes.
- Logged-in user name is shown in the shared header menu.
- Costume contest signup at `/party/costumes`.
- Costume signup validation for required name and costume description.
- Costume signup success redirect and confirmation state.
- List of submitted costume entries.
- Karaoke signup at `/party/karaoke`.
- Karaoke signup validation for required name, song title, and artist.
- Optional YouTube link field for karaoke entries.
- Karaoke signup success redirect and lineup display.
- Event highlight slide rotation on the party dashboard.
- Contest status banners on attendee pages when costume voting is visible or the winner is locked.

## Costume Contest Features

- Admin can start, stop, and reset the costume contest.
- Starting the contest opens voting, clears previous submitted-voter tracking, clears winner/scoreboard state, and pushes a live-display contest-start override.
- Stopping the contest closes and hides attendee voting without deleting entries or existing results.
- Resetting the contest clears votes, submitted-voter tracking, winner/scoreboard state, and live-display override without deleting costume entries.
- Voting page and voting navigation are only visible while the costume contest is started, voting is open, and no winner is locked.
- Voting page requires a checked-in session.
- Each guest/session can vote once.
- Voting requires a score for every costume entry.
- Scores must be whole numbers from 1 to 10.
- Votes are stored as ID-keyed ballots per checked-in guest.
- Scoreboard calculates total, vote count, average, leader, and percent-of-current-max values.
- Tie handling for leader favors higher average, then higher vote count.
- Admin can view vote tally bars and current leader.
- Admin can lock the costume winner once at least one vote exists.
- Locking the winner closes voting and creates a top-three scoreboard card.
- Admin can show the winner as a live-display override.
- Admin can restore the rotating live display after an override.
- After restoring display, a locked scoreboard card can rejoin the rotation.

## Karaoke Features

- Guests can join the karaoke lineup with name, song title, artist, and optional YouTube link.
- Admin can add, edit, delete, and reorder karaoke signups.
- Admin page highlights the first karaoke signup as the opening act.
- Admin warning appears when the opening act has no YouTube link.
- Admin can start, stop, and reset the Halloween karaoke party if at least one karaoke signup exists for start.
- Starting karaoke sets a live-display override with countdown to 11:00 PM MST and the current lineup.
- Stopping or resetting karaoke clears active karaoke state and karaoke-start live-display override without deleting the lineup.
- Live display has client-side support for countdown and rotating karaoke panels.

## Admin Features

- Admin dashboard at `/admin`.
- Password-backed admin login at `/admin/login`.
- Admin sessions can access admin routes, JSON exports, and the live-display
  routes; they do not implicitly receive regular guest access.
- Admin can choose which page `/` redirects to: RSVP landing, party login,
  party account signup, party portal, or live display.
- Admin can set or replace the party code and optional code hint. The party code
  is stored as a hash, not plaintext.
- Admin can add, edit, and delete RSVP entries, and see the total guest count.
- Admin can edit the static party detail cards and map address shown on the RSVP
  page.
- Admin can post, remove, and resend RSVP updates. Updates appear on `/rsvp`
  newest first after the static party detail cards. When Halloween email updates
  are enabled, admins can select which eligible RSVP and registered-user
  recipients receive each posted or resent update email through SES.
- Admin can add, edit, remove, and disable food/drink menu items, including image
  URLs, descriptions, and drink recipes for bartender reference.
- Admin can add, edit, and delete party account users, reset account passwords
  directly, and assign or remove the `bartender` role.
- Admin can open the bartender view and see bar operations summary counts.
- Admins use the same `/logout` action as attendees; logout clears the current
  browser session rather than a role-specific slice of it.
- Add, edit, delete, move up, and move down costume signups.
- Add, edit, delete, move up, and move down karaoke signups.
- Add-entry and existing-entry admin forms are collapsed disclosure rows by
  default to improve mobile scanning and reduce scroll fatigue.
- Admin mutations validate required fields.
- Admin mutations broadcast live-display updates when they affect display content.
- Admin can start, stop, and reset the costume contest; lock winner, show winner, restore display; and start, stop, and reset karaoke party state.
- Admin receives inline success/error messages.
- Admin JSON export routes are available for full Redis state, costume results,
  and karaoke lineup at `/admin/export/state`,
  `/admin/export/costume-results`, and `/admin/export/karaoke-lineup`.
- POST forms include CSRF tokens outside testing mode.

## Bar And Drink Ordering Features

- Bartender view at `/bartender` is available to assigned bartender accounts and
  admins.
- Drink orders progress from `received` to `in_progress` to `complete`.
- Bartender view shows drink image and recipe reference; in-progress orders keep
  the recipe visible.
- Completed orders track prep duration and feed future estimated ready times.
- Drink order confirmation emails include estimated ready time when Halloween
  email sending is enabled.
- Completing a drink sends a ready email, updates attendee dashboard/menu order
  cards, and creates a temporary live-display drink-ready override with the
  drink image.

Important caveat: UI role passwords must be configured for normal use:
`HALLOWEEN_ADMIN_PASSWORD` is the only UI password loaded from Vault. Regular
attendee passwords are account-specific and stored as password hashes in Redis
app state.

## Live Display Features

- `/live-display` can be selected as the root destination from admin public
  access controls, but `/` defaults to `/rsvp`.
- `/live-display`, `/api/display-data`, and `/api/display-updates` require a
  signed-in admin session from `/admin/login`.
- `/health` returns JSON service and Redis readiness for production health
  checks.
- Shows event title and live counts for costume and karaoke signups.
- Before `HALLOWEEN_PARTY_START`, live display rotates only RSVP, static party
  detail, and RSVP update cards.
- Rotates through signup portal instructions, event spotlight cards, winner/scoreboard cards, costume entries, and karaoke entries.
- Signup portal card includes WiFi network, WiFi password, and portal link.
- Display entries rotate every 8 seconds with fade/slide transitions.
- Display data refreshes every 30 seconds via `/api/display-data`.
- Display also updates immediately through server-sent events from `/api/display-updates`.
- SSE endpoint sends keep-alive comments on idle intervals.
- Display supports full-screen override cards for contest start, winner announcement, and karaoke start.
- Display supports temporary drink-ready override cards with drink images.
- Live-display cards use dynamic browser-size scaling, long/dense text classes,
  and overflow wrapping so normal desktop/laptop browser windows and narrow
  browsers do not clip cards.
- Karaoke start override includes countdown and upcoming-singer panel markup for
  the existing client-side karaoke rotator.
- Display client can cache-bust `display.css` once when an override becomes active.

## Styling And UX Features

- Shared dark Halloween visual system in `static/styles.css`.
- Dedicated TV/projector display styling in `static/display.css`.
- Responsive layouts for mobile, normal browser windows, and large display
  screens.
- Sticky site header for attendee/admin pages.
- Attendee/admin mobile header uses compact disclosure navigation with shorter
  labels and touch-friendly controls.
- The single logout control is tucked into the disclosure navigation menu.
- Red glowing cards, buttons, banners, score bars, and display panels.
