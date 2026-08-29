# Game Reset, Party Wrap-Up, History, Analytics, And Recap Email Plan

## Status

**Implementation committed, pushed, and active in production on both API
instances. Public Halloween and GoodVines isolation checks pass. Email/browser
visual QA, a host-only production test email, and deployment-workflow hardening
remain pending.**

This file is both the implementation specification and the durable progress
tracker. Update it in the same commit as each implementation milestone:

- change checklist items from `[ ]` to `[x]` only after the code and milestone
  verification are complete;
- keep the Current Milestone and Next Action fields accurate;
- record important scope or data-model changes in the Decision Log;
- record exact test commands and results in the Verification Log; and
- do not mark the project complete until every release gate is satisfied.

**Current milestone:** Milestone 10 — released with operational follow-up

**Next action:** harden the GitHub Actions rollout so a Halloween service restart
cannot make the shared Auto Scaling Group replace an otherwise healthy API
instance, then perform the remaining browser/email visual QA and optional
host-only production test email.

**Implemented Redis schema:** `18`.

## Objective

Provide a safe, test-friendly game reset and an end-of-party workflow that:

1. resets one game or all games without typed confirmation phrases;
2. lets the host repeatedly return all games to pristine testing defaults;
3. finalizes real game and costume results into durable official history;
4. credits confirmed attendees and linked winners with idempotent recognition;
5. freezes the resulting jukebox playlist and privacy-safe party analytics;
6. previews and sends personalized recap emails through Halloween SES;
7. automatically erases mutable game data, bar orders, specialty allowances,
   and drink-ready notices only after every official recap email has been
   accepted by SES;
8. gives admins organized, per-edition historical game views and explicit data
   retention/deletion controls; and
9. provides synthetic and current-database test emails that cannot finalize,
   award, contact guests, or trigger cleanup.

## Non-Negotiable Invariants

- Official archives, recap snapshots, attendance credits, winner credits, and
  earned achievements survive ordinary game resets.
- Mutable game data is erased after successful official recap delivery.
- A partial email failure never triggers cleanup.
- Test preview/send actions never mutate party state or official delivery state.
- Simulated results can never become official or grant recognition.
- Private MMF ballots are never exported, emailed, or historically archived.
- Blind prompt-voting authorship is never exported, emailed, or historically
  archived.
- Anonymous-mode real names and account IDs never enter attendee email, public
  history, analytics, or downloadable historical exports.
- Every mutation remains admin-authenticated, CSRF-protected, Redis-locked,
  idempotent where retry is possible, and compatible with the existing
  progressive admin-panel replacement.
- Halloween email continues to use `no-reply@tnq-halloween.com` through the
  existing isolated SES identity. Do not change GoodVines identities, source,
  services, nginx blocks, or Vault paths.
- No typed reset confirmation phrases remain. Destructive actions use concise
  confirmation popups with accurate consequences.

## Terminology And Data Boundaries

### Mutable game data

The active `games_state` records: participants, statements, guesses, answers,
responses, votes, scores, winners, round state/results, simulations,
presentations, and current configuration.

### Pristine game state

A fresh code-defined game record with built-in prompts/MMF trios restored. A
global reset disables all games; an individual reset preserves the selected
game's enabled flag.

### Official result

The existing privacy-safe `result_archives` summary used by Results, Hall of
Fame, winner recognition, and recap presentation.

### Detailed historical archive

An optional, sanitized, admin-only snapshot stored separately from active state
and official summaries. It must never contain private MMF ballots, blind voter
identity links, anonymous players' real names, or account IDs.

### Party recap

An immutable per-edition snapshot of official results, playlist, analytics,
selected attendees, created credits, personalized achievement changes, email
delivery status, retention choices, and cleanup status.

## Retention Matrix

| Data | Reset one | Reset all for testing | Successful wrap-up cleanup |
|---|---:|---:|---:|
| Selected/current mutable game data | Clear selected | Clear all | Clear all |
| Code-defined game defaults | Restore | Restore | Restore |
| Enabled flags | Preserve selected | Disable all | Disable all |
| Draft/simulated current-event archives | Clear selected draft | Clear all | Clear all |
| Official result archives | Preserve | Preserve | Preserve unless explicit full-history deletion was selected |
| Detailed historical archives | Preserve | Preserve | Follow each game's retention choice |
| Winner and attendance credits | Preserve | Preserve | Preserve unless their source archive is explicitly deleted |
| Recaps, analytics, and delivery ledgers | Preserve | Preserve | Preserve |
| Costume, karaoke, accounts, and RSVP state | Preserve | Preserve | Preserve |
| Bar orders, allowances, and drink-ready notices | Preserve | Preserve | Clear |
| Privacy-safe bar aggregate snapshot | N/A | N/A | Preserve in wrap-up analytics |
| Mutable game/bar data in Redis backups | Existing selected-reset behavior | Sanitize game data | Sanitize game and bar data |

## Proposed Code Organization

Keep `main.py` as the Flask integration point while moving pure and testable
logic into focused modules:

- `party_wrapup.py`
  - schema normalization for recap and detailed-history records;
  - readiness evaluation;
  - immutable recap construction;
  - retention policy normalization;
  - delivery and cleanup state transitions; and
  - snapshot sanitization helpers that have no Flask/Redis/SES dependency.
- `recap_analytics.py`
  - privacy-safe aggregate calculations;
  - deterministic synthetic recap fixtures; and
  - email-safe chart view models with bounded percentages and text fallbacks.
- `main.py`
  - Redis/global-state integration;
  - admin routes/actions and state locking;
  - official archive/recognition orchestration;
  - SES calls;
  - view-model construction; and
  - display cleanup/broadcasts.
- `templates/_admin_wrapup.html`
  - readiness, roster, retention, preview, delivery, cleanup, and Email Test Lab.
- `templates/_admin_game_history.html`
  - edition/game filters, summaries, detailed views, exports, and deletion.
- `templates/email/party_recap.html`
  - shared official/test HTML rendering with inline email-safe charts.

If implementation shows that a new module adds needless indirection, keep the
function names and boundaries but colocate the smallest helpers in `main.py`.
Do not create a new service layer solely for architectural symmetry.

## Proposed State Model

### `event_wrapups`

Dictionary keyed by `event_id`. Each normalized record contains:

- `id`, `event_id`, `year`, `title`, and `date`;
- `status`: `draft`, `finalized`, `sending`, `delivery_failed`, `sent`,
  `cleanup_pending`, `cleanup_failed`, or `complete`;
- `created_at`, `finalized_at`, `sent_at`, `cleanup_started_at`, and
  `completed_at`;
- `game_archive_ids` and `costume_archive_id`;
- privacy-safe `game_results` and `costume_result` snapshots;
- `playlist_snapshot`;
- `analytics_snapshot`;
- selected attendee account IDs and created attendance/winner credit IDs;
- per-account newly unlocked achievement keys;
- per-game historical retention choices;
- recipient delivery ledger; and
- bounded admin/error audit metadata without secrets or copied raw ballots.

### `game_data_archives`

Dictionary keyed by `<event-id>:game:<game-key>`. Each record contains:

- event/game identity, title, engine, and timestamps;
- related official result archive ID;
- participant count and selected public identity mode;
- sanitized engine-specific detail;
- retention state: `detailed`, `summary_only`, or `deleted`;
- preserved/deleted timestamps; and
- bounded audit metadata.

### Delivery entry

One entry per intended attendee:

- `account_id`, normalized recipient email, and display name;
- personalization snapshot/reference;
- `status`: `pending`, `sending`, `sent`, or `failed`;
- attempt count, last attempt, SES acceptance time, and bounded error text.

Do not store rendered HTML/text bodies when the immutable recap payload is
sufficient to reproduce them.

### Test-send audit

A bounded list containing only mode, destination, requested/sent timestamps,
success/failure, and bounded error text. Never store a duplicate real-data
payload or let test records enter the official recipient ledger.

## Workflow A — Individual Reset

UI:

- retain the selected game's danger area;
- remove the typed phrase label/input and `reset_phrase` view-model field;
- render one `Reset Game` danger button; and
- use `onsubmit="return confirm(...)"`, compatible with the existing admin
  inline-form controller and normal navigation fallback.

Server behavior:

1. authenticate admin and validate CSRF through existing hooks;
2. write the existing recoverable backup;
3. replace only the selected game with its pristine code-defined state;
4. preserve its enabled flag;
5. clear matching game display overrides/pins/cards;
6. remove only a replaceable current-event draft/simulation for that game;
7. preserve official/detailed history and recognition; and
8. broadcast once.

Consolidate the separate Two Truths handler through the shared reset helper.

## Workflow B — Reset All Games For Testing

UI:

- place `Reset All Games` beside `Download All Game Data` in the Games heading;
- show counts of current players, ended real games, simulations, and unpublished
  drafts in the confirmation message when available; and
- recommend Wrap-Up first when apparent non-simulated real play exists.

Server behavior:

1. run under the existing admin POST state lock;
2. replace all five games with pristine defaults and disable them;
3. delete current-event draft/simulated game archives, never official archives;
4. clear game-result card settings, pinned game/card, and game event overrides;
5. resume center rotation when a game result card was pinned;
6. sanitize mutable game/test data from retained state backups while preserving
   unrelated and official data;
7. persist atomically or restore the pre-mutation in-memory snapshot on failure;
8. broadcast once; and
9. report exactly what was cleared and preserved.

## Workflow C — Wrap-Up Readiness And Attendance

Add `wrapup` to `ADMIN_WORKSPACES`. The workspace order is:

1. readiness checklist;
2. attendance roster;
3. per-game retention choices;
4. result/playlist/analytics preview;
5. finalization;
6. Email Test Lab;
7. official delivery; and
8. cleanup/progress report.

Readiness blocks finalization when:

- a game with participants has not ended;
- an included game is simulated;
- an ended played game lacks a usable result snapshot;
- the costume winner is not locked;
- the selected attendance roster is empty; or
- a selected attendee lacks a usable party-account email.

It warns, but does not necessarily block, when winner links are missing. Unplayed
games are excluded rather than treated as errors.

Attendance roster behavior:

- list every party account with name/email;
- suggest accounts with game, costume, karaoke, drink-order, or jukebox-request
  activity;
- show suggestion reasons;
- support Select All and explicit inclusion/exclusion; and
- flag known attendees without linked accounts for host resolution.

Each selected account receives one idempotent current-edition attendance
credit. Add a visible threshold-one `party_attendee` achievement, then preserve
the existing Returning Reveler, Seasoned Spirit, Halloween Legend, Game
Champion, Costume Champion, and Multi-Game Master derivation.

## Workflow D — Historical Retention Choices

Before finalization, each played game selects one policy:

1. `summary_only` — default/recommended; preserve the official result and
   recognition, erase detailed mutable data after email;
2. `detailed` — preserve a sanitized admin-only detailed archive plus the
   official result; or
3. `delete_all` — include the game in this outgoing recap, then remove its
   official/detailed stored history and associated winner recognition during
   cleanup.

The UI must state that erased detail cannot be reconstructed and already-sent
emails cannot be recalled.

Detailed archive rules by engine:

- Two Truths: cards, public participant identities, final standings, guess
  counts/accuracy, and optionally sanitized individual guess rows.
- MMF: final standings and round/action aggregates only; never ballots.
- Prompt games: prompt text, revealed responses, aggregate vote totals, round
  winners, final standings, and only the configured public identity.

## Workflow E — Finalization

`Finalize Party Results` is separate from sending email.

Within the existing Redis mutation lock:

1. re-evaluate readiness against freshly loaded state;
2. write a recovery backup;
3. upsert and publish each played non-simulated game archive;
4. award linked tied winners idempotently;
5. upsert/publish the locked costume result and linked winner credit;
6. award selected attendance credits idempotently;
7. calculate pre/post achievement differences per attendee;
8. freeze the final enabled jukebox playlist;
9. build privacy-safe analytics;
10. build optional detailed archives according to retention choices;
11. create/update the immutable wrap-up record; and
12. persist/broadcast once.

Re-running finalization cannot duplicate archives or credits and cannot replace
an already-official result with simulation/test state.

## Workflow F — Jukebox Snapshot

Snapshot each enabled final song with position, title, artist, album, artwork,
duration, explicit flag, Apple Music catalog ID/link, source, and appropriate
request provenance.

Prefer the receiver-confirmed resolved queue order when it is complete and maps
cleanly to saved songs. Otherwise use saved `dj_playlist` order. Label this the
resulting playlist, not an exact played-song history; a future confirmed play
history is separate scope.

## Workflow G — Privacy-Safe Analytics

Calculate analytics before cleanup and store them immutably in the recap:

- credited attendee count;
- games played;
- participation by game and percent of credited attendees;
- engine-appropriate activity/completion metrics;
- compact per-game final leaderboards;
- participation depth (attendees playing 1, 2, 3, or 4+ games);
- costume top-five, ballot count, winning margin, and averages;
- playlist track count, duration, unique artists, explicit/clean counts,
  host/attendee source split, and top artists;
- credits awarded and achievements newly unlocked; and
- safe fun facts such as hardest Two Truths identity, closest prompt vote,
  biggest prompt landslide, most/least unanimous MMF aggregate round, and
  closest costume margin.

Email v1 uses inline table-based horizontal bars and stat cards—no JavaScript,
SVG, CSS background images, or external chart dependency. Every chart includes
visible numeric labels, bounded 0–100% widths, useful alt/heading text, and a
plain-text equivalent.

Recommended official email charts:

1. participation by game;
2. costume leaderboard; and
3. jukebox source composition/top artists.

Keep richer analytics in the admin history/recap view so the email remains
readable.

## Workflow H — Email Test Lab

### Synthetic mode

`Generate Sample Preview` and `Send Sample Test Email` use a deterministic,
in-memory payload that exercises every section: five games, tie, no-winner,
costume results, playlist, charts, attendance, and achievement personas.

Synthetic generation must not populate Redis game state.

### Current-database mode

`Preview Current Party Data` and `Send Current-Data Test Email` derive a
read-only payload from a copied current snapshot. Incomplete sections render
honest states such as in progress, no participants, winner not locked, or no
playlist.

Allow choosing a real account as the personalization model while sending only
to the explicitly entered admin test address.

### Shared safeguards

- default destination to the configured host notification address;
- validate one destination only;
- prefix subject with `[TEST]`;
- render a prominent non-official banner, data source, and timestamp;
- never use the attendee recipient list;
- never archive, award, finalize, mutate, or clean up;
- never enter official delivery status; and
- store only the bounded test-send audit.

Both modes use the same normalized view model and HTML/plain-text renderers as
official delivery.

## Workflow I — Official Personalized Email

The frozen recap preview includes:

- thank-you introduction;
- each played game's winner/tied winners or No Winner outcome;
- compact leaderboards and selected analytics;
- costume winner and leaderboard;
- resulting jukebox playlist with Apple Music links;
- aggregate attendance/achievement statistics;
- a personalized Your Night section; and
- a Results & Hall of Fame link.

Send one SES message per selected attendee to protect addresses and enable
personalization/retry. Never use a shared To/CC recipient list.

The confirmation popup must disclose automatic cleanup:

> Send the party recap to all selected attendees? After every email is
> successfully sent, all current game players, submissions, votes, scores,
> simulations, and display results will be erased. Official results, selected
> historical archives, awards, achievements, playlist analytics, and this recap
> will be preserved.

Treat `sent` as accepted by SES. Record each outcome immediately and retry only
pending/failed recipients. Email failure never rolls back finalized history or
awards.

## Workflow J — Automatic Post-Email Cleanup

When every intended recipient is `sent`:

1. transition to `cleanup_pending` under the state lock;
2. reset all active games to pristine disabled defaults;
3. remove current draft/simulation data;
4. apply each historical retention choice;
5. clear game display cards/pins/overrides and resume rotation;
6. sanitize mutable/deleted game data from Redis backups;
7. preserve official results except explicit `delete_all` selections;
8. preserve recap, analytics, playlist, delivery ledger, attendance, and
   recognition except recognition sourced from explicit full-history deletion;
9. transition to `complete`; and
10. broadcast once.

If cleanup fails, transition to `cleanup_failed`, show `Retry Cleanup`, and do
not resend email. A restart after delivery but before cleanup resumes from the
persisted ledger.

## Workflow K — Organized Game History

Add `game_history` to `ADMIN_WORKSPACES`, grouped as edition → game. Support:

- event, game, and retention-status filters;
- winner/public-identity search;
- edition/game summary counts;
- official result and standings;
- detailed sanitized archive when retained;
- related recognition status;
- stored analytics and recap delivery timestamp;
- JSON export per game or edition;
- `Delete Detailed Data`; and
- `Delete Entire Historical Record`.

Deletion uses popup confirmation, not a typed phrase.

`Delete Detailed Data` hard-deletes detail and sanitizes backups while
preserving official history/recognition/recap summary.

`Delete Entire Historical Record` removes official and detailed storage,
removes the stored recap's view of the record where policy permits, and removes
or revokes source-linked winner credits according to the finalized recognition
audit decision. It must recalculate affected achievements and warn that sent
emails cannot be recalled. Preserve only a minimal non-participant audit event.

Recommended audit policy: revoke linked credits with a clear reason rather than
silently deleting recognition audit rows. Confirm this product choice before
implementing full-history deletion.

## Implementation Milestones And Progress

### Milestone 0 — Baseline And Contracts

- [x] Capture `git status` and protect unrelated user changes.
- [x] Run and record the pre-change Python/JS/test baseline.
- [x] Confirm the next available Redis schema number.
- [x] Confirm the credit deletion-versus-revocation policy.
- [x] Confirm first-attendance achievement title/art direction.
- [x] Freeze route/action/state names in this document.
- [x] Add pure test fixtures for every existing game engine shape.

**Gate:** no application behavior changed; baseline and decisions recorded.

### Milestone 1 — Pure Schema, Reset, And Sanitization Helpers

- [x] Add normalized `event_wrapups` and `game_data_archives` state.
- [x] Add backward-compatible schema migration/defaults/round-trip support.
- [x] Add one pure per-game pristine-state factory boundary.
- [x] Add pure all-game snapshot reset/sanitization helpers.
- [x] Add engine-specific historical sanitizers.
- [x] Add backup-payload sanitization that preserves unrelated fields/TTL.
- [x] Cover malformed/legacy snapshots and idempotent repeated sanitation.

**Gate:** pure/unit tests and schema round trips pass; no UI or SES work yet.

### Milestone 2 — Individual And Global Reset UI/Actions

- [x] Consolidate legacy Two Truths reset handling.
- [x] Remove reset phrases and typed inputs.
- [x] Add confirm-only individual reset forms.
- [x] Add Reset All Games with real-data counts/warnings.
- [x] Clear game display artifacts consistently.
- [x] Ensure atomic persistence and one broadcast.
- [x] Verify inline panel replacement and no-JS form fallback.

**Gate:** reset integration tests, desktop/mobile browser QA, and privacy checks
pass without changing official history.

### Milestone 3 — Wrap-Up State, Readiness, And Attendance

- [x] Add Wrap-Up admin navigation/workspace.
- [x] Build readiness evaluator and actionable errors/warnings.
- [x] Build activity-suggested attendance roster and Select All.
- [x] Add idempotent attendance credit orchestration.
- [x] Add threshold-one Party Attendee achievement.
- [x] Add per-game retention policy controls.
- [x] Persist a draft wrap-up without finalizing side effects.

**Gate:** readiness/roster/credit tests pass; incomplete or simulated party state
cannot be finalized.

### Milestone 4 — Finalization, History Snapshots, And Playlist

- [x] Publish all eligible game archives atomically/idempotently.
- [x] Publish costume result and linked credit.
- [x] Capture tied/no-winner results correctly.
- [x] Freeze receiver-confirmed/fallback playlist order.
- [x] Build detailed archives according to policy.
- [x] Create immutable finalized recap.
- [x] Prevent official overwrite by later simulations.

**Gate:** repeated finalization produces no duplicates; restart/Redis round trip
preserves the exact recap.

### Milestone 5 — Analytics

- [x] Implement privacy-safe aggregate analytics.
- [x] Implement deterministic synthetic analytics fixture.
- [x] Implement email-safe bar/stat view models and text equivalents.
- [x] Cover zero/one/many records, ties, bounds, and divide-by-zero cases.
- [x] Confirm no account IDs, private ballots, or blind voter links appear.

**Gate:** analytics snapshot is deterministic, privacy-reviewed, and unchanged
after current-state mutation.

### Milestone 6 — Email Test Lab

- [x] Add sample/current-data preview modes.
- [x] Add personalization personas/account projection.
- [x] Add single-recipient test send with validation and `[TEST]` labeling.
- [x] Add bounded test-send audit.
- [x] Prove test paths are read-only and cannot enter official state.
- [ ] Render desktop, mobile, and plain-text previews.

**Gate:** SES fake-client tests and browser/email visual QA pass with zero
official-state diffs.

### Milestone 7 — Official Delivery Ledger And Retry

- [x] Freeze official recipient/personalization entries at finalization.
- [x] Send one message per attendee.
- [x] Persist outcome after each recipient.
- [x] Add retry-failed-only action.
- [x] Make restart recovery idempotent.
- [x] Block cleanup until every intended recipient is sent.

**Gate:** partial failure/retry/crash tests prove no duplicate successful sends
and no premature cleanup.

### Milestone 8 — Automatic Cleanup

- [x] Transition sent → cleanup_pending → complete.
- [x] Apply current reset plus historical retention policies.
- [x] Sanitize backups without harming official/unrelated data.
- [x] Add cleanup failure state and Retry Cleanup.
- [x] Prove cleanup is repeatable and never resends email.
- [x] Verify all five games reload as pristine and disabled.

**Gate:** complete workflow survives forced failure at every state boundary.

### Milestone 9 — Game History Workspace

- [x] Add edition/game/status filters and summary metrics.
- [x] Add engine-specific organized detail views.
- [x] Add per-game/edition privacy-safe exports.
- [x] Add detailed-data deletion.
- [x] Add full-history deletion/revocation and achievement recalculation.
- [x] Add recap/analytics/delivery links.
- [ ] Verify mobile layout and bounded large datasets.

**Gate:** history privacy, deletion cascade, backup sanitation, and export tests
pass.

### Milestone 10 — Documentation, Full Verification, And Release

- [x] Update `PROJECT_OVERVIEW.md`, `FEATURES.md`, `FILE_INVENTORY.md`,
  `ARCHITECTURE.md`, games, recognition, admin UX, and email context.
- [x] Run Python compilation.
- [x] Run the complete pytest suite.
- [x] Run JavaScript syntax/regression checks.
- [x] Run `git diff --check`.
- [ ] Render/inspect HTML email at desktop and mobile widths.
- [ ] Browser-QA Games, Wrap-Up, History, Results, and Account surfaces.
- [x] Verify unauthenticated/admin/CSRF boundaries.
- [ ] Deploy through the existing GitHub Actions → AWS SSM path.
- [x] Verify Halloween health and GoodVines isolation.
- [ ] Perform a reversible production test-email smoke test to the host only.
- [x] Record commit, workflow run, release path, and production verification.

**Gate:** all acceptance criteria pass and the progress/status section is marked
complete with evidence.

## Verification Matrix

### Reset

- [x] Individual reset needs no phrase and preserves enabled state/history.
- [x] Reset All needs no phrase and resets every engine/default.
- [x] Current/draft/simulation data is absent after Redis reload.
- [x] Official history, recognition, recap, and unrelated state survive.
- [x] Backup payloads obey the same retention boundary.

### Finalization And Recognition

- [x] Unended played games block finalization.
- [x] Simulations block official inclusion.
- [x] Ties and No Winner outcomes remain accurate.
- [x] Attendance/winner credits are created exactly once.
- [x] Achievement thresholds and post-deletion recalculation are correct.
- [x] Unlinked winners remain public history without false account awards.

### Analytics And History

- [x] Charts match source values and remain bounded/readable.
- [x] Scoring systems are not compared with misleading shared scales.
- [x] Detailed archive contents obey each engine's privacy policy.
- [x] Summary/detail/full deletion has the documented cascade.
- [x] Sent email is never represented as recallable.

### Test Email

- [x] Synthetic email fills every section deterministically.
- [x] Current-data email exactly reflects the copied Redis state.
- [x] Incomplete sections render honest warnings.
- [x] Only the entered test recipient is contacted.
- [x] Test paths create no official side effects or cleanup.

### Official Email And Cleanup

- [ ] HTML/plain text contain equivalent core results.
- [x] Recipients are isolated and personalization is correct.
- [x] Partial failure preserves mutable game data.
- [x] Retry contacts only failed/pending recipients.
- [x] All-success delivery triggers cleanup exactly once.
- [ ] Restart resumes sending or cleanup at the correct boundary.
- [x] Cleanup preserves recap, analytics, playlist, history, and awards per
  retention policy.

### Security And Operations

- [x] Admin auth and CSRF protect every action.
- [x] No secrets, account IDs, anonymous real names, or private votes leak.
- [x] SES remains restricted to the Halloween identity/sender.
- [x] GoodVines code/services/nginx/identities remain untouched.

## Progress Summary

| Milestone | Status | Evidence |
|---|---|---|
| 0. Baseline and contracts | Complete | Dirty-worktree inventory and pre-change test baseline recorded. |
| 1. Schema/reset helpers | Complete | Schema 18 helpers plus pure/round-trip tests. |
| 2. Reset UI/actions | Implemented; browser QA pending | Phrase-free individual/global integration tests pass. |
| 3. Wrap-Up/readiness/attendance | Complete | Draft/finalize/attendance integration tests pass. |
| 4. Finalization/history/playlist | Complete | Frozen real-data recap and retention tests pass. |
| 5. Analytics | Complete | Deterministic chart/privacy unit tests pass. |
| 6. Email Test Lab | Implemented; visual QA pending | Fake-SES current/sample side-effect tests pass. |
| 7. Official delivery/retry | Complete | Per-recipient persistence and failed-only retry tests pass. |
| 8. Automatic cleanup | Complete | Partial-failure preservation and all-success cleanup tests pass. |
| 9. Game History workspace | Implemented; browser QA pending | Filter/export/detail/delete privacy tests pass. |
| 10. Verification/release | Released; visual QA and rollout hardening pending | Commit `98be60f` is on `origin/main` and active on both API instances; 210 tests + 21 subtests and public health checks pass. |

## Decision Log

| Date | Decision | Reason |
|---|---|---|
| 2026-08-29 | Separate testing reset from durable official history. | Hosts need repeatable QA without erasing real results or awards. |
| 2026-08-29 | Cleanup starts only after every official recipient is accepted by SES. | Partial delivery must remain recoverable and must not erase source data. |
| 2026-08-29 | Store recap/analytics/playlist before cleanup. | Email retry and historical viewing cannot depend on mutable game state. |
| 2026-08-29 | Default historical retention is official summary only. | Preserve meaningful results while minimizing private/raw data retention. |
| 2026-08-29 | Use email-native HTML bars for v1 charts. | Reliable rendering without JavaScript, remote images, or a new chart pipeline. |
| 2026-08-29 | Synthetic email data is in-memory, not written to Redis. | Full visual testing should not contaminate party state. |
| 2026-08-29 | Test email can project a real account but sends only to an explicit admin address. | Validate personalization without contacting guests. |
| 2026-08-29 | Full-history deletion revokes source-linked winner credits with a reason. | Preserve the existing append-style recognition audit while immediately recalculating derived achievements. |
| 2026-08-29 | Party Attendee reuses the Returning Reveler emblem for this local implementation. | Avoid introducing unreviewed generated artwork during a parallel dirty-worktree change; a dedicated emblem can replace the path later. |
| 2026-08-29 | SES network calls release the request state lock; outcomes persist under short locks. | Avoid lock expiry during multi-recipient delivery and preserve completed outcomes across partial failure. |
| 2026-08-29 | Initially do not commit, push, deploy, or send a production smoke email. | The user's initial parallel-work constraint; later superseded for commit/push/deploy by an explicit instruction, while the production test email remains unsent. |
| 2026-08-29 | Treat replacement-instance bootstrap verification as the completed release after the SSM workflow raced Auto Scaling health replacement. | Both current instances independently reported release `98be60f46fb417032008c07f4f096e19f81f4f2e`, active service state, and healthy Redis-backed local responses; rerunning the unsafe rollout would cause more avoidable instance churn. |

## Verification Log

| Date | Milestone | Command/check | Result |
|---|---|---|---|
| 2026-08-29 | 0 | `python -m compileall -q main.py party_games.py recognition.py && python -m pytest -q` | Pre-change baseline: 196 passed, 21 subtests passed. |
| 2026-08-29 | 1–9 | Focused pure/integration pytest runs | Reset, draft, test email, finalization, partial delivery, retry, cleanup, history, export, and schema tests passed. |
| 2026-08-29 | 10 | `python -m compileall -q main.py party_wrapup.py recap_analytics.py recognition.py` | Passed. |
| 2026-08-29 | 10 | Bundled Node `--check static/wrapup-admin.js` | Passed. |
| 2026-08-29 | 10 | `python -m pytest -q` | 210 passed, 21 subtests passed in 37.73s. |
| 2026-08-29 | 10 | Commit/push | `98be60f46fb417032008c07f4f096e19f81f4f2e` (`Add party wrap-up and consolidate menu orders`) pushed to `origin/main`; local `main` matches remote. |
| 2026-08-29 | 10 | GitHub Actions run `33259498419` | Validation passed twice. SSM rollout failed because ALB health replacement removed each selected instance during its service restart; public smoke step therefore did not run in the workflow. |
| 2026-08-29 | 10 | SSM read-only verification on `i-00874dc476ea795e3` and `i-069299cb23a5a9979` | Both replacement instances reported `/opt/halloween/releases/98be60f46fb417032008c07f4f096e19f81f4f2e`, active `halloween-party`, and Redis DB 1 health `ok`. |
| 2026-08-29 | 10 | Public smoke: Halloween apex/www, RSVP, party login, Wrap-Up/History auth redirects, and `appg-v.com/health` | Passed. Apex and www responses reached different healthy Halloween instances; GoodVines remained online at service version `73a1f39430cb730e50a7713cc16d06e670bcdf0b`. |
| 2026-08-29 | Bar cleanup extension | `python -m pytest -q` | 218 passed, 21 subtests passed; allowance controls, manual reset, wrap-up cleanup, bar analytics, and backup sanitization are covered. |

## Known Risks And Mitigations

- **External email is not transactional.** Persist per-recipient outcomes and
  make send/cleanup transitions idempotent.
- **Cleanup can destroy unfinalized real data.** Show readiness warnings and
  freeze official recap/history before official send.
- **Backups can retain deleted private data.** Sanitize matching fields while
  preserving TTL and unrelated state; test malformed/failure behavior.
- **Large state documents can make admin rendering expensive.** Build lightweight
  history summaries first and detailed models only for the selected archive.
- **Email clients render CSS inconsistently.** Use inline table layouts, visible
  values, text fallbacks, and rendered visual QA.
- **Small-party aggregates can reveal individuals.** Exclude private dimensions
  and suppress/phrase fun facts that would expose a protected identity.
- **Historical deletion can invalidate awards.** Show the cascade before action,
  apply one source-linked policy, and recalculate achievements deterministically.
- **Concurrent admin actions can race sending/cleanup.** Re-evaluate persisted
  state under the existing Redis lock at every transition and never hold the
  lock across SES network calls.
- **The current SSM rollout restarts Halloween while an instance remains an
  InService ELB target.** The brief health-check failure can trigger Auto
  Scaling replacement. Drain or place one instance in Standby for deployment,
  restore it, and wait for healthy target registration before advancing to the
  next instance. The launch-template bootstrap kept this release available and
  installed the exact requested SHA on both replacements.

## Out Of Scope For This Project

- Exact receiver-confirmed history of every jukebox song played.
- Recalling or modifying already-delivered email.
- Restoring a historical archive into a live game.
- Interactive JavaScript charts inside email.
- Exposing raw/private ballots to admins or attendees.
- Contacting RSVP-only recipients as if they had account-linked achievements
  without an explicit attendance/account-link decision.
