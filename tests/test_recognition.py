import unittest

from recognition import (
    achievement_views,
    credit_exists,
    event_id_for_year,
    new_credit,
    normalize_event_editions,
    normalize_recognition_credits,
    normalize_result_archives,
)


class RecognitionTests(unittest.TestCase):
    def attendance_credit(self, year: str, account_id: str = "guest-1"):
        return new_credit(
            kind="attendance",
            account_id=account_id,
            recipient_name="Jamie",
            event_id=event_id_for_year(year),
            year=year,
        )

    def test_attendance_achievements_unlock_at_distinct_event_thresholds(self):
        credits = [self.attendance_credit(year) for year in ("2024", "2025", "2026")]

        rewards = achievement_views(credits, "guest-1")

        self.assertEqual(3, rewards["attendance_count"])
        self.assertEqual(["2026", "2025", "2024"], rewards["attendance_years"])
        self.assertEqual(
            {"party_attendee", "returning_reveler", "seasoned_spirit"},
            {achievement["key"] for achievement in rewards["achievements"]},
        )
        self.assertEqual("halloween_legend", rewards["next_attendance"]["key"])

    def test_revoked_and_duplicate_attendance_do_not_inflate_progress(self):
        active = self.attendance_credit("2025")
        duplicate = self.attendance_credit("2025")
        revoked = self.attendance_credit("2024")
        revoked["revoked_at"] = "2026-01-01T00:00:00Z"

        rewards = achievement_views([active, duplicate, revoked], "guest-1")

        self.assertEqual(1, rewards["attendance_count"])
        self.assertIn("party_attendee", {item["key"] for item in rewards["achievements"]})
        self.assertNotIn("returning_reveler", {item["key"] for item in rewards["achievements"]})

    def test_winner_achievements_support_ties_and_multiple_games(self):
        credits = [
            new_credit(
                kind="game_win",
                account_id="guest-1",
                recipient_name="Jamie",
                public_identity="Specimen 7",
                event_id="2026-halloween",
                year="2026",
                subject_key=game,
            )
            for game in ("fill_in_the_blank", "wrong_answers_only")
        ]
        credits.append(
            new_credit(
                kind="costume_win",
                account_id="guest-1",
                recipient_name="Jamie",
                event_id="2025-halloween",
                year="2025",
                subject_key="costume_contest",
            )
        )

        keys = {item["key"] for item in achievement_views(credits, "guest-1")["achievements"]}

        self.assertTrue({"game_champion", "multi_game_master", "costume_champion"}.issubset(keys))

    def test_normalizers_reject_invalid_rows_and_sanitize_winner_links(self):
        archives = normalize_result_archives(
            [
                {"id": "bad", "kind": "unknown"},
                {
                    "id": "2026-halloween:game:test",
                    "event_id": "2026-halloween",
                    "kind": "game",
                    "subject_key": "test",
                    "status": "official",
                    "winner_links": [None, {"account_id": "a" * 200, "public_identity": "Winner"}],
                },
            ]
        )
        credits = normalize_recognition_credits(
            [
                {"id": "invalid", "kind": "bogus", "recipient_name": "Nobody"},
                {"id": "credit-1", "kind": "attendance", "recipient_name": "Jamie"},
            ]
        )

        self.assertEqual(1, len(archives))
        self.assertEqual(120, len(archives[0]["winner_links"][0]["account_id"]))
        self.assertEqual(["credit-1"], [credit["id"] for credit in credits])

    def test_credit_exists_is_idempotent_and_ignores_revoked_rows(self):
        credit = new_credit(
            kind="game_win",
            account_id="guest-1",
            recipient_name="Jamie",
            event_id="2026-halloween",
            subject_key="test_game",
            source_ref="archive-1",
        )
        self.assertTrue(
            credit_exists(
                [credit],
                kind="game_win",
                account_id="guest-1",
                event_id="2026-halloween",
                subject_key="test_game",
                source_ref="archive-1",
            )
        )
        credit["revoked_at"] = "2026-11-01T00:00:00Z"
        self.assertFalse(
            credit_exists(
                [credit],
                kind="game_win",
                account_id="guest-1",
                event_id="2026-halloween",
                subject_key="test_game",
                source_ref="archive-1",
            )
        )

    def test_event_editions_always_include_the_current_party(self):
        editions = normalize_event_editions(
            {"2024-halloween": {"year": "2024", "title": "First Party", "date": "October 31"}},
            current_year="2026",
            current_title="Third Party",
            current_date="October 31",
        )

        self.assertEqual({"2024-halloween", "2026-halloween"}, set(editions))


if __name__ == "__main__":
    unittest.main()
