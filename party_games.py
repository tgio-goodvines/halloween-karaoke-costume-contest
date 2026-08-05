from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any


TWO_TRUTHS_GAME_KEY = "two_truths_and_a_lie"
GAME_PHASES = {"signup", "active", "ended"}
GAME_STATEMENT_MAX_LENGTH = 240

DEFAULT_TWO_TRUTHS_GAME_STATE: dict[str, Any] = {
    "enabled": False,
    "phase": "signup",
    "started_at": "",
    "ended_at": "",
    "participants": {},
    "guesses": {},
    "results": {
        "finalized_at": "",
        "scores": [],
        "winner_ids": [],
        "participant_results": [],
    },
}

DEFAULT_GAMES_STATE: dict[str, Any] = {
    TWO_TRUTHS_GAME_KEY: copy.deepcopy(DEFAULT_TWO_TRUTHS_GAME_STATE),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_guess_name(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def normalize_statement(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:GAME_STATEMENT_MAX_LENGTH]


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def empty_two_truths_game_state(*, enabled: bool = False) -> dict[str, Any]:
    state = copy.deepcopy(DEFAULT_TWO_TRUTHS_GAME_STATE)
    state["enabled"] = bool(enabled)
    return state


def normalize_participant(raw: object, user_id: str = "") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    participant_user_id = str(raw.get("user_id", "") or user_id).strip()
    submission_id = str(raw.get("submission_id", "") or "").strip()
    answer_name = re.sub(r"\s+", " ", str(raw.get("answer_name", "") or "").strip())[:80]
    raw_truths = raw.get("truths", [])
    truths = [normalize_statement(value) for value in raw_truths[:2]] if isinstance(raw_truths, list) else []
    lie = normalize_statement(raw.get("lie", ""))
    if not participant_user_id or not submission_id or not answer_name or len(truths) != 2 or not all(truths) or not lie:
        return None

    normalized_statements = [normalize_guess_name(value) for value in [*truths, lie]]
    if len(set(normalized_statements)) != 3:
        return None

    raw_order = raw.get("display_order", [])
    display_order = []
    if isinstance(raw_order, list):
        for value in raw_order:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if index in {0, 1, 2} and index not in display_order:
                display_order.append(index)
    if len(display_order) != 3:
        display_order = [0, 1, 2]

    return {
        "submission_id": submission_id,
        "user_id": participant_user_id,
        "answer_name": answer_name,
        "truths": truths,
        "lie": lie,
        "display_order": display_order,
        "created_at": str(raw.get("created_at", "") or ""),
        "updated_at": str(raw.get("updated_at", "") or ""),
    }


def normalize_guess(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    guessed_name = re.sub(r"\s+", " ", str(raw.get("guessed_name", "") or "").strip())[:80]
    normalized_name = normalize_guess_name(guessed_name)
    if not guessed_name or not normalized_name:
        return None
    return {
        "guessed_name": guessed_name,
        "normalized_name": normalized_name,
        "submitted_at": str(raw.get("submitted_at", "") or ""),
    }


def normalize_results(raw: object) -> dict[str, Any]:
    default = copy.deepcopy(DEFAULT_TWO_TRUTHS_GAME_STATE["results"])
    if not isinstance(raw, dict):
        return default

    scores: list[dict[str, Any]] = []
    if isinstance(raw.get("scores"), list):
        for entry in raw["scores"]:
            if not isinstance(entry, dict):
                continue
            user_id = str(entry.get("user_id", "") or "")
            name = str(entry.get("name", "") or "").strip()[:80]
            if not user_id or not name:
                continue
            attempts = _nonnegative_int(entry.get("attempts"))
            correct = min(attempts, _nonnegative_int(entry.get("correct")))
            scores.append(
                {
                    "user_id": user_id,
                    "name": name,
                    "correct": correct,
                    "attempts": attempts,
                    "accuracy": round((correct / attempts * 100) if attempts else 0.0, 1),
                }
            )

    participant_results = []
    if isinstance(raw.get("participant_results"), list):
        for entry in raw["participant_results"]:
            if not isinstance(entry, dict):
                continue
            participant_results.append(
                {
                    "submission_id": str(entry.get("submission_id", "") or ""),
                    "name": str(entry.get("name", "") or "").strip()[:80],
                    "correct_guesses": _nonnegative_int(entry.get("correct_guesses")),
                    "guess_count": _nonnegative_int(entry.get("guess_count")),
                }
            )

    valid_user_ids = {entry["user_id"] for entry in scores}
    winner_ids = [
        str(value)
        for value in raw.get("winner_ids", [])
        if str(value) in valid_user_ids
    ] if isinstance(raw.get("winner_ids"), list) else []
    return {
        "finalized_at": str(raw.get("finalized_at", "") or ""),
        "scores": scores,
        "winner_ids": winner_ids,
        "participant_results": participant_results,
    }


def normalize_two_truths_game_state(raw: object) -> dict[str, Any]:
    state = empty_two_truths_game_state()
    if not isinstance(raw, dict):
        return state

    state["enabled"] = bool(raw.get("enabled"))
    phase = str(raw.get("phase", "signup") or "signup")
    state["phase"] = phase if phase in GAME_PHASES else "signup"
    state["started_at"] = str(raw.get("started_at", "") or "")
    state["ended_at"] = str(raw.get("ended_at", "") or "")

    participants: dict[str, dict[str, Any]] = {}
    seen_submission_ids: set[str] = set()
    raw_participants = raw.get("participants", {})
    if isinstance(raw_participants, dict):
        for raw_user_id, raw_participant in raw_participants.items():
            user_id = str(raw_user_id)
            participant = normalize_participant(raw_participant, user_id)
            if participant and participant["submission_id"] not in seen_submission_ids:
                participants[user_id] = participant
                seen_submission_ids.add(participant["submission_id"])
    state["participants"] = participants

    submission_owners = {
        entry["submission_id"]: entry["user_id"]
        for entry in participants.values()
    }
    guesses: dict[str, dict[str, dict[str, str]]] = {}
    raw_guesses = raw.get("guesses", {})
    if isinstance(raw_guesses, dict):
        for raw_guesser_id, raw_submission_guesses in raw_guesses.items():
            guesser_id = str(raw_guesser_id)
            if guesser_id not in participants or not isinstance(raw_submission_guesses, dict):
                continue
            normalized_submission_guesses = {}
            for raw_submission_id, raw_guess in raw_submission_guesses.items():
                submission_id = str(raw_submission_id)
                guess = normalize_guess(raw_guess)
                if submission_id in submission_owners and submission_owners[submission_id] != guesser_id and guess:
                    normalized_submission_guesses[submission_id] = guess
            if normalized_submission_guesses:
                guesses[guesser_id] = normalized_submission_guesses
    state["guesses"] = guesses
    state["results"] = normalize_results(raw.get("results"))
    return state


def normalize_games_state(raw: object) -> dict[str, Any]:
    raw_games = raw if isinstance(raw, dict) else {}
    return {
        TWO_TRUTHS_GAME_KEY: normalize_two_truths_game_state(
            raw_games.get(TWO_TRUTHS_GAME_KEY)
        )
    }


def participant_statements(participant: dict[str, Any]) -> list[str]:
    statements = [*participant.get("truths", []), participant.get("lie", "")]
    order = participant.get("display_order", [0, 1, 2])
    return [str(statements[index]) for index in order if index in {0, 1, 2}]


def calculate_two_truths_results(game: dict[str, Any], *, finalized_at: str | None = None) -> dict[str, Any]:
    participants = game.get("participants", {})
    guesses = game.get("guesses", {})
    targets_by_submission = {
        participant["submission_id"]: participant
        for participant in participants.values()
    }

    scores = []
    target_totals = {
        submission_id: {"guess_count": 0, "correct_guesses": 0}
        for submission_id in targets_by_submission
    }
    for guesser_id, guesser in participants.items():
        submission_guesses = guesses.get(guesser_id, {})
        attempts = 0
        correct = 0
        for submission_id, guess in submission_guesses.items():
            target = targets_by_submission.get(submission_id)
            if not target or target.get("user_id") == guesser_id:
                continue
            attempts += 1
            target_totals[submission_id]["guess_count"] += 1
            is_correct = guess.get("normalized_name") == normalize_guess_name(target.get("answer_name"))
            if is_correct:
                correct += 1
                target_totals[submission_id]["correct_guesses"] += 1
        scores.append(
            {
                "user_id": guesser_id,
                "name": guesser.get("answer_name", "Guest"),
                "correct": correct,
                "attempts": attempts,
                "accuracy": round((correct / attempts * 100) if attempts else 0.0, 1),
            }
        )

    scores.sort(key=lambda entry: (-entry["correct"], -entry["accuracy"], entry["name"].casefold()))
    top_score = scores[0]["correct"] if scores else 0
    winner_ids = [entry["user_id"] for entry in scores if top_score > 0 and entry["correct"] == top_score]
    participant_results = [
        {
            "submission_id": submission_id,
            "name": target.get("answer_name", "Guest"),
            **target_totals[submission_id],
        }
        for submission_id, target in targets_by_submission.items()
    ]
    participant_results.sort(key=lambda entry: entry["name"].casefold())
    return {
        "finalized_at": finalized_at or utc_now_iso(),
        "scores": scores,
        "winner_ids": winner_ids,
        "participant_results": participant_results,
    }


def two_truths_statistics(game: dict[str, Any]) -> dict[str, Any]:
    participants = game.get("participants", {})
    guesses = game.get("guesses", {})
    provisional = calculate_two_truths_results(game, finalized_at="")
    possible_guesses = max(0, len(participants) * max(0, len(participants) - 1))
    submitted_guesses = sum(len(entries) for entries in guesses.values())
    matched_guesses = sum(entry["correct"] for entry in provisional["scores"])
    return {
        "participant_count": len(participants),
        "guesser_count": sum(1 for entries in guesses.values() if entries),
        "submitted_guesses": submitted_guesses,
        "possible_guesses": possible_guesses,
        "completion_percent": round((submitted_guesses / possible_guesses * 100) if possible_guesses else 0.0, 1),
        "correct_guesses": matched_guesses,
        "incorrect_guesses": max(0, submitted_guesses - matched_guesses),
        "scores": provisional["scores"],
        "participant_results": provisional["participant_results"],
    }
