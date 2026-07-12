import io
import json
import os
import tempfile
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
        self.original_rsvp_notification_email = main.rsvp_notification_email
        self.original_create_ses_client = main.create_ses_client
        self.original_specialty_extra_orders_are_open = main.specialty_extra_orders_are_open
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
        main.app.config["PARTY_START"] = "2026-01-01T00:00:00-06:00"
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
        main.rsvp_notification_email = self.original_rsvp_notification_email
        main.create_ses_client = self.original_create_ses_client
        main.specialty_extra_orders_are_open = self.original_specialty_extra_orders_are_open
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
        main.live_display_event_override = None
        main.live_display_notice_override = None
        main.landing_page_target = main.DEFAULT_LANDING_PAGE_TARGET
        main.event_experience_mode = main.DEFAULT_EVENT_EXPERIENCE_MODE
        main.party_code_hash = main.generate_password_hash("invite-code")
        main.party_code_hint = ""
        main.rsvp_notification_email = main.DEFAULT_RSVP_NOTIFICATION_EMAIL
        main.display_settings = main.copy.deepcopy(main.DEFAULT_DISPLAY_SETTINGS)
        main.bartender_tip_settings = main.copy.deepcopy(main.DEFAULT_BARTENDER_TIP_SETTINGS)
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
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
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
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": 1,
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
        main.live_display_notice_override = {"type": "drink_ready", "title": "Tonight"}
        main.landing_page_target = "party_login"
        main.event_experience_mode = "party_day"
        main.party_code_hash = main.generate_password_hash("secret-code")
        main.party_code_hint = "On your invite"
        main.rsvp_notification_email = "host@example.com"
        main.party_details = {
            "date": "Saturday, October 31",
            "time": "8:00 PM",
            "location": "The haunted house",
            "map_address": "123 Pumpkin Lane, Denver, CO",
            "overview": "Bring a costume.",
        }
        main.display_settings = {
            "wifi_network": "Upside Down LAN",
            "wifi_password": "friends-dont-lie",
        }
        main.bartender_tip_settings = {
            "enabled": True,
            "display_name": "Casey",
            "note": "Tip the bar if you had fun.",
            "image_url": "https://example.test/tip.png",
            "zelle": "casey@example.com",
            "paypal": "caseypay",
            "venmo": "@casey",
            "cash_app": "$casey",
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
        self.assertEqual("specialty", main.menu_items[0]["drink_type"])
        self.assertTrue(main.menu_items[0]["orderable"])
        self.assertEqual("order-1", main.drink_orders[0]["id"])
        self.assertEqual(360, main.drink_orders[0]["completed_seconds"])
        self.assertEqual("specialty", main.drink_orders[0]["drink_type"])
        self.assertEqual(1, main.drink_orders[0]["specialty_sequence_number"])
        self.assertEqual("Morgan", main.rsvp_signups[0].name)
        self.assertEqual(2, main.rsvp_signups[0].guest_count)
        self.assertEqual("Bringing cider", main.rsvp_signups[0].note)
        self.assertEqual("Parking", main.rsvp_updates[0].title)
        self.assertEqual("Use the west side of the street.", main.rsvp_updates[0].message)
        self.assertEqual({"user-1", "user-2"}, main.submitted_costume_votes)
        self.assertTrue(main.contest_state["contest_started"])
        self.assertTrue(main.contest_state["voting_open"])
        self.assertTrue(main.karaoke_state["party_started"])
        self.assertIsNone(main.live_display_event_override)
        self.assertEqual({"type": "drink_ready", "title": "Tonight"}, main.live_display_notice_override)
        self.assertEqual("party_login", main.landing_page_target)
        self.assertEqual("party_day", main.event_experience_mode)
        self.assertTrue(main.check_password_hash(main.party_code_hash, "secret-code"))
        self.assertEqual("On your invite", main.party_code_hint)
        self.assertEqual("host@example.com", main.rsvp_notification_email)
        self.assertEqual("Saturday, October 31", main.party_details["date"])
        self.assertEqual("8:00 PM", main.party_details["time"])
        self.assertEqual("The haunted house", main.party_details["location"])
        self.assertTrue(main.bartender_tip_settings["enabled"])
        self.assertEqual("https://example.test/tip.png", main.bartender_tip_settings["image_url"])
        self.assertEqual("123 Pumpkin Lane, Denver, CO", main.party_details["map_address"])
        self.assertEqual("Bring a costume.", main.party_details["overview"])
        self.assertEqual("Upside Down LAN", main.display_settings["wifi_network"])
        self.assertEqual("friends-dont-lie", main.display_settings["wifi_password"])
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
            "live_display_event_override": None,
            "live_display_notice_override": None,
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

    def test_pre_party_dashboard_shows_rsvp_details_and_blocks_event_routes(self):
        main.app.config["PARTY_START"] = "2026-10-31T19:00:00-06:00"
        self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        main.party_details = {
            "date": "Saturday, October 31",
            "time": "7:00 PM until late",
            "location": "The haunted house",
            "map_address": "123 Pumpkin Lane, Denver, CO",
            "overview": "RSVP before party night.",
        }
        main.rsvp_updates = [
            main.RSVPUpdate("Parking", "Use the west side of the street.", "2026-07-07T00:00:00Z", "update-1")
        ]
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
        ]
        main.karaoke_signups = [
            main.KaraokeSignup("Grace", "Thriller", "Michael Jackson", "", "karaoke-1"),
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            dashboard_response = client.get("/party")
            menu_response = client.get("/party/menu")
            costume_response = client.get("/party/costumes")
            karaoke_response = client.get("/party/karaoke")

        dashboard_body = dashboard_response.get_data(as_text=True)
        self.assertEqual(200, dashboard_response.status_code)
        self.assertIn("Party Details", dashboard_body)
        self.assertIn("Saturday, October 31", dashboard_body)
        self.assertIn("Directions", dashboard_body)
        self.assertIn("Rideshare Reminder", dashboard_body)
        self.assertIn("Potluck Details", dashboard_body)
        self.assertIn("Later Tonight", dashboard_body)
        self.assertIn("Parking", dashboard_body)
        self.assertNotIn("Tonight's Lineup", dashboard_body)
        self.assertNotIn("Join the Live Party Hub", dashboard_body)
        self.assertNotIn("Costume Contest Signups", dashboard_body)
        self.assertNotIn("Karaoke Signups", dashboard_body)
        self.assertNotIn('href="/party/menu"', dashboard_body)
        self.assertNotIn('href="/party/costumes"', dashboard_body)
        self.assertNotIn('href="/party/karaoke"', dashboard_body)
        self.assertEqual("/party", menu_response.headers["Location"])
        self.assertEqual("/party", costume_response.headers["Location"])
        self.assertEqual("/party", karaoke_response.headers["Location"])

    def test_party_day_dashboard_enables_event_routes_but_voting_stays_admin_gated(self):
        main.app.config["PARTY_START"] = "2026-01-01T19:00:00-06:00"
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
        ]
        main.karaoke_signups = [
            main.KaraokeSignup("Grace", "Thriller", "Michael Jackson", "", "karaoke-1"),
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            dashboard_response = client.get("/party")
            voting_response = client.get("/party/costumes/vote")

        dashboard_body = dashboard_response.get_data(as_text=True)
        self.assertEqual(200, dashboard_response.status_code)
        self.assertIn("Welcome to the Party Portal", dashboard_body)
        self.assertIn("Costume Contest Signups", dashboard_body)
        self.assertIn("Karaoke Signups", dashboard_body)
        self.assertIn('href="/party/menu"', dashboard_body)
        self.assertIn('href="/party/costumes"', dashboard_body)
        self.assertIn('href="/party/karaoke"', dashboard_body)
        self.assertNotIn("Start Voting", dashboard_body)
        self.assertEqual(302, voting_response.status_code)
        self.assertEqual("/party", voting_response.headers["Location"])

    def test_admin_can_start_stop_and_reset_costume_contest(self):
        main.costume_signups = [
            main.CostumeSignup("Ada", "Vampire", "", "costume-1"),
        ]
        main.karaoke_state["party_started"] = True
        main.karaoke_state["current_singer_id"] = "karaoke-1"
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
        self.assertFalse(state_after_start["karaoke_state"]["party_started"])
        self.assertIsNone(state_after_start["karaoke_state"]["current_singer_id"])
        self.assertEqual("contest_start", state_after_start["live_display_event_override"]["type"])
        self.assertEqual(200, stop_response.status_code)
        self.assertFalse(state_after_stop["contest_state"]["contest_started"])
        self.assertFalse(state_after_stop["contest_state"]["voting_open"])
        self.assertIsNone(state_after_stop["live_display_event_override"])

        main.load_state_from_redis()
        main.contest_state["contest_started"] = True
        main.contest_state["voting_open"] = True
        main.contest_state["winner"] = {"id": "costume-1", "name": "Ada"}
        main.contest_state["winner_locked"] = True
        main.costume_ballots = {"user-1": {"costume-1": 10}}
        main.submitted_costume_votes = {"user-1"}
        main.live_display_event_override = {"type": "winner", "title": "Costume Contest Champion"}
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
        self.assertIsNone(state_after_reset["live_display_event_override"])

    def test_admin_can_start_stop_and_reset_karaoke_party(self):
        main.karaoke_signups = [
            main.KaraokeSignup("Grace", "Thriller", "Michael Jackson", "", "karaoke-1"),
        ]
        main.contest_state["contest_started"] = True
        main.contest_state["voting_open"] = True
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
        self.assertFalse(state_after_start["contest_state"]["contest_started"])
        self.assertFalse(state_after_start["contest_state"]["voting_open"])
        self.assertEqual("karaoke_start", state_after_start["live_display_event_override"]["type"])
        self.assertEqual(200, stop_response.status_code)
        self.assertFalse(state_after_stop["karaoke_state"]["party_started"])
        self.assertIsNone(state_after_stop["karaoke_state"]["current_singer_id"])
        self.assertIsNone(state_after_stop["live_display_event_override"])

        main.load_state_from_redis()
        main.karaoke_state["party_started"] = True
        main.karaoke_state["current_singer_id"] = "karaoke-1"
        main.live_display_event_override = {"type": "karaoke_start", "title": "Halloween Karaoke Party"}
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            reset_response = client.post("/admin", data={"action": "reset_karaoke_party"})

        state_after_reset = self.redis_state()
        self.assertEqual(200, reset_response.status_code)
        self.assertFalse(state_after_reset["karaoke_state"]["party_started"])
        self.assertIsNone(state_after_reset["karaoke_state"]["current_singer_id"])
        self.assertEqual("Grace", state_after_reset["karaoke_signups"][0]["name"])
        self.assertIsNone(state_after_reset["live_display_event_override"])

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

    def test_admin_can_update_guest_experience_mode(self):
        main.app.config["PARTY_START"] = "2026-10-31T19:00:00-06:00"
        self.add_user_account()
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "update_event_experience_mode",
                    "event_experience_mode": "party_day",
                },
            )
            self.login_regular(client)
            dashboard_response = client.get("/party")
            menu_response = client.get("/party/menu")

        state = self.redis_state()
        dashboard_body = dashboard_response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Guest experience mode set to Party day.", response.get_data(as_text=True))
        self.assertEqual("party_day", state["event_experience_mode"])
        self.assertIn("Welcome to the Party Portal", dashboard_body)
        self.assertEqual(200, menu_response.status_code)

    def test_admin_can_force_pre_party_guest_experience(self):
        main.app.config["PARTY_START"] = "2026-01-01T19:00:00-06:00"
        main.event_experience_mode = "pre_party"
        self.add_user_account()
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            dashboard_response = client.get("/party")
            menu_response = client.get("/party/menu")

        dashboard_body = dashboard_response.get_data(as_text=True)
        self.assertEqual(200, dashboard_response.status_code)
        self.assertIn("Party Details", dashboard_body)
        self.assertNotIn("Welcome to the Party Portal", dashboard_body)
        self.assertEqual(302, menu_response.status_code)
        self.assertEqual("/party", menu_response.headers["Location"])

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

    def test_login_and_register_forms_are_public_without_party_code_gate(self):
        self.add_user_account()
        self.save_current_state()

        with main.app.test_client() as client:
            login_form = client.get("/party/login")
            register_form = client.get("/party/register")
            login_form = client.get("/party/login?next=/party")

        self.assertEqual(200, login_form.status_code)
        self.assertEqual(200, register_form.status_code)
        self.assertIn("Welcome to the Halloween Hub", login_form.get_data(as_text=True))
        self.assertIn("Your Name", login_form.get_data(as_text=True))
        self.assertIn("Create Your Halloween Account", register_form.get_data(as_text=True))
        self.assertNotIn("Enter the Party Code", login_form.get_data(as_text=True))
        self.assertNotIn("Enter the Party Code", register_form.get_data(as_text=True))
        self.assertNotIn("Overview", login_form.get_data(as_text=True))
        self.assertNotIn("Overview", register_form.get_data(as_text=True))

    def test_rsvp_requires_party_code_on_form_and_creates_independent_rsvp(self):
        main.rsvp_updates = [
            main.RSVPUpdate("Parking", "Use the west side of the street.", "2026-07-07T00:00:00Z", "update-1")
        ]
        self.save_current_state()
        long_note = "A" * 241

        with main.app.test_client() as client:
            rsvp_form = client.get("/rsvp")
            bad_code_response = client.post(
                "/rsvp",
                data={
                    "action": "submit_rsvp",
                    "party_code": "wrong",
                    "username": "Casey",
                    "contact": "casey@example.com",
                    "guest_count": "3",
                    "note": long_note,
                },
            )
            state_after_bad_code = self.redis_state()
            signup_response = client.post(
                "/rsvp",
                data={
                    "action": "submit_rsvp",
                    "party_code": "invite-code",
                    "username": "Casey",
                    "contact": "casey@example.com",
                    "guest_count": "3",
                    "note": long_note,
                },
            )
            confirmation_response = client.get("/rsvp")

            with client.session_transaction() as session:
                roles = session.get("roles", [])
                rsvp_id = session.get("rsvp_id")

        rsvp_form_body = rsvp_form.get_data(as_text=True)
        self.assertIn("Save your RSVP", rsvp_form_body)
        self.assertIn("Party Code", rsvp_form_body)
        self.assertIn('maxlength="5000"', rsvp_form_body)
        self.assertNotIn("Password", rsvp_form_body)
        self.assertIn("Date", rsvp_form_body)
        self.assertIn("Time", rsvp_form_body)
        self.assertIn("Location", rsvp_form_body)
        self.assertIn("Get Directions", rsvp_form_body)
        self.assertIn("Latest Updates", rsvp_form_body)
        self.assertNotIn("<h3>Costume Contest</h3>", rsvp_form_body)
        self.assertNotIn("<h3>Karaoke</h3>", rsvp_form_body)
        self.assertNotIn("site-nav", rsvp_form_body)
        self.assertNotIn("site-nav__toggle", rsvp_form_body)
        self.assertEqual(200, bad_code_response.status_code)
        self.assertIn("That party code did not match", bad_code_response.get_data(as_text=True))
        self.assertEqual([], state_after_bad_code["rsvp_signups"])
        self.assertEqual(302, signup_response.status_code)
        state = self.redis_state()
        self.assertEqual("Casey", state["rsvp_signups"][0]["name"])
        self.assertEqual("casey@example.com", state["rsvp_signups"][0]["contact"])
        self.assertTrue(state["rsvp_signups"][0]["email_updates_acknowledged"])
        self.assertEqual(3, state["rsvp_signups"][0]["guest_count"])
        self.assertEqual(long_note, state["rsvp_signups"][0]["note"])
        self.assertEqual(state["rsvp_signups"][0]["id"], rsvp_id)
        self.assertNotIn("casey", state["user_accounts"])
        self.assertNotIn("regular", roles)
        confirmation_body = confirmation_response.get_data(as_text=True)
        self.assertIn("You're on the RSVP list", confirmation_body)
        self.assertNotIn("Total guest", confirmation_body)
        self.assertNotIn("Karaoke song", confirmation_body)
        self.assertNotIn("site-nav", confirmation_body)
        self.assertNotIn("site-nav__toggle", confirmation_body)

    def test_rsvp_page_hides_site_navigation_for_signed_in_party_users(self):
        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.get("/rsvp")

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Save your RSVP", body)
        self.assertNotIn("site-nav", body)
        self.assertNotIn("site-nav__toggle", body)
        self.assertNotIn("Overview", body)
        self.assertNotIn("Log Out", body)

    def test_rsvp_sends_confirmation_email_with_calendar_links(self):
        main.app.config["PARTY_START"] = "2026-10-31T19:00:00-06:00"
        main.party_details = {
            "date": "Saturday, October 31",
            "time": "7:00 PM until late",
            "location": "The haunted house",
            "map_address": "123 Pumpkin Lane, Denver, CO",
            "overview": "Costumes encouraged.",
        }
        self.save_current_state()
        fake_ses = FakeSESClient()
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            response = client.post(
                "/rsvp",
                data={
                    "action": "submit_rsvp",
                    "party_code": "invite-code",
                    "username": "Casey",
                    "contact": "casey@example.com",
                    "guest_count": "3",
                    "note": "Arriving after 8",
                },
            )
            rsvp_id = self.redis_state()["rsvp_signups"][0]["id"]
            calendar_response = client.get(f"/rsvp/calendar/{rsvp_id}")

        self.assertEqual(302, response.status_code)
        self.assertEqual(2, len(fake_ses.sent_messages))
        sent_email = fake_ses.sent_messages[0]
        notification_email = fake_ses.sent_messages[1]
        text_body = sent_email["Content"]["Simple"]["Body"]["Text"]["Data"]
        html_body = sent_email["Content"]["Simple"]["Body"]["Html"]["Data"]
        self.assertEqual(["casey@example.com"], sent_email["Destination"]["ToAddresses"])
        self.assertEqual(["tgio1129@gmail.com"], notification_email["Destination"]["ToAddresses"])
        self.assertIn("RSVP confirmed", sent_email["Content"]["Simple"]["Subject"]["Data"])
        self.assertIn("New RSVP", notification_email["Content"]["Simple"]["Subject"]["Data"])
        self.assertIn("Guests: 3", text_body)
        self.assertIn("Note: Arriving after 8", text_body)
        self.assertIn(f"/rsvp/calendar/{rsvp_id}", text_body)
        self.assertIn("calendar.google.com", text_body)
        self.assertIn("Download calendar file", html_body)
        self.assertEqual(200, calendar_response.status_code)
        self.assertIn("text/calendar", calendar_response.content_type)
        calendar_body = calendar_response.get_data(as_text=True)
        self.assertIn("BEGIN:VCALENDAR", calendar_body)
        self.assertIn("SUMMARY:Qiana and Tony's 3rd Annual Halloween Party", calendar_body)
        self.assertIn("DTSTART:20261101T010000Z", calendar_body)
        self.assertIn("LOCATION:123 Pumpkin Lane\\, Denver\\, CO", calendar_body)

    def test_rsvp_confirmation_email_failure_does_not_block_rsvp(self):
        self.save_current_state()
        fake_ses = FakeSESClient(failing_recipients={"casey@example.com"})
        main.create_ses_client = lambda: fake_ses
        main.app.config["EMAIL_UPDATES_ENABLED"] = True

        with main.app.test_client() as client:
            response = client.post(
                "/rsvp",
                data={
                    "action": "submit_rsvp",
                    "party_code": "invite-code",
                    "username": "Casey",
                    "contact": "casey@example.com",
                    "guest_count": "2",
                    "note": "",
                },
            )

        state = self.redis_state()
        self.assertEqual(302, response.status_code)
        self.assertEqual("Casey", state["rsvp_signups"][0]["name"])
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertEqual(["tgio1129@gmail.com"], fake_ses.sent_messages[0]["Destination"]["ToAddresses"])

    def test_unknown_rsvp_calendar_returns_404(self):
        self.save_current_state()

        with main.app.test_client() as client:
            response = client.get("/rsvp/calendar/not-found")

        self.assertEqual(404, response.status_code)

    def test_rsvp_details_are_public_across_browser_sessions(self):
        self.save_current_state()

        with main.app.test_client() as first_client:
            first_response = first_client.get("/rsvp")

        with main.app.test_client() as second_client:
            second_response = second_client.get("/rsvp")

        first_body = first_response.get_data(as_text=True)
        second_body = second_response.get_data(as_text=True)
        self.assertIn("Save your RSVP", first_body)
        self.assertIn("Date", first_body)
        self.assertIn("Latest Updates", first_body)
        self.assertIn("Save your RSVP", second_body)
        self.assertIn("Date", second_body)
        self.assertIn("Latest Updates", second_body)
        self.assertNotIn("Unlock RSVP", first_body)
        self.assertNotIn("Unlock RSVP", second_body)

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

    def test_admin_can_update_rsvp_notification_email(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "update_rsvp_notification_email",
                    "rsvp_notification_email": "Host@Example.COM",
                },
            )
            invalid_response = client.post(
                "/admin",
                data={
                    "action": "update_rsvp_notification_email",
                    "rsvp_notification_email": "not-an-email",
                },
            )
            disabled_response = client.post(
                "/admin",
                data={
                    "action": "update_rsvp_notification_email",
                    "rsvp_notification_email": "",
                },
            )

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertIn("RSVP notifications will be sent to host@example.com", response.get_data(as_text=True))
        self.assertIn("Enter a valid RSVP notification email", invalid_response.get_data(as_text=True))
        self.assertEqual(200, disabled_response.status_code)
        self.assertEqual("", state["rsvp_notification_email"])
        main.load_state_from_redis()
        self.assertEqual("", main.rsvp_notification_email)

    def test_admin_can_update_live_display_wifi_details(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post(
                "/admin",
                data={
                    "action": "update_display_wifi",
                    "display_wifi_network": "Upside Down LAN",
                    "display_wifi_password": "friends-dont-lie",
                },
            )
            display_response = client.get("/api/display-data")

        state = self.redis_state()
        display_payload = display_response.get_json()
        first_entry = display_payload["entries"][0]
        self.assertEqual(200, response.status_code)
        self.assertIn("Live display WiFi settings updated.", response.get_data(as_text=True))
        self.assertEqual("Upside Down LAN", state["display_settings"]["wifi_network"])
        self.assertEqual("friends-dont-lie", state["display_settings"]["wifi_password"])
        self.assertEqual("Upside Down LAN", first_entry["cta_details"]["wifi_network"])
        self.assertEqual("friends-dont-lie", first_entry["cta_details"]["wifi_password"])
        self.assertEqual("https://tnq-halloween.com", first_entry["cta_details"]["site_url"])
        self.assertIn("browse to https://tnq-halloween.com", first_entry["secondary"])

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

    def test_pre_party_display_rotates_party_night_cards_for_staging(self):
        main.app.config["PARTY_START"] = "2026-10-31T19:00:00-06:00"
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

        self.assertIn("Signup Portal", {entry["category"] for entry in entries})
        self.assertIn("Costume Contest", {entry["category"] for entry in entries})
        self.assertIn("Karaoke Stage", {entry["category"] for entry in entries})
        self.assertIn("Bar Queue", {entry["category"] for entry in entries})
        self.assertIn("Live Updates", {entry["category"] for entry in entries})
        self.assertIn("Dressed as Vampire", serialized_entries)
        self.assertIn("Thriller", serialized_entries)
        self.assertNotIn("RSVP before party night", serialized_entries)
        self.assertNotIn("Parking", serialized_entries)

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
        welcome_body = fake_ses.sent_messages[0]["Content"]["Simple"]["Body"]
        self.assertNotIn("/party/menu", welcome_body["Text"]["Data"])
        self.assertNotIn("/party/costumes", welcome_body["Text"]["Data"])
        self.assertNotIn("/party/karaoke", welcome_body["Text"]["Data"])
        self.assertNotIn("/party/menu", welcome_body["Html"]["Data"])
        self.assertNotIn("/party/costumes", welcome_body["Html"]["Data"])
        self.assertNotIn("/party/karaoke", welcome_body["Html"]["Data"])
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

    def test_specialty_drink_limit_blocks_fourth_order_before_11(self):
        main.specialty_extra_orders_are_open = lambda now=None: False
        main.menu_items = [
            {
                "id": "drink-1",
                "name": "Witch Margarita",
                "category": "drink",
                "description": "Lime, smoke, and salt.",
                "image_url": "",
                "recipe": "",
                "available": True,
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "created_at": "2026-07-06T00:00:00Z",
            }
        ]
        self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        main.drink_orders = [
            {
                "id": f"order-{index}",
                "user_id": "user-1",
                "username": "Jamie",
                "email": "jamie@example.com",
                "menu_item_id": "drink-1",
                "item_name": "Witch Margarita",
                "item_image_url": "",
                "recipe": "",
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": index,
                "status": "complete",
                "estimated_ready_at": "",
                "created_at": f"2026-07-06T00:0{index}:00Z",
                "started_at": "",
                "completed_at": f"2026-07-06T00:1{index}:00Z",
                "completed_seconds": 60,
            }
            for index in range(1, 4)
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.post("/party/menu", data={"menu_item_id": "drink-1"})

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertIn("More specialty requests open after 11:00 PM", response.get_data(as_text=True))
        self.assertEqual(3, len(state["drink_orders"]))

    def test_standard_drinks_do_not_count_against_specialty_limit_and_after_11_allows_extra_specialty(self):
        main.specialty_extra_orders_are_open = lambda now=None: True
        main.menu_items = [
            {
                "id": "specialty-1",
                "name": "Witch Margarita",
                "category": "drink",
                "description": "",
                "image_url": "",
                "recipe": "",
                "available": True,
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "created_at": "2026-07-06T00:00:00Z",
            },
            {
                "id": "standard-1",
                "name": "Sparkling Water",
                "category": "drink",
                "description": "",
                "image_url": "",
                "recipe": "",
                "available": True,
                "drink_type": "standard",
                "beverage_type": "non_alcoholic",
                "orderable": True,
                "created_at": "2026-07-06T00:00:00Z",
            },
        ]
        self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        main.drink_orders = [
            {
                "id": f"specialty-order-{index}",
                "user_id": "user-1",
                "username": "Jamie",
                "email": "jamie@example.com",
                "menu_item_id": "specialty-1",
                "item_name": "Witch Margarita",
                "item_image_url": "",
                "recipe": "",
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": index,
                "status": "complete",
                "estimated_ready_at": "",
                "created_at": f"2026-07-06T00:0{index}:00Z",
                "started_at": "",
                "completed_at": f"2026-07-06T00:1{index}:00Z",
                "completed_seconds": 60,
            }
            for index in range(1, 4)
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            standard_response = client.post("/party/menu", data={"menu_item_id": "standard-1"})
            specialty_response = client.post("/party/menu", data={"menu_item_id": "specialty-1"})

        state = self.redis_state()
        self.assertEqual(302, standard_response.status_code)
        self.assertEqual(302, specialty_response.status_code)
        self.assertEqual(5, len(state["drink_orders"]))
        self.assertEqual("standard", state["drink_orders"][3]["drink_type"])
        self.assertEqual(0, state["drink_orders"][3]["specialty_sequence_number"])
        self.assertEqual(4, state["drink_orders"][4]["specialty_sequence_number"])
        self.assertTrue(state["drink_orders"][4]["specialty_extra_request"])
        self.assertTrue(state["drink_orders"][4]["specialty_extra_window_open"])

    def test_drink_history_is_user_scoped_and_reorder_creates_unique_order(self):
        main.menu_items = [
            {
                "id": "drink-1",
                "name": "Witch Margarita",
                "category": "drink",
                "description": "",
                "image_url": "https://example.test/witch.jpg",
                "recipe": "",
                "available": True,
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "created_at": "2026-07-06T00:00:00Z",
            }
        ]
        self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        self.add_user_account(username="Morgan", user_id="user-2", email="morgan@example.com")
        main.drink_orders = [
            {
                "id": "order-1",
                "user_id": "user-1",
                "username": "Jamie",
                "email": "jamie@example.com",
                "menu_item_id": "drink-1",
                "item_name": "Witch Margarita",
                "item_image_url": "https://example.test/witch.jpg",
                "recipe": "",
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": 1,
                "status": "complete",
                "estimated_ready_at": "",
                "created_at": "2026-07-06T00:00:00Z",
                "started_at": "",
                "completed_at": "2026-07-06T00:05:00Z",
                "completed_seconds": 300,
            },
            {
                "id": "order-2",
                "user_id": "user-2",
                "username": "Morgan",
                "email": "morgan@example.com",
                "menu_item_id": "drink-1",
                "item_name": "Witch Margarita",
                "item_image_url": "https://example.test/witch.jpg",
                "recipe": "",
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": 1,
                "status": "complete",
                "estimated_ready_at": "",
                "created_at": "2026-07-06T00:00:00Z",
                "started_at": "",
                "completed_at": "2026-07-06T00:05:00Z",
                "completed_seconds": 300,
            },
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            history_response = client.get("/party/drink-history")
            reorder_response = client.post("/party/drink-history", data={"order_id": "order-1"})

        state = self.redis_state()
        history_html = history_response.get_data(as_text=True)
        self.assertEqual(200, history_response.status_code)
        self.assertIn("Jamie", history_html)
        self.assertNotIn("Morgan", history_html)
        self.assertEqual(302, reorder_response.status_code)
        self.assertEqual(3, len(state["drink_orders"]))
        self.assertNotEqual("order-1", state["drink_orders"][2]["id"])
        self.assertEqual("user-1", state["drink_orders"][2]["user_id"])
        self.assertEqual(2, state["drink_orders"][2]["specialty_sequence_number"])

    def test_admin_tip_settings_rotate_on_party_overview(self):
        self.add_user_account(username="Jamie", user_id="user-1")
        main.drink_orders = [
            {
                "id": "order-1",
                "user_id": "user-1",
                "username": "Jamie",
                "email": "jamie@example.com",
                "menu_item_id": "drink-1",
                "item_name": "Witch Margarita",
                "item_image_url": "",
                "recipe": "",
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": 1,
                "status": "complete",
                "estimated_ready_at": "",
                "created_at": "2026-07-06T00:00:00Z",
                "started_at": "",
                "completed_at": "2026-07-06T00:05:00Z",
                "completed_seconds": 300,
            }
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            admin_response = client.post(
                "/admin",
                data={
                    "action": "update_bartender_tip_settings",
                    "tip_enabled": "yes",
                    "tip_display_name": "Casey",
                    "tip_note": "Thanks for keeping the bar moving.",
                    "tip_image_url": "https://example.test/tip.png",
                    "tip_venmo": "@casey",
                },
            )
            self.login_regular(client)
            overview_response = client.get("/party")
            history_response = client.get("/party/drink-history")
            tip_response = client.get("/party/bartender-tip")

        state = self.redis_state()
        overview_html = overview_response.get_data(as_text=True)
        history_html = history_response.get_data(as_text=True)
        tip_html = tip_response.get_data(as_text=True)
        self.assertEqual(200, admin_response.status_code)
        self.assertTrue(state["bartender_tip_settings"]["enabled"])
        self.assertIn("Tip Casey", overview_html)
        self.assertIn("https://example.test/tip.png", overview_html)
        self.assertIn("@casey", overview_html)
        self.assertIn("Tip Bartender", history_html)
        self.assertIn("/party/bartender-tip", history_html)
        self.assertIn("Bartender payment QR code", tip_html)
        self.assertIn("@casey", tip_html)

    def test_admin_can_upload_bartender_tip_qr_image(self):
        original_upload_dir = main.app.config["BARTENDER_TIP_UPLOAD_DIR"]
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"qr-code-bytes"

        with tempfile.TemporaryDirectory() as upload_dir:
            main.app.config["BARTENDER_TIP_UPLOAD_DIR"] = upload_dir
            try:
                with main.app.test_client() as client:
                    self.login_admin(client)
                    response = client.post(
                        "/admin",
                        data={
                            "action": "update_bartender_tip_settings",
                            "tip_enabled": "yes",
                            "tip_display_name": "Casey",
                            "tip_note": "Thanks for keeping the bar moving.",
                            "tip_image_url": "",
                            "tip_image_upload": (io.BytesIO(png_bytes), "casey-qr.png"),
                            "tip_venmo": "@casey",
                        },
                        content_type="multipart/form-data",
                    )
            finally:
                main.app.config["BARTENDER_TIP_UPLOAD_DIR"] = original_upload_dir

            state = self.redis_state()
            image_url = state["bartender_tip_settings"]["image_url"]
            self.assertEqual(200, response.status_code)
            self.assertTrue(state["bartender_tip_settings"]["enabled"])
            self.assertTrue(image_url.startswith("/static/uploads/bartender-tips/bartender-tip-"))
            self.assertTrue(image_url.endswith(".png"))
            self.assertTrue(os.path.exists(os.path.join(upload_dir, os.path.basename(image_url))))

    def test_admin_rejects_invalid_bartender_tip_qr_upload(self):
        original_upload_dir = main.app.config["BARTENDER_TIP_UPLOAD_DIR"]

        with tempfile.TemporaryDirectory() as upload_dir:
            main.app.config["BARTENDER_TIP_UPLOAD_DIR"] = upload_dir
            try:
                with main.app.test_client() as client:
                    self.login_admin(client)
                    response = client.post(
                        "/admin",
                        data={
                            "action": "update_bartender_tip_settings",
                            "tip_enabled": "yes",
                            "tip_display_name": "Casey",
                            "tip_note": "Thanks for keeping the bar moving.",
                            "tip_image_url": "",
                            "tip_image_upload": (io.BytesIO(b"not really an image"), "casey-qr.png"),
                        },
                        content_type="multipart/form-data",
                    )
            finally:
                main.app.config["BARTENDER_TIP_UPLOAD_DIR"] = original_upload_dir

            html = response.get_data(as_text=True)
            self.assertEqual(200, response.status_code)
            self.assertIn("does not look like a valid image file", html)
            self.assertEqual([], os.listdir(upload_dir))

    def test_dashboard_ready_drink_notifications_expire_but_history_retains_orders(self):
        self.add_user_account(username="Jamie", user_id="user-1")
        old_completed_at = (
            main.datetime.now(main.timezone.utc) - main.timedelta(minutes=6)
        ).isoformat().replace("+00:00", "Z")
        main.drink_orders = [
            {
                "id": "old-ready-order",
                "user_id": "user-1",
                "username": "Jamie",
                "email": "jamie@example.com",
                "menu_item_id": "drink-1",
                "item_name": "Witch Margarita",
                "item_image_url": "",
                "recipe": "",
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": 1,
                "status": "complete",
                "estimated_ready_at": "",
                "created_at": "2026-07-06T00:00:00Z",
                "started_at": "",
                "completed_at": old_completed_at,
                "completed_seconds": 300,
            }
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            overview_response = client.get("/party")
            history_response = client.get("/party/drink-history")

        self.assertEqual(200, overview_response.status_code)
        self.assertEqual(200, history_response.status_code)
        self.assertNotIn("Your Drink Is Ready", overview_response.get_data(as_text=True))
        self.assertIn("old-ready-order", history_response.get_data(as_text=True))

    def test_bartender_queue_prioritizes_included_orders_before_extra_specialty_requests(self):
        account = self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        account["roles"] = ["regular", "bartender"]
        main.drink_orders = [
            {
                "id": "extra-order",
                "user_id": "user-1",
                "username": "Jamie",
                "email": "jamie@example.com",
                "menu_item_id": "drink-1",
                "item_name": "Fourth Witch Margarita",
                "item_image_url": "",
                "recipe": "",
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": 4,
                "specialty_extra_request": True,
                "specialty_extra_window_open": True,
                "status": "received",
                "estimated_ready_at": "",
                "created_at": "2026-07-06T00:01:00Z",
                "started_at": "",
                "completed_at": "",
                "completed_seconds": None,
            },
            {
                "id": "included-order",
                "user_id": "user-2",
                "username": "Morgan",
                "email": "morgan@example.com",
                "menu_item_id": "drink-1",
                "item_name": "First Witch Margarita",
                "item_image_url": "",
                "recipe": "",
                "drink_type": "specialty",
                "beverage_type": "alcoholic",
                "orderable": True,
                "specialty_sequence_number": 1,
                "specialty_extra_request": False,
                "specialty_extra_window_open": True,
                "status": "received",
                "estimated_ready_at": "",
                "created_at": "2026-07-06T00:02:00Z",
                "started_at": "",
                "completed_at": "",
                "completed_seconds": None,
            },
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            with client.session_transaction() as session:
                session["roles"] = ["regular", "bartender"]
            response = client.get("/bartender")

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertLess(body.index("First Witch Margarita"), body.index("Fourth Witch Margarita"))
        self.assertIn("After-11 PM 4+ specialty request", body)
        self.assertIn("Included specialty order 1 of 3", body)

    def test_bartender_queue_api_reflects_new_drink_orders(self):
        main.menu_items = [
            {
                "id": "drink-1",
                "name": "Witch Margarita",
                "category": "drink",
                "description": "Lime, smoke, and salt.",
                "image_url": "",
                "recipe": "Shake tequila, lime, and syrup with ice.",
                "available": True,
                "orderable": True,
                "created_at": "2026-07-06T00:00:00Z",
            }
        ]
        account = self.add_user_account(username="Jamie", user_id="user-1", email="jamie@example.com")
        account["roles"] = ["regular", "bartender"]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            with client.session_transaction() as session:
                session["roles"] = ["regular", "bartender"]
            empty_response = client.get("/api/bartender-queue")
            order_response = client.post("/party/menu", data={"menu_item_id": "drink-1"})
            queue_response = client.get("/api/bartender-queue")

        empty_payload = empty_response.get_json()
        queue_payload = queue_response.get_json()
        self.assertEqual(200, empty_response.status_code)
        self.assertEqual(302, order_response.status_code)
        self.assertEqual(200, queue_response.status_code)
        self.assertNotEqual(empty_payload["queue_version"], queue_payload["queue_version"])
        self.assertEqual(1, queue_payload["active_count"])
        self.assertIn("Witch Margarita", queue_payload["html"])
        self.assertIn("For Jamie", queue_payload["html"])

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
        main.live_display_event_override = {"type": "contest_start", "title": "Contest Is Live"}
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
        self.assertEqual("drink_ready", state["live_display_notice_override"]["type"])
        self.assertEqual("https://example.test/witch.jpg", state["live_display_notice_override"]["image_url"])
        self.assertEqual("contest_start", state["live_display_event_override"]["type"])
        self.assertEqual(1, len(fake_ses.sent_messages))
        self.assertEqual(200, display_response.status_code)
        display_payload = display_response.get_json()
        self.assertEqual("contest_start", display_payload["event_override"]["type"])
        self.assertEqual("drink_ready", display_payload["notice_override"]["type"])

    def test_expired_drink_notice_clears_without_clearing_event_override(self):
        main.live_display_event_override = {"type": "karaoke_start", "title": "Halloween Karaoke Party"}
        main.live_display_notice_override = {
            "type": "drink_ready",
            "title": "Drink Ready",
            "expires_at": "2000-01-01T00:00:00Z",
        }
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.get("/api/display-data")

        state = self.redis_state()
        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertIsNone(state["live_display_notice_override"])
        self.assertEqual("karaoke_start", state["live_display_event_override"]["type"])
        self.assertIsNone(payload["notice_override"])
        self.assertEqual("karaoke_start", payload["event_override"]["type"])

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
