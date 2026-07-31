from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import List, Tuple
from threading import Condition, Thread
from urllib.parse import quote, quote_plus, unquote, urlencode, urlparse
from urllib.request import Request as UrlRequest, urlopen
from uuid import uuid4
import copy
import hashlib
import io
import json
import os
import random
import re
import secrets
import time

import redis
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from flask import (
    Flask,
    Response,
    abort,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    stream_with_context,
    url_for,
    session,
    g,
)

from youtube_karaoke import (
    VaultYouTubeSecretStore,
    YouTubeApiError,
    YouTubeConfig,
    YouTubeService,
    build_oauth_flow,
    canonical_watch_url,
    parse_youtube_video_id,
)


def _config_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "")
    try:
        return int(raw_value) if raw_value else default
    except ValueError:
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("HALLOWEEN_APP_SECRET", "dev-secret-key")
app.config["ADMIN_PASSWORD"] = os.environ.get("HALLOWEEN_ADMIN_PASSWORD", "")
app.config["PARTY_CODE"] = os.environ.get("HALLOWEEN_PARTY_CODE", "")
app.config["PARTY_TITLE"] = os.environ.get(
    "HALLOWEEN_PARTY_TITLE",
    "Qiana and Tony's 3rd Annual Halloween Party",
)
app.config["PARTY_YEAR"] = os.environ.get("HALLOWEEN_PARTY_YEAR", "2026")
app.config["PARTY_START"] = os.environ.get("HALLOWEEN_PARTY_START", "2026-10-31T19:00:00-06:00")
app.config["PARTY_DATE_LABEL"] = os.environ.get("HALLOWEEN_PARTY_DATE_LABEL", "Saturday, October 31")
app.config["PARTY_TIME_LABEL"] = os.environ.get("HALLOWEEN_PARTY_TIME_LABEL", "7:00 PM until late")
app.config["PARTY_LOCATION_LABEL"] = os.environ.get("HALLOWEEN_PARTY_LOCATION_LABEL", "Qiana and Tony's place")
app.config["PARTY_OVERVIEW"] = os.environ.get(
    "HALLOWEEN_PARTY_OVERVIEW",
    "The third annual Halloween party: costumes encouraged, karaoke expected, dramatic entrances welcomed.",
)
app.config["DISPLAY_WIFI_NETWORK"] = os.environ.get("HALLOWEEN_DISPLAY_WIFI_NETWORK", "Halloween Party WiFi")
app.config["DISPLAY_WIFI_PASSWORD"] = os.environ.get("HALLOWEEN_DISPLAY_WIFI_PASSWORD", "halloween")
app.config["EMAIL_UPDATES_ENABLED"] = os.environ.get("HALLOWEEN_EMAIL_UPDATES_ENABLED", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
app.config["SES_REGION"] = os.environ.get("HALLOWEEN_SES_REGION", os.environ.get("AWS_REGION", "us-east-1"))
app.config["EMAIL_FROM"] = os.environ.get(
    "HALLOWEEN_EMAIL_FROM",
    "Qiana and Tony's Halloween Party <no-reply@tnq-halloween.com>",
)
app.config["PUBLIC_BASE_URL"] = os.environ.get("HALLOWEEN_PUBLIC_BASE_URL", "https://tnq-halloween.com")
app.config["RSVP_NOTIFICATION_EMAIL"] = os.environ.get(
    "HALLOWEEN_RSVP_NOTIFICATION_EMAIL",
    "tgio1129@gmail.com",
)
app.config["BARTENDER_TIP_UPLOAD_DIR"] = os.environ.get(
    "HALLOWEEN_BARTENDER_TIP_UPLOAD_DIR",
    os.path.join(app.static_folder or "static", "uploads", "bartender-tips"),
)
app.config["APPLE_MUSIC_TEAM_ID"] = os.environ.get("HALLOWEEN_APPLE_MUSIC_TEAM_ID", "").strip()
app.config["APPLE_MUSIC_KEY_ID"] = os.environ.get("HALLOWEEN_APPLE_MUSIC_KEY_ID", "").strip()
app.config["APPLE_MUSIC_PRIVATE_KEY"] = os.environ.get("HALLOWEEN_APPLE_MUSIC_PRIVATE_KEY", "").replace("\\n", "\n")
app.config["APPLE_MUSIC_DEVELOPER_TOKEN"] = os.environ.get(
    "HALLOWEEN_APPLE_MUSIC_DEVELOPER_TOKEN", ""
).strip()
app.config["APPLE_MUSIC_STOREFRONT"] = os.environ.get(
    "HALLOWEEN_APPLE_MUSIC_STOREFRONT", "us"
).strip().lower() or "us"
app.config["APPLE_MUSIC_WEB_ORIGIN"] = os.environ.get(
    "HALLOWEEN_APPLE_MUSIC_WEB_ORIGIN", app.config["PUBLIC_BASE_URL"]
).strip() or app.config["PUBLIC_BASE_URL"]
app.config["YOUTUBE_KARAOKE_ENABLED"] = os.environ.get(
    "HALLOWEEN_YOUTUBE_KARAOKE_ENABLED", ""
).strip().lower() in {"1", "true", "yes", "on"}
app.config["YOUTUBE_API_KEY"] = os.environ.get("HALLOWEEN_YOUTUBE_API_KEY", "").strip()
app.config["YOUTUBE_CLIENT_ID"] = os.environ.get("HALLOWEEN_YOUTUBE_CLIENT_ID", "").strip()
app.config["YOUTUBE_CLIENT_SECRET"] = os.environ.get("HALLOWEEN_YOUTUBE_CLIENT_SECRET", "").strip()
app.config["YOUTUBE_REFRESH_TOKEN"] = os.environ.get("HALLOWEEN_YOUTUBE_REFRESH_TOKEN", "").strip()
app.config["YOUTUBE_REGION_CODE"] = (
    os.environ.get("HALLOWEEN_YOUTUBE_REGION_CODE", "US").strip().upper() or "US"
)
app.config["YOUTUBE_SEARCH_DAILY_BUDGET"] = _config_int(
    "HALLOWEEN_YOUTUBE_SEARCH_DAILY_BUDGET", 90
)
app.config["YOUTUBE_SEARCH_ACCOUNT_LIMIT"] = _config_int(
    "HALLOWEEN_YOUTUBE_SEARCH_ACCOUNT_LIMIT", 10
)
app.config["YOUTUBE_VAULT_ADDR"] = os.environ.get(
    "VAULT_ADDR", "http://172.31.118.0:8200"
).strip()
app.config["YOUTUBE_VAULT_AWS_AUTH_ROLE"] = os.environ.get(
    "HALLOWEEN_YOUTUBE_VAULT_AWS_AUTH_ROLE",
    os.environ.get("VAULT_AWS_AUTH_ROLE", "halloween-api"),
).strip()
app.config["YOUTUBE_VAULT_SECRET_PATH"] = os.environ.get(
    "HALLOWEEN_YOUTUBE_VAULT_SECRET_PATH", "appsecrets/halloween_youtube"
).strip()

# Allow routes to respond to both `/path` and `/path/` so that users who
# bookmark a trailing slash variant do not receive a 404 that might look like
# a timeout when the browser keeps retrying.
app.url_map.strict_slashes = False


@dataclass(frozen=True)
class RedisConfig:
    host: str
    port: int
    db: int
    username: str | None
    password: str | None
    prefix: str
    url: str | None = None


def _parse_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


def _normalize_redis_prefix(prefix: str) -> str:
    cleaned_prefix = prefix.strip()
    if not cleaned_prefix:
        return "halloween"
    return cleaned_prefix[:-1] if cleaned_prefix.endswith(":") else cleaned_prefix


def load_redis_config() -> RedisConfig:
    redis_url = os.environ.get("HALLOWEEN_REDIS_URL", "").strip()
    prefix = _normalize_redis_prefix(os.environ.get("HALLOWEEN_REDIS_PREFIX", "halloween"))

    if redis_url:
        parsed_url = urlparse(redis_url)
        if parsed_url.scheme not in {"redis", "rediss"}:
            raise RuntimeError("HALLOWEEN_REDIS_URL must use redis:// or rediss://.")

        db = 1
        if parsed_url.path and parsed_url.path != "/":
            try:
                db = int(parsed_url.path.lstrip("/"))
            except ValueError as exc:
                raise RuntimeError("HALLOWEEN_REDIS_URL path must be a Redis database number.") from exc

        return RedisConfig(
            host=parsed_url.hostname or "127.0.0.1",
            port=parsed_url.port or 6379,
            db=db,
            username=unquote(parsed_url.username) if parsed_url.username else None,
            password=unquote(parsed_url.password) if parsed_url.password else None,
            prefix=prefix,
            url=redis_url,
        )

    return RedisConfig(
        host=os.environ.get("HALLOWEEN_REDIS_HOST", "127.0.0.1"),
        port=_parse_int_env("HALLOWEEN_REDIS_PORT", 6379),
        db=_parse_int_env("HALLOWEEN_REDIS_DB", 1),
        username=os.environ.get("HALLOWEEN_REDIS_USERNAME") or None,
        password=os.environ.get("HALLOWEEN_REDIS_PASSWORD") or None,
        prefix=prefix,
    )


REDIS_CONFIG = load_redis_config()


def redis_key(name: str) -> str:
    return f"{REDIS_CONFIG.prefix}:{name.lstrip(':')}"


def create_redis_client(config: RedisConfig) -> redis.Redis:
    if config.url:
        return redis.Redis.from_url(
            config.url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            health_check_interval=30,
        )

    return redis.Redis(
        host=config.host,
        port=config.port,
        db=config.db,
        username=config.username,
        password=config.password,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        health_check_interval=30,
    )


redis_client = create_redis_client(REDIS_CONFIG)
APP_INSTANCE_ID = uuid4().hex


def verify_redis_connection() -> bool:
    return bool(redis_client.ping())


def build_health_payload() -> tuple[dict[str, object], int]:
    redis_ok = False
    redis_error = None

    try:
        redis_ok = verify_redis_connection()
    except redis.RedisError as exc:
        redis_error = exc.__class__.__name__

    production = os.environ.get("APP_ENV") == "production"
    healthy = bool(redis_ok) or not production
    payload: dict[str, object] = {
        "app": "halloween-party",
        "status": "ok" if healthy else "unhealthy",
        "instance": APP_INSTANCE_ID,
        "redis": {
            "ok": bool(redis_ok),
            "required": production,
            "db": REDIS_CONFIG.db,
            "prefix": REDIS_CONFIG.prefix,
        },
        "state": {
            "available": bool(redis_state_available),
            "display_update_version": display_update_version,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if redis_error:
        payload["redis"]["error"] = redis_error

    return payload, 200 if healthy else 503


STATE_SCHEMA_VERSION = 6


@dataclass
class CostumeSignup:
    name: str
    costume: str
    contact: str = ""
    id: str = ""


@dataclass
class KaraokeSignup:
    name: str
    song_title: str
    artist: str
    youtube_link: str = ""
    id: str = ""
    requester_id: str = ""
    requested_at: str = ""
    youtube: dict[str, object] = field(default_factory=dict)
    workflow: dict[str, object] = field(default_factory=dict)
    history: list[dict[str, object]] = field(default_factory=list)


@dataclass
class RSVPSignup:
    name: str
    contact: str = ""
    guest_count: int = 1
    note: str = ""
    created_at: str = ""
    id: str = ""
    email_updates_acknowledged: bool = False


@dataclass
class RSVPUpdate:
    title: str
    message: str
    created_at: str = ""
    id: str = ""


DEFAULT_CONTEST_STATE: dict[str, object] = {
    "contest_started": False,
    "voting_open": False,
    "winner": None,
    "winner_locked": False,
    "scoreboard_card": None,
    "show_scoreboard_card": False,
}


DEFAULT_KARAOKE_STATE: dict[str, object] = {
    "party_started": False,
    "current_singer_index": None,
    "current_singer_id": None,
    "next_singer_id": None,
    "stage_mode": "standby",
}
KARAOKE_VIDEO_VALIDATION_STATUSES = {"pending", "verified", "failed", "unavailable"}
KARAOKE_APPROVAL_STATUSES = {"pending", "approved", "rejected", "cancelled"}
KARAOKE_PLAYLIST_SYNC_STATUSES = {
    "not_started",
    "pending",
    "synced",
    "out_of_order",
    "failed",
    "removal_pending",
    "removed",
}
KARAOKE_PERFORMANCE_STATUSES = {"waiting", "called", "on_stage", "completed", "skipped"}
KARAOKE_HISTORY_LIMIT = 100
KARAOKE_OPERATION_STALE_SECONDS = 60
YOUTUBE_SEARCH_CACHE_SECONDS = 60 * 60 * 6
YOUTUBE_SEARCH_PAGE_SIZE = 8
YOUTUBE_SEARCH_QUERY_MAX_LENGTH = 180
YOUTUBE_PLAYLIST_NOTE_PREFIX = "halloween-karaoke"
KARAOKE_CLEAR_ACTIVE_STATUSES = {"preparing", "deleting_youtube", "finalizing"}
DEFAULT_KARAOKE_WORKFLOW: dict[str, object] = {
    "video_validation_status": "pending",
    "approval_status": "pending",
    "playlist_sync_status": "not_started",
    "performance_status": "waiting",
    "playlist_item_id": "",
    "playlist_revision": 1,
    "operation_id": "",
    "operation_action": "",
    "operation_started_at": "",
    "last_sync_error_code": "",
    "last_sync_error_message": "",
    "approved_at": "",
    "approved_by": "",
    "called_at": "",
    "started_at": "",
    "completed_at": "",
}
DEFAULT_YOUTUBE_KARAOKE_STATE: dict[str, object] = {
    "playlist_id": "",
    "playlist_title": "",
    "playlist_privacy": "",
    "channel_id": "",
    "channel_title": "",
    "connection_status": "not_configured",
    "last_connection_check_at": "",
    "last_connection_error": "",
    "last_reconciled_at": "",
    "last_reconciliation_summary": {},
    "clear_operation": {
        "operation_id": "",
        "mode": "",
        "status": "idle",
        "started_at": "",
        "completed_at": "",
        "backup_key": "",
        "record_count": 0,
        "target_count": 0,
        "deleted_count": 0,
        "failed_count": 0,
        "target_item_ids": [],
        "failed_item_ids": [],
        "last_error": "",
    },
}

DJ_RECEIVER_STALE_SECONDS = 20
DJ_COMMAND_TIMEOUT_SECONDS = 8
MAX_DJ_SONG_REQUESTS_PER_ATTENDEE = 3
DJ_PLAYBACK_STATUSES = {"stopped", "paused", "playing", "buffering", "unknown"}
DJ_RECEIVER_STATUSES = {"offline", "needs_authorization", "needs_audio_enable", "ready", "error"}
DJ_COMMAND_ACTIONS = {
    "play_song",
    "play_playlist",
    "shuffle_playlist",
    "pause",
    "stop",
    "next",
    "previous",
    "reset",
}
DEFAULT_DJ_STATE: dict[str, object] = {
    "command_revision": 0,
    "current_command": None,
    "last_command": None,
    "last_reset": None,
    "receiver": {
        "id": "",
        "status": "offline",
        "authorization_status": "not_configured",
        "audio_enabled": False,
        "playback_status": "stopped",
        "current_song_id": "",
        "playback_position_seconds": 0,
        "last_seen_at": "",
        "last_error": "",
    },
    "desired": {
        "playback_status": "stopped",
        "song_id": "",
        "queue_order": [],
        "shuffle_enabled": False,
    },
}

DEFAULT_DRINK_ESTIMATE_SECONDS = 8 * 60
DRINK_READY_OVERRIDE_SECONDS = 10
DRINK_READY_DASHBOARD_SECONDS = 5 * 60
SPECIALTY_DRINK_INCLUDED_LIMIT = 3
SPECIALTY_EXTRA_ORDER_HOUR = 23
DRINK_ORDER_STATUSES = ("received", "in_progress", "complete")
MENU_ITEM_CATEGORIES = ("drink", "food")
DRINK_TYPES = ("standard", "specialty")
BEVERAGE_TYPES = ("alcoholic", "non_alcoholic")
BARTENDER_TIP_UPLOAD_URL_PREFIX = "/static/uploads/bartender-tips"
ALLOWED_BARTENDER_TIP_IMAGE_EXTENSIONS = {".gif", ".jpg", ".jpeg", ".png", ".webp"}
MAX_BARTENDER_TIP_IMAGE_BYTES = 5 * 1024 * 1024

DEFAULT_PARTY_DETAILS: dict[str, str] = {
    "date": app.config["PARTY_DATE_LABEL"],
    "time": app.config["PARTY_TIME_LABEL"],
    "location": app.config["PARTY_LOCATION_LABEL"],
    "map_address": app.config["PARTY_LOCATION_LABEL"],
    "overview": app.config["PARTY_OVERVIEW"],
}
DEFAULT_DISPLAY_SETTINGS: dict[str, str] = {
    "wifi_network": app.config["DISPLAY_WIFI_NETWORK"],
    "wifi_password": app.config["DISPLAY_WIFI_PASSWORD"],
}
DEFAULT_BARTENDER_TIP_SETTINGS: dict[str, object] = {
    "enabled": False,
    "display_name": "Your Bartender",
    "note": "Tips are never required, always appreciated.",
    "image_url": "",
    "zelle": "",
    "paypal": "",
    "venmo": "",
    "cash_app": "",
}
DEFAULT_RSVP_NOTIFICATION_EMAIL = app.config["RSVP_NOTIFICATION_EMAIL"]
RSVP_NOTE_MAX_LENGTH = 5000
RSVP_UPDATE_MESSAGE_MAX_LENGTH = 5000

DEFAULT_EVENT_EXPERIENCE_MODE = "auto"
EVENT_EXPERIENCE_MODES: dict[str, dict[str, str]] = {
    "auto": {
        "label": "Automatic",
        "description": "Use the configured party date to decide which guest portal experience appears.",
    },
    "pre_party": {
        "label": "Pre-party",
        "description": "Force the planning view and hide party-day menu, costume, karaoke, drink, and voting actions.",
    },
    "party_day": {
        "label": "Party day",
        "description": "Force the event-night portal so hosts can test guest menu, drink, costume, karaoke, and voting flows.",
    },
}

DEFAULT_LANDING_PAGE_TARGET = "rsvp"
LANDING_PAGE_TARGETS: dict[str, dict[str, str]] = {
    "rsvp": {
        "endpoint": "rsvp",
        "label": "RSVP landing page",
        "description": "Show the public RSVP page with signup and sign-in options.",
    },
    "party_login": {
        "endpoint": "party_login",
        "label": "Party login",
        "description": "Send guests directly to the Halloween account sign-in page.",
    },
    "party_register": {
        "endpoint": "party_register",
        "label": "Party account signup",
        "description": "Send guests directly to the account creation form.",
    },
    "party_dashboard": {
        "endpoint": "party_dashboard",
        "label": "Party portal",
        "description": "Send signed-in guests to the party portal, with login required.",
    },
    "live_display": {
        "endpoint": "live_display",
        "label": "Live display",
        "description": "Use the big-screen live display as the public root route.",
    },
}

ADMIN_WORKSPACES: dict[str, dict[str, str]] = {
    "home": {"label": "Tonight", "description": "Live party status and next actions."},
    "guests": {"label": "Guests", "description": "RSVPs, guest updates, and party details."},
    "public": {"label": "Public Info", "description": "Guest-facing access and display settings."},
    "program": {"label": "Program", "description": "Costume contest controls, voting, and results."},
    "karaoke": {"label": "Karaoke", "description": "YouTube requests, playlist workflow, and stage controls."},
    "dj": {"label": "DJ", "description": "Playlist, live-display receiver, and verified music controls."},
    "bar": {"label": "Bar", "description": "Drink operations and bartender tipping."},
    "menu": {"label": "Menu", "description": "Food and drink availability."},
    "accounts": {"label": "Accounts", "description": "Party accounts and bartender access."},
}

ROLE_PREVIEW_OPTIONS: dict[str, dict[str, object]] = {
    "regular": {"label": "Attendee", "roles": {"regular"}},
    "bartender": {"label": "Bartender", "roles": {"regular", "bartender"}},
    "admin": {"label": "Admin", "roles": {"admin"}},
}


# Redis is the persistence target. These globals remain as the process-local
# state cache while the app is migrated route by route.
costume_signups: List[CostumeSignup] = []
karaoke_signups: List[KaraokeSignup] = []
costume_votes: List[List[int]] = []
costume_ballots: dict[str, dict[str, int]] = {}
registered_users: dict[str, str] = {}
user_accounts: dict[str, dict[str, object]] = {}
password_reset_tokens: dict[str, dict[str, object]] = {}
menu_items: list[dict[str, object]] = []
drink_orders: list[dict[str, object]] = []
dj_playlist: list[dict[str, object]] = []
dj_song_requests: list[dict[str, object]] = []
dj_state: dict[str, object] = copy.deepcopy(DEFAULT_DJ_STATE)
rsvp_signups: List[RSVPSignup] = []
rsvp_updates: List[RSVPUpdate] = []
submitted_costume_votes: set[str] = set()
live_display_event_override: dict[str, object] | None = None
live_display_notice_override: dict[str, object] | None = None
landing_page_target = DEFAULT_LANDING_PAGE_TARGET
event_experience_mode = DEFAULT_EVENT_EXPERIENCE_MODE
party_code_hash = generate_password_hash(app.config["PARTY_CODE"]) if app.config["PARTY_CODE"] else ""
party_code_hint = ""
rsvp_notification_email = DEFAULT_RSVP_NOTIFICATION_EMAIL.strip()

display_update_condition = Condition()
display_update_version = 0


contest_state: dict[str, object] = copy.deepcopy(DEFAULT_CONTEST_STATE)
karaoke_state: dict[str, object] = copy.deepcopy(DEFAULT_KARAOKE_STATE)
youtube_karaoke: dict[str, object] = copy.deepcopy(DEFAULT_YOUTUBE_KARAOKE_STATE)
party_details: dict[str, str] = copy.deepcopy(DEFAULT_PARTY_DETAILS)
display_settings: dict[str, str] = copy.deepcopy(DEFAULT_DISPLAY_SETTINGS)
bartender_tip_settings: dict[str, object] = copy.deepcopy(DEFAULT_BARTENDER_TIP_SETTINGS)
redis_state_available = False
display_pubsub_listener_started = False
STATE_MUTATION_ENDPOINTS = {
    "party_account",
    "party_login",
    "party_register",
    "password_reset_request",
    "password_reset_confirm",
    "rsvp",
    "admin_portal",
    "bartender_portal",
    "party_menu",
    "party_drink_history",
    "party_costumes",
    "party_costume_voting",
    "party_jukebox_request",
    "dj_receiver_state",
}
STATE_REFRESH_ENDPOINTS = {
    "party_account",
    "rsvp",
    "rsvp_calendar",
    "admin_portal",
    "party_dashboard",
    "party_menu",
    "party_drink_history",
    "party_bartender_tip",
    "bartender_portal",
    "bartender_queue_data",
    "party_costumes",
    "party_karaoke",
    "party_karaoke_search",
    "party_karaoke_cancel",
    "party_karaoke_replace",
    "party_costume_voting",
    "party_jukebox",
    "party_jukebox_data",
    "party_jukebox_catalog_search",
    "admin_dj_song_request_queue",
    "live_display",
    "display_data",
    "dj_catalog_search",
    "dj_musickit_token",
    "admin_karaoke_state",
    "admin_karaoke_search",
    "admin_youtube_playlists",
}
ADMIN_ENDPOINTS = {
    "admin_portal",
    "export_state",
    "export_costume_results",
    "export_karaoke_lineup",
    "admin_dj_song_request_queue",
    "admin_karaoke_state",
    "admin_karaoke_search",
    "admin_karaoke_approve",
    "admin_karaoke_retry",
    "admin_karaoke_reject",
    "admin_karaoke_remove",
    "admin_karaoke_replace",
    "admin_karaoke_reset",
    "admin_karaoke_reconcile",
    "admin_karaoke_sync_order",
    "admin_youtube_test_connection",
    "admin_youtube_playlists",
    "admin_youtube_select_playlist",
    "admin_youtube_create_playlist",
    "admin_youtube_connect",
    "admin_youtube_callback",
    "admin_youtube_disconnect",
}
BAR_ENDPOINTS = {
    "bartender_portal",
    "bartender_queue_data",
}
REGULAR_USER_ENDPOINTS = {
    "party_account",
    "party_dashboard",
    "party_menu",
    "party_drink_history",
    "party_bartender_tip",
    "party_costumes",
    "party_karaoke",
    "party_karaoke_search",
    "party_karaoke_cancel",
    "party_karaoke_replace",
    "party_costume_voting",
    "party_jukebox",
    "party_jukebox_data",
    "party_jukebox_catalog_search",
    "party_jukebox_request",
}
DISPLAY_ENDPOINTS = {
    "live_display",
    "display_updates",
    "display_data",
    "dj_receiver_state",
    "dj_catalog_search",
    "dj_musickit_token",
}
ROLE_LOGIN_ENDPOINTS = {
    "regular": "party_login",
    "bartender": "party_login",
    "admin": "admin_login",
}
STATE_LOCK_TIMEOUT_SECONDS = 10
STATE_LOCK_BLOCKING_TIMEOUT_SECONDS = 5
STATE_BACKUP_TTL_SECONDS = 60 * 60 * 24 * 30


def broadcast_display_update() -> None:
    global display_update_version
    with display_update_condition:
        display_update_version += 1
        if persist_state_if_available() and has_request_context():
            g.redis_state_saved_during_request = True
        publish_display_update("state-change")
        display_update_condition.notify_all()


def ensure_signup_ids() -> None:
    for signup in costume_signups:
        if not signup.id:
            signup.id = uuid4().hex

    for signup in karaoke_signups:
        if not signup.id:
            signup.id = uuid4().hex
        signup.youtube = normalize_karaoke_youtube(signup.youtube, signup.youtube_link)
        signup.workflow = normalize_karaoke_workflow(
            signup.workflow,
            has_video=bool(signup.youtube.get("video_id")),
        )
        signup.history = normalize_karaoke_history(signup.history)


def ensure_costume_votes_alignment() -> None:
    ensure_signup_ids()
    rebuild_legacy_vote_rows_from_ballots()


def ensure_submitted_vote_tracking() -> None:
    submitted_costume_votes.clear()
    submitted_costume_votes.update(costume_ballots.keys())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def format_time_label(raw_iso: object) -> str:
    parsed = parse_utc_iso(raw_iso)
    if not parsed:
        return ""
    return parsed.astimezone().strftime("%-I:%M %p")


def parse_party_start() -> datetime:
    raw_start = str(app.config.get("PARTY_START", "") or "")
    try:
        parsed_start = datetime.fromisoformat(raw_start)
    except ValueError:
        parsed_start = datetime(2026, 10, 31, 19, 0, tzinfo=timezone(timedelta(hours=-6)))

    if parsed_start.tzinfo is None:
        return parsed_start.replace(tzinfo=timezone(timedelta(hours=-6)))
    return parsed_start


def party_has_started() -> bool:
    return datetime.now(timezone.utc) >= parse_party_start().astimezone(timezone.utc)


def party_day_has_arrived(now: datetime | None = None) -> bool:
    if event_experience_mode == "pre_party":
        return False
    if event_experience_mode == "party_day":
        return True

    party_start = parse_party_start()
    party_tz = party_start.tzinfo or timezone(timedelta(hours=-6))
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=party_tz)
    return current_time.astimezone(party_tz).date() >= party_start.astimezone(party_tz).date()


def specialty_extra_orders_are_open(now: datetime | None = None) -> bool:
    party_start = parse_party_start()
    party_tz = party_start.tzinfo or timezone(timedelta(hours=-6))
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=party_tz)
    local_time = current_time.astimezone(party_tz)
    if local_time.date() > party_start.astimezone(party_tz).date():
        return True
    return local_time.date() == party_start.astimezone(party_tz).date() and local_time.hour >= SPECIALTY_EXTRA_ORDER_HOUR


def party_info_cards() -> list[dict[str, str]]:
    return [
        {
            "title": "Date",
            "message": party_details.get("date", DEFAULT_PARTY_DETAILS["date"]),
        },
        {
            "title": "Time",
            "message": party_details.get("time", DEFAULT_PARTY_DETAILS["time"]),
        },
        {
            "title": "Location",
            "message": party_details.get("location", DEFAULT_PARTY_DETAILS["location"]),
        },
        {
            "title": "Party Details",
            "message": party_details.get("overview", DEFAULT_PARTY_DETAILS["overview"]),
        },
    ]


def google_maps_urls(address: str) -> dict[str, str]:
    cleaned_address = address.strip()
    if not cleaned_address:
        return {}

    encoded_address = quote_plus(cleaned_address)
    return {
        "directions": f"https://www.google.com/maps/dir/?api=1&destination={encoded_address}",
        "embed": f"https://www.google.com/maps?q={encoded_address}&output=embed",
    }


def party_calendar_times() -> tuple[datetime, datetime]:
    start = parse_party_start().astimezone(timezone.utc)
    return start, start + timedelta(hours=5)


def calendar_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_escape(value: object) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def party_calendar_description() -> str:
    details = party_details.get("overview", DEFAULT_PARTY_DETAILS["overview"])
    rsvp_url = app.config["PUBLIC_BASE_URL"].rstrip("/") + url_for("rsvp")
    return f"{details}\n\nRSVP details: {rsvp_url}"


def google_calendar_url() -> str:
    start, end = party_calendar_times()
    location = party_details.get("map_address") or party_details.get("location", "")
    params = {
        "action": "TEMPLATE",
        "text": app.config["PARTY_TITLE"],
        "dates": f"{calendar_timestamp(start)}/{calendar_timestamp(end)}",
        "details": party_calendar_description(),
        "location": location,
    }
    return "https://calendar.google.com/calendar/render?" + "&".join(
        f"{key}={quote(str(value), safe='')}" for key, value in params.items()
    )


def build_party_ics(rsvp_id: str | None = None) -> str:
    start, end = party_calendar_times()
    location = party_details.get("map_address") or party_details.get("location", "")
    uid = f"{rsvp_id or 'party'}@tnq-halloween.com"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TNQ Halloween//Party RSVP//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{ics_escape(uid)}",
        f"DTSTAMP:{calendar_timestamp(datetime.now(timezone.utc))}",
        f"DTSTART:{calendar_timestamp(start)}",
        f"DTEND:{calendar_timestamp(end)}",
        f"SUMMARY:{ics_escape(app.config['PARTY_TITLE'])}",
        f"DESCRIPTION:{ics_escape(party_calendar_description())}",
        f"LOCATION:{ics_escape(location)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def normalize_username(username: str) -> str:
    return " ".join(username.strip().lower().split())


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw_email: str) -> str:
    parsed_email = parseaddr(raw_email.strip())[1].strip().lower()
    return parsed_email if EMAIL_PATTERN.match(parsed_email) else ""


def normalize_rsvp_notification_email(raw_email: object) -> str:
    return normalize_email(str(raw_email or ""))


def create_user_account(username: str, password: str, email: str = "") -> dict[str, object]:
    return {
        "id": uuid4().hex,
        "username": username.strip(),
        "email": normalize_email(email),
        "email_updates_acknowledged": True,
        "roles": ["regular"],
        "password_hash": generate_password_hash(password),
        "created_at": _utc_now_iso(),
    }


def find_user_account_key_by_id(account_id: str) -> str | None:
    for normalized_username, account in user_accounts.items():
        if str(account.get("id", "")) == account_id:
            return normalized_username
    return None


def find_rsvp_index_by_id(rsvp_id: str) -> int | None:
    for index, signup in enumerate(rsvp_signups):
        if signup.id == rsvp_id:
            return index
    return None


def normalize_account_roles(raw_roles: object) -> list[str]:
    roles = {"regular"}
    if isinstance(raw_roles, list):
        roles.update(str(role) for role in raw_roles if role in {"regular", "bartender"})
    return sorted(roles)


def account_has_role(account: dict[str, object] | None, role: str) -> bool:
    if not account:
        return False
    return role in normalize_account_roles(account.get("roles", []))


def current_user_account() -> dict[str, object] | None:
    user_id = str(session.get("user_id", "") or "")
    if not user_id:
        return None
    for account in user_accounts.values():
        if str(account.get("id", "")) == user_id:
            return account
    return None


def sync_attendee_session_roles(account: dict[str, object]) -> None:
    """Refresh account-derived attendee roles without removing other active roles."""
    roles = session_roles()
    roles.add("regular")
    if account_has_role(account, "bartender"):
        roles.add("bartender")
    else:
        roles.discard("bartender")
    session["roles"] = sorted(roles)


def invalidate_password_reset_tokens_for_account(account_id: str) -> None:
    """Remove reset links that must no longer work for an updated account."""
    for token_hash, record in list(password_reset_tokens.items()):
        if str(record.get("account_id", "")) == account_id:
            password_reset_tokens.pop(token_hash, None)


def hash_password_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_utc_iso(raw_value: object) -> datetime | None:
    if not raw_value:
        return None

    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def find_user_account_by_email(email: str) -> tuple[str, dict[str, object]] | None:
    normalized_email = normalize_email(email)
    if not normalized_email:
        return None

    for normalized_username, account in user_accounts.items():
        if normalize_email(str(account.get("email", "") or "")) == normalized_email:
            return normalized_username, account

    return None


def cleanup_password_reset_tokens() -> None:
    now = datetime.now(timezone.utc)
    expired_hashes = [
        token_hash
        for token_hash, record in password_reset_tokens.items()
        if parse_utc_iso(record.get("expires_at")) and parse_utc_iso(record.get("expires_at")) < now
    ]
    for token_hash in expired_hashes:
        password_reset_tokens.pop(token_hash, None)


def create_password_reset_token(normalized_username: str, account: dict[str, object]) -> str:
    cleanup_password_reset_tokens()
    token = secrets.token_urlsafe(32)
    token_hash = hash_password_reset_token(token)
    now = datetime.now(timezone.utc)
    password_reset_tokens[token_hash] = {
        "normalized_username": normalized_username,
        "account_id": str(account.get("id", "")),
        "email": normalize_email(str(account.get("email", "") or "")),
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=45)).isoformat().replace("+00:00", "Z"),
        "used_at": "",
    }
    return token


def valid_password_reset_record(token: str) -> tuple[str, dict[str, object]] | None:
    token_hash = hash_password_reset_token(token)
    record = password_reset_tokens.get(token_hash)
    if not record or record.get("used_at"):
        return None

    expires_at = parse_utc_iso(record.get("expires_at"))
    if not expires_at or expires_at < datetime.now(timezone.utc):
        return None

    normalized_username = normalize_username(str(record.get("normalized_username", "") or ""))
    account = user_accounts.get(normalized_username)
    if not account or str(account.get("id", "")) != str(record.get("account_id", "")):
        return None

    return token_hash, record


def mark_password_reset_token_used(token_hash: str) -> None:
    if token_hash in password_reset_tokens:
        password_reset_tokens[token_hash]["used_at"] = _utc_now_iso()


def normalize_landing_page_target(raw_target: object) -> str:
    target = str(raw_target or "").strip()
    if target in LANDING_PAGE_TARGETS:
        return target
    return DEFAULT_LANDING_PAGE_TARGET


def normalize_event_experience_mode(raw_mode: object) -> str:
    mode = str(raw_mode or "").strip()
    if mode in EVENT_EXPERIENCE_MODES:
        return mode
    return DEFAULT_EVENT_EXPERIENCE_MODE


def landing_page_endpoint() -> str:
    target = normalize_landing_page_target(landing_page_target)
    return LANDING_PAGE_TARGETS[target]["endpoint"]


def party_code_is_configured() -> bool:
    return bool(party_code_hash)


def verify_party_code(raw_code: str) -> bool:
    return bool(raw_code) and party_code_is_configured() and check_password_hash(party_code_hash, raw_code)


def rsvp_signup_to_dict(signup: RSVPSignup) -> dict[str, object]:
    return {
        "id": signup.id,
        "name": signup.name,
        "contact": signup.contact,
        "guest_count": signup.guest_count,
        "note": signup.note,
        "created_at": signup.created_at,
        "email_updates_acknowledged": signup.email_updates_acknowledged,
    }


def rsvp_signup_from_dict(data: dict[str, object]) -> RSVPSignup:
    try:
        guest_count = int(data.get("guest_count", 1) or 1)
    except (TypeError, ValueError):
        guest_count = 1

    return RSVPSignup(
        id=str(data.get("id", "") or uuid4().hex),
        name=str(data.get("name", "") or ""),
        contact=str(data.get("contact", "") or ""),
        guest_count=max(1, min(12, guest_count)),
        note=str(data.get("note", "") or ""),
        created_at=str(data.get("created_at", "") or ""),
        email_updates_acknowledged=bool(data.get("email_updates_acknowledged", False)),
    )


def rsvp_update_to_dict(update: RSVPUpdate) -> dict[str, str]:
    return {
        "id": update.id,
        "title": update.title,
        "message": update.message,
        "created_at": update.created_at,
    }


def rsvp_update_from_dict(data: dict[str, object]) -> RSVPUpdate:
    return RSVPUpdate(
        id=str(data.get("id", "") or uuid4().hex),
        title=str(data.get("title", "") or ""),
        message=str(data.get("message", "") or ""),
        created_at=str(data.get("created_at", "") or ""),
    )


def sorted_rsvp_updates() -> list[RSVPUpdate]:
    return sorted(
        rsvp_updates,
        key=lambda update: update.created_at or "",
        reverse=True,
    )


def available_update_email_recipients() -> list[dict[str, str]]:
    recipients: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_recipient(recipient_id: str, recipient_type: str, name: object, raw_email: object) -> None:
        email = normalize_email(str(raw_email or ""))
        if email and email not in seen:
            recipients.append(
                {
                    "id": recipient_id,
                    "type": recipient_type,
                    "name": str(name or "Guest").strip() or "Guest",
                    "email": email,
                }
            )
            seen.add(email)

    for signup in rsvp_signups:
        add_recipient(f"rsvp:{signup.id}", "RSVP", signup.name, signup.contact)

    for account in user_accounts.values():
        add_recipient(
            f"account:{account.get('id', '')}",
            "Account",
            account.get("username", ""),
            account.get("email", ""),
        )

    return recipients


def collect_update_email_recipients(selected_recipient_ids: set[str] | None = None) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()
    available_recipients = available_update_email_recipients()

    for recipient in available_recipients:
        if selected_recipient_ids is not None and recipient["id"] not in selected_recipient_ids:
            continue

        email = recipient["email"]
        if email not in seen:
            recipients.append(email)
            seen.add(email)

    return recipients


def create_ses_client():
    import boto3

    return boto3.client("sesv2", region_name=app.config["SES_REGION"])


def send_rsvp_update_emails(update: RSVPUpdate, selected_recipient_ids: set[str] | None = None) -> tuple[int, int]:
    recipients = collect_update_email_recipients(selected_recipient_ids)
    if not recipients:
        return 0, 0

    if not app.config["EMAIL_UPDATES_ENABLED"]:
        return 0, len(recipients)

    try:
        ses_client = create_ses_client()
    except ImportError:
        app.logger.warning("Email updates are enabled, but boto3 is not installed.")
        return 0, len(recipients)

    rsvp_url = app.config["PUBLIC_BASE_URL"].rstrip("/") + url_for("rsvp")
    subject = f"Halloween Party Update: {update.title}"
    text_body = (
        f"{update.title}\n\n"
        f"{update.message}\n\n"
        f"Read the latest party details: {rsvp_url}\n\n"
        "You are receiving this because you RSVP'd or created a party account for "
        f"{app.config['PARTY_TITLE']}."
    )
    html_body = render_template(
        "email/rsvp_update.html",
        update=update,
        rsvp_url=rsvp_url,
    )

    sent_count = 0
    failed_count = 0
    for recipient in recipients:
        try:
            ses_client.send_email(
                FromEmailAddress=app.config["EMAIL_FROM"],
                Destination={"ToAddresses": [recipient]},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": text_body, "Charset": "UTF-8"},
                            "Html": {"Data": html_body, "Charset": "UTF-8"},
                        },
                    }
                },
            )
            sent_count += 1
        except Exception as exc:
            failed_count += 1
            app.logger.warning("Unable to send RSVP update email to %s: %s", recipient, exc)

    return sent_count, failed_count


def send_password_reset_email(account: dict[str, object], token: str) -> bool:
    recipient = normalize_email(str(account.get("email", "") or ""))
    if not recipient or not app.config["EMAIL_UPDATES_ENABLED"]:
        return False

    try:
        ses_client = create_ses_client()
    except ImportError:
        app.logger.warning("Password reset email requested, but boto3 is not installed.")
        return False

    reset_url = app.config["PUBLIC_BASE_URL"].rstrip("/") + url_for("password_reset_confirm", token=token)
    subject = "Reset your Halloween Party password"
    text_body = (
        f"Hi {account.get('username', 'there')},\n\n"
        "Use this link to reset your Halloween Party password. It expires in 45 minutes:\n\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    html_body = render_template(
        "email/password_reset.html",
        account=account,
        reset_url=reset_url,
    )

    try:
        ses_client.send_email(
            FromEmailAddress=app.config["EMAIL_FROM"],
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            },
        )
        return True
    except Exception as exc:
        app.logger.warning("Unable to send password reset email to %s: %s", recipient, exc)
        return False


def send_account_welcome_email(account: dict[str, object]) -> bool:
    recipient = normalize_email(str(account.get("email", "") or ""))
    if not recipient or not app.config["EMAIL_UPDATES_ENABLED"]:
        return False

    try:
        ses_client = create_ses_client()
    except ImportError:
        app.logger.warning("Account welcome email requested, but boto3 is not installed.")
        return False

    base_url = app.config["PUBLIC_BASE_URL"].rstrip("/")
    dashboard_url = base_url + url_for("party_dashboard")
    subject = f"Welcome to {app.config['PARTY_TITLE']}"
    text_body = (
        f"Hi {account.get('username', 'there')},\n\n"
        f"Your account for {app.config['PARTY_TITLE']} is ready.\n\n"
        f"Party portal: {dashboard_url}\n\n"
        "See you at the party."
    )
    html_body = render_template(
        "email/account_welcome.html",
        account=account,
        dashboard_url=dashboard_url,
    )

    try:
        ses_client.send_email(
            FromEmailAddress=app.config["EMAIL_FROM"],
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            },
        )
        return True
    except Exception as exc:
        app.logger.warning("Unable to send account welcome email to %s: %s", recipient, exc)
        return False


def send_rsvp_confirmation_email(signup: RSVPSignup) -> bool:
    recipient = normalize_email(signup.contact)
    if not recipient or not app.config["EMAIL_UPDATES_ENABLED"]:
        return False

    try:
        ses_client = create_ses_client()
    except ImportError:
        app.logger.warning("RSVP confirmation email requested, but boto3 is not installed.")
        return False

    base_url = app.config["PUBLIC_BASE_URL"].rstrip("/")
    rsvp_url = base_url + url_for("rsvp")
    calendar_url = base_url + url_for("rsvp_calendar", rsvp_id=signup.id)
    maps_urls = google_maps_urls(party_details.get("map_address", ""))
    subject = f"RSVP confirmed: {app.config['PARTY_TITLE']}"
    text_body = (
        f"Hi {signup.name},\n\n"
        f"Your RSVP for {app.config['PARTY_TITLE']} is confirmed.\n\n"
        f"Guests: {signup.guest_count}\n"
        f"Email: {signup.contact}\n"
        f"Note: {signup.note or 'None'}\n\n"
        f"Date: {party_details.get('date', DEFAULT_PARTY_DETAILS['date'])}\n"
        f"Time: {party_details.get('time', DEFAULT_PARTY_DETAILS['time'])}\n"
        f"Location: {party_details.get('location', DEFAULT_PARTY_DETAILS['location'])}\n\n"
        f"RSVP details: {rsvp_url}\n"
        f"Add to calendar: {calendar_url}\n"
        f"Google Calendar: {google_calendar_url()}\n"
    )
    html_body = render_template(
        "email/rsvp_confirmation.html",
        signup=signup,
        party_details=party_details,
        rsvp_url=rsvp_url,
        calendar_url=calendar_url,
        google_calendar_url=google_calendar_url(),
        maps_urls=maps_urls,
    )

    try:
        ses_client.send_email(
            FromEmailAddress=app.config["EMAIL_FROM"],
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            },
        )
        return True
    except Exception as exc:
        app.logger.warning("Unable to send RSVP confirmation email to %s: %s", recipient, exc)
        return False


def send_rsvp_admin_notification_email(signup: RSVPSignup) -> bool:
    recipient = normalize_rsvp_notification_email(rsvp_notification_email)
    if not recipient or not app.config["EMAIL_UPDATES_ENABLED"]:
        return False

    try:
        ses_client = create_ses_client()
    except ImportError:
        app.logger.warning("RSVP admin notification requested, but boto3 is not installed.")
        return False

    admin_url = app.config["PUBLIC_BASE_URL"].rstrip("/") + url_for("admin_portal")
    subject = f"New RSVP: {signup.name}"
    text_body = (
        f"New RSVP for {app.config['PARTY_TITLE']}\n\n"
        f"Name: {signup.name}\n"
        f"Email: {signup.contact}\n"
        f"Guests: {signup.guest_count}\n"
        f"Note: {signup.note or 'None'}\n"
        f"Submitted: {signup.created_at or 'Unknown'}\n\n"
        f"Date: {party_details.get('date', DEFAULT_PARTY_DETAILS['date'])}\n"
        f"Time: {party_details.get('time', DEFAULT_PARTY_DETAILS['time'])}\n"
        f"Location: {party_details.get('location', DEFAULT_PARTY_DETAILS['location'])}\n\n"
        f"Admin dashboard: {admin_url}"
    )
    html_body = render_template(
        "email/rsvp_admin_notification.html",
        signup=signup,
        party_details=party_details,
        admin_url=admin_url,
    )

    try:
        ses_client.send_email(
            FromEmailAddress=app.config["EMAIL_FROM"],
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            },
        )
        return True
    except Exception as exc:
        app.logger.warning("Unable to send RSVP admin notification email to %s: %s", recipient, exc)
        return False


def send_drink_order_placed_email(order: dict[str, object]) -> bool:
    recipient = normalize_email(str(order.get("email", "") or ""))
    if not recipient or not app.config["EMAIL_UPDATES_ENABLED"]:
        return False

    try:
        ses_client = create_ses_client()
    except ImportError:
        app.logger.warning("Drink order email requested, but boto3 is not installed.")
        return False

    menu_url = app.config["PUBLIC_BASE_URL"].rstrip("/") + url_for("party_menu")
    ready_label = format_time_label(order.get("estimated_ready_at")) or "soon"
    subject = f"Drink order received: {order.get('item_name', 'your drink')}"
    text_body = (
        f"Hi {order.get('username', 'there')},\n\n"
        f"We received your order for {order.get('item_name', 'your drink')}.\n"
        f"Estimated ready time: {ready_label}.\n\n"
        f"You can check your order status here: {menu_url}"
    )
    html_body = render_template(
        "email/drink_order_placed.html",
        order=order,
        ready_label=ready_label,
        menu_url=menu_url,
    )

    try:
        ses_client.send_email(
            FromEmailAddress=app.config["EMAIL_FROM"],
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            },
        )
        return True
    except Exception as exc:
        app.logger.warning("Unable to send drink order email to %s: %s", recipient, exc)
        return False


def send_drink_ready_email(order: dict[str, object]) -> bool:
    recipient = normalize_email(str(order.get("email", "") or ""))
    if not recipient or not app.config["EMAIL_UPDATES_ENABLED"]:
        return False

    try:
        ses_client = create_ses_client()
    except ImportError:
        app.logger.warning("Drink ready email requested, but boto3 is not installed.")
        return False

    menu_url = app.config["PUBLIC_BASE_URL"].rstrip("/") + url_for("party_menu")
    subject = f"Drink ready: {order.get('item_name', 'your drink')}"
    text_body = (
        f"Hi {order.get('username', 'there')},\n\n"
        f"Your {order.get('item_name', 'drink')} is ready. Pick it up at the bar.\n\n"
        f"Order status: {menu_url}"
    )
    html_body = render_template("email/drink_order_ready.html", order=order, menu_url=menu_url)

    try:
        ses_client.send_email(
            FromEmailAddress=app.config["EMAIL_FROM"],
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                }
            },
        )
        return True
    except Exception as exc:
        app.logger.warning("Unable to send drink ready email to %s: %s", recipient, exc)
        return False


def safe_image_url(raw_url: str) -> str:
    image_url = raw_url.strip()
    if not image_url:
        return ""
    if len(image_url) > 500:
        return ""
    parsed = urlparse(image_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return image_url
    if image_url.startswith("/static/"):
        return image_url
    return ""


def image_bytes_match_extension(filename: str, image_bytes: bytes) -> bool:
    extension = os.path.splitext(filename)[1].lower()
    if extension in {".jpg", ".jpeg"}:
        return image_bytes.startswith(b"\xff\xd8\xff")
    if extension == ".png":
        return image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == ".gif":
        return image_bytes.startswith((b"GIF87a", b"GIF89a"))
    if extension == ".webp":
        return image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP"
    return False


def save_uploaded_bartender_tip_image(upload) -> tuple[str, str]:
    if upload is None or not upload.filename:
        return "", ""

    safe_name = secure_filename(upload.filename)
    extension = os.path.splitext(safe_name)[1].lower()
    if extension not in ALLOWED_BARTENDER_TIP_IMAGE_EXTENSIONS:
        return "", "Bartender tip QR upload must be a PNG, JPG, GIF, or WebP image."

    image_bytes = upload.stream.read(MAX_BARTENDER_TIP_IMAGE_BYTES + 1)
    if not image_bytes:
        return "", "Bartender tip QR upload was empty."
    if len(image_bytes) > MAX_BARTENDER_TIP_IMAGE_BYTES:
        return "", "Bartender tip QR upload must be 5 MB or smaller."
    if not image_bytes_match_extension(safe_name, image_bytes):
        return "", "Bartender tip QR upload does not look like a valid image file."

    upload_dir = app.config["BARTENDER_TIP_UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"bartender-tip-{uuid4().hex}{extension}"
    upload_path = os.path.join(upload_dir, filename)
    with open(upload_path, "wb") as image_file:
        image_file.write(image_bytes)

    return f"{BARTENDER_TIP_UPLOAD_URL_PREFIX}/{filename}", ""


def normalize_menu_category(raw_category: object) -> str:
    category = str(raw_category or "").strip().lower()
    return category if category in MENU_ITEM_CATEGORIES else "drink"


def normalize_drink_type(raw_type: object) -> str:
    drink_type = str(raw_type or "").strip().lower()
    return drink_type if drink_type in DRINK_TYPES else "standard"


def normalize_beverage_type(raw_type: object) -> str:
    beverage_type = str(raw_type or "").strip().lower()
    return beverage_type if beverage_type in BEVERAGE_TYPES else "alcoholic"


def drink_type_label(raw_type: object) -> str:
    return "Specialty" if normalize_drink_type(raw_type) == "specialty" else "Standard"


def beverage_type_label(raw_type: object) -> str:
    return "Non-alcoholic" if normalize_beverage_type(raw_type) == "non_alcoholic" else "Alcoholic"


def normalize_bartender_tip_settings(raw_settings: object) -> dict[str, object]:
    settings = copy.deepcopy(DEFAULT_BARTENDER_TIP_SETTINGS)
    if not isinstance(raw_settings, dict):
        return settings

    settings["enabled"] = bool(raw_settings.get("enabled", False))
    for key in ("display_name", "note", "zelle", "paypal", "venmo", "cash_app"):
        settings[key] = str(raw_settings.get(key, settings.get(key, "")) or "").strip()
    settings["image_url"] = safe_image_url(str(raw_settings.get("image_url", "") or ""))
    return settings


def menu_item_to_dict(item: dict[str, object]) -> dict[str, object]:
    category = normalize_menu_category(item.get("category"))
    drink_type = normalize_drink_type(item.get("drink_type"))
    beverage_type = normalize_beverage_type(item.get("beverage_type"))
    return {
        "id": str(item.get("id", "") or uuid4().hex),
        "name": str(item.get("name", "") or "").strip(),
        "category": category,
        "description": str(item.get("description", "") or "").strip(),
        "image_url": safe_image_url(str(item.get("image_url", "") or "")),
        "recipe": str(item.get("recipe", "") or "").strip(),
        "available": bool(item.get("available", True)),
        "drink_type": drink_type if category == "drink" else "standard",
        "beverage_type": beverage_type if category == "drink" else "non_alcoholic",
        "orderable": bool(item.get("orderable", True)) if category == "drink" else False,
        "created_at": str(item.get("created_at", "") or _utc_now_iso()),
    }


def normalize_menu_item(data: dict[str, object]) -> dict[str, object] | None:
    item = menu_item_to_dict(data)
    if not item["name"]:
        return None
    return item


def find_menu_item(item_id: str) -> dict[str, object] | None:
    return next((item for item in menu_items if str(item.get("id", "")) == item_id), None)


def normalize_drink_order(data: dict[str, object]) -> dict[str, object] | None:
    order_id = str(data.get("id", "") or uuid4().hex)
    menu_item_id = str(data.get("menu_item_id", "") or "")
    item_name = str(data.get("item_name", "") or "").strip()
    status = str(data.get("status", "received") or "received")
    if status not in DRINK_ORDER_STATUSES:
        status = "received"
    if not order_id or not item_name:
        return None

    completed_seconds = None
    try:
        raw_seconds = data.get("completed_seconds")
        completed_seconds = int(raw_seconds) if raw_seconds not in (None, "") else None
    except (TypeError, ValueError):
        completed_seconds = None
    try:
        specialty_sequence_number = int(data.get("specialty_sequence_number", 0) or 0)
    except (TypeError, ValueError):
        specialty_sequence_number = 0

    return {
        "id": order_id,
        "user_id": str(data.get("user_id", "") or ""),
        "username": str(data.get("username", "") or "").strip(),
        "email": normalize_email(str(data.get("email", "") or "")),
        "menu_item_id": menu_item_id,
        "item_name": item_name,
        "item_image_url": safe_image_url(str(data.get("item_image_url", "") or "")),
        "recipe": str(data.get("recipe", "") or "").strip(),
        "drink_type": normalize_drink_type(data.get("drink_type")),
        "beverage_type": normalize_beverage_type(data.get("beverage_type")),
        "orderable": bool(data.get("orderable", True)),
        "specialty_sequence_number": specialty_sequence_number,
        "specialty_extra_request": bool(data.get("specialty_extra_request", specialty_sequence_number > SPECIALTY_DRINK_INCLUDED_LIMIT)),
        "specialty_extra_window_open": bool(data.get("specialty_extra_window_open", specialty_sequence_number > SPECIALTY_DRINK_INCLUDED_LIMIT)),
        "status": status,
        "estimated_ready_at": str(data.get("estimated_ready_at", "") or ""),
        "created_at": str(data.get("created_at", "") or _utc_now_iso()),
        "started_at": str(data.get("started_at", "") or ""),
        "completed_at": str(data.get("completed_at", "") or ""),
        "completed_seconds": completed_seconds,
    }


def active_drink_orders() -> list[dict[str, object]]:
    return [order for order in drink_orders if order.get("status") in {"received", "in_progress"}]


def user_drink_orders(user_id: str) -> list[dict[str, object]]:
    return sorted(
        [order for order in drink_orders if str(order.get("user_id", "")) == user_id],
        key=lambda order: str(order.get("created_at", "")),
        reverse=True,
    )


def user_specialty_drink_orders(user_id: str) -> list[dict[str, object]]:
    return [
        order for order in user_drink_orders(user_id)
        if normalize_drink_type(order.get("drink_type")) == "specialty"
    ]


def user_specialty_drink_count(user_id: str) -> int:
    return len(user_specialty_drink_orders(user_id))


def can_order_menu_item(user_id: str, item: dict[str, object] | None) -> tuple[bool, str]:
    if not item:
        return False, "That menu item could not be found."
    if item.get("category") != "drink":
        return False, "Only drinks can be ordered from the portal right now."
    if not bool(item.get("available", True)):
        return False, "That drink is not available right now."
    if not bool(item.get("orderable", True)):
        return False, "That drink is available at the bar and does not need a portal order."

    if normalize_drink_type(item.get("drink_type")) == "specialty":
        specialty_count = user_specialty_drink_count(user_id)
        if specialty_count >= SPECIALTY_DRINK_INCLUDED_LIMIT and not specialty_extra_orders_are_open():
            return (
                False,
                "You have used tonight's 3 specialty drink orders. More specialty requests open after 11:00 PM if supplies last.",
            )

    return True, ""


def create_drink_order(user_id: str, account: dict[str, object], item: dict[str, object]) -> dict[str, object]:
    estimated_ready_at = estimate_drink_ready_at()
    drink_type = normalize_drink_type(item.get("drink_type"))
    specialty_sequence_number = (
        user_specialty_drink_count(user_id) + 1 if drink_type == "specialty" else 0
    )
    return {
        "id": uuid4().hex,
        "user_id": user_id,
        "username": str(account.get("username", session.get("username", "Guest"))),
        "email": normalize_email(str(account.get("email", "") or "")),
        "menu_item_id": str(item.get("id", "")),
        "item_name": str(item.get("name", "")),
        "item_image_url": str(item.get("image_url", "") or ""),
        "recipe": str(item.get("recipe", "") or ""),
        "drink_type": drink_type,
        "beverage_type": normalize_beverage_type(item.get("beverage_type")),
        "orderable": bool(item.get("orderable", True)),
        "specialty_sequence_number": specialty_sequence_number,
        "specialty_extra_request": drink_type == "specialty" and specialty_sequence_number > SPECIALTY_DRINK_INCLUDED_LIMIT,
        "specialty_extra_window_open": specialty_extra_orders_are_open(),
        "status": "received",
        "estimated_ready_at": estimated_ready_at,
        "created_at": _utc_now_iso(),
        "started_at": "",
        "completed_at": "",
        "completed_seconds": None,
    }


def ready_order_is_visible_on_dashboard(order: dict[str, object], now: datetime | None = None) -> bool:
    if order.get("status") != "complete":
        return False
    completed_at = parse_utc_iso(order.get("completed_at"))
    if not completed_at:
        return True
    current_time = now or datetime.now(timezone.utc)
    return completed_at + timedelta(seconds=DRINK_READY_DASHBOARD_SECONDS) >= current_time.astimezone(timezone.utc)


def bartender_tip_methods(settings: dict[str, object] | None = None) -> list[dict[str, str]]:
    source = settings or bartender_tip_settings
    labels = {
        "zelle": "Zelle",
        "paypal": "PayPal",
        "venmo": "Venmo",
        "cash_app": "Cash App",
    }
    return [
        {"label": label, "value": str(source.get(key, "") or "").strip()}
        for key, label in labels.items()
        if str(source.get(key, "") or "").strip()
    ]


def drink_order_priority_bucket(order: dict[str, object]) -> int:
    if order.get("status") == "in_progress":
        return 0
    if bool(order.get("specialty_extra_request")):
        return 2
    return 1


def completed_drink_order_durations() -> list[int]:
    durations = [
        int(order["completed_seconds"])
        for order in drink_orders
        if order.get("completed_seconds") and int(order.get("completed_seconds", 0) or 0) > 0
    ]
    return durations[-20:]


def average_drink_completion_seconds() -> int:
    durations = completed_drink_order_durations()
    if not durations:
        return DEFAULT_DRINK_ESTIMATE_SECONDS
    return max(60, int(sum(durations) / len(durations)))


def estimate_drink_ready_at() -> str:
    active_count = len(active_drink_orders()) + 1
    wait_seconds = average_drink_completion_seconds() * active_count
    return (datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)).isoformat().replace("+00:00", "Z")


def drink_order_status_label(status: object) -> str:
    labels = {
        "received": "Order received",
        "in_progress": "In progress",
        "complete": "Complete",
    }
    return labels.get(str(status), "Order received")


def find_drink_order(order_id: str) -> dict[str, object] | None:
    return next((order for order in drink_orders if str(order.get("id", "")) == order_id), None)


def build_drink_ready_override(order: dict[str, object]) -> dict[str, object]:
    attendee_name = str(order.get("username", "") or "Guest")
    item_name = str(order.get("item_name", "") or "your drink")
    return {
        "type": "drink_ready",
        "title": "Drink Ready",
        "highlight": attendee_name,
        "message": f"Your {item_name} is ready at the bar.",
        "image_url": str(order.get("item_image_url", "") or ""),
        "details": [
            item_name,
            "Pick it up while the spirits are still lively.",
        ],
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=DRINK_READY_OVERRIDE_SECONDS))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def cleanup_expired_display_notices() -> bool:
    global live_display_notice_override
    if not live_display_notice_override:
        return False
    expires_at = parse_utc_iso(live_display_notice_override.get("expires_at"))
    if expires_at and expires_at <= datetime.now(timezone.utc):
        live_display_notice_override = None
        persist_state_if_available()
        return True
    return False


def display_notice_types() -> set[str]:
    return {"drink_ready"}


def split_legacy_display_override(
    override: dict[str, object] | None,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    if not override:
        return None, None

    override_type = str(override.get("type", "") or "")
    if override_type in display_notice_types():
        return None, copy.deepcopy(override)
    return copy.deepcopy(override), None


def current_display_override() -> dict[str, object] | None:
    return live_display_notice_override or live_display_event_override


def normalize_dj_song(raw_song: object) -> dict[str, object] | None:
    if not isinstance(raw_song, dict):
        return None

    title = str(raw_song.get("title", "") or "").strip()
    artist = str(raw_song.get("artist", "") or "").strip()
    apple_music_id = str(raw_song.get("apple_music_id", "") or "").strip()
    if not title or not artist or not apple_music_id:
        return None

    try:
        duration_ms = max(0, int(raw_song.get("duration_ms", 0) or 0))
    except (TypeError, ValueError):
        duration_ms = 0

    return {
        "id": str(raw_song.get("id", "") or uuid4().hex),
        "apple_music_id": apple_music_id,
        "title": title,
        "artist": artist,
        "album": str(raw_song.get("album", "") or "").strip(),
        "artwork_url": safe_image_url(str(raw_song.get("artwork_url", "") or "")),
        "duration_ms": duration_ms,
        "explicit": bool(raw_song.get("explicit", False)),
        "enabled": bool(raw_song.get("enabled", True)),
        "created_at": str(raw_song.get("created_at", "") or _utc_now_iso()),
    }


def normalize_dj_song_request(raw_request: object) -> dict[str, object] | None:
    if not isinstance(raw_request, dict):
        return None

    requester_id = str(raw_request.get("requester_id", "") or "").strip()
    requester_name = str(raw_request.get("requester_name", "") or "").strip()
    raw_song = raw_request.get("song")
    song = normalize_dj_song(raw_song)
    if not requester_id or not requester_name or not song:
        return None

    return {
        "id": str(raw_request.get("id", "") or uuid4().hex),
        "requester_id": requester_id[:120],
        "requester_name": requester_name[:80],
        "requested_at": str(raw_request.get("requested_at", "") or _utc_now_iso()),
        "song": song,
    }


def find_dj_song_request(request_id: str) -> dict[str, object] | None:
    return next((entry for entry in dj_song_requests if str(entry.get("id", "")) == request_id), None)


def user_dj_song_requests(user_id: str) -> list[dict[str, object]]:
    return [request_entry for request_entry in dj_song_requests if request_entry.get("requester_id") == user_id]


def attendee_jukebox_state(user_id: str) -> dict[str, object]:
    receiver = dj_state.get("receiver", {})
    current_song = find_dj_song(str(receiver.get("current_song_id", "") if isinstance(receiver, dict) else ""))
    return {
        "now_playing": copy.deepcopy(current_song),
        "playback_status": str(receiver.get("playback_status", "stopped") if isinstance(receiver, dict) else "stopped"),
        "playlist": [copy.deepcopy(song) for song in dj_playlist if bool(song.get("enabled", True))],
        "pending_requests": copy.deepcopy(user_dj_song_requests(user_id)),
        "request_limit": MAX_DJ_SONG_REQUESTS_PER_ATTENDEE,
    }


def find_dj_song(song_id: str) -> dict[str, object] | None:
    return next((song for song in dj_playlist if str(song.get("id", "")) == song_id), None)


def enabled_dj_song_ids() -> list[str]:
    return [str(song.get("id", "")) for song in dj_playlist if bool(song.get("enabled", True))]


def dj_receiver_is_online(receiver: dict[str, object] | None = None) -> bool:
    source = receiver if isinstance(receiver, dict) else dj_state.get("receiver", {})
    if not isinstance(source, dict):
        return False
    last_seen = parse_utc_iso(source.get("last_seen_at"))
    return bool(last_seen and last_seen >= datetime.now(timezone.utc) - timedelta(seconds=DJ_RECEIVER_STALE_SECONDS))


def normalize_dj_state(raw_state: object) -> dict[str, object]:
    state = copy.deepcopy(DEFAULT_DJ_STATE)
    if not isinstance(raw_state, dict):
        return state

    try:
        state["command_revision"] = max(0, int(raw_state.get("command_revision", 0) or 0))
    except (TypeError, ValueError):
        state["command_revision"] = 0

    raw_receiver = raw_state.get("receiver")
    if isinstance(raw_receiver, dict):
        receiver = state["receiver"]
        receiver["id"] = str(raw_receiver.get("id", "") or "").strip()[:120]
        requested_status = str(raw_receiver.get("status", "offline") or "offline")
        receiver["status"] = requested_status if requested_status in DJ_RECEIVER_STATUSES else "error"
        receiver["authorization_status"] = str(raw_receiver.get("authorization_status", "") or "not_configured")[:80]
        receiver["audio_enabled"] = bool(raw_receiver.get("audio_enabled", False))
        playback_status = str(raw_receiver.get("playback_status", "stopped") or "stopped")
        receiver["playback_status"] = playback_status if playback_status in DJ_PLAYBACK_STATUSES else "unknown"
        receiver["current_song_id"] = str(raw_receiver.get("current_song_id", "") or "")
        try:
            receiver["playback_position_seconds"] = max(0, int(raw_receiver.get("playback_position_seconds", 0) or 0))
        except (TypeError, ValueError):
            receiver["playback_position_seconds"] = 0
        receiver["last_seen_at"] = str(raw_receiver.get("last_seen_at", "") or "")
        receiver["last_error"] = str(raw_receiver.get("last_error", "") or "").strip()[:500]

    raw_desired = raw_state.get("desired")
    if isinstance(raw_desired, dict):
        desired = state["desired"]
        requested_status = str(raw_desired.get("playback_status", "stopped") or "stopped")
        desired["playback_status"] = requested_status if requested_status in DJ_PLAYBACK_STATUSES else "stopped"
        desired["song_id"] = str(raw_desired.get("song_id", "") or "")
        raw_queue_order = raw_desired.get("queue_order", [])
        desired["queue_order"] = [str(song_id) for song_id in raw_queue_order] if isinstance(raw_queue_order, list) else []
        desired["shuffle_enabled"] = bool(raw_desired.get("shuffle_enabled", False))

    for key in ("current_command", "last_command"):
        raw_command = raw_state.get(key)
        if isinstance(raw_command, dict):
            state[key] = {
                "id": str(raw_command.get("id", "") or ""),
                "revision": int(raw_command.get("revision", 0) or 0),
                "action": str(raw_command.get("action", "") or ""),
                "song_id": str(raw_command.get("song_id", "") or ""),
                "queue_order": [str(song_id) for song_id in raw_command.get("queue_order", [])]
                if isinstance(raw_command.get("queue_order"), list)
                else [],
                "requested_at": str(raw_command.get("requested_at", "") or ""),
                "requested_by": str(raw_command.get("requested_by", "") or "")[:80],
                "status": str(raw_command.get("status", "pending") or "pending"),
                "acknowledged_at": str(raw_command.get("acknowledged_at", "") or ""),
                "error": str(raw_command.get("error", "") or "")[:500],
            }

    raw_reset = raw_state.get("last_reset")
    if isinstance(raw_reset, dict):
        reset_status = str(raw_reset.get("status", "pending") or "pending")
        state["last_reset"] = {
            "id": str(raw_reset.get("id", "") or ""),
            "revision": max(0, int(raw_reset.get("revision", 0) or 0)),
            "requested_at": str(raw_reset.get("requested_at", "") or ""),
            "requested_by": str(raw_reset.get("requested_by", "") or "")[:80],
            "status": reset_status if reset_status in {"pending", "acknowledged", "failed"} else "pending",
            "acknowledged_at": str(raw_reset.get("acknowledged_at", "") or ""),
            "error": str(raw_reset.get("error", "") or "")[:500],
        }

    return state


def queue_dj_command(action: str, song_id: str = "", requested_by: str = "Admin") -> dict[str, object] | None:
    if action not in DJ_COMMAND_ACTIONS:
        return None

    if action == "reset":
        return queue_dj_workflow_reset(requested_by)

    queue_order = enabled_dj_song_ids()
    if action in {"play_song", "play_playlist", "shuffle_playlist"} and not queue_order:
        return None

    if action == "play_song":
        song = find_dj_song(song_id)
        if not song or not bool(song.get("enabled", True)):
            return None
        queue_order = [song_id] + [candidate_id for candidate_id in queue_order if candidate_id != song_id]
    elif action == "shuffle_playlist":
        random.SystemRandom().shuffle(queue_order)
        song_id = queue_order[0]
    elif action == "play_playlist":
        song_id = queue_order[0]

    desired = dj_state["desired"]
    if action in {"play_song", "play_playlist", "shuffle_playlist", "next", "previous"}:
        desired["playback_status"] = "playing"
    elif action == "pause":
        desired["playback_status"] = "paused"
    elif action == "stop":
        desired["playback_status"] = "stopped"
    if song_id:
        desired["song_id"] = song_id
    if action in {"play_song", "play_playlist", "shuffle_playlist"}:
        desired["queue_order"] = queue_order
        desired["shuffle_enabled"] = action == "shuffle_playlist"

    revision = int(dj_state.get("command_revision", 0) or 0) + 1
    dj_state["command_revision"] = revision
    command = {
        "id": uuid4().hex,
        "revision": revision,
        "action": action,
        "song_id": song_id,
        "queue_order": copy.deepcopy(desired.get("queue_order", [])),
        "requested_at": _utc_now_iso(),
        "requested_by": requested_by,
        "status": "pending",
        "acknowledged_at": "",
        "error": "",
    }
    dj_state["current_command"] = command
    dj_state["last_reset"] = None
    return command


def queue_dj_workflow_reset(requested_by: str = "Admin") -> dict[str, object]:
    """Ask the display to stop and return the persisted DJ workflow to standby.

    Playlist records intentionally live outside this transient receiver state.
    The reset remains pending until the display consumes it, so an offline TV
    never produces a misleading successful reset in the admin workspace.
    """
    revision = int(dj_state.get("command_revision", 0) or 0) + 1
    requested_at = _utc_now_iso()
    command = {
        "id": uuid4().hex,
        "revision": revision,
        "action": "reset",
        "song_id": "",
        "queue_order": [],
        "requested_at": requested_at,
        "requested_by": requested_by,
        "status": "pending",
        "acknowledged_at": "",
        "error": "",
    }
    dj_state["command_revision"] = revision
    dj_state["current_command"] = command
    dj_state["last_command"] = None
    dj_state["last_reset"] = {
        "id": command["id"],
        "revision": revision,
        "requested_at": requested_at,
        "requested_by": requested_by,
        "status": "pending",
        "acknowledged_at": "",
        "error": "",
    }
    dj_state["desired"] = copy.deepcopy(DEFAULT_DJ_STATE["desired"])
    return command


def reset_dj_workflow_state(reset_record: dict[str, object]) -> None:
    """Clear only transient DJ workflow data, retaining the curated playlist."""
    revision = int(dj_state.get("command_revision", 0) or 0)
    dj_state.clear()
    dj_state.update(copy.deepcopy(DEFAULT_DJ_STATE))
    dj_state["command_revision"] = revision
    dj_state["last_reset"] = reset_record


def record_dj_receiver_state(payload: dict[str, object]) -> None:
    receiver = dj_state["receiver"]
    receiver["id"] = str(payload.get("receiver_id", "") or receiver.get("id", ""))[:120]
    requested_status = str(payload.get("status", "") or receiver.get("status", "offline"))
    receiver["status"] = requested_status if requested_status in DJ_RECEIVER_STATUSES else "error"
    receiver["authorization_status"] = str(payload.get("authorization_status", "") or receiver.get("authorization_status", ""))[:80]
    receiver["audio_enabled"] = bool(payload.get("audio_enabled", False))
    playback_status = str(payload.get("playback_status", "") or receiver.get("playback_status", "stopped"))
    receiver["playback_status"] = playback_status if playback_status in DJ_PLAYBACK_STATUSES else "unknown"
    receiver["current_song_id"] = str(payload.get("current_song_id", "") or receiver.get("current_song_id", ""))
    try:
        receiver["playback_position_seconds"] = max(0, int(payload.get("playback_position_seconds", 0) or 0))
    except (TypeError, ValueError):
        receiver["playback_position_seconds"] = 0
    receiver["last_seen_at"] = _utc_now_iso()
    reported_error = str(payload.get("error", "") or "").strip()[:500]
    if reported_error:
        receiver["last_error"] = reported_error
    elif bool(payload.get("clear_error", False)):
        receiver["last_error"] = ""

    current_command = dj_state.get("current_command")
    acknowledged_id = str(payload.get("acknowledged_command_id", "") or "")
    if isinstance(current_command, dict) and acknowledged_id and acknowledged_id == current_command.get("id"):
        succeeded = bool(payload.get("command_succeeded", False))
        if current_command.get("action") == "reset":
            reset_record = copy.deepcopy(dj_state.get("last_reset") or {})
            reset_record["status"] = "acknowledged" if succeeded else "failed"
            reset_record["acknowledged_at"] = _utc_now_iso()
            reset_record["error"] = "" if succeeded else receiver["last_error"] or "The live display could not complete the DJ reset."
            reset_dj_workflow_state(reset_record)
            return
        current_command["status"] = "succeeded" if succeeded else "failed"
        current_command["acknowledged_at"] = _utc_now_iso()
        current_command["error"] = "" if succeeded else receiver["last_error"] or "The display could not complete the DJ command."
        dj_state["last_command"] = copy.deepcopy(current_command)
        dj_state["current_command"] = None


def dj_command_flow() -> list[dict[str, str]]:
    receiver = dj_state.get("receiver", {})
    current_command = dj_state.get("current_command")
    last_command = dj_state.get("last_command")
    last_reset = dj_state.get("last_reset")
    receiver_online = dj_receiver_is_online(receiver if isinstance(receiver, dict) else None)
    receiver_ready = bool(
        isinstance(receiver, dict)
        and receiver_online
        and receiver.get("status") == "ready"
        and receiver.get("authorization_status") == "authorized"
        and receiver.get("audio_enabled")
    )
    requested_state = "ready" if receiver_ready else "idle"
    requested_detail = "DJ controls are armed and ready for a song." if receiver_ready else "No command waiting."
    command_error = ""
    if isinstance(current_command, dict):
        requested_state = "pending"
        requested_detail = "DJ reset is waiting for the live display." if current_command.get("action") == "reset" else "Command saved in Redis."
        requested_at = parse_utc_iso(current_command.get("requested_at"))
        if requested_at and requested_at < datetime.now(timezone.utc) - timedelta(seconds=DJ_COMMAND_TIMEOUT_SECONDS):
            requested_state = "timed_out"
            command_error = "The live display has not confirmed this command yet."
    elif isinstance(last_reset, dict):
        if last_reset.get("status") == "acknowledged":
            requested_state = "confirmed"
            requested_detail = "DJ workflow reset was acknowledged by the live display."
        elif last_reset.get("status") == "failed":
            requested_state = "failed"
            requested_detail = str(last_reset.get("error", "") or "The DJ reset did not complete.")
    elif isinstance(last_command, dict):
        if last_command.get("status") == "failed":
            requested_state = "failed"
            requested_detail = str(last_command.get("error", "") or "The display could not complete the DJ command.")
        elif last_command.get("status") == "succeeded":
            requested_state = "confirmed"
            requested_detail = "The live display confirmed the last DJ command."

    audio_state = str(receiver.get("playback_status", "stopped") or "stopped")
    audio_detail = command_error or ("DJ audio is enabled." if receiver.get("audio_enabled") else "Use Enable DJ Audio on the live display once.")
    if receiver_ready and audio_state == "stopped":
        audio_state = "ready"
        audio_detail = "Audio is unlocked and ready to play."

    return [
        {"label": "Admin request", "state": requested_state, "detail": requested_detail},
        {"label": "Live display", "state": "connected" if receiver_online else "offline", "detail": "Receiver heartbeat is current." if receiver_online else "Open or refresh the live display on the TV."},
        {"label": "Apple Music", "state": str(receiver.get("authorization_status", "not_configured") or "not_configured"), "detail": str(receiver.get("last_error", "") or "Authorize Apple Music on the display when needed.")},
        {"label": "Audio output", "state": audio_state, "detail": audio_detail},
    ]


def dj_view_state() -> dict[str, object]:
    view = copy.deepcopy(dj_state)
    receiver = view.get("receiver", {})
    if isinstance(receiver, dict):
        receiver["online"] = dj_receiver_is_online(receiver)
        if not receiver["online"]:
            receiver["effective_status"] = "offline"
        else:
            receiver["effective_status"] = receiver.get("status", "offline")
    current_song = find_dj_song(str(receiver.get("current_song_id", "") if isinstance(receiver, dict) else ""))
    desired_song = find_dj_song(str(view.get("desired", {}).get("song_id", ""))) if isinstance(view.get("desired"), dict) else None
    view["current_song"] = copy.deepcopy(current_song)
    view["desired_song"] = copy.deepcopy(desired_song)
    view["playlist"] = copy.deepcopy(dj_playlist)
    view["flow"] = dj_command_flow()
    return view


def apple_music_is_configured() -> bool:
    return bool(
        app.config["APPLE_MUSIC_DEVELOPER_TOKEN"]
        or (
            app.config["APPLE_MUSIC_TEAM_ID"]
            and app.config["APPLE_MUSIC_KEY_ID"]
            and app.config["APPLE_MUSIC_PRIVATE_KEY"]
        )
    )


def apple_music_web_origin() -> str:
    """Return the canonical browser origin Apple should bind a MusicKit token to."""
    raw_origin = str(app.config.get("APPLE_MUSIC_WEB_ORIGIN", "") or "").strip()
    parsed = urlparse(raw_origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def apple_music_developer_token() -> str:
    direct_token = app.config["APPLE_MUSIC_DEVELOPER_TOKEN"]
    if direct_token:
        return direct_token
    if not apple_music_is_configured():
        raise RuntimeError("Apple Music has not been configured for the DJ receiver.")

    try:
        import jwt
    except ImportError as exc:
        raise RuntimeError("PyJWT is required to sign Apple Music developer tokens.") from exc

    now = int(time.time())
    claims = {"iss": app.config["APPLE_MUSIC_TEAM_ID"], "iat": now, "exp": now + 60 * 60 * 24 * 180}
    # MusicKit on the Web uses this claim while exchanging the subscriber's
    # authorization for a Music User Token. Omitting it can allow catalog
    # searches but fail the subsequent /v1/me/storefront request.
    web_origin = apple_music_web_origin()
    if web_origin:
        claims["origin"] = web_origin

    return str(
        jwt.encode(
            claims,
            app.config["APPLE_MUSIC_PRIVATE_KEY"],
            algorithm="ES256",
            headers={"kid": app.config["APPLE_MUSIC_KEY_ID"]},
        )
    )


APPLE_MUSIC_CATALOG_PAGE_SIZE = 8
APPLE_MUSIC_CATALOG_MAX_OFFSET = 200


def parse_catalog_search_offset(raw_offset: str | None) -> int | None:
    """Return a bounded catalog result offset without accepting provider URLs."""
    if raw_offset in {None, ""}:
        return 0
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        return None
    if (
        offset < 0
        or offset > APPLE_MUSIC_CATALOG_MAX_OFFSET
        or offset % APPLE_MUSIC_CATALOG_PAGE_SIZE != 0
    ):
        return None
    return offset


def search_apple_music_catalog(query: str, offset: int = 0) -> dict[str, object]:
    query = query.strip()
    if not query:
        return {"results": [], "next_offset": None}
    encoded_query = urlencode(
        {
            "term": query,
            "types": "songs",
            "limit": APPLE_MUSIC_CATALOG_PAGE_SIZE,
            "offset": offset,
        }
    )
    url = f"https://api.music.apple.com/v1/catalog/{app.config['APPLE_MUSIC_STOREFRONT']}/search?{encoded_query}"
    api_request = UrlRequest(url, headers={"Authorization": f"Bearer {apple_music_developer_token()}"})
    try:
        with urlopen(api_request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # Apple returns provider-specific HTTP errors.
        raise RuntimeError("Apple Music catalog search is unavailable right now.") from exc

    song_results = payload.get("results", {}).get("songs", {}) if isinstance(payload, dict) else {}
    results = song_results.get("data", []) if isinstance(song_results, dict) else []
    songs: list[dict[str, object]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        attributes = result.get("attributes", {})
        if not isinstance(attributes, dict):
            continue
        artwork = attributes.get("artwork", {})
        artwork_url = str(artwork.get("url", "") or "") if isinstance(artwork, dict) else ""
        if artwork_url:
            artwork_url = artwork_url.replace("{w}", "300").replace("{h}", "300").replace("{f}", "jpg")
        song = normalize_dj_song(
            {
                "id": uuid4().hex,
                "apple_music_id": result.get("id", ""),
                "title": attributes.get("name", ""),
                "artist": attributes.get("artistName", ""),
                "album": attributes.get("albumName", ""),
                "artwork_url": artwork_url,
                "duration_ms": attributes.get("durationInMillis", 0),
                "explicit": attributes.get("contentRating") == "explicit",
            }
        )
        if song:
            songs.append(song)
    # Apple returns an opaque `next` URL. We use it only as a signal that a
    # following page exists; the browser passes a bounded numeric offset to our
    # own endpoint, never a provider-controlled URL.
    has_next_page = bool(song_results.get("next")) if isinstance(song_results, dict) else False
    return {
        "results": songs,
        "next_offset": offset + APPLE_MUSIC_CATALOG_PAGE_SIZE if has_next_page else None,
    }


def build_menu_sections() -> dict[str, list[dict[str, object]]]:
    return {
        "drinks": [item for item in menu_items if item.get("category") == "drink"],
        "food": [item for item in menu_items if item.get("category") == "food"],
    }


def costume_signup_to_dict(signup: CostumeSignup) -> dict[str, str]:
    return {
        "id": signup.id,
        "name": signup.name,
        "costume": signup.costume,
        "contact": signup.contact,
    }


def costume_signup_from_dict(data: dict[str, object]) -> CostumeSignup:
    return CostumeSignup(
        id=str(data.get("id", "") or uuid4().hex),
        name=str(data.get("name", "") or ""),
        costume=str(data.get("costume", "") or ""),
        contact=str(data.get("contact", "") or ""),
    )


def normalize_karaoke_youtube(raw_youtube: object, youtube_link: str = "") -> dict[str, object]:
    source = raw_youtube if isinstance(raw_youtube, dict) else {}
    video_id = parse_youtube_video_id(source.get("video_id") or youtube_link)
    return {
        "video_id": video_id,
        "title": str(source.get("title", "") or "").strip()[:300],
        "channel_id": str(source.get("channel_id", "") or "").strip()[:120],
        "channel_title": str(source.get("channel_title", "") or "").strip()[:180],
        "thumbnail_url": safe_image_url(str(source.get("thumbnail_url", "") or "")),
        "duration_seconds": max(0, _safe_int(source.get("duration_seconds"), 0)),
        "privacy_status": str(source.get("privacy_status", "") or "").strip()[:40],
        "upload_status": str(source.get("upload_status", "") or "").strip()[:40],
        "embeddable": bool(source.get("embeddable", False)),
        "age_restricted": bool(source.get("age_restricted", False)),
        "region_allowed": bool(source.get("region_allowed", True)),
        "available": bool(source.get("available", bool(video_id))),
        "last_verified_at": str(source.get("last_verified_at", "") or ""),
        "watch_url": canonical_watch_url(video_id),
    }


def normalize_karaoke_workflow(raw_workflow: object, *, has_video: bool) -> dict[str, object]:
    source = raw_workflow if isinstance(raw_workflow, dict) else {}
    workflow = copy.deepcopy(DEFAULT_KARAOKE_WORKFLOW)
    workflow.update({key: copy.deepcopy(value) for key, value in source.items() if key in workflow})

    validation_status = str(workflow.get("video_validation_status", "pending") or "pending")
    approval_status = str(workflow.get("approval_status", "pending") or "pending")
    playlist_status = str(workflow.get("playlist_sync_status", "not_started") or "not_started")
    performance_status = str(workflow.get("performance_status", "waiting") or "waiting")
    workflow["video_validation_status"] = (
        validation_status if validation_status in KARAOKE_VIDEO_VALIDATION_STATUSES else "pending"
    )
    workflow["approval_status"] = (
        approval_status if approval_status in KARAOKE_APPROVAL_STATUSES else "pending"
    )
    workflow["playlist_sync_status"] = (
        playlist_status if playlist_status in KARAOKE_PLAYLIST_SYNC_STATUSES else "not_started"
    )
    workflow["performance_status"] = (
        performance_status if performance_status in KARAOKE_PERFORMANCE_STATUSES else "waiting"
    )
    if not has_video and not source:
        workflow["video_validation_status"] = "unavailable"

    workflow["playlist_item_id"] = str(workflow.get("playlist_item_id", "") or "")[:180]
    workflow["playlist_revision"] = max(1, _safe_int(workflow.get("playlist_revision"), 1))
    workflow["operation_id"] = str(workflow.get("operation_id", "") or "")[:120]
    workflow["operation_action"] = str(workflow.get("operation_action", "") or "")[:80]
    workflow["operation_started_at"] = str(workflow.get("operation_started_at", "") or "")
    workflow["last_sync_error_code"] = str(workflow.get("last_sync_error_code", "") or "")[:120]
    workflow["last_sync_error_message"] = str(workflow.get("last_sync_error_message", "") or "")[:500]
    for key in ("approved_at", "approved_by", "called_at", "started_at", "completed_at"):
        workflow[key] = str(workflow.get(key, "") or "")[:180]
    return workflow


def normalize_karaoke_history(raw_history: object) -> list[dict[str, object]]:
    if not isinstance(raw_history, list):
        return []
    history: list[dict[str, object]] = []
    for raw_event in raw_history[-KARAOKE_HISTORY_LIMIT:]:
        if not isinstance(raw_event, dict):
            continue
        event = str(raw_event.get("event", "") or "").strip()[:80]
        if not event:
            continue
        history.append(
            {
                "event": event,
                "at": str(raw_event.get("at", "") or ""),
                "actor_id": str(raw_event.get("actor_id", "") or "")[:120],
                "actor_name": str(raw_event.get("actor_name", "") or "")[:120],
                "detail": str(raw_event.get("detail", "") or "")[:500],
            }
        )
    return history


def append_karaoke_history(
    signup: KaraokeSignup,
    event: str,
    *,
    detail: str = "",
    actor_id: str = "",
    actor_name: str = "",
) -> None:
    signup.history.append(
        {
            "event": event[:80],
            "at": _utc_now_iso(),
            "actor_id": actor_id[:120],
            "actor_name": actor_name[:120],
            "detail": detail[:500],
        }
    )
    if len(signup.history) > KARAOKE_HISTORY_LIMIT:
        signup.history[:] = signup.history[-KARAOKE_HISTORY_LIMIT:]


def karaoke_entry_is_active(signup: KaraokeSignup) -> bool:
    approval = str(signup.workflow.get("approval_status", "pending"))
    performance = str(signup.workflow.get("performance_status", "waiting"))
    return approval == "approved" and performance not in {"completed", "skipped"}


def karaoke_entry_is_ready(signup: KaraokeSignup) -> bool:
    return (
        signup.workflow.get("video_validation_status") == "verified"
        and signup.workflow.get("approval_status") == "approved"
        and signup.workflow.get("playlist_sync_status") == "synced"
        and signup.workflow.get("performance_status") == "waiting"
    )


def karaoke_entry_can_stage(signup: KaraokeSignup) -> bool:
    if app.config.get("YOUTUBE_KARAOKE_ENABLED"):
        return karaoke_entry_is_ready(signup)
    return signup.workflow.get("performance_status") == "waiting"


def karaoke_workflow_steps(signup: KaraokeSignup) -> list[dict[str, str]]:
    workflow = signup.workflow
    validation = str(workflow.get("video_validation_status", "pending"))
    approval = str(workflow.get("approval_status", "pending"))
    playlist = str(workflow.get("playlist_sync_status", "not_started"))
    performance = str(workflow.get("performance_status", "waiting"))
    terminal = approval in {"rejected", "cancelled"}

    def state(completed: bool, current: bool = False, attention: bool = False) -> str:
        if attention:
            return "attention"
        if completed:
            return "complete"
        if current and not terminal:
            return "current"
        return "waiting"

    return [
        {"key": "submitted", "label": "Submitted", "state": "complete"},
        {
            "key": "verified",
            "label": "Video verified",
            "state": state(
                validation == "verified",
                validation == "pending",
                validation in {"failed", "unavailable"},
            ),
        },
        {
            "key": "approved",
            "label": "Approved",
            "state": state(
                approval == "approved",
                validation == "verified" and approval == "pending",
                approval in {"rejected", "cancelled"},
            ),
        },
        {
            "key": "playlist",
            "label": "Playlist synced",
            "state": state(
                playlist == "synced",
                approval == "approved" and playlist in {"not_started", "pending", "out_of_order"},
                playlist in {"failed", "removal_pending"},
            ),
        },
        {
            "key": "ready",
            "label": "Ready",
            "state": state(
                karaoke_entry_is_ready(signup) or performance in {"called", "on_stage", "completed"},
                playlist == "synced" and performance == "waiting",
            ),
        },
        {
            "key": "stage",
            "label": "On stage",
            "state": state(
                performance in {"on_stage", "completed"},
                performance == "called",
                performance == "skipped",
            ),
        },
        {
            "key": "complete",
            "label": "Complete",
            "state": state(performance == "completed", performance == "on_stage"),
        },
    ]


def youtube_config() -> YouTubeConfig:
    return YouTubeConfig(
        api_key=str(app.config.get("YOUTUBE_API_KEY", "") or ""),
        client_id=str(app.config.get("YOUTUBE_CLIENT_ID", "") or ""),
        client_secret=str(app.config.get("YOUTUBE_CLIENT_SECRET", "") or ""),
        refresh_token=str(app.config.get("YOUTUBE_REFRESH_TOKEN", "") or ""),
        region_code=str(app.config.get("YOUTUBE_REGION_CODE", "US") or "US"),
    )


def youtube_service() -> YouTubeService:
    return YouTubeService(youtube_config())


def youtube_vault_store() -> VaultYouTubeSecretStore:
    return VaultYouTubeSecretStore(
        vault_addr=str(app.config.get("YOUTUBE_VAULT_ADDR", "") or ""),
        aws_auth_role=str(app.config.get("YOUTUBE_VAULT_AWS_AUTH_ROLE", "") or ""),
        secret_path=str(app.config.get("YOUTUBE_VAULT_SECRET_PATH", "") or ""),
    )


def youtube_playlist_note(signup: KaraokeSignup) -> str:
    revision = max(1, _safe_int(signup.workflow.get("playlist_revision"), 1))
    return f"{YOUTUBE_PLAYLIST_NOTE_PREFIX}:{signup.id}:{revision}"


def normalized_karaoke_clear_operation() -> dict[str, object]:
    defaults = copy.deepcopy(DEFAULT_YOUTUBE_KARAOKE_STATE["clear_operation"])
    raw = youtube_karaoke.get("clear_operation")
    if not isinstance(raw, dict):
        return defaults
    for key in defaults:
        if key in raw:
            defaults[key] = copy.deepcopy(raw[key])
    raw_target_item_ids = defaults.get("target_item_ids", [])
    if not isinstance(raw_target_item_ids, list):
        raw_target_item_ids = []
    defaults["target_item_ids"] = list(
        dict.fromkeys(
            str(item_id)
            for item_id in raw_target_item_ids
            if str(item_id)
        )
    )
    raw_failed_item_ids = defaults.get("failed_item_ids", [])
    if not isinstance(raw_failed_item_ids, list):
        raw_failed_item_ids = []
    defaults["failed_item_ids"] = list(
        dict.fromkeys(
            str(item_id)
            for item_id in raw_failed_item_ids
            if str(item_id)
        )
    )
    for key in (
        "record_count",
        "target_count",
        "deleted_count",
        "failed_count",
    ):
        defaults[key] = max(0, _safe_int(defaults.get(key), 0))
    return defaults


def karaoke_clear_blocks_mutation() -> bool:
    return str(normalized_karaoke_clear_operation().get("status", "")) in (
        KARAOKE_CLEAR_ACTIVE_STATUSES | {"failed"}
    )


def require_karaoke_clear_idle() -> None:
    if karaoke_clear_blocks_mutation():
        raise ValueError(
            "Karaoke queue clearing is in progress or needs attention. "
            "Finish or retry that operation first."
        )


def reset_karaoke_runtime_state() -> None:
    global live_display_event_override
    karaoke_state.clear()
    karaoke_state.update(copy.deepcopy(DEFAULT_KARAOKE_STATE))
    if live_display_event_override and str(
        live_display_event_override.get("type", "")
    ).startswith("karaoke_"):
        live_display_event_override = None


def find_matching_youtube_playlist_item(
    playlist_items: list[dict[str, object]],
    *,
    playlist_item_id: str = "",
    note: str = "",
    video_id: str = "",
    expected_position: int | None = None,
    excluded_item_ids: set[str] | None = None,
) -> dict[str, object] | None:
    """Match an app entry without requiring YouTube to round-trip item notes.

    YouTube accepts ``contentDetails.note`` on playlist item writes, but some
    accounts return an empty note on later reads. Persisted playlist item IDs
    remain authoritative; video and position are conservative recovery
    fallbacks for an insert whose result was uncertain.
    """

    excluded = excluded_item_ids or set()

    def available(item: dict[str, object]) -> bool:
        return str(item.get("playlist_item_id", "") or "") not in excluded

    if playlist_item_id:
        by_id = next(
            (
                item
                for item in playlist_items
                if available(item)
                and str(item.get("playlist_item_id", "") or "") == playlist_item_id
            ),
            None,
        )
        if by_id and (
            not video_id or str(by_id.get("video_id", "") or "") == video_id
        ):
            return by_id

    if note:
        by_note = next(
            (
                item
                for item in playlist_items
                if available(item) and str(item.get("note", "") or "") == note
            ),
            None,
        )
        if by_note and (
            not video_id or str(by_note.get("video_id", "") or "") == video_id
        ):
            return by_note

    if not video_id:
        return None
    video_candidates = [
        item
        for item in playlist_items
        if available(item) and str(item.get("video_id", "") or "") == video_id
    ]
    if expected_position is not None:
        positioned = [
            item
            for item in video_candidates
            if _safe_int(item.get("position"), -1) == expected_position
        ]
        if len(positioned) == 1:
            return positioned[0]
    return video_candidates[0] if len(video_candidates) == 1 else None


def find_karaoke_signup(entry_id: str) -> KaraokeSignup | None:
    return next((signup for signup in karaoke_signups if signup.id == entry_id), None)


def approved_karaoke_signups(*, include_completed: bool = False) -> list[KaraokeSignup]:
    entries = [
        signup
        for signup in karaoke_signups
        if signup.workflow.get("approval_status") == "approved"
    ]
    if include_completed:
        return entries
    return [
        signup
        for signup in entries
        if signup.workflow.get("performance_status") not in {"completed", "skipped"}
    ]


def active_karaoke_signups() -> list[KaraokeSignup]:
    if app.config.get("YOUTUBE_KARAOKE_ENABLED"):
        return approved_karaoke_signups()
    return [
        signup
        for signup in karaoke_signups
        if signup.workflow.get("performance_status") not in {"completed", "skipped"}
    ]


def public_karaoke_signups() -> list[KaraokeSignup]:
    if not app.config.get("YOUTUBE_KARAOKE_ENABLED"):
        return list(karaoke_signups)
    return [
        signup
        for signup in approved_karaoke_signups(include_completed=False)
        if signup.workflow.get("playlist_sync_status") == "synced"
    ]


def refresh_karaoke_stage_selection() -> None:
    current_id = str(karaoke_state.get("current_singer_id", "") or "")
    active_entries = active_karaoke_signups()
    active_ids = [signup.id for signup in active_entries]
    if current_id not in active_ids:
        current_id = next(
            (
                signup.id
                for signup in active_entries
                if signup.workflow.get("performance_status") in {"called", "on_stage"}
            ),
            "",
        )
    karaoke_state["current_singer_id"] = current_id or None
    karaoke_state["current_singer_index"] = (
        active_ids.index(current_id) if current_id in active_ids else None
    )

    next_id = ""
    if current_id in active_ids:
        current_position = active_ids.index(current_id)
        next_id = next(
            (
                signup.id
                for signup in active_entries[current_position + 1 :]
                if karaoke_entry_can_stage(signup)
            ),
            "",
        )
    if not next_id:
        next_id = next(
            (
                signup.id
                for signup in active_entries
                if signup.id != current_id and karaoke_entry_can_stage(signup)
            ),
            "",
        )
    karaoke_state["next_singer_id"] = next_id or None


def karaoke_signup_view(signup: KaraokeSignup) -> dict[str, object]:
    workflow = copy.deepcopy(signup.workflow)
    is_stale = False
    if workflow.get("operation_id"):
        operation_started = parse_utc_iso(workflow.get("operation_started_at"))
        is_stale = bool(
            operation_started
            and operation_started
            < datetime.now(timezone.utc) - timedelta(seconds=KARAOKE_OPERATION_STALE_SECONDS)
        )
    needs_attention = (
        workflow.get("video_validation_status") in {"failed", "unavailable"}
        or workflow.get("playlist_sync_status") in {"failed", "out_of_order", "removal_pending"}
        or is_stale
    )
    return {
        **karaoke_signup_to_dict(signup),
        "workflow": workflow,
        "steps": karaoke_workflow_steps(signup),
        "ready": karaoke_entry_is_ready(signup),
        "needs_attention": needs_attention,
        "operation_stale": is_stale,
        "queue_position": next(
            (
                index + 1
                for index, entry in enumerate(active_karaoke_signups())
                if entry.id == signup.id
            ),
            None,
        ),
    }


def karaoke_admin_view_state() -> dict[str, object]:
    ensure_signup_ids()
    refresh_karaoke_stage_selection()
    entries = [karaoke_signup_view(signup) for signup in karaoke_signups]
    clear_operation = normalized_karaoke_clear_operation()
    managed_playlist_item_count = len(
        {
            str(signup.workflow.get("playlist_item_id", "") or "")
            for signup in karaoke_signups
            if signup.workflow.get("playlist_item_id")
        }
    )
    pending = (
        [
            entry
            for entry in entries
            if entry["workflow"].get("approval_status") == "pending"
        ]
        if app.config.get("YOUTUBE_KARAOKE_ENABLED")
        else []
    )
    active = [karaoke_signup_view(signup) for signup in active_karaoke_signups()]
    completed = [
        entry
        for entry in entries
        if entry["workflow"].get("performance_status") in {"completed", "skipped"}
        or entry["workflow"].get("approval_status") in {"rejected", "cancelled"}
    ]
    attention = (
        [entry for entry in entries if entry.get("needs_attention")]
        if app.config.get("YOUTUBE_KARAOKE_ENABLED")
        else []
    )
    connection_needs_attention = bool(app.config.get("YOUTUBE_KARAOKE_ENABLED")) and (
        not youtube_config().search_configured
        or not youtube_config().oauth_client_configured
        or not youtube_config().playlist_configured
        or not youtube_karaoke.get("playlist_id")
        or youtube_karaoke.get("connection_status") != "connected"
    )
    current = find_karaoke_signup(str(karaoke_state.get("current_singer_id", "") or ""))
    next_signup = find_karaoke_signup(str(karaoke_state.get("next_singer_id", "") or ""))
    remaining_seconds = sum(
        max(0, _safe_int(signup.youtube.get("duration_seconds"), 0))
        for signup in active_karaoke_signups()
    )
    return {
        "enabled": bool(app.config.get("YOUTUBE_KARAOKE_ENABLED")),
        "search_configured": youtube_config().search_configured,
        "oauth_client_configured": youtube_config().oauth_client_configured,
        "playlist_configured": youtube_config().playlist_configured,
        "youtube": copy.deepcopy(youtube_karaoke),
        "pending": pending,
        "active": active,
        "attention": attention,
        "connection_needs_attention": connection_needs_attention,
        "history": completed,
        "record_count": len(karaoke_signups),
        "managed_playlist_item_count": managed_playlist_item_count,
        "clear_operation": {
            key: copy.deepcopy(value)
            for key, value in clear_operation.items()
            if key not in {"target_item_ids", "failed_item_ids"}
        },
        "current": karaoke_signup_view(current) if current else None,
        "next": karaoke_signup_view(next_signup) if next_signup else None,
        "metrics": {
            "pending": len(pending),
            "attention": len(attention) + int(connection_needs_attention),
            "ready": sum(
                1
                for signup in active_karaoke_signups()
                if karaoke_entry_can_stage(signup)
            ),
            "completed": sum(
                1
                for entry in entries
                if entry["workflow"].get("performance_status") == "completed"
            ),
            "remaining_seconds": remaining_seconds,
        },
        "party_started": bool(karaoke_state.get("party_started")),
        "stage_mode": str(karaoke_state.get("stage_mode", "standby") or "standby"),
    }


def build_karaoke_stage_override(signup: KaraokeSignup, mode: str) -> dict[str, object]:
    labels = {
        "call": ("Up Next", "Get ready at the microphone."),
        "on_stage": ("Now Singing", "Cheer them on!"),
        "complete": ("Karaoke", "Give it up for our singer!"),
    }
    title, message = labels.get(mode, labels["call"])
    return {
        "type": f"karaoke_{mode}",
        "title": title,
        "highlight": signup.name,
        "message": message,
        "image_url": str(signup.youtube.get("thumbnail_url", "") or ""),
        "details": [
            f'"{signup.song_title}"',
            f"by {signup.artist}",
        ],
    }


def youtube_search_cache_key(query: str, page_token: str) -> str:
    signature = hashlib.sha256(f"{query.casefold()}|{page_token}".encode("utf-8")).hexdigest()
    return redis_key(f"youtube-search:{signature}")


def youtube_search_budget_keys(user_id: str) -> tuple[str, str]:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        redis_key(f"youtube-search-budget:{day}"),
        redis_key(f"youtube-search-account:{day}:{hashlib.sha256(user_id.encode('utf-8')).hexdigest()}"),
    )


def increment_youtube_search_budget(user_id: str) -> None:
    if not redis_state_available:
        return
    global_key, account_key = youtube_search_budget_keys(user_id)
    global_count = int(redis_client.get(global_key) or 0)
    account_count = int(redis_client.get(account_key) or 0)
    if global_count >= max(1, int(app.config["YOUTUBE_SEARCH_DAILY_BUDGET"])):
        raise YouTubeApiError(
            "search_budget_exhausted",
            "YouTube search has reached its event safety limit for today. Paste a direct YouTube link instead.",
        )
    if account_count >= max(1, int(app.config["YOUTUBE_SEARCH_ACCOUNT_LIMIT"])):
        raise YouTubeApiError(
            "search_rate_limited",
            "You have reached the current YouTube search limit. Paste a direct YouTube link or ask the host for help.",
        )
    global_count = redis_client.incr(global_key)
    account_count = redis_client.incr(account_key)
    if global_count == 1:
        redis_client.expire(global_key, 60 * 60 * 48)
    if account_count == 1:
        redis_client.expire(account_key, 60 * 60 * 48)


def search_youtube_karaoke(query: str, *, page_token: str, user_id: str) -> dict[str, object]:
    cleaned_query = " ".join(str(query or "").split())
    if cleaned_query and "karaoke" not in cleaned_query.casefold().split():
        cleaned_query = f"{cleaned_query} karaoke"
    if not cleaned_query or len(cleaned_query) > YOUTUBE_SEARCH_QUERY_MAX_LENGTH:
        raise YouTubeApiError(
            "invalid_query",
            f"Enter a search between 1 and {YOUTUBE_SEARCH_QUERY_MAX_LENGTH} characters.",
        )
    cache_key = youtube_search_cache_key(cleaned_query, page_token)
    if redis_state_available:
        cached = redis_client.get(cache_key)
        if cached:
            try:
                payload = json.loads(cached)
                if isinstance(payload, dict):
                    payload["cached"] = True
                    return payload
            except (TypeError, json.JSONDecodeError):
                pass

    increment_youtube_search_budget(user_id)
    payload = youtube_service().search_videos(
        cleaned_query,
        page_token=page_token,
        limit=YOUTUBE_SEARCH_PAGE_SIZE,
    )
    safe_payload: dict[str, object] = {
        "items": payload.get("items", []),
        "next_page_token": str(payload.get("next_page_token", "") or ""),
        "previous_page_token": str(payload.get("previous_page_token", "") or ""),
        "cached": False,
        "query": cleaned_query,
    }
    if redis_state_available:
        redis_client.setex(
            cache_key,
            YOUTUBE_SEARCH_CACHE_SECONDS,
            json.dumps(safe_payload, sort_keys=True),
        )
    return safe_payload


def verify_youtube_video(video_id_or_url: str) -> dict[str, object]:
    video_id = parse_youtube_video_id(video_id_or_url)
    if not video_id:
        raise YouTubeApiError("invalid_video", "Select or paste a valid YouTube video.")
    videos = youtube_service().get_videos([video_id])
    if not videos:
        raise YouTubeApiError("video_not_found", "That YouTube video is no longer available.")
    video = videos[0]
    if not video.get("available"):
        raise YouTubeApiError(
            "video_unavailable",
            "That YouTube video is private, deleted, or unavailable in this region.",
        )
    if video.get("age_restricted"):
        raise YouTubeApiError(
            "video_age_restricted",
            "That YouTube video is age-restricted. Choose another karaoke version for the event queue.",
        )
    return video


def karaoke_signup_to_dict(signup: KaraokeSignup) -> dict[str, object]:
    return {
        "id": signup.id,
        "name": signup.name,
        "song_title": signup.song_title,
        "artist": signup.artist,
        "youtube_link": signup.youtube_link,
        "requester_id": signup.requester_id,
        "requested_at": signup.requested_at,
        "youtube": copy.deepcopy(signup.youtube),
        "workflow": copy.deepcopy(signup.workflow),
        "history": copy.deepcopy(signup.history),
    }


def karaoke_signup_from_dict(data: dict[str, object]) -> KaraokeSignup:
    youtube_link = str(data.get("youtube_link", "") or "")
    youtube = normalize_karaoke_youtube(data.get("youtube"), youtube_link)
    workflow = normalize_karaoke_workflow(
        data.get("workflow"),
        has_video=bool(youtube.get("video_id")),
    )
    return KaraokeSignup(
        id=str(data.get("id", "") or uuid4().hex),
        name=str(data.get("name", "") or ""),
        song_title=str(data.get("song_title", "") or ""),
        artist=str(data.get("artist", "") or ""),
        youtube_link=canonical_watch_url(str(youtube.get("video_id", "") or "")) or youtube_link,
        requester_id=str(data.get("requester_id", "") or ""),
        requested_at=str(data.get("requested_at", "") or ""),
        youtube=youtube,
        workflow=workflow,
        history=normalize_karaoke_history(data.get("history")),
    )


def _normalize_vote_rows(raw_votes: object) -> List[List[int]]:
    if not isinstance(raw_votes, list):
        return []

    normalized_votes: List[List[int]] = []
    for row in raw_votes:
        if not isinstance(row, list):
            normalized_votes.append([])
            continue

        normalized_row: List[int] = []
        for value in row:
            try:
                normalized_row.append(int(value))
            except (TypeError, ValueError):
                continue
        normalized_votes.append(normalized_row)

    return normalized_votes


def _normalize_costume_ballots(raw_ballots: object) -> dict[str, dict[str, int]]:
    if not isinstance(raw_ballots, dict):
        return {}

    normalized_ballots: dict[str, dict[str, int]] = {}
    for raw_user_id, raw_scores in raw_ballots.items():
        if not isinstance(raw_scores, dict):
            continue

        user_id = str(raw_user_id)
        normalized_scores: dict[str, int] = {}
        for raw_costume_id, raw_score in raw_scores.items():
            try:
                score = int(raw_score)
            except (TypeError, ValueError):
                continue

            if 1 <= score <= 10:
                normalized_scores[str(raw_costume_id)] = score

        if normalized_scores:
            normalized_ballots[user_id] = normalized_scores

    return normalized_ballots


def migrate_index_votes_to_ballots(
    raw_votes: object,
    raw_submitted_votes: object,
) -> dict[str, dict[str, int]]:
    vote_rows = _normalize_vote_rows(raw_votes)
    if not isinstance(raw_submitted_votes, list):
        return {}

    submitted_user_ids = [str(user_id) for user_id in raw_submitted_votes]
    if not submitted_user_ids:
        return {}

    migrated_ballots: dict[str, dict[str, int]] = {}
    costume_ids = [signup.id for signup in costume_signups]

    for vote_number, user_id in enumerate(submitted_user_ids):
        scores: dict[str, int] = {}
        for costume_index, costume_id in enumerate(costume_ids):
            if costume_index >= len(vote_rows):
                continue

            row = vote_rows[costume_index]
            if vote_number < len(row):
                score = row[vote_number]
                if 1 <= score <= 10:
                    scores[costume_id] = score

        if scores:
            migrated_ballots[user_id] = scores

    return migrated_ballots


def rebuild_legacy_vote_rows_from_ballots() -> None:
    global costume_votes

    costume_ids = [signup.id for signup in costume_signups]
    costume_votes = [[] for _ in costume_ids]

    for ballot in costume_ballots.values():
        for index, costume_id in enumerate(costume_ids):
            score = ballot.get(costume_id)
            if isinstance(score, int):
                costume_votes[index].append(score)


def snapshot_state() -> dict[str, object]:
    ensure_signup_ids()
    ensure_submitted_vote_tracking()
    rebuild_legacy_vote_rows_from_ballots()
    cleanup_password_reset_tokens()

    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "costume_signups": [
            costume_signup_to_dict(signup) for signup in costume_signups
        ],
        "karaoke_signups": [
            karaoke_signup_to_dict(signup) for signup in karaoke_signups
        ],
        "costume_ballots": copy.deepcopy(costume_ballots),
        "user_accounts": copy.deepcopy(user_accounts),
        "password_reset_tokens": copy.deepcopy(password_reset_tokens),
        "menu_items": copy.deepcopy(menu_items),
        "drink_orders": copy.deepcopy(drink_orders),
        "dj_playlist": copy.deepcopy(dj_playlist),
        "dj_song_requests": copy.deepcopy(dj_song_requests),
        "dj_state": copy.deepcopy(dj_state),
        "registered_users": copy.deepcopy(registered_users),
        "rsvp_signups": [
            rsvp_signup_to_dict(signup) for signup in rsvp_signups
        ],
        "rsvp_updates": [
            rsvp_update_to_dict(update) for update in rsvp_updates
        ],
        "submitted_costume_votes": sorted(submitted_costume_votes),
        "contest_state": copy.deepcopy(contest_state),
        "karaoke_state": copy.deepcopy(karaoke_state),
        "youtube_karaoke": copy.deepcopy(youtube_karaoke),
        "party_details": copy.deepcopy(party_details),
        "display_settings": copy.deepcopy(display_settings),
        "bartender_tip_settings": copy.deepcopy(bartender_tip_settings),
        "live_display_event_override": copy.deepcopy(live_display_event_override),
        "live_display_notice_override": copy.deepcopy(live_display_notice_override),
        "live_display_override": copy.deepcopy(current_display_override()),
        "landing_page_target": normalize_landing_page_target(landing_page_target),
        "event_experience_mode": normalize_event_experience_mode(event_experience_mode),
        "party_code_hash": party_code_hash,
        "party_code_hint": party_code_hint,
        "rsvp_notification_email": normalize_rsvp_notification_email(rsvp_notification_email),
        "display_update_version": display_update_version,
        "updated_at": _utc_now_iso(),
    }


def apply_state_snapshot(data: dict[str, object]) -> None:
    global costume_signups, karaoke_signups, costume_votes, registered_users, rsvp_signups, rsvp_updates
    global user_accounts, costume_ballots, submitted_costume_votes
    global live_display_event_override, live_display_notice_override
    global landing_page_target, event_experience_mode, party_code_hash, party_code_hint, party_details, display_settings, display_update_version
    global password_reset_tokens, menu_items, drink_orders, dj_playlist, dj_song_requests, dj_state, rsvp_notification_email, bartender_tip_settings, youtube_karaoke

    raw_costume_signups = data.get("costume_signups", [])
    costume_signups = [
        costume_signup_from_dict(signup)
        for signup in raw_costume_signups
        if isinstance(signup, dict)
    ]

    raw_karaoke_signups = data.get("karaoke_signups", [])
    karaoke_signups = [
        karaoke_signup_from_dict(signup)
        for signup in raw_karaoke_signups
        if isinstance(signup, dict)
    ]

    raw_rsvp_signups = data.get("rsvp_signups", [])
    rsvp_signups = [
        rsvp_signup_from_dict(signup)
        for signup in raw_rsvp_signups
        if isinstance(signup, dict)
    ]

    raw_rsvp_updates = data.get("rsvp_updates", [])
    rsvp_updates = [
        rsvp_update_from_dict(update)
        for update in raw_rsvp_updates
        if isinstance(update, dict)
    ]

    ensure_signup_ids()

    raw_registered_users = data.get("registered_users", {})
    if isinstance(raw_registered_users, dict):
        registered_users = {
            str(user_id): str(username)
            for user_id, username in raw_registered_users.items()
        }
    else:
        registered_users = {}

    raw_user_accounts = data.get("user_accounts", {})
    if isinstance(raw_user_accounts, dict):
        user_accounts = {}
        for raw_username, raw_account in raw_user_accounts.items():
            if not isinstance(raw_account, dict):
                continue

            normalized_username = normalize_username(str(raw_username))
            username = str(raw_account.get("username", "") or raw_username).strip()
            password_hash = str(raw_account.get("password_hash", "") or "")
            account_id = str(raw_account.get("id", "") or uuid4().hex)
            if normalized_username and username and password_hash:
                user_accounts[normalized_username] = {
                    "id": account_id,
                    "username": username,
                    "email": normalize_email(str(raw_account.get("email", "") or "")),
                    "email_updates_acknowledged": bool(raw_account.get("email_updates_acknowledged", False)),
                    "roles": normalize_account_roles(raw_account.get("roles", [])),
                    "password_hash": password_hash,
                    "created_at": str(raw_account.get("created_at", "") or ""),
                }
    else:
        user_accounts = {}

    raw_menu_items = data.get("menu_items", [])
    menu_items = []
    if isinstance(raw_menu_items, list):
        for raw_item in raw_menu_items:
            if isinstance(raw_item, dict):
                item = normalize_menu_item(raw_item)
                if item:
                    menu_items.append(item)

    raw_drink_orders = data.get("drink_orders", [])
    drink_orders = []
    if isinstance(raw_drink_orders, list):
        for raw_order in raw_drink_orders:
            if isinstance(raw_order, dict):
                order = normalize_drink_order(raw_order)
                if order:
                    drink_orders.append(order)

    raw_dj_playlist = data.get("dj_playlist", [])
    dj_playlist = []
    if isinstance(raw_dj_playlist, list):
        for raw_song in raw_dj_playlist:
            song = normalize_dj_song(raw_song)
            if song:
                dj_playlist.append(song)
    raw_dj_song_requests = data.get("dj_song_requests", [])
    dj_song_requests = []
    if isinstance(raw_dj_song_requests, list):
        for raw_request in raw_dj_song_requests:
            normalized_request = normalize_dj_song_request(raw_request)
            if normalized_request:
                dj_song_requests.append(normalized_request)
    dj_state = normalize_dj_state(data.get("dj_state"))

    bartender_tip_settings = normalize_bartender_tip_settings(data.get("bartender_tip_settings", {}))

    raw_password_reset_tokens = data.get("password_reset_tokens", {})
    password_reset_tokens = {}
    if isinstance(raw_password_reset_tokens, dict):
        for token_hash, raw_record in raw_password_reset_tokens.items():
            if not isinstance(raw_record, dict):
                continue
            normalized_username = normalize_username(str(raw_record.get("normalized_username", "") or ""))
            expires_at = str(raw_record.get("expires_at", "") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", str(token_hash)) or not normalized_username or not expires_at:
                continue
            password_reset_tokens[str(token_hash)] = {
                "normalized_username": normalized_username,
                "account_id": str(raw_record.get("account_id", "") or ""),
                "email": normalize_email(str(raw_record.get("email", "") or "")),
                "created_at": str(raw_record.get("created_at", "") or ""),
                "expires_at": expires_at,
                "used_at": str(raw_record.get("used_at", "") or ""),
            }
    cleanup_password_reset_tokens()

    raw_submitted_votes = data.get("submitted_costume_votes", [])
    if isinstance(raw_submitted_votes, list):
        submitted_costume_votes = {str(user_id) for user_id in raw_submitted_votes}
    else:
        submitted_costume_votes = set()

    try:
        schema_version = int(data.get("schema_version", 1) or 1)
    except (TypeError, ValueError):
        schema_version = 1

    if schema_version >= 2:
        costume_ballots = _normalize_costume_ballots(data.get("costume_ballots"))
    else:
        costume_ballots = migrate_index_votes_to_ballots(
            data.get("costume_votes"),
            raw_submitted_votes,
        )

    ensure_submitted_vote_tracking()

    raw_contest_state = data.get("contest_state", {})
    contest_state.clear()
    contest_state.update(copy.deepcopy(DEFAULT_CONTEST_STATE))
    if isinstance(raw_contest_state, dict):
        contest_state.update(copy.deepcopy(raw_contest_state))
    if not bool(contest_state.get("contest_started")) and (
        bool(contest_state.get("voting_open")) or bool(contest_state.get("winner_locked"))
    ):
        contest_state["contest_started"] = True

    raw_karaoke_state = data.get("karaoke_state", {})
    karaoke_state.clear()
    karaoke_state.update(copy.deepcopy(DEFAULT_KARAOKE_STATE))
    if isinstance(raw_karaoke_state, dict):
        karaoke_state.update(copy.deepcopy(raw_karaoke_state))
    if not karaoke_state.get("current_singer_id"):
        try:
            current_index = int(karaoke_state.get("current_singer_index"))
        except (TypeError, ValueError):
            current_index = -1
        if 0 <= current_index < len(karaoke_signups):
            karaoke_state["current_singer_id"] = karaoke_signups[current_index].id

    raw_youtube_karaoke = data.get("youtube_karaoke", {})
    youtube_karaoke = copy.deepcopy(DEFAULT_YOUTUBE_KARAOKE_STATE)
    if isinstance(raw_youtube_karaoke, dict):
        for key in DEFAULT_YOUTUBE_KARAOKE_STATE:
            if key in raw_youtube_karaoke:
                youtube_karaoke[key] = copy.deepcopy(raw_youtube_karaoke[key])

    raw_party_details = data.get("party_details", {})
    party_details = copy.deepcopy(DEFAULT_PARTY_DETAILS)
    if isinstance(raw_party_details, dict):
        for key in DEFAULT_PARTY_DETAILS:
            party_details[key] = str(raw_party_details.get(key, party_details[key]) or "").strip()

    raw_display_settings = data.get("display_settings", {})
    display_settings = copy.deepcopy(DEFAULT_DISPLAY_SETTINGS)
    if isinstance(raw_display_settings, dict):
        for key in DEFAULT_DISPLAY_SETTINGS:
            display_settings[key] = str(raw_display_settings.get(key, display_settings[key]) or "").strip()

    raw_event_override = data.get("live_display_event_override")
    raw_notice_override = data.get("live_display_notice_override")
    if isinstance(raw_event_override, dict) or isinstance(raw_notice_override, dict):
        live_display_event_override = (
            copy.deepcopy(raw_event_override) if isinstance(raw_event_override, dict) else None
        )
        live_display_notice_override = (
            copy.deepcopy(raw_notice_override) if isinstance(raw_notice_override, dict) else None
        )
    else:
        raw_override = data.get("live_display_override")
        live_display_event_override, live_display_notice_override = split_legacy_display_override(
            copy.deepcopy(raw_override) if isinstance(raw_override, dict) else None
        )
    cleanup_expired_display_notices()
    landing_page_target = normalize_landing_page_target(data.get("landing_page_target"))
    event_experience_mode = normalize_event_experience_mode(data.get("event_experience_mode"))
    party_code_hash = str(data.get("party_code_hash", party_code_hash) or "")
    party_code_hint = str(data.get("party_code_hint", party_code_hint) or "").strip()
    if "rsvp_notification_email" in data:
        rsvp_notification_email = normalize_rsvp_notification_email(data.get("rsvp_notification_email"))
    else:
        rsvp_notification_email = normalize_rsvp_notification_email(DEFAULT_RSVP_NOTIFICATION_EMAIL)

    try:
        display_update_version = int(data.get("display_update_version", 0) or 0)
    except (TypeError, ValueError):
        display_update_version = 0

    rebuild_legacy_vote_rows_from_ballots()


def save_state_to_redis() -> None:
    state_snapshot = snapshot_state()
    redis_client.set(redis_key("state"), json.dumps(state_snapshot, sort_keys=True))
    redis_client.set(redis_key("display:update-version"), display_update_version)


def write_state_backup(reason: str) -> str | None:
    if not redis_state_available:
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_key = redis_key(f"state:backup:{timestamp}:{reason}")
    backup_payload = snapshot_state()
    backup_payload["backup_reason"] = reason
    backup_payload["backup_key"] = backup_key

    redis_client.setex(
        backup_key,
        STATE_BACKUP_TTL_SECONDS,
        json.dumps(backup_payload, sort_keys=True),
    )
    return backup_key


def write_state_backup_if_available(reason: str) -> str | None:
    try:
        return write_state_backup(reason)
    except redis.RedisError as exc:
        if os.environ.get("APP_ENV") == "production":
            raise RuntimeError("Unable to write Halloween state backup to Redis.") from exc
        app.logger.warning("Unable to write Halloween state backup: %s", exc)
        return None


def build_costume_results_export() -> dict[str, object]:
    scoreboard, leader = build_costume_scoreboard()
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "exported_at": _utc_now_iso(),
        "winner": copy.deepcopy(contest_state.get("winner")),
        "leader": copy.deepcopy(leader),
        "results": rank_costume_entries(scoreboard),
        "vote_count": sum(int(entry.get("count", 0) or 0) for entry in scoreboard),
    }


def build_karaoke_lineup_export() -> dict[str, object]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "exported_at": _utc_now_iso(),
        "party_started": bool(karaoke_state.get("party_started")),
        "current_singer_id": karaoke_state.get("current_singer_id"),
        "lineup": [
            {
                "position": index + 1,
                **karaoke_signup_to_dict(signup),
            }
            for index, signup in enumerate(karaoke_signups)
        ],
    }


def send_json_export(payload: dict[str, object], filename: str):
    json_bytes = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return send_file(
        io.BytesIO(json_bytes),
        mimetype="application/json",
        as_attachment=True,
        download_name=filename,
    )


def persist_state_if_available() -> bool:
    global redis_state_available

    if not redis_state_available:
        return False

    try:
        save_state_to_redis()
    except redis.RedisError as exc:
        if os.environ.get("APP_ENV") == "production":
            raise RuntimeError("Unable to persist Halloween state to Redis.") from exc
        app.logger.warning("Unable to persist Halloween state to Redis: %s", exc)
        redis_state_available = False
        return False

    return True


def publish_display_update(reason: str) -> None:
    if not redis_state_available:
        return

    message = {
        "version": display_update_version,
        "reason": reason,
        "sender": APP_INSTANCE_ID,
        "published_at": _utc_now_iso(),
    }

    try:
        redis_client.publish(redis_key("display:pubsub"), json.dumps(message, sort_keys=True))
    except redis.RedisError as exc:
        app.logger.warning("Unable to publish Redis display update: %s", exc)


def notify_local_display_clients() -> None:
    with display_update_condition:
        display_update_condition.notify_all()


def handle_display_pubsub_message(message_data: object) -> None:
    if not isinstance(message_data, str):
        return

    try:
        message = json.loads(message_data)
    except json.JSONDecodeError:
        app.logger.warning("Ignoring invalid Redis display update payload.")
        return

    if not isinstance(message, dict):
        return

    if message.get("sender") == APP_INSTANCE_ID:
        return

    try:
        load_state_from_redis()
    except redis.RedisError as exc:
        app.logger.warning("Unable to reload Redis state from display update: %s", exc)
        return

    notify_local_display_clients()


def redis_display_pubsub_loop() -> None:
    channel_name = redis_key("display:pubsub")

    while True:
        pubsub_client = create_redis_client(REDIS_CONFIG)
        pubsub = pubsub_client.pubsub(ignore_subscribe_messages=True)

        try:
            pubsub.subscribe(channel_name)

            while True:
                message = pubsub.get_message(timeout=1.0)
                if message and message.get("type") == "message":
                    handle_display_pubsub_message(message.get("data"))
        except redis.RedisError as exc:
            app.logger.warning("Redis display pub/sub listener disconnected: %s", exc)
            time.sleep(2)
        finally:
            try:
                pubsub.close()
            except redis.RedisError:
                pass


def start_display_pubsub_listener() -> bool:
    global display_pubsub_listener_started

    if display_pubsub_listener_started or not redis_state_available:
        return False

    listener_thread = Thread(
        target=redis_display_pubsub_loop,
        name="redis-display-pubsub",
        daemon=True,
    )
    listener_thread.start()
    display_pubsub_listener_started = True
    return True


def acquire_state_lock() -> redis.lock.Lock | None:
    if not redis_state_available:
        return None

    state_lock = redis_client.lock(
        redis_key("lock:state"),
        timeout=STATE_LOCK_TIMEOUT_SECONDS,
        blocking_timeout=STATE_LOCK_BLOCKING_TIMEOUT_SECONDS,
        thread_local=False,
    )

    if not state_lock.acquire(blocking=True):
        return None

    return state_lock


def release_state_lock(state_lock: redis.lock.Lock | None) -> None:
    if not state_lock:
        return

    try:
        state_lock.release()
    except redis.exceptions.LockError as exc:
        app.logger.warning("Redis state lock could not be released cleanly: %s", exc)


class StateMutationBusy(RuntimeError):
    pass


def explicit_state_mutation(mutator, *, broadcast: bool = True):
    """Run a short state-only mutation without holding the lock across I/O."""
    state_lock = acquire_state_lock() if redis_state_available else None
    if redis_state_available and state_lock is None:
        raise StateMutationBusy("The event state is busy. Please try again.")
    try:
        if redis_state_available:
            load_state_from_redis()
        result = mutator()
        if broadcast:
            broadcast_display_update()
        elif redis_state_available:
            save_state_to_redis()
        return result
    except redis.RedisError as exc:
        app.logger.warning("YouTube karaoke state mutation could not reach Redis: %s", exc)
        raise StateMutationBusy(
            "The event state store is temporarily unavailable. Please try again."
        ) from exc
    finally:
        release_state_lock(state_lock)


def load_state_from_redis() -> bool:
    raw_state = redis_client.get(redis_key("state"))
    if not raw_state:
        save_state_to_redis()
        return False

    try:
        parsed_state = json.loads(raw_state)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Redis state at {redis_key('state')} is not valid JSON.") from exc

    if not isinstance(parsed_state, dict):
        raise RuntimeError(f"Redis state at {redis_key('state')} must be a JSON object.")

    apply_state_snapshot(parsed_state)
    return True


def initialize_state_store() -> bool:
    global redis_state_available

    try:
        verify_redis_connection()
        loaded_existing_state = load_state_from_redis()
    except redis.RedisError as exc:
        if os.environ.get("APP_ENV") == "production":
            raise RuntimeError("Redis state store is required in production.") from exc
        app.logger.warning("Redis state store unavailable; using process memory only: %s", exc)
        redis_state_available = False
        return False

    redis_state_available = True
    app.logger.info(
        "Redis state store ready at %s, existing_state=%s",
        redis_key("state"),
        loaded_existing_state,
    )
    return True


if initialize_state_store():
    start_display_pubsub_listener()


def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = uuid4().hex
        session["csrf_token"] = token
    return token


def is_safe_next_path(next_page: str | None) -> bool:
    if not next_page:
        return False

    parsed_next = urlparse(next_page)
    return not parsed_next.scheme and not parsed_next.netloc and next_page.startswith("/")


def normalize_next_page(next_page: str | None, fallback: str) -> str:
    return next_page if is_safe_next_path(next_page) else fallback


def session_roles() -> set[str]:
    raw_roles = session.get("roles", [])
    roles = {str(role) for role in raw_roles if role}
    if session.get("admin_authenticated"):
        roles.add("admin")
    return roles


def session_has_role(role: str) -> bool:
    return role in session_roles()


def role_preview_key() -> str | None:
    preview_key = str(session.get("role_preview", "") or "")
    return preview_key if preview_key in ROLE_PREVIEW_OPTIONS else None


def preview_roles() -> set[str]:
    preview_key = role_preview_key()
    if not preview_key:
        return session_roles()
    return set(ROLE_PREVIEW_OPTIONS[preview_key]["roles"])


def role_is_hidden_in_preview(role: str) -> bool:
    """True when a real session permission is intentionally hidden by role preview."""
    return role in session_roles() and role not in preview_roles()


def capability_is_hidden_in_preview(*roles: str) -> bool:
    """True when a route capability is real but absent from the selected preview."""
    required_roles = set(roles)
    return bool(session_roles() & required_roles) and not bool(preview_roles() & required_roles)


def preview_has_role(role: str) -> bool:
    """Return the effective role for a role-view demo, never a newly granted role."""
    return role in preview_roles()


def grant_session_role(role: str) -> None:
    roles = session_roles()
    roles.add(role)
    session["roles"] = sorted(roles)
    if role == "admin":
        session["admin_authenticated"] = True


def revoke_session_role(role: str) -> None:
    roles = session_roles()
    roles.discard(role)
    session["roles"] = sorted(roles)
    if role == "admin":
        session.pop("admin_authenticated", None)


def required_role_for_endpoint(endpoint: str | None) -> str | None:
    if endpoint in ADMIN_ENDPOINTS:
        return "admin"
    if endpoint in DISPLAY_ENDPOINTS:
        return "admin"
    if endpoint in BAR_ENDPOINTS:
        return "bartender"
    if endpoint in REGULAR_USER_ENDPOINTS:
        return "regular"
    return None


@app.before_request
def protect_role_routes():
    # This endpoint is the intentional recovery hatch for a preview that hides
    # the admin role. It verifies the real session role inside the view.
    if request.endpoint == "exit_role_preview":
        return None

    required_role = required_role_for_endpoint(request.endpoint)
    if not required_role:
        return None

    if preview_has_role(required_role):
        return None

    if required_role == "bartender" and preview_has_role("admin"):
        return None

    login_endpoint = ROLE_LOGIN_ENDPOINTS[required_role]
    next_page = normalize_next_page(request.full_path, url_for(login_endpoint))
    return redirect(url_for(login_endpoint, next=next_page))


@app.before_request
def validate_csrf_token():
    if request.method != "POST" or app.config.get("TESTING"):
        return None

    expected_token = session.get("csrf_token")
    provided_token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not expected_token or provided_token != expected_token:
        return Response("The form expired. Please go back, refresh, and try again.", status=400)

    return None


@app.before_request
def refresh_state_for_reads():
    if request.method != "GET" or request.endpoint not in STATE_REFRESH_ENDPOINTS:
        return None

    if not redis_state_available:
        return None

    try:
        load_state_from_redis()
    except redis.RedisError as exc:
        app.logger.warning("Unable to refresh Redis state before read: %s", exc)
        if os.environ.get("APP_ENV") == "production":
            return Response(
                "The event state store is temporarily unavailable. Please try again.",
                status=503,
            )

    return None


@app.before_request
def lock_state_for_mutation():
    if request.method != "POST" or request.endpoint not in STATE_MUTATION_ENDPOINTS:
        return None

    g.redis_state_lock = None
    g.redis_state_lock_owned = False

    if not redis_state_available:
        if os.environ.get("APP_ENV") == "production":
            return Response(
                "The event state store is temporarily unavailable. Please try again.",
                status=503,
            )
        return None

    try:
        state_lock = acquire_state_lock()
    except redis.RedisError as exc:
        app.logger.warning("Unable to acquire Redis state lock: %s", exc)
        if os.environ.get("APP_ENV") == "production":
            return Response(
                "The event state store is temporarily unavailable. Please try again.",
                status=503,
            )
        return None

    if state_lock is None:
        return Response(
            "The event state store is busy. Please try again in a moment.",
            status=503,
        )

    g.redis_state_lock = state_lock
    g.redis_state_lock_owned = True

    try:
        load_state_from_redis()
    except redis.RedisError as exc:
        release_state_lock(state_lock)
        g.redis_state_lock = None
        g.redis_state_lock_owned = False
        app.logger.warning("Unable to reload Redis state before mutation: %s", exc)
        return Response(
            "The event state store is temporarily unavailable. Please try again.",
            status=503,
        )

    return None


@app.after_request
def save_and_unlock_state_after_mutation(response):
    state_lock = getattr(g, "redis_state_lock", None)
    lock_owned = bool(getattr(g, "redis_state_lock_owned", False))

    if lock_owned:
        try:
            if not bool(getattr(g, "redis_state_saved_during_request", False)):
                persist_state_if_available()
        finally:
            release_state_lock(state_lock)
            g.redis_state_lock = None
            g.redis_state_lock_owned = False
            g.redis_state_saved_during_request = False

    return response


def build_costume_scoreboard() -> Tuple[List[dict[str, object]], dict[str, object] | None]:
    ensure_signup_ids()

    scoreboard: List[dict[str, object]] = []
    max_average = 0.0
    leader_index: int | None = None

    for index, signup in enumerate(costume_signups):
        votes = [
            int(ballot[signup.id])
            for ballot in costume_ballots.values()
            if signup.id in ballot
        ]
        total = sum(votes)
        vote_count = len(votes)
        average = total / vote_count if vote_count else 0.0

        entry = {
            "id": signup.id,
            "name": signup.name,
            "costume": signup.costume,
            "total": total,
            "count": vote_count,
            "average": average,
        }

        scoreboard.append(entry)

        if vote_count > 0:
            if leader_index is None:
                leader_index = index
            else:
                leader = scoreboard[leader_index]
                if average > leader["average"]:
                    leader_index = index
                elif average == leader["average"] and vote_count > leader["count"]:
                    leader_index = index

        if average > max_average:
            max_average = average

    if max_average <= 0:
        max_average = 10.0

    for entry in scoreboard:
        entry["percent"] = (entry["average"] / max_average) * 100 if max_average else 0.0
        entry["is_leader"] = False

    leader: dict[str, object] | None = None
    if leader_index is not None and 0 <= leader_index < len(scoreboard):
        scoreboard[leader_index]["is_leader"] = True
        leader = scoreboard[leader_index]

    return scoreboard, leader


def rank_costume_entries(entries: List[dict[str, object]]) -> List[dict[str, object]]:
    return sorted(
        entries,
        key=lambda entry: (
            -float(entry.get("average", 0.0) or 0.0),
            -int(entry.get("count", 0) or 0),
            entry.get("name", "").lower(),
        ),
    )


def create_scoreboard_card(top_entries: List[dict[str, object]]) -> dict[str, object]:
    scoreboard_rows = [
        {
            "rank": index + 1,
            "id": entry.get("id", ""),
            "name": entry.get("name", ""),
            "costume": entry.get("costume", ""),
            "average": float(entry.get("average", 0.0) or 0.0),
            "count": int(entry.get("count", 0) or 0),
            "total": int(entry.get("total", 0) or 0),
        }
        for index, entry in enumerate(top_entries)
    ]

    return {
        "category": "Costume Contest",
        "primary": "Top Costume Scores",
        "secondary": "Final top three standings",
        "tertiary": "Averages reflect scores out of 10.",
        "scoreboard": {
            "entries": scoreboard_rows,
        },
    }


def build_winner_entry() -> dict[str, object] | None:
    winner = contest_state.get("winner")
    if not winner:
        return None

    return {
        "category": "Costume Contest Champion",
        "primary": winner.get("name", ""),
        "secondary": f"Crowned for {winner.get('costume', '').strip()}".strip(),
        "tertiary": f"Average score: {winner.get('average', 0):.2f} | Votes: {winner.get('count', 0)}",
    }


def find_signup_index_by_id(signups: list[object], signup_id: str | None) -> int | None:
    if not signup_id:
        return None

    for index, signup in enumerate(signups):
        if getattr(signup, "id", None) == signup_id:
            return index

    return None


def is_costume_lineup_locked_for_voting() -> bool:
    return bool(contest_state.get("voting_open")) and not bool(contest_state.get("winner_locked"))


def costume_voting_is_visible() -> bool:
    return (
        party_day_has_arrived()
        and bool(contest_state.get("contest_started"))
        and bool(contest_state.get("voting_open"))
        and not bool(contest_state.get("winner_locked"))
    )


PARTY_SITE_URL = "https://tnq-halloween.com"
PARTY_PORTAL_URL = f"{PARTY_SITE_URL}/party"


PARTY_DAY_DASHBOARD_SLIDES = [
    {
        "title": "Join the Live Party Hub",
        "content": "Sign in or create an account to order drinks, enter the costume contest, and add a karaoke song.",
    },
    {
        "title": "Costume Contest",
        "content": "Add your costume before judging starts so your entry appears on the live display.",
    },
    {
        "title": "Karaoke Queue",
        "content": "Pick a song and reserve your spot. New karaoke signups appear in the live rotation.",
    },
    {
        "title": "Event Drinks",
        "content": "Browse the menu, order available drinks from your phone, and watch for the ready notification.",
    },
    {
        "title": "WiFi and Access",
        "content": f"Connect to the party WiFi, then open {PARTY_PORTAL_URL} to sign in or create your account.",
    },
]


def build_pre_party_dashboard_slides() -> list[dict[str, str]]:
    details = copy.deepcopy(DEFAULT_PARTY_DETAILS)
    details.update({key: value for key, value in party_details.items() if value})
    location = details.get("location", DEFAULT_PARTY_DETAILS["location"])
    map_address = details.get("map_address") or location

    slides = [
        {
            "title": "Party Date",
            "content": f"{details['date']} at {details['time']}.",
        },
        {
            "title": "Directions",
            "content": f"Head to {location}. Use the RSVP page map or your preferred maps app for turn-by-turn directions.",
        },
        {
            "title": "Rideshare Reminder",
            "content": "Uber or Lyft is a good move if costumes, weather, drinks, or parking make driving annoying.",
        },
        {
            "title": "Potluck Details",
            "content": details["overview"],
        },
        {
            "title": "Later Tonight",
            "content": "Expect a costume contest, games, and karaoke once the party gets rolling.",
        },
    ]
    if map_address and map_address != location:
        slides.insert(
            2,
            {
                "title": "Map Address",
                "content": map_address,
            },
        )
    slides.extend(
        {
            "title": update.title,
            "content": update.message,
        }
        for update in sorted_rsvp_updates()
    )
    return slides


def build_rotation_entries() -> List[dict[str, object]]:
    ensure_costume_votes_alignment()
    wifi_network = display_settings.get("wifi_network", DEFAULT_DISPLAY_SETTINGS["wifi_network"])
    wifi_password = display_settings.get("wifi_password", DEFAULT_DISPLAY_SETTINGS["wifi_password"])

    rotation_entries: List[dict[str, object]] = [
        {
            "category": "Signup Portal",
            "primary": "Connect to the party WiFi.",
            "secondary": f"After you connect, browse to {PARTY_SITE_URL} to start the party experience.",
            "cta": True,
            "cta_details": {
                "lede": "Get your phone connected, then open the party site.",
                "wifi_network": wifi_network,
                "wifi_password": wifi_password,
                "site_url": PARTY_SITE_URL,
            },
        },
        {
            "category": "Costume Contest",
            "primary": "Add your costume to the live lineup.",
            "secondary": "Use the party portal to enter your name plus costume before judging starts.",
            "tertiary": "New costume signups appear here automatically.",
        },
        {
            "category": "Karaoke Stage",
            "primary": "Reserve your karaoke song.",
            "secondary": "Use the party portal to queue the song you want to perform.",
        },
        {
            "category": "Bar Queue",
            "primary": "Order event drinks from your phone.",
            "secondary": "Browse the drink menu in the app, send available drinks to the bar, and watch for the ready email.",
            "tertiary": "Completed drinks also pop up on this display.",
        },
        {
            "category": "Live Updates",
            "primary": "Watch the party build in real time.",
            "secondary": "Costumes, karaoke songs, winners, drink-ready cards, and announcements rotate here all night.",
            "tertiary": "Keep an eye on this screen after each signup.",
        },
    ]

    costume_entries = [
        {
            "id": signup.id,
            "category": "Costume Contest",
            "primary": signup.name,
            "secondary": f"Dressed as {signup.costume}",
            "tertiary": f"Contact: {signup.contact}" if signup.contact else "",
        }
        for signup in costume_signups
    ]

    karaoke_entries = [
        {
            "id": signup.id,
            "category": "Karaoke Stage",
            "primary": signup.name,
            "secondary": f'Performing "{signup.song_title}"',
            "tertiary": f"by {signup.artist}" if signup.artist else "",
        }
        for signup in public_karaoke_signups()
    ]

    winner_entry = build_winner_entry()
    if winner_entry:
        rotation_entries.append({
            **winner_entry,
            "cta": False,
        })

    if contest_state.get("show_scoreboard_card") and contest_state.get("scoreboard_card"):
        rotation_entries.append(copy.deepcopy(contest_state["scoreboard_card"]))

    max_length = max(len(costume_entries), len(karaoke_entries))
    for index in range(max_length):
        if index < len(costume_entries):
            rotation_entries.append(costume_entries[index])
        if index < len(karaoke_entries):
            rotation_entries.append(karaoke_entries[index])

    return rotation_entries


@app.route("/")
def index():
    return redirect(url_for(landing_page_endpoint()))


@app.route("/health")
def health():
    payload, status_code = build_health_payload()
    return jsonify(payload), status_code


@app.route("/live-display")
def live_display():
    cleanup_expired_display_notices()
    rotation_entries = build_rotation_entries()

    return render_template(
        "display.html",
        entries=rotation_entries,
        costume_count=len(costume_signups),
        karaoke_count=len(public_karaoke_signups()),
        override=live_display_event_override,
        notice_override=live_display_notice_override,
        dj=dj_view_state(),
        apple_music_configured=apple_music_is_configured(),
    )


@app.route("/api/display-updates")
def display_updates():
    def event_stream():
        last_sent_version = None
        # Send the current version immediately so clients sync quickly.
        with display_update_condition:
            current_version = display_update_version

        yield f"data: {current_version}\n\n"
        last_sent_version = current_version

        while True:
            with display_update_condition:
                display_update_condition.wait(timeout=25)
                current_version = display_update_version

            if current_version != last_sent_version:
                last_sent_version = current_version
                yield f"data: {current_version}\n\n"
            else:
                yield ": keep-alive\n\n"

    response = Response(stream_with_context(event_stream()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route("/api/display-data")
def display_data():
    cleanup_expired_display_notices()
    rotation_entries = build_rotation_entries()

    return jsonify(
        {
            "entries": rotation_entries,
            "costume_count": len(costume_signups),
            "karaoke_count": len(public_karaoke_signups()),
            "override": live_display_event_override,
            "event_override": live_display_event_override,
            "notice_override": live_display_notice_override,
            "dj": dj_view_state(),
            "display_update_version": display_update_version,
        }
    )


@app.route("/api/dj/musickit-token")
def dj_musickit_token():
    if not apple_music_is_configured():
        return jsonify({"configured": False, "error": "Apple Music is not configured for this event."}), 503

    try:
        token = apple_music_developer_token()
    except RuntimeError as exc:
        app.logger.warning("Unable to issue Apple Music developer token: %s", exc)
        return jsonify({"configured": False, "error": "Apple Music token setup is unavailable."}), 503

    return jsonify(
        {
            "configured": True,
            "developer_token": token,
            "app_name": app.config["PARTY_TITLE"],
            "storefront": app.config["APPLE_MUSIC_STOREFRONT"],
        }
    )


@app.route("/api/dj/catalog-search")
def dj_catalog_search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"results": [], "error": "Enter at least two characters to search Apple Music."})
    offset = parse_catalog_search_offset(request.args.get("offset"))
    if offset is None:
        return jsonify({"results": [], "error": "That search results page is invalid."}), 400
    if not apple_music_is_configured():
        return jsonify({"results": [], "error": "Apple Music is not configured for this event."}), 503
    try:
        search_page = search_apple_music_catalog(query, offset)
    except RuntimeError as exc:
        app.logger.warning("Apple Music catalog search failed: %s", exc)
        return jsonify({"results": [], "error": "Apple Music catalog search is unavailable right now."}), 502
    return jsonify({**search_page, "offset": offset})


@app.route("/api/party/jukebox/catalog-search")
def party_jukebox_catalog_search():
    if not party_day_has_arrived():
        return jsonify({"results": [], "error": "Song requests open on party day."}), 403

    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"results": [], "error": "Enter at least two characters to search Apple Music."})
    offset = parse_catalog_search_offset(request.args.get("offset"))
    if offset is None:
        return jsonify({"results": [], "error": "That search results page is invalid."}), 400
    if not apple_music_is_configured():
        return jsonify({"results": [], "error": "Apple Music is not configured for this event."}), 503
    try:
        search_page = search_apple_music_catalog(query, offset)
    except RuntimeError as exc:
        app.logger.warning("Attendee Apple Music catalog search failed: %s", exc)
        return jsonify({"results": [], "error": "Apple Music catalog search is unavailable right now."}), 502
    return jsonify({**search_page, "offset": offset})


@app.route("/api/party/jukebox-data")
def party_jukebox_data():
    if not party_day_has_arrived():
        return jsonify({"error": "Song requests open on party day."}), 403
    return jsonify(attendee_jukebox_state(str(session.get("user_id", "") or "")))


@app.route("/api/admin/dj-song-request-queue")
def admin_dj_song_request_queue():
    return jsonify(
        {
            "html": render_template("_dj_song_request_queue.html", dj_song_requests=dj_song_requests),
            "request_count": len(dj_song_requests),
        }
    )


@app.route("/api/dj/receiver-state", methods=["POST"])
def dj_receiver_state():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a DJ receiver state payload."}), 400

    record_dj_receiver_state(payload)
    broadcast_display_update()
    return jsonify({"dj": dj_view_state(), "command": copy.deepcopy(dj_state.get("current_command"))})


@app.context_processor
def inject_contest_state():
    active_roles = session_roles()
    effective_preview_roles = preview_roles()
    preview_key = role_preview_key()
    return {
        "costume_contest_state": {
            "contest_started": bool(contest_state.get("contest_started")),
            "voting_open": bool(contest_state.get("voting_open")),
            "voting_visible": costume_voting_is_visible(),
            "winner_locked": bool(contest_state.get("winner_locked")),
            "winner": contest_state.get("winner"),
        },
        "csrf_token": get_csrf_token,
        # These reflect actual authorization. Preview is presentation-only and
        # must never grant a capability or weaken server-side route protection.
        "admin_authenticated": "admin" in active_roles,
        "regular_authenticated": "regular" in active_roles,
        "bartender_authenticated": "bartender" in active_roles,
        "role_preview_key": preview_key,
        "role_preview_label": ROLE_PREVIEW_OPTIONS[preview_key]["label"] if preview_key else "",
        "role_preview_roles": sorted(effective_preview_roles),
        "role_preview_options": ROLE_PREVIEW_OPTIONS,
        "role_is_hidden_in_preview": role_is_hidden_in_preview,
        "capability_is_hidden_in_preview": capability_is_hidden_in_preview,
        "format_time_label": format_time_label,
        "drink_order_status_label": drink_order_status_label,
        "drink_type_label": drink_type_label,
        "beverage_type_label": beverage_type_label,
        "party_day_has_arrived": party_day_has_arrived(),
        "party_title": app.config["PARTY_TITLE"],
        "party_year": app.config["PARTY_YEAR"],
    }


@app.route("/halloween")
def legacy_halloween_overview():
    return redirect(url_for("party_dashboard"), code=301)


@app.route("/rsvp/calendar/<rsvp_id>")
def rsvp_calendar(rsvp_id: str):
    signup = next((entry for entry in rsvp_signups if entry.id == rsvp_id), None)
    if signup is None:
        return Response("Calendar invite not found.", status=404)

    response = Response(build_party_ics(rsvp_id), mimetype="text/calendar; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=tnq-halloween-party.ics"
    return response


@app.route("/rsvp", methods=["GET", "POST"])
def rsvp():
    errors: List[str] = []
    submitted_rsvp = None
    session_rsvp_id = session.get("rsvp_id")
    if session_rsvp_id:
        submitted_rsvp = next(
            (signup for signup in rsvp_signups if signup.id == session_rsvp_id),
            None,
        )

    if request.method == "POST" and request.form.get("action") == "submit_rsvp":
        username = request.form.get("username", "").strip()
        contact = request.form.get("contact", "").strip()
        note = request.form.get("note", "").strip()
        provided_code = request.form.get("party_code", "").strip()
        try:
            guest_count = int(request.form.get("guest_count", "1") or 1)
        except ValueError:
            guest_count = 1

        if not party_code_is_configured():
            errors.append("The party code is not configured yet. Please ask the hosts.")
        elif not verify_party_code(provided_code):
            errors.append("That party code did not match. Please try again.")
        if not username:
            errors.append("Name is required.")
        elif len(username) > 80:
            errors.append("Name must be 80 characters or fewer.")
        if not contact:
            errors.append("Email is required so the hosts can send party updates.")
        elif len(contact) > 120:
            errors.append("Email must be 120 characters or fewer.")
        elif not normalize_email(contact):
            errors.append("Enter a valid email address for party updates.")
        if not 1 <= guest_count <= 12:
            errors.append("Guest count must be between 1 and 12.")
        if len(note) > RSVP_NOTE_MAX_LENGTH:
            errors.append(f"Note must be {RSVP_NOTE_MAX_LENGTH} characters or fewer.")

        if not errors:
            submitted_rsvp = RSVPSignup(
                id=uuid4().hex,
                name=username,
                contact=normalize_email(contact),
                guest_count=guest_count,
                note=note,
                created_at=_utc_now_iso(),
                email_updates_acknowledged=True,
            )
            rsvp_signups.append(submitted_rsvp)
            session["rsvp_id"] = submitted_rsvp.id
            send_rsvp_confirmation_email(submitted_rsvp)
            send_rsvp_admin_notification_email(submitted_rsvp)
            persist_state_if_available()
            return redirect(url_for("rsvp", success="1"))

    return render_template(
        "rsvp.html",
        errors=errors,
        party_code_verified=True,
        party_code_configured=party_code_is_configured(),
        party_code_hint=party_code_hint,
        submitted_rsvp=submitted_rsvp,
        party_info_cards=party_info_cards(),
        maps_urls=google_maps_urls(party_details.get("map_address", "")),
        rsvp_updates=sorted_rsvp_updates(),
        rsvp_note_max_length=RSVP_NOTE_MAX_LENGTH,
        show_admin_link=False,
        hide_site_nav=True,
        hide_party_nav=True,
    )


@app.route("/halloween/login", methods=["GET", "POST"])
def legacy_halloween_login():
    return redirect(
        url_for("party_login", **request.args.to_dict(flat=True)),
        code=308 if request.method == "POST" else 301,
    )


@app.route("/halloween/register", methods=["GET", "POST"])
def legacy_halloween_register():
    return redirect(
        url_for("party_register", **request.args.to_dict(flat=True)),
        code=308 if request.method == "POST" else 301,
    )


@app.route("/halloween/logout", methods=["POST"])
def legacy_halloween_logout():
    return logout()


@app.route("/costume-signup", methods=["GET", "POST"])
def legacy_costume_signup():
    return redirect(
        url_for("party_costumes", **request.args.to_dict(flat=True)),
        code=308 if request.method == "POST" else 301,
    )


@app.route("/karaoke-signup", methods=["GET", "POST"])
def legacy_karaoke_signup():
    return redirect(
        url_for("party_karaoke", **request.args.to_dict(flat=True)),
        code=308 if request.method == "POST" else 301,
    )


@app.route("/costume-voting", methods=["GET", "POST"])
def legacy_costume_voting():
    return redirect(
        url_for("party_costume_voting", **request.args.to_dict(flat=True)),
        code=308 if request.method == "POST" else 301,
    )


@app.route("/party")
def party_dashboard():
    if "user_id" not in session or "username" not in session:
        return redirect(url_for("party_login", next=url_for("party_dashboard")))

    party_day = party_day_has_arrived()
    user_orders = user_drink_orders(str(session.get("user_id", "")))
    ready_orders = [order for order in user_orders if ready_order_is_visible_on_dashboard(order)][:3] if party_day else []
    if party_day:
        slides = list(PARTY_DAY_DASHBOARD_SLIDES)
        if bartender_tip_settings.get("enabled"):
            tip_methods = bartender_tip_methods()
            method_text = "; ".join(f"{method['label']}: {method['value']}" for method in tip_methods)
            tip_content = str(bartender_tip_settings.get("note", "") or "Tips are never required, always appreciated.")
            if method_text:
                tip_content = f"{tip_content} {method_text}."
            slides.append(
                {
                    "title": f"Tip {bartender_tip_settings.get('display_name') or 'the Bartender'}",
                    "content": tip_content,
                    "image_url": str(bartender_tip_settings.get("image_url", "") or ""),
                    "methods": tip_methods,
                }
            )
        winner = contest_state.get("winner")
        if winner:
            slides.append(
                {
                    "title": "Costume Contest Champion",
                    "content": f"Congratulations to {winner['name']} for {winner['costume']}! Average score: {winner['average']:.2f}.",
                }
            )
    else:
        slides = build_pre_party_dashboard_slides()

    return render_template(
        "index.html",
        slides=slides,
        costume_signups=costume_signups,
        karaoke_signups=public_karaoke_signups(),
        drink_orders=user_orders[:5] if party_day else [],
        ready_drink_orders=ready_orders,
        jukebox=attendee_jukebox_state(str(session.get("user_id", "") or "")) if party_day else None,
        bartender_tip_settings=bartender_tip_settings,
        party_day_has_arrived=party_day,
        show_admin_link=False,
    )


@app.route("/party/account", methods=["GET", "POST"])
def party_account():
    account = current_user_account()
    if account is None:
        # Retain a simultaneous admin session, but remove the stale attendee identity.
        session.pop("user_id", None)
        session.pop("username", None)
        revoke_session_role("regular")
        revoke_session_role("bartender")
        return redirect(url_for("party_login", next=url_for("party_account")))

    errors: List[str] = []
    messages: List[str] = []
    account_id = str(account.get("id", "") or "")

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "update_profile":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip()
            normalized_username = normalize_username(username)
            normalized_email = normalize_email(email)
            existing_key = find_user_account_key_by_id(account_id)

            if existing_key is None:
                errors.append("Your account could not be found. Please sign in again.")
            if not username:
                errors.append("Name is required.")
            elif len(username) > 80:
                errors.append("Name must be 80 characters or fewer.")
            elif normalized_username in user_accounts and normalized_username != existing_key:
                errors.append("That name is already registered.")
            if not email:
                errors.append("Email is required so the hosts can send party updates.")
            elif len(email) > 120 or not normalized_email:
                errors.append("Enter a valid email address for party updates.")

            if not errors and existing_key is not None:
                account = user_accounts.pop(existing_key)
                previous_email = str(account.get("email", "") or "")
                account["username"] = username
                account["email"] = normalized_email
                user_accounts[normalized_username] = account
                session["username"] = username
                registered_users[account_id] = username
                if existing_key != normalized_username or previous_email != normalized_email:
                    invalidate_password_reset_tokens_for_account(account_id)
                messages.append("Your profile details were updated.")

        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not current_password:
                errors.append("Enter your current password.")
            elif not check_password_hash(str(account.get("password_hash", "")), current_password):
                errors.append("Your current password is incorrect.")
            if len(new_password) < 8:
                errors.append("New password must be at least 8 characters.")
            elif new_password != confirm_password:
                errors.append("New passwords do not match.")

            if not errors:
                account["password_hash"] = generate_password_hash(new_password)
                invalidate_password_reset_tokens_for_account(account_id)
                messages.append("Your password was updated.")

        else:
            errors.append("That account action is not available.")

        if not errors:
            persist_state_if_available()

    account_roles = normalize_account_roles(account.get("roles", []))
    role_labels = ["Attendee"]
    if "bartender" in account_roles:
        role_labels.append("Bartender")
    created_at = parse_utc_iso(account.get("created_at"))
    created_at_label = created_at.astimezone().strftime("%B %-d, %Y") if created_at else ""
    profile_update_requested = request.method == "POST" and request.form.get("action") == "update_profile"

    return render_template(
        "account.html",
        account=account,
        errors=errors,
        messages=messages,
        role_labels=role_labels,
        account_roles=account_roles,
        active_session_roles=sorted(preview_roles()),
        created_at_label=created_at_label,
        profile_username=request.form.get("username", "") if profile_update_requested else str(account.get("username", "")),
        profile_email=request.form.get("email", "") if profile_update_requested else str(account.get("email", "")),
        show_admin_link=False,
    )


@app.route("/party/jukebox")
def party_jukebox():
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))

    user_id = str(session.get("user_id", "") or "")
    return render_template(
        "jukebox.html",
        jukebox=attendee_jukebox_state(user_id),
        catalog_search_url=url_for("party_jukebox_catalog_search"),
        jukebox_data_url=url_for("party_jukebox_data"),
        request_url=url_for("party_jukebox_request"),
        show_admin_link=False,
    )


@app.route("/party/jukebox/requests", methods=["POST"])
def party_jukebox_request():
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))

    user_id = str(session.get("user_id", "") or "")
    username = str(session.get("username", "") or "Guest").strip() or "Guest"
    raw_song_request = {
        "title": request.form.get("title", ""),
        "artist": request.form.get("artist", ""),
        "apple_music_id": request.form.get("apple_music_id", ""),
        "album": request.form.get("album", ""),
        "artwork_url": request.form.get("artwork_url", ""),
    }
    maximum_lengths = {"title": 180, "artist": 180, "apple_music_id": 160, "album": 180, "artwork_url": 500}
    if any(len(str(value or "").strip()) > maximum_lengths[field] for field, value in raw_song_request.items()):
        return redirect(url_for("party_jukebox", request_error="That song request contains invalid song metadata."))
    song = normalize_dj_song(
        {
            "id": uuid4().hex,
            **raw_song_request,
            "duration_ms": request.form.get("duration_ms", 0),
            "explicit": request.form.get("explicit") == "yes",
        }
    )
    if not song:
        return redirect(url_for("party_jukebox", request_error="Select a valid Apple Music song before requesting it."))

    existing_requests = user_dj_song_requests(user_id)
    if any(str(entry.get("song", {}).get("apple_music_id", "")) == song["apple_music_id"] for entry in existing_requests):
        return redirect(url_for("party_jukebox", request_error="You already have that song in the request queue."))
    if len(existing_requests) >= MAX_DJ_SONG_REQUESTS_PER_ATTENDEE:
        return redirect(
            url_for(
                "party_jukebox",
                request_error=f"You can keep up to {MAX_DJ_SONG_REQUESTS_PER_ATTENDEE} song requests pending at once.",
            )
        )

    normalized_request = normalize_dj_song_request(
        {
            "id": uuid4().hex,
            "requester_id": user_id,
            "requester_name": username,
            "requested_at": _utc_now_iso(),
            "song": song,
        }
    )
    if not normalized_request:
        return redirect(url_for("party_jukebox", request_error="That song request could not be saved."))

    dj_song_requests.append(normalized_request)
    broadcast_display_update()
    return redirect(url_for("party_jukebox", request_success="Song request sent to the DJ."))


def begin_karaoke_playlist_operation(
    entry_id: str,
    action: str,
    *,
    approve: bool = False,
) -> dict[str, object]:
    operation_id = uuid4().hex

    def begin() -> dict[str, object]:
        require_karaoke_clear_idle()
        signup = find_karaoke_signup(entry_id)
        if not signup:
            raise ValueError("Karaoke request could not be found.")
        if not youtube_karaoke.get("playlist_id"):
            raise ValueError("Choose a YouTube event playlist first.")
        if not signup.youtube.get("video_id"):
            raise ValueError("Choose and verify a YouTube video first.")
        if approve:
            signup.workflow["approval_status"] = "approved"
            signup.workflow["approved_at"] = _utc_now_iso()
            signup.workflow["approved_by"] = "admin"
            append_karaoke_history(signup, "approved", actor_name="admin")
        elif signup.workflow.get("approval_status") != "approved":
            raise ValueError("Approve this request before synchronizing it.")

        signup.workflow["playlist_sync_status"] = "pending"
        signup.workflow["operation_id"] = operation_id
        signup.workflow["operation_action"] = action
        signup.workflow["operation_started_at"] = _utc_now_iso()
        signup.workflow["last_sync_error_code"] = ""
        signup.workflow["last_sync_error_message"] = ""
        append_karaoke_history(
            signup,
            f"playlist_{action}_started",
            actor_name="admin",
        )
        active_entries = approved_karaoke_signups()
        return {
            "operation_id": operation_id,
            "playlist_id": str(youtube_karaoke.get("playlist_id", "") or ""),
            "video_id": str(signup.youtube.get("video_id", "") or ""),
            "position": next(
                (index for index, entry in enumerate(active_entries) if entry.id == signup.id),
                max(0, len(active_entries) - 1),
            ),
            "note": youtube_playlist_note(signup),
            "existing_playlist_item_id": str(signup.workflow.get("playlist_item_id", "") or ""),
        }

    return explicit_state_mutation(begin)


def finish_karaoke_playlist_operation(
    entry_id: str,
    operation_id: str,
    *,
    playlist_item_id: str = "",
    error: YouTubeApiError | None = None,
    event: str = "playlist_insert_confirmed",
    playlist_sync_status: str = "synced",
) -> bool:
    def finish() -> bool:
        signup = find_karaoke_signup(entry_id)
        if not signup or signup.workflow.get("operation_id") != operation_id:
            return False
        signup.workflow["operation_id"] = ""
        signup.workflow["operation_action"] = ""
        signup.workflow["operation_started_at"] = ""
        if error:
            signup.workflow["playlist_sync_status"] = "failed"
            signup.workflow["last_sync_error_code"] = (
                "operation_result_unknown" if error.uncertain else error.code
            )
            signup.workflow["last_sync_error_message"] = error.message
            append_karaoke_history(
                signup,
                "playlist_operation_unknown" if error.uncertain else "playlist_operation_failed",
                detail=error.message,
                actor_name="system",
            )
        else:
            if playlist_item_id:
                signup.workflow["playlist_item_id"] = playlist_item_id
            signup.workflow["playlist_sync_status"] = playlist_sync_status
            signup.workflow["last_sync_error_code"] = ""
            signup.workflow["last_sync_error_message"] = ""
            append_karaoke_history(signup, event, actor_name="system")
        refresh_karaoke_stage_selection()
        return True

    return bool(explicit_state_mutation(finish))


def sync_karaoke_entry_to_youtube(entry_id: str, *, approve: bool = False) -> dict[str, object]:
    signup = find_karaoke_signup(entry_id)
    if not signup:
        raise ValueError("Karaoke request could not be found.")
    verified_video = verify_youtube_video(str(signup.youtube.get("video_id") or signup.youtube_link))

    def save_verification() -> None:
        current = find_karaoke_signup(entry_id)
        if not current:
            raise ValueError("Karaoke request could not be found.")
        current.youtube = normalize_karaoke_youtube(verified_video)
        current.youtube_link = str(current.youtube.get("watch_url", "") or "")
        current.workflow["video_validation_status"] = "verified"
        append_karaoke_history(current, "video_verified", actor_name="system")

    explicit_state_mutation(save_verification)
    operation = begin_karaoke_playlist_operation(entry_id, "insert", approve=approve)
    service = youtube_service()
    try:
        playlist_items = service.list_playlist_items(str(operation["playlist_id"]))
        existing = find_matching_youtube_playlist_item(
            playlist_items,
            playlist_item_id=str(operation["existing_playlist_item_id"]),
            note=str(operation["note"]),
            video_id=str(operation["video_id"]),
            expected_position=int(operation["position"]),
        )
        if existing:
            playlist_item_id = str(existing.get("playlist_item_id", "") or "")
            actual_position = _safe_int(existing.get("position"), -1)
        else:
            inserted = service.insert_playlist_item(
                str(operation["playlist_id"]),
                str(operation["video_id"]),
                position=min(int(operation["position"]), len(playlist_items)),
                note=str(operation["note"]),
            )
            playlist_item_id = str(inserted.get("playlist_item_id", "") or "")
            actual_position = _safe_int(inserted.get("position"), -1)
        order_matches = actual_position == int(operation["position"])
        finish_karaoke_playlist_operation(
            entry_id,
            str(operation["operation_id"]),
            playlist_item_id=playlist_item_id,
            playlist_sync_status="synced" if order_matches else "out_of_order",
        )
        message = (
            "The karaoke request is approved and synchronized."
            if order_matches
            else "The karaoke request is approved and added. Synchronize playlist order after resolving earlier entries."
        )
        return {"ok": True, "message": message, "entry_id": entry_id}
    except YouTubeApiError as exc:
        finish_karaoke_playlist_operation(
            entry_id,
            str(operation["operation_id"]),
            error=exc,
        )
        return {"ok": False, "message": exc.message, "code": exc.code, "entry_id": entry_id}


@app.get("/api/admin/karaoke-state")
def admin_karaoke_state():
    return jsonify(karaoke_admin_view_state())


@app.get("/api/admin/karaoke/search")
def admin_karaoke_search():
    query = request.args.get("q", "")
    page_token = request.args.get("page_token", "")
    if len(page_token) > 300:
        return jsonify({"error": "Invalid YouTube result page."}), 400
    try:
        payload = search_youtube_karaoke(
            query,
            page_token=page_token,
            user_id=f"admin:{session.get('user_id', 'host')}",
        )
    except YouTubeApiError as exc:
        return jsonify({"error": exc.message, "code": exc.code}), 429 if "limit" in exc.code or "budget" in exc.code else 503
    return jsonify(payload)


@app.post("/api/admin/karaoke/entries/<entry_id>/approve")
def admin_karaoke_approve(entry_id: str):
    try:
        result = sync_karaoke_entry_to_youtube(entry_id, approve=True)
    except (StateMutationBusy, ValueError, YouTubeApiError) as exc:
        message = exc.message if isinstance(exc, YouTubeApiError) else str(exc)
        return jsonify({"ok": False, "message": message}), 409
    return jsonify(result), 200 if result["ok"] else 502


@app.post("/api/admin/karaoke/entries/<entry_id>/retry")
def admin_karaoke_retry(entry_id: str):
    try:
        result = sync_karaoke_entry_to_youtube(entry_id, approve=False)
    except (StateMutationBusy, ValueError, YouTubeApiError) as exc:
        message = exc.message if isinstance(exc, YouTubeApiError) else str(exc)
        return jsonify({"ok": False, "message": message}), 409
    return jsonify(result), 200 if result["ok"] else 502


@app.post("/api/admin/karaoke/entries/<entry_id>/reject")
def admin_karaoke_reject(entry_id: str):
    reason = request.form.get("reason", "").strip()[:500]

    def reject() -> None:
        require_karaoke_clear_idle()
        signup = find_karaoke_signup(entry_id)
        if not signup:
            raise ValueError("Karaoke request could not be found.")
        if signup.workflow.get("playlist_item_id"):
            raise ValueError("Remove the synchronized playlist entry instead of rejecting it.")
        signup.workflow["approval_status"] = "rejected"
        append_karaoke_history(signup, "rejected", detail=reason, actor_name="admin")
        refresh_karaoke_stage_selection()

    try:
        explicit_state_mutation(reject)
    except (StateMutationBusy, ValueError) as exc:
        return jsonify({"ok": False, "message": str(exc)}), 409
    return jsonify({"ok": True, "message": "Karaoke request rejected."})


@app.post("/api/admin/karaoke/entries/<entry_id>/remove")
def admin_karaoke_remove(entry_id: str):
    operation_id = uuid4().hex

    def begin_remove() -> dict[str, str]:
        require_karaoke_clear_idle()
        signup = find_karaoke_signup(entry_id)
        if not signup:
            raise ValueError("Karaoke entry could not be found.")
        playlist_item_id = str(signup.workflow.get("playlist_item_id", "") or "")
        signup.workflow["playlist_sync_status"] = "removal_pending"
        signup.workflow["operation_id"] = operation_id
        signup.workflow["operation_action"] = "remove"
        signup.workflow["operation_started_at"] = _utc_now_iso()
        append_karaoke_history(signup, "playlist_remove_started", actor_name="admin")
        return {"playlist_item_id": playlist_item_id}

    try:
        operation = explicit_state_mutation(begin_remove)
        if operation["playlist_item_id"]:
            youtube_service().delete_playlist_item(operation["playlist_item_id"])

        def finish_remove() -> None:
            signup = find_karaoke_signup(entry_id)
            if not signup or signup.workflow.get("operation_id") != operation_id:
                return
            signup.workflow["operation_id"] = ""
            signup.workflow["operation_action"] = ""
            signup.workflow["operation_started_at"] = ""
            signup.workflow["playlist_sync_status"] = "removed"
            signup.workflow["playlist_item_id"] = ""
            signup.workflow["approval_status"] = "cancelled"
            append_karaoke_history(signup, "playlist_remove_confirmed", actor_name="system")
            refresh_karaoke_stage_selection()

        explicit_state_mutation(finish_remove)
    except YouTubeApiError as exc:
        finish_karaoke_playlist_operation(entry_id, operation_id, error=exc)
        return jsonify({"ok": False, "message": exc.message, "code": exc.code}), 502
    except (StateMutationBusy, ValueError) as exc:
        return jsonify({"ok": False, "message": str(exc)}), 409
    return jsonify({"ok": True, "message": "Karaoke entry removed from the active lineup and playlist."})


@app.post("/api/admin/karaoke/reset")
def admin_karaoke_reset():
    mode = str(request.form.get("mode", "combined") or "combined").strip()
    if mode not in {"combined", "local"}:
        return jsonify({"ok": False, "message": "That karaoke clear mode is not available."}), 400
    required_phrase = "CLEAR LOCAL KARAOKE" if mode == "local" else "CLEAR KARAOKE"
    if str(request.form.get("confirm_phrase", "") or "").strip() != required_phrase:
        return jsonify(
            {
                "ok": False,
                "message": f"Type {required_phrase} exactly to confirm this destructive action.",
            }
        ), 400

    operation_id = uuid4().hex

    def begin_clear() -> dict[str, object]:
        existing = normalized_karaoke_clear_operation()
        if str(existing.get("status", "")) in KARAOKE_CLEAR_ACTIVE_STATUSES:
            raise ValueError("A karaoke queue clear is already in progress.")

        resuming_failed_clear = existing.get("status") == "failed"
        current_item_ids = [
            str(signup.workflow.get("playlist_item_id", "") or "")
            for signup in karaoke_signups
            if signup.workflow.get("playlist_item_id")
        ]
        if resuming_failed_clear:
            selected_operation_id = str(existing.get("operation_id", "") or operation_id)
            target_item_ids = list(existing.get("target_item_ids", []))
            backup_key = str(existing.get("backup_key", "") or "")
            record_count = max(
                len(karaoke_signups),
                _safe_int(existing.get("record_count"), 0),
            )
            started_at = str(existing.get("started_at", "") or _utc_now_iso())
        else:
            selected_operation_id = operation_id
            target_item_ids = list(dict.fromkeys(current_item_ids))
            backup_key = str(
                write_state_backup_if_available("karaoke-clear") or ""
            )
            record_count = len(karaoke_signups)
            started_at = _utc_now_iso()

        if mode == "local":
            if resuming_failed_clear:
                target_item_ids = list(
                    dict.fromkeys(
                        list(existing.get("target_item_ids", []))
                        + current_item_ids
                    )
                )
                backup_key = str(existing.get("backup_key", "") or backup_key)
            removed_records = len(karaoke_signups)
            karaoke_signups.clear()
            reset_karaoke_runtime_state()
            youtube_karaoke["last_reconciled_at"] = ""
            youtube_karaoke["last_reconciliation_summary"] = {}
            youtube_karaoke["clear_operation"] = {
                "operation_id": selected_operation_id,
                "mode": "local",
                "status": "local_only_completed",
                "started_at": started_at,
                "completed_at": _utc_now_iso(),
                "backup_key": backup_key,
                "record_count": removed_records,
                "target_count": len(target_item_ids),
                "deleted_count": 0,
                "failed_count": len(target_item_ids),
                "target_item_ids": target_item_ids,
                "failed_item_ids": target_item_ids,
                "last_error": (
                    "The local lineup was cleared, but app-managed YouTube "
                    "playlist items were intentionally left unchanged."
                ),
            }
            return {
                "operation_id": selected_operation_id,
                "mode": mode,
                "local_completed": True,
                "record_count": removed_records,
                "target_item_ids": target_item_ids,
            }

        for signup in karaoke_signups:
            playlist_item_id = str(
                signup.workflow.get("playlist_item_id", "") or ""
            )
            if playlist_item_id in target_item_ids:
                signup.workflow["playlist_sync_status"] = "removal_pending"
                signup.workflow["last_sync_error_code"] = ""
                signup.workflow["last_sync_error_message"] = ""
                append_karaoke_history(
                    signup,
                    "playlist_bulk_remove_started",
                    actor_name="admin",
                )
        reset_karaoke_runtime_state()
        youtube_karaoke["clear_operation"] = {
            "operation_id": selected_operation_id,
            "mode": "combined",
            "status": "deleting_youtube",
            "started_at": started_at,
            "completed_at": "",
            "backup_key": backup_key,
            "record_count": record_count,
            "target_count": len(target_item_ids),
            "deleted_count": 0,
            "failed_count": 0,
            "target_item_ids": target_item_ids,
            "failed_item_ids": [],
            "last_error": "",
        }
        return {
            "operation_id": selected_operation_id,
            "mode": mode,
            "local_completed": False,
            "record_count": record_count,
            "target_item_ids": target_item_ids,
        }

    try:
        operation = explicit_state_mutation(begin_clear)
    except (StateMutationBusy, ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "message": str(exc)}), 409

    if operation["local_completed"]:
        return jsonify(
            {
                "ok": True,
                "message": (
                    f"Cleared {operation['record_count']} local karaoke records. "
                    "The YouTube playlist was left unchanged."
                ),
            }
        )

    selected_operation_id = str(operation["operation_id"])
    target_item_ids = [
        str(item_id) for item_id in operation["target_item_ids"]
    ]
    succeeded_item_ids: list[str] = []
    failures: list[tuple[str, YouTubeApiError]] = []
    service = youtube_service()

    for playlist_item_id in target_item_ids:
        try:
            service.delete_playlist_item(playlist_item_id)
            succeeded_item_ids.append(playlist_item_id)
        except YouTubeApiError as exc:
            if exc.http_status == 404 or exc.code in {
                "playlistItemNotFound",
                "videoNotFound",
            }:
                succeeded_item_ids.append(playlist_item_id)
            else:
                failures.append((playlist_item_id, exc))

        def update_progress() -> None:
            current = normalized_karaoke_clear_operation()
            if current.get("operation_id") != selected_operation_id:
                return
            current["deleted_count"] = len(succeeded_item_ids)
            current["failed_count"] = len(failures)
            youtube_karaoke["clear_operation"] = current

        try:
            explicit_state_mutation(update_progress, broadcast=False)
        except StateMutationBusy:
            pass

    if failures:
        failed_item_ids = [item_id for item_id, _ in failures]
        first_error = failures[0][1]

        def finish_failed_clear() -> None:
            current = normalized_karaoke_clear_operation()
            if current.get("operation_id") != selected_operation_id:
                return
            current["status"] = "failed"
            current["deleted_count"] = len(succeeded_item_ids)
            current["failed_count"] = len(failed_item_ids)
            current["failed_item_ids"] = failed_item_ids
            current["last_error"] = (
                f"{len(failed_item_ids)} YouTube playlist item"
                f"{'s' if len(failed_item_ids) != 1 else ''} could not be removed. "
                f"{first_error.message}"
            )
            youtube_karaoke["clear_operation"] = current
            for signup in karaoke_signups:
                playlist_item_id = str(
                    signup.workflow.get("playlist_item_id", "") or ""
                )
                if playlist_item_id in succeeded_item_ids:
                    signup.workflow["playlist_item_id"] = ""
                    signup.workflow["playlist_sync_status"] = "removed"
                    signup.workflow["approval_status"] = "cancelled"
                    append_karaoke_history(
                        signup,
                        "playlist_bulk_remove_confirmed",
                        actor_name="system",
                    )
                elif playlist_item_id in failed_item_ids:
                    signup.workflow["playlist_sync_status"] = "failed"
                    signup.workflow["last_sync_error_code"] = first_error.code
                    signup.workflow["last_sync_error_message"] = first_error.message
                    append_karaoke_history(
                        signup,
                        "playlist_bulk_remove_failed",
                        detail=first_error.message,
                        actor_name="system",
                    )
            reset_karaoke_runtime_state()

        try:
            explicit_state_mutation(finish_failed_clear)
        except StateMutationBusy as exc:
            return jsonify({"ok": False, "message": str(exc)}), 409
        return jsonify(
            {
                "ok": False,
                "message": (
                    "The karaoke queue clear needs attention. "
                    "No active entries will be shown; retry the clear from the admin page."
                ),
            }
        ), 502

    def finish_successful_clear() -> None:
        current = normalized_karaoke_clear_operation()
        if current.get("operation_id") != selected_operation_id:
            return
        record_count = max(
            len(karaoke_signups),
            _safe_int(current.get("record_count"), 0),
        )
        karaoke_signups.clear()
        reset_karaoke_runtime_state()
        youtube_karaoke["last_reconciled_at"] = _utc_now_iso()
        youtube_karaoke["last_reconciliation_summary"] = {
            "synced": 0,
            "missing": 0,
            "out_of_order": 0,
            "orphan_app_items": 0,
            "foreign_items": 0,
        }
        current.update(
            {
                "status": "completed",
                "completed_at": _utc_now_iso(),
                "record_count": record_count,
                "deleted_count": len(target_item_ids),
                "failed_count": 0,
                "target_item_ids": [],
                "failed_item_ids": [],
                "last_error": "",
            }
        )
        youtube_karaoke["clear_operation"] = current

    try:
        explicit_state_mutation(finish_successful_clear)
    except StateMutationBusy as exc:
        return jsonify({"ok": False, "message": str(exc)}), 409
    return jsonify(
        {
            "ok": True,
            "message": (
                f"Cleared {operation['record_count']} karaoke records and "
                f"{len(target_item_ids)} app-managed YouTube playlist items."
            ),
        }
    )


@app.post("/api/admin/karaoke/entries/<entry_id>/replace")
def admin_karaoke_replace(entry_id: str):
    raw_video = request.form.get("youtube_video_id") or request.form.get("youtube_link", "")
    operation_id = uuid4().hex
    try:
        video = verify_youtube_video(raw_video)

        def replace_pending() -> bool:
            require_karaoke_clear_idle()
            signup = find_karaoke_signup(entry_id)
            if not signup:
                raise ValueError("Karaoke entry could not be found.")
            if signup.workflow.get("approval_status") != "pending":
                return False
            signup.workflow["playlist_revision"] = max(
                1, _safe_int(signup.workflow.get("playlist_revision"), 1)
            ) + 1
            signup.youtube = normalize_karaoke_youtube(video)
            signup.youtube_link = str(signup.youtube.get("watch_url", "") or "")
            signup.workflow["video_validation_status"] = "verified"
            append_karaoke_history(signup, "video_replaced", actor_name="admin")
            return True

        if explicit_state_mutation(replace_pending):
            return jsonify({"ok": True, "message": "Pending karaoke video replaced and ready for host approval."})

        def begin_replace() -> dict[str, object]:
            require_karaoke_clear_idle()
            signup = find_karaoke_signup(entry_id)
            if not signup:
                raise ValueError("Karaoke entry could not be found.")
            if signup.workflow.get("approval_status") != "approved":
                raise ValueError("Approve the request before replacing its synchronized video.")
            old_playlist_item_id = str(signup.workflow.get("playlist_item_id", "") or "")
            signup.workflow["playlist_revision"] = max(
                1, _safe_int(signup.workflow.get("playlist_revision"), 1)
            ) + 1
            signup.youtube = normalize_karaoke_youtube(video)
            signup.youtube_link = str(signup.youtube.get("watch_url", "") or "")
            signup.workflow["video_validation_status"] = "verified"
            signup.workflow["playlist_sync_status"] = "pending"
            signup.workflow["operation_id"] = operation_id
            signup.workflow["operation_action"] = "replace"
            signup.workflow["operation_started_at"] = _utc_now_iso()
            append_karaoke_history(signup, "video_replaced", actor_name="admin")
            append_karaoke_history(signup, "playlist_insert_started", actor_name="admin")
            active_entries = approved_karaoke_signups()
            return {
                "playlist_id": str(youtube_karaoke.get("playlist_id", "") or ""),
                "video_id": str(signup.youtube.get("video_id", "") or ""),
                "position": next(
                    (index for index, entry in enumerate(active_entries) if entry.id == entry_id),
                    max(0, len(active_entries) - 1),
                ),
                "note": youtube_playlist_note(signup),
                "old_playlist_item_id": old_playlist_item_id,
            }

        operation = explicit_state_mutation(begin_replace)
        service = youtube_service()
        playlist_items = service.list_playlist_items(str(operation["playlist_id"]))
        existing = find_matching_youtube_playlist_item(
            playlist_items,
            note=str(operation["note"]),
            video_id=str(operation["video_id"]),
            expected_position=int(operation["position"]),
        )
        inserted = existing or service.insert_playlist_item(
            str(operation["playlist_id"]),
            str(operation["video_id"]),
            position=min(int(operation["position"]), len(playlist_items)),
            note=str(operation["note"]),
        )
        new_item_id = str(inserted.get("playlist_item_id", "") or "")
        order_matches = _safe_int(inserted.get("position"), -1) == int(operation["position"])
        orphan_warning = ""
        old_item_id = str(operation["old_playlist_item_id"] or "")
        if old_item_id and old_item_id != new_item_id:
            try:
                service.delete_playlist_item(old_item_id)
            except YouTubeApiError:
                orphan_warning = " The prior playlist item could not be removed and will appear in reconciliation."
        finish_karaoke_playlist_operation(
            entry_id,
            operation_id,
            playlist_item_id=new_item_id,
            event="playlist_replacement_confirmed",
            playlist_sync_status="synced" if order_matches else "out_of_order",
        )
    except YouTubeApiError as exc:
        finish_karaoke_playlist_operation(entry_id, operation_id, error=exc)
        return jsonify({"ok": False, "message": exc.message, "code": exc.code}), 502
    except (StateMutationBusy, ValueError) as exc:
        return jsonify({"ok": False, "message": str(exc)}), 409
    return jsonify({"ok": True, "message": f"Karaoke video replaced and synchronized.{orphan_warning}"})


def reconcile_karaoke_playlist() -> dict[str, object]:
    require_karaoke_clear_idle()
    playlist_id = str(youtube_karaoke.get("playlist_id", "") or "")
    if not playlist_id:
        raise ValueError("Choose a YouTube event playlist first.")
    playlist_items = youtube_service().list_playlist_items(playlist_id)
    def reconcile_state() -> dict[str, object]:
        synced = 0
        missing = 0
        out_of_order = 0
        expected_entries = approved_karaoke_signups()
        expected_notes = set()
        matched_item_ids: set[str] = set()
        for expected_position, signup in enumerate(expected_entries):
            note = youtube_playlist_note(signup)
            expected_notes.add(note)
            item = find_matching_youtube_playlist_item(
                playlist_items,
                playlist_item_id=str(signup.workflow.get("playlist_item_id", "") or ""),
                note=note,
                video_id=str(signup.youtube.get("video_id", "") or ""),
                expected_position=expected_position,
                excluded_item_ids=matched_item_ids,
            )
            if not item:
                signup.workflow["playlist_sync_status"] = "failed"
                signup.workflow["last_sync_error_code"] = "playlist_item_missing"
                signup.workflow["last_sync_error_message"] = "The approved item is missing from the YouTube playlist."
                signup.workflow["operation_id"] = ""
                signup.workflow["operation_action"] = ""
                signup.workflow["operation_started_at"] = ""
                missing += 1
                continue
            matched_item_id = str(item.get("playlist_item_id", "") or "")
            signup.workflow["playlist_item_id"] = matched_item_id
            matched_item_ids.add(matched_item_id)
            signup.workflow["operation_id"] = ""
            signup.workflow["operation_action"] = ""
            signup.workflow["operation_started_at"] = ""
            if int(item.get("position", -1)) != expected_position:
                signup.workflow["playlist_sync_status"] = "out_of_order"
                out_of_order += 1
            else:
                signup.workflow["playlist_sync_status"] = "synced"
                signup.workflow["last_sync_error_code"] = ""
                signup.workflow["last_sync_error_message"] = ""
                synced += 1
        unmatched_items = [
            item
            for item in playlist_items
            if str(item.get("playlist_item_id", "") or "") not in matched_item_ids
        ]
        orphan_count = sum(
            1
            for item in unmatched_items
            if str(item.get("note", "") or "").startswith(
                f"{YOUTUBE_PLAYLIST_NOTE_PREFIX}:"
            )
            and str(item.get("note", "") or "") not in expected_notes
        )
        summary = {
            "synced": synced,
            "missing": missing,
            "out_of_order": out_of_order,
            "orphan_app_items": orphan_count,
            "foreign_items": max(0, len(unmatched_items) - orphan_count),
        }
        youtube_karaoke["last_reconciled_at"] = _utc_now_iso()
        youtube_karaoke["last_reconciliation_summary"] = summary
        return summary

    return explicit_state_mutation(reconcile_state)


@app.post("/api/admin/karaoke/reconcile")
def admin_karaoke_reconcile():
    try:
        summary = reconcile_karaoke_playlist()
    except (StateMutationBusy, ValueError, YouTubeApiError) as exc:
        message = exc.message if isinstance(exc, YouTubeApiError) else str(exc)
        return jsonify({"ok": False, "message": message}), 502
    return jsonify({"ok": True, "message": "YouTube playlist reconciliation completed.", "summary": summary})


@app.post("/api/admin/karaoke/sync-order")
def admin_karaoke_sync_order():
    if karaoke_clear_blocks_mutation():
        return jsonify(
            {
                "ok": False,
                "message": (
                    "Karaoke queue clearing is in progress or needs attention. "
                    "Finish or retry that operation first."
                ),
            }
        ), 409
    entries = approved_karaoke_signups()
    playlist_id = str(youtube_karaoke.get("playlist_id", "") or "")
    if not playlist_id:
        return jsonify({"ok": False, "message": "Choose a YouTube event playlist first."}), 409
    failures: list[tuple[str, YouTubeApiError]] = []
    service = youtube_service()
    try:
        current_items = service.list_playlist_items(playlist_id)
    except YouTubeApiError as exc:
        return jsonify({"ok": False, "message": exc.message, "code": exc.code}), 502
    current_by_id = {
        str(item.get("playlist_item_id", "") or ""): item
        for item in current_items
    }
    for position, signup in enumerate(entries):
        playlist_item_id = str(signup.workflow.get("playlist_item_id", "") or "")
        if not playlist_item_id:
            failures.append((signup.id, YouTubeApiError("playlist_item_missing", "Playlist item is missing.")))
            continue
        current_item = current_by_id.get(playlist_item_id)
        if (
            current_item
            and _safe_int(current_item.get("position"), -1) == position
            and str(current_item.get("video_id", "") or "")
            == str(signup.youtube.get("video_id", "") or "")
        ):
            continue
        try:
            service.move_playlist_item(
                playlist_item_id,
                playlist_id,
                str(signup.youtube.get("video_id", "") or ""),
                position=position,
                note=youtube_playlist_note(signup),
            )
        except YouTubeApiError as exc:
            failures.append((signup.id, exc))

    if not failures:
        try:
            confirmed_items = service.list_playlist_items(playlist_id)
            confirmed_by_id = {
                str(item.get("playlist_item_id", "") or ""): item
                for item in confirmed_items
            }
            for position, signup in enumerate(entries):
                playlist_item_id = str(signup.workflow.get("playlist_item_id", "") or "")
                confirmed = confirmed_by_id.get(playlist_item_id)
                if (
                    not confirmed
                    or _safe_int(confirmed.get("position"), -1) != position
                    or str(confirmed.get("video_id", "") or "")
                    != str(signup.youtube.get("video_id", "") or "")
                ):
                    failures.append(
                        (
                            signup.id,
                            YouTubeApiError(
                                "playlist_order_not_confirmed",
                                "YouTube did not confirm the requested playlist position.",
                            ),
                        )
                    )
        except YouTubeApiError as exc:
            failures.extend((signup.id, exc) for signup in entries)

    def finish_order() -> None:
        failed_by_id = {entry_id: error for entry_id, error in failures}
        for signup in approved_karaoke_signups():
            error = failed_by_id.get(signup.id)
            if error:
                signup.workflow["playlist_sync_status"] = "failed"
                signup.workflow["last_sync_error_code"] = error.code
                signup.workflow["last_sync_error_message"] = error.message
                append_karaoke_history(signup, "playlist_order_failed", detail=error.message, actor_name="system")
            else:
                signup.workflow["playlist_sync_status"] = "synced"
                signup.workflow["last_sync_error_code"] = ""
                signup.workflow["last_sync_error_message"] = ""
                append_karaoke_history(signup, "playlist_order_confirmed", actor_name="system")

    try:
        explicit_state_mutation(finish_order)
    except StateMutationBusy as exc:
        return jsonify({"ok": False, "message": str(exc)}), 409
    if failures:
        return jsonify({"ok": False, "message": f"{len(failures)} playlist positions could not be synchronized."}), 502
    return jsonify({"ok": True, "message": "YouTube playlist order synchronized."})


@app.post("/api/admin/karaoke/youtube/test")
def admin_youtube_test_connection():
    try:
        channel = youtube_service().connection_status()

        def save_connection() -> None:
            youtube_karaoke["channel_id"] = channel["channel_id"]
            youtube_karaoke["channel_title"] = channel["channel_title"]
            youtube_karaoke["connection_status"] = "connected"
            youtube_karaoke["last_connection_check_at"] = _utc_now_iso()
            youtube_karaoke["last_connection_error"] = ""

        explicit_state_mutation(save_connection)
    except (StateMutationBusy, YouTubeApiError) as exc:
        message = exc.message if isinstance(exc, YouTubeApiError) else str(exc)
        return jsonify({"ok": False, "message": message}), 502
    return jsonify({"ok": True, "message": f"Connected to YouTube channel {channel['channel_title']}."})


@app.get("/api/admin/karaoke/youtube/playlists")
def admin_youtube_playlists():
    try:
        payload = youtube_service().list_owned_playlists(page_token=request.args.get("page_token", ""))
    except YouTubeApiError as exc:
        return jsonify({"error": exc.message, "code": exc.code}), 502
    return jsonify(payload)


@app.post("/api/admin/karaoke/youtube/playlist")
def admin_youtube_select_playlist():
    playlist_id = request.form.get("playlist_id", "").strip()
    try:
        payload = youtube_service().list_owned_playlists()
        playlist = next((item for item in payload["items"] if item["playlist_id"] == playlist_id), None)
        if not playlist:
            raise ValueError("Choose a playlist owned by the connected YouTube account.")

        def select() -> None:
            youtube_karaoke["playlist_id"] = playlist["playlist_id"]
            youtube_karaoke["playlist_title"] = playlist["title"]
            youtube_karaoke["playlist_privacy"] = playlist["privacy"]
            youtube_karaoke["last_reconciled_at"] = ""
            youtube_karaoke["last_reconciliation_summary"] = {}

        explicit_state_mutation(select)
    except (StateMutationBusy, ValueError, YouTubeApiError) as exc:
        message = exc.message if isinstance(exc, YouTubeApiError) else str(exc)
        return jsonify({"ok": False, "message": message}), 409
    return jsonify({"ok": True, "message": f"Selected playlist {playlist['title']}."})


@app.post("/api/admin/karaoke/youtube/playlist/create")
def admin_youtube_create_playlist():
    title = request.form.get("title", "").strip() or f"Halloween Karaoke {app.config['PARTY_YEAR']}"
    privacy = request.form.get("privacy", "private")
    try:
        playlist = youtube_service().create_playlist(title, privacy=privacy)

        def select_created() -> None:
            youtube_karaoke["playlist_id"] = playlist["playlist_id"]
            youtube_karaoke["playlist_title"] = playlist["title"]
            youtube_karaoke["playlist_privacy"] = playlist["privacy"]

        explicit_state_mutation(select_created)
    except (StateMutationBusy, YouTubeApiError) as exc:
        message = exc.message if isinstance(exc, YouTubeApiError) else str(exc)
        return jsonify({"ok": False, "message": message}), 502
    return jsonify({"ok": True, "message": f"Created and selected playlist {playlist['title']}."})


@app.get("/admin/karaoke/youtube/connect")
def admin_youtube_connect():
    redirect_uri = url_for("admin_youtube_callback", _external=True, _scheme="https")
    try:
        flow = build_oauth_flow(youtube_config(), redirect_uri=redirect_uri)
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
    except YouTubeApiError as exc:
        return redirect(url_for("admin_portal", admin_view="karaoke", youtube_error=exc.message))
    session["youtube_oauth_state"] = state
    session["youtube_oauth_code_verifier"] = str(flow.code_verifier or "")
    return redirect(authorization_url)


@app.get("/admin/karaoke/youtube/callback")
def admin_youtube_callback():
    expected_state = str(session.pop("youtube_oauth_state", "") or "")
    code_verifier = str(session.pop("youtube_oauth_code_verifier", "") or "")
    provided_state = request.args.get("state", "")
    if not expected_state or not secrets.compare_digest(expected_state, provided_state):
        return redirect(url_for("admin_portal", admin_view="karaoke", youtube_error="YouTube authorization state did not match."))
    if not code_verifier:
        return redirect(url_for("admin_portal", admin_view="karaoke", youtube_error="YouTube authorization session expired. Reconnect and try again."))
    redirect_uri = url_for("admin_youtube_callback", _external=True, _scheme="https")
    try:
        flow = build_oauth_flow(youtube_config(), redirect_uri=redirect_uri, state=expected_state)
        flow.code_verifier = code_verifier
        authorization_response = (
            f"{redirect_uri}?{request.query_string.decode('utf-8', errors='ignore')}"
        )
        flow.fetch_token(authorization_response=authorization_response)
        refresh_token = str(flow.credentials.refresh_token or app.config.get("YOUTUBE_REFRESH_TOKEN", "") or "")
        if not refresh_token:
            raise YouTubeApiError("refresh_token_missing", "Google did not return offline YouTube access. Reconnect and approve access.")
        if app.config.get("TESTING"):
            app.config["YOUTUBE_REFRESH_TOKEN"] = refresh_token
        else:
            youtube_vault_store().update_refresh_token(refresh_token)
            app.config["YOUTUBE_REFRESH_TOKEN"] = refresh_token
        channel = youtube_service().connection_status()

        def save_connection() -> None:
            youtube_karaoke["channel_id"] = channel["channel_id"]
            youtube_karaoke["channel_title"] = channel["channel_title"]
            youtube_karaoke["connection_status"] = "connected"
            youtube_karaoke["last_connection_check_at"] = _utc_now_iso()
            youtube_karaoke["last_connection_error"] = ""

        explicit_state_mutation(save_connection)
    except Exception as exc:
        api_error = exc if isinstance(exc, YouTubeApiError) else YouTubeApiError(
            "oauth_failed", "YouTube authorization could not be completed."
        )
        app.logger.warning("YouTube OAuth callback failed: %s", type(exc).__name__)
        return redirect(url_for("admin_portal", admin_view="karaoke", youtube_error=api_error.message))
    return redirect(url_for("admin_portal", admin_view="karaoke", youtube_success="YouTube account connected."))


@app.post("/admin/karaoke/youtube/disconnect")
def admin_youtube_disconnect():
    try:
        youtube_service().revoke_credentials()
        if not app.config.get("TESTING"):
            youtube_vault_store().update_refresh_token("")
        app.config["YOUTUBE_REFRESH_TOKEN"] = ""

        def disconnect() -> None:
            youtube_karaoke["connection_status"] = "not_connected"
            youtube_karaoke["last_connection_check_at"] = _utc_now_iso()
            youtube_karaoke["last_connection_error"] = ""

        explicit_state_mutation(disconnect)
    except (StateMutationBusy, YouTubeApiError, RuntimeError) as exc:
        message = exc.message if isinstance(exc, YouTubeApiError) else str(exc)
        return redirect(url_for("admin_portal", admin_view="karaoke", youtube_error=message))
    return redirect(url_for("admin_portal", admin_view="karaoke", youtube_success="YouTube account disconnected."))


@app.route("/party/login", methods=["GET", "POST"])
def party_login():
    errors: List[str] = []
    next_page = normalize_next_page(
        request.args.get("next") or request.form.get("next"),
        url_for("party_dashboard"),
    )

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        provided_password = request.form.get("password", "")
        normalized_username = normalize_username(username)
        account = user_accounts.get(normalized_username)

        if not username:
            errors.append("Username is required.")
        if not provided_password:
            errors.append("Password is required.")
        if not errors and (
            not account
            or not check_password_hash(account.get("password_hash", ""), provided_password)
        ):
            errors.append("Incorrect username or password.")
        if not errors:
            user_id = account["id"]
            display_name = account["username"]

            session["user_id"] = user_id
            session["username"] = display_name
            sync_attendee_session_roles(account)
            registered_users[user_id] = display_name
            persist_state_if_available()

            return redirect(next_page)

    return render_template(
        "halloween_login.html",
        errors=errors,
        next_page=next_page,
        show_admin_link=False,
    )


@app.route("/party/password-reset", methods=["GET", "POST"])
def password_reset_request():
    messages: List[str] = []
    errors: List[str] = []
    next_page = normalize_next_page(
        request.args.get("next") or request.form.get("next"),
        url_for("party_login"),
    )

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        normalized_email = normalize_email(email)
        if not email:
            errors.append("Email is required.")
        elif len(email) > 120 or not normalized_email:
            errors.append("Enter a valid email address.")

        if not errors:
            account_match = find_user_account_by_email(normalized_email)
            if account_match:
                normalized_username, account = account_match
                token = create_password_reset_token(normalized_username, account)
                sent = send_password_reset_email(account, token)
                if not sent:
                    app.logger.warning("Password reset email was not sent for %s.", normalized_email)
            messages.append("If that email is registered, we sent a password reset link.")
            persist_state_if_available()

    return render_template(
        "password_reset_request.html",
        errors=errors,
        messages=messages,
        next_page=next_page,
        show_admin_link=False,
    )


@app.route("/party/password-reset/<token>", methods=["GET", "POST"])
def password_reset_confirm(token: str):
    errors: List[str] = []
    messages: List[str] = []
    token_record = valid_password_reset_record(token)

    if token_record is None:
        errors.append("That password reset link is invalid or expired.")
        return render_template(
            "password_reset_form.html",
            errors=errors,
            messages=messages,
            token=token,
            token_valid=False,
            show_admin_link=False,
        )

    token_hash, record = token_record
    account = user_accounts.get(str(record["normalized_username"]))
    if account is None:
        errors.append("That password reset link is invalid or expired.")
        return render_template(
            "password_reset_form.html",
            errors=errors,
            messages=messages,
            token=token,
            token_valid=False,
            show_admin_link=False,
        )

    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(new_password) < 8:
            errors.append("Password must be at least 8 characters.")
        elif new_password != confirm_password:
            errors.append("Passwords do not match.")

        if not errors:
            account["password_hash"] = generate_password_hash(new_password)
            mark_password_reset_token_used(token_hash)
            persist_state_if_available()
            messages.append("Password updated. You can sign in with your new password.")
            return render_template(
                "password_reset_form.html",
                errors=errors,
                messages=messages,
                token=token,
                token_valid=False,
                reset_complete=True,
                show_admin_link=False,
            )

    return render_template(
        "password_reset_form.html",
        errors=errors,
        messages=messages,
        token=token,
        token_valid=True,
        reset_complete=False,
        show_admin_link=False,
    )


@app.route("/party/register", methods=["GET", "POST"])
def party_register():
    errors: List[str] = []
    next_page = normalize_next_page(
        request.args.get("next") or request.form.get("next"),
        url_for("party_dashboard"),
    )

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        provided_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        normalized_username = normalize_username(username)

        if not username:
            errors.append("Username is required.")
        elif len(username) > 80:
            errors.append("Username must be 80 characters or fewer.")
        elif normalized_username in user_accounts:
            errors.append("That username is already registered.")

        if not email:
            errors.append("Email is required so the hosts can send party updates.")
        elif len(email) > 120:
            errors.append("Email must be 120 characters or fewer.")
        elif not normalize_email(email):
            errors.append("Enter a valid email address for party updates.")
        if len(provided_password) < 8:
            errors.append("Password must be at least 8 characters.")
        elif provided_password != confirm_password:
            errors.append("Passwords do not match.")

        if not errors:
            account = create_user_account(username, provided_password, email)
            user_accounts[normalized_username] = account
            session["user_id"] = account["id"]
            session["username"] = account["username"]
            sync_attendee_session_roles(account)
            registered_users[account["id"]] = account["username"]
            send_account_welcome_email(account)
            persist_state_if_available()
            return redirect(next_page)

    return render_template(
        "halloween_register.html",
        errors=errors,
        next_page=next_page,
        show_admin_link=False,
    )


@app.route("/party/menu", methods=["GET", "POST"])
def party_menu():
    errors: List[str] = []
    messages: List[str] = []
    user_id = str(session.get("user_id", "") or "")
    account = current_user_account()

    if not user_id or not account:
        return redirect(url_for("party_login", next=url_for("party_menu")))
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))

    if request.method == "POST":
        item_id = request.form.get("menu_item_id", "").strip()
        item = find_menu_item(item_id)
        can_order, order_error = can_order_menu_item(user_id, item)
        if not can_order:
            errors.append(order_error)

        if not errors and item:
            order = create_drink_order(user_id, account, item)
            drink_orders.append(order)
            send_drink_order_placed_email(order)
            messages.append(
                f"Order received for {order['item_name']}. Estimated ready time: "
                f"{format_time_label(order['estimated_ready_at']) or 'soon'}."
            )
            persist_state_if_available()
            return redirect(url_for("party_menu", ordered="1"))

    if request.args.get("ordered") == "1":
        messages.append("Your drink order was sent to the bar.")

    return render_template(
        "menu.html",
        errors=errors,
        messages=messages,
        menu_sections=build_menu_sections(),
        drink_orders=user_drink_orders(user_id),
        specialty_drink_count=user_specialty_drink_count(user_id),
        specialty_drink_limit=SPECIALTY_DRINK_INCLUDED_LIMIT,
        specialty_extra_orders_open=specialty_extra_orders_are_open(),
        show_admin_link=False,
    )


@app.route("/party/drink-history", methods=["GET", "POST"])
def party_drink_history():
    errors: List[str] = []
    messages: List[str] = []
    user_id = str(session.get("user_id", "") or "")
    account = current_user_account()

    if not user_id or not account:
        return redirect(url_for("party_login", next=url_for("party_drink_history")))
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))

    if request.method == "POST":
        order_id = request.form.get("order_id", "").strip()
        original_order = find_drink_order(order_id)
        if not original_order or str(original_order.get("user_id", "")) != user_id:
            errors.append("That drink order could not be found.")
        else:
            item = find_menu_item(str(original_order.get("menu_item_id", "") or ""))
            can_order, order_error = can_order_menu_item(user_id, item)
            if not can_order:
                errors.append(order_error)
            elif item:
                order = create_drink_order(user_id, account, item)
                drink_orders.append(order)
                send_drink_order_placed_email(order)
                messages.append(f"Reordered {order['item_name']}.")
                persist_state_if_available()
                return redirect(url_for("party_drink_history", reordered="1"))

    if request.args.get("reordered") == "1":
        messages.append("Your reorder was sent to the bar.")

    orders = user_drink_orders(user_id)
    reorderable_item_ids = {
        str(item.get("id", ""))
        for item in menu_items
        if can_order_menu_item(user_id, item)[0]
    }

    return render_template(
        "drink_history.html",
        errors=errors,
        messages=messages,
        drink_orders=orders,
        reorderable_item_ids=reorderable_item_ids,
        specialty_drink_count=user_specialty_drink_count(user_id),
        specialty_drink_limit=SPECIALTY_DRINK_INCLUDED_LIMIT,
        specialty_extra_orders_open=specialty_extra_orders_are_open(),
        bartender_tip_settings=bartender_tip_settings,
        bartender_tip_methods=bartender_tip_methods(),
        show_admin_link=False,
    )


@app.route("/party/bartender-tip")
def party_bartender_tip():
    user_id = str(session.get("user_id", "") or "")
    account = current_user_account()

    if not user_id or not account:
        return redirect(url_for("party_login", next=url_for("party_bartender_tip")))
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))
    if not bartender_tip_settings.get("enabled"):
        return redirect(url_for("party_drink_history"))

    return render_template(
        "bartender_tip.html",
        bartender_tip_settings=bartender_tip_settings,
        bartender_tip_methods=bartender_tip_methods(),
        show_admin_link=False,
    )


def bartender_queue_context() -> dict[str, object]:
    sorted_orders = sorted(
        drink_orders,
        key=lambda order: (
            {"in_progress": 0, "received": 1, "complete": 3}.get(str(order.get("status")), 4),
            drink_order_priority_bucket(order),
            str(order.get("created_at", "")),
        ),
    )
    recent_completed = [
        order for order in sorted_orders if order.get("status") == "complete"
    ][-12:]
    active_orders = [order for order in sorted_orders if order.get("status") != "complete"]
    version_source = [
        {
            "id": str(order.get("id", "")),
            "status": str(order.get("status", "")),
            "started_at": str(order.get("started_at", "")),
            "completed_at": str(order.get("completed_at", "")),
            "created_at": str(order.get("created_at", "")),
            "item_name": str(order.get("item_name", "")),
            "username": str(order.get("username", "")),
        }
        for order in sorted_orders
    ]
    queue_version = hashlib.sha256(
        json.dumps(version_source, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return {
        "active_orders": active_orders,
        "completed_orders": list(reversed(recent_completed)),
        "average_completion_seconds": average_drink_completion_seconds(),
        "queue_version": queue_version,
    }


@app.route("/bartender", methods=["GET", "POST"])
def bartender_portal():
    global live_display_notice_override
    errors: List[str] = []
    messages: List[str] = []

    if request.method == "POST":
        order_id = request.form.get("order_id", "").strip()
        requested_status = request.form.get("status", "").strip()
        order = find_drink_order(order_id)

        if not order:
            errors.append("That drink order could not be found.")
        elif requested_status not in {"in_progress", "complete"}:
            errors.append("Choose a valid order status.")
        elif requested_status == "in_progress" and order.get("status") != "received":
            errors.append("Only received orders can be started.")
        elif requested_status == "complete" and order.get("status") not in {"received", "in_progress"}:
            errors.append("Only active orders can be completed.")

        if not errors and order:
            now_iso = _utc_now_iso()
            if requested_status == "in_progress":
                order["status"] = "in_progress"
                order["started_at"] = now_iso
                messages.append(f"Started {order.get('item_name')} for {order.get('username')}.")
            elif requested_status == "complete":
                order["status"] = "complete"
                order["completed_at"] = now_iso
                started_or_created_at = (
                    parse_utc_iso(order.get("started_at"))
                    or parse_utc_iso(order.get("created_at"))
                    or datetime.now(timezone.utc)
                )
                order["completed_seconds"] = max(
                    1,
                    int((datetime.now(timezone.utc) - started_or_created_at).total_seconds()),
                )
                send_drink_ready_email(order)
                live_display_notice_override = build_drink_ready_override(order)
                messages.append(f"Marked {order.get('item_name')} ready for {order.get('username')}.")
                broadcast_display_update()
            persist_state_if_available()

    queue_context = bartender_queue_context()

    return render_template(
        "bartender.html",
        errors=errors,
        messages=messages,
        **queue_context,
        show_admin_link=session_has_role("admin"),
    )


@app.route("/api/bartender-queue")
def bartender_queue_data():
    queue_context = bartender_queue_context()
    html = render_template("_bartender_queue.html", **queue_context)
    return jsonify(
        {
            "html": html,
            "queue_version": queue_context["queue_version"],
            "active_count": len(queue_context["active_orders"]),
            "completed_count": len(queue_context["completed_orders"]),
        }
    )


@app.route("/party/logout", methods=["POST"])
@app.route("/admin/logout", methods=["POST"])
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("party_login"))


@app.post("/admin/role-preview/exit")
def exit_role_preview():
    """Clear local preview state even when the selected role hides admin routes."""
    if not session_has_role("admin"):
        return redirect(url_for("admin_login", next=request.path))

    session.pop("role_preview", None)
    return redirect(url_for("admin_portal", admin_view="public"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    errors: List[str] = []
    next_page = normalize_next_page(
        request.args.get("next") or request.form.get("next"),
        url_for("admin_portal"),
    )

    if session_has_role("admin"):
        return redirect(next_page)

    if request.method == "POST":
        admin_password = app.config.get("ADMIN_PASSWORD", "")
        provided_password = request.form.get("password", "")

        if not admin_password:
            errors.append("Admin password is not configured.")
        elif provided_password == admin_password:
            grant_session_role("admin")
            return redirect(next_page)
        else:
            errors.append("Incorrect admin password.")

    return render_template(
        "admin_login.html",
        errors=errors,
        next_page=next_page,
        show_admin_link=False,
    )


@app.route("/admin", defaults={"admin_view": "home"}, methods=["GET", "POST"])
@app.route("/admin/<admin_view>", methods=["GET", "POST"])
def admin_portal(admin_view: str):
    if admin_view not in ADMIN_WORKSPACES:
        abort(404)

    errors: List[str] = []
    messages: List[str] = []
    global live_display_event_override, live_display_notice_override
    global submitted_costume_votes, costume_ballots, karaoke_state
    global landing_page_target, event_experience_mode, party_code_hash, party_code_hint, party_details, display_settings, rsvp_notification_email
    global bartender_tip_settings, dj_song_requests

    ensure_costume_votes_alignment()

    def parse_index(raw_index: str | None, total: int, label: str) -> int | None:
        if raw_index is None:
            errors.append(f"Missing {label} index.")
            return None
        try:
            index_value = int(raw_index)
        except ValueError:
            errors.append(f"Invalid {label} index.")
            return None
        if not 0 <= index_value < total:
            errors.append(f"{label.capitalize()} entry could not be found.")
            return None
        return index_value

    def parse_entry_index(
        signups: list[object],
        label: str,
        raw_id: str | None,
        raw_index: str | None,
    ) -> int | None:
        entry_index = find_signup_index_by_id(signups, raw_id)
        if entry_index is not None:
            return entry_index

        if raw_id:
            errors.append(f"{label.capitalize()} entry could not be found.")
            return None

        return parse_index(raw_index, len(signups), label)

    def block_if_voting_locked(action_label: str) -> bool:
        if not is_costume_lineup_locked_for_voting():
            return False

        errors.append(
            f"{action_label} is disabled while costume voting is open. Lock a winner or restart voting before changing the lineup."
        )
        return True

    def menu_item_from_form(existing_id: str | None = None, existing_created_at: str | None = None) -> dict[str, object] | None:
        image_url = request.form.get("image_url", "").strip()
        normalized_image_url = safe_image_url(image_url)
        if image_url and not normalized_image_url:
            errors.append("Menu image URL must be http, https, or a /static/ path.")

        category = normalize_menu_category(request.form.get("category", "drink"))
        drink_type = normalize_drink_type(request.form.get("drink_type", "standard"))
        beverage_type = normalize_beverage_type(request.form.get("beverage_type", "alcoholic"))
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        recipe = request.form.get("recipe", "").strip()
        orderable_values = request.form.getlist("orderable")
        orderable = True if not orderable_values else "yes" in orderable_values

        if not name:
            errors.append("Menu item name is required.")
        elif len(name) > 100:
            errors.append("Menu item name must be 100 characters or fewer.")
        if len(description) > 500:
            errors.append("Menu item description must be 500 characters or fewer.")
        if len(recipe) > 1200:
            errors.append("Drink recipe must be 1200 characters or fewer.")
        if category == "food" and recipe:
            recipe = ""

        if errors:
            return None

        return {
            "id": existing_id or uuid4().hex,
            "name": name,
            "category": category,
            "description": description,
            "image_url": normalized_image_url,
            "recipe": recipe,
            "available": request.form.get("available") == "yes",
            "drink_type": drink_type if category == "drink" else "standard",
            "beverage_type": beverage_type if category == "drink" else "non_alcoholic",
            "orderable": orderable if category == "drink" else False,
            "created_at": existing_created_at or _utc_now_iso(),
        }

    def dj_song_from_form(existing_id: str | None = None, existing_created_at: str | None = None) -> dict[str, object] | None:
        raw_artwork_url = request.form.get("artwork_url", "").strip()
        normalized_artwork_url = safe_image_url(raw_artwork_url)
        title = request.form.get("title", "").strip()
        artist = request.form.get("artist", "").strip()
        apple_music_id = request.form.get("apple_music_id", "").strip()
        album = request.form.get("album", "").strip()
        try:
            duration_ms = max(0, int(request.form.get("duration_ms", "0") or 0))
        except ValueError:
            duration_ms = 0

        if not title:
            errors.append("DJ song title is required.")
        elif len(title) > 180:
            errors.append("DJ song title must be 180 characters or fewer.")
        if not artist:
            errors.append("DJ artist is required.")
        elif len(artist) > 180:
            errors.append("DJ artist must be 180 characters or fewer.")
        if not apple_music_id:
            errors.append("An Apple Music song ID is required for playback.")
        elif len(apple_music_id) > 160:
            errors.append("Apple Music song ID must be 160 characters or fewer.")
        if len(album) > 180:
            errors.append("Album must be 180 characters or fewer.")
        if raw_artwork_url and not normalized_artwork_url:
            errors.append("DJ artwork URL must be http, https, or a /static/ path.")
        if errors:
            return None

        return normalize_dj_song(
            {
                "id": existing_id or uuid4().hex,
                "title": title,
                "artist": artist,
                "apple_music_id": apple_music_id,
                "album": album,
                "artwork_url": normalized_artwork_url,
                "duration_ms": duration_ms,
                "explicit": request.form.get("explicit") == "yes",
                "enabled": request.form.get("enabled") == "yes",
                "created_at": existing_created_at or _utc_now_iso(),
            }
        )

    def bartender_tip_settings_from_form() -> dict[str, object] | None:
        image_url = request.form.get("tip_image_url", "").strip()
        uploaded_image_url, upload_error = save_uploaded_bartender_tip_image(request.files.get("tip_image_upload"))
        if upload_error:
            errors.append(upload_error)
        if uploaded_image_url:
            image_url = uploaded_image_url

        normalized_image_url = safe_image_url(image_url)
        if image_url and not normalized_image_url:
            errors.append("Bartender tip image URL must be http, https, or a /static/ path.")

        settings = {
            "enabled": request.form.get("tip_enabled") == "yes",
            "display_name": request.form.get("tip_display_name", "").strip(),
            "note": request.form.get("tip_note", "").strip(),
            "image_url": normalized_image_url,
            "zelle": request.form.get("tip_zelle", "").strip(),
            "paypal": request.form.get("tip_paypal", "").strip(),
            "venmo": request.form.get("tip_venmo", "").strip(),
            "cash_app": request.form.get("tip_cash_app", "").strip(),
        }
        if len(settings["display_name"]) > 80:
            errors.append("Bartender tip display name must be 80 characters or fewer.")
        if len(settings["note"]) > 240:
            errors.append("Bartender tip note must be 240 characters or fewer.")
        if any(len(str(settings[key])) > 120 for key in ("zelle", "paypal", "venmo", "cash_app")):
            errors.append("Bartender payment handles must be 120 characters or fewer.")
        if errors:
            return None
        return normalize_bartender_tip_settings(settings)

    def roles_from_account_form() -> list[str]:
        roles = {"regular"}
        if request.form.get("bartender") == "yes":
            roles.add("bartender")
        return sorted(roles)

    def account_fields_from_form(existing_key: str | None = None) -> dict[str, object] | None:
        username = request.form.get("username", "").strip()
        normalized_username = normalize_username(username)
        email = request.form.get("email", "").strip()
        normalized_email = normalize_email(email)

        if not username:
            errors.append("Account username is required.")
        elif len(username) > 80:
            errors.append("Account username must be 80 characters or fewer.")
        elif normalized_username in user_accounts and normalized_username != existing_key:
            errors.append("That account username is already registered.")

        if not email:
            errors.append("Account email is required.")
        elif len(email) > 120:
            errors.append("Account email must be 120 characters or fewer.")
        elif not normalized_email:
            errors.append("Enter a valid account email address.")

        if errors:
            return None

        return {
            "username": username,
            "normalized_username": normalized_username,
            "email": normalized_email,
            "email_updates_acknowledged": True,
            "roles": roles_from_account_form(),
        }

    def rsvp_from_form(existing_id: str | None = None, existing_created_at: str | None = None) -> RSVPSignup | None:
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        normalized_contact = normalize_email(contact)
        note = request.form.get("note", "").strip()
        try:
            guest_count = int(request.form.get("guest_count", "1") or 1)
        except ValueError:
            guest_count = 1

        if not name:
            errors.append("RSVP name is required.")
        elif len(name) > 80:
            errors.append("RSVP name must be 80 characters or fewer.")
        if not contact:
            errors.append("RSVP email is required.")
        elif len(contact) > 120:
            errors.append("RSVP email must be 120 characters or fewer.")
        elif not normalized_contact:
            errors.append("Enter a valid RSVP email address.")
        if not 1 <= guest_count <= 12:
            errors.append("RSVP guest count must be between 1 and 12.")
        if len(note) > RSVP_NOTE_MAX_LENGTH:
            errors.append(f"RSVP note must be {RSVP_NOTE_MAX_LENGTH} characters or fewer.")

        if errors:
            return None

        return RSVPSignup(
            id=existing_id or uuid4().hex,
            name=name,
            contact=normalized_contact,
            guest_count=guest_count,
            note=note,
            created_at=existing_created_at or _utc_now_iso(),
            email_updates_acknowledged=True,
        )

    def selected_update_recipient_ids() -> set[str]:
        return {
            recipient_id.strip()
            for recipient_id in request.form.getlist("recipient_ids")
            if recipient_id.strip()
        }

    def update_email_message(prefix: str, sent_count: int, failed_count: int, selected_count: int) -> str:
        if not app.config["EMAIL_UPDATES_ENABLED"]:
            return f"{prefix} Email notifications are disabled."
        if selected_count == 0:
            return f"{prefix} No email recipients were selected."
        if failed_count:
            return (
                f"{prefix} Email sent to {sent_count} selected recipient"
                f"{'s' if sent_count != 1 else ''}; {failed_count} failed."
            )
        return (
            f"{prefix} Email sent to {sent_count} selected recipient"
            f"{'s' if sent_count != 1 else ''}."
        )

    if request.method == "POST":
        action = request.form.get("action", "")
        should_broadcast = False
        if karaoke_clear_blocks_mutation() and action in {
            "add_karaoke",
            "update_karaoke",
            "delete_karaoke",
            "start_karaoke_party",
            "call_karaoke_singer",
            "mark_karaoke_on_stage",
            "complete_karaoke_and_advance",
            "skip_karaoke_singer",
            "move_karaoke_to_top",
            "move_karaoke_up",
            "move_karaoke_down",
            "move_karaoke_to_end",
        }:
            errors.append(
                "Karaoke queue clearing is in progress or needs attention. "
                "Finish or retry that operation first."
            )
            action = ""

        if action == "set_role_preview":
            requested_preview = request.form.get("role_preview", "")
            if requested_preview in ROLE_PREVIEW_OPTIONS:
                session["role_preview"] = requested_preview
                messages.append(
                    f"Role preview enabled for {ROLE_PREVIEW_OPTIONS[requested_preview]['label']}."
                )
                preview_destinations = {
                    "regular": "party_dashboard",
                    "bartender": "bartender_portal",
                    "admin": "admin_portal",
                }
                return redirect(url_for(preview_destinations[requested_preview]))
            else:
                session.pop("role_preview", None)
                messages.append("Role preview cleared. Full session view restored.")

        elif action == "clear_role_preview":
            session.pop("role_preview", None)
            messages.append("Role preview cleared. Full session view restored.")

        elif action == "add_dj_song":
            song = dj_song_from_form()
            if song:
                dj_playlist.append(song)
                messages.append(f"Added {song['title']} by {song['artist']} to the DJ playlist.")
                should_broadcast = True

        elif action in {"approve_dj_song_request", "reject_dj_song_request"}:
            request_id = request.form.get("request_id", "").strip()
            request_index = next(
                (index for index, entry in enumerate(dj_song_requests) if entry.get("id") == request_id),
                None,
            )
            if request_index is None:
                errors.append("Song request could not be found.")
            else:
                request_entry = dj_song_requests.pop(request_index)
                requested_song = request_entry.get("song", {})
                if action == "approve_dj_song_request":
                    playlist_song = normalize_dj_song(
                        {
                            **requested_song,
                            "id": uuid4().hex,
                            "created_at": _utc_now_iso(),
                            "enabled": True,
                        }
                    )
                    if playlist_song is None:
                        errors.append("Song request could not be converted into a playlist entry.")
                        dj_song_requests.insert(request_index, request_entry)
                    else:
                        insertion_index = secrets.randbelow(len(dj_playlist) + 1)
                        dj_playlist.insert(insertion_index, playlist_song)
                        messages.append(
                            f"Approved {playlist_song['title']} and added it at playlist position {insertion_index + 1}."
                        )
                        should_broadcast = True
                else:
                    request_song = requested_song if isinstance(requested_song, dict) else {}
                    messages.append(f"Rejected {request_song.get('title', 'the song')} request from {request_entry.get('requester_name', 'a guest')}.")
                    should_broadcast = True

        elif action == "update_dj_song":
            song_id = request.form.get("song_id", "").strip()
            song_index = next((index for index, song in enumerate(dj_playlist) if song.get("id") == song_id), None)
            if song_index is None:
                errors.append("DJ song could not be found.")
            else:
                updated_song = dj_song_from_form(
                    existing_id=song_id,
                    existing_created_at=str(dj_playlist[song_index].get("created_at", "") or ""),
                )
                if updated_song:
                    dj_playlist[song_index] = updated_song
                    messages.append(f"Updated {updated_song['title']} in the DJ playlist.")
                    should_broadcast = True

        elif action == "delete_dj_song":
            song_id = request.form.get("song_id", "").strip()
            song_index = next((index for index, song in enumerate(dj_playlist) if song.get("id") == song_id), None)
            if song_index is None:
                errors.append("DJ song could not be found.")
            else:
                removed_song = dj_playlist.pop(song_index)
                desired = dj_state["desired"]
                desired["queue_order"] = [candidate_id for candidate_id in desired.get("queue_order", []) if candidate_id != song_id]
                if desired.get("song_id") == song_id:
                    desired["song_id"] = ""
                if str(dj_state["receiver"].get("current_song_id", "")) == song_id:
                    queue_dj_command("stop", requested_by="Admin")
                messages.append(f"Removed {removed_song['title']} from the DJ playlist.")
                should_broadcast = True

        elif action in {"move_dj_song_up", "move_dj_song_down"}:
            song_id = request.form.get("song_id", "").strip()
            song_index = next((index for index, song in enumerate(dj_playlist) if song.get("id") == song_id), None)
            if song_index is None:
                errors.append("DJ song could not be found.")
            elif action == "move_dj_song_up" and song_index == 0:
                messages.append("DJ song is already at the top of the playlist.")
            elif action == "move_dj_song_down" and song_index == len(dj_playlist) - 1:
                messages.append("DJ song is already at the bottom of the playlist.")
            else:
                target_index = song_index - 1 if action == "move_dj_song_up" else song_index + 1
                dj_playlist[song_index], dj_playlist[target_index] = dj_playlist[target_index], dj_playlist[song_index]
                messages.append("DJ playlist order updated.")
                should_broadcast = True

        elif action == "reset_dj_workflow":
            queue_dj_workflow_reset(requested_by="Admin")
            if dj_receiver_is_online():
                messages.append("DJ workflow reset sent to the live display. Waiting for acknowledgement.")
            else:
                messages.append("DJ workflow reset saved. It will complete when the live display reconnects.")
            should_broadcast = True

        elif action in {"play_dj_song", "play_dj_playlist", "shuffle_dj_playlist", "pause_dj", "stop_dj", "next_dj", "previous_dj"}:
            action_map = {
                "play_dj_song": "play_song",
                "play_dj_playlist": "play_playlist",
                "shuffle_dj_playlist": "shuffle_playlist",
                "pause_dj": "pause",
                "stop_dj": "stop",
                "next_dj": "next",
                "previous_dj": "previous",
            }
            command = queue_dj_command(action_map[action], request.form.get("song_id", "").strip(), requested_by="Admin")
            if not command:
                errors.append("Add and enable at least one valid DJ song before sending this command.")
            else:
                messages.append("DJ command sent to the live display. Waiting for receiver confirmation.")
                should_broadcast = True

        elif action == "update_costume":
            index = parse_entry_index(
                costume_signups,
                "costume signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            name = request.form.get("name", "").strip()
            costume = request.form.get("costume", "").strip()
            contact = request.form.get("contact", "").strip()

            if not name:
                errors.append("Costume signup name is required.")
            if not costume:
                errors.append("Costume description is required.")

            if index is not None and name and costume:
                costume_signups[index] = CostumeSignup(
                    id=costume_signups[index].id,
                    name=name,
                    costume=costume,
                    contact=contact,
                )
                messages.append(f"Updated costume signup for {name}.")
                should_broadcast = True

        elif action == "update_landing_page":
            requested_target = request.form.get("landing_page_target", "").strip()
            normalized_target = normalize_landing_page_target(requested_target)
            if requested_target != normalized_target:
                errors.append("Choose a valid landing page.")
            else:
                landing_page_target = normalized_target
                messages.append(
                    f"Public landing page set to {LANDING_PAGE_TARGETS[landing_page_target]['label']}."
                )

        elif action == "update_event_experience_mode":
            requested_mode = request.form.get("event_experience_mode", "").strip()
            normalized_mode = normalize_event_experience_mode(requested_mode)
            if requested_mode != normalized_mode:
                errors.append("Choose a valid guest experience mode.")
            else:
                event_experience_mode = normalized_mode
                messages.append(
                    f"Guest experience mode set to {EVENT_EXPERIENCE_MODES[event_experience_mode]['label']}."
                )

        elif action == "update_party_code":
            new_party_code = request.form.get("party_code", "").strip()
            new_party_code_hint = request.form.get("party_code_hint", "").strip()
            if len(new_party_code_hint) > 120:
                errors.append("Party code hint must be 120 characters or fewer.")
            if not new_party_code and not party_code_hash:
                errors.append("Enter a party code before accepting guest RSVP submissions.")
            if new_party_code and len(new_party_code) < 4:
                errors.append("Party code must be at least 4 characters.")
            if not errors:
                if new_party_code:
                    party_code_hash = generate_password_hash(new_party_code)
                party_code_hint = new_party_code_hint
                messages.append("Party code settings updated.")

        elif action == "update_rsvp_notification_email":
            raw_email = request.form.get("rsvp_notification_email", "").strip()
            normalized_email = normalize_rsvp_notification_email(raw_email)
            if raw_email and not normalized_email:
                errors.append("Enter a valid RSVP notification email address, or leave it blank to disable host notifications.")
            if not errors:
                rsvp_notification_email = normalized_email
                if rsvp_notification_email:
                    messages.append(f"RSVP notifications will be sent to {rsvp_notification_email}.")
                else:
                    messages.append("RSVP host email notifications disabled.")

        elif action == "update_display_wifi":
            updated_display_settings = {
                "wifi_network": request.form.get("display_wifi_network", "").strip(),
                "wifi_password": request.form.get("display_wifi_password", "").strip(),
            }
            if len(updated_display_settings["wifi_network"]) > 120:
                errors.append("WiFi network name must be 120 characters or fewer.")
            if len(updated_display_settings["wifi_password"]) > 120:
                errors.append("WiFi password must be 120 characters or fewer.")
            if not errors:
                display_settings = updated_display_settings
                messages.append("Live display WiFi settings updated.")
                should_broadcast = True

        elif action == "update_bartender_tip_settings":
            updated_tip_settings = bartender_tip_settings_from_form()
            if updated_tip_settings:
                bartender_tip_settings = updated_tip_settings
                messages.append("Bartender tip settings updated.")

        elif action == "update_party_details":
            updated_details = {
                "date": request.form.get("party_date", "").strip(),
                "time": request.form.get("party_time", "").strip(),
                "location": request.form.get("party_location", "").strip(),
                "map_address": request.form.get("party_map_address", "").strip(),
                "overview": request.form.get("party_overview", "").strip(),
            }
            if not updated_details["date"]:
                errors.append("Party date is required.")
            if not updated_details["time"]:
                errors.append("Party time is required.")
            if not updated_details["location"]:
                errors.append("Party location is required.")
            if not updated_details["overview"]:
                errors.append("Party overview is required.")
            if any(len(updated_details[key]) > 240 for key in ("date", "time", "location", "map_address")):
                errors.append("Party date, time, location, and map address must each be 240 characters or fewer.")
            if len(updated_details["overview"]) > 1000:
                errors.append("Party overview must be 1000 characters or fewer.")
            if not errors:
                party_details = updated_details
                messages.append("Party details updated on the RSVP page.")
                should_broadcast = True

        elif action == "add_rsvp_update":
            title = request.form.get("title", "").strip()
            message = request.form.get("message", "").strip()
            if not title:
                errors.append("RSVP update title is required.")
            elif len(title) > 100:
                errors.append("RSVP update title must be 100 characters or fewer.")
            if not message:
                errors.append("RSVP update message is required.")
            elif len(message) > RSVP_UPDATE_MESSAGE_MAX_LENGTH:
                errors.append(f"RSVP update message must be {RSVP_UPDATE_MESSAGE_MAX_LENGTH} characters or fewer.")
            if not errors:
                posted_update = RSVPUpdate(
                    id=uuid4().hex,
                    title=title,
                    message=message,
                    created_at=_utc_now_iso(),
                )
                rsvp_updates.append(posted_update)
                selected_recipients = selected_update_recipient_ids()
                sent_count, failed_count = send_rsvp_update_emails(posted_update, selected_recipients)
                messages.append(
                    update_email_message(
                        "RSVP update posted.",
                        sent_count,
                        failed_count,
                        len(selected_recipients),
                    )
                )
                should_broadcast = True

        elif action == "delete_rsvp_update":
            update_id = request.form.get("update_id", "")
            update_index = next(
                (index for index, update in enumerate(rsvp_updates) if update.id == update_id),
                None,
            )
            if update_index is None:
                errors.append("RSVP update could not be found.")
            else:
                removed_update = rsvp_updates.pop(update_index)
                messages.append(f"Removed RSVP update: {removed_update.title}.")
                should_broadcast = True

        elif action == "resend_rsvp_update":
            update_id = request.form.get("update_id", "")
            update = next((candidate for candidate in rsvp_updates if candidate.id == update_id), None)
            if update is None:
                errors.append("RSVP update could not be found.")
            else:
                selected_recipients = selected_update_recipient_ids()
                sent_count, failed_count = send_rsvp_update_emails(update, selected_recipients)
                messages.append(
                    update_email_message(
                        f"Resent RSVP update: {update.title}.",
                        sent_count,
                        failed_count,
                        len(selected_recipients),
                    )
                )

        elif action == "add_rsvp":
            new_rsvp = rsvp_from_form()
            if new_rsvp:
                rsvp_signups.append(new_rsvp)
                messages.append(f"Added RSVP for {new_rsvp.name}.")

        elif action == "update_rsvp":
            rsvp_id = request.form.get("rsvp_id", "").strip()
            rsvp_index = find_rsvp_index_by_id(rsvp_id)
            if rsvp_index is None:
                errors.append("RSVP could not be found.")
            else:
                existing_rsvp = rsvp_signups[rsvp_index]
                updated_rsvp = rsvp_from_form(
                    existing_id=existing_rsvp.id,
                    existing_created_at=existing_rsvp.created_at,
                )
                if updated_rsvp:
                    rsvp_signups[rsvp_index] = updated_rsvp
                    messages.append(f"Updated RSVP for {updated_rsvp.name}.")

        elif action == "delete_rsvp":
            rsvp_id = request.form.get("rsvp_id", "").strip()
            rsvp_index = find_rsvp_index_by_id(rsvp_id)
            if rsvp_index is None:
                errors.append("RSVP could not be found.")
            else:
                removed_rsvp = rsvp_signups.pop(rsvp_index)
                if session.get("rsvp_id") == removed_rsvp.id:
                    session.pop("rsvp_id", None)
                messages.append(f"Removed RSVP for {removed_rsvp.name}.")

        elif action == "add_menu_item":
            item = menu_item_from_form()
            if item:
                menu_items.append(item)
                messages.append(f"Added {item['name']} to the menu.")

        elif action == "update_menu_item":
            item_id = request.form.get("item_id", "").strip()
            item_index = next(
                (index for index, item in enumerate(menu_items) if str(item.get("id", "")) == item_id),
                None,
            )
            if item_index is None:
                errors.append("Menu item could not be found.")
            else:
                existing_item = menu_items[item_index]
                item = menu_item_from_form(
                    existing_id=str(existing_item.get("id", "")),
                    existing_created_at=str(existing_item.get("created_at", "")),
                )
                if item:
                    menu_items[item_index] = item
                    messages.append(f"Updated menu item {item['name']}.")

        elif action == "delete_menu_item":
            item_id = request.form.get("item_id", "").strip()
            item_index = next(
                (index for index, item in enumerate(menu_items) if str(item.get("id", "")) == item_id),
                None,
            )
            if item_index is None:
                errors.append("Menu item could not be found.")
            elif any(order.get("menu_item_id") == item_id and order.get("status") != "complete" for order in drink_orders):
                errors.append("Menu items with active drink orders cannot be removed. Mark it unavailable instead.")
            else:
                removed_item = menu_items.pop(item_index)
                messages.append(f"Removed {removed_item.get('name')} from the menu.")

        elif action == "set_user_roles":
            account_id = request.form.get("account_id", "").strip()
            account = next(
                (candidate for candidate in user_accounts.values() if str(candidate.get("id", "")) == account_id),
                None,
            )
            if not account:
                errors.append("User account could not be found.")
            else:
                roles = {"regular"}
                if request.form.get("bartender") == "yes":
                    roles.add("bartender")
                account["roles"] = sorted(roles)
                messages.append(f"Updated roles for {account.get('username')}.")

        elif action == "add_user_account":
            account_fields = account_fields_from_form()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            if len(password) < 8:
                errors.append("Account password must be at least 8 characters.")
            elif password != confirm_password:
                errors.append("Account passwords do not match.")
            if account_fields and not errors:
                account = create_user_account(
                    str(account_fields["username"]),
                    password,
                    str(account_fields["email"]),
                )
                account["email_updates_acknowledged"] = bool(account_fields["email_updates_acknowledged"])
                account["roles"] = account_fields["roles"]
                user_accounts[str(account_fields["normalized_username"])] = account
                registered_users[str(account["id"])] = str(account["username"])
                welcome_sent = send_account_welcome_email(account)
                if app.config["EMAIL_UPDATES_ENABLED"]:
                    if welcome_sent:
                        messages.append(f"Added account for {account['username']} and sent a welcome email.")
                    else:
                        messages.append(f"Added account for {account['username']}; welcome email was not sent.")
                else:
                    messages.append(f"Added account for {account['username']}.")

        elif action == "update_user_account":
            account_id = request.form.get("account_id", "").strip()
            existing_key = find_user_account_key_by_id(account_id)
            if existing_key is None:
                errors.append("User account could not be found.")
            else:
                account_fields = account_fields_from_form(existing_key)
                if account_fields:
                    account = user_accounts.pop(existing_key)
                    account["username"] = account_fields["username"]
                    account["email"] = account_fields["email"]
                    account["email_updates_acknowledged"] = account_fields["email_updates_acknowledged"]
                    account["roles"] = account_fields["roles"]
                    new_key = str(account_fields["normalized_username"])
                    user_accounts[new_key] = account
                    registered_users[str(account["id"])] = str(account["username"])
                    messages.append(f"Updated account for {account['username']}.")

        elif action == "reset_user_password":
            account_id = request.form.get("account_id", "").strip()
            account_key = find_user_account_key_by_id(account_id)
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            if account_key is None:
                errors.append("User account could not be found.")
            if len(password) < 8:
                errors.append("New account password must be at least 8 characters.")
            elif password != confirm_password:
                errors.append("New account passwords do not match.")
            if account_key is not None and not errors:
                account = user_accounts[account_key]
                account["password_hash"] = generate_password_hash(password)
                for token_hash, record in list(password_reset_tokens.items()):
                    if str(record.get("account_id", "")) == account_id:
                        password_reset_tokens.pop(token_hash, None)
                messages.append(f"Reset password for {account.get('username')}.")

        elif action == "delete_user_account":
            account_id = request.form.get("account_id", "").strip()
            account_key = find_user_account_key_by_id(account_id)
            if account_key is None:
                errors.append("User account could not be found.")
            else:
                account = user_accounts.pop(account_key)
                registered_users.pop(account_id, None)
                submitted_costume_votes.discard(account_id)
                costume_ballots.pop(account_id, None)
                for token_hash, record in list(password_reset_tokens.items()):
                    if (
                        str(record.get("account_id", "")) == account_id
                        or normalize_username(str(record.get("normalized_username", ""))) == account_key
                    ):
                        password_reset_tokens.pop(token_hash, None)
                messages.append(f"Deleted account for {account.get('username')}.")

        elif action == "delete_costume":
            index = parse_entry_index(
                costume_signups,
                "costume signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            if index is not None and not block_if_voting_locked("Removing costume signups"):
                removed = costume_signups.pop(index)
                for ballot in costume_ballots.values():
                    ballot.pop(removed.id, None)
                messages.append(f"Removed costume signup for {removed.name}.")
                should_broadcast = True

        elif action == "add_costume":
            name = request.form.get("name", "").strip()
            costume = request.form.get("costume", "").strip()
            contact = request.form.get("contact", "").strip()

            if not name:
                errors.append("Costume signup name is required to add a new entry.")
            if not costume:
                errors.append("Costume description is required to add a new entry.")

            if name and costume and not block_if_voting_locked("Adding costume signups"):
                costume_signups.append(
                    CostumeSignup(
                        id=uuid4().hex,
                        name=name,
                        costume=costume,
                        contact=contact,
                    )
                )
                messages.append(f"Added costume signup for {name}.")
                should_broadcast = True

        elif action == "update_karaoke":
            index = parse_entry_index(
                karaoke_signups,
                "karaoke signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            name = request.form.get("name", "").strip()
            song_title = request.form.get("song_title", "").strip()
            artist = request.form.get("artist", "").strip()
            youtube_link = request.form.get("youtube_link", "").strip()

            if not name:
                errors.append("Karaoke signup name is required.")
            if not song_title:
                errors.append("Song title is required.")
            if not artist:
                errors.append("Artist is required.")

            if index is not None and name and song_title and artist:
                existing_signup = karaoke_signups[index]
                existing_signup.name = name
                existing_signup.song_title = song_title
                existing_signup.artist = artist
                if not app.config.get("YOUTUBE_KARAOKE_ENABLED"):
                    existing_signup.youtube_link = youtube_link
                    existing_signup.youtube = normalize_karaoke_youtube({}, youtube_link)
                append_karaoke_history(
                    existing_signup,
                    "details_updated",
                    actor_name="admin",
                )
                messages.append(f"Updated karaoke signup for {name}.")
                should_broadcast = True

        elif action == "delete_karaoke":
            index = parse_entry_index(
                karaoke_signups,
                "karaoke signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            if index is not None:
                candidate = karaoke_signups[index]
                if (
                    app.config.get("YOUTUBE_KARAOKE_ENABLED")
                    and candidate.workflow.get("playlist_item_id")
                    and candidate.workflow.get("playlist_sync_status") != "removed"
                ):
                    errors.append("Remove this synchronized entry from the dedicated Karaoke workspace.")
                else:
                    removed = karaoke_signups.pop(index)
                    if karaoke_state.get("current_singer_id") == removed.id:
                        karaoke_state["current_singer_id"] = None
                        karaoke_state["current_singer_index"] = None
                    messages.append(f"Removed karaoke signup for {removed.name}.")
                    should_broadcast = True

        elif action == "add_karaoke":
            name = request.form.get("name", "").strip()
            song_title = request.form.get("song_title", "").strip()
            artist = request.form.get("artist", "").strip()
            youtube_link = request.form.get("youtube_link", "").strip()

            if not name:
                errors.append("Karaoke signup name is required to add a new entry.")
            if not song_title:
                errors.append("Song title is required to add a new entry.")
            if not artist:
                errors.append("Artist is required to add a new entry.")

            if name and song_title and artist:
                karaoke_signups.append(
                    KaraokeSignup(
                        id=uuid4().hex,
                        name=name,
                        song_title=song_title,
                        artist=artist,
                        youtube_link=youtube_link,
                    )
                )
                messages.append(f"Added karaoke signup for {name}.")
                should_broadcast = True

        elif action == "move_costume_up":
            index = parse_entry_index(
                costume_signups,
                "costume signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            if index is not None and not block_if_voting_locked("Reordering costume signups"):
                if index == 0:
                    messages.append("Costume signup is already at the top.")
                else:
                    moved_signup = costume_signups[index]
                    costume_signups[index - 1], costume_signups[index] = (
                        costume_signups[index],
                        costume_signups[index - 1],
                    )
                    messages.append(f"Moved costume signup for {moved_signup.name} up.")
                    should_broadcast = True

        elif action == "move_costume_down":
            index = parse_entry_index(
                costume_signups,
                "costume signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            if index is not None and not block_if_voting_locked("Reordering costume signups"):
                if index == len(costume_signups) - 1:
                    messages.append("Costume signup is already at the bottom.")
                else:
                    moved_signup = costume_signups[index]
                    costume_signups[index + 1], costume_signups[index] = (
                        costume_signups[index],
                        costume_signups[index + 1],
                    )
                    messages.append(f"Moved costume signup for {moved_signup.name} down.")
                    should_broadcast = True

        elif action == "start_costume_contest":
            voting_url = url_for("party_costume_voting", _external=True)
            live_display_event_override = {
                "type": "contest_start",
                "title": "The Costume Contest Has Begun!",
                "highlight": "Submit your votes now",
                "message": "Visit the costume voting page to rate every competitor from 1-10.",
                "details": [
                    f"Open {voting_url} on your device to cast your ballot.",
                ],
            }
            messages.append("Live display updated with costume contest kickoff message.")
            contest_state["contest_started"] = True
            contest_state["voting_open"] = True
            contest_state["winner"] = None
            contest_state["winner_locked"] = False
            contest_state["scoreboard_card"] = None
            contest_state["show_scoreboard_card"] = False
            karaoke_state["party_started"] = False
            karaoke_state["current_singer_index"] = None
            karaoke_state["current_singer_id"] = None
            costume_ballots.clear()
            submitted_costume_votes.clear()
            write_state_backup_if_available("contest-start")
            should_broadcast = True

        elif action == "stop_costume_contest":
            contest_state["contest_started"] = False
            contest_state["voting_open"] = False
            if live_display_event_override and live_display_event_override.get("type") in {
                "contest_start",
                "winner",
            }:
                live_display_event_override = None
            messages.append("Costume contest stopped. Attendee voting is now hidden.")
            write_state_backup_if_available("contest-stop")
            should_broadcast = True

        elif action == "reset_costume_contest":
            contest_state.clear()
            contest_state.update(copy.deepcopy(DEFAULT_CONTEST_STATE))
            costume_ballots.clear()
            submitted_costume_votes.clear()
            if live_display_event_override and live_display_event_override.get("type") in {
                "contest_start",
                "winner",
            }:
                live_display_event_override = None
            messages.append("Costume contest reset. Votes, winner, and display override were cleared.")
            write_state_backup_if_available("contest-reset")
            should_broadcast = True

        elif action == "show_costume_winner":
            winner = contest_state.get("winner")
            if winner:
                live_display_event_override = {
                    "type": "winner",
                    "title": "Costume Contest Champion",
                    "highlight": winner.get("name"),
                    "message": f"Dressed as {winner.get('costume')}",
                    "details": [
                        f"Average score: {winner.get('average', 0):.2f}",
                        f"Total votes: {winner.get('count', 0)}",
                    ],
                }
                messages.append(
                    f"Live display updated to announce {winner.get('name')} as the costume contest winner."
                )
                should_broadcast = True
            else:
                errors.append("Lock a costume contest winner before announcing it on the live display.")

        elif action == "clear_display_override":
            live_display_event_override = None
            live_display_notice_override = None
            messages.append("Live display has been restored to the rotating schedule.")
            if contest_state.get("winner_locked") and contest_state.get("scoreboard_card"):
                contest_state["show_scoreboard_card"] = True
            should_broadcast = True

        elif action == "start_karaoke_party":
            karaoke_lineup = public_karaoke_signups()
            if karaoke_lineup:
                lineup_entries = [
                    {
                        "id": signup.id,
                        "name": signup.name,
                        "song_title": signup.song_title,
                        "artist": signup.artist,
                    }
                    for signup in karaoke_lineup
                ]

                karaoke_state["party_started"] = True
                karaoke_state["current_singer_index"] = None
                first_ready = next(
                    (signup for signup in karaoke_lineup if karaoke_entry_can_stage(signup)),
                    None,
                )
                karaoke_state["current_singer_id"] = (
                    first_ready.id if first_ready else karaoke_lineup[0].id
                )
                karaoke_state["stage_mode"] = "countdown"
                refresh_karaoke_stage_selection()
                contest_state["contest_started"] = False
                contest_state["voting_open"] = False

                mountain_offset = timezone(timedelta(hours=-7), name="MST")
                now_mountain = datetime.now(mountain_offset)
                countdown_target = now_mountain.replace(
                    hour=23, minute=0, second=0, microsecond=0
                )
                if countdown_target <= now_mountain:
                    countdown_target += timedelta(days=1)

                live_display_event_override = {
                    "type": "karaoke_start",
                    "title": "Halloween Karaoke Party",
                    "highlight": "Showtime begins at 11:00 PM MST",
                    "message": "The lineup is getting ready. Countdown to the first singers!",
                    "karaoke": {
                        "lineup": lineup_entries,
                        "countdown_target": countdown_target.isoformat(),
                        "countdown_label": "11:00 PM MST",
                    },
                }
                messages.append(
                    "Live display updated with the karaoke kickoff countdown."
                )
                write_state_backup_if_available("karaoke-start")
                should_broadcast = True
            else:
                errors.append(
                    "Approve at least one karaoke signup before starting the karaoke party."
                )

        elif action == "call_karaoke_singer":
            entry_id = request.form.get("entry_id", "").strip()
            signup = find_karaoke_signup(entry_id) if entry_id else find_karaoke_signup(
                str(karaoke_state.get("next_singer_id", "") or "")
            )
            if not signup:
                signup = next(
                    (entry for entry in active_karaoke_signups() if karaoke_entry_can_stage(entry)),
                    None,
                )
            if not signup:
                errors.append("No ready karaoke singer is available to call.")
            elif not karaoke_entry_can_stage(signup):
                errors.append("This singer is not ready. Resolve video approval and playlist synchronization first.")
            else:
                previous = find_karaoke_signup(str(karaoke_state.get("current_singer_id", "") or ""))
                if previous and previous.id != signup.id and previous.workflow.get("performance_status") == "called":
                    previous.workflow["performance_status"] = "waiting"
                signup.workflow["performance_status"] = "called"
                signup.workflow["called_at"] = _utc_now_iso()
                append_karaoke_history(signup, "called_to_stage", actor_name="admin")
                karaoke_state["party_started"] = True
                karaoke_state["current_singer_id"] = signup.id
                karaoke_state["stage_mode"] = "called"
                refresh_karaoke_stage_selection()
                live_display_event_override = build_karaoke_stage_override(signup, "call")
                messages.append(f"Called {signup.name} to the karaoke stage.")
                should_broadcast = True

        elif action == "mark_karaoke_on_stage":
            signup = find_karaoke_signup(
                request.form.get("entry_id", "").strip()
                or str(karaoke_state.get("current_singer_id", "") or "")
            )
            if not signup or signup.workflow.get("performance_status") not in {"called", "waiting"}:
                errors.append("Call a ready singer before marking them on stage.")
            elif not (
                karaoke_entry_can_stage(signup)
                or signup.workflow.get("performance_status") == "called"
            ):
                errors.append("This singer is not ready for the stage.")
            else:
                signup.workflow["performance_status"] = "on_stage"
                signup.workflow["started_at"] = _utc_now_iso()
                append_karaoke_history(signup, "performance_started", actor_name="admin")
                karaoke_state["current_singer_id"] = signup.id
                karaoke_state["stage_mode"] = "on_stage"
                refresh_karaoke_stage_selection()
                live_display_event_override = build_karaoke_stage_override(signup, "on_stage")
                messages.append(f"Marked {signup.name} on stage. Start the video in the official YouTube tab.")
                should_broadcast = True

        elif action in {"complete_karaoke_and_advance", "skip_karaoke_singer"}:
            signup = find_karaoke_signup(
                request.form.get("entry_id", "").strip()
                or str(karaoke_state.get("current_singer_id", "") or "")
            )
            if not signup:
                errors.append("No current karaoke singer was found.")
            else:
                if action == "complete_karaoke_and_advance":
                    signup.workflow["performance_status"] = "completed"
                    signup.workflow["completed_at"] = _utc_now_iso()
                    append_karaoke_history(signup, "performance_completed", actor_name="admin")
                    messages.append(f"Completed {signup.name}'s karaoke performance.")
                else:
                    signup.workflow["performance_status"] = "skipped"
                    signup.workflow["completed_at"] = _utc_now_iso()
                    append_karaoke_history(
                        signup,
                        "performance_skipped",
                        detail=request.form.get("reason", "").strip(),
                        actor_name="admin",
                    )
                    messages.append(f"Skipped {signup.name} and advanced the lineup.")
                karaoke_state["current_singer_id"] = None
                karaoke_state["stage_mode"] = "standby"
                refresh_karaoke_stage_selection()
                next_signup = find_karaoke_signup(str(karaoke_state.get("next_singer_id", "") or ""))
                if next_signup:
                    live_display_event_override = build_karaoke_stage_override(next_signup, "call")
                else:
                    live_display_event_override = build_karaoke_stage_override(signup, "complete")
                should_broadcast = True

        elif action in {
            "move_karaoke_to_top",
            "move_karaoke_up",
            "move_karaoke_down",
            "move_karaoke_to_end",
        }:
            entry_id = request.form.get("entry_id", "").strip()
            approved_entries = active_karaoke_signups()
            movable_ids = {entry.id for entry in approved_entries}
            current_position = next(
                (idx for idx, entry in enumerate(approved_entries) if entry.id == entry_id),
                None,
            )
            if current_position is None:
                errors.append("Karaoke signup could not be found.")
            else:
                signup = approved_entries.pop(current_position)
                if action == "move_karaoke_to_top":
                    target_position = 0
                elif action == "move_karaoke_up":
                    target_position = max(0, current_position - 1)
                elif action == "move_karaoke_down":
                    target_position = min(len(approved_entries), current_position + 1)
                else:
                    target_position = len(approved_entries)
                approved_entries.insert(target_position, signup)
                ordered_approved = iter(approved_entries)
                karaoke_signups[:] = [
                    next(ordered_approved)
                    if entry.id in movable_ids
                    else entry
                    for entry in karaoke_signups
                ]
                if signup.workflow.get("performance_status") in {"called", "on_stage"}:
                    signup.workflow["performance_status"] = "waiting"
                if app.config.get("YOUTUBE_KARAOKE_ENABLED"):
                    for entry in approved_karaoke_signups():
                        if entry.workflow.get("playlist_sync_status") == "synced":
                            entry.workflow["playlist_sync_status"] = "out_of_order"
                append_karaoke_history(
                    signup,
                    {
                        "move_karaoke_to_top": "moved_to_top",
                        "move_karaoke_up": "moved_up",
                        "move_karaoke_down": "moved_down",
                        "move_karaoke_to_end": "moved_to_end",
                    }[action],
                    actor_name="admin",
                )
                karaoke_state["current_singer_id"] = None
                refresh_karaoke_stage_selection()
                messages.append(f"Updated {signup.name}'s karaoke lineup position.")
                should_broadcast = True

        elif action == "stop_karaoke_party":
            karaoke_state["party_started"] = False
            karaoke_state["current_singer_index"] = None
            karaoke_state["current_singer_id"] = None
            karaoke_state["next_singer_id"] = None
            karaoke_state["stage_mode"] = "standby"
            if live_display_event_override and str(live_display_event_override.get("type", "")).startswith("karaoke_"):
                live_display_event_override = None
            messages.append("Karaoke party stopped.")
            write_state_backup_if_available("karaoke-stop")
            should_broadcast = True

        elif action == "reset_karaoke_party":
            karaoke_state.clear()
            karaoke_state.update(copy.deepcopy(DEFAULT_KARAOKE_STATE))
            if live_display_event_override and live_display_event_override.get("type") == "karaoke_start":
                live_display_event_override = None
            messages.append("Karaoke party reset. The lineup was kept.")
            write_state_backup_if_available("karaoke-reset")
            should_broadcast = True

        elif action == "lock_costume_winner":
            scoreboard, leader = build_costume_scoreboard()
            if leader and leader["count"]:
                contest_state["winner"] = {
                    "id": leader["id"],
                    "name": leader["name"],
                    "costume": leader["costume"],
                    "average": leader["average"],
                    "count": leader["count"],
                    "total": leader["total"],
                }
                contest_state["contest_started"] = False
                contest_state["winner_locked"] = True
                contest_state["voting_open"] = False
                top_entries = rank_costume_entries(scoreboard)[:3]
                contest_state["scoreboard_card"] = (
                    create_scoreboard_card(top_entries) if top_entries else None
                )
                contest_state["show_scoreboard_card"] = False
                messages.append(
                    f"Locked in {leader['name']} as the costume contest champion."
                )
                write_state_backup_if_available("winner-lock")
                should_broadcast = True
            else:
                errors.append("No votes have been submitted yet, so a winner cannot be locked in.")

        else:
            errors.append("Unknown action submitted. Please try again.")

        ensure_costume_votes_alignment()

        if should_broadcast:
            broadcast_display_update()

    costume_scores, costume_leader = build_costume_scoreboard()
    top_costume_rankings = rank_costume_entries(costume_scores)[:5]

    return render_template(
        "admin_karaoke.html" if admin_view == "karaoke" else "admin.html",
        admin_view=admin_view,
        admin_workspaces=ADMIN_WORKSPACES,
        costume_signups=costume_signups,
        karaoke_signups=karaoke_signups,
        errors=errors,
        messages=messages,
        show_admin_link=True,
        costume_scores=costume_scores,
        costume_leader=costume_leader,
        live_override=current_display_override(),
        top_costume_rankings=top_costume_rankings,
        karaoke_state=karaoke_state,
        costume_lineup_locked=is_costume_lineup_locked_for_voting(),
        landing_page_target=normalize_landing_page_target(landing_page_target),
        landing_page_targets=LANDING_PAGE_TARGETS,
        event_experience_mode=normalize_event_experience_mode(event_experience_mode),
        event_experience_modes=EVENT_EXPERIENCE_MODES,
        effective_party_day_has_arrived=party_day_has_arrived(),
        party_code_configured=party_code_is_configured(),
        party_code_hint=party_code_hint,
        rsvp_notification_email=rsvp_notification_email,
        display_settings=display_settings,
        party_details=party_details,
        rsvp_signups=rsvp_signups,
        rsvp_guest_total=sum(signup.guest_count for signup in rsvp_signups),
        rsvp_note_max_length=RSVP_NOTE_MAX_LENGTH,
        rsvp_update_message_max_length=RSVP_UPDATE_MESSAGE_MAX_LENGTH,
        rsvp_updates=sorted_rsvp_updates(),
        update_email_recipients=available_update_email_recipients(),
        email_updates_enabled=app.config["EMAIL_UPDATES_ENABLED"],
        menu_items=menu_items,
        menu_sections=build_menu_sections(),
        drink_orders=drink_orders,
        active_drink_order_count=len(active_drink_orders()),
        average_drink_completion_seconds=average_drink_completion_seconds(),
        specialty_drink_order_count=sum(
            1 for order in drink_orders if normalize_drink_type(order.get("drink_type")) == "specialty"
        ),
        specialty_limit_user_count=sum(
            1 for account in user_accounts.values()
            if user_specialty_drink_count(str(account.get("id", ""))) >= SPECIALTY_DRINK_INCLUDED_LIMIT
        ),
        bartender_tip_settings=bartender_tip_settings,
        bartender_tip_methods=bartender_tip_methods(),
        user_accounts=user_accounts,
        dj_playlist=dj_playlist,
        dj_song_requests=dj_song_requests,
        dj_state=dj_view_state(),
        apple_music_configured=apple_music_is_configured(),
        karaoke_admin=karaoke_admin_view_state(),
        karaoke_admin_state_url=url_for("admin_karaoke_state"),
        karaoke_admin_search_url=url_for("admin_karaoke_search"),
    )


@app.route("/admin/export/state")
def export_state():
    if redis_state_available:
        load_state_from_redis()
    backup_key = write_state_backup_if_available("manual-export")
    export_payload = snapshot_state()
    export_payload["backup_key"] = backup_key
    return send_json_export(export_payload, "halloween-state.json")


@app.route("/admin/export/costume-results")
def export_costume_results():
    if redis_state_available:
        load_state_from_redis()
    return send_json_export(
        build_costume_results_export(),
        "halloween-costume-results.json",
    )


@app.route("/admin/export/karaoke-lineup")
def export_karaoke_lineup():
    if redis_state_available:
        load_state_from_redis()
    return send_json_export(
        build_karaoke_lineup_export(),
        "halloween-karaoke-lineup.json",
    )


@app.route("/party/costumes", methods=["GET", "POST"])
def party_costumes():
    errors: List[str] = []
    submitted = False
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))

    ensure_costume_votes_alignment()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        costume = request.form.get("costume", "").strip()
        contact = request.form.get("contact", "").strip()

        if not name:
            errors.append("Name is required.")
        if not costume:
            errors.append("Costume description is required.")

        if not errors:
            costume_signups.append(
                CostumeSignup(
                    id=uuid4().hex,
                    name=name,
                    costume=costume,
                    contact=contact,
                )
            )
            submitted = True
            broadcast_display_update()
            return redirect(url_for("party_costumes", success="1"))

    if request.args.get("success") == "1":
        submitted = True

    return render_template(
        "costume_signup.html",
        errors=errors,
        submitted=submitted,
        costume_signups=costume_signups,
        show_admin_link=False,
    )


@app.route("/party/karaoke", methods=["GET", "POST"])
def party_karaoke():
    errors: List[str] = []
    submitted = False
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))

    karaoke_form = {
        "name": str(session.get("username", "") or "").strip(),
        "song_title": "",
        "artist": "",
        "youtube_link": "",
        "youtube_video_id": "",
    }
    selected_youtube: dict[str, object] | None = None
    if request.method == "POST":
        name = request.form.get("name", "").strip() or str(session.get("username", "") or "").strip()
        song_title = request.form.get("song_title", "").strip()
        artist = request.form.get("artist", "").strip()
        youtube_link = request.form.get("youtube_link", "").strip()
        youtube_video_id = request.form.get("youtube_video_id", "").strip()
        karaoke_form.update(
            {
                "name": name,
                "song_title": song_title,
                "artist": artist,
                "youtube_link": youtube_link,
                "youtube_video_id": youtube_video_id,
            }
        )

        if not name:
            errors.append("Name is required.")
        if not song_title:
            errors.append("Song title is required.")
        if not artist:
            errors.append("Artist is required.")

        verified_video: dict[str, object] | None = None
        if app.config.get("YOUTUBE_KARAOKE_ENABLED"):
            if youtube_video_id or youtube_link:
                try:
                    verified_video = verify_youtube_video(youtube_video_id or youtube_link)
                    selected_youtube = normalize_karaoke_youtube(verified_video)
                except YouTubeApiError as exc:
                    errors.append(exc.message)
            else:
                errors.append("Choose a YouTube karaoke version before submitting.")

        if not errors:
            def add_signup() -> None:
                require_karaoke_clear_idle()
                if app.config.get("YOUTUBE_KARAOKE_ENABLED") and verified_video:
                    workflow = normalize_karaoke_workflow({}, has_video=True)
                    workflow["video_validation_status"] = "verified"
                    signup = KaraokeSignup(
                        id=uuid4().hex,
                        requester_id=str(session.get("user_id", "") or ""),
                        requested_at=_utc_now_iso(),
                        name=name,
                        song_title=song_title,
                        artist=artist,
                        youtube_link=str(verified_video.get("watch_url", "") or ""),
                        youtube=normalize_karaoke_youtube(verified_video),
                        workflow=workflow,
                    )
                    append_karaoke_history(
                        signup,
                        "submitted",
                        actor_id=str(session.get("user_id", "") or ""),
                        actor_name=name,
                    )
                    append_karaoke_history(signup, "video_verified")
                else:
                    signup = KaraokeSignup(
                        id=uuid4().hex,
                        requester_id=str(session.get("user_id", "") or ""),
                        requested_at=_utc_now_iso(),
                        name=name,
                        song_title=song_title,
                        artist=artist,
                        youtube_link=youtube_link,
                    )
                karaoke_signups.append(signup)

            try:
                explicit_state_mutation(add_signup)
            except (StateMutationBusy, ValueError) as exc:
                errors.append(str(exc))
            else:
                submitted = True
                return redirect(url_for("party_karaoke", success="1"))

    if request.args.get("success") == "1":
        submitted = True

    user_id = str(session.get("user_id", "") or "")
    return render_template(
        "karaoke_signup.html",
        errors=errors,
        submitted=submitted,
        karaoke_signups=public_karaoke_signups(),
        own_karaoke_requests=[
            karaoke_signup_view(signup)
            for signup in karaoke_signups
            if signup.requester_id == user_id
        ],
        youtube_karaoke_enabled=bool(app.config.get("YOUTUBE_KARAOKE_ENABLED")),
        youtube_search_configured=youtube_config().search_configured,
        youtube_search_url=url_for("party_karaoke_search"),
        karaoke_form=karaoke_form,
        selected_youtube=selected_youtube,
        show_admin_link=False,
    )


@app.get("/api/party/karaoke/search")
def party_karaoke_search():
    if not party_day_has_arrived():
        return jsonify({"error": "Karaoke requests are not open yet."}), 403
    song_title = " ".join(request.args.get("song_title", "").split())
    artist = " ".join(request.args.get("artist", "").split())
    query = request.args.get("q", "")
    if song_title or artist:
        if not song_title or not artist:
            return jsonify(
                {
                    "error": "Enter both the song title and artist before searching.",
                    "code": "invalid_query",
                }
            ), 400
        query = f"{song_title} {artist}"
    page_token = request.args.get("page_token", "")
    if len(page_token) > 300:
        return jsonify({"error": "Invalid YouTube result page."}), 400
    try:
        payload = search_youtube_karaoke(
            query,
            page_token=page_token,
            user_id=str(session.get("user_id", "") or request.remote_addr or "guest"),
        )
    except YouTubeApiError as exc:
        if exc.code == "invalid_query":
            status_code = 400
        elif "limit" in exc.code or "budget" in exc.code:
            status_code = 429
        else:
            status_code = 503
        return jsonify({"error": exc.message, "code": exc.code}), status_code
    return jsonify(payload)


@app.post("/party/karaoke/<entry_id>/cancel")
def party_karaoke_cancel(entry_id: str):
    user_id = str(session.get("user_id", "") or "")

    def cancel() -> None:
        require_karaoke_clear_idle()
        signup = find_karaoke_signup(entry_id)
        if not signup or signup.requester_id != user_id:
            raise ValueError("Karaoke request could not be found.")
        if signup.workflow.get("approval_status") != "pending":
            raise ValueError("Only a pending karaoke request can be cancelled.")
        signup.workflow["approval_status"] = "cancelled"
        append_karaoke_history(
            signup,
            "cancelled",
            actor_id=user_id,
            actor_name=str(session.get("username", "") or ""),
        )

    try:
        explicit_state_mutation(cancel)
    except (StateMutationBusy, ValueError) as exc:
        return redirect(url_for("party_karaoke", request_error=str(exc)))
    return redirect(url_for("party_karaoke", request_success="Karaoke request cancelled."))


@app.post("/party/karaoke/<entry_id>/replace")
def party_karaoke_replace(entry_id: str):
    user_id = str(session.get("user_id", "") or "")
    raw_video = request.form.get("youtube_video_id") or request.form.get("youtube_link", "")
    try:
        video = verify_youtube_video(raw_video)

        def replace() -> None:
            require_karaoke_clear_idle()
            signup = find_karaoke_signup(entry_id)
            if not signup or signup.requester_id != user_id:
                raise ValueError("Karaoke request could not be found.")
            if signup.workflow.get("approval_status") != "pending":
                raise ValueError("Only a pending karaoke request can be replaced.")
            signup.youtube = normalize_karaoke_youtube(video)
            signup.youtube_link = str(signup.youtube.get("watch_url", "") or "")
            signup.workflow["video_validation_status"] = "verified"
            signup.workflow["playlist_revision"] = max(
                1, _safe_int(signup.workflow.get("playlist_revision"), 1)
            ) + 1
            append_karaoke_history(
                signup,
                "video_replaced",
                actor_id=user_id,
                actor_name=str(session.get("username", "") or ""),
            )

        explicit_state_mutation(replace)
    except YouTubeApiError as exc:
        return redirect(url_for("party_karaoke", request_error=exc.message))
    except (StateMutationBusy, ValueError) as exc:
        return redirect(url_for("party_karaoke", request_error=str(exc)))
    return redirect(url_for("party_karaoke", request_success="Karaoke video replaced and returned to host review."))


@app.route("/party/costumes/vote", methods=["GET", "POST"])
def party_costume_voting():
    errors: List[str] = []
    submitted = False

    ensure_costume_votes_alignment()

    if not costume_voting_is_visible():
        return redirect(url_for("party_dashboard"))

    user_id = session.get("user_id")
    username = session.get("username")

    if not user_id or user_id not in registered_users:
        return redirect(url_for("party_login", next=url_for("party_costume_voting")))

    user_has_voted = user_id in submitted_costume_votes
    submitted = user_has_voted

    if request.method == "POST":
        if user_has_voted:
            errors.append("Our records show you've already submitted your costume contest scores. Thank you!")
        elif not costume_signups:
            errors.append("There are no costume entries to rate yet.")
        else:
            ratings_by_costume_id: dict[str, int] = {}
            for index, signup in enumerate(costume_signups):
                field_name = f"rating_{signup.id}"
                raw_value = request.form.get(field_name, "").strip()

                if not raw_value:
                    errors.append(f"Please provide a score for {signup.name}.")
                    continue

                try:
                    rating_value = int(raw_value)
                except ValueError:
                    errors.append(f"Scores for {signup.name} must be a whole number between 1 and 10.")
                    continue

                if not 1 <= rating_value <= 10:
                    errors.append(f"Scores for {signup.name} must be between 1 and 10.")
                    continue

                ratings_by_costume_id[signup.id] = rating_value

            if not errors:
                costume_ballots[user_id] = ratings_by_costume_id
                submitted_costume_votes.add(user_id)
                broadcast_display_update()

                return redirect(url_for("party_costume_voting", success="1"))

    if request.args.get("success") == "1":
        submitted = True

    return render_template(
        "costume_voting.html",
        costume_signups=costume_signups,
        errors=errors,
        submitted=submitted,
        user_has_voted=user_has_voted,
        username=username,
        show_admin_link=False,
    )


if __name__ == "__main__":
    # Run on port 80 so the app is available from any browser.
    app.run(host="0.0.0.0", port=80, debug=True)
