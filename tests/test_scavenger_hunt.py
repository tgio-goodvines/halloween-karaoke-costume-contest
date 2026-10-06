from party_games import (
    calculate_scavenger_hunt_results,
    empty_cursed_objectives_game_state,
    empty_scavenger_hunt_game_state,
    normalize_cursed_objectives_game_state,
    normalize_scavenger_hunt_game_state,
    scavenger_hunt_statistics,
)


def participant(player_id, name, submissions):
    return {
        "player_id": player_id,
        "display_name": name,
        "alias": name,
        "submissions": submissions,
        "created_at": "",
        "updated_at": "",
    }


def submission(item_id, status):
    return {
        "id": f"submission-{item_id}",
        "item_id": item_id,
        "item_title": item_id,
        "item_instructions": "",
        "image_url": f"/scavenger-hunt-images/{'a' * 32}.webp",
        "review_status": status,
        "submitted_at": "",
        "updated_at": "",
        "reviewed_at": "",
    }


def test_scavenger_hunt_defaults_to_an_editable_item_deck():
    game = empty_scavenger_hunt_game_state()

    assert game["phase"] == "signup"
    assert len(game["items"]) >= 3
    assert all(item["id"] and item["title"] and item["enabled"] for item in game["items"])


def test_scavenger_hunt_scores_only_approved_photos_and_supports_ties():
    game = empty_scavenger_hunt_game_state(enabled=True)
    first_item, second_item = [item["id"] for item in game["items"][:2]]
    game["participants"] = {
        "user-1": participant(
            "player-1",
            "Jamie",
            {
                first_item: submission(first_item, "approved"),
                second_item: submission(second_item, "pending"),
            },
        ),
        "user-2": participant(
            "player-2",
            "Morgan",
            {
                first_item: submission(first_item, "approved"),
                second_item: submission(second_item, "rejected"),
            },
        ),
    }

    results = calculate_scavenger_hunt_results(game, finalized_at="2026-10-31T23:00:00Z")
    statistics = scavenger_hunt_statistics(game)

    assert [entry["points"] for entry in results["scores"]] == [1, 1]
    assert set(results["winner_player_ids"]) == {"player-1", "player-2"}
    assert statistics["submission_count"] == 4
    assert statistics["approved_count"] == 2
    assert statistics["pending_count"] == 1
    assert statistics["rejected_count"] == 1


def test_scavenger_hunt_normalization_preserves_review_and_rebuilds_final_results():
    game = empty_scavenger_hunt_game_state(enabled=True)
    item_id = game["items"][0]["id"]
    game["phase"] = "ended"
    game["participants"] = {
        "user-1": participant(
            "player-1",
            "Jamie",
            {item_id: submission(item_id, "approved")},
        )
    }

    normalized = normalize_scavenger_hunt_game_state(game)

    assert normalized["participants"]["user-1"]["submissions"][item_id]["review_status"] == "approved"
    assert normalized["results"]["scores"][0]["points"] == 1
    assert normalized["results"]["winner_player_ids"] == ["player-1"]


def test_cursed_objective_snapshot_survives_later_deck_edits():
    game = empty_cursed_objectives_game_state(enabled=True)
    mission_id = game["objectives"][0]["id"]
    original_text = game["objectives"][0]["text"]
    game["participants"] = {
        "user-1": {
            "player_id": "player-1",
            "display_name": "Jamie",
            "alias": "Jamie",
            "mission_ids": [mission_id],
            "mission_snapshots": {mission_id: original_text},
            "completed_mission_ids": [],
            "completed_at": {},
            "created_at": "",
            "updated_at": "",
        }
    }
    game["objectives"][0]["text"] = "New wording for future players"

    normalized = normalize_cursed_objectives_game_state(game)

    assert normalized["participants"]["user-1"]["mission_snapshots"][mission_id] == original_text
