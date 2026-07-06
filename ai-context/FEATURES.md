# Feature Inventory

## Public And Attendee Features

- Party dashboard at `/halloween`.
- Device/session check-in at `/halloween/login`.
- Logged-in user name is shown in the shared header.
- Costume contest signup at `/costume-signup`.
- Costume signup validation for required name and costume description.
- Costume signup success redirect and confirmation state.
- List of submitted costume entries.
- Karaoke signup at `/karaoke-signup`.
- Karaoke signup validation for required name, song title, and artist.
- Optional YouTube link field for karaoke entries.
- Karaoke signup success redirect and lineup display.
- Event highlight slide rotation on the party dashboard.
- Contest status banners on attendee pages when voting is open or the winner is locked.

## Costume Contest Features

- Admin can start the costume contest.
- Starting the contest opens voting, clears previous submitted-voter tracking, clears winner/scoreboard state, and pushes a live-display contest-start override.
- Voting page is only available while voting is open and no winner is locked.
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
- Admin can start the Halloween karaoke party if at least one karaoke signup exists.
- Starting karaoke sets a live-display override with countdown to 11:00 PM MST and the current lineup.
- Live display has client-side support for countdown and rotating karaoke panels.

## Admin Features

- Admin dashboard at `/admin`.
- Admin login at `/admin/login` when `HALLOWEEN_ADMIN_PASSWORD` is configured.
- Admin logout at `/admin/logout`.
- Add, edit, delete, move up, and move down costume signups.
- Add, edit, delete, move up, and move down karaoke signups.
- Admin mutations validate required fields.
- Admin mutations broadcast live-display updates when they affect display content.
- Admin can start costume contest, lock winner, show winner, restore display, and start karaoke party.
- Admin receives inline success/error messages.
- Admin JSON export routes are available for full Redis state, costume results,
  and karaoke lineup at `/admin/export/state`,
  `/admin/export/costume-results`, and `/admin/export/karaoke-lineup`.
- POST forms include CSRF tokens outside testing mode.

Important caveat: In non-production development, `/admin` remains open when
`HALLOWEEN_ADMIN_PASSWORD` is unset. Production should set that environment
variable.

## Live Display Features

- `/live-display` is the default root destination via `/` redirect.
- Shows event title and live counts for costume and karaoke signups.
- Rotates through signup portal instructions, event spotlight cards, winner/scoreboard cards, costume entries, and karaoke entries.
- Signup portal card includes WiFi network, WiFi password, and portal link.
- Display entries rotate every 8 seconds with fade/slide transitions.
- Display data refreshes every 30 seconds via `/api/display-data`.
- Display also updates immediately through server-sent events from `/api/display-updates`.
- SSE endpoint sends keep-alive comments on idle intervals.
- Display supports full-screen override cards for contest start, winner announcement, and karaoke start.
- Display client can cache-bust `display.css` once when an override becomes active.

## Styling And UX Features

- Shared dark Halloween visual system in `static/styles.css`.
- Dedicated TV/projector display styling in `static/display.css`.
- Responsive layouts for mobile and large display screens.
- Sticky site header for attendee/admin pages.
- Red glowing cards, buttons, banners, score bars, and display panels.
