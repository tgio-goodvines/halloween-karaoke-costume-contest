import random

import pytest

from party_games import (
    CURSED_OBJECTIVES_PER_PLAYER,
    assign_cursed_objectives,
    calculate_cursed_objectives_results,
    empty_cursed_objectives_game_state,
    normalize_cursed_objectives_game_state,
)


def test_each_joining_player_receives_non_overlapping_objectives():
    game = empty_cursed_objectives_game_state(enabled=True)
    first = assign_cursed_objectives(game, "account-1", display_name="First", rng=random.Random(1))
    second = assign_cursed_objectives(game, "account-2", display_name="Second", rng=random.Random(1))

    assert len(first["mission_ids"]) == CURSED_OBJECTIVES_PER_PLAYER
    assert len(second["mission_ids"]) == CURSED_OBJECTIVES_PER_PLAYER
    assert set(first["mission_ids"]).isdisjoint(second["mission_ids"])


def test_existing_player_keeps_the_same_private_objectives():
    game = empty_cursed_objectives_game_state(enabled=True)
    first = assign_cursed_objectives(game, "account-1", display_name="First", rng=random.Random(2))
    again = assign_cursed_objectives(game, "account-1", display_name="Renamed", rng=random.Random(99))

    assert again is first
    assert again["mission_ids"] == first["mission_ids"]


def test_join_fails_instead_of_reusing_an_assigned_objective():
    game = empty_cursed_objectives_game_state(enabled=True)
    objective_count = len(game["objectives"])
    for index in range(objective_count // CURSED_OBJECTIVES_PER_PLAYER):
        assign_cursed_objectives(game, f"account-{index}", display_name=f"Player {index}", rng=random.Random(index))

    with pytest.raises(ValueError):
        assign_cursed_objectives(game, "one-too-many", display_name="Late Player")


def test_scoring_preserves_tied_positive_winners():
    game = empty_cursed_objectives_game_state(enabled=True)
    first = assign_cursed_objectives(game, "account-1", display_name="First", rng=random.Random(3))
    second = assign_cursed_objectives(game, "account-2", display_name="Second", rng=random.Random(4))
    first["completed_mission_ids"] = first["mission_ids"][:2]
    second["completed_mission_ids"] = second["mission_ids"][:2]

    results = calculate_cursed_objectives_results(game, finalized_at="2026-10-31T23:00:00Z")

    assert [entry["points"] for entry in results["scores"]] == [2, 2]
    assert set(results["winner_player_ids"]) == {first["player_id"], second["player_id"]}


def test_normalization_drops_duplicate_cross_player_assignments():
    game = empty_cursed_objectives_game_state(enabled=True)
    first = assign_cursed_objectives(game, "account-1", display_name="First", rng=random.Random(5))
    second = assign_cursed_objectives(game, "account-2", display_name="Second", rng=random.Random(6))
    second["mission_ids"][0] = first["mission_ids"][0]

    normalized = normalize_cursed_objectives_game_state(game)

    assigned = [
        mission_id
        for participant in normalized["participants"].values()
        for mission_id in participant["mission_ids"]
    ]
    assert len(assigned) == len(set(assigned))
