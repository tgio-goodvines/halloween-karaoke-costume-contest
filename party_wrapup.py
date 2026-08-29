from __future__ import annotations

import copy
from typing import Any, Iterable

from party_games import (
    GAME_CATALOG,
    MURDER_MARRY_FUCK_GAME_KEY,
    PROMPT_GAME_KEYS,
    TWO_TRUTHS_GAME_KEY,
    empty_mmf_game_state,
    empty_prompt_game_state,
    empty_two_truths_game_state,
    normalize_games_state,
    participant_statements,
)


WRAPUP_STATUSES = {
    "draft",
    "finalized",
    "sending",
    "delivery_failed",
    "sent",
    "cleanup_pending",
    "cleanup_failed",
    "complete",
}
DELIVERY_STATUSES = {"pending", "sending", "sent", "failed"}
RETENTION_POLICIES = {"summary_only", "detailed", "delete_all"}
DEFAULT_RETENTION_POLICY = "summary_only"
TEST_EMAIL_MODES = {"sample", "current"}
GAME_ACHIEVEMENT_KEYS = {"game_champion", "multi_game_master"}


def _text(value: object, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_list(value: object) -> list[dict[str, Any]]:
    return [copy.deepcopy(entry) for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def pristine_game_state(game_key: str, *, enabled: bool = False) -> dict[str, Any]:
    if game_key == TWO_TRUTHS_GAME_KEY:
        return empty_two_truths_game_state(enabled=enabled)
    if game_key == MURDER_MARRY_FUCK_GAME_KEY:
        return empty_mmf_game_state(enabled=enabled)
    if game_key in PROMPT_GAME_KEYS:
        return empty_prompt_game_state(game_key, enabled=enabled)
    raise KeyError(f"Unknown game key: {game_key}")


def reset_games_state(
    raw_games: object,
    *,
    game_keys: Iterable[str] | None = None,
    preserve_enabled: bool = False,
) -> dict[str, Any]:
    normalized = normalize_games_state(raw_games)
    selected = set(game_keys or GAME_CATALOG)
    for game_key in GAME_CATALOG:
        if game_key not in selected:
            continue
        enabled = bool(normalized[game_key].get("enabled")) if preserve_enabled else False
        normalized[game_key] = pristine_game_state(game_key, enabled=enabled)
    return normalized


def game_has_activity(game: object) -> bool:
    if not isinstance(game, dict):
        return False
    return bool(
        game.get("participants")
        or game.get("guesses")
        or game.get("rounds")
        or game.get("phase") in {"active", "ended"}
        or game.get("simulation", {}).get("is_simulated")
    )


def game_reset_counts(raw_games: object) -> dict[str, int]:
    games = normalize_games_state(raw_games)
    return {
        "game_count": len(games),
        "enabled_count": sum(1 for game in games.values() if game.get("enabled")),
        "active_count": sum(1 for game in games.values() if game.get("phase") == "active"),
        "ended_count": sum(1 for game in games.values() if game.get("phase") == "ended"),
        "participant_count": sum(len(game.get("participants", {})) for game in games.values()),
        "simulation_count": sum(
            1 for game in games.values() if game.get("simulation", {}).get("is_simulated")
        ),
    }


def _game_card_matches(card_id: object, game_keys: set[str]) -> bool:
    text = _text(card_id, 160)
    return any(text.startswith(f"games:{game_key}-") for game_key in game_keys)


def is_game_credit(credit: object, game_keys: set[str] | None = None) -> bool:
    if not isinstance(credit, dict):
        return False
    selected = game_keys or set(GAME_CATALOG)
    return bool(
        credit.get("kind") == "game_win"
        and (not credit.get("subject_key") or str(credit.get("subject_key")) in selected)
    ) or str(credit.get("achievement_key", "")) in GAME_ACHIEVEMENT_KEYS


def remove_game_history_from_wrapup(
    raw_wrapup: object,
    *,
    game_key: str,
    official_archive_id: str = "",
) -> dict[str, Any]:
    wrapup = copy.deepcopy(raw_wrapup) if isinstance(raw_wrapup, dict) else {}
    wrapup["game_results"] = [
        result
        for result in _safe_list(wrapup.get("game_results", []))
        if str(result.get("game_key", "")) != game_key
    ]
    if official_archive_id and isinstance(wrapup.get("game_archive_ids"), list):
        wrapup["game_archive_ids"] = [
            archive_id
            for archive_id in wrapup["game_archive_ids"]
            if str(archive_id) != official_archive_id
        ]
    policies = wrapup.get("retention_policies", {})
    if isinstance(policies, dict):
        policies[game_key] = "delete_all"
    analytics = wrapup.get("analytics_snapshot", {})
    if isinstance(analytics, dict):
        for field in ("participation_by_game", "activity_by_game"):
            analytics[field] = [
                row
                for row in _safe_list(analytics.get(field, []))
                if str(row.get("game_key", "")) != game_key
            ]
        leaderboards = analytics.get("leaderboards", {})
        if isinstance(leaderboards, dict):
            leaderboards.pop(game_key, None)
        analytics["games_played"] = len(wrapup["game_results"])
        analytics["total_game_participations"] = sum(
            _nonnegative_int(result.get("participant_count"))
            for result in wrapup["game_results"]
        )
        analytics["total_game_interactions"] = sum(
            _nonnegative_int(row.get("value"))
            for row in analytics.get("activity_by_game", [])
            if isinstance(row, dict)
        )
        analytics["participation_depth"] = []
    # Per-person totals cannot be safely recomputed from the remaining public
    # archive. Remove them instead of keeping a misleading/deleted game count.
    wrapup["personal_summaries"] = {}
    return wrapup


def sanitize_mutable_game_data(
    raw_snapshot: object,
    *,
    game_keys: Iterable[str] | None = None,
    preserve_enabled: bool = False,
    preserve_official: bool = True,
    delete_official_for: Iterable[str] | None = None,
    delete_official_archive_ids: Iterable[str] | None = None,
    delete_detailed_archive_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a copy with selected mutable game data removed.

    This helper deliberately preserves unrelated state. It is suitable for the
    canonical state document and retained full-state backup payloads.
    """

    snapshot = copy.deepcopy(raw_snapshot) if isinstance(raw_snapshot, dict) else {}
    selected = set(game_keys or GAME_CATALOG)
    delete_official = set(delete_official_for or ())
    official_archive_ids = set(delete_official_archive_ids or ())
    detailed_archive_ids = set(delete_detailed_archive_ids or ())
    deleted_event_games = {
        (str(archive.get("event_id", "")), str(archive.get("subject_key", "")), str(archive.get("id", "")))
        for archive in _safe_list(snapshot.get("result_archives", []))
        if str(archive.get("id", "")) in official_archive_ids
    }
    snapshot["games_state"] = reset_games_state(
        snapshot.get("games_state", {}),
        game_keys=selected,
        preserve_enabled=preserve_enabled,
    )

    archives = []
    for archive in _safe_list(snapshot.get("result_archives", [])):
        game_key = str(archive.get("subject_key", ""))
        if archive.get("kind") != "game" or game_key not in selected:
            if str(archive.get("id", "")) not in official_archive_ids:
                archives.append(archive)
            continue
        if str(archive.get("id", "")) in official_archive_ids:
            continue
        if game_key in delete_official:
            continue
        if preserve_official and archive.get("status") == "official":
            archives.append(archive)
    snapshot["result_archives"] = archives

    detailed = snapshot.get("game_data_archives", {})
    if isinstance(detailed, dict):
        snapshot["game_data_archives"] = {
            archive_id: copy.deepcopy(archive)
            for archive_id, archive in detailed.items()
            if not (
                isinstance(archive, dict)
                and (
                    str(archive_id) in detailed_archive_ids
                    or str(archive.get("game_key", "")) in delete_official
                    or str(archive.get("official_archive_id", "")) in official_archive_ids
                )
            )
        }

    if delete_official or official_archive_ids:
        snapshot["recognition_credits"] = [
            copy.deepcopy(credit)
            for credit in _safe_list(snapshot.get("recognition_credits", []))
            if not (
                str(credit.get("source_ref", "")) in official_archive_ids
                or (
                    is_game_credit(credit, delete_official)
                    and str(credit.get("subject_key", "")) in delete_official
                )
            )
        ]

    raw_wrapups = snapshot.get("event_wrapups", {})
    if isinstance(raw_wrapups, dict) and (delete_official or deleted_event_games):
        updated_wrapups = copy.deepcopy(raw_wrapups)
        for event_id, raw_wrapup in list(updated_wrapups.items()):
            for deleted_event_id, game_key, archive_id in deleted_event_games:
                if str(event_id) == deleted_event_id:
                    raw_wrapup = remove_game_history_from_wrapup(
                        raw_wrapup,
                        game_key=game_key,
                        official_archive_id=archive_id,
                    )
            if delete_official:
                for game_key in delete_official:
                    raw_wrapup = remove_game_history_from_wrapup(
                        raw_wrapup,
                        game_key=game_key,
                    )
            updated_wrapups[str(event_id)] = raw_wrapup
        snapshot["event_wrapups"] = updated_wrapups

    display_config = snapshot.get("display_config")
    if isinstance(display_config, dict):
        configured = display_config.get("game_result_card_enabled", {})
        if isinstance(configured, dict):
            display_config["game_result_card_enabled"] = {
                str(card_id): bool(enabled)
                for card_id, enabled in configured.items()
                if not _game_card_matches(card_id, selected)
            }
        if str(display_config.get("pinned_game_key", "")) in selected:
            display_config["pinned_game_key"] = ""

    display_runtime = snapshot.get("display_runtime")
    if isinstance(display_runtime, dict) and _game_card_matches(
        display_runtime.get("pinned_card_id"), selected
    ):
        display_runtime["pinned_card_id"] = ""
        display_runtime["center_paused"] = False

    for override_key in ("live_display_event_override", "live_display_override"):
        override = snapshot.get(override_key)
        if isinstance(override, dict) and str(override.get("type", "")).startswith("game_"):
            snapshot[override_key] = None
    return snapshot


def _public_participant_names(game: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    by_account: dict[str, str] = {}
    by_player: dict[str, str] = {}
    anonymous = bool(game.get("anonymous_mode"))
    participants = game.get("participants", {})
    if not isinstance(participants, dict):
        return by_account, by_player
    for account_id, participant in participants.items():
        if not isinstance(participant, dict):
            continue
        name = _text(
            participant.get("alias") if anonymous else participant.get("display_name"),
            80,
        ) or _text(participant.get("alias"), 80) or "Player"
        by_account[str(account_id)] = name
        player_id = _text(participant.get("player_id"), 120)
        if player_id:
            by_player[player_id] = name
    return by_account, by_player


def _safe_scores(raw_scores: object) -> list[dict[str, Any]]:
    scores = []
    for index, entry in enumerate(_safe_list(raw_scores)):
        name = _text(entry.get("name") or entry.get("alias"), 80) or "Player"
        try:
            accuracy = float(entry.get("accuracy", 0) or 0)
        except (TypeError, ValueError):
            accuracy = 0.0
        scores.append(
            {
                "rank": _nonnegative_int(entry.get("rank")) or index + 1,
                "name": name,
                "points": _nonnegative_int(entry.get("points", entry.get("correct", 0))),
                "attempts": _nonnegative_int(entry.get("attempts")),
                "accuracy": max(0.0, min(100.0, accuracy)),
            }
        )
    return scores


def build_detailed_game_archive(
    game_key: str,
    raw_game: object,
    *,
    event_id: str,
    year: str,
    archived_at: str,
    official_archive_id: str,
) -> dict[str, Any]:
    game = normalize_games_state({game_key: raw_game})[game_key]
    base: dict[str, Any] = {
        "id": f"{event_id}:game-data:{game_key}",
        "event_id": _text(event_id, 80),
        "year": _text(year, 12),
        "game_key": game_key,
        "title": GAME_CATALOG[game_key]["title"],
        "engine": GAME_CATALOG[game_key]["engine"],
        "official_archive_id": _text(official_archive_id, 160),
        "participant_count": len(game.get("participants", {})),
        "anonymous_mode": bool(game.get("anonymous_mode")),
        "archived_at": _text(archived_at, 180),
        "retention_status": "detailed",
        "deleted_at": "",
        "scores": _safe_scores(game.get("results", {}).get("scores", [])),
        "detail": {},
    }

    if game_key == TWO_TRUTHS_GAME_KEY:
        participants = game.get("participants", {})
        submissions: dict[str, str] = {}
        people = []
        if isinstance(participants, dict):
            for participant in participants.values():
                if not isinstance(participant, dict):
                    continue
                submission_id = _text(participant.get("submission_id"), 120)
                name = _text(participant.get("answer_name"), 80) or "Guest"
                if submission_id:
                    submissions[submission_id] = name
                people.append(
                    {
                        "name": name,
                        "statements": [_text(item, 240) for item in participant_statements(participant)],
                    }
                )
        guesses = []
        raw_guesses = game.get("guesses", {})
        if isinstance(raw_guesses, dict):
            for guesser_id, entries in raw_guesses.items():
                guesser = participants.get(guesser_id, {}) if isinstance(participants, dict) else {}
                guesser_name = _text(guesser.get("answer_name"), 80) if isinstance(guesser, dict) else ""
                if not isinstance(entries, dict):
                    continue
                for submission_id, guess in entries.items():
                    if not isinstance(guess, dict):
                        continue
                    guesses.append(
                        {
                            "guesser": guesser_name or "Guest",
                            "target": submissions.get(str(submission_id), "Guest"),
                            "entered": _text(guess.get("guessed_name"), 80),
                        }
                    )
        base["detail"] = {"participants": people, "guesses": guesses}
        return base

    _, by_player = _public_participant_names(game)
    if game_key == MURDER_MARRY_FUCK_GAME_KEY:
        rounds = []
        for index, result in enumerate(_safe_list(game.get("results", {}).get("round_results", []))):
            rounds.append(
                {
                    "round": index + 1,
                    "people": [_text(person.get("name"), 80) for person in result.get("people", []) if isinstance(person, dict)],
                    "totals": copy.deepcopy(result.get("totals", {})) if isinstance(result.get("totals"), dict) else {},
                    "pluralities": copy.deepcopy(result.get("pluralities", {})) if isinstance(result.get("pluralities"), dict) else {},
                    "respondent_count": _nonnegative_int(result.get("respondent_count")),
                }
            )
        base["detail"] = {"rounds": rounds, "explicit_label": _text(game.get("explicit_label"), 24)}
        return base

    rounds = []
    for index, game_round in enumerate(_safe_list(game.get("rounds", []))):
        results = game_round.get("results", {}) if isinstance(game_round.get("results"), dict) else {}
        vote_counts = results.get("vote_counts", {}) if isinstance(results.get("vote_counts"), dict) else {}
        responses = []
        raw_responses = game_round.get("responses", {})
        if isinstance(raw_responses, dict):
            for response_id, response in raw_responses.items():
                if not isinstance(response, dict):
                    continue
                responses.append(
                    {
                        "name": by_player.get(str(response.get("player_id", "")), "Player"),
                        "text": _text(response.get("text"), 280),
                        "votes": _nonnegative_int(vote_counts.get(str(response_id))),
                        "winner": str(response_id) in set(results.get("winner_response_ids", [])),
                    }
                )
        rounds.append(
            {
                "round": index + 1,
                "prompt": _text(game_round.get("prompt_text"), 240),
                "responses": responses,
                "vote_count": _nonnegative_int(results.get("vote_count")),
            }
        )
    base["detail"] = {"rounds": rounds}
    return base


def normalize_game_data_archives(raw: object) -> dict[str, dict[str, Any]]:
    source = raw if isinstance(raw, dict) else {}
    archives: dict[str, dict[str, Any]] = {}
    for raw_id, raw_archive in source.items():
        if not isinstance(raw_archive, dict):
            continue
        archive_id = _text(raw_archive.get("id") or raw_id, 180)
        game_key = _text(raw_archive.get("game_key"), 100)
        event_id = _text(raw_archive.get("event_id"), 80)
        status = _text(raw_archive.get("retention_status"), 40)
        if not archive_id or not event_id or game_key not in GAME_CATALOG:
            continue
        archives[archive_id] = {
            "id": archive_id,
            "event_id": event_id,
            "year": _text(raw_archive.get("year"), 12),
            "game_key": game_key,
            "title": _text(raw_archive.get("title"), 160) or GAME_CATALOG[game_key]["title"],
            "engine": GAME_CATALOG[game_key]["engine"],
            "official_archive_id": _text(raw_archive.get("official_archive_id"), 180),
            "participant_count": _nonnegative_int(raw_archive.get("participant_count")),
            "anonymous_mode": bool(raw_archive.get("anonymous_mode")),
            "archived_at": _text(raw_archive.get("archived_at"), 180),
            "retention_status": status if status in {"detailed", "summary_only", "deleted"} else "detailed",
            "deleted_at": _text(raw_archive.get("deleted_at"), 180),
            "scores": _safe_scores(raw_archive.get("scores", [])),
            "detail": copy.deepcopy(raw_archive.get("detail", {})) if isinstance(raw_archive.get("detail"), dict) else {},
        }
    return archives


def normalize_delivery_entries(raw: object) -> list[dict[str, Any]]:
    entries = []
    seen: set[str] = set()
    for raw_entry in _safe_list(raw):
        account_id = _text(raw_entry.get("account_id"), 120)
        email = _text(raw_entry.get("email"), 320).casefold()
        status = _text(raw_entry.get("status"), 40)
        key = account_id or email
        if not key or key in seen or "@" not in email:
            continue
        entries.append(
            {
                "account_id": account_id,
                "email": email,
                "name": _text(raw_entry.get("name"), 80) or "Guest",
                "status": status if status in DELIVERY_STATUSES else "pending",
                "attempt_count": _nonnegative_int(raw_entry.get("attempt_count")),
                "last_attempt_at": _text(raw_entry.get("last_attempt_at"), 180),
                "sent_at": _text(raw_entry.get("sent_at"), 180),
                "last_error": _text(raw_entry.get("last_error"), 500),
            }
        )
        seen.add(key)
    return entries


def normalize_event_wrapups(raw: object) -> dict[str, dict[str, Any]]:
    source = raw if isinstance(raw, dict) else {}
    wrapups: dict[str, dict[str, Any]] = {}
    for raw_id, raw_wrapup in source.items():
        if not isinstance(raw_wrapup, dict):
            continue
        event_id = _text(raw_wrapup.get("event_id") or raw_id, 80)
        status = _text(raw_wrapup.get("status"), 40)
        if not event_id:
            continue
        raw_policies = raw_wrapup.get("retention_policies", {})
        policies = {
            game_key: (
                str(raw_policies.get(game_key))
                if isinstance(raw_policies, dict) and str(raw_policies.get(game_key)) in RETENTION_POLICIES
                else DEFAULT_RETENTION_POLICY
            )
            for game_key in GAME_CATALOG
        }
        wrapups[event_id] = {
            "id": event_id,
            "event_id": event_id,
            "year": _text(raw_wrapup.get("year"), 12),
            "title": _text(raw_wrapup.get("title"), 160),
            "date": _text(raw_wrapup.get("date"), 80),
            "status": status if status in WRAPUP_STATUSES else "draft",
            "created_at": _text(raw_wrapup.get("created_at"), 180),
            "finalized_at": _text(raw_wrapup.get("finalized_at"), 180),
            "sent_at": _text(raw_wrapup.get("sent_at"), 180),
            "cleanup_started_at": _text(raw_wrapup.get("cleanup_started_at"), 180),
            "completed_at": _text(raw_wrapup.get("completed_at"), 180),
            "last_error": _text(raw_wrapup.get("last_error"), 500),
            "game_archive_ids": [_text(value, 180) for value in raw_wrapup.get("game_archive_ids", []) if _text(value, 180)] if isinstance(raw_wrapup.get("game_archive_ids"), list) else [],
            "costume_archive_id": _text(raw_wrapup.get("costume_archive_id"), 180),
            "game_results": _safe_list(raw_wrapup.get("game_results", [])),
            "costume_result": copy.deepcopy(raw_wrapup.get("costume_result", {})) if isinstance(raw_wrapup.get("costume_result"), dict) else {},
            "playlist_snapshot": _safe_list(raw_wrapup.get("playlist_snapshot", [])),
            "analytics_snapshot": copy.deepcopy(raw_wrapup.get("analytics_snapshot", {})) if isinstance(raw_wrapup.get("analytics_snapshot"), dict) else {},
            "attendee_account_ids": [_text(value, 120) for value in raw_wrapup.get("attendee_account_ids", []) if _text(value, 120)] if isinstance(raw_wrapup.get("attendee_account_ids"), list) else [],
            "attendance_credit_ids": [_text(value, 180) for value in raw_wrapup.get("attendance_credit_ids", []) if _text(value, 180)] if isinstance(raw_wrapup.get("attendance_credit_ids"), list) else [],
            "winner_credit_ids": [_text(value, 180) for value in raw_wrapup.get("winner_credit_ids", []) if _text(value, 180)] if isinstance(raw_wrapup.get("winner_credit_ids"), list) else [],
            "new_achievements": copy.deepcopy(raw_wrapup.get("new_achievements", {})) if isinstance(raw_wrapup.get("new_achievements"), dict) else {},
            "personal_summaries": copy.deepcopy(raw_wrapup.get("personal_summaries", {})) if isinstance(raw_wrapup.get("personal_summaries"), dict) else {},
            "retention_policies": policies,
            "deliveries": normalize_delivery_entries(raw_wrapup.get("deliveries", [])),
        }
    return wrapups


def normalize_test_email_audit(raw: object, *, limit: int = 50) -> list[dict[str, Any]]:
    entries = []
    for raw_entry in _safe_list(raw)[-limit:]:
        mode = _text(raw_entry.get("mode"), 30)
        if mode not in TEST_EMAIL_MODES:
            continue
        entries.append(
            {
                "mode": mode,
                "destination": _text(raw_entry.get("destination"), 320).casefold(),
                "requested_at": _text(raw_entry.get("requested_at"), 180),
                "sent_at": _text(raw_entry.get("sent_at"), 180),
                "success": bool(raw_entry.get("success")),
                "error": _text(raw_entry.get("error"), 500),
            }
        )
    return entries


def all_deliveries_sent(wrapup: object) -> bool:
    if not isinstance(wrapup, dict):
        return False
    deliveries = normalize_delivery_entries(wrapup.get("deliveries", []))
    return bool(deliveries) and all(entry.get("status") == "sent" for entry in deliveries)
