from datetime import datetime, timedelta, timezone
import random

import pytest

from party_games import (
    FILL_BLANK_GAME_KEY,
    PROMPT_GAME_KEYS,
    PROMPT_RESPONSE_WINDOW_SECONDS,
    PROMPT_REVEAL_WINDOW_SECONDS,
    PROMPT_VOTING_WINDOW_SECONDS,
    advance_prompt_game_automation,
    empty_prompt_game_state,
    generate_prompt_for_game,
    normalize_prompt_game_state,
    prompt_round_for_game,
)


NOW = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)


def _response(response_id: str, player_id: str) -> dict[str, object]:
    return {
        "id": response_id,
        "player_id": player_id,
        "text": f"Answer {response_id}",
        "submitted_at": NOW.isoformat(),
        "display_hidden": False,
    }


def test_prompt_generators_are_valid_and_avoid_recent_repeats():
    for game_key in PROMPT_GAME_KEYS:
        game = empty_prompt_game_state(game_key, enabled=True)
        generated = [
            generate_prompt_for_game(game_key, game, rng=random.Random(index))
            for index in range(12)
        ]
        texts = [str(item["text"]) for item in generated]
        assert all(text and len(text) <= 240 for text in texts)
        assert len(texts) == len(set(texts))
        if game_key == FILL_BLANK_GAME_KEY:
            assert all("___" in text for text in texts)


def test_automatic_prompt_round_runs_response_vote_extension_reveal_cycle():
    game = empty_prompt_game_state(FILL_BLANK_GAME_KEY, enabled=True)

    assert advance_prompt_game_automation(FILL_BLANK_GAME_KEY, game, now=NOW, rng=random.Random(4)) == ["round_opened"]
    game_round = prompt_round_for_game(game)
    assert game_round is not None
    first_round_id = game_round["id"]

    game_round["responses"] = {
        "r1": _response("r1", "p1"),
        "r2": _response("r2", "p2"),
    }
    assert advance_prompt_game_automation(FILL_BLANK_GAME_KEY, game, now=NOW) == []
    assert game_round["deadline_at"] == ""

    game_round["responses"]["r3"] = _response("r3", "p3")
    threshold_time = NOW + timedelta(seconds=20)
    assert advance_prompt_game_automation(FILL_BLANK_GAME_KEY, game, now=threshold_time) == ["response_timer_started"]
    assert datetime.fromisoformat(game_round["deadline_at"].replace("Z", "+00:00")) == threshold_time + timedelta(seconds=PROMPT_RESPONSE_WINDOW_SECONDS)

    voting_time = threshold_time + timedelta(seconds=PROMPT_RESPONSE_WINDOW_SECONDS)
    assert advance_prompt_game_automation(FILL_BLANK_GAME_KEY, game, now=voting_time) == ["voting_opened"]
    assert game_round["status"] == "voting"
    first_vote_deadline = voting_time + timedelta(seconds=PROMPT_VOTING_WINDOW_SECONDS)

    assert advance_prompt_game_automation(FILL_BLANK_GAME_KEY, game, now=first_vote_deadline) == ["voting_extended"]
    assert game_round["vote_extensions"] == 1

    game_round["votes"] = {"p1": "r2"}
    second_vote_deadline = first_vote_deadline + timedelta(seconds=PROMPT_VOTING_WINDOW_SECONDS)
    assert advance_prompt_game_automation(FILL_BLANK_GAME_KEY, game, now=second_vote_deadline) == ["round_revealed"]
    assert game_round["status"] == "revealed"
    assert game_round["results"]["vote_count"] == 1

    next_round_time = second_vote_deadline + timedelta(seconds=PROMPT_REVEAL_WINDOW_SECONDS)
    assert advance_prompt_game_automation(FILL_BLANK_GAME_KEY, game, now=next_round_time, rng=random.Random(8)) == ["round_opened"]
    assert prompt_round_for_game(game)["id"] != first_round_id
    assert prompt_round_for_game(game)["status"] == "submissions"


def test_legacy_prompt_game_migrates_with_automation_paused():
    legacy = empty_prompt_game_state(FILL_BLANK_GAME_KEY, enabled=True)
    legacy.pop("automation")
    normalized = normalize_prompt_game_state(legacy, FILL_BLANK_GAME_KEY)
    assert normalized["automation"]["enabled"] is False
    assert normalized["automation"]["paused"] is True


@pytest.mark.parametrize("game_key", PROMPT_GAME_KEYS)
def test_paused_automation_does_not_create_round(game_key):
    game = empty_prompt_game_state(game_key, enabled=True)
    game["automation"]["paused"] = True
    assert advance_prompt_game_automation(game_key, game, now=NOW) == []
    assert prompt_round_for_game(game) is None
