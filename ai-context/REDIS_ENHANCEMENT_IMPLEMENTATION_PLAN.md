# Redis Enhancement Implementation Plan

This file persists the active implementation plan and progress for hardening the
Redis-backed Halloween app state model.

## Goal

Make Redis-backed event state safer for the intended party workflows while
keeping the app compact and consistent with the current Flask/Jinja structure.
The most important correction is to stop coupling costume votes to list indexes.

## Recommended Implementation Order

1. State IDs and schema migration.
2. ID-keyed costume ballots and scoreboard aggregation.
3. ID-based admin actions and active-voting protections.
4. Redis read freshness and display payload versioning.
5. Save/broadcast cleanup and Redis lock timeout behavior.
6. Admin authentication and CSRF protection.
7. Test updates and verification.

## Target State Shape

Schema version 2 should include stable IDs:

```json
{
  "schema_version": 2,
  "costume_signups": [
    {
      "id": "uuid",
      "name": "Ada",
      "costume": "Vampire",
      "contact": ""
    }
  ],
  "karaoke_signups": [
    {
      "id": "uuid",
      "name": "Grace",
      "song_title": "Thriller",
      "artist": "Michael Jackson",
      "youtube_link": ""
    }
  ],
  "costume_ballots": {
    "user-id": {
      "costume-id": 8
    }
  }
}
```

List order can remain the presentation and queue order. IDs provide durable
identity across edits and reorders.

## Feature Decisions

- Keep the single JSON Redis document at `halloween:state`; do not split into
  Redis lists for this app size.
- Keep Redis pub/sub for live-display updates.
- Use IDs in forms instead of indexes.
- Block destructive costume lineup changes while voting is open unless a reset
  flow exists.
- Snapshot final winner/scoreboard state at lock time.
- Add admin auth before treating Redis exports or admin controls as production
  safe.

## Progress Log

- 2026-07-06: Created this implementation tracker before code changes.
- 2026-07-06: Implemented schema version 2 in `main.py` with stable IDs on
  costume and karaoke signups. Existing schema version 1 Redis state migrates on
  load by assigning IDs and converting index-aligned `costume_votes` into
  ID-keyed `costume_ballots`.
- 2026-07-06: Replaced active vote submission and scoreboard aggregation with
  `costume_ballots[user_id][costume_id] = score`. The old `costume_votes` rows
  are rebuilt only as a compatibility artifact in process memory.
- 2026-07-06: Converted admin edit/delete/reorder forms and route handling to
  submit/use `entry_id`, while preserving index fallback for old forms/tests.
- 2026-07-06: Added active-voting protections that block destructive costume
  lineup changes during open voting. Text edits remain allowed.
- 2026-07-06: Added Redis read refresh for important GET routes and included
  `display_update_version` in `/api/display-data`.
- 2026-07-06: Added finite Redis lock wait behavior and avoided duplicate
  post-request saves when a display broadcast already persisted state.
- 2026-07-06: Added lightweight admin authentication via
  `HALLOWEEN_ADMIN_PASSWORD`, `/admin/login`, `/admin/logout`, and CSRF tokens
  on POST forms. In non-production development, admin remains open if no admin
  password is configured.
- 2026-07-06: Added tests for schema migration, ID-keyed voting, reorder-safe
  ballots, active-voting protections, lock contention, admin auth, CSRF, display
  update versioning, backups, and exports. Verified with
  `python3 -m unittest discover -s tests` and
  `python3 -m py_compile main.py tests/test_redis_state.py`.
