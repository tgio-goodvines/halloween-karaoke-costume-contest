import json
import unittest

import main


class FakeLock:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.acquired = False
        self.released = False

    def acquire(self, blocking=True):
        self.acquired = True
        self.redis_client.acquired_locks.append(self)
        return True

    def release(self):
        self.released = True
        self.redis_client.released_locks.append(self)


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}
        self.published_messages = []
        self.acquired_locks = []
        self.released_locks = []

    def ping(self):
        return True

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = str(value)
        return True

    def setex(self, key, ttl, value):
        self.store[key] = str(value)
        self.ttls[key] = ttl
        return True

    def exists(self, key):
        return int(key in self.store)

    def delete(self, *keys):
        deleted = 0
        for key in keys:
            if key in self.store:
                deleted += 1
                del self.store[key]
        return deleted

    def publish(self, channel, message):
        self.published_messages.append((channel, message))
        return 1

    def scan_iter(self, match=None):
        if match is None:
            yield from self.store.keys()
            return

        prefix = match[:-1] if match.endswith("*") else match
        for key in self.store.keys():
            if key.startswith(prefix):
                yield key

    def lock(self, *args, **kwargs):
        return FakeLock(self)


class RedisStateTests(unittest.TestCase):
    def setUp(self):
        self.fake_redis = FakeRedis()
        self.original_redis_client = main.redis_client
        self.original_redis_available = main.redis_state_available
        self.original_config = main.REDIS_CONFIG

        main.redis_client = self.fake_redis
        main.redis_state_available = True
        main.REDIS_CONFIG = main.RedisConfig(
            host="127.0.0.1",
            port=6379,
            db=1,
            username=None,
            password=None,
            prefix="test-halloween",
        )
        main.app.config["TESTING"] = True
        self.reset_state()

    def tearDown(self):
        main.redis_client = self.original_redis_client
        main.redis_state_available = self.original_redis_available
        main.REDIS_CONFIG = self.original_config
        self.reset_state()

    def reset_state(self):
        main.costume_signups = []
        main.karaoke_signups = []
        main.costume_votes = []
        main.registered_users = {}
        main.submitted_costume_votes = set()
        main.live_display_override = None
        main.display_update_version = 0
        main.contest_state.clear()
        main.contest_state.update(main.copy.deepcopy(main.DEFAULT_CONTEST_STATE))
        main.karaoke_state.clear()
        main.karaoke_state.update(main.copy.deepcopy(main.DEFAULT_KARAOKE_STATE))

    def redis_state(self):
        return json.loads(self.fake_redis.store[main.redis_key("state")])

    def save_current_state(self):
        main.save_state_to_redis()

    def test_serialization_round_trip_preserves_state(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "ada@example.com"),
            main.CostumeSignup("Grace", "Ghost", ""),
        ]
        main.karaoke_signups = [
            main.KaraokeSignup("Lin", "Thriller", "Michael Jackson", "https://example.test/video")
        ]
        main.costume_votes = [[8, "9"], [10]]
        main.registered_users = {"user-1": "Ada"}
        main.submitted_costume_votes = {"user-1"}
        main.contest_state["voting_open"] = True
        main.karaoke_state["party_started"] = True
        main.live_display_override = {"type": "notice", "title": "Tonight"}
        main.display_update_version = 7

        snapshot = main.snapshot_state()
        self.reset_state()
        main.apply_state_snapshot(snapshot)

        self.assertEqual(["Ada", "Grace"], [signup.name for signup in main.costume_signups])
        self.assertEqual("Thriller", main.karaoke_signups[0].song_title)
        self.assertEqual([[8, 9], [10]], main.costume_votes)
        self.assertEqual({"user-1": "Ada"}, main.registered_users)
        self.assertEqual({"user-1"}, main.submitted_costume_votes)
        self.assertTrue(main.contest_state["voting_open"])
        self.assertTrue(main.karaoke_state["party_started"])
        self.assertEqual({"type": "notice", "title": "Tonight"}, main.live_display_override)
        self.assertEqual(7, main.display_update_version)

    def test_load_state_from_redis_initializes_missing_state_and_hydrates_existing_state(self):
        main.costume_signups = [main.CostumeSignup("Ada", "Vampire", "")]

        loaded_existing = main.load_state_from_redis()

        self.assertFalse(loaded_existing)
        self.assertIn(main.redis_key("state"), self.fake_redis.store)

        replacement = main.snapshot_state()
        replacement["costume_signups"] = [
            {"name": "Grace", "costume": "Ghost", "contact": "grace@example.com"}
        ]
        replacement["karaoke_signups"] = [
            {"name": "Lin", "song_title": "Monster Mash", "artist": "Bobby Pickett", "youtube_link": ""}
        ]
        replacement["display_update_version"] = 3
        self.fake_redis.set(main.redis_key("state"), json.dumps(replacement))

        self.assertTrue(main.load_state_from_redis())
        self.assertEqual("Grace", main.costume_signups[0].name)
        self.assertEqual("Monster Mash", main.karaoke_signups[0].song_title)
        self.assertEqual(3, main.display_update_version)

    def test_attendee_signups_persist_and_publish_display_updates(self):
        self.save_current_state()

        with main.app.test_client() as client:
            costume_response = client.post(
                "/costume-signup",
                data={"name": "Ada", "costume": "Vampire", "contact": "ada@example.com"},
            )
            karaoke_response = client.post(
                "/karaoke-signup",
                data={
                    "name": "Grace",
                    "song_title": "Thriller",
                    "artist": "Michael Jackson",
                    "youtube_link": "https://example.test/thriller",
                },
            )

        state = self.redis_state()
        self.assertEqual(302, costume_response.status_code)
        self.assertEqual(302, karaoke_response.status_code)
        self.assertEqual("Ada", state["costume_signups"][0]["name"])
        self.assertEqual("Grace", state["karaoke_signups"][0]["name"])
        self.assertEqual(2, state["display_update_version"])
        self.assertEqual(2, len(self.fake_redis.published_messages))

    def test_voting_persists_scores_and_blocks_second_vote(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", ""),
            main.CostumeSignup("Grace", "Ghost", ""),
        ]
        main.costume_votes = [[], []]
        main.registered_users = {"user-1": "Jamie"}
        main.contest_state["voting_open"] = True
        self.save_current_state()

        with main.app.test_client() as client:
            with client.session_transaction() as session:
                session["user_id"] = "user-1"
                session["username"] = "Jamie"

            first_response = client.post(
                "/costume-voting",
                data={"rating_0": "9", "rating_1": "7"},
            )
            second_response = client.post(
                "/costume-voting",
                data={"rating_0": "1", "rating_1": "1"},
            )

        state = self.redis_state()
        self.assertEqual(302, first_response.status_code)
        self.assertEqual(200, second_response.status_code)
        self.assertEqual([[9], [7]], state["costume_votes"])
        self.assertEqual(["user-1"], state["submitted_costume_votes"])

    def test_admin_reorder_keeps_votes_aligned_with_costumes(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", ""),
            main.CostumeSignup("Grace", "Ghost", ""),
        ]
        main.costume_votes = [[1], [9]]
        self.save_current_state()

        with main.app.test_client() as client:
            response = client.post("/admin", data={"action": "move_costume_down", "index": "0"})

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertEqual(["Grace", "Ada"], [entry["name"] for entry in state["costume_signups"]])
        self.assertEqual([[9], [1]], state["costume_votes"])

    def test_display_data_reflects_persisted_state_and_update_version_publish(self):
        self.save_current_state()

        with main.app.test_client() as client:
            client.post(
                "/costume-signup",
                data={"name": "Ada", "costume": "Vampire", "contact": ""},
            )
            response = client.get("/api/display-data")

        payload = response.get_json()
        state = self.redis_state()
        published_channel, published_message = self.fake_redis.published_messages[-1]
        published_payload = json.loads(published_message)

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, payload["costume_count"])
        self.assertEqual(0, payload["karaoke_count"])
        self.assertTrue(any(entry["primary"] == "Ada" for entry in payload["entries"]))
        self.assertEqual(1, state["display_update_version"])
        self.assertEqual(main.redis_key("display:pubsub"), published_channel)
        self.assertEqual(1, published_payload["version"])
        self.assertEqual("state-change", published_payload["reason"])

    def test_admin_exports_return_json_and_manual_state_backup(self):
        main.costume_signups = [main.CostumeSignup("Ada", "Vampire", "")]
        main.costume_votes = [[10]]
        main.karaoke_signups = [
            main.KaraokeSignup("Grace", "Thriller", "Michael Jackson", "")
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            state_response = client.get("/admin/export/state")
            results_response = client.get("/admin/export/costume-results")
            lineup_response = client.get("/admin/export/karaoke-lineup")

        state_export = json.loads(state_response.get_data(as_text=True))
        results_export = json.loads(results_response.get_data(as_text=True))
        lineup_export = json.loads(lineup_response.get_data(as_text=True))
        backup_keys = [
            key for key in self.fake_redis.store
            if key.startswith(main.redis_key("state:backup:"))
        ]

        self.assertEqual(200, state_response.status_code)
        self.assertEqual(200, results_response.status_code)
        self.assertEqual(200, lineup_response.status_code)
        self.assertEqual("Ada", state_export["costume_signups"][0]["name"])
        self.assertEqual("manual-export", json.loads(self.fake_redis.store[backup_keys[0]])["backup_reason"])
        self.assertEqual("Ada", results_export["results"][0]["name"])
        self.assertEqual("Grace", lineup_export["lineup"][0]["name"])
