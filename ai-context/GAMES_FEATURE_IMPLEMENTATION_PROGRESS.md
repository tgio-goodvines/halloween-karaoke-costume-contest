# Party Games Implementation Progress

## Objective

Add a reusable party Games surface with Two Truths and a Lie as the first game. Attendees enroll from the party-day portal, submit two truths and one lie, browse anonymous mystery cards after the host starts play, and enter free-text identity guesses. Admins control the lifecycle, inspect progress, finalize tied winners, export data, and control game result cards on the live display.

## Lifecycle

- `disabled`: hidden and blocked for attendees while stored data remains intact.
- `signup`: enabled enrollment; attendees may create or edit one mystery submission per account.
- `active`: roster and statements are locked; enrolled participants can guess every other participant.
- `ended`: guesses are locked and the finalized leaderboard, winner set, and participant results are stored.
- `reset`: clears all game records and results while preserving the enabled setting.

## Implementation Status

Application implementation and local verification are complete on branch
`agent/games-two-truths-lie`. Publication and production deployment are in
progress.

Completed so far:

- Added `party_games.py` for defaults, normalization, statement presentation, scoring, ties, and statistics.
- Advanced the Redis snapshot schema from version 6 to version 7.
- Added Redis-backed `games_state` serialization and hydration.
- Added role, read-refresh, and state-mutation endpoint registration for attendee game routes and admin export.
- Added attendee Games page, opt-in transition, statement create/update, anonymous play cards, free-text guess upserts, and final results.
- Added the party dashboard Games callout and shared Menu link.
- Added a focused `/admin/games` workspace with lifecycle actions, live statistics, raw guess inspection, participant truth/lie data, JSON export, and confirmed reset.
- Added anonymous live-display clue rotation entries, final winner/results entries, persistent game overrides, and manual resume.
- Generalized live-display scoreboard row labels for both costume and game results.

Completed verification:

- `python -m compileall main.py party_games.py` passed.
- `python -m pytest -q` passed with 131 tests and 5 migration subtests.
- Bundled Node `--check static/display.js` passed.
- Browser QA covered `/party`, `/party/games`, `/admin/games`, and
  `/live-display` at `390x844` and 1280px with no horizontal overflow.
- Browser QA exercised enablement, opt-in, statement entry, persistence,
  anonymous display payloads, participant statistics, and the minimum-player
  start validation.
- The live-display browser reported no console errors or warnings.

Remaining:

- Commit and push over SSH.
- Open and merge the PR, observe the existing GitHub Actions deployment, and
  verify Halloween plus GoodVines production health.

## Scoring Rules

- Each correctly identified mystery guest is worth one point.
- Guess matching trims and collapses whitespace and compares party-account names case-insensitively.
- Ranking uses correct guesses, then accuracy, then display name for deterministic ordering.
- Everyone tied at the highest positive score is a winner.
- Zero correct guesses produces final results but no winner card.
- Final results are snapshotted at game end so later account-profile changes cannot alter the outcome.

## Guardrails

- Attendee and rotation payloads do not reveal names or truth/lie classifications before the game ends.
- Only enrolled participants can guess, and self-guesses are rejected.
- All POSTs use the existing CSRF and Redis mutation-lock flow.
- Game display overrides do not alter costume, karaoke, DJ, or drink-notice state.
- Reset writes a Redis backup before clearing game data.
- No SQL, new infrastructure, new secret, or GoodVines service change is required.
