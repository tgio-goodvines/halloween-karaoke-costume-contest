import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import redis

import main
import youtube_karaoke


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

    def incr(self, key):
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    def expire(self, key, ttl):
        if key in self.store:
            self.ttls[key] = ttl
            return True
        return False

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


class FakeYouTubeService:
    def __init__(self):
        self.video_id = "abc123DEF45"
        self.search_calls = []
        self.get_video_calls = []
        self.playlist_items = []
        self.insert_calls = []
        self.move_calls = []
        self.delete_calls = []
        self.fail_insert = None
        self.fail_delete_ids = {}
        self.channel = {"channel_id": "channel-1", "channel_title": "Halloween Host"}
        self.playlists = [
            {"playlist_id": "playlist-1", "title": "Halloween Karaoke 2026", "privacy": "private"}
        ]

    def video(self, video_id=None, **updates):
        selected_id = video_id or self.video_id
        return {
            "video_id": selected_id,
            "title": "Thriller Karaoke",
            "channel_id": "channel-sing",
            "channel_title": "Sing King",
            "thumbnail_url": "https://i.ytimg.com/vi/abc123DEF45/hqdefault.jpg",
            "duration_seconds": 358,
            "privacy_status": "public",
            "upload_status": "processed",
            "embeddable": True,
            "age_restricted": False,
            "region_allowed": True,
            "available": True,
            "last_verified_at": "2026-07-30T00:00:00Z",
            "watch_url": f"https://www.youtube.com/watch?v={selected_id}",
            **updates,
        }

    def search_videos(self, query, *, page_token="", limit=8):
        self.search_calls.append((query, page_token, limit))
        return {
            "items": [self.video()],
            "next_page_token": "next-token",
            "previous_page_token": "",
        }

    def get_videos(self, video_ids, *, client=None):
        self.get_video_calls.append(list(video_ids))
        return [self.video(video_ids[0])] if video_ids else []

    def connection_status(self):
        return dict(self.channel)

    def list_owned_playlists(self, *, page_token="", limit=25):
        return {"items": list(self.playlists), "next_page_token": ""}

    def create_playlist(self, title, *, privacy="private"):
        playlist = {"playlist_id": "playlist-created", "title": title, "privacy": privacy}
        self.playlists.append(playlist)
        return playlist

    def list_playlist_items(self, playlist_id):
        return [dict(item) for item in self.playlist_items]

    def insert_playlist_item(self, playlist_id, video_id, *, position, note):
        self.insert_calls.append((playlist_id, video_id, position, note))
        if self.fail_insert:
            raise self.fail_insert
        item = {
            "playlist_item_id": f"playlist-item-{len(self.playlist_items) + 1}",
            "video_id": video_id,
            "position": position,
            "note": note,
        }
        self.playlist_items.insert(position, item)
        return dict(item)

    def move_playlist_item(self, playlist_item_id, playlist_id, video_id, *, position, note):
        self.move_calls.append((playlist_item_id, playlist_id, video_id, position, note))
        item = next(entry for entry in self.playlist_items if entry["playlist_item_id"] == playlist_item_id)
        self.playlist_items.remove(item)
        item["position"] = position
        item["note"] = note
        self.playlist_items.insert(position, item)
        for index, entry in enumerate(self.playlist_items):
            entry["position"] = index
        return dict(item)

    def delete_playlist_item(self, playlist_item_id):
        self.delete_calls.append(playlist_item_id)
        failure = self.fail_delete_ids.get(playlist_item_id)
        if failure:
            raise failure
        self.playlist_items = [
            item for item in self.playlist_items if item["playlist_item_id"] != playlist_item_id
        ]

    def revoke_credentials(self):
        return None


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
        self.original_youtube_service = main.youtube_service
        self.original_youtube_config = {
            key: main.app.config[key]
            for key in (
                "YOUTUBE_KARAOKE_ENABLED",
                "YOUTUBE_API_KEY",
                "YOUTUBE_CLIENT_ID",
                "YOUTUBE_CLIENT_SECRET",
                "YOUTUBE_REFRESH_TOKEN",
                "YOUTUBE_REGION_CODE",
                "YOUTUBE_SEARCH_DAILY_BUDGET",
                "YOUTUBE_SEARCH_ACCOUNT_LIMIT",
            )
        }

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
        main.app.config["YOUTUBE_KARAOKE_ENABLED"] = False
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
        main.youtube_service = self.original_youtube_service
        for key, value in self.original_youtube_config.items():
            main.app.config[key] = value
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
        main.dj_playlist = []
        main.dj_song_requests = []
        main.dj_state = main.copy.deepcopy(main.DEFAULT_DJ_STATE)
        main.rsvp_signups = []
        main.rsvp_updates = []
        main.submitted_costume_votes = set()
        main.live_display_event_override = None
        main.live_display_notice_override = None
        main.live_display_notice_queue = []
        main.landing_page_target = main.DEFAULT_LANDING_PAGE_TARGET
        main.event_experience_mode = main.DEFAULT_EVENT_EXPERIENCE_MODE
        main.party_code_hash = main.generate_password_hash("invite-code")
        main.party_code_hint = ""
        main.rsvp_notification_email = main.DEFAULT_RSVP_NOTIFICATION_EMAIL
        main.display_settings = main.copy.deepcopy(main.DEFAULT_DISPLAY_SETTINGS)
        main.display_config = main.copy.deepcopy(main.DEFAULT_DISPLAY_CONFIG)
        main.display_runtime = main.copy.deepcopy(main.DEFAULT_DISPLAY_RUNTIME)
        main.display_custom_cards = []
        main.bartender_tip_settings = main.copy.deepcopy(main.DEFAULT_BARTENDER_TIP_SETTINGS)
        main.display_update_version = 0
        main.contest_state.clear()
        main.contest_state.update(main.copy.deepcopy(main.DEFAULT_CONTEST_STATE))
        main.karaoke_state.clear()
        main.karaoke_state.update(main.copy.deepcopy(main.DEFAULT_KARAOKE_STATE))
        main.youtube_karaoke = main.copy.deepcopy(main.DEFAULT_YOUTUBE_KARAOKE_STATE)
        main.games_state = main.copy.deepcopy(main.DEFAULT_GAMES_STATE)
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

    def enable_youtube_karaoke(self):
        fake_youtube = FakeYouTubeService()
        main.youtube_service = lambda: fake_youtube
        main.app.config["YOUTUBE_KARAOKE_ENABLED"] = True
        main.app.config["YOUTUBE_API_KEY"] = "test-api-key"
        main.app.config["YOUTUBE_CLIENT_ID"] = "test-client-id"
        main.app.config["YOUTUBE_CLIENT_SECRET"] = "test-client-secret"
        main.app.config["YOUTUBE_REFRESH_TOKEN"] = "test-refresh-token"
        main.youtube_karaoke.update(
            {
                "connection_status": "connected",
                "channel_id": fake_youtube.channel["channel_id"],
                "channel_title": fake_youtube.channel["channel_title"],
                "playlist_id": "playlist-1",
                "playlist_title": "Halloween Karaoke 2026",
                "playlist_privacy": "private",
            }
        )
        self.save_current_state()
        return fake_youtube

    def submit_youtube_karaoke_request(self, client, *, video_id="abc123DEF45"):
        return client.post(
            "/party/karaoke",
            data={
                "name": "Jamie",
                "song_title": "Thriller",
                "artist": "Michael Jackson",
                "youtube_video_id": video_id,
                "youtube_link": f"https://www.youtube.com/watch?v={video_id}",
            },
        )

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
        main.dj_playlist = [
            {
                "id": "dj-1",
                "apple_music_id": "203709340",
                "title": "Thriller",
                "artist": "Michael Jackson",
                "album": "Thriller",
                "artwork_url": "https://example.test/thriller.jpg",
                "duration_ms": 357000,
                "explicit": False,
                "enabled": True,
                "created_at": "2026-07-06T00:00:00Z",
            }
        ]
        main.dj_state["desired"] = {
            "playback_status": "playing",
            "song_id": "dj-1",
            "queue_order": ["dj-1"],
            "shuffle_enabled": False,
        }
        main.dj_state["receiver"].update(
            {
                "id": "tv-1",
                "status": "ready",
                "authorization_status": "authorized",
                "audio_enabled": True,
                "playback_status": "playing",
                "current_song_id": "dj-1",
                "last_seen_at": "2026-07-06T00:00:00Z",
            }
        )
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
        main.display_config = main.normalize_display_config(
            {
                "center_interval_seconds": 12,
                "game_interval_seconds": 9,
                "music_mode": "always",
                "source_order": ["custom", "portal"],
            }
        )
        main.display_runtime = main.normalize_display_runtime(
            {"center_index": 3, "center_paused": True, "pinned_card_id": "custom:card-1", "center_revision": 4}
        )
        main.display_custom_cards = [
            main.normalize_display_custom_card(
                {
                    "id": "card-1",
                    "category": "Host Update",
                    "primary": "Costume voting starts soon",
                    "enabled": True,
                    "duration_seconds": 12,
                }
            )
        ]
        main.live_display_notice_queue = [
            {"id": "notice-2", "type": "drink_ready", "title": "Drink Ready", "highlight": "Morgan"}
        ]
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
        self.assertEqual("Thriller", main.dj_playlist[0]["title"])
        self.assertEqual("dj-1", main.dj_state["receiver"]["current_song_id"])
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
        self.assertEqual(12, main.display_config["center_interval_seconds"])
        self.assertEqual("always", main.display_config["music_mode"])
        self.assertTrue(main.display_runtime["center_paused"])
        self.assertEqual("custom:card-1", main.display_runtime["pinned_card_id"])
        self.assertEqual("Costume voting starts soon", main.display_custom_cards[0]["primary"])
        self.assertEqual("Morgan", main.live_display_notice_queue[0]["highlight"])
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

    def test_admin_can_manage_dj_playlist_and_send_a_pending_command(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            add_response = client.post(
                "/admin/dj",
                data={
                    "action": "add_dj_song",
                    "title": "Thriller",
                    "artist": "Michael Jackson",
                    "apple_music_id": "203709340",
                    "album": "Thriller",
                    "artwork_url": "https://example.test/thriller.jpg",
                    "duration_ms": "357000",
                    "enabled": "yes",
                },
            )
            song_id = self.redis_state()["dj_playlist"][0]["id"]
            play_response = client.post(
                "/admin/dj",
                data={"action": "play_dj_song", "song_id": song_id},
            )

        state = self.redis_state()
        self.assertEqual(200, add_response.status_code)
        self.assertEqual(200, play_response.status_code)
        self.assertEqual("Thriller", state["dj_playlist"][0]["title"])
        self.assertEqual("play_song", state["dj_state"]["current_command"]["action"])
        self.assertEqual("pending", state["dj_state"]["current_command"]["status"])
        self.assertEqual(song_id, state["dj_state"]["desired"]["song_id"])
        self.assertIn("Waiting for confirmation", play_response.get_data(as_text=True))

    def test_attendee_can_submit_song_request_and_admin_approval_randomly_inserts_it_without_command(self):
        main.event_experience_mode = "party_day"
        main.dj_playlist = [
            main.normalize_dj_song(
                {"id": "dj-1", "apple_music_id": "203709340", "title": "Thriller", "artist": "Michael Jackson"}
            )
        ]
        self.save_current_state()
        original_randbelow = main.secrets.randbelow
        main.secrets.randbelow = lambda upper: upper - 1
        try:
            with main.app.test_client() as client:
                self.login_regular(client)
                request_response = client.post(
                    "/party/jukebox/requests",
                    data={
                        "title": "Superstition",
                        "artist": "Stevie Wonder",
                        "apple_music_id": "1440823671",
                        "album": "Talking Book",
                        "artwork_url": "https://example.test/superstition.jpg",
                        "duration_ms": "267000",
                    },
                )
                request_id = self.redis_state()["dj_song_requests"][0]["id"]
                self.login_admin(client)
                approve_response = client.post(
                    "/admin/dj",
                    data={"action": "approve_dj_song_request", "request_id": request_id},
                )
        finally:
            main.secrets.randbelow = original_randbelow

        state = self.redis_state()
        self.assertEqual(302, request_response.status_code)
        self.assertEqual(200, approve_response.status_code)
        self.assertEqual([], state["dj_song_requests"])
        self.assertEqual(["Thriller", "Superstition"], [song["title"] for song in state["dj_playlist"]])
        self.assertIsNone(state["dj_state"]["current_command"])
        self.assertIn("playlist position 2", approve_response.get_data(as_text=True))

    def test_rejected_song_request_is_removed_without_changing_playlist(self):
        main.dj_playlist = [
            main.normalize_dj_song(
                {"id": "dj-1", "apple_music_id": "203709340", "title": "Thriller", "artist": "Michael Jackson"}
            )
        ]
        main.dj_song_requests = [
            main.normalize_dj_song_request(
                {
                    "id": "request-1",
                    "requester_id": "user-1",
                    "requester_name": "Jamie",
                    "song": {"apple_music_id": "1440823671", "title": "Superstition", "artist": "Stevie Wonder"},
                }
            )
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post("/admin/dj", data={"action": "reject_dj_song_request", "request_id": "request-1"})

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertEqual([], state["dj_song_requests"])
        self.assertEqual(["Thriller"], [song["title"] for song in state["dj_playlist"]])

    def test_admin_song_request_queue_fragment_requires_admin_and_contains_requests(self):
        main.dj_song_requests = [
            main.normalize_dj_song_request(
                {"id": "request-1", "requester_id": "user-1", "requester_name": "Jamie", "song": {"apple_music_id": "1440823671", "title": "Superstition", "artist": "Stevie Wonder"}}
            )
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            unauthorized_response = client.get("/api/admin/dj-song-request-queue")
            self.login_admin(client)
            response = client.get("/api/admin/dj-song-request-queue")

        payload = response.get_json()
        self.assertEqual(302, unauthorized_response.status_code)
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, payload["request_count"])
        self.assertIn("Superstition", payload["html"])

    def test_attendee_jukebox_only_exposes_confirmed_song_and_own_pending_requests(self):
        main.event_experience_mode = "party_day"
        main.dj_playlist = [
            main.normalize_dj_song(
                {"id": "dj-1", "apple_music_id": "203709340", "title": "Thriller", "artist": "Michael Jackson"}
            )
        ]
        main.dj_state["desired"]["song_id"] = "missing-song"
        main.dj_state["receiver"]["current_song_id"] = "dj-1"
        main.dj_state["receiver"]["playback_status"] = "playing"
        main.dj_song_requests = [
            main.normalize_dj_song_request(
                {"id": "request-1", "requester_id": "user-1", "requester_name": "Jamie", "song": {"apple_music_id": "1440823671", "title": "Superstition", "artist": "Stevie Wonder"}}
            ),
            main.normalize_dj_song_request(
                {"id": "request-2", "requester_id": "user-2", "requester_name": "Alex", "song": {"apple_music_id": "1440767688", "title": "Billie Jean", "artist": "Michael Jackson"}}
            ),
        ]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.get("/api/party/jukebox-data")
            page_response = client.get("/party/jukebox")
            dashboard_response = client.get("/party")

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual(200, page_response.status_code)
        self.assertEqual(200, dashboard_response.status_code)
        self.assertEqual("Thriller", payload["now_playing"]["title"])
        self.assertEqual("playing", payload["playback_status"])
        self.assertEqual(["request-1"], [entry["id"] for entry in payload["pending_requests"]])
        self.assertNotIn("desired", payload)
        self.assertNotIn("receiver", payload)
        self.assertIn("data-party-jukebox", page_response.get_data(as_text=True))
        self.assertIn("Open Jukebox", dashboard_response.get_data(as_text=True))

    def test_apple_music_catalog_search_returns_safe_eight_song_pages(self):
        class FakeAppleResponse:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        requested_urls = []
        payloads = [
            {"results": {"songs": {"data": [{"id": "song-1", "attributes": {"name": "Song 1", "artistName": "Artist 1"}}], "next": "/v1/catalog/us/search?offset=8"}}},
            {"results": {"songs": {"data": [{"id": "song-9", "attributes": {"name": "Song 9", "artistName": "Artist 9"}}]}}},
        ]
        original_urlopen = main.urlopen
        original_developer_token = main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"]

        def fake_urlopen(api_request, timeout):
            requested_urls.append(api_request.full_url)
            return FakeAppleResponse(payloads.pop(0))

        main.urlopen = fake_urlopen
        main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"] = "test-developer-token"
        try:
            first_page = main.search_apple_music_catalog("Artist", 0)
            second_page = main.search_apple_music_catalog("Artist", 8)
        finally:
            main.urlopen = original_urlopen
            main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"] = original_developer_token

        self.assertEqual(["Song 1"], [song["title"] for song in first_page["results"]])
        self.assertEqual(8, first_page["next_offset"])
        self.assertIsNone(second_page["next_offset"])
        self.assertIn("limit=8", requested_urls[0])
        self.assertIn("offset=0", requested_urls[0])
        self.assertIn("offset=8", requested_urls[1])

    def test_catalog_search_endpoints_return_pages_and_reject_invalid_offsets(self):
        main.event_experience_mode = "party_day"
        original_search = main.search_apple_music_catalog
        original_developer_token = main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"]
        captured_offsets = []

        def fake_search(query, offset=0):
            captured_offsets.append((query, offset))
            return {
                "results": [{"title": "Song 9", "artist": "Artist", "apple_music_id": "song-9"}],
                "next_offset": None,
            }

        main.search_apple_music_catalog = fake_search
        main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"] = "test-developer-token"
        try:
            with main.app.test_client() as client:
                self.login_admin(client)
                admin_response = client.get("/api/dj/catalog-search?q=Artist&offset=8")
                invalid_admin_response = client.get("/api/dj/catalog-search?q=Artist&offset=provider-url")
                self.login_regular(client)
                attendee_response = client.get("/api/party/jukebox/catalog-search?q=Artist&offset=8")
                invalid_attendee_response = client.get("/api/party/jukebox/catalog-search?q=Artist&offset=-1")
                misaligned_attendee_response = client.get("/api/party/jukebox/catalog-search?q=Artist&offset=7")
        finally:
            main.search_apple_music_catalog = original_search
            main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"] = original_developer_token

        self.assertEqual(200, admin_response.status_code)
        self.assertEqual(8, admin_response.get_json()["offset"])
        self.assertEqual(200, attendee_response.status_code)
        self.assertEqual(8, attendee_response.get_json()["offset"])
        self.assertEqual([("Artist", 8), ("Artist", 8)], captured_offsets)
        self.assertEqual(400, invalid_admin_response.status_code)
        self.assertEqual(400, invalid_attendee_response.status_code)
        self.assertEqual(400, misaligned_attendee_response.status_code)

        page_html = client.get("/party/jukebox").get_data(as_text=True)
        self.assertIn("data-jukebox-pagination", page_html)
        self.assertIn("Song title or artist", page_html)

    def test_attendee_song_request_prevents_duplicate_and_limits_pending_requests(self):
        main.event_experience_mode = "party_day"
        self.save_current_state()
        base_song = {
            "title": "Thriller",
            "artist": "Michael Jackson",
            "apple_music_id": "203709340",
            "album": "Thriller",
            "artwork_url": "",
            "duration_ms": "357000",
        }

        with main.app.test_client() as client:
            self.login_regular(client)
            first_response = client.post("/party/jukebox/requests", data=base_song)
            duplicate_response = client.post("/party/jukebox/requests", data=base_song)
            for index in range(2):
                client.post(
                    "/party/jukebox/requests",
                    data={**base_song, "title": f"Song {index}", "apple_music_id": f"song-{index}"},
                )
            limited_response = client.post(
                "/party/jukebox/requests",
                data={**base_song, "title": "One Too Many", "apple_music_id": "song-limit"},
            )

        state = self.redis_state()
        self.assertEqual(302, first_response.status_code)
        self.assertIn("already have that song", duplicate_response.location.replace("+", " "))
        self.assertEqual(3, len(state["dj_song_requests"]))
        self.assertIn("up to 3 song requests", limited_response.location.replace("+", " "))

    def test_dj_receiver_acknowledges_command_and_display_data_uses_confirmed_song(self):
        main.dj_playlist = [
            main.normalize_dj_song(
                {
                    "id": "dj-1",
                    "apple_music_id": "203709340",
                    "title": "Thriller",
                    "artist": "Michael Jackson",
                    "artwork_url": "https://example.test/thriller.jpg",
                }
            )
        ]
        main.queue_dj_command("play_song", "dj-1")
        command_id = main.dj_state["current_command"]["id"]
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            receiver_response = client.post(
                "/api/dj/receiver-state",
                json={
                    "receiver_id": "living-room-tv",
                    "status": "ready",
                    "authorization_status": "authorized",
                    "audio_enabled": True,
                    "playback_status": "playing",
                    "current_song_id": "dj-1",
                    "acknowledged_command_id": command_id,
                    "command_succeeded": True,
                },
            )
            display_response = client.get("/api/display-data")

        state = self.redis_state()
        display_payload = display_response.get_json()
        self.assertEqual(200, receiver_response.status_code)
        self.assertEqual(200, display_response.status_code)
        self.assertIsNone(state["dj_state"]["current_command"])
        self.assertEqual("succeeded", state["dj_state"]["last_command"]["status"])
        self.assertEqual("playing", display_payload["dj"]["receiver"]["playback_status"])
        self.assertEqual("Thriller", display_payload["dj"]["current_song"]["title"])

    def test_dj_failure_remains_visible_after_a_regular_receiver_heartbeat(self):
        main.dj_playlist = [
            main.normalize_dj_song(
                {"id": "dj-1", "apple_music_id": "203709340", "title": "Thriller", "artist": "Michael Jackson"}
            )
        ]
        main.queue_dj_command("play_song", "dj-1")
        command_id = main.dj_state["current_command"]["id"]

        main.record_dj_receiver_state(
            {
                "receiver_id": "living-room-tv",
                "status": "error",
                "authorization_status": "error",
                "audio_enabled": False,
                "acknowledged_command_id": command_id,
                "command_succeeded": False,
                "error": "Apple Music authorization was cancelled.",
            }
        )
        main.record_dj_receiver_state(
            {
                "receiver_id": "living-room-tv",
                "status": "error",
                "authorization_status": "error",
                "audio_enabled": False,
            }
        )

        flow = main.dj_command_flow()
        self.assertEqual("failed", main.dj_state["last_command"]["status"])
        self.assertEqual("Apple Music authorization was cancelled.", main.dj_state["receiver"]["last_error"])
        self.assertEqual("failed", flow[0]["state"])
        self.assertIn("cancelled", flow[0]["detail"])
        self.assertIn("cancelled", flow[2]["detail"])

    def test_dj_signal_path_is_green_ready_after_display_audio_is_enabled(self):
        main.record_dj_receiver_state(
            {
                "receiver_id": "living-room-tv",
                "status": "ready",
                "authorization_status": "authorized",
                "audio_enabled": True,
                "playback_status": "stopped",
                "clear_error": True,
            }
        )

        flow = main.dj_command_flow()
        self.assertEqual(["ready", "connected", "authorized", "ready"], [step["state"] for step in flow])
        self.assertIn("armed", flow[0]["detail"])
        self.assertIn("unlocked", flow[3]["detail"])

    def test_dj_workflow_reset_preserves_playlist_and_waits_for_display_acknowledgement(self):
        main.dj_playlist = [
            main.normalize_dj_song(
                {"id": "dj-1", "apple_music_id": "203709340", "title": "Thriller", "artist": "Michael Jackson"}
            )
        ]
        main.queue_dj_command("play_song", "dj-1")

        reset_command = main.queue_dj_workflow_reset()

        self.assertEqual("reset", main.dj_state["current_command"]["action"])
        self.assertEqual("pending", main.dj_state["last_reset"]["status"])
        self.assertEqual([], main.dj_state["desired"]["queue_order"])
        self.assertEqual("pending", main.dj_command_flow()[0]["state"])
        self.assertEqual("Thriller", main.dj_playlist[0]["title"])

        main.record_dj_receiver_state(
            {
                "receiver_id": "living-room-tv",
                "status": "needs_audio_enable",
                "authorization_status": "not_authorized",
                "audio_enabled": False,
                "playback_status": "stopped",
                "acknowledged_command_id": reset_command["id"],
                "command_succeeded": True,
                "clear_error": True,
            }
        )

        self.assertIsNone(main.dj_state["current_command"])
        self.assertIsNone(main.dj_state["last_command"])
        self.assertEqual("acknowledged", main.dj_state["last_reset"]["status"])
        self.assertEqual("offline", main.dj_state["receiver"]["status"])
        self.assertEqual("stopped", main.dj_state["desired"]["playback_status"])
        self.assertEqual("confirmed", main.dj_command_flow()[0]["state"])
        self.assertEqual("Thriller", main.dj_playlist[0]["title"])

    def test_admin_can_request_dj_workflow_reset_while_display_is_offline(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.post("/admin/dj", data={"action": "reset_dj_workflow"})

        state = self.redis_state()
        self.assertEqual(200, response.status_code)
        self.assertEqual("reset", state["dj_state"]["current_command"]["action"])
        self.assertEqual("pending", state["dj_state"]["last_reset"]["status"])
        self.assertIn("will complete when the live display reconnects", response.get_data(as_text=True))

    def test_dj_admin_workspace_loads_live_receiver_status_updates(self):
        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.get("/admin/dj")

        page = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("data-dj-status-root", page)
        self.assertIn("dj-admin-status.js", page)

    def test_dj_receiver_requires_admin_session_and_json_csrf_outside_testing(self):
        self.save_current_state()
        main.app.config["TESTING"] = False

        with main.app.test_client() as client:
            unauthorized_response = client.post("/api/dj/receiver-state", json={"receiver_id": "tv"})
            self.login_admin(client)
            with client.session_transaction() as session:
                csrf_token = session["csrf_token"] = "dj-csrf"
            rejected_response = client.post("/api/dj/receiver-state", json={"receiver_id": "tv"})
            accepted_response = client.post(
                "/api/dj/receiver-state",
                json={"receiver_id": "tv", "status": "needs_audio_enable"},
                headers={"X-CSRF-Token": csrf_token},
            )

        self.assertEqual(302, unauthorized_response.status_code)
        self.assertEqual(400, rejected_response.status_code)
        self.assertEqual(200, accepted_response.status_code)

    def test_musickit_token_response_includes_configured_storefront(self):
        original_token = main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"]
        original_storefront = main.app.config["APPLE_MUSIC_STOREFRONT"]
        main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"] = "test-developer-token"
        main.app.config["APPLE_MUSIC_STOREFRONT"] = "us"
        try:
            with main.app.test_client() as client:
                self.login_admin(client)
                response = client.get("/api/dj/musickit-token")
        finally:
            main.app.config["APPLE_MUSIC_DEVELOPER_TOKEN"] = original_token
            main.app.config["APPLE_MUSIC_STOREFRONT"] = original_storefront

        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("us", payload["storefront"])

    def test_generated_musickit_token_binds_to_configured_web_origin(self):
        original_team_id = main.app.config["APPLE_MUSIC_TEAM_ID"]
        original_key_id = main.app.config["APPLE_MUSIC_KEY_ID"]
        original_private_key = main.app.config["APPLE_MUSIC_PRIVATE_KEY"]
        original_origin = main.app.config["APPLE_MUSIC_WEB_ORIGIN"]
        original_jwt = sys.modules.get("jwt")
        captured = {}

        def encode(claims, private_key, algorithm, headers):
            captured.update({"claims": claims, "private_key": private_key, "algorithm": algorithm, "headers": headers})
            return "signed-token"

        main.app.config["APPLE_MUSIC_TEAM_ID"] = "team-id"
        main.app.config["APPLE_MUSIC_KEY_ID"] = "key-id"
        main.app.config["APPLE_MUSIC_PRIVATE_KEY"] = "private-key"
        main.app.config["APPLE_MUSIC_WEB_ORIGIN"] = "https://tnq-halloween.com/display"
        sys.modules["jwt"] = types.SimpleNamespace(encode=encode)
        try:
            token = main.apple_music_developer_token()
        finally:
            main.app.config["APPLE_MUSIC_TEAM_ID"] = original_team_id
            main.app.config["APPLE_MUSIC_KEY_ID"] = original_key_id
            main.app.config["APPLE_MUSIC_PRIVATE_KEY"] = original_private_key
            main.app.config["APPLE_MUSIC_WEB_ORIGIN"] = original_origin
            if original_jwt is None:
                del sys.modules["jwt"]
            else:
                sys.modules["jwt"] = original_jwt

        self.assertEqual("signed-token", token)
        self.assertEqual("https://tnq-halloween.com", captured["claims"]["origin"])
        self.assertEqual("ES256", captured["algorithm"])
        self.assertEqual({"kid": "key-id"}, captured["headers"])

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

    def test_admin_display_workspace_manages_layout_custom_cards_and_center_controls(self):
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            workspace = client.get("/admin/display")
            settings_response = client.post(
                "/admin/display",
                data={
                    "action": "update_display_layout",
                    "source_enabled": ["portal", "custom", "costume"],
                    "center_interval_seconds": "12",
                    "game_interval_seconds": "9",
                    "game_mode": "auto",
                    "bar_mode": "auto",
                    "music_mode": "always",
                    "max_bar_orders": "5",
                    "notice_duration_seconds": "14",
                    "density": "compact",
                },
            )
            card_response = client.post(
                "/admin/display",
                data={
                    "action": "add_display_card",
                    "category": "Host Update",
                    "primary": "Costume voting starts at ten",
                    "secondary": "Finish your signup now.",
                    "tertiary": "Open the party portal.",
                    "link": "/party",
                    "link_label": "Party portal",
                    "duration_seconds": "11",
                    "enabled": "yes",
                },
            )
            display_payload = client.get("/api/display-data").get_json()
            custom_entry = next(entry for entry in display_payload["entries"] if entry["source"] == "custom")
            card_id = custom_entry["id"].split(":", 1)[1]
            update_response = client.post(
                "/admin/display",
                data={
                    "action": "update_display_card",
                    "card_id": card_id,
                    "category": "Schedule Update",
                    "primary": "Costume voting starts at eleven",
                    "secondary": "The card editor saved this change.",
                    "tertiary": "Open the party portal.",
                    "link": "/party",
                    "link_label": "Party portal",
                    "duration_seconds": "13",
                    "enabled": "yes",
                },
            )
            updated_workspace = client.get("/admin/display")
            display_payload = client.get("/api/display-data").get_json()
            portal_entry = next(entry for entry in display_payload["entries"] if entry["source"] == "portal")
            pin_response = client.post(
                "/admin/display",
                data={"action": "pin_display_entry", "entry_id": portal_entry["id"]},
            )

        state = self.redis_state()
        self.assertEqual(200, workspace.status_code)
        self.assertIn("Live Display", workspace.get_data(as_text=True))
        self.assertEqual(200, settings_response.status_code)
        self.assertEqual(200, card_response.status_code)
        self.assertEqual(200, update_response.status_code)
        self.assertEqual(200, pin_response.status_code)
        self.assertEqual(12, state["display_config"]["center_interval_seconds"])
        self.assertEqual("always", state["display_config"]["music_mode"])
        self.assertEqual("compact", display_payload["layout"]["density"])
        custom_entry = next(entry for entry in display_payload["entries"] if entry["source"] == "custom")
        self.assertEqual("Costume voting starts at eleven", custom_entry["primary"])
        self.assertEqual(13, custom_entry["duration_seconds"])
        self.assertEqual("/party", custom_entry["link"])
        self.assertIn("Edit Card", updated_workspace.get_data(as_text=True))
        self.assertIn("Save Card Changes", updated_workspace.get_data(as_text=True))
        self.assertFalse(any(entry["source"] == "karaoke" for entry in display_payload["entries"]))
        self.assertEqual(portal_entry["id"], state["display_runtime"]["pinned_card_id"])
        self.assertTrue(state["display_runtime"]["center_paused"])

    def test_display_layout_rotates_multiple_games_on_left_stage_and_removes_private_costume_contact(self):
        main.costume_signups = [
            main.CostumeSignup("Jamie", "Vampire", "private@example.com", "costume-1")
        ]
        for game_key in (main.TWO_TRUTHS_GAME_KEY, main.FILL_BLANK_GAME_KEY):
            main.party_game_state(game_key)["enabled"] = True

        with main.app.test_client() as client:
            self.login_admin(client)
            payload = client.get("/api/display-data").get_json()

        game_keys = {entry["game_key"] for entry in payload["layout"]["games"]["entries"]}
        self.assertEqual(
            {main.TWO_TRUTHS_GAME_KEY, main.FILL_BLANK_GAME_KEY},
            game_keys,
        )
        self.assertTrue(payload["layout"]["games"]["visible"])
        self.assertTrue(all(entry.get("steps") for entry in payload["layout"]["games"]["entries"]))
        self.assertTrue(all(entry.get("action_label") for entry in payload["layout"]["games"]["entries"]))
        self.assertNotIn("private@example.com", json.dumps(payload))

    def test_bar_stage_hides_when_empty_and_ready_notices_advance_sequentially(self):
        order = {
            "id": "order-1",
            "user_id": "user-1",
            "username": "Jamie",
            "email": "private@example.com",
            "menu_item_id": "drink-1",
            "item_name": "Witch Margarita",
            "item_image_url": "https://example.test/witch.jpg",
            "recipe": "Private bartender recipe",
            "status": "received",
            "estimated_ready_at": main._utc_now_iso(),
            "created_at": main._utc_now_iso(),
            "started_at": "",
            "completed_at": "",
            "completed_seconds": None,
        }
        empty_bar = main.build_bar_stage()
        main.menu_items = [
            {
                "id": "drink-1",
                "name": "Witch Margarita",
                "category": "drink",
                "description": "A smoky citrus specialty.",
                "image_url": "https://example.test/witch.jpg",
                "available": True,
                "orderable": True,
            }
        ]
        main.drink_orders = [order]
        active_bar = main.build_bar_stage()
        first = main.build_drink_ready_override(order)
        second = {**main.build_drink_ready_override({**order, "username": "Morgan"}), "expires_at": ""}
        main.enqueue_display_notice(first)
        main.enqueue_display_notice(second)
        main.live_display_notice_override["expires_at"] = "2000-01-01T00:00:00Z"
        main.cleanup_expired_display_notices()

        self.assertFalse(empty_bar["visible"])
        self.assertTrue(active_bar["visible"])
        self.assertEqual("Jamie", active_bar["orders"][0]["name"])
        self.assertEqual(1, active_bar["orders"][0]["position"])
        self.assertEqual(1, active_bar["summary"]["waiting_count"])
        self.assertEqual(1, active_bar["summary"]["available_drink_count"])
        self.assertEqual("Witch Margarita", active_bar["featured_item"]["name"])
        self.assertEqual("https://tnq-halloween.com/party/menu", active_bar["action"]["url"])
        self.assertNotIn("email", active_bar["orders"][0])
        self.assertNotIn("recipe", active_bar["orders"][0])
        self.assertEqual("Morgan", main.live_display_notice_override["highlight"])
        self.assertEqual([], main.live_display_notice_queue)

    def test_live_display_renders_enriched_space_utilization_regions(self):
        with main.app.test_client() as client:
            self.login_admin(client)
            response = client.get("/live-display")

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        for marker in (
            "data-center-facts",
            "data-center-steps",
            "data-center-action",
            "data-game-steps",
            "data-game-action",
            "data-bar-summary",
            "data-bar-feature",
            "data-bar-action",
        ):
            self.assertIn(marker, body)

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
            response = client.get("/admin/guests")

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
        long_message = "Bring your costume. " * 120

        with main.app.test_client() as client:
            self.login_admin(client)
            form_response = client.get("/admin/guests")
            response = client.post(
                "/admin/guests",
                data={
                    "action": "add_rsvp_update",
                    "title": "Long update",
                    "message": long_message,
                },
            )

        state = self.redis_state()
        self.assertIn('id="rsvp_update_message" name="message" maxlength="5000"', form_response.get_data(as_text=True))
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
        portal_entry = next(entry for entry in entries if entry["id"] == "portal:wifi")
        costume_entry = next(entry for entry in entries if entry["id"] == "costume:signup")
        karaoke_entry = next(entry for entry in entries if entry["id"] == "karaoke:signup")
        self.assertEqual("access", portal_entry["kind"])
        self.assertEqual(4, len(portal_entry["facts"]))
        self.assertEqual(3, len(portal_entry["steps"]))
        self.assertEqual("action", costume_entry["kind"])
        self.assertEqual("https://tnq-halloween.com/party/costumes", costume_entry["action"]["url"])
        self.assertEqual("action", karaoke_entry["kind"])
        self.assertEqual("https://tnq-halloween.com/party/karaoke", karaoke_entry["action"]["url"])
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

    def test_party_account_requires_login_and_shows_roles_and_session_permissions(self):
        self.add_user_account("Jamie", "party-password", "user-1", "jamie@example.com")["roles"] = ["regular", "bartender"]
        self.save_current_state()

        with main.app.test_client() as client:
            redirect_response = client.get("/party/account")
            self.login_regular(client)
            with client.session_transaction() as session:
                session["roles"] = ["bartender", "regular"]
            account_response = client.get("/party/account")
            dashboard_response = client.get("/party")

        body = account_response.get_data(as_text=True)
        self.assertEqual(302, redirect_response.status_code)
        self.assertIn("/party/login", redirect_response.headers["Location"])
        self.assertEqual(200, account_response.status_code)
        self.assertIn("Account level", body)
        self.assertIn("Assigned roles", body)
        self.assertIn("Current session permissions", body)
        self.assertIn("bartender, regular", body)
        self.assertIn('href="/party/account"', dashboard_response.get_data(as_text=True))

    def test_party_account_updates_profile_without_changing_account_id(self):
        account = self.add_user_account("Jamie", "party-password", "user-1", "jamie@example.com")
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.post(
                "/party/account",
                data={
                    "action": "update_profile",
                    "username": "Jamie Wells",
                    "email": "jamie.wells@example.com",
                },
            )
            with client.session_transaction() as session:
                session_username = session.get("username")

        state = self.redis_state()
        updated_account = state["user_accounts"]["jamie wells"]
        self.assertEqual(200, response.status_code)
        self.assertIn("profile details were updated", response.get_data(as_text=True))
        self.assertNotIn("jamie", state["user_accounts"])
        self.assertEqual(account["id"], updated_account["id"])
        self.assertEqual("jamie.wells@example.com", updated_account["email"])
        self.assertEqual("Jamie Wells", state["registered_users"][account["id"]])
        self.assertEqual("Jamie Wells", session_username)

    def test_party_account_rejects_invalid_profile_and_changes_password(self):
        account = self.add_user_account("Jamie", "party-password", "user-1", "jamie@example.com")
        main.password_reset_tokens["token-hash"] = {
            "normalized_username": "jamie",
            "account_id": account["id"],
            "email": account["email"],
            "created_at": "2026-07-01T00:00:00Z",
            "expires_at": "2026-07-01T00:45:00Z",
            "used_at": "",
        }
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            invalid_profile_response = client.post(
                "/party/account",
                data={"action": "update_profile", "username": "", "email": "not-an-email"},
            )
            incorrect_password_response = client.post(
                "/party/account",
                data={
                    "action": "change_password",
                    "current_password": "incorrect",
                    "new_password": "new-party-password",
                    "confirm_password": "new-party-password",
                },
            )
            password_response = client.post(
                "/party/account",
                data={
                    "action": "change_password",
                    "current_password": "party-password",
                    "new_password": "new-party-password",
                    "confirm_password": "new-party-password",
                },
            )
            client.post("/logout")
            login_response = client.post(
                "/party/login",
                data={"username": "Jamie", "password": "new-party-password"},
            )

        state = self.redis_state()
        self.assertIn("Name is required.", invalid_profile_response.get_data(as_text=True))
        self.assertIn("valid email", invalid_profile_response.get_data(as_text=True))
        self.assertIn("current password is incorrect", incorrect_password_response.get_data(as_text=True))
        self.assertIn("password was updated", password_response.get_data(as_text=True))
        self.assertTrue(main.check_password_hash(state["user_accounts"]["jamie"]["password_hash"], "new-party-password"))
        self.assertEqual({}, state["password_reset_tokens"])
        self.assertEqual(302, login_response.status_code)

    def test_combined_session_roles_expose_all_role_navigation_and_views(self):
        account = self.add_user_account("Jamie", "party-password", "user-1", "jamie@example.com")
        account["roles"] = ["regular", "bartender"]
        main.event_experience_mode = "party_day"
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            self.login_admin(client)
            with client.session_transaction() as session:
                session["roles"] = ["admin", "bartender", "regular"]
            dashboard_response = client.get("/party")
            responses = [
                client.get("/party/account"),
                client.get("/party/menu"),
                client.get("/party/drink-history"),
                client.get("/party/jukebox"),
                client.get("/party/costumes"),
                client.get("/party/karaoke"),
                client.get("/bartender"),
                client.get("/admin"),
                client.get("/live-display"),
            ]

        dashboard_body = dashboard_response.get_data(as_text=True)
        self.assertEqual(200, dashboard_response.status_code)
        for label in ("Account", "Menu", "Drink History", "Jukebox", "Costume", "Karaoke", "Bartender", "Admin"):
            self.assertIn(f">{label}<", dashboard_body)
        self.assertTrue(all(response.status_code == 200 for response in responses))

    def test_admin_role_preview_blocks_extra_session_views_and_preserves_exit_hatch(self):
        self.add_user_account("Jamie", "party-password", "user-1", "jamie@example.com")
        main.event_experience_mode = "party_day"
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            self.login_admin(client)
            with client.session_transaction() as session:
                session["roles"] = ["admin", "bartender", "regular"]

            preview_response = client.post(
                "/admin/public",
                data={"action": "set_role_preview", "role_preview": "regular"},
            )
            dashboard_response = client.get("/party")
            bartender_response = client.get("/bartender")
            admin_response = client.get("/admin")
            with client.session_transaction() as session:
                preview_key = session.get("role_preview")

            clear_response = client.post("/admin/role-preview/exit")
            restored_response = client.get("/party")

        dashboard_body = dashboard_response.get_data(as_text=True)
        self.assertEqual(302, preview_response.status_code)
        self.assertEqual("regular", preview_key)
        self.assertIn("Role preview: Attendee", dashboard_body)
        self.assertIn("Bartender<span>Hidden</span>", dashboard_body)
        self.assertIn("Admin<span>Hidden</span>", dashboard_body)
        # A regular-role preview cannot open bartender or admin views, even
        # when the underlying test session contains those extra roles.
        self.assertEqual(302, bartender_response.status_code)
        self.assertEqual(302, admin_response.status_code)
        self.assertEqual(302, clear_response.status_code)
        self.assertNotIn("Role preview:", restored_response.get_data(as_text=True))
        self.assertEqual(200, restored_response.status_code)

    def test_attendee_preview_marks_bartender_capability_hidden_without_admin_role(self):
        self.add_user_account("Jamie", "party-password", "user-1", "jamie@example.com")
        main.event_experience_mode = "party_day"
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_regular(client)
            with client.session_transaction() as session:
                session["roles"] = ["bartender", "regular"]
                session["role_preview"] = "regular"
            dashboard_response = client.get("/party")

        dashboard_body = dashboard_response.get_data(as_text=True)
        self.assertEqual(200, dashboard_response.status_code)
        self.assertIn('class="role-preview-hidden" aria-disabled="true">Bartender<span>Hidden</span>', dashboard_body)

    def test_party_login_refreshes_account_derived_roles_and_preserves_admin(self):
        self.add_user_account("Jamie", "party-password", "user-1", "jamie@example.com")
        self.save_current_state()

        with main.app.test_client() as client:
            self.login_admin(client)
            with client.session_transaction() as session:
                session["roles"] = ["admin", "bartender"]
            response = client.post(
                "/party/login",
                data={"username": "Jamie", "password": "party-password"},
            )
            with client.session_transaction() as session:
                roles = session.get("roles", [])
                admin_authenticated = session.get("admin_authenticated")

        self.assertEqual(302, response.status_code)
        self.assertEqual(["admin", "regular"], roles)
        self.assertTrue(admin_authenticated)

    def test_jukebox_request_uses_regular_role_protection(self):
        main.event_experience_mode = "party_day"
        self.save_current_state()

        with main.app.test_client() as client:
            response = client.post("/party/jukebox/requests", data={})

        self.assertEqual(302, response.status_code)
        self.assertIn("/party/login", response.headers["Location"])

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

    def test_youtube_url_parser_accepts_supported_formats_and_rejects_invalid_hosts(self):
        video_id = "abc123DEF45"

        self.assertEqual(video_id, main.parse_youtube_video_id(video_id))
        self.assertEqual(
            video_id,
            main.parse_youtube_video_id(f"https://www.youtube.com/watch?v={video_id}&list=PL123"),
        )
        self.assertEqual(
            video_id,
            main.parse_youtube_video_id(f"https://youtu.be/{video_id}?si=share"),
        )
        self.assertEqual(
            video_id,
            main.parse_youtube_video_id(f"https://www.youtube.com/shorts/{video_id}"),
        )
        self.assertEqual("", main.parse_youtube_video_id("https://example.com/watch?v=abc123DEF45"))
        self.assertEqual("", main.parse_youtube_video_id("not-a-youtube-video"))

    def test_youtube_vault_store_uses_aws_provider_chain_credentials(self):
        frozen_credentials = types.SimpleNamespace(
            access_key="temporary-access-key",
            secret_key="temporary-secret-key",
            token="temporary-session-token",
        )
        session = MagicMock()
        session.get_credentials.return_value.get_frozen_credentials.return_value = (
            frozen_credentials
        )
        client = MagicMock()
        client.is_authenticated.return_value = True
        client.secrets.kv.v1.read_secret.return_value = {
            "data": {"enabled": "false"}
        }

        with (
            patch.object(youtube_karaoke.boto3, "Session", return_value=session),
            patch.object(youtube_karaoke.hvac, "Client", return_value=client),
        ):
            store = youtube_karaoke.VaultYouTubeSecretStore(
                vault_addr="http://vault.test:8200",
                aws_auth_role="halloween-api",
            )
            data = store.read()

        self.assertEqual({"enabled": "false"}, data)
        client.auth.aws.iam_login.assert_called_once_with(
            access_key="temporary-access-key",
            secret_key="temporary-secret-key",
            session_token="temporary-session-token",
            role="halloween-api",
        )

    def test_attendee_search_uses_cache_without_spending_second_budget_unit(self):
        fake_youtube = self.enable_youtube_karaoke()

        with main.app.test_client() as client:
            self.login_regular(client)
            first = client.get("/api/party/karaoke/search?q=thriller")
            second = client.get("/api/party/karaoke/search?q=thriller")

        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertFalse(first.get_json()["cached"])
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(1, len(fake_youtube.search_calls))
        budget_key, account_key = main.youtube_search_budget_keys("user-1")
        self.assertEqual("1", self.fake_redis.store[budget_key])
        self.assertEqual("1", self.fake_redis.store[account_key])

    def test_attendee_search_builds_query_from_song_details(self):
        fake_youtube = self.enable_youtube_karaoke()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.get(
                "/api/party/karaoke/search",
                query_string={
                    "song_title": "  Thriller ",
                    "artist": " Michael   Jackson ",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [("Thriller Michael Jackson karaoke", "", 8)],
            fake_youtube.search_calls,
        )
        self.assertEqual(
            "Thriller Michael Jackson karaoke",
            response.get_json()["query"],
        )

    def test_attendee_structured_search_requires_song_and_artist(self):
        fake_youtube = self.enable_youtube_karaoke()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.get(
                "/api/party/karaoke/search",
                query_string={"song_title": "Thriller"},
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("invalid_query", response.get_json()["code"])
        self.assertEqual([], fake_youtube.search_calls)

    def test_attendee_karaoke_page_starts_with_song_details_not_freeform_search(self):
        self.enable_youtube_karaoke()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.get("/party/karaoke")

        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Tell us what you’re singing", html)
        self.assertIn("Find Karaoke Versions", html)
        self.assertIn("Choose your YouTube version", html)
        self.assertIn("Review your request", html)
        self.assertNotIn('id="youtube_query"', html)
        self.assertLess(html.index('id="song_title"'), html.index("Find Karaoke Versions"))
        self.assertLess(
            html.index("Find Karaoke Versions"),
            html.index("Choose your YouTube version"),
        )

    def test_attendee_karaoke_validation_preserves_details_and_verified_video(self):
        self.enable_youtube_karaoke()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = client.post(
                "/party/karaoke",
                data={
                    "name": "Tony",
                    "song_title": "Thriller",
                    "artist": "",
                    "youtube_video_id": "abc123DEF45",
                    "youtube_link": "https://www.youtube.com/watch?v=abc123DEF45",
                },
            )

        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertEqual([], main.karaoke_signups)
        self.assertIn("Artist is required.", html)
        self.assertIn('value="Thriller"', html)
        self.assertIn('value="abc123DEF45"', html)
        self.assertIn("Thriller Karaoke", html)

    def test_youtube_karaoke_submission_is_pending_and_hidden_from_public_lineup(self):
        self.enable_youtube_karaoke()

        with main.app.test_client() as client:
            self.login_regular(client)
            response = self.submit_youtube_karaoke_request(client)
            page = client.get("/party/karaoke")

        self.assertEqual(302, response.status_code)
        self.assertEqual(1, len(main.karaoke_signups))
        signup = main.karaoke_signups[0]
        self.assertEqual("user-1", signup.requester_id)
        self.assertEqual("pending", signup.workflow["approval_status"])
        self.assertEqual("verified", signup.workflow["video_validation_status"])
        self.assertEqual("abc123DEF45", signup.youtube["video_id"])
        self.assertEqual("Thriller", signup.song_title)
        self.assertEqual("Michael Jackson", signup.artist)
        self.assertEqual([], main.public_karaoke_signups())
        html = page.get_data(as_text=True)
        self.assertIn("Your Karaoke Requests", html)
        self.assertIn("Awaiting host approval", html)
        self.assertIn("No approved karaoke songs are queued yet", html)

    def test_admin_karaoke_workspace_is_protected_and_shows_pending_workflow(self):
        self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)

        with main.app.test_client() as client:
            protected = client.get("/admin/karaoke")
            self.login_admin(client)
            response = client.get("/admin/karaoke")

        self.assertEqual(302, protected.status_code)
        self.assertIn("/admin/login", protected.headers["Location"])
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Karaoke Operations", html)
        self.assertIn("Host review", html)
        self.assertIn("Thriller", html)
        self.assertIn("Approve and Add to Playlist", html)
        self.assertIn("Open YouTube Playlist", html)
        self.assertIn(
            "Approved songs are written to this playlist",
            html,
        )
        self.assertIn("Find on YouTube", html)
        self.assertIn(
            'data-karaoke-query="Thriller Michael Jackson karaoke"',
            html,
        )
        self.assertIn("Queue Management", html)
        self.assertIn("Download Karaoke Backup", html)
        self.assertIn("Clear Queue &amp; YouTube Playlist", html)

    def test_disabled_youtube_flag_preserves_manual_admin_lineup_and_stage_controls(self):
        main.app.config["YOUTUBE_CLIENT_ID"] = "setup-client-id"
        main.app.config["YOUTUBE_CLIENT_SECRET"] = "setup-client-secret"
        main.karaoke_signups = [
            main.KaraokeSignup(
                id="manual-karaoke",
                name="Manual Singer",
                song_title="Monster Mash",
                artist="Bobby Pickett",
                youtube_link="https://www.youtube.com/watch?v=abc123DEF45",
            )
        ]
        self.save_current_state()

        with main.app.test_client() as admin:
            self.login_admin(admin)
            page = admin.get("/admin/karaoke")
            called = admin.post(
                "/admin/karaoke",
                data={"action": "call_karaoke_singer", "entry_id": "manual-karaoke"},
            )

        self.assertEqual(200, page.status_code)
        html = page.get_data(as_text=True)
        self.assertIn("Add a manual karaoke entry", html)
        self.assertIn("YouTube connection", html)
        self.assertIn("Connect YouTube", html)
        self.assertIn("Manual Singer", html)
        self.assertNotIn("Approve and Add to Playlist", html)
        self.assertEqual(200, called.status_code)
        self.assertEqual(
            "called",
            main.find_karaoke_signup("manual-karaoke").workflow["performance_status"],
        )

    def test_admin_approval_verifies_and_inserts_playlist_item(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as admin:
            self.login_admin(admin)
            response = admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve")

        self.assertEqual(200, response.status_code)
        signup = main.find_karaoke_signup(entry_id)
        self.assertEqual("approved", signup.workflow["approval_status"])
        self.assertEqual("synced", signup.workflow["playlist_sync_status"])
        self.assertTrue(signup.workflow["playlist_item_id"])
        self.assertEqual(1, len(fake_youtube.insert_calls))
        self.assertEqual([entry_id], [entry.id for entry in main.public_karaoke_signups()])

    def test_admin_retry_is_idempotent_when_playlist_note_already_exists(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as admin:
            self.login_admin(admin)
            self.assertEqual(
                200,
                admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve").status_code,
            )
            response = admin.post(f"/api/admin/karaoke/entries/{entry_id}/retry")

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(fake_youtube.insert_calls))
        self.assertEqual(1, len(fake_youtube.playlist_items))
        self.assertEqual("synced", main.find_karaoke_signup(entry_id).workflow["playlist_sync_status"])

    def test_admin_retry_is_idempotent_when_youtube_omits_playlist_note(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as admin:
            self.login_admin(admin)
            self.assertEqual(
                200,
                admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve").status_code,
            )
            fake_youtube.playlist_items[0]["note"] = ""
            response = admin.post(f"/api/admin/karaoke/entries/{entry_id}/retry")

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, len(fake_youtube.insert_calls))
        self.assertEqual(1, len(fake_youtube.playlist_items))
        self.assertEqual(
            "synced",
            main.find_karaoke_signup(entry_id).workflow["playlist_sync_status"],
        )

    def test_age_restricted_video_is_rejected_during_server_side_verification(self):
        fake_youtube = self.enable_youtube_karaoke()
        fake_youtube.get_videos = lambda video_ids, client=None: [
            fake_youtube.video(video_ids[0], age_restricted=True)
        ]

        with self.assertRaises(main.YouTubeApiError) as error:
            main.verify_youtube_video("abc123DEF45")

        self.assertEqual("video_age_restricted", error.exception.code)

    def test_playlist_failure_keeps_approved_request_visible_for_retry(self):
        fake_youtube = self.enable_youtube_karaoke()
        fake_youtube.fail_insert = main.YouTubeApiError(
            "quota_exceeded",
            "YouTube quota is temporarily unavailable.",
        )
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as admin:
            self.login_admin(admin)
            response = admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve")

        self.assertEqual(502, response.status_code)
        signup = main.find_karaoke_signup(entry_id)
        self.assertEqual("approved", signup.workflow["approval_status"])
        self.assertEqual("failed", signup.workflow["playlist_sync_status"])
        self.assertEqual("quota_exceeded", signup.workflow["last_sync_error_code"])
        self.assertEqual([], main.public_karaoke_signups())
        self.assertTrue(main.karaoke_signup_view(signup)["needs_attention"])

    def test_reconciliation_recovers_uncertain_operation_from_playlist_note(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        signup = main.karaoke_signups[0]
        signup.workflow["approval_status"] = "approved"
        signup.workflow["playlist_sync_status"] = "failed"
        signup.workflow["last_sync_error_code"] = "operation_result_unknown"
        note = main.youtube_playlist_note(signup)
        fake_youtube.playlist_items.append(
            {
                "playlist_item_id": "playlist-item-recovered",
                "video_id": signup.youtube["video_id"],
                "position": 0,
                "note": note,
            }
        )
        self.save_current_state()

        with main.app.test_client() as admin:
            self.login_admin(admin)
            response = admin.post("/api/admin/karaoke/reconcile")

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.get_json()["summary"]["synced"])
        recovered = main.find_karaoke_signup(signup.id)
        self.assertEqual("synced", recovered.workflow["playlist_sync_status"])
        self.assertEqual("playlist-item-recovered", recovered.workflow["playlist_item_id"])

    def test_reconciliation_recovers_unique_video_when_youtube_omits_note(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        signup = main.karaoke_signups[0]
        signup.workflow["approval_status"] = "approved"
        signup.workflow["playlist_sync_status"] = "failed"
        signup.workflow["last_sync_error_code"] = "operation_result_unknown"
        fake_youtube.playlist_items.append(
            {
                "playlist_item_id": "playlist-item-no-note",
                "video_id": signup.youtube["video_id"],
                "position": 0,
                "note": "",
            }
        )
        self.save_current_state()

        with main.app.test_client() as admin:
            self.login_admin(admin)
            response = admin.post("/api/admin/karaoke/reconcile")

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.get_json()["summary"]["synced"])
        self.assertEqual(0, response.get_json()["summary"]["foreign_items"])
        recovered = main.find_karaoke_signup(signup.id)
        self.assertEqual("synced", recovered.workflow["playlist_sync_status"])
        self.assertEqual("playlist-item-no-note", recovered.workflow["playlist_item_id"])

    def test_attendee_cannot_cancel_another_users_pending_request(self):
        self.enable_youtube_karaoke()
        with main.app.test_client() as owner:
            self.login_regular(owner, user_id="user-owner", username="Owner")
            self.submit_youtube_karaoke_request(owner)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as other:
            self.login_regular(other, user_id="user-other", username="Other")
            response = other.post(f"/party/karaoke/{entry_id}/cancel")

        self.assertEqual(302, response.status_code)
        self.assertIn("request_error=", response.headers["Location"])
        self.assertEqual("pending", main.find_karaoke_signup(entry_id).workflow["approval_status"])

    def test_stage_workflow_updates_status_and_live_display_without_embedding_video(self):
        self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as admin:
            self.login_admin(admin)
            admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve")
            called = admin.post(
                "/admin/karaoke",
                data={"action": "call_karaoke_singer", "entry_id": entry_id},
            )
            on_stage = admin.post(
                "/admin/karaoke",
                data={"action": "mark_karaoke_on_stage", "entry_id": entry_id},
            )

        self.assertEqual(200, called.status_code)
        self.assertEqual(200, on_stage.status_code)
        signup = main.find_karaoke_signup(entry_id)
        self.assertEqual("on_stage", signup.workflow["performance_status"])
        self.assertEqual("on_stage", main.karaoke_state["stage_mode"])
        self.assertEqual("karaoke_on_stage", main.live_display_event_override["type"])
        self.assertNotIn("embed", json.dumps(main.live_display_event_override).lower())

    def test_admin_lineup_reorder_marks_playlist_order_for_resynchronization(self):
        self.enable_youtube_karaoke()
        entries = []
        for index, name in enumerate(("First", "Second", "Third")):
            signup = main.KaraokeSignup(
                id=f"karaoke-{index}",
                name=name,
                song_title=f"Song {index}",
                artist="Artist",
                youtube_link=f"https://www.youtube.com/watch?v=abc123DEF4{index}",
                youtube=main.normalize_karaoke_youtube(
                    {
                        **FakeYouTubeService().video(f"abc123DEF4{index}"),
                        "video_id": f"abc123DEF4{index}",
                    }
                ),
                workflow=main.normalize_karaoke_workflow({}, has_video=True),
            )
            signup.workflow.update(
                {
                    "video_validation_status": "verified",
                    "approval_status": "approved",
                    "playlist_sync_status": "synced",
                    "playlist_item_id": f"playlist-item-{index}",
                }
            )
            entries.append(signup)
        main.karaoke_signups = entries
        self.save_current_state()

        with main.app.test_client() as admin:
            self.login_admin(admin)
            response = admin.post(
                "/admin/karaoke",
                data={"action": "move_karaoke_to_top", "entry_id": "karaoke-2"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            ["karaoke-2", "karaoke-0", "karaoke-1"],
            [entry.id for entry in main.approved_karaoke_signups()],
        )
        self.assertTrue(
            all(
                entry.workflow["playlist_sync_status"] == "out_of_order"
                for entry in main.approved_karaoke_signups()
            )
        )

    def test_youtube_oauth_callback_rejects_state_mismatch_without_fetching_tokens(self):
        self.enable_youtube_karaoke()

        with main.app.test_client() as client:
            self.login_admin(client)
            with client.session_transaction() as session:
                session["youtube_oauth_state"] = "expected-state"
            response = client.get(
                "/admin/karaoke/youtube/callback?state=unexpected-state&code=authorization-code"
            )

        self.assertEqual(302, response.status_code)
        self.assertIn("youtube_error=", response.headers["Location"])
        self.assertIn(
            "YouTube+authorization+state+did+not+match",
            response.headers["Location"],
        )

    def test_youtube_oauth_callback_reuses_pkce_verifier_from_connect_session(self):
        self.enable_youtube_karaoke()

        class FakeOAuthFlow:
            def __init__(self, *, verifier="", refresh_token="new-refresh-token"):
                self.code_verifier = verifier
                self.credentials = types.SimpleNamespace(refresh_token=refresh_token)
                self.fetch_verifier = ""

            def authorization_url(self, **_kwargs):
                return "https://accounts.google.test/authorize", "oauth-state"

            def fetch_token(self, **_kwargs):
                self.fetch_verifier = self.code_verifier

        connect_flow = FakeOAuthFlow(verifier="pkce-verifier")
        callback_flow = FakeOAuthFlow()

        with patch.object(
            main,
            "build_oauth_flow",
            side_effect=[connect_flow, callback_flow],
        ):
            with main.app.test_client() as client:
                self.login_admin(client)
                connect = client.get("/admin/karaoke/youtube/connect")
                with client.session_transaction() as session:
                    self.assertEqual("oauth-state", session["youtube_oauth_state"])
                    self.assertEqual(
                        "pkce-verifier",
                        session["youtube_oauth_code_verifier"],
                    )
                callback = client.get(
                    "/admin/karaoke/youtube/callback?state=oauth-state&code=authorization-code"
                )

        self.assertEqual(302, connect.status_code)
        self.assertEqual(
            "https://accounts.google.test/authorize",
            connect.headers["Location"],
        )
        self.assertEqual(302, callback.status_code)
        self.assertIn("youtube_success=", callback.headers["Location"])
        self.assertEqual("pkce-verifier", callback_flow.fetch_verifier)
        self.assertEqual("new-refresh-token", main.app.config["YOUTUBE_REFRESH_TOKEN"])

    def test_persisted_youtube_state_contains_operational_metadata_but_no_credentials(self):
        self.enable_youtube_karaoke()
        snapshot = self.redis_state()
        serialized = json.dumps(snapshot)

        self.assertEqual("playlist-1", snapshot["youtube_karaoke"]["playlist_id"])
        self.assertNotIn("test-api-key", serialized)
        self.assertNotIn("test-client-secret", serialized)
        self.assertNotIn("test-refresh-token", serialized)

    def test_schema_versions_one_through_five_upgrade_karaoke_workflow_to_v6(self):
        for schema_version in range(1, 6):
            with self.subTest(schema_version=schema_version):
                self.reset_state()
                snapshot = main.snapshot_state()
                snapshot["schema_version"] = schema_version
                snapshot.pop("youtube_karaoke", None)
                snapshot["karaoke_signups"] = [
                    {
                        "id": "legacy-karaoke",
                        "name": "Legacy Singer",
                        "song_title": "Monster Mash",
                        "artist": "Bobby Pickett",
                        "youtube_link": "https://youtu.be/abc123DEF45",
                    }
                ]
                self.fake_redis.set(main.redis_key("state"), json.dumps(snapshot))

                self.assertTrue(main.load_state_from_redis())
                migrated = main.karaoke_signups[0]
                self.assertEqual("legacy-karaoke", migrated.id)
                self.assertEqual("abc123DEF45", migrated.youtube["video_id"])
                self.assertEqual("pending", migrated.workflow["video_validation_status"])
                self.assertEqual("pending", migrated.workflow["approval_status"])
                self.assertEqual("not_started", migrated.workflow["playlist_sync_status"])
                main.save_state_to_redis()
                self.assertEqual(main.STATE_SCHEMA_VERSION, self.redis_state()["schema_version"])

    def test_youtube_search_budget_blocks_new_uncached_queries_at_configured_limit(self):
        self.enable_youtube_karaoke()
        main.app.config["YOUTUBE_SEARCH_DAILY_BUDGET"] = 1

        first = main.search_youtube_karaoke(
            "thriller",
            page_token="",
            user_id="user-1",
        )

        self.assertFalse(first["cached"])
        with self.assertRaises(main.YouTubeApiError) as error:
            main.search_youtube_karaoke(
                "monster mash",
                page_token="",
                user_id="user-1",
            )
        self.assertEqual("search_budget_exhausted", error.exception.code)

    def test_admin_can_create_select_and_test_owned_youtube_playlist(self):
        fake_youtube = self.enable_youtube_karaoke()

        with main.app.test_client() as admin:
            self.login_admin(admin)
            created = admin.post(
                "/api/admin/karaoke/youtube/playlist/create",
                data={"title": "Private Rehearsal", "privacy": "private"},
            )
            selected = admin.post(
                "/api/admin/karaoke/youtube/playlist",
                data={"playlist_id": "playlist-1"},
            )
            tested = admin.post("/api/admin/karaoke/youtube/test")

        self.assertEqual(200, created.status_code)
        self.assertIn("Private Rehearsal", created.get_json()["message"])
        self.assertEqual(200, selected.status_code)
        self.assertEqual(200, tested.status_code)
        self.assertEqual("playlist-1", main.youtube_karaoke["playlist_id"])
        self.assertEqual(fake_youtube.channel["channel_id"], main.youtube_karaoke["channel_id"])
        self.assertTrue(main.youtube_karaoke["last_connection_check_at"])

    def test_admin_replacement_inserts_new_revision_before_removing_old_item(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as admin:
            self.login_admin(admin)
            self.assertEqual(
                200,
                admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve").status_code,
            )
            old_item_id = main.find_karaoke_signup(entry_id).workflow["playlist_item_id"]
            response = admin.post(
                f"/api/admin/karaoke/entries/{entry_id}/replace",
                data={"youtube_link": "https://www.youtube.com/watch?v=abc123DEF46"},
            )

        self.assertEqual(200, response.status_code)
        signup = main.find_karaoke_signup(entry_id)
        self.assertEqual(2, signup.workflow["playlist_revision"])
        self.assertEqual("abc123DEF46", signup.youtube["video_id"])
        self.assertEqual("synced", signup.workflow["playlist_sync_status"])
        self.assertNotEqual(old_item_id, signup.workflow["playlist_item_id"])
        self.assertEqual([old_item_id], fake_youtube.delete_calls)
        self.assertEqual(2, len(fake_youtube.insert_calls))

    def test_admin_removal_deletes_only_known_playlist_item_and_cancels_entry(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as admin:
            self.login_admin(admin)
            admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve")
            playlist_item_id = main.find_karaoke_signup(entry_id).workflow["playlist_item_id"]
            response = admin.post(f"/api/admin/karaoke/entries/{entry_id}/remove")

        self.assertEqual(200, response.status_code)
        signup = main.find_karaoke_signup(entry_id)
        self.assertEqual("cancelled", signup.workflow["approval_status"])
        self.assertEqual("removed", signup.workflow["playlist_sync_status"])
        self.assertEqual([playlist_item_id], fake_youtube.delete_calls)
        self.assertEqual([], main.public_karaoke_signups())

    def test_admin_bulk_clear_backs_up_and_removes_only_app_managed_items(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
            self.submit_youtube_karaoke_request(attendee, video_id="abc123DEF46")
        entry_ids = [signup.id for signup in main.karaoke_signups]

        with main.app.test_client() as admin:
            self.login_admin(admin)
            for entry_id in entry_ids:
                self.assertEqual(
                    200,
                    admin.post(
                        f"/api/admin/karaoke/entries/{entry_id}/approve"
                    ).status_code,
                )

            managed_item_ids = [
                signup.workflow["playlist_item_id"]
                for signup in main.karaoke_signups
            ]
            fake_youtube.playlist_items.append(
                {
                    "playlist_item_id": "foreign-playlist-item",
                    "video_id": "foreign12345",
                    "position": 2,
                    "note": "",
                }
            )
            main.karaoke_signups[0].workflow["performance_status"] = "completed"
            main.karaoke_state["party_started"] = True
            main.karaoke_state["current_singer_id"] = entry_ids[1]
            main.karaoke_state["stage_mode"] = "on_stage"
            main.live_display_event_override = {
                "type": "karaoke_on_stage",
                "title": "Now Singing",
            }
            self.save_current_state()

            response = admin.post(
                "/api/admin/karaoke/reset",
                data={
                    "mode": "combined",
                    "confirm_phrase": "CLEAR KARAOKE",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual([], main.karaoke_signups)
        self.assertFalse(main.karaoke_state["party_started"])
        self.assertIsNone(main.karaoke_state["current_singer_id"])
        self.assertIsNone(main.live_display_event_override)
        self.assertEqual(
            sorted(managed_item_ids),
            sorted(fake_youtube.delete_calls),
        )
        self.assertEqual(
            ["foreign-playlist-item"],
            [
                item["playlist_item_id"]
                for item in fake_youtube.playlist_items
            ],
        )
        self.assertEqual("playlist-1", main.youtube_karaoke["playlist_id"])
        clear_operation = main.normalized_karaoke_clear_operation()
        self.assertEqual("completed", clear_operation["status"])
        self.assertEqual(2, clear_operation["record_count"])
        self.assertEqual(2, clear_operation["deleted_count"])
        backup_keys = [
            key
            for key in self.fake_redis.store
            if key.startswith(main.redis_key("state:backup:"))
        ]
        self.assertEqual(1, len(backup_keys))
        backup = json.loads(self.fake_redis.store[backup_keys[0]])
        self.assertEqual("karaoke-clear", backup["backup_reason"])
        self.assertEqual(2, len(backup["karaoke_signups"]))

    def test_schema_six_snapshot_migrates_to_disabled_games_state(self):
        snapshot = main.snapshot_state()
        snapshot["schema_version"] = 6
        snapshot.pop("games_state", None)
        self.fake_redis.set(main.redis_key("state"), json.dumps(snapshot))

        self.assertTrue(main.load_state_from_redis())

        game = main.two_truths_game()
        self.assertFalse(game["enabled"])
        self.assertEqual("signup", game["phase"])
        self.assertEqual({}, game["participants"])
        main.save_state_to_redis()
        self.assertEqual(12, self.redis_state()["schema_version"])
        self.assertIn("games_state", self.redis_state())
        self.assertEqual(
            {
                "two_truths_and_a_lie",
                "murder_marry_fuck",
                "fill_in_the_blank",
                "bad_advice_hotline",
                "wrong_answers_only",
            },
            set(self.redis_state()["games_state"]),
        )

    def test_two_truths_enrollment_is_persisted_and_live_display_is_anonymous(self):
        with main.app.test_client() as admin:
            self.login_admin(admin)
            enabled = admin.post("/admin/games", data={"action": "enable_two_truths_game"})
        self.assertEqual(200, enabled.status_code)

        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="user-1", username="Jamie")
            page = attendee.get("/party/games")
            submitted = attendee.post(
                "/party/games/two-truths-and-a-lie/submission",
                data={
                    "truth_one": "I have climbed a volcano.",
                    "truth_two": "I can juggle.",
                    "lie": "I have never seen a horror movie.",
                },
            )

        self.assertEqual(200, page.status_code)
        self.assertEqual(302, submitted.status_code)
        game = main.two_truths_game()
        self.assertIn("user-1", game["participants"])
        self.assertEqual("Jamie", game["participants"]["user-1"]["answer_name"])
        self.assertEqual(
            [0, 1, 2],
            sorted(game["participants"]["user-1"]["display_order"]),
        )

        with main.app.test_client() as admin:
            self.login_admin(admin)
            payload = admin.get("/api/display-data").get_json()
        game_entry = next(
            entry
            for entry in payload["layout"]["games"]["entries"]
            if entry["game_key"] == main.TWO_TRUTHS_GAME_KEY and entry["status_label"] == "Mystery clue"
        )
        self.assertNotIn("Jamie", json.dumps(game_entry))
        self.assertNotIn("answer_name", json.dumps(game_entry))
        self.assertNotIn('"lie":', json.dumps(game_entry).lower())
        self.assertNotIn('"truths":', json.dumps(game_entry).lower())

    def test_two_truths_lifecycle_guess_scoring_ties_overrides_export_and_reset(self):
        with main.app.test_client() as admin:
            self.login_admin(admin)
            admin.post("/admin/games", data={"action": "enable_two_truths_game"})

        participants = [
            ("user-1", "Jamie", "I own a kayak.", "I speak French.", "I dislike candy."),
            ("user-2", "Morgan", "I met a president.", "I bake bread.", "I fear pumpkins."),
        ]
        submission_ids = {}
        for user_id, username, truth_one, truth_two, lie in participants:
            with main.app.test_client() as attendee:
                self.login_regular(attendee, user_id=user_id, username=username)
                response = attendee.post(
                    "/party/games/two-truths-and-a-lie/submission",
                    data={"truth_one": truth_one, "truth_two": truth_two, "lie": lie},
                )
                self.assertEqual(302, response.status_code)
            submission_ids[user_id] = main.two_truths_game()["participants"][user_id]["submission_id"]

        with main.app.test_client() as admin:
            self.login_admin(admin)
            started = admin.post("/admin/games", data={"action": "start_two_truths_game"})
        self.assertEqual(200, started.status_code)
        self.assertEqual("active", main.two_truths_game()["phase"])

        with main.app.test_client() as jamie:
            self.login_regular(jamie, user_id="user-1", username="Jamie")
            active_page = jamie.get("/party/games")
            self.assertNotIn(b"Morgan", active_page.data)
            guessed = jamie.post(
                f"/party/games/two-truths-and-a-lie/guesses/{submission_ids['user-2']}",
                data={"guessed_name": "  MORGAN  "},
            )
            self.assertEqual(302, guessed.status_code)

        with main.app.test_client() as morgan:
            self.login_regular(morgan, user_id="user-2", username="Morgan")
            guessed = morgan.post(
                f"/party/games/two-truths-and-a-lie/guesses/{submission_ids['user-1']}",
                data={"guessed_name": "jamie"},
            )
            self.assertEqual(302, guessed.status_code)

        with main.app.test_client() as admin:
            self.login_admin(admin)
            ended = admin.post("/admin/games", data={"action": "end_two_truths_game"})
            exported = admin.get("/admin/export/games")
            winner_override = admin.post("/admin/games", data={"action": "show_two_truths_winner"})
            self.assertEqual("game_winner", main.live_display_event_override["type"])
            results_override = admin.post("/admin/games", data={"action": "show_two_truths_results"})
            self.assertEqual("game_results", main.live_display_event_override["type"])
            resumed = admin.post("/admin/games", data={"action": "resume_game_display"})

        self.assertEqual(200, ended.status_code)
        self.assertEqual(200, exported.status_code)
        self.assertEqual(200, winner_override.status_code)
        self.assertEqual(200, results_override.status_code)
        self.assertEqual(200, resumed.status_code)
        self.assertIsNone(main.live_display_event_override)
        game = main.two_truths_game()
        self.assertEqual("ended", game["phase"])
        self.assertEqual({"user-1", "user-2"}, set(game["results"]["winner_ids"]))
        self.assertTrue(all(score["correct"] == 1 for score in game["results"]["scores"]))
        self.assertIn(b'"games_state"', exported.data)

        entries = main.build_rotation_entries()
        self.assertTrue(any(entry["category"].startswith("Two Truths and a Lie Winner") for entry in entries))
        self.assertTrue(any(entry.get("primary") == "Final Scores" for entry in entries))

        with main.app.test_client() as admin:
            self.login_admin(admin)
            reset = admin.post(
                "/admin/games",
                data={
                    "action": "reset_two_truths_game",
                    "confirmation": "RESET TWO TRUTHS AND A LIE",
                },
            )
        self.assertEqual(200, reset.status_code)
        self.assertTrue(main.two_truths_game()["enabled"])
        self.assertEqual({}, main.two_truths_game()["participants"])
        self.assertEqual({}, main.two_truths_game()["guesses"])

    def test_admin_can_simulate_every_game_and_generate_result_cards(self):
        for game_key in main.GAME_CATALOG:
            with self.subTest(game_key=game_key):
                self.reset_state()
                game = main.party_game_state(game_key)
                if game_key == main.MURDER_MARRY_FUCK_GAME_KEY:
                    game["explicit_label"] = "Choose"
                elif game_key in main.PROMPT_GAME_KEYS:
                    game["prompts"][0]["text"] = "Custom simulation prompt ___" if game_key == main.FILL_BLANK_GAME_KEY else "Custom simulation prompt"
                    if game_key == main.WRONG_ANSWERS_GAME_KEY:
                        for prompt in game["prompts"]:
                            prompt["enabled"] = False
                self.save_current_state()

                with main.app.test_client() as admin:
                    self.login_admin(admin)
                    response = admin.post(
                        "/admin/games",
                        data={"action": "simulate_game", "game_key": game_key, "player_count": "6"},
                    )
                    display_page = admin.get("/admin/display")

                self.assertEqual(200, response.status_code)
                self.assertIn("Simulated", response.get_data(as_text=True))
                game = main.party_game_state(game_key)
                self.assertTrue(game["enabled"])
                self.assertEqual("ended", game["phase"])
                self.assertEqual(6, len(game["participants"]))
                self.assertEqual(
                    {"is_simulated": True, "player_count": 6, "generated_at": game["ended_at"]},
                    game["simulation"],
                )
                self.assertTrue(game["results"]["scores"])
                self.assertTrue(main.game_winners(game_key, game))
                if game_key == main.MURDER_MARRY_FUCK_GAME_KEY:
                    self.assertEqual("Choose", game["explicit_label"])
                elif game_key in main.PROMPT_GAME_KEYS:
                    self.assertTrue(game["prompts"][0]["text"].startswith("Custom simulation prompt"))
                    if game_key == main.WRONG_ANSWERS_GAME_KEY:
                        self.assertFalse(any(prompt["enabled"] for prompt in game["prompts"]))

                cards = main.generated_game_result_entries(include_hidden=True)
                card_ids = {entry["id"] for entry in cards}
                winner_card = next(entry for entry in cards if entry["id"] == f"games:{game_key}-winner")
                self.assertIn(f"games:{game_key}-winner", card_ids)
                self.assertIn(f"games:{game_key}-scores", card_ids)
                self.assertEqual("result", winner_card["kind"])
                self.assertEqual(3, len(winner_card["facts"]))
                self.assertTrue(winner_card["scoreboard"]["entries"])
                self.assertLessEqual(len(winner_card["scoreboard"]["entries"]), 3)
                self.assertIn(b"Generated Game Result Cards", display_page.data)
                self.assertIn(f"games:{game_key}-winner".encode(), display_page.data)
                persisted = self.redis_state()
                self.assertEqual(12, persisted["schema_version"])
                self.assertTrue(persisted["games_state"][game_key]["simulation"]["is_simulated"])
                self.assertEqual({}, persisted["user_accounts"])

    def test_simulation_refuses_to_replace_real_players(self):
        game = main.party_game_state(main.FILL_BLANK_GAME_KEY)
        game["participants"]["real-user"] = {
            "player_id": "real-player",
            "alias": "Real Alias",
            "created_at": "",
            "updated_at": "",
        }
        self.save_current_state()

        with main.app.test_client() as admin:
            self.login_admin(admin)
            response = admin.post(
                "/admin/games",
                data={"action": "simulate_game", "game_key": main.FILL_BLANK_GAME_KEY, "player_count": "8"},
            )

        self.assertEqual(200, response.status_code)
        self.assertIn("Reset Fill in the Blank", response.get_data(as_text=True))
        self.assertEqual({"real-user"}, set(main.party_game_state(main.FILL_BLANK_GAME_KEY)["participants"]))
        self.assertFalse(main.party_game_state(main.FILL_BLANK_GAME_KEY)["simulation"]["is_simulated"])

    def test_generated_game_cards_survive_disable_and_can_be_hidden_or_pinned(self):
        game_key = main.BAD_ADVICE_GAME_KEY
        main.games_state[game_key] = main.build_simulated_game_state(
            game_key,
            main.party_game_state(game_key),
            player_count=5,
            generated_at="2026-08-13T12:00:00Z",
        )
        main.party_game_state(game_key)["enabled"] = False
        self.save_current_state()
        winner_id = f"games:{game_key}-winner"

        self.assertIn(winner_id, {entry["id"] for entry in main.build_rotation_entries()})
        with main.app.test_client() as admin:
            self.login_admin(admin)
            hidden = admin.post(
                "/admin/display",
                data={"action": "toggle_game_result_card", "card_id": winner_id},
            )
            self.assertNotIn(winner_id, {entry["id"] for entry in main.build_rotation_entries()})
            shown = admin.post(
                "/admin/display",
                data={"action": "show_game_result_card", "card_id": winner_id},
            )

        self.assertEqual(200, hidden.status_code)
        self.assertEqual(200, shown.status_code)
        self.assertTrue(main.display_config["game_result_card_enabled"][winner_id])
        self.assertTrue(main.display_config["source_enabled"]["games"])
        self.assertEqual(winner_id, main.display_runtime["pinned_card_id"])
        self.assertTrue(main.display_runtime["center_paused"])

    def test_ended_game_without_positive_score_gets_no_winner_outcome_card(self):
        game = main.two_truths_game()
        game.update(
            main.build_simulated_game_state(
                main.TWO_TRUTHS_GAME_KEY,
                game,
                player_count=2,
                generated_at="2026-08-13T12:00:00Z",
            )
        )
        game["guesses"] = {}
        game["results"] = main.calculate_two_truths_results(game, finalized_at=game["ended_at"])

        outcome = main.game_outcome_entry(main.TWO_TRUTHS_GAME_KEY)
        self.assertEqual("No Winner This Round", outcome["primary"])
        self.assertIn(
            f"games:{main.TWO_TRUTHS_GAME_KEY}-winner",
            {entry["id"] for entry in main.generated_game_result_entries()},
        )

    def test_two_truths_routes_require_role_phase_and_participation(self):
        main.two_truths_game()["enabled"] = True
        self.save_current_state()

        with main.app.test_client() as anonymous:
            self.assertEqual(302, anonymous.get("/party/games").status_code)

        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="user-1", username="Jamie")
            self.assertEqual(
                302,
                attendee.post(
                    "/party/games/two-truths-and-a-lie/submission",
                    data={"truth_one": "Same", "truth_two": " same ", "lie": "Different"},
                ).status_code,
            )
            game = main.two_truths_game()
            self.assertEqual({}, game["participants"])
            game["phase"] = "active"
            self.save_current_state()
            blocked = attendee.post(
                "/party/games/two-truths-and-a-lie/guesses/not-found",
                data={"guessed_name": "Morgan"},
            )
            self.assertEqual(302, blocked.status_code)
            self.assertEqual({}, main.two_truths_game()["guesses"])

    def test_admin_controls_game_anonymity_during_signup(self):
        game_key = main.FILL_BLANK_GAME_KEY
        slug = main.GAME_CATALOG[game_key]["slug"]
        main.party_game_state(game_key)["enabled"] = True
        self.save_current_state()

        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="user-1", username="Jamie")
            joined = attendee.post(f"/party/games/{slug}/join")
            named_page = attendee.get(f"/party/games?game={slug}")

        participant = main.party_game_state(game_key)["participants"]["user-1"]
        alias = participant["alias"]
        self.assertFalse(main.party_game_state(game_key)["anonymous_mode"])
        self.assertEqual("Jamie", participant["display_name"])
        self.assertEqual("Jamie", main.participant_public_name(participant, anonymous=False))
        self.assertIn(b"You\xe2\x80\x99re in as Jamie", named_page.data)
        self.assertNotIn(b"play_anonymously", named_page.data)

        with main.app.test_client() as admin:
            self.login_admin(admin)
            admin_page = admin.get(f"/admin/games?game={game_key}")
            changed = admin.post(
                "/admin/games",
                data={"action": "toggle_game_anonymity", "game_key": game_key},
            )

        self.assertIn(b"Signed-in names", admin_page.data)
        self.assertIn(b"Use Anonymous Aliases", admin_page.data)
        self.assertEqual(200, changed.status_code)
        self.assertTrue(main.party_game_state(game_key)["anonymous_mode"])

        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="user-1", username="Jamie")
            anonymous_page = attendee.get(f"/party/games?game={slug}")
        self.assertIn(alias.encode(), anonymous_page.data)

        main.party_game_state(game_key)["phase"] = "active"
        self.save_current_state()
        with main.app.test_client() as admin:
            self.login_admin(admin)
            locked = admin.post(
                "/admin/games",
                data={"action": "toggle_game_anonymity", "game_key": game_key},
            )

        self.assertEqual(302, joined.status_code)
        self.assertEqual(200, locked.status_code)
        self.assertIn(b"only be changed while enrollment is open", locked.data)
        self.assertTrue(main.party_game_state(game_key)["anonymous_mode"])

    def test_schema_eleven_game_participants_backfill_names_for_admin_default_mode(self):
        raw = main.empty_prompt_game_state(main.BAD_ADVICE_GAME_KEY, enabled=True)
        raw["participants"] = {
            "legacy-user": {
                "player_id": "legacy-player",
                "alias": "Legacy Ghost",
                "created_at": "",
                "updated_at": "",
            }
        }

        snapshot = main.snapshot_state()
        snapshot["schema_version"] = 11
        snapshot["registered_users"] = {"legacy-user": "Legacy Guest"}
        snapshot["games_state"][main.BAD_ADVICE_GAME_KEY] = raw
        main.apply_state_snapshot(snapshot)
        participant = main.party_game_state(main.BAD_ADVICE_GAME_KEY)["participants"]["legacy-user"]

        self.assertEqual("Legacy Guest", participant["display_name"])
        self.assertFalse(main.party_game_state(main.BAD_ADVICE_GAME_KEY)["anonymous_mode"])
        self.assertEqual("Legacy Guest", main.participant_public_name(participant, anonymous=False))

    def test_mmf_admin_anonymous_lifecycle_scoring_presentation_export_and_reset(self):
        game_key = main.MURDER_MARRY_FUCK_GAME_KEY
        slug = main.GAME_CATALOG[game_key]["slug"]
        with main.app.test_client() as admin:
            self.login_admin(admin)
            enabled = admin.post("/admin/games", data={"action": "enable_game", "game_key": game_key})
            anonymous = admin.post("/admin/games", data={"action": "toggle_game_anonymity", "game_key": game_key})
        self.assertEqual(200, enabled.status_code)
        self.assertEqual(200, anonymous.status_code)
        self.assertTrue(main.party_game_state(game_key)["anonymous_mode"])

        aliases = {}
        for user_id, username in (("user-1", "Jamie"), ("user-2", "Morgan")):
            with main.app.test_client() as attendee:
                self.login_regular(attendee, user_id=user_id, username=username)
                joined = attendee.post(f"/party/games/{slug}/join")
            self.assertEqual(302, joined.status_code)
            aliases[user_id] = main.party_game_state(game_key)["participants"][user_id]["alias"]
        self.assertNotEqual(aliases["user-1"], aliases["user-2"])

        with main.app.test_client() as admin:
            self.login_admin(admin)
            started = admin.post("/admin/games", data={"action": "start_game", "game_key": game_key})
        self.assertEqual(200, started.status_code)
        self.assertEqual("active", main.party_game_state(game_key)["phase"])

        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="user-1", username="Jamie")
            active_page = attendee.get(f"/party/games?game={slug}")
        self.assertEqual(200, active_page.status_code)
        self.assertIn(b"Round 10", active_page.data)

        for user_id, username in (("user-1", "Jamie"), ("user-2", "Morgan")):
            with main.app.test_client() as attendee:
                self.login_regular(attendee, user_id=user_id, username=username)
                for game_round in main.party_game_state(game_key)["rounds"]:
                    person_ids = [person["id"] for person in game_round["people"]]
                    saved = attendee.post(
                        "/party/games/murder-marry-fuck/answers",
                        data={
                            "round_id": game_round["id"],
                            "murder": person_ids[0],
                            "marry": person_ids[1],
                            "fuck": person_ids[2],
                        },
                    )
                    self.assertEqual(302, saved.status_code)

        with main.app.test_client() as admin:
            self.login_admin(admin)
            ended = admin.post("/admin/games", data={"action": "end_game", "game_key": game_key})
            presentation = admin.post("/admin/games", data={"action": "start_game_presentation", "game_key": game_key})
            next_slide = admin.post("/admin/games", data={"action": "next_game_slide", "game_key": game_key})
            exported = json.loads(admin.get("/admin/export/games").data)
        self.assertEqual(200, ended.status_code)
        self.assertEqual(200, presentation.status_code)
        self.assertEqual(200, next_slide.status_code)
        game = main.party_game_state(game_key)
        self.assertEqual("ended", game["phase"])
        self.assertEqual(2, len(game["results"]["winner_player_ids"]))
        self.assertTrue(all(score["points"] == 30 for score in game["results"]["scores"]))
        self.assertEqual(set(aliases.values()), {score["name"] for score in game["results"]["scores"]})
        public_result_text = json.dumps(
            {
                "scoreboard": main.game_scoreboard_entry(game_key),
                "winner": main.game_winner_entry(game_key),
                "stage": [entry for entry in main.build_game_stage_entries() if entry.get("game_key") == game_key],
            }
        )
        self.assertNotIn("Jamie", public_result_text)
        self.assertIn(aliases["user-2"], public_result_text)
        self.assertNotIn("Morgan", public_result_text)
        self.assertEqual("game_presentation", main.live_display_event_override["type"])
        self.assertEqual(1, game["presentation"]["slide_index"])
        exported_mmf = exported["games_state"][game_key]
        self.assertIsInstance(exported_mmf["participants"], list)
        self.assertNotIn("user-1", json.dumps(exported_mmf))
        self.assertNotIn("user-2", json.dumps(exported_mmf))
        self.assertNotIn("Jamie", json.dumps(exported_mmf))
        self.assertNotIn("Morgan", json.dumps(exported_mmf))
        self.assertIn(aliases["user-2"], json.dumps(exported_mmf))
        self.assertNotIn("answers", json.dumps(exported_mmf))

        with main.app.test_client() as admin:
            self.login_admin(admin)
            reset = admin.post("/admin/games", data={"action": "reset_game", "game_key": game_key, "confirmation": "RESET MURDER MARRY FUCK"})
        self.assertEqual(200, reset.status_code)
        self.assertTrue(main.party_game_state(game_key)["enabled"])
        self.assertFalse(main.party_game_state(game_key)["anonymous_mode"])
        self.assertEqual({}, main.party_game_state(game_key)["participants"])
        self.assertEqual(10, len(main.party_game_state(game_key)["rounds"]))

    def test_prompt_games_share_anonymous_response_vote_and_result_engine(self):
        for game_key in main.PROMPT_GAME_KEYS:
            with self.subTest(game_key=game_key):
                self.reset_state()
                slug = main.GAME_CATALOG[game_key]["slug"]
                with main.app.test_client() as admin:
                    self.login_admin(admin)
                    admin.post("/admin/games", data={"action": "enable_game", "game_key": game_key})
                for user_id, username in (("user-1", "Jamie"), ("user-2", "Morgan")):
                    with main.app.test_client() as attendee:
                        self.login_regular(attendee, user_id=user_id, username=username)
                        self.assertEqual(302, attendee.post(f"/party/games/{slug}/join").status_code)
                game = main.party_game_state(game_key)
                prompt_id = game["prompts"][0]["id"]
                with main.app.test_client() as admin:
                    self.login_admin(admin)
                    admin.post("/admin/games", data={"action": "start_game", "game_key": game_key})
                    opened = admin.post("/admin/games", data={"action": "start_prompt_round", "game_key": game_key, "prompt_id": prompt_id})
                self.assertEqual(200, opened.status_code)

                with main.app.test_client() as attendee:
                    self.login_regular(attendee, user_id="user-1", username="Jamie")
                    response_page = attendee.get(f"/party/games?game={slug}")
                self.assertEqual(200, response_page.status_code)
                self.assertIn(b"Responses open", response_page.data)

                response_ids = {}
                for user_id, username, answer in (("user-1", "Jamie", "A haunted fax machine"), ("user-2", "Morgan", "Three raccoons in a trench coat")):
                    with main.app.test_client() as attendee:
                        self.login_regular(attendee, user_id=user_id, username=username)
                        submitted = attendee.post(f"/party/games/{slug}/response", data={"response": answer})
                    self.assertEqual(302, submitted.status_code)
                    player_id = main.party_game_state(game_key)["participants"][user_id]["player_id"]
                    current = main.prompt_round_for_game(main.party_game_state(game_key))
                    response_ids[user_id] = next(response_id for response_id, response in current["responses"].items() if response["player_id"] == player_id)

                with main.app.test_client() as admin:
                    self.login_admin(admin)
                    voting = admin.post("/admin/games", data={"action": "open_prompt_voting", "game_key": game_key})
                    display_payload = admin.get("/api/display-data").get_json()
                self.assertEqual(200, voting.status_code)
                current_game_entries = [
                    entry
                    for entry in display_payload["layout"]["games"]["entries"]
                    if entry.get("game_key") == game_key
                ]
                display_text = json.dumps(current_game_entries)
                self.assertIn("A haunted fax machine", display_text)
                self.assertNotIn("Jamie", display_text)
                with main.app.test_client() as attendee:
                    self.login_regular(attendee, user_id="user-1", username="Jamie")
                    voting_page = attendee.get(f"/party/games?game={slug}")
                self.assertEqual(200, voting_page.status_code)
                self.assertIn(b"Voting open", voting_page.data)

                for user_id, username, target_id in (("user-1", "Jamie", response_ids["user-2"]), ("user-2", "Morgan", response_ids["user-1"])):
                    with main.app.test_client() as attendee:
                        self.login_regular(attendee, user_id=user_id, username=username)
                        voted = attendee.post(f"/party/games/{slug}/vote", data={"response_id": target_id})
                    self.assertEqual(302, voted.status_code)

                with main.app.test_client() as admin:
                    self.login_admin(admin)
                    revealed = admin.post("/admin/games", data={"action": "reveal_prompt_round", "game_key": game_key})
                    ended = admin.post("/admin/games", data={"action": "end_game", "game_key": game_key})
                    presented = admin.post("/admin/games", data={"action": "start_game_presentation", "game_key": game_key})
                self.assertEqual(200, revealed.status_code)
                self.assertEqual(200, ended.status_code)
                self.assertEqual(200, presented.status_code)
                game = main.party_game_state(game_key)
                self.assertEqual("ended", game["phase"])
                self.assertEqual(2, len(game["results"]["winner_player_ids"]))
                self.assertTrue(all(score["points"] == 1 for score in game["results"]["scores"]))
                self.assertEqual({"Jamie", "Morgan"}, {score["name"] for score in game["results"]["scores"]})
                self.assertEqual("game_presentation", main.live_display_event_override["type"])

    def test_single_player_games_start_and_score_without_peer_votes(self):
        game_key = main.MURDER_MARRY_FUCK_GAME_KEY
        slug = main.GAME_CATALOG[game_key]["slug"]
        with main.app.test_client() as admin:
            self.login_admin(admin)
            admin.post("/admin/games", data={"action": "enable_game", "game_key": game_key})
        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="solo-user", username="Solo")
            attendee.post(f"/party/games/{slug}/join")
        with main.app.test_client() as admin:
            self.login_admin(admin)
            started = admin.post("/admin/games", data={"action": "start_game", "game_key": game_key})
        self.assertEqual(200, started.status_code)
        self.assertEqual("active", main.party_game_state(game_key)["phase"])

        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="solo-user", username="Solo")
            for game_round in main.party_game_state(game_key)["rounds"]:
                people = [person["id"] for person in game_round["people"]]
                attendee.post(
                    "/party/games/murder-marry-fuck/answers",
                    data={"round_id": game_round["id"], "murder": people[0], "marry": people[1], "fuck": people[2]},
                )
        with main.app.test_client() as admin:
            self.login_admin(admin)
            admin.post("/admin/games", data={"action": "end_game", "game_key": game_key})
        mmf_results = main.party_game_state(game_key)["results"]
        self.assertEqual(30, mmf_results["scores"][0]["points"])
        self.assertEqual(1, len(mmf_results["winner_player_ids"]))

        for game_key in main.PROMPT_GAME_KEYS:
            with self.subTest(game_key=game_key):
                self.reset_state()
                slug = main.GAME_CATALOG[game_key]["slug"]
                with main.app.test_client() as admin:
                    self.login_admin(admin)
                    admin.post("/admin/games", data={"action": "enable_game", "game_key": game_key})
                with main.app.test_client() as attendee:
                    self.login_regular(attendee, user_id="solo-user", username="Solo")
                    attendee.post(f"/party/games/{slug}/join")
                game = main.party_game_state(game_key)
                with main.app.test_client() as admin:
                    self.login_admin(admin)
                    admin.post("/admin/games", data={"action": "start_game", "game_key": game_key})
                    admin.post("/admin/games", data={"action": "start_prompt_round", "game_key": game_key, "prompt_id": game["prompts"][0]["id"]})
                with main.app.test_client() as attendee:
                    self.login_regular(attendee, user_id="solo-user", username="Solo")
                    attendee.post(f"/party/games/{slug}/response", data={"response": "A beautifully terrible solo answer"})
                with main.app.test_client() as admin:
                    self.login_admin(admin)
                    revealed = admin.post("/admin/games", data={"action": "open_prompt_voting", "game_key": game_key})
                    admin.post("/admin/games", data={"action": "end_game", "game_key": game_key})
                self.assertEqual(200, revealed.status_code)
                game = main.party_game_state(game_key)
                self.assertTrue(game["rounds"][0]["results"]["solo_spotlight"])
                self.assertEqual(1, game["results"]["scores"][0]["points"])
                self.assertEqual(1, len(game["results"]["winner_player_ids"]))
                self.assertIn("Solo spotlight", json.dumps(main.build_game_presentation_slides(game_key)))

    def test_two_truths_still_requires_two_players_and_game_ui_is_unified(self):
        main.two_truths_game()["enabled"] = True
        participant = main.empty_two_truths_game_state()["participants"]
        main.two_truths_game()["participants"] = participant
        main.two_truths_game()["participants"]["user-1"] = {
            "user_id": "user-1", "submission_id": "solo", "answer_name": "Solo",
            "truths": ["One", "Two"], "lie": "Three", "display_order": [0, 1, 2],
            "created_at": "", "updated_at": "",
        }
        with main.app.test_client() as admin:
            self.login_admin(admin)
            response = admin.post("/admin/games", data={"action": "start_two_truths_game"})
            page = admin.get("/admin/games")
        self.assertEqual(200, response.status_code)
        self.assertEqual("signup", main.two_truths_game()["phase"])
        self.assertIn(b"Choose one game to operate", page.data)
        self.assertNotIn(b"Additional Games", page.data)
        self.assertEqual(5, page.data.count(b'data-view-key="game-selector:'))
        self.assertEqual(1, page.data.count(b'class="game-admin-card game-admin-card--selected"'))
        self.assertIn(b'id="admin-game-two_truths_and_a_lie"', page.data)
        self.assertIn(b'data-admin-inline="true"', page.data)
        self.assertIn(b"preserve-scroll.js", page.data)
        with main.app.test_client() as admin:
            self.login_admin(admin)
            selected = admin.get("/admin/games?game=fill_in_the_blank")
            invalid = admin.get("/admin/games?game=not-a-game")
            updated = admin.post(
                "/admin/games?game=fill_in_the_blank",
                data={"action": "enable_game", "game_key": main.FILL_BLANK_GAME_KEY},
            )
        self.assertIn(b'id="admin-game-fill_in_the_blank"', selected.data)
        self.assertNotIn(b'id="admin-game-two_truths_and_a_lie"', selected.data)
        self.assertIn(b'id="admin-game-two_truths_and_a_lie"', invalid.data)
        self.assertIn(b'id="admin-game-fill_in_the_blank"', updated.data)
        self.assertIn(b"Disable", updated.data)
        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="user-1", username="Solo")
            dashboard = attendee.get("/party")
        self.assertIn(b"/static/images/games/two-truths-and-a-lie.jpg", dashboard.data)
        self.assertLess(dashboard.data.index(b"signup-callout"), dashboard.data.index(b"games-showcase"))
        self.assertLess(dashboard.data.index(b"games-showcase"), dashboard.data.index(b"jukebox-overview"))

    def test_new_game_routes_reject_invalid_assignments_and_self_votes(self):
        mmf = main.party_game_state(main.MURDER_MARRY_FUCK_GAME_KEY)
        mmf["enabled"] = True
        mmf["phase"] = "active"
        participant = main.add_alias_participant(mmf, "user-1")
        self.save_current_state()
        game_round = mmf["rounds"][0]
        duplicate_person = game_round["people"][0]["id"]
        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="user-1", username="Jamie")
            invalid = attendee.post("/party/games/murder-marry-fuck/answers", data={"round_id": game_round["id"], "murder": duplicate_person, "marry": duplicate_person, "fuck": duplicate_person})
        self.assertEqual(302, invalid.status_code)
        self.assertEqual({}, main.party_game_state(main.MURDER_MARRY_FUCK_GAME_KEY)["participants"]["user-1"].get("answers", {}))

        self.reset_state()
        game = main.party_game_state(main.WRONG_ANSWERS_GAME_KEY)
        game["enabled"] = True
        game["phase"] = "active"
        participant = main.add_alias_participant(game, "user-1")
        game_round = {"id": "round-1", "prompt_id": "prompt-1", "prompt_text": "Wrong?", "status": "voting", "responses": {"response-1": {"id": "response-1", "player_id": participant["player_id"], "text": "Mine", "submitted_at": ""}}, "votes": {}, "results": {}, "created_at": "", "revealed_at": ""}
        game["rounds"] = [game_round]
        game["current_round_id"] = "round-1"
        self.save_current_state()
        with main.app.test_client() as attendee:
            self.login_regular(attendee, user_id="user-1", username="Jamie")
            self_vote = attendee.post("/party/games/wrong-answers-only/vote", data={"response_id": "response-1"})
        self.assertEqual(302, self_vote.status_code)
        self.assertEqual({}, main.prompt_round_for_game(main.party_game_state(main.WRONG_ANSWERS_GAME_KEY))["votes"])

    def test_admin_bulk_clear_requires_exact_confirmation_and_admin(self):
        self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
            unauthorized = attendee.post(
                "/api/admin/karaoke/reset",
                data={
                    "mode": "combined",
                    "confirm_phrase": "CLEAR KARAOKE",
                },
            )

        with main.app.test_client() as admin:
            self.login_admin(admin)
            unconfirmed = admin.post(
                "/api/admin/karaoke/reset",
                data={"mode": "combined", "confirm_phrase": "clear"},
            )

        self.assertEqual(302, unauthorized.status_code)
        self.assertEqual(400, unconfirmed.status_code)
        self.assertEqual(1, len(main.karaoke_signups))

    def test_admin_bulk_clear_partial_failure_is_retriable_and_idempotent(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
            self.submit_youtube_karaoke_request(attendee, video_id="abc123DEF46")
        entry_ids = [signup.id for signup in main.karaoke_signups]

        with main.app.test_client() as admin:
            self.login_admin(admin)
            for entry_id in entry_ids:
                admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve")
            failed_item_id = main.karaoke_signups[1].workflow[
                "playlist_item_id"
            ]
            fake_youtube.fail_delete_ids[failed_item_id] = main.YouTubeApiError(
                "quotaExceeded",
                "The YouTube API quota is exhausted for today.",
                http_status=403,
            )
            first = admin.post(
                "/api/admin/karaoke/reset",
                data={
                    "mode": "combined",
                    "confirm_phrase": "CLEAR KARAOKE",
                },
            )

            self.assertEqual(502, first.status_code)
            self.assertEqual(
                "failed",
                main.normalized_karaoke_clear_operation()["status"],
            )
            self.assertEqual(2, len(main.karaoke_signups))
            self.assertEqual([], main.public_karaoke_signups())

            fake_youtube.fail_delete_ids.clear()
            retry = admin.post(
                "/api/admin/karaoke/reset",
                data={
                    "mode": "combined",
                    "confirm_phrase": "CLEAR KARAOKE",
                },
            )

        self.assertEqual(200, retry.status_code)
        self.assertEqual([], main.karaoke_signups)
        self.assertEqual(
            "completed",
            main.normalized_karaoke_clear_operation()["status"],
        )
        backup_keys = [
            key
            for key in self.fake_redis.store
            if key.startswith(main.redis_key("state:backup:"))
        ]
        self.assertEqual(1, len(backup_keys))

    def test_admin_can_clear_local_lineup_after_youtube_failure(self):
        fake_youtube = self.enable_youtube_karaoke()
        with main.app.test_client() as attendee:
            self.login_regular(attendee)
            self.submit_youtube_karaoke_request(attendee)
        entry_id = main.karaoke_signups[0].id

        with main.app.test_client() as admin:
            self.login_admin(admin)
            admin.post(f"/api/admin/karaoke/entries/{entry_id}/approve")
            playlist_item_id = main.karaoke_signups[0].workflow[
                "playlist_item_id"
            ]
            fake_youtube.fail_delete_ids[playlist_item_id] = (
                main.YouTubeApiError(
                    "playlistItemsNotAccessible",
                    "The selected playlist is not writable.",
                    http_status=403,
                )
            )
            failed = admin.post(
                "/api/admin/karaoke/reset",
                data={
                    "mode": "combined",
                    "confirm_phrase": "CLEAR KARAOKE",
                },
            )
            local = admin.post(
                "/api/admin/karaoke/reset",
                data={
                    "mode": "local",
                    "confirm_phrase": "CLEAR LOCAL KARAOKE",
                },
            )

        self.assertEqual(502, failed.status_code)
        self.assertEqual(200, local.status_code)
        self.assertEqual([], main.karaoke_signups)
        clear_operation = main.normalized_karaoke_clear_operation()
        self.assertEqual("local_only_completed", clear_operation["status"])
        self.assertEqual([playlist_item_id], clear_operation["failed_item_ids"])
        backup_keys = [
            key
            for key in self.fake_redis.store
            if key.startswith(main.redis_key("state:backup:"))
        ]
        self.assertEqual(1, len(backup_keys))
