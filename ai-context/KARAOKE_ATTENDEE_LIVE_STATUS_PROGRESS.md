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
- Completed performance notices include a per-user Dismiss action on both
  attendee surfaces. Dismissing removes only that completion instance from the
  signed-in attendee's banner and active personal-song cards; it does not
  delete the karaoke record, admin history, or exports.
- Each song retains an independent notification lifecycle. An acknowledged
  completion cannot suppress Ready, Up Next, Called, On Stage, or Complete
  notices for another song, and completion ties favor the most recently
  completed performance.
- `static/karaoke-live-status.js` refreshes both attendee surfaces every five
  seconds and whenever the tab becomes visible. It rejects stale responses,
  updates the browser title for Up Next and Called states, posts protected
  completion dismissals, reconciles personal-song cards by entry ID, and uses
  text-only DOM construction for refreshed entries.
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

## Completion Acknowledgements

- Redis schema 15 adds bounded `karaoke_completion_acknowledgements` to each
  attendee account. The map stores a karaoke entry ID and its exact
  `completed_at` timestamp, capped at 50 entries per account.
- The completion timestamp makes acknowledgements performance-specific. If a
  host requeues and later completes the same entry, the new timestamp produces
  a new dismissible notice.
- `POST /api/party/karaoke/entries/<entry_id>/dismiss-completion` requires a
  regular-user session and CSRF token, verifies requester/co-singer
  participation, accepts only completed performances, matches the completion
  identifier supplied by the rendered notice to reject stale clicks, and is
  idempotent for that completion instance. Legacy completed entries without a
  timestamp derive a stable fallback identifier until they are re-completed.
- Co-singer acknowledgements are independent; one singer cannot dismiss the
  completion for another singer.

## Data And Security

- The attendee endpoint excludes playlist IDs, operation IDs, history,
  host-only sync errors, OAuth state, YouTube credentials, and other attendees'
  private pending requests.
- Public lineup data remains limited to approved, playlist-synchronized active
  songs while YouTube karaoke is enabled.
- Manual karaoke mode receives the same Ready/Up Next/Called/On Stage attendee
  status without exposing unused YouTube workflow internals.

## Verification

- Full Python suite: 176 tests passed.
- Dependency-free Node suites: 13 tests passed, including four attendee live
  status tests.
- Python compilation, JavaScript syntax checks, and `git diff --check` passed.
- Browser QA confirmed a separate attendee tab changed from Ready to Called
  within one five-second polling window, the overview matched the karaoke page,
  the urgent browser title updated, and the `390x844` layout had no horizontal
  overflow or console errors during the final pass.
- Completion-dismissal browser QA used two sequential songs: the second song's
  Called and Complete states took primary focus over the older completion,
  dismissing the newest completion revealed the older one, dismissing from
  `/party` immediately hid that notice, and `/party/karaoke` then showed no
  acknowledged personal cards. The final browser console had no warnings or
  errors. QA also caught and corrected an author-style override of native
  `[hidden]` behavior before release so Dismiss is visible only for completed
  performances.
- Regression coverage includes atomic completion/advance, stage preservation
  while reordering another song, display-only singer-card replay, stop cleanup,
  co-singer visibility/authorization, safe endpoint output, and stale browser
  response rejection, newest-completion selection, per-song dismissal,
  independent co-singer acknowledgement, Redis persistence, CSRF enforcement,
  re-completion visibility, and the next song's full notification lifecycle.

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
