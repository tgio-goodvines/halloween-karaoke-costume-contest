# Party Games Implementation Progress

## Objective

Provide one Redis-backed Games area for opt-in attendee play, independent game
lifecycles, anonymous submissions where appropriate, final scoring, admin
operations, and host-controlled live-display results.

## Implemented Games

1. **Two Truths and a Lie** — account-named clue submissions, anonymous clue
   rotation, identity guesses, tied winners, and final reveal.
2. **Murder, Marry, F%$@** — anonymous aliases, ten configurable trios of
   famous adults, one unique assignment per action and round, aggregate-only
   results, plurality scoring, and announcer presentation.
3. **Fill in the Blank: After Dark** — anonymous prompt responses and voting.
4. **Bad Advice Hotline** — fictional dilemmas, anonymous bad advice, and
   response voting.
5. **Wrong Answers Only** — fictional/general questions, anonymous wrong
   answers, and response voting.

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

- One anonymous response and one editable vote per player per round.
- Self-voting is rejected.
- Each vote received is one cumulative point.
- Tied round responses and tied final leaders are preserved.

## Privacy And Content Guardrails

- MMF and prompt-game players receive random aliases; account names never enter
  their answers, scoreboards, result cards, or presentation slides.
- MMF admin/export surfaces show aggregate selections only. The export removes
  the account-keyed participant map and all individual ballots.
- Active prompt responses rotate only after voting opens, preventing early
  submissions from receiving extra exposure.
- MMF choices are limited by product policy to famous/infamous adults. The UI
  explicitly prohibits attendees, private people, minors, confessions, and
  personal information.
- The server retains opaque account association only for authorization,
  duplicate prevention, score integrity, and returning a player to their alias.

## Admin And Display

- `/admin/games` retains detailed Two Truths operations and adds four
  independent game control cards.
- MMF includes a ten-trio editor, optional image URLs, and configurable third
  action label.
- Prompt games include independent prompt decks, enable/disable/remove prompt
  controls, response/vote counts, round controls, and leaderboards.
- Ended games provide Start, Previous, and Next announcer presentation controls,
  direct winner/results cards, and normal-rotation resume.
- MMF presentation walks through each trio and action total. Prompt presentation
  walks through each revealed prompt and winning anonymous response.
- Ended winner/scoreboard cards join normal live-display rotation. Prompt
  responses join rotation only during voting/reveal.
- Temporary drink-ready notices retain priority above game event overrides.

## State And Routes

- Redis schema version is `8`.
- `games_state` contains all five independent game records.
- Attendee hub: `GET /party/games?game=<slug>`.
- Anonymous opt-in: `POST /party/games/<slug>/join`.
- MMF ballot round: `POST /party/games/murder-marry-fuck/answers`.
- Prompt response/vote: `POST /party/games/<slug>/response|vote`.
- Admin operations continue through the focused `/admin/games` POST handler.
- Aggregate/redacted download: `GET /admin/export/games`.

## Verification

- `python -m compileall -q main.py party_games.py` passed.
- `python -m pytest -q` passed with 134 tests and 8 subtests.
- Coverage includes schema migration, every game variant, MMF 30-point ties,
  aggregate-only export, invalid assignments, prompt voting, self-vote
  rejection, display anonymity, result presentation, and resets.
- Browser QA exercised the dashboard, game tabs, adult-content notice,
  anonymous opt-in, multi-game admin enable/start controls, prompt selection,
  the 10-round configuration presence, and desktop overflow at 1280px.
- Active MMF, prompt submission, and prompt voting templates have dedicated
  authenticated route-render regression tests.

## Publication Status

Implementation, tests, and local browser QA are complete on
`agent/add-remaining-party-games`. Commit, PR, merge, production deployment,
and smoke verification are the remaining publication steps.
