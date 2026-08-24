# Party Games Implementation Progress

## Objective

Provide one Redis-backed Games area for opt-in attendee play, independent game
lifecycles, anonymous submissions where appropriate, final scoring, admin
operations, and host-controlled live-display results.

## Implemented Games

1. **Two Truths and a Lie** — account-named clue submissions, anonymous clue
   rotation, identity guesses, tied winners, and final reveal.
2. **Murder, Marry, F%$@** — admin-selected signed-in-name or anonymous-alias
   mode, ten configurable trios of famous adults, one unique assignment per
   action and round, aggregate-only results, plurality scoring, and announcer
   presentation.
3. **Fill in the Blank: After Dark** — blind prompt responses and voting with
   an admin-selected public identity mode.
4. **Bad Advice Hotline** — fictional dilemmas, blind bad advice, response
   voting, and an admin-selected public identity mode.
5. **Wrong Answers Only** — fictional/general questions, blind wrong answers,
   response voting, and an admin-selected public identity mode.

All new games deploy disabled. Admin must enable each game before its tab,
dashboard status, or enrollment flow appears to attendees.

## Shared Lifecycle

- `disabled`: hidden and blocked while saved data remains intact.
- `signup`: enabled enrollment; attendees may opt in. Two Truths submissions
  remain editable in this phase.
- `active`: enrollment locks and game-specific play opens.
- `ended`: answers/votes lock and final scores/winners are snapshotted.
- `reset`: creates a Redis backup, clears play data, restores configuration
  defaults, and preserves the enabled flag.

Prompt games add per-round phases: `submissions -> voting -> revealed`. The
host must reveal the current round before opening another or ending the game.

MMF and all three prompt games can start with one opted-in player. A solo MMF
ballot is scored against its own round pluralities. A prompt round with one
response skips the impossible self-vote step, reveals a solo spotlight, and
awards one point. Two Truths still requires two mystery guests because its core
interaction depends on guessing another attendee.

## Scoring

### Two Truths and a Lie

- One point for every correctly identified mystery guest.
- Ranking uses correct count, accuracy, then name.
- Everyone tied at the top positive score wins.

### Murder, Marry, F%$@

- Exactly ten rounds and three famous adults per round.
- Every completed ballot uses Murder, Marry, and the configurable third label
  exactly once.
- One point when a player's assignment matches the party plurality for an
  action; tied pluralities all count.
- Maximum score is 30. Everyone tied at the top positive score wins.

### Prompt Games

- One blind response and one editable vote per player per round.
- Self-voting is rejected.
- Each vote received is one cumulative point.
- Tied round responses and tied final leaders are preserved.

## Privacy And Content Guardrails

- MMF and prompt games default to signed-in display names. The selected-game
  admin console can switch the entire game to generated aliases during signup;
  attendees do not control anonymity.
- Prompt responses remain authorless during voting so named enrollment cannot
  bias voting. Reveals, scoreboards, result cards, and presentation slides use
  the admin-selected public identity.
- MMF individual ballots remain private for named and anonymous players alike.
  Admin/export surfaces show aggregate selections only.
- The aggregate game export removes account-keyed participant maps from MMF and
  prompt games. Anonymous players' signed-in names are not exported.
- Active prompt responses rotate only after voting opens, preventing early
  submissions from receiving extra exposure.
- MMF choices are limited by product policy to famous/infamous adults. The UI
  explicitly prohibits attendees, private people, minors, confessions, and
  personal information.
- The server retains account association for authorization, duplicate
  prevention, score integrity, and returning a player to the game identity
  selected by the host. Schema normalization backfills legacy display names
  from registered users when available and otherwise retains alias fallback.

## Admin And Display

- `/admin/games?game=<game-key>` presents a compact five-game status selector
  and one detailed operational console, with shared aggregate status. Detailed
  data is constructed only for the selected game.
- MMF includes a ten-trio editor, optional image URLs, and configurable third
  action label.
- Prompt games include independent prompt decks, enable/disable/remove prompt
  controls, response/vote counts, round controls, and leaderboards.
- Ended games provide Start, Previous, and Next announcer presentation controls,
  direct winner/results cards, and normal-rotation resume.
- MMF presentation walks through each trio and action total. Prompt presentation
  walks through each revealed prompt and winning response under its selected
  public identity.
- Ended winner/scoreboard cards join normal live-display rotation. Prompt
  responses join rotation only during voting/reveal.
- Each selected game console provides a deterministic completed-game simulator for 2-20
  test players. It preserves game configuration, creates no party accounts,
  backs up Redis before mutation, and refuses to replace real participants.
- Ended games always contribute a winner or No Winner outcome card. Generated
  outcome and final-score cards remain available when attendee enrollment is
  disabled and can be shown, included, or hidden from `/admin/display`.
- Temporary drink-ready notices retain priority above game event overrides.
- Every enabled game contributes privacy-safe left-stage data to an independent
  rotation, so multiple live games can cycle without interrupting center cards.
  The display admin can pin one game or resume automatic game rotation.

## State And Routes

- Games were introduced in schema version `12`; the canonical app state is now
  schema version `17` after recognition/history additions.
- `games_state` contains all five independent game records.
- Attendee hub: `GET /party/games?game=<slug>`.
- Attendee enrollment under the admin-selected identity mode:
  `POST /party/games/<slug>/join`.
- MMF ballot round: `POST /party/games/murder-marry-fuck/answers`.
- Prompt response/vote: `POST /party/games/<slug>/response|vote`.
- Admin operations continue through the focused `/admin/games` POST handler.
- Aggregate/redacted download: `GET /admin/export/games`.

## Realtime Results And Official History (2026-08-24)

- `/party/results` and `/api/party/games-data` expose attendee-safe live status,
  completion metrics, final scoreboards, official prior-year results, and the
  signed-in account's awards. Overview/game widgets refresh every five seconds.
- Every game finalization snapshots one durable draft archive. Hosts explicitly
  publish the draft to official history and grant idempotent credits to all
  linked tied winners. Simulation archives are permanently ineligible.
- Winner/outcome cards use five dedicated trophy illustrations under
  `static/images/games/winners/`; ordinary status and final-score cards retain
  the original five game illustrations.
- Full data model, privacy rules, recognition admin flow, and asset inventory
  are documented in `GAME_RESULTS_REWARDS_RECOGNITION_PROGRESS.md`.

## Verification

- `python -m compileall -q main.py party_games.py` passed.
- `python -m pytest -q` passed with 146 tests and 16 subtests.
- Coverage includes schema migration, every game variant, admin-selected
  named/anonymous identity, MMF 30-point ties, aggregate-only export, invalid assignments,
  blind prompt voting, self-vote rejection, result presentation, and resets.
- Browser QA exercised the dashboard, game tabs, adult-content notice,
  game enrollment, multi-game admin enable/start controls, prompt selection,
  the 10-round configuration presence, and desktop overflow at 1280px.
- Active MMF, prompt submission, and prompt voting templates have dedicated
  authenticated route-render regression tests.

## Simulation And Result-Card Controls (2026-08-13)

- Every `/admin/games` card now includes a completed-game simulator for 2-20
  deterministic test players. Simulation creates a Redis backup, preserves
  configured MMF rounds and prompt decks, creates no party accounts, and blocks
  replacement when non-simulated participants exist.
- Simulated games finalize directly into `ended`, retain explicit simulation
  metadata, and immediately broadcast their winner/outcome and final-score
  cards to the live display.
- Every ended game now has a stable winner/outcome card, including a No Winner
  card when no positive score exists. Result cards remain available after the
  game is disabled for attendees.
- `/admin/display` exposes every generated game result card with Show Now and
  Include/Hide actions. Per-card inclusion was introduced in schema v10 and is
  retained in schema-v12 `display_config.game_result_card_enabled` state.
- Verification passed with 143 tests and 16 subtests, Python compilation,
  bundled-Node syntax checks for both live-display scripts, deployment-script
  shell validation, and `git diff --check`.

## Admin-Controlled Game Identity (2026-08-14)

- MMF and the three prompt games default to attendees' signed-in display names.
  The selected-game admin console owns one game-level anonymity toggle; it
  switches every player to generated aliases and locks when the game starts.
- Attendees do not receive an identity or anonymity control. The game page tells
  them whether the hosts selected signed-in names or anonymous aliases.
- A generated alias is retained for every player as a safe fallback. Schema-v12
  normalization adds the game-level mode and backfills legacy display names from
  registered users when available.
- Prompt voting remains blind and MMF ballots remain aggregate-only. Selected
  identities appear only on appropriate reveals, final scoreboards, winner
  cards, presentation slides, and live-display results.
- The game export redacts MMF and prompt account keys, includes admin-selected
  public names plus game anonymity flags, omits account names in anonymous mode, and still
  excludes individual MMF ballots.

## Presentation And Navigation Refinement (2026-08-05)

- Five generated, optimized game illustrations live under
  `static/images/games/` and drive distinct dashboard cards and game-page hero
  treatments. They were created with built-in ImageGen using text-free dark
  lab-terminal prompts: sealed evidence cards, a three-person choice chamber,
  a glowing sentence blank and pen, a devilish bad-advice hotline, and a
  surreal wrong-answer buzzer.
- The party-game gallery now sits directly below the party dashboard welcome
  panel, ahead of drink history, jukebox, and event highlights.
- `static/preserve-scroll.js` restores scroll position and open disclosure rows
  after same-page POST actions throughout the shared attendee/admin shell.

## Selected-Game Admin And No-Jump Actions (2026-08-14)

- The Games admin now renders one selected console at a time and retains all
  five game phases/player counts in a desktop grid or sticky mobile rail.
- Large score, participant, and guess views are bounded in the browser; complete
  data remains available through the redacted aggregate export.
- Standard admin actions fetch the existing Flask response and replace the
  workspace in place. Stable view keys retain disclosures, anchor position, and
  logical focus, with ordinary forms preserved as the fallback.
- Detailed design and verification live in
  `ai-context/ADMIN_GAMES_WORKSPACE_REORGANIZATION.md`.
