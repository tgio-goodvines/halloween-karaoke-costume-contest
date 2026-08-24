# Game Results, Rewards, Recognition, And Artwork

## Status

Implemented on August 24, 2026. This work adds attendee-safe live game status,
durable official party history, account-linked achievements, retroactive admin
crediting, and a complete feature/winner artwork system.

## Attendee Experience

- `GET /party/results` is available to every signed-in attendee before, during,
  and after the party. It combines five-second live game updates, completed
  current-game standings, the attendee's earned achievements, attendance
  progress, and the official cross-year Hall of Fame.
- `GET /api/party/games-data` supplies the polling payload with `Cache-Control:
  no-store`. It is regular-role protected and never exposes account IDs, real
  names behind anonymous game aliases, prompt-response authors during blind
  voting, or private MMF ballots.
- The party overview links to Results & Rewards in pre-party and party-night
  modes. Party-night overview/game pages also refresh status every five seconds
  and when the tab returns to the foreground.
- `/party/account` shows the same account achievement collection and attendance
  progress. Recognition follows the stable account ID through display-name
  changes.

## Official Results And History

- Ending any game creates or refreshes one draft result archive for that event
  edition and game. Locking the costume winner creates the equivalent costume
  archive.
- Draft archives snapshot the privacy-safe standings plus internal winner links.
  Game resets do not remove them, so a reset cannot erase history awaiting host
  review.
- Hosts explicitly publish a draft from `/admin/games` or
  `/admin/recognition`. Publication makes the archive official and grants
  idempotent win credits to linked accounts. Tied winners each receive credit;
  legacy winners without an account remain visible in history without receiving
  an account achievement.
- Deterministic test simulations can still drive display QA, but archives marked
  `simulation=true` can never become official or grant recognition.
- The public result payload removes all `winner_links`; only the approved public
  identity and safe summary remain.

## Recognition And Achievements

`recognition.py` owns normalization and derived award logic. Schema version 17
adds:

- `event_editions`: event ID, year, title, and optional date label;
- `result_archives`: draft/official game or costume snapshots;
- `recognition_credits`: append-style attendance, game-win, costume-win, or
  custom credits with optional account association, historical public identity,
  source reference, audit note, and revocation metadata;
- `CostumeSignup.account_id`: stable winner association for current and future
  costume contests.

Derived collection awards are:

- Returning Reveler: two distinct attended editions;
- Seasoned Spirit: three distinct attended editions;
- Halloween Legend: five distinct attended editions;
- Game Champion: at least one official game win;
- Costume Champion: at least one official costume win;
- Multi-Game Master: at least two official game-win credits.

Revoked credits do not count. Duplicate attendance for one edition does not
increase progress. Account deletion unlinks recognition, archived winner links,
and costume entries while retaining historical names and public identities.

## Admin Operations

`/admin/recognition` provides:

- event-edition creation for prior years;
- account-linked attendance and winner credits;
- unlinked legacy winner/custom recognition;
- official result review/publication;
- per-account collections;
- linking a legacy credit to an existing account;
- non-destructive credit revocation with a reason;
- JSON export at `GET /admin/export/recognition`.

The Program workspace can associate admin-created or edited costume entries
with an existing party account, enabling future locked costume winners to be
credited correctly.

## Artwork

Built-in ImageGen produced text-free, style-matched assets using the existing
game illustrations as visual references. All assets use the app's near-black,
crimson, cold-blue, glass-and-metal laboratory language.

- Five completed-game winner cards live in
  `static/images/games/winners/`. Winner/outcome cards and ended-game status
  rails use these trophy variants; neutral status and final-score cards retain
  each game's original illustration.
- Jukebox, bar, menu, and karaoke feature cards live in
  `static/images/features/`. They appear on the party overview, dedicated
  attendee/bartender pages, live bar stage, karaoke cards, and DJ footer. A
  song's album art and a drink's item art still take precedence when present.
- Six transparent achievement emblems live in
  `static/images/achievements/`. They are optimized to 512px PNGs for account,
  results, and admin collection views.

## Operational Invariants

- Current mutable game state and durable official history are separate.
- Publication is explicit and idempotent; simulations are ineligible.
- Public history is safe for every attendee, while internal account associations
  remain admin/persistence-only.
- Polling is used for attendee status rather than adding another long-lived SSE
  connection to the fixed-worker production service.
- Content-specific media wins over generic feature art; generic art supplies a
  complete fallback instead of an empty card.

## Verification

- Pure recognition tests cover thresholds, distinct editions, revocation,
  game/costume awards, normalization, and idempotency.
- Integration tests cover authentication, public-payload redaction, blind-vote
  privacy, tied-winner publication, simulation blocking, retro attendance,
  account deletion/unlinking, dedicated display art, and schema-17 round trips.
- Python compilation, bundled-Node syntax checks, the complete pytest suite,
  template/browser QA, deployment workflow, production health, and GoodVines
  isolation must pass before this document's release section is marked deployed.

## Release

Release uses the existing `main` GitHub Actions → AWS SSM →
`halloween-party.service` path. The implementation commit, workflow run, public
health checks, deployed page/asset checks, and GoodVines isolation result are
reported in the deployment handoff for this change.
