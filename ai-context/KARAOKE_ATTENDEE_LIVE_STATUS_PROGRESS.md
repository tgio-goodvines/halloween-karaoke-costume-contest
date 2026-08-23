# Karaoke Attendee Live Status

## Objective

Keep karaoke workflow, admin stage controls, attendee pages, and the live
display synchronized throughout the event. Requesters and registered
co-singers must see whether a song is awaiting approval, syncing, ready, up
next, called, on stage, completed, skipped, rejected, or cancelled.

## Implemented Behavior

- `GET /api/party/karaoke-data` returns a regular-user-authenticated,
  attendee-safe karaoke view. It includes the signed-in account's songs, the
  safe public lineup, current/next public performers, derived attendee status,
  and `display_update_version`.
- Personal songs include requests owned by the signed-in account and requests
  where the account is a registered singer. Registered co-singers can see the
  status but cannot replace or cancel a request they do not own.
- `/party` shows a live personal karaoke banner and a status-labeled public
  lineup on the party date.
- `/party/karaoke` shows the same live banner, complete status copy on each
  participating song, workflow updates, and public Now Singing/Up Next/Ready
  labels.
- `static/karaoke-live-status.js` refreshes both attendee surfaces every five
  seconds and whenever the tab becomes visible. It rejects stale responses,
  updates the browser title for Up Next and Called states, and uses text-only
  DOM construction for refreshed lineup entries.
- Attendee refresh intentionally uses short polling instead of attendee SSE so
  party traffic does not consume the production Gunicorn worker pool with
  long-lived connections.

## Stage Transition Corrections

- Complete and Advance atomically completes the current performance and calls
  the next ready singer. Skip and Call Next follows the same invariant.
- A displayed Up Next call now always has matching `performance_status=called`,
  `karaoke_state.current_singer_id`, `stage_mode=called`, audit history, and
  display override state.
- Show Singer Card is a display-only action. It no longer repeats or mutates
  the call transition.
- Reordering a non-current song no longer clears the current performer.
- Requeueing the current performer clears their stage timestamps, current
  selection, stage mode, and stale karaoke override.
- Stop and Reset return called/on-stage entries to `waiting` while preserving
  the lineup and completed/skipped history.
- The workflow step label distinguishes Called to stage from On stage.

## Data And Security

- No Redis schema change was required. Existing workflow dimensions and
  current/next stage fields remain authoritative.
- The attendee endpoint excludes playlist IDs, operation IDs, history,
  host-only sync errors, OAuth state, YouTube credentials, and other attendees'
  private pending requests.
- Public lineup data remains limited to approved, playlist-synchronized active
  songs while YouTube karaoke is enabled.
- Manual karaoke mode receives the same Ready/Up Next/Called/On Stage attendee
  status without exposing unused YouTube workflow internals.

## Verification

- Full Python suite: 170 tests passed.
- Dependency-free Node suites: 12 tests passed, including three attendee live
  status tests.
- Python compilation, JavaScript syntax checks, and `git diff --check` passed.
- Browser QA confirmed a separate attendee tab changed from Ready to Called
  within one five-second polling window, the overview matched the karaoke page,
  the urgent browser title updated, and the `390x844` layout had no horizontal
  overflow or console errors during the final pass.
- Regression coverage includes atomic completion/advance, stage preservation
  while reordering another song, display-only singer-card replay, stop cleanup,
  co-singer visibility/authorization, safe endpoint output, and stale browser
  response rejection.

## Event-Night Operator Contract

- Call Next Singer notifies that performer and marks the following ready song
  Up Next.
- Mark On Stage changes the called performer to Now Singing.
- Complete and Advance or Skip and Call Next immediately calls the next ready
  performer.
- Move to End requeues the selected performer. If that performer was current,
  the stage returns to standby until the host calls someone again.
- Restore Display Rotation changes only presentation; it does not alter the
  workflow stage.
