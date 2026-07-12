import json
import os
import unittest

import redis

import main


class FakeLock:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.acquired = False
        self.released = False

    def acquire(self, blocking=True):
        if not self.redis_client.lock_should_acquire:
            return False
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
        self.lock_should_acquire = True

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


class FailingRedis(FakeRedis):
    def ping(self):
        raise redis.RedisError("redis unavailable")


class FakeSESClient:
    def __init__(self, failing_recipients=None):
        self.failing_recipients = set(failing_recipients or [])
        self.sent_messages = []

    def send_email(self, **kwargs):
        recipient = kwargs["Destination"]["ToAddresses"][0]
        if recipient in self.failing_recipients:
            raise RuntimeError("SES send failed")
        self.sent_messages.append(kwargs)
        return {"MessageId": f"message-{len(self.sent_messages)}"}


class RedisStateTests(unittest.TestCase):
    def setUp(self):
        self.fake_redis = FakeRedis()
        self.original_redis_client = main.redis_client
        self.original_redis_available = main.redis_state_available
        self.original_config = main.REDIS_CONFIG
        self.original_testing = main.app.config["TESTING"]
        self.original_admin_password = main.app.config["ADMIN_PASSWORD"]
        self.original_party_start = main.app.config["PARTY_START"]
        self.original_email_updates_enabled = main.app.config["EMAIL_UPDATES_ENABLED"]
        self.original_email_from = main.app.config["EMAIL_FROM"]
        self.original_public_base_url = main.app.config["PUBLIC_BASE_URL"]
        self.original_create_ses_client = main.create_ses_client
        self.original_app_env = os.environ.get("APP_ENV")

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
        main.app.config["ADMIN_PASSWORD"] = "admin-secret"
        main.app.config["EMAIL_UPDATES_ENABLED"] = False
        main.app.config["EMAIL_FROM"] = "Halloween Party <no-reply@tnq-halloween.com>"
        main.app.config["PUBLIC_BASE_URL"] = "https://tnq-halloween.com"
        self.reset_state()

    def tearDown(self):
        main.redis_client = self.original_redis_client
        main.redis_state_available = self.original_redis_available
        main.REDIS_CONFIG = self.original_config
        main.app.config["TESTING"] = self.original_testing
        main.app.config["ADMIN_PASSWORD"] = self.original_admin_password
        main.app.config["PARTY_START"] = self.original_party_start
        main.app.config["EMAIL_UPDATES_ENABLED"] = self.original_email_updates_enabled
        main.app.config["EMAIL_FROM"] = self.original_email_from
        main.app.config["PUBLIC_BASE_URL"] = self.original_public_base_url
        main.create_ses_client = self.original_create_ses_client
        if self.original_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = self.original_app_env
        self.reset_state()

    def reset_state(self):
        main.costume_signups = []
        main.karaoke_signups = []
        main.costume_votes = []
        main.costume_ballots = {}
        main.registered_users = {}
        main.user_accounts = {}
        main.password_reset_tokens = {}
        main.menu_items = []
        main.drink_orders = []
        main.rsvp_signups = []
        main.rsvp_updates = []
        main.submitted_costume_votes = set()
        main.live_display_override = None
        main.landing_page_target = main.DEFAULT_LANDING_PAGE_TARGET
        main.party_code_hash = main.generate_password_hash("invite-code")
        main.party_code_hint = ""
        main.display_update_version = 0
        main.contest_state.clear()
        main.contest_state.update(main.copy.deepcopy(main.DEFAULT_CONTEST_STATE))
        main.karaoke_state.clear()
        main.karaoke_state.update(main.copy.deepcopy(main.DEFAULT_KARAOKE_STATE))
        main.party_details = main.copy.deepcopy(main.DEFAULT_PARTY_DETAILS)

    def login_regular(self, client, user_id="user-1", username="Jamie"):
        main.registered_users[user_id] = username
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["username"] = username
            session["roles"] = ["regular"]

    def login_admin(self, client):
        with client.session_transaction() as session:
            roles = set(session.get("roles", []))
            roles.add("admin")
            session["roles"] = sorted(roles)
            session["admin_authenticated"] = True

    def verify_party_code(self, client):
        with client.session_transaction() as session:
            session["party_code_verified"] = True

    def add_user_account(self, username="Jamie", password="party-password", user_id="user-1", email="jamie@example.com"):
        account = main.create_user_account(username, password, email)
        account["id"] = user_id
        main.user_accounts[main.normalize_username(username)] = account
        return account

    def redis_state(self):
        return json.loads(self.fake_redis.store[main.redis_key("state")])

    def password_reset_token_from_email(self, fake_ses):
        text_body = fake_ses.sent_messages[-1]["Content"]["Simple"]["Body"]["Text"]["Data"]
        marker = "/party/password-reset/"
        reset_url = next(line.strip() for line in text_body.splitlines() if marker in line)
        return reset_url.rsplit(marker, 1)[1].strip()

    def save_current_state(self):
        main.save_state_to_redis()

    def test_serialization_round_trip_preserves_state(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "ada@example.com", "costume-1"),
            main.CostumeSignup("Grace", "Ghost", "", "costume-2"),
        ]
        main.karaoke_signups = [
            main.KaraokeSignup("Lin", "Thriller", "Michael Jackson", "https://example.test/video", "karaoke-1")
        ]
        main.costume_ballots = {
            "user-1": {
                "costume-1": 8,
                "costume-2": 10,
            },
            "user-2": {
                "costume-1": 9,
            },
        }
        main.registered_users = {"user-1": "Ada"}
        main.user_accounts = {
            "ada": {
                "id": "user-1",
                "username": "Ada",
                "email": "ada@example.com",
                "roles": ["regular", "bartender"],
                "password_hash": main.generate_password_hash("party-password"),
                "created_at": "2026-07-06T00:00:00Z",
            }
        }
        main.menu_items = [
            {
                "id": "drink-1",
                "name": "Witch Margarita",
                "category": "drink",
                "description": "Lime and smoke.",
                "image_url": "https://example.test/margarita.jpg",
                "recipe": "Shake with ice.",
                "available": True,
                "created_at": "2026-07-06T00:00:00Z",
            }
        ]
        main.drink_orders = [
            {
                "id": "order-1",
                "user_id": "user-1",
                "username": "Ada",
                "email": "ada@example.com",
                "menu_item_id": "drink-1",
                "item_name": "Witch Margarita",
                "item_image_url": "https://example.test/margarita.jpg",
                "recipe": "Shake with ice.",
                "status": "complete",
                "estimated_ready_at": "2026-07-06T00:08:00Z",
                "created_at": "2026-07-06T00:00:00Z",
                "started_at": "2026-07-06T00:01:00Z",
                "completed_at": "2026-07-06T00:06:00Z",
                "completed_seconds": 360,
            }
        ]
        main.rsvp_signups = [
            main.RSVPSignup(
                "Morgan",
                "morgan@example.com",
                2,
                "Bringing cider",
                "2026-07-06T00:00:00Z",
                "rsvp-1",
            )
        ]
        main.rsvp_updates = [
            main.RSVPUpdate(
                "Parking",
                "Use the west side of the street.",
                "2026-07-07T00:00:00Z",
                "update-1",
            )
        ]
        main.submitted_costume_votes = {"user-1", "user-2"}
        main.contest_state["contest_started"] = True
        main.contest_state["voting_open"] = True
        main.karaoke_state["party_started"] = True
        main.live_display_override = {"type": "notice", "title": "Tonight"}
        main.landing_page_target = "party_login"
        main.party_code_hash = main.generate_password_hash("secret-code")
        main.party_code_hint = "On your invite"
        main.party_details = {
            "date": "Saturday, October 31",
            "time": "8:00 PM",
            "location": "The haunted house",
            "map_address": "123 Pumpkin Lane, Denver, CO",
            "overview": "Bring a costume.",
        }
        main.display_update_version = 7

        snapshot = main.snapshot_state()
        self.reset_state()
        main.apply_state_snapshot(snapshot)

        self.assertEqual(["Ada", "Grace"], [signup.name for signup in main.costume_signups])
        self.assertEqual("Thriller", main.karaoke_signups[0].song_title)
        self.assertEqual(["costume-1", "costume-2"], [signup.id for signup in main.costume_signups])
        self.assertEqual([[8, 9], [10]], main.costume_votes)
        self.assertEqual(
            {
                "user-1": {"costume-1": 8, "costume-2": 10},
                "user-2": {"costume-1": 9},
            },
            main.costume_ballots,
        )
        self.assertEqual({"user-1": "Ada"}, main.registered_users)
        self.assertEqual("Ada", main.user_accounts["ada"]["username"])
        self.assertEqual(["bartender", "regular"], main.user_accounts["ada"]["roles"])
        self.assertTrue(main.check_password_hash(main.user_accounts["ada"]["password_hash"], "party-password"))
        self.assertEqual("Witch Margarita", main.menu_items[0]["name"])
        self.assertEqual("https://example.test/margarita.jpg", main.menu_items[0]["image_url"])
        self.assertEqual("order-1", main.drink_orders[0]["id"])
        self.assertEqual(360, main.drink_orders[0]["completed_seconds"])
        self.assertEqual("Morgan", main.rsvp_signups[0].name)
        self.assertEqual(2, main.rsvp_signups[0].guest_count)
        self.assertEqual("Bringing cider", main.rsvp_signups[0].note)
        self.assertEqual("Parking", main.rsvp_updates[0].title)
        self.assertEqual("Use the west side of the street.", main.rsvp_updates[0].message)
        self.assertEqual({"user-1", "user-2"}, main.submitted_costume_votes)
        self.assertTrue(main.contest_state["contest_started"])
        self.assertTrue(main.contest_state["voting_open"])
        self.assertTrue(main.karaoke_state["party_started"])
        self.assertEqual({"type": "notice", "title": "Tonight"}, main.live_display_override)
        self.assertEqual("party_login", main.landing_page_target)
        self.assertTrue(main.check_password_hash(main.party_code_hash, "secret-code"))
        self.assertEqual("On your invite", main.party_code_hint)
        self.assertEqual("Saturday, October 31", main.party_details["date"])
        self.assertEqual("8:00 PM", main.party_details["time"])
        self.assertEqual("The haunted house", main.party_details["location"])
        self.assertEqual("123 Pumpkin Lane, Denver, CO", main.party_details["map_address"])
        self.assertEqual("Bring a costume.", main.party_details["overview"])
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

    def test_load_state_from_redis_migrates_legacy_index_votes_to_ballots(self):
        legacy_state = {
            "schema_version": 1,
            "costume_signups": [
                {"name": "Ada", "costume": "Vampire", "contact": ""},
                {"name": "Grace", "costume": "Ghost", "contact": ""},
            ],
            "karaoke_signups": [],
            "costume_votes": [[9, 8], [7, 10]],
            "registered_users": {"user-1": "Jamie", "user-2": "Morgan"},
            "submitted_costume_votes": ["user-1", "user-2"],
            "contest_state": {},
            "karaoke_state": {},
            "live_display_override": None,
            "display_update_version": 4,
        }
        self.fake_redis.set(main.redis_key("state"), json.dumps(legacy_state))

        self.assertTrue(main.load_state_from_redis())

        costume_ids = [signup.id for signup in main.costume_signups]
        self.assertEqual(
            {
                "user-1": {
                    costume_ids[0]: 9,
                    costume_ids[1]: 7,
                },
                "user-2": {
                    costume_ids[0]: 8,
                    costume_ids[1]: 10,
                },
            },
            main.costume_ballots,
        )
        self.assertEqual([[9, 8], [7, 10]], main.costume_votes)

    def test_attendee_signups_persist_and_publish_display_updates(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            costume_response = client.post(
                "/party/costumes",
                data={"name": "Ada", "costume": "Vampire", "contact": "ada@example.com"},
            )
            karaoke_response = client.post(
                "/party/karaoke",
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
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
            main.CostumeSignup("Grace", "Ghost", "", "costume-2"),
        ]
        main.registered_users = {"user-1": "Jamie"}
        main.contest_state["contest_started"] = True
        main.contest_state["voting_open"] = True
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)

            first_response = client.post(
                "/party/costumes/vote",
                data={"rating_costume-1": "9", "rating_costume-2": "7"},
            )
            second_response = client.post(
                "/party/costumes/vote",
                data={"rating_costume-1": "1", "rating_costume-2": "1"},
            )

        state = self.redis_state()
        self.assertEqual(302, first_response.status_code)
        self.assertEqual(200, second_response.status_code)
        self.assertEqual({"costume-1": 9, "costume-2": 7}, state["costume_ballots"]["user-1"])
        self.assertEqual(["user-1"], state["submitted_costume_votes"])

    def test_costume_voting_is_hidden_until_contest_is_started(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
        ]
        main.registered_users = {"user-1": "Jamie"}
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            dashboard_response = client.get("/party")
            voting_response = client.get("/party/costumes/vote")

        dashboard_body = dashboard_response.get_data(as_text=True)
        self.assertEqual(200, dashboard_response.status_code)
        self.assertNotIn("Start Voting", dashboard_body)
        self.assertEqual(302, voting_response.status_code)
        self.assertEqual("/party", voting_response.headers["Location"])

    def test_admin_can_start_stop_and_reset_costume_contest(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            start_response = client.post("/admin", data={"action": "start_costume_contest"})
            state_after_start = self.redis_state()
            stop_response = client.post("/admin", data={"action": "stop_costume_contest"})
            state_after_stop = self.redis_state()

        self.assertEqual(200, start_response.status_code)
        self.assertTrue(state_after_start["contest_state"]["contest_started"])
        self.assertTrue(state_after_start["contest_state"]["voting_open"])
        self.assertEqual("contest_start", state_after_start["live_display_override"]["type"])
        self.assertEqual(200, stop_response.status_code)
        self.assertFalse(state_after_stop["contest_state"]["contest_started"])
        self.assertFalse(state_after_stop["contest_state"]["voting_open"])
        self.assertIsNone(state_after_stop["live_display_override"])

        main.load_state_from_redis()
        main.contest_state["contest_started"] = True
        main.contest_state["voting_open"] = True
        main.contest_state["winner"] = {"id": "costume-1", "name": "Ada"}
        main.contest_state["winner_locked"] = True
        main.costume_ballots = {"user-1": {"costume-1": 10}}
        main.submitted_costume_votes = {"user-1"}
        main.live_display_override = {"type": "winner", "title": "Costume Contest Champion"}
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            reset_response = client.post("/admin", data={"action": "reset_costume_contest"})

        state_after_reset = self.redis_state()
        self.assertEqual(200, reset_response.status_code)
        self.assertFalse(state_after_reset["contest_state"]["contest_started"])
        self.assertFalse(state_after_reset["contest_state"]["voting_open"])
        self.assertIsNone(state_after_reset["contest_state"]["winner"])
        self.assertFalse(state_after_reset["contest_state"]["winner_locked"])
        self.assertEqual({}, state_after_reset["costume_ballots"])
        self.assertEqual([], state_after_reset["submitted_costume_votes"])
        self.assertEqual("Ada", state_after_reset["costume_signups"][0]["name"])
        self.assertIsNone(state_after_reset["live_display_override"])

    def test_admin_can_start_stop_and_reset_karaoke_party(self):
        main.karaoke_signups = [
            main.KaraokeSignup("Grace", "Thriller", "Michael Jackson", "", "karaoke-1"),
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            start_response = client.post("/admin", data={"action": "start_karaoke_party"})
            state_after_start = self.redis_state()
            stop_response = client.post("/admin", data={"action": "stop_karaoke_party"})
            state_after_stop = self.redis_state()

        self.assertEqual(200, start_response.status_code)
        self.assertTrue(state_after_start["karaoke_state"]["party_started"])
        self.assertEqual("karaoke-1", state_after_start["karaoke_state"]["current_singer_id"])
        self.assertEqual("karaoke_start", state_after_start["live_display_override"]["type"])
        self.assertEqual(200, stop_response.status_code)
        self.assertFalse(state_after_stop["karaoke_state"]["party_started"])
        self.assertIsNone(state_after_stop["karaoke_state"]["current_singer_id"])
        self.assertIsNone(state_after_stop["live_display_override"])

        main.load_state_from_redis()
        main.karaoke_state["party_started"] = True
        main.karaoke_state["current_singer_id"] = "karaoke-1"
        main.live_display_override = {"type": "karaoke_start", "title": "Halloween Karaoke Party"}
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            reset_response = client.post("/admin", data={"action": "reset_karaoke_party"})

        state_after_reset = self.redis_state()
        self.assertEqual(200, reset_response.status_code)
        self.assertFalse(state_after_reset["karaoke_state"]["party_started"])
        self.assertIsNone(state_after_reset["karaoke_state"]["current_singer_id"])
        self.assertEqual("Grace", state_after_reset["karaoke_signups"][0]["name"])
        self.assertIsNone(state_after_reset["live_display_override"])

    def test_admin_reorder_keeps_votes_aligned_with_costumes(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
            main.CostumeSignup("Grace", "Ghost", "", "costume-2"),
        ]
        main.costume_ballots = {"user-1": {"costume-1": 1, "costume-2": 9}}
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post("/admin", data={"action": "move_costume_down", "index": "0"})

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertEqual(["Grace", "Ada"], [entry["name"] for entry in state["costume_signups"]])
        self.assertEqual({"costume-1": 1, "costume-2": 9}, state["costume_ballots"]["user-1"])

    def test_display_data_reflects_persisted_state_and_update_version_publish(self):
        main.app.config["PARTY_START"] = "2026-01-01T00:00:00+00:00"
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            client.post(
                "/party/costumes",
                data={"name": "Ada", "costume": "Vampire", "contact": ""},
            )
            self.login_admin(client)
            response = client.get("/api/display-data")

        payload = response.get_json()
        state = self.redis_state()
        published_channel, published_message = self.fake_redis.published_messages[-1]
        published_payload = json.loads(published_message)

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, payload["costume_count"])
        self.assertEqual(0, payload["karaoke_count"])
        self.assertEqual(1, payload["display_update_version"])
        self.assertTrue(any(entry["primary"] == "Ada" for entry in payload["entries"]))
        self.assertEqual(1, state["display_update_version"])
        self.assertEqual(main.redis_key("display:pubsub"), published_channel)
        self.assertEqual(1, published_payload["version"])
        self.assertEqual("state-change", published_payload["reason"])

    def test_health_returns_state_store_status(self):
        main.display_update_version = 5
        main.redis_state_available = True

        with main.app.test_client() as client:
            response = client.get("/health")

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("halloween-party", payload["app"])
        self.assertEqual("ok", payload["status"])
        self.assertTrue(payload["redis"]["ok"])
        self.assertEqual("test-halloween", payload["redis"]["prefix"])
        self.assertTrue(payload["state"]["available"])
        self.assertEqual(5, payload["state"]["display_update_version"])

    def test_health_fails_when_production_redis_ping_fails(self):
        main.redis_client = FailingRedis()
        main.redis_state_available = False
        os.environ["APP_ENV"] = "production"

        with main.app.test_client() as client:
            response = client.get("/health")

        payload = response.get_json()
        self.assertEqual(503, response.status_code)
        self.assertEqual("unhealthy", payload["status"])
        self.assertFalse(payload["redis"]["ok"])
        self.assertTrue(payload["redis"]["required"])
        self.assertEqual("RedisError", payload["redis"]["error"])

    def test_admin_exports_return_json_and_manual_state_backup(self):
        main.costume_signups = [main.CostumeSignup("Ada", "Vampire", "", "costume-1")]
        main.costume_ballots = {"user-1": {"costume-1": 10}}
        main.karaoke_signups = [
            main.KaraokeSignup("Grace", "Thriller", "Michael Jackson", "", "karaoke-1")
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
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

    def test_admin_blocks_destructive_costume_lineup_changes_while_voting_is_open(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
            main.CostumeSignup("Grace", "Ghost", "", "costume-2"),
        ]
        main.registered_users = {"user-1": "Jamie"}
        main.costume_ballots = {"user-1": {"costume-1": 8, "costume-2": 9}}
        main.contest_state["contest_started"] = True
        main.contest_state["voting_open"] = True
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={"action": "move_costume_down", "entry_id": "costume-1"},
            )

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertEqual(["Ada", "Grace"], [entry["name"] for entry in state["costume_signups"]])
        self.assertIn("disabled while costume voting is open", response.get_data(as_text=True))

    def test_lock_contention_returns_busy_response(self):
        self.save_current_state()
        self.fake_redis.lock_should_acquire = False

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.post(
                "/party/costumes",
                data={"name": "Ada", "costume": "Vampire", "contact": ""},
            )

        self.assertEqual(503, response.status_code)
        self.assertIn("state store is busy", response.get_data(as_text=True))

    def test_admin_auth_requires_password_when_configured(self):
        main.app.config["ADMIN_PASSWORD"] = "secret"
        self.save_current_state()

        with main.app.test_client() as client:
            login_redirect = client.get("/admin")
            bad_login = client.post(
                "/admin/login",
                data={"password": "wrong", "next": "/admin"},
            )
            good_login = client.post(
                "/admin/login",
                data={"password": "secret", "next": "/admin"},
            )
            admin_response = client.get("/admin")

        self.assertEqual(302, login_redirect.status_code)
        self.assertIn("/admin/login", login_redirect.headers["Location"])
        self.assertEqual(200, bad_login.status_code)
        self.assertIn("Incorrect admin password", bad_login.get_data(as_text=True))
        self.assertEqual(302, good_login.status_code)
        self.assertEqual(200, admin_response.status_code)

    def test_root_defaults_to_rsvp_landing_page(self):
        self.save_current_state()

        with main.app.test_client() as client:
            response = client.get("/")

        self.assertEqual(302, response.status_code)
        self.assertEqual("/rsvp", response.headers["Location"])

    def test_admin_can_update_public_landing_page(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "update_landing_page",
                    "landing_page_target": "party_login",
                },
            )
            root_response = client.get("/")

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertEqual("party_login", state["landing_page_target"])
        self.assertEqual(302, root_response.status_code)
        self.assertEqual("/party/login", root_response.headers["Location"])

    def test_admin_can_set_party_code_without_exposing_plaintext(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "update_party_code",
                    "party_code": "new-invite-code",
                    "party_code_hint": "Ask Tony",
                },
            )

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertTrue(main.check_password_hash(state["party_code_hash"], "new-invite-code"))
        self.assertNotIn("new-invite-code", state["party_code_hash"])
        self.assertEqual("Ask Tony", state["party_code_hint"])

    def test_party_code_required_before_login_form_is_visible(self):
        self.add_user_account()
        self.save_current_state()

        with main.app.test_client() as client:
            login_gate = client.get("/party/login")
            bad_code = client.post(
                "/party/login",
                data={"party_code": "wrong", "next": "/party"},
            )
            good_code = client.post(
                "/party/login",
                data={"party_code": "invite-code", "next": "/party"},
            )
            login_form = client.get("/party/login?next=/party")

        self.assertEqual(200, login_gate.status_code)
        self.assertIn("Enter the Party Code", login_gate.get_data(as_text=True))
        self.assertNotIn("Your Name", login_gate.get_data(as_text=True))
        self.assertEqual(200, bad_code.status_code)
        self.assertIn("did not match", bad_code.get_data(as_text=True))
        self.assertEqual(302, good_code.status_code)
        self.assertIn("/party/login", good_code.headers["Location"])
        self.assertIn("Welcome to the Halloween Hub", login_form.get_data(as_text=True))

    def test_rsvp_requires_party_code_and_creates_independent_rsvp_after_unlock(self):
        main.rsvp_updates = [
            main.RSVPUpdate("Parking", "Use the west side of the street.", "2026-07-07T00:00:00Z", "update-1")
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            locked_rsvp = client.get("/rsvp")
            unlock_response = client.post(
                "/rsvp",
                data={"party_code": "invite-code"},
            )
            rsvp_form = client.get("/rsvp")
            signup_response = client.post(
                "/rsvp",
                data={
                    "action": "submit_rsvp",
                    "username": "Casey",
                    "contact": "casey@example.com",
                    "guest_count": "3",
                    "note": "Arriving after 8",
                },
            )
            confirmation_response = client.get("/rsvp")

            with client.session_transaction() as session:
                roles = session.get("roles", [])
                rsvp_id = session.get("rsvp_id")

        state = self.redis_state()
        self.assertEqual(200, locked_rsvp.status_code)
        locked_body = locked_rsvp.get_data(as_text=True)
        self.assertIn("Unlock RSVP", locked_body)
        self.assertNotIn("Date", locked_body)
        self.assertNotIn("Time", locked_body)
        self.assertNotIn("Location", locked_body)
        self.assertNotIn("Latest Updates", locked_body)
        self.assertNotIn("Get Directions", locked_body)
        self.assertNotIn("Costume Contest", locked_body)
        self.assertNotIn("Karaoke", locked_body)
        self.assertEqual(302, unlock_response.status_code)
        self.assertIn("Save your RSVP", rsvp_form.get_data(as_text=True))
        self.assertNotIn("Password", rsvp_form.get_data(as_text=True))
        self.assertIn("Date", rsvp_form.get_data(as_text=True))
        self.assertIn("Latest Updates", rsvp_form.get_data(as_text=True))
        self.assertNotIn("<h3>Costume Contest</h3>", rsvp_form.get_data(as_text=True))
        self.assertNotIn("<h3>Karaoke</h3>", rsvp_form.get_data(as_text=True))
        self.assertEqual(302, signup_response.status_code)
        self.assertEqual("Casey", state["rsvp_signups"][0]["name"])
        self.assertEqual("casey@example.com", state["rsvp_signups"][0]["contact"])
        self.assertTrue(state["rsvp_signups"][0]["email_updates_acknowledged"])
        self.assertEqual(3, state["rsvp_signups"][0]["guest_count"])
        self.assertEqual("Arriving after 8", state["rsvp_signups"][0]["note"])
        self.assertEqual(state["rsvp_signups"][0]["id"], rsvp_id)
        self.assertNotIn("casey", state["user_accounts"])
        self.assertNotIn("regular", roles)
        self.assertIn("You're on the RSVP list", confirmation_response.get_data(as_text=True))
        self.assertNotIn("Total guest", confirmation_response.get_data(as_text=True))
        self.assertNotIn("Karaoke song", confirmation_response.get_data(as_text=True))

    def test_rsvp_unlock_is_per_browser_session(self):
        self.save_current_state()

        with main.app.test_client() as unlocked_client:
            unlocked_client.post("/rsvp", data={"party_code": "invite-code"})
            unlocked_response = unlocked_client.get("/rsvp")

        with main.app.test_client() as locked_client:
            locked_response = locked_client.get("/rsvp")

        unlocked_body = unlocked_response.get_data(as_text=True)
        locked_body = locked_response.get_data(as_text=True)
        self.assertIn("Save your RSVP", unlocked_body)
        self.assertIn("Date", unlocked_body)
        self.assertIn("Unlock RSVP", locked_body)
        self.assertNotIn("Date", locked_body)
        self.assertNotIn("Latest Updates", locked_body)
        self.assertNotIn("Costume", locked_body)
        self.assertNotIn("Karaoke", locked_body)

    def test_admin_can_update_party_details_on_rsvp_page(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "update_party_details",
                    "party_date": "Saturday, October 31",
                    "party_time": "8:00 PM",
                    "party_location": "The haunted house",
                    "party_map_address": "123 Pumpkin Lane, Denver, CO",
                    "party_overview": "Bring a costume and your best karaoke song.",
                },
            )
            self.verify_party_code(client)
            rsvp_response = client.get("/rsvp")

        state = self.redis_state()
        body = rsvp_response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertEqual("Saturday, October 31", state["party_details"]["date"])
        self.assertEqual("8:00 PM", state["party_details"]["time"])
        self.assertEqual("The haunted house", state["party_details"]["location"])
        self.assertEqual("123 Pumpkin Lane, Denver, CO", state["party_details"]["map_address"])
        self.assertIn("Saturday, October 31", body)
        self.assertIn("8:00 PM", body)
        self.assertIn("The haunted house", body)
        self.assertIn("Bring a costume and your best karaoke song.", body)
        self.assertIn("Get Directions", body)
        self.assertIn("https://www.google.com/maps/dir/?api=1&amp;destination=123+Pumpkin+Lane%2C+Denver%2C+CO", body)
        self.assertIn("https://www.google.com/maps?q=123+Pumpkin+Lane%2C+Denver%2C+CO&amp;output=embed", body)

    def test_admin_page_shows_rsvp_list(self):
        main.rsvp_signups = [
            main.RSVPSignup(
                id="rsvp-1",
                name="Casey",
                contact="casey@example.com",
                guest_count=2,
                note="Vegetarian",
                created_at="2026-07-07T00:00:00Z",
            )
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.get("/admin")

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("RSVP List", body)
        self.assertIn("Casey", body)
        self.assertIn("casey@example.com", body)
        self.assertIn("Vegetarian", body)

    def test_admin_can_add_update_and_delete_rsvps(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            add_response = client.post(
                "/admin",
                data={
                    "action": "add_rsvp",
                    "name": "Morgan",
                    "contact": "Morgan@Example.COM",
                    "guest_count": "2",
                    "note": "Needs parking",
                },
            )
            state_after_add = self.redis_state()
            rsvp_id = state_after_add["rsvp_signups"][0]["id"]
            update_response = client.post(
                "/admin",
                data={
                    "action": "update_rsvp",
                    "rsvp_id": rsvp_id,
                    "name": "Morgan Lee",
                    "contact": "morgan.lee@example.com",
                    "guest_count": "3",
                    "note": "Arriving at 8",
                },
            )
            state_after_update = self.redis_state()
            delete_response = client.post(
                "/admin",
                data={
                    "action": "delete_rsvp",
                    "rsvp_id": rsvp_id,
                },
            )

        state = self.redis_state()
        self.assertEqual(200, add_response.status_code)
        self.assertEqual(200, update_response.status_code)
        self.assertEqual(200, delete_response.status_code)
        self.assertEqual("Morgan", state_after_add["rsvp_signups"][0]["name"])
        self.assertEqual("morgan@example.com", state_after_add["rsvp_signups"][0]["contact"])
        self.assertEqual("Morgan Lee", state_after_update["rsvp_signups"][0]["name"])
        self.assertEqual(3, state_after_update["rsvp_signups"][0]["guest_count"])
        self.assertEqual("Arriving at 8", state_after_update["rsvp_signups"][0]["note"])
        self.assertEqual([], state["rsvp_signups"])

    def test_admin_can_post_rsvp_updates_and_rsvp_page_shows_newest_first(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            first_response = client.post(
                "/admin",
                data={
                    "action": "add_rsvp_update",
                    "title": "Costume reminder",
                    "message": "Bring your costume contest energy.",
                },
            )
            second_response = client.post(
                "/admin",
                data={
                    "action": "add_rsvp_update",
                    "title": "Parking",
                    "message": "Use the west side of the street.",
                },
            )
            self.verify_party_code(client)
            rsvp_response = client.get("/rsvp")

        state = self.redis_state()
        body = rsvp_response.get_data(as_text=True)
        parking_index = body.index("Parking")
        costume_index = body.index("Costume reminder")
        self.assertEqual(200, first_response.status_code)
        self.assertEqual(200, second_response.status_code)
        self.assertEqual(2, len(state["rsvp_updates"]))
        self.assertLess(parking_index, costume_index)
        self.assertIn("Latest update", body)

    def test_rsvp_update_message_allows_longer_host_updates(self):
        self.save_current_state()
        long_message = "Bring your costume. " * 40

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "add_rsvp_update",
                    "title": "Long update",
                    "message": long_message,
                },
            )

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertEqual(long_message.strip(), state["rsvp_updates"][0]["message"])

    def test_update_email_recipients_include_rsvps_and_registered_users_once(self):
        main.rsvp_signups = [
            main.RSVPSignup(
                name="Casey",
                contact="casey@example.com",
                email_updates_acknowledged=True,
            ),
            main.RSVPSignup(
                name="Duplicate Casey",
                contact="CASEY@example.com",
                email_updates_acknowledged=True,
            ),
            main.RSVPSignup(
                name="Phone Only",
                contact="303-555-0100",
                email_updates_acknowledged=True,
            ),
            main.RSVPSignup(
                name="No Ack",
                contact="noack@example.com",
                email_updates_acknowledged=False,
            ),
        ]
        main.user_accounts = {
            "morgan": main.create_user_account("Morgan", "party-password", "morgan@example.com"),
            "casey": main.create_user_account("Casey", "party-password", "casey@example.com"),
            "old-account": {
                "id": "user-old",
                "username": "Old Account",
                "password_hash": main.generate_password_hash("party-password"),
                "created_at": "2026-07-06T00:00:00Z",
            },
        }

        recipients = main.collect_update_email_recipients()

        self.assertEqual(["casey@example.com", "noack@example.com", "morgan@example.com"], recipients)

    def test_admin_rsvp_update_sends_email_without_blocking_on_partial_failure(self):
        main.rsvp_signups = [
            main.RSVPSignup(
                id="rsvp-casey",
                name="Casey",
                contact="casey@example.com",
                email_updates_acknowledged=True,
            )
        ]
        main.user_accounts = {
            "morgan": main.create_user_account("Morgan", "party-password", "morgan@example.com"),
        }
        self.save_current_state()
        fake_ses = FakeSESClient(failing_recipients={"morgan@example.com"})
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "add_rsvp_update",
                    "title": "Parking",
                    "message": "Use the west side of the street.",
                    "recipient_ids": ["rsvp:rsvp-casey", f"account:{main.user_accounts['morgan']['id']}"],
                },
            )

        state = self.redis_state()
        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertEqual("Parking", state["rsvp_updates"][0]["title"])
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertEqual(["casey@example.com"], fake_ses.sent_messages[0]["Destination"]["ToAddresses"])
        self.assertIn("Email sent to 1 selected recipient; 1 failed.", body)

    def test_admin_can_resend_rsvp_update_to_selected_recipients(self):
        account = main.create_user_account("Morgan", "party-password", "morgan@example.com")
        main.user_accounts = {"morgan": account}
        main.rsvp_signups = [
            main.RSVPSignup(
                id="rsvp-casey",
                name="Casey",
                contact="casey@example.com",
                email_updates_acknowledged=True,
            )
        ]
        main.rsvp_updates = [
            main.RSVPUpdate(
                id="update-1",
                title="Parking",
                message="Use the west side of the street.",
                created_at="2026-07-07T00:00:00Z",
            )
        ]
        self.save_current_state()
        fake_ses = FakeSESClient()
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "resend_rsvp_update",
                    "update_id": "update-1",
                    "recipient_ids": [f"account:{account['id']}"],
                },
            )

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertEqual(["morgan@example.com"], fake_ses.sent_messages[0]["Destination"]["ToAddresses"])
        self.assertIn("Resent RSVP update: Parking. Email sent to 1 selected recipient.", body)

    def test_pre_party_display_rotates_only_rsvp_cards_and_updates(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
        ]
        main.karaoke_signups = [
            main.KaraokeSignup("Grace", "Thriller", "Michael Jackson", "", "karaoke-1"),
        ]
        main.rsvp_updates = [
            main.RSVPUpdate("Parking", "Use the west side of the street.", "2026-07-07T00:00:00Z", "update-1")
        ]

        entries = main.build_rotation_entries()
        serialized_entries = json.dumps(entries)

        self.assertIn("RSVP", {entry["category"] for entry in entries})
        self.assertIn("RSVP Update", {entry["category"] for entry in entries})
        self.assertIn("Parking", serialized_entries)
        self.assertNotIn("Dressed as Vampire", serialized_entries)
        self.assertNotIn("Thriller", serialized_entries)

    def test_regular_user_login_grants_only_regular_route_access(self):
        self.add_user_account()
        self.save_current_state()

        with main.app.test_client() as client:
            protected_response = client.get("/party")
            self.verify_party_code(client)
            bad_login = client.post(
                "/party/login",
                data={
                    "username": "Jamie",
                    "password": "wrong",
                    "next": "/party",
                },
            )
            good_login = client.post(
                "/party/login",
                data={
                    "username": "Jamie",
                    "password": "party-password",
                    "next": "/party",
                },
            )
            halloween_response = client.get("/party")
            admin_response = client.get("/admin")
            display_response = client.get("/live-display")

            with client.session_transaction() as session:
                roles = session.get("roles", [])

        self.assertEqual(302, protected_response.status_code)
        self.assertIn("/party/login", protected_response.headers["Location"])
        self.assertEqual(200, bad_login.status_code)
        self.assertIn("Incorrect username or password", bad_login.get_data(as_text=True))
        self.assertEqual(302, good_login.status_code)
        self.assertEqual(200, halloween_response.status_code)
        self.assertIn("regular", roles)
        self.assertNotIn("admin", roles)
        self.assertEqual(302, admin_response.status_code)
        self.assertIn("/admin/login", admin_response.headers["Location"])
        self.assertEqual(302, display_response.status_code)
        self.assertIn("/admin/login", display_response.headers["Location"])

    def test_admin_can_manage_menu_images_and_assign_bartender_role(self):
        account = self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            add_response = client.post(
                "/admin",
                data={
                    "action": "add_menu_item",
                    "name": "Witch Margarita",
                    "category": "drink",
                    "description": "Lime, smoke, and salt.",
                    "image_url": "https://example.test/witch.jpg",
                    "recipe": "Shake tequila, lime, and syrup with ice.",
                    "available": "yes",
                },
            )
            role_response = client.post(
                "/admin",
                data={
                    "action": "set_user_roles",
                    "account_id": account["id"],
                    "bartender": "yes",
                },
            )

        state = self.redis_state()
        self.assertEqual(200, add_response.status_code)
        self.assertEqual(200, role_response.status_code)
        self.assertEqual("Witch Margarita", state["menu_items"][0]["name"])
        self.assertEqual("https://example.test/witch.jpg", state["menu_items"][0]["image_url"])
        self.assertIn("bartender", state["user_accounts"]["jamie"]["roles"])

    def test_admin_can_crud_user_accounts_and_reset_passwords(self):
        self.save_current_state()
        fake_ses = FakeSESClient()
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            self.login_admin(client)
            add_response = client.post(
                "/admin",
                data={
                    "action": "add_user_account",
                    "username": "Morgan",
                    "email": "Morgan@Example.COM",
                    "password": "party-password",
                    "confirm_password": "party-password",
                    "bartender": "yes",
                },
            )
            state_after_add = self.redis_state()
            account_id = state_after_add["user_accounts"]["morgan"]["id"]
            update_response = client.post(
                "/admin",
                data={
                    "action": "update_user_account",
                    "account_id": account_id,
                    "username": "Morgan Lee",
                    "email": "morgan.lee@example.com",
                },
            )
            reset_response = client.post(
                "/admin",
                data={
                    "action": "reset_user_password",
                    "account_id": account_id,
                    "password": "new-party-password",
                    "confirm_password": "new-party-password",
                },
            )

        state_after_reset = self.redis_state()
        self.assertEqual(200, add_response.status_code)
        self.assertIn("sent a welcome email", add_response.get_data(as_text=True))
        self.assertEqual(200, update_response.status_code)
        self.assertEqual(200, reset_response.status_code)
        self.assertEqual("morgan@example.com", state_after_add["user_accounts"]["morgan"]["email"])
        self.assertIn("bartender", state_after_add["user_accounts"]["morgan"]["roles"])
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertEqual(["morgan@example.com"], fake_ses.sent_messages[0]["Destination"]["ToAddresses"])
        self.assertNotIn("morgan", state_after_reset["user_accounts"])
        self.assertEqual("Morgan Lee", state_after_reset["user_accounts"]["morgan lee"]["username"])
        self.assertEqual(["regular"], state_after_reset["user_accounts"]["morgan lee"]["roles"])
        self.assertTrue(
            main.check_password_hash(
                state_after_reset["user_accounts"]["morgan lee"]["password_hash"],
                "new-party-password",
            )
        )

        main.load_state_from_redis()
        main.costume_ballots[account_id] = {"costume-1": 9}
        main.submitted_costume_votes.add(account_id)
        main.registered_users[account_id] = "Morgan Lee"
        main.password_reset_tokens["token-hash"] = {
            "normalized_username": "morgan lee",
            "account_id": account_id,
            "email": "morgan.lee@example.com",
            "created_at": "2026-12-01T00:00:00Z",
            "expires_at": "2026-12-01T00:45:00Z",
            "used_at": "",
        }
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            delete_response = client.post(
                "/admin",
                data={
                    "action": "delete_user_account",
                    "account_id": account_id,
                },
            )

        state_after_delete = self.redis_state()
        self.assertEqual(200, delete_response.status_code)
        self.assertEqual({}, state_after_delete["user_accounts"])
        self.assertNotIn(account_id, state_after_delete["registered_users"])
        self.assertNotIn(account_id, state_after_delete["costume_ballots"])
        self.assertNotIn(account_id, state_after_delete["submitted_costume_votes"])
        self.assertEqual({}, state_after_delete["password_reset_tokens"])

    def test_admin_account_creation_continues_when_welcome_email_fails(self):
        self.save_current_state()
        fake_ses = FakeSESClient(failing_recipients={"morgan@example.com"})
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "add_user_account",
                    "username": "Morgan",
                    "email": "morgan@example.com",
                    "password": "party-password",
                    "confirm_password": "party-password",
                },
            )

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertIn("morgan", state["user_accounts"])
        self.assertIn("welcome email was not sent", response.get_data(as_text=True))
        self.assertEqual(0, len(fake_ses.sent_messages))

    def test_attendee_can_order_drink_and_menu_displays_images(self):
        main.menu_items = [
            {
                "id": "drink-1",
                "name": "Witch Margarita",
                "category": "drink",
                "description": "Lime, smoke, and salt.",
                "image_url": "https://example.test/witch.jpg",
                "recipe": "Shake tequila, lime, and syrup with ice.",
                "available": True,
                "created_at": "2026-07-06T00:00:00Z",
            },
            {
                "id": "food-1",
                "name": "Pumpkin Bites",
                "category": "food",
                "description": "Small savory snacks.",
                "image_url": "https://example.test/bites.jpg",
                "recipe": "",
                "available": True,
                "created_at": "2026-07-06T00:00:00Z",
            },
        ]
        self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        self.save_current_state()

        fake_ses = FakeSESClient()
        main.app.config["EMAIL_UPDATES_ENABLED"] = True
        main.create_ses_client = lambda: fake_ses

        with main.app.test_client() as client:
            self.login_regular(client)
            menu_response = client.get("/party/menu")
            order_response = client.post("/party/menu", data={"menu_item_id": "drink-1"})

        state = self.redis_state()
        self.assertEqual(200, menu_response.status_code)
        menu_html = menu_response.get_data(as_text=True)
        self.assertIn("https://example.test/witch.jpg", menu_html)
        self.assertIn("https://example.test/bites.jpg", menu_html)
        self.assertEqual(302, order_response.status_code)
        self.assertEqual(1, len(state["drink_orders"]))
        self.assertEqual("received", state["drink_orders"][0]["status"])
        self.assertEqual("https://example.test/witch.jpg", state["drink_orders"][0]["item_image_url"])
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertIn("Drink order received", fake_ses.sent_messages[0]["Content"]["Simple"]["Body"]["Html"]["Data"])

    def test_food_items_cannot_be_ordered_as_drinks(self):
        main.menu_items = [
            {
                "id": "food-1",
                "name": "Pumpkin Bites",
                "category": "food",
                "description": "Small savory snacks.",
                "image_url": "https://example.test/bites.jpg",
                "recipe": "",
                "available": True,
                "created_at": "2026-07-06T00:00:00Z",
            }
        ]
        self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.post("/party/menu", data={"menu_item_id": "food-1"})

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertIn("Only drinks can be ordered", response.get_data(as_text=True))
        self.assertEqual([], state["drink_orders"])

    def test_bartender_can_complete_order_and_publish_ready_override(self):
        account = self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        account["roles"] = ["regular", "bartender"]
        main.drink_orders = [
            {
                "id": "order-1",
                "user_id": "user-1",
                "username": "Jamie",
                "email": "jamie@example.com",
                "menu_item_id": "drink-1",
                "item_name": "Witch Margarita",
                "item_image_url": "https://example.test/witch.jpg",
                "recipe": "Shake tequila, lime, and syrup with ice.",
                "status": "received",
                "estimated_ready_at": "2026-07-06T00:08:00Z",
                "created_at": main._utc_now_iso(),
                "started_at": "",
                "completed_at": "",
                "completed_seconds": None,
            }
        ]
        self.save_current_state()

        fake_ses = FakeSESClient()
        main.app.config["EMAIL_UPDATES_ENABLED"] = True
        main.create_ses_client = lambda: fake_ses

        with main.app.test_client() as client:
            self.login_regular(client)
            with client.session_transaction() as session:
                session["roles"] = ["regular", "bartender"]
            start_response = client.post(
                "/bartender",
                data={"order_id": "order-1", "status": "in_progress"},
            )
            complete_response = client.post(
                "/bartender",
                data={"order_id": "order-1", "status": "complete"},
            )
            self.login_admin(client)
            display_response = client.get("/api/display-data")

        state = self.redis_state()
        self.assertEqual(200, start_response.status_code)
        self.assertEqual(200, complete_response.status_code)
        self.assertEqual("complete", state["drink_orders"][0]["status"])
        self.assertGreater(state["drink_orders"][0]["completed_seconds"], 0)
        self.assertEqual("drink_ready", state["live_display_override"]["type"])
        self.assertEqual("https://example.test/witch.jpg", state["live_display_override"]["image_url"])
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertEqual(200, display_response.status_code)
        self.assertEqual("drink_ready", display_response.get_json()["override"]["type"])

    def test_bartender_view_requires_bartender_or_admin(self):
        self.add_user_account(username="Jamie", user_id="user-1")
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            regular_response = client.get("/bartender")

        with main.app.test_client() as client:
            self.login_admin(client)
            admin_response = client.get("/bartender")

        self.assertEqual(302, regular_response.status_code)
        self.assertIn("/party/login", regular_response.headers["Location"])
        self.assertEqual(200, admin_response.status_code)

    def test_legacy_attendee_routes_redirect_to_party_paths(self):
        self.save_current_state()

        with main.app.test_client() as client:
            overview_response = client.get("/halloween")
            login_response = client.get("/halloween/login?next=/halloween")
            register_response = client.get("/halloween/register?next=/halloween")
            costume_response = client.get("/costume-signup?success=1")
            karaoke_response = client.get("/karaoke-signup?success=1")
            voting_response = client.get("/costume-voting")

        self.assertEqual(301, overview_response.status_code)
        self.assertEqual("/party", overview_response.headers["Location"])
        self.assertEqual(301, login_response.status_code)
        self.assertIn("/party/login", login_response.headers["Location"])
        self.assertEqual(301, register_response.status_code)
        self.assertIn("/party/register", register_response.headers["Location"])
        self.assertEqual(301, costume_response.status_code)
        self.assertIn("/party/costumes", costume_response.headers["Location"])
        self.assertEqual(301, karaoke_response.status_code)
        self.assertIn("/party/karaoke", karaoke_response.headers["Location"])
        self.assertEqual(301, voting_response.status_code)
        self.assertEqual("/party/costumes/vote", voting_response.headers["Location"])

    def test_regular_user_registration_creates_account_and_signs_in(self):
        self.save_current_state()
        fake_ses = FakeSESClient()
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            self.verify_party_code(client)
            register_response = client.post(
                "/party/register",
                data={
                    "username": "Morgan",
                    "email": "morgan@example.com",
                    "password": "party-password",
                    "confirm_password": "party-password",
                    "next": "/party",
                },
            )
            halloween_response = client.get("/party")

            with client.session_transaction() as session:
                roles = session.get("roles", [])
                user_id = session.get("user_id")

        state = self.redis_state()
        account = state["user_accounts"]["morgan"]
        self.assertEqual(302, register_response.status_code)
        self.assertEqual(200, halloween_response.status_code)
        self.assertEqual("Morgan", account["username"])
        self.assertEqual("morgan@example.com", account["email"])
        self.assertTrue(account["email_updates_acknowledged"])
        self.assertNotEqual("party-password", account["password_hash"])
        self.assertEqual("Morgan", state["registered_users"][user_id])
        self.assertIn("regular", roles)
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertEqual(["morgan@example.com"], fake_ses.sent_messages[0]["Destination"]["ToAddresses"])
        self.assertIn("Welcome", fake_ses.sent_messages[0]["Content"]["Simple"]["Subject"]["Data"])

    def test_password_reset_request_sends_generic_response_and_email_for_existing_account(self):
        self.add_user_account("Morgan", "party-password", "user-1", "morgan@example.com")
        self.save_current_state()
        fake_ses = FakeSESClient()
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            response = client.post(
                "/party/password-reset",
                data={"email": "morgan@example.com"},
            )

        state = self.redis_state()
        token_hashes = list(state["password_reset_tokens"].keys())
        self.assertEqual(200, response.status_code)
        self.assertIn("If that email is registered, we sent a password reset link.", response.get_data(as_text=True))
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertEqual(["morgan@example.com"], fake_ses.sent_messages[0]["Destination"]["ToAddresses"])
        self.assertEqual(1, len(token_hashes))
        self.assertEqual(64, len(token_hashes[0]))
        self.assertEqual("morgan", state["password_reset_tokens"][token_hashes[0]]["normalized_username"])

    def test_password_reset_request_for_unknown_email_does_not_reveal_account_status(self):
        self.add_user_account("Morgan", "party-password", "user-1", "morgan@example.com")
        self.save_current_state()
        fake_ses = FakeSESClient()
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            response = client.post(
                "/party/password-reset",
                data={"email": "unknown@example.com"},
            )

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertIn("If that email is registered, we sent a password reset link.", response.get_data(as_text=True))
        self.assertEqual(0, len(fake_ses.sent_messages))
        self.assertEqual({}, state.get("password_reset_tokens", {}))

    def test_password_reset_updates_password_and_prevents_token_reuse(self):
        self.add_user_account("Morgan", "party-password", "user-1", "morgan@example.com")
        self.save_current_state()
        fake_ses = FakeSESClient()
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            request_response = client.post(
                "/party/password-reset",
                data={"email": "morgan@example.com"},
            )
            token = self.password_reset_token_from_email(fake_ses)
            form_response = client.get(f"/party/password-reset/{token}")
            reset_response = client.post(
                f"/party/password-reset/{token}",
                data={
                    "password": "new-party-password",
                    "confirm_password": "new-party-password",
                },
            )
            reuse_response = client.get(f"/party/password-reset/{token}")
            self.verify_party_code(client)
            old_login = client.post(
                "/party/login",
                data={"username": "Morgan", "password": "party-password"},
            )
            new_login = client.post(
                "/party/login",
                data={"username": "Morgan", "password": "new-party-password"},
            )

        state = self.redis_state()
        token_hash = main.hash_password_reset_token(token)
        account = state["user_accounts"]["morgan"]
        self.assertEqual(200, request_response.status_code)
        self.assertEqual(200, form_response.status_code)
        self.assertIn("Update Password", form_response.get_data(as_text=True))
        self.assertEqual(200, reset_response.status_code)
        self.assertIn("Password updated", reset_response.get_data(as_text=True))
        self.assertIn("invalid or expired", reuse_response.get_data(as_text=True))
        self.assertIn("Incorrect username or password.", old_login.get_data(as_text=True))
        self.assertEqual(302, new_login.status_code)
        self.assertTrue(main.check_password_hash(account["password_hash"], "new-party-password"))
        self.assertTrue(state["password_reset_tokens"][token_hash]["used_at"])

    def test_expired_password_reset_token_is_rejected(self):
        account = self.add_user_account("Morgan", "party-password", "user-1", "morgan@example.com")
        token = "expired-token"
        token_hash = main.hash_password_reset_token(token)
        main.password_reset_tokens[token_hash] = {
            "normalized_username": "morgan",
            "account_id": account["id"],
            "email": account["email"],
            "created_at": "2026-07-01T00:00:00Z",
            "expires_at": "2026-07-01T00:45:00Z",
            "used_at": "",
        }
        self.save_current_state()

        with main.app.test_client() as client:
            response = client.get(f"/party/password-reset/{token}")

        self.assertEqual(200, response.status_code)
        self.assertIn("invalid or expired", response.get_data(as_text=True))

    def test_password_reset_email_failure_still_returns_generic_response(self):
        self.add_user_account("Morgan", "party-password", "user-1", "morgan@example.com")
        self.save_current_state()
        fake_ses = FakeSESClient(failing_recipients={"morgan@example.com"})
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            response = client.post(
                "/party/password-reset",
                data={"email": "morgan@example.com"},
            )

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertIn("If that email is registered, we sent a password reset link.", response.get_data(as_text=True))
        self.assertEqual(0, len(fake_ses.sent_messages))
        self.assertEqual(1, len(state["password_reset_tokens"]))

    def test_logout_clears_current_session(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            halloween_response = client.get("/party")
            logout_response = client.post("/logout")
            protected_response = client.get("/party")

            with client.session_transaction() as session:
                roles = session.get("roles", [])
                username = session.get("username")

        self.assertEqual(200, halloween_response.status_code)
        self.assertIn("Log Out", halloween_response.get_data(as_text=True))
        self.assertEqual(1, halloween_response.get_data(as_text=True).count("Log Out"))
        self.assertIn('action="/logout"', halloween_response.get_data(as_text=True))
        self.assertEqual(302, logout_response.status_code)
        self.assertIn("/party/login", logout_response.headers["Location"])
        self.assertEqual(302, protected_response.status_code)
        self.assertIn("/party/login", protected_response.headers["Location"])
        self.assertNotIn("regular", roles)
        self.assertIsNone(username)

    def test_logout_clears_regular_and_admin_roles_when_both_exist(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            self.login_admin(client)
            admin_response = client.get("/admin")
            logout_response = client.post("/logout")
            halloween_response = client.get("/party")
            admin_redirect = client.get("/admin")

            with client.session_transaction() as session:
                roles = session.get("roles", [])
                username = session.get("username")

        self.assertEqual(200, admin_response.status_code)
        self.assertEqual(1, admin_response.get_data(as_text=True).count("Log Out"))
        self.assertNotIn("Admin Logout", admin_response.get_data(as_text=True))
        self.assertIn('action="/logout"', admin_response.get_data(as_text=True))
        self.assertEqual(302, logout_response.status_code)
        self.assertIn("/party/login", logout_response.headers["Location"])
        self.assertEqual(302, halloween_response.status_code)
        self.assertIn("/party/login", halloween_response.headers["Location"])
        self.assertEqual(302, admin_redirect.status_code)
        self.assertIn("/admin/login", admin_redirect.headers["Location"])
        self.assertNotIn("regular", roles)
        self.assertNotIn("admin", roles)
        self.assertIsNone(username)

    def test_admin_session_grants_display_route_access(self):
        self.save_current_state()

        with main.app.test_client() as client:
            protected_response = client.get("/api/display-data")
            self.login_admin(client)
            display_response = client.get("/api/display-data")
            halloween_response = client.get("/party")

        self.assertEqual(302, protected_response.status_code)
        self.assertIn("/admin/login", protected_response.headers["Location"])
        self.assertEqual(200, display_response.status_code)
        self.assertEqual(302, halloween_response.status_code)
        self.assertIn("/party/login", halloween_response.headers["Location"])

    def test_csrf_rejects_post_without_token_outside_testing_mode(self):
        main.app.config["TESTING"] = False
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.post(
                "/party/costumes",
                data={"name": "Ada", "costume": "Vampire", "contact": ""},
            )

        self.assertEqual(400, response.status_code)
        self.assertIn("form expired", response.get_data(as_text=True))
