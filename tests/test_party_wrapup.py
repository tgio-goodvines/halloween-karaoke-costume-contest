import json
import unittest

from party_games import (
    GAME_CATALOG,
    MURDER_MARRY_FUCK_GAME_KEY,
    TWO_TRUTHS_GAME_KEY,
    build_simulated_game_state,
    empty_mmf_game_state,
    empty_two_truths_game_state,
)
from party_wrapup import (
    build_detailed_game_archive,
    normalize_event_wrapups,
    reset_games_state,
    sanitize_mutable_game_data,
)
from recap_analytics import build_playlist_snapshot, build_recap_analytics, chart_rows


class PartyWrapupHelperTests(unittest.TestCase):
    def test_reset_all_games_returns_disabled_pristine_states(self):
        games = {
            game_key: build_simulated_game_state(game_key, {}, player_count=4)
            for game_key in GAME_CATALOG
        }

        reset = reset_games_state(games)

        self.assertEqual(set(GAME_CATALOG), set(reset))
        self.assertTrue(all(not game["enabled"] for game in reset.values()))
        self.assertTrue(all(game["phase"] == "signup" for game in reset.values()))
        self.assertTrue(all(not game["participants"] for game in reset.values()))
        self.assertTrue(
            all(not game["simulation"]["is_simulated"] for game in reset.values())
        )

    def test_per_game_reset_can_preserve_enabled_setting(self):
        games = {TWO_TRUTHS_GAME_KEY: build_simulated_game_state(TWO_TRUTHS_GAME_KEY, {})}

        reset = reset_games_state(
            games,
            game_keys={TWO_TRUTHS_GAME_KEY},
            preserve_enabled=True,
        )

        self.assertTrue(reset[TWO_TRUTHS_GAME_KEY]["enabled"])
        self.assertEqual({}, reset[TWO_TRUTHS_GAME_KEY]["participants"])

    def test_backup_sanitizer_preserves_official_history_and_unrelated_state(self):
        snapshot = {
            "games_state": {
                TWO_TRUTHS_GAME_KEY: build_simulated_game_state(TWO_TRUTHS_GAME_KEY, {})
            },
            "result_archives": [
                {
                    "id": "official",
                    "kind": "game",
                    "subject_key": TWO_TRUTHS_GAME_KEY,
                    "status": "official",
                },
                {
                    "id": "draft",
                    "kind": "game",
                    "subject_key": TWO_TRUTHS_GAME_KEY,
                    "status": "draft",
                },
                {"id": "costume", "kind": "costume", "status": "official"},
            ],
            "recognition_credits": [{"id": "attendance", "kind": "attendance"}],
            "party_details": {"address": "Keep me"},
        }

        sanitized = sanitize_mutable_game_data(snapshot)
        sanitized_twice = sanitize_mutable_game_data(sanitized)

        self.assertEqual(["official", "costume"], [row["id"] for row in sanitized["result_archives"]])
        self.assertEqual({"address": "Keep me"}, sanitized["party_details"])
        self.assertEqual("attendance", sanitized["recognition_credits"][0]["id"])
        self.assertEqual({}, sanitized["games_state"][TWO_TRUTHS_GAME_KEY]["participants"])
        self.assertEqual(sanitized, sanitized_twice)

    def test_precise_history_deletion_does_not_remove_other_years(self):
        snapshot = {
            "games_state": {},
            "result_archives": [
                {
                    "id": "2025-game",
                    "kind": "game",
                    "subject_key": TWO_TRUTHS_GAME_KEY,
                    "status": "official",
                },
                {
                    "id": "2026-game",
                    "kind": "game",
                    "subject_key": TWO_TRUTHS_GAME_KEY,
                    "status": "official",
                },
            ],
            "game_data_archives": {
                "2025-detail": {"official_archive_id": "2025-game", "game_key": TWO_TRUTHS_GAME_KEY},
                "2026-detail": {"official_archive_id": "2026-game", "game_key": TWO_TRUTHS_GAME_KEY},
            },
            "recognition_credits": [
                {"id": "credit-2025", "kind": "game_win", "source_ref": "2025-game"},
                {"id": "credit-2026", "kind": "game_win", "source_ref": "2026-game"},
            ],
        }

        sanitized = sanitize_mutable_game_data(
            snapshot,
            delete_official_archive_ids={"2025-game"},
            delete_detailed_archive_ids={"2025-detail"},
        )

        self.assertEqual(["2026-game"], [row["id"] for row in sanitized["result_archives"]])
        self.assertEqual(["2026-detail"], list(sanitized["game_data_archives"]))
        self.assertEqual(["credit-2026"], [row["id"] for row in sanitized["recognition_credits"]])

    def test_mmf_detailed_archive_contains_aggregates_not_private_ballots(self):
        game = build_simulated_game_state(
            MURDER_MARRY_FUCK_GAME_KEY,
            empty_mmf_game_state(enabled=True),
            player_count=4,
        )

        archive = build_detailed_game_archive(
            MURDER_MARRY_FUCK_GAME_KEY,
            game,
            event_id="2026-halloween",
            year="2026",
            archived_at="2026-11-01T06:00:00Z",
            official_archive_id="official-mmf",
        )
        encoded = json.dumps(archive)

        self.assertIn("rounds", archive["detail"])
        self.assertNotIn('"answers"', encoded)
        self.assertNotIn("simulation:murder_marry_fuck", encoded)

    def test_wrapup_normalizer_freezes_personal_summaries_and_delivery_ledger(self):
        normalized = normalize_event_wrapups(
            {
                "2026-halloween": {
                    "status": "finalized",
                    "personal_summaries": {"user-1": {"games_joined": 3}},
                    "deliveries": [
                        {
                            "account_id": "user-1",
                            "email": "JAMIE@example.com",
                            "name": "Jamie",
                            "status": "failed",
                            "attempt_count": 2,
                        }
                    ],
                }
            }
        )["2026-halloween"]

        self.assertEqual(3, normalized["personal_summaries"]["user-1"]["games_joined"])
        self.assertEqual("jamie@example.com", normalized["deliveries"][0]["email"])
        self.assertEqual(2, normalized["deliveries"][0]["attempt_count"])

    def test_recap_analytics_generate_email_safe_bar_widths_and_playlist_totals(self):
        game = build_simulated_game_state(TWO_TRUTHS_GAME_KEY, empty_two_truths_game_state(), player_count=4)
        game["simulation"]["is_simulated"] = False
        playlist = build_playlist_snapshot(
            [
                {"id": "one", "title": "Song One", "artist": "Artist", "duration_ms": 180000, "enabled": True},
                {"id": "two", "title": "Song Two", "artist": "Artist", "duration_ms": 240000, "enabled": True},
            ]
        )

        analytics = build_recap_analytics(
            {TWO_TRUTHS_GAME_KEY: game},
            attendee_count=5,
            playlist_snapshot=playlist,
        )

        self.assertEqual(4, analytics["total_game_participations"])
        self.assertEqual("7 min", analytics["playlist"]["duration_label"])
        self.assertEqual(1, analytics["playlist"]["unique_artist_count"])
        self.assertEqual([100.0, 50.0], [row["percent"] for row in chart_rows([{"label": "A", "value": 2}, {"label": "B", "value": 1}])])


if __name__ == "__main__":
    unittest.main()
