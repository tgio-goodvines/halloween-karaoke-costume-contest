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


class RedisStateTests(unittest.TestCase):
    def setUp(self):
        self.fake_redis = FakeRedis()
        self.original_redis_client = main.redis_client
        self.original_redis_available = main.redis_state_available
        self.original_config = main.REDIS_CONFIG
        self.original_testing = main.app.config["TESTING"]
        self.original_admin_password = main.app.config["ADMIN_PASSWORD"]
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
        self.reset_state()

    def tearDown(self):
        main.redis_client = self.original_redis_client
        main.redis_state_available = self.original_redis_available
        main.REDIS_CONFIG = self.original_config
        main.app.config["TESTING"] = self.original_testing
        main.app.config["ADMIN_PASSWORD"] = self.original_admin_password
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

    def add_user_account(self, username="Jamie", password="party-password", user_id="user-1"):
        account = main.create_user_account(username, password)
        account["id"] = user_id
        main.user_accounts[main.normalize_username(username)] = account
        return account

    def redis_state(self):
        return json.loads(self.fake_redis.store[main.redis_key("state")])

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
                "password_hash": main.generate_password_hash("party-password"),
                "created_at": "2026-07-06T00:00:00Z",
            }
        }
        main.submitted_costume_votes = {"user-1", "user-2"}
        main.contest_state["voting_open"] = True
        main.karaoke_state["party_started"] = True
        main.live_display_override = {"type": "notice", "title": "Tonight"}
        main.landing_page_target = "party_login"
        main.party_code_hash = main.generate_password_hash("secret-code")
        main.party_code_hint = "On your invite"
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
        self.assertTrue(main.check_password_hash(main.user_accounts["ada"]["password_hash"], "party-password"))
        self.assertEqual({"user-1", "user-2"}, main.submitted_costume_votes)
        self.assertTrue(main.contest_state["voting_open"])
        self.assertTrue(main.karaoke_state["party_started"])
        self.assertEqual({"type": "notice", "title": "Tonight"}, main.live_display_override)
        self.assertEqual("party_login", main.landing_page_target)
        self.assertTrue(main.check_password_hash(main.party_code_hash, "secret-code"))
        self.assertEqual("On your invite", main.party_code_hint)
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

    def test_rsvp_requires_party_code_and_creates_account_after_unlock(self):
        self.save_current_state()

        with main.app.test_client() as client:
            locked_rsvp = client.get("/rsvp")
            unlock_response = client.post(
                "/rsvp",
                data={"party_code": "invite-code", "next": "/party"},
            )
            rsvp_form = client.get("/rsvp?next=/party")
            signup_response = client.post(
                "/rsvp",
                data={
                    "username": "Casey",
                    "password": "party-password",
                    "confirm_password": "party-password",
                    "next": "/party",
                },
            )

            with client.session_transaction() as session:
                roles = session.get("roles", [])
                user_id = session.get("user_id")

        state = self.redis_state()
        self.assertEqual(200, locked_rsvp.status_code)
        self.assertIn("Unlock RSVP", locked_rsvp.get_data(as_text=True))
        self.assertEqual(302, unlock_response.status_code)
        self.assertIn("Save your RSVP", rsvp_form.get_data(as_text=True))
        self.assertEqual(302, signup_response.status_code)
        self.assertEqual("Casey", state["user_accounts"]["casey"]["username"])
        self.assertEqual("Casey", state["registered_users"][user_id])
        self.assertIn("regular", roles)

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

        with main.app.test_client() as client:
            self.verify_party_code(client)
            register_response = client.post(
                "/party/register",
                data={
                    "username": "Morgan",
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
        self.assertNotEqual("party-password", account["password_hash"])
        self.assertEqual("Morgan", state["registered_users"][user_id])
        self.assertIn("regular", roles)

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
