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
from party_games import (
    BAD_ADVICE_GAME_KEY,
    DEFAULT_GAMES_STATE,
    FILL_BLANK_GAME_KEY,
    GAME_CATALOG,
    GAME_KEY_BY_SLUG,
    GAME_PROMPT_MAX_LENGTH,
    GAME_RESPONSE_MAX_LENGTH,
    GAME_STATEMENT_MAX_LENGTH,
    MMF_ACTIONS,
    MMF_ROUND_COUNT,
    MURDER_MARRY_FUCK_GAME_KEY,
    PROMPT_GAME_KEYS,
    TWO_TRUTHS_GAME_KEY,
    WRONG_ANSWERS_GAME_KEY,
    calculate_mmf_results,
    calculate_prompt_results,
    calculate_two_truths_results,
    build_simulated_game_state,
    empty_mmf_game_state,
    empty_prompt_game_state,
    empty_two_truths_game_state,
    finalize_prompt_round,
    game_by_slug,
    game_winners,
    generate_game_alias,
    mmf_statistics,
    normalize_games_state,
    normalize_guess_name,
    normalize_prompt,
    normalize_response,
    normalize_statement,
    participant_public_name,
    participant_statements,
    prompt_game_statistics,
    prompt_round_for_game,
    two_truths_statistics,
)
from recognition import (
    ACHIEVEMENT_CATALOG,
    CREDIT_KINDS,
    achievement_views,
    credit_exists,
    event_id_for_year,
    new_credit,
    normalize_event_editions,
    normalize_recognition_credits,
    normalize_result_archives,
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


STATE_SCHEMA_VERSION = 17
KARAOKE_MAX_SINGERS = 4
KARAOKE_SINGER_NAME_MAX_LENGTH = 100
KARAOKE_CUSTOM_SINGER_VALUE = "__custom__"
KARAOKE_COMPLETION_ACK_LIMIT = 50
KARAOKE_COMPLETION_ACK_USER_LIMIT = 2_000


@dataclass
class CostumeSignup:
    name: str
    costume: str
    contact: str = ""
    id: str = ""
    account_id: str = ""


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
    singers: list[dict[str, str]] = field(default_factory=list)

    @property
    def singer_names(self) -> list[str]:
        return karaoke_singer_names(self)

    @property
    def singer_label(self) -> str:
        return karaoke_singer_label(self)


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
    "sync_priority_queue",
    "reset",
}
DJ_PRIORITY_STATUSES = {"none", "pending", "playing", "served"}
DEFAULT_DJ_STATE: dict[str, object] = {
    "command_revision": 0,
    "priority_revision": 0,
    "priority_sync_pending": False,
    "priority_sync_attempted_revision": 0,
    "priority_sync_error": "",
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
        "queue_order": [],
        "current_queue_index": -1,
        "queue_revision": 0,
        "priority_revision": 0,
        "playback_position_seconds": 0,
        "last_seen_at": "",
        "last_error": "",
    },
    "desired": {
        "playback_status": "stopped",
        "song_id": "",
        "queue_order": [],
        "base_queue_order": [],
        "shuffle_enabled": False,
    },
}

DEFAULT_DRINK_ESTIMATE_SECONDS = 8 * 60
DRINK_READY_OVERRIDE_SECONDS = 10
DISPLAY_NOTICE_QUEUE_LIMIT = 12
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
DISPLAY_SOURCE_KEYS = ("portal", "custom", "costume", "karaoke", "games", "bar", "updates")
DISPLAY_SOURCE_LABELS = {
    "portal": "Portal and WiFi",
    "custom": "Custom cards",
    "costume": "Costume contest",
    "karaoke": "Karaoke",
    "games": "Party games",
    "bar": "Drink ordering",
    "updates": "Live updates",
}
DISPLAY_VISIBILITY_MODES = {"auto", "always", "hidden"}
DEFAULT_DISPLAY_CONFIG: dict[str, object] = {
    "source_order": list(DISPLAY_SOURCE_KEYS),
    "source_enabled": {source: True for source in DISPLAY_SOURCE_KEYS},
    "center_interval_seconds": 8,
    "game_interval_seconds": 10,
    "game_mode": "auto",
    "pinned_game_key": "",
    "bar_mode": "auto",
    "music_mode": "auto",
    "max_bar_orders": 4,
    "notice_duration_seconds": DRINK_READY_OVERRIDE_SECONDS,
    "density": "standard",
    "game_result_card_enabled": {},
}
DEFAULT_DISPLAY_RUNTIME: dict[str, object] = {
    "center_index": 0,
    "center_paused": False,
    "pinned_card_id": "",
    "center_revision": 0,
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
    "display": {"label": "Display", "description": "Live TV layout, cards, regions, and run-of-show controls."},
    "program": {"label": "Program", "description": "Costume contest controls, voting, and results."},
    "games": {"label": "Games", "description": "Enrollment, live play, scoring, and game results."},
    "karaoke": {"label": "Karaoke", "description": "YouTube requests, playlist workflow, and stage controls."},
    "dj": {"label": "DJ", "description": "Playlist, live-display receiver, and verified music controls."},
    "bar": {"label": "Bar", "description": "Drink operations and bartender tipping."},
    "menu": {"label": "Menu", "description": "Food and drink availability."},
    "accounts": {"label": "Accounts", "description": "Party accounts and bartender access."},
    "recognition": {"label": "Recognition", "description": "Attendance, achievements, and official winner history."},
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
karaoke_completion_acknowledgements: dict[str, dict[str, str]] = {}
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
live_display_notice_queue: list[dict[str, object]] = []
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
display_config: dict[str, object] = copy.deepcopy(DEFAULT_DISPLAY_CONFIG)
display_runtime: dict[str, object] = copy.deepcopy(DEFAULT_DISPLAY_RUNTIME)
display_custom_cards: list[dict[str, object]] = []
bartender_tip_settings: dict[str, object] = copy.deepcopy(DEFAULT_BARTENDER_TIP_SETTINGS)
games_state: dict[str, object] = copy.deepcopy(DEFAULT_GAMES_STATE)
event_editions: dict[str, dict[str, str]] = normalize_event_editions(
    {},
    current_year=str(app.config["PARTY_YEAR"]),
    current_title=str(app.config["PARTY_TITLE"]),
    current_date=str(app.config["PARTY_DATE_LABEL"]),
)
result_archives: list[dict[str, object]] = []
recognition_credits: list[dict[str, object]] = []
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
    "party_game_opt_in",
    "party_game_submission",
    "party_game_guess",
    "party_game_join",
    "party_mmf_answers",
    "party_prompt_response",
    "party_prompt_vote",
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
    "party_karaoke_data",
    "party_karaoke_search",
    "party_karaoke_cancel",
    "party_karaoke_replace",
    "party_games",
    "party_results",
    "party_games_data",
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
    "export_games",
    "export_recognition",
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
    "party_karaoke_data",
    "party_karaoke_search",
    "party_karaoke_cancel",
    "party_karaoke_replace",
    "party_karaoke_dismiss_completion",
    "party_costume_voting",
    "party_jukebox",
    "party_jukebox_data",
    "party_jukebox_catalog_search",
    "party_jukebox_request",
    "party_games",
    "party_results",
    "party_games_data",
    "party_game_opt_in",
    "party_game_submission",
    "party_game_guess",
    "party_game_join",
    "party_mmf_answers",
    "party_prompt_response",
    "party_prompt_vote",
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


def normalize_karaoke_singers(
    raw_singers: object,
    legacy_name: object = "",
) -> list[dict[str, str]]:
    source = raw_singers if isinstance(raw_singers, list) else []
    singers: list[dict[str, str]] = []
    seen_account_ids: set[str] = set()
    seen_names: set[str] = set()

    for raw_singer in source[:KARAOKE_MAX_SINGERS]:
        if not isinstance(raw_singer, dict):
            continue
        account_id = str(raw_singer.get("account_id", "") or "").strip()[:120]
        name = " ".join(str(raw_singer.get("name", "") or "").split())[
            :KARAOKE_SINGER_NAME_MAX_LENGTH
        ]
        if not name:
            continue
        normalized_name = name.casefold()
        if (account_id and account_id in seen_account_ids) or normalized_name in seen_names:
            continue
        singers.append({"account_id": account_id, "name": name})
        if account_id:
            seen_account_ids.add(account_id)
        seen_names.add(normalized_name)

    if not singers:
        name = " ".join(str(legacy_name or "").split())[:KARAOKE_SINGER_NAME_MAX_LENGTH]
        if name:
            singers.append({"account_id": "", "name": name})
    return singers


def karaoke_singer_names(signup_or_singers: KaraokeSignup | object) -> list[str]:
    if isinstance(signup_or_singers, KaraokeSignup):
        singers = normalize_karaoke_singers(signup_or_singers.singers, signup_or_singers.name)
    else:
        singers = normalize_karaoke_singers(signup_or_singers)
    return [str(singer["name"]) for singer in singers]


def format_karaoke_singer_names(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    return f"{', '.join(names[:-1])} & {names[-1]}"


def karaoke_singer_label(signup_or_singers: KaraokeSignup | object) -> str:
    return format_karaoke_singer_names(karaoke_singer_names(signup_or_singers))


def karaoke_attendee_options() -> list[dict[str, str]]:
    attendees: dict[str, str] = {
        str(account.get("id", "") or "").strip(): " ".join(
            str(account.get("username", "") or "").split()
        )[:KARAOKE_SINGER_NAME_MAX_LENGTH]
        for account in user_accounts.values()
        if str(account.get("id", "") or "").strip()
        and str(account.get("username", "") or "").strip()
    }
    for account_id, name in registered_users.items():
        clean_id = str(account_id or "").strip()
        clean_name = " ".join(str(name or "").split())[:KARAOKE_SINGER_NAME_MAX_LENGTH]
        if clean_id and clean_name:
            attendees.setdefault(clean_id, clean_name)
    return [
        {"account_id": account_id, "name": name}
        for account_id, name in sorted(
            attendees.items(),
            key=lambda item: (item[1].casefold(), item[0]),
        )
    ]


def karaoke_singer_form_rows(
    singers: object = None,
    *,
    default_account_id: str = "",
    default_name: str = "",
) -> list[dict[str, str]]:
    normalized = normalize_karaoke_singers(singers)
    if not normalized and default_name:
        normalized = [
            {
                "account_id": default_account_id,
                "name": " ".join(default_name.split())[:KARAOKE_SINGER_NAME_MAX_LENGTH],
            }
        ]
    rows = []
    for singer in normalized:
        account_id = str(singer.get("account_id", "") or "")
        rows.append(
            {
                "selection": account_id or KARAOKE_CUSTOM_SINGER_VALUE,
                "custom_name": "" if account_id else str(singer.get("name", "") or ""),
                "name": str(singer.get("name", "") or ""),
            }
        )
    return rows or [{"selection": "", "custom_name": "", "name": ""}]


def parse_karaoke_singers_from_form() -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[str],
]:
    selections = [str(value or "").strip() for value in request.form.getlist("singer_account_id")]
    custom_names = [
        " ".join(str(value or "").split())
        for value in request.form.getlist("singer_custom_name")
    ]

    # Preserve compatibility with the original single-name form and older clients.
    if not selections and not custom_names:
        legacy_name = " ".join(request.form.get("name", "").split())
        if legacy_name:
            selections = [KARAOKE_CUSTOM_SINGER_VALUE]
            custom_names = [legacy_name]

    row_count = max(len(selections), len(custom_names))
    selections.extend([""] * (row_count - len(selections)))
    custom_names.extend([""] * (row_count - len(custom_names)))
    rows = [
        {
            "selection": selections[index],
            "custom_name": custom_names[index],
            "name": "",
        }
        for index in range(row_count)
    ]

    errors: list[str] = []
    if row_count == 0:
        errors.append("Choose at least one singer.")
        return [], [{"selection": "", "custom_name": "", "name": ""}], errors
    if row_count > KARAOKE_MAX_SINGERS:
        errors.append(f"A karaoke request can include at most {KARAOKE_MAX_SINGERS} singers.")

    attendees = {
        option["account_id"]: option["name"]
        for option in karaoke_attendee_options()
    }
    singers: list[dict[str, str]] = []
    seen_account_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, row in enumerate(rows[:KARAOKE_MAX_SINGERS], start=1):
        selection = row["selection"]
        if selection == KARAOKE_CUSTOM_SINGER_VALUE:
            name = row["custom_name"]
            account_id = ""
            if not name:
                errors.append(f"Enter a name for singer {index}.")
                continue
        elif selection:
            name = attendees.get(selection, "")
            account_id = selection
            if not name:
                errors.append(f"Singer {index} is not a registered attendee. Choose another singer.")
                continue
        else:
            errors.append(f"Choose singer {index} or select Someone not listed.")
            continue

        if len(name) > KARAOKE_SINGER_NAME_MAX_LENGTH:
            errors.append(
                f"Singer {index}'s name must be {KARAOKE_SINGER_NAME_MAX_LENGTH} characters or fewer."
            )
            continue
        normalized_name = name.casefold()
        if account_id and account_id in seen_account_ids:
            errors.append(f"Singer {index} is already included in this request.")
            continue
        if normalized_name in seen_names:
            errors.append(f"Singer {index}'s name is already included in this request.")
            continue
        singers.append({"account_id": account_id, "name": name})
        row["name"] = name
        if account_id:
            seen_account_ids.add(account_id)
        seen_names.add(normalized_name)

    return singers, rows, errors


def ensure_signup_ids() -> None:
    for signup in costume_signups:
        if not signup.id:
            signup.id = uuid4().hex

    for signup in karaoke_signups:
        if not signup.id:
            signup.id = uuid4().hex
        signup.singers = normalize_karaoke_singers(signup.singers, signup.name)
        signup.name = karaoke_singer_label(signup)
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
        "karaoke_completion_acknowledgements": {},
        "roles": ["regular"],
        "password_hash": generate_password_hash(password),
        "created_at": _utc_now_iso(),
    }


def find_user_account_key_by_id(account_id: str) -> str | None:
    for normalized_username, account in user_accounts.items():
        if str(account.get("id", "")) == account_id:
            return normalized_username
    return None


def normalize_karaoke_completion_acknowledgements(raw_value: object) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        return {}
    acknowledgements: dict[str, str] = {}
    for raw_entry_id, raw_completed_at in list(raw_value.items())[-KARAOKE_COMPLETION_ACK_LIMIT:]:
        entry_id = str(raw_entry_id or "").strip()[:120]
        completed_at = str(raw_completed_at or "").strip()[:180]
        if entry_id and completed_at:
            acknowledgements[entry_id] = completed_at
    return acknowledgements


def normalize_karaoke_completion_acknowledgement_ledger(
    raw_value: object,
) -> dict[str, dict[str, str]]:
    if not isinstance(raw_value, dict):
        return {}
    ledger: dict[str, dict[str, str]] = {}
    for raw_user_id, raw_acknowledgements in list(raw_value.items())[
        -KARAOKE_COMPLETION_ACK_USER_LIMIT:
    ]:
        user_id = str(raw_user_id or "").strip()[:120]
        acknowledgements = normalize_karaoke_completion_acknowledgements(
            raw_acknowledgements
        )
        if user_id and acknowledgements:
            ledger[user_id] = acknowledgements
    return ledger


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


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def normalize_display_config(raw_config: object) -> dict[str, object]:
    normalized = copy.deepcopy(DEFAULT_DISPLAY_CONFIG)
    if not isinstance(raw_config, dict):
        return normalized

    raw_order = raw_config.get("source_order", [])
    order = []
    if isinstance(raw_order, list):
        for source in raw_order:
            source_key = str(source)
            if source_key in DISPLAY_SOURCE_KEYS and source_key not in order:
                order.append(source_key)
    normalized["source_order"] = order + [source for source in DISPLAY_SOURCE_KEYS if source not in order]

    raw_enabled = raw_config.get("source_enabled", {})
    if isinstance(raw_enabled, dict):
        normalized["source_enabled"] = {
            source: bool(raw_enabled.get(source, True)) for source in DISPLAY_SOURCE_KEYS
        }

    normalized["center_interval_seconds"] = _bounded_int(
        raw_config.get("center_interval_seconds"), 8, 4, 30
    )
    normalized["game_interval_seconds"] = _bounded_int(
        raw_config.get("game_interval_seconds"), 10, 5, 30
    )
    normalized["max_bar_orders"] = _bounded_int(raw_config.get("max_bar_orders"), 4, 1, 8)
    normalized["notice_duration_seconds"] = _bounded_int(
        raw_config.get("notice_duration_seconds"), DRINK_READY_OVERRIDE_SECONDS, 5, 30
    )

    for key in ("game_mode", "bar_mode", "music_mode"):
        value = str(raw_config.get(key, normalized[key]) or "auto")
        normalized[key] = value if value in DISPLAY_VISIBILITY_MODES else "auto"

    pinned_game_key = str(raw_config.get("pinned_game_key", "") or "")
    normalized["pinned_game_key"] = pinned_game_key if pinned_game_key in GAME_CATALOG else ""
    raw_game_card_enabled = raw_config.get("game_result_card_enabled", {})
    if isinstance(raw_game_card_enabled, dict):
        valid_suffixes = {"winner", "scores"}
        normalized["game_result_card_enabled"] = {
            str(card_id)[:80]: bool(enabled)
            for card_id, enabled in raw_game_card_enabled.items()
            if str(card_id).startswith("games:")
            and str(card_id).rsplit("-", 1)[-1] in valid_suffixes
        }
    density = str(raw_config.get("density", "standard") or "standard")
    normalized["density"] = density if density in {"compact", "standard", "large"} else "standard"
    return normalized


def normalize_display_runtime(raw_runtime: object) -> dict[str, object]:
    normalized = copy.deepcopy(DEFAULT_DISPLAY_RUNTIME)
    if not isinstance(raw_runtime, dict):
        return normalized
    normalized["center_index"] = max(0, _bounded_int(raw_runtime.get("center_index"), 0, 0, 100000))
    normalized["center_paused"] = bool(raw_runtime.get("center_paused", False))
    normalized["pinned_card_id"] = str(raw_runtime.get("pinned_card_id", "") or "")[:80]
    normalized["center_revision"] = max(0, _bounded_int(raw_runtime.get("center_revision"), 0, 0, 1000000000))
    return normalized


def normalize_display_custom_card(raw_card: object) -> dict[str, object] | None:
    if not isinstance(raw_card, dict):
        return None
    category = str(raw_card.get("category", "Announcement") or "Announcement").strip()[:80]
    primary = str(raw_card.get("primary", "") or "").strip()[:180]
    if not primary:
        return None
    starts_at = str(raw_card.get("starts_at", "") or "").strip()
    ends_at = str(raw_card.get("ends_at", "") or "").strip()
    if starts_at and not parse_utc_iso(starts_at):
        starts_at = ""
    if ends_at and not parse_utc_iso(ends_at):
        ends_at = ""
    return {
        "id": str(raw_card.get("id", "") or uuid4().hex),
        "category": category,
        "primary": primary,
        "secondary": str(raw_card.get("secondary", "") or "").strip()[:500],
        "tertiary": str(raw_card.get("tertiary", "") or "").strip()[:300],
        "image_url": safe_image_url(str(raw_card.get("image_url", "") or "")),
        "link": safe_display_link(str(raw_card.get("link", "") or "")),
        "link_label": str(raw_card.get("link_label", "") or "").strip()[:80],
        "enabled": bool(raw_card.get("enabled", True)),
        "duration_seconds": _bounded_int(raw_card.get("duration_seconds"), 8, 4, 30),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "created_at": str(raw_card.get("created_at", "") or _utc_now_iso()),
    }


def safe_display_link(raw_url: str) -> str:
    link = raw_url.strip()
    if not link or len(link) > 500:
        return ""
    parsed = urlparse(link)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return link
    if link.startswith("/") and not link.startswith("//"):
        return link
    return ""


def display_custom_card_is_active(card: dict[str, object], now: datetime | None = None) -> bool:
    if not card.get("enabled"):
        return False
    current = now or datetime.now(timezone.utc)
    starts_at = parse_utc_iso(card.get("starts_at"))
    ends_at = parse_utc_iso(card.get("ends_at"))
    return (not starts_at or starts_at <= current) and (not ends_at or ends_at > current)


def normalize_display_form_datetime(raw_value: object) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        party_tz = parse_party_start().tzinfo or timezone(timedelta(hours=-6))
        parsed = parsed.replace(tzinfo=party_tz)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def display_form_datetime_value(raw_value: object) -> str:
    parsed = parse_utc_iso(raw_value)
    if not parsed:
        return ""
    party_tz = parse_party_start().tzinfo or timezone(timedelta(hours=-6))
    return parsed.astimezone(party_tz).strftime("%Y-%m-%dT%H:%M")


def build_drink_ready_override(order: dict[str, object]) -> dict[str, object]:
    attendee_name = str(order.get("username", "") or "Guest")
    item_name = str(order.get("item_name", "") or "your drink")
    duration_seconds = _bounded_int(
        display_config.get("notice_duration_seconds"), DRINK_READY_OVERRIDE_SECONDS, 5, 30
    )
    return {
        "id": uuid4().hex,
        "type": "drink_ready",
        "title": "Drink Ready",
        "highlight": attendee_name,
        "message": f"Your {item_name} is ready at the bar.",
        "image_url": str(order.get("item_image_url", "") or ""),
        "details": [
            item_name,
            "Pick it up while the spirits are still lively.",
        ],
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=duration_seconds))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def enqueue_display_notice(notice: dict[str, object]) -> None:
    global live_display_notice_override
    if not live_display_notice_override:
        live_display_notice_override = copy.deepcopy(notice)
        return
    queued_notice = copy.deepcopy(notice)
    queued_notice["expires_at"] = ""
    live_display_notice_queue.append(queued_notice)
    del live_display_notice_queue[:-DISPLAY_NOTICE_QUEUE_LIMIT]


def activate_next_display_notice() -> None:
    global live_display_notice_override
    if not live_display_notice_queue:
        live_display_notice_override = None
        return
    next_notice = live_display_notice_queue.pop(0)
    duration_seconds = _bounded_int(
        display_config.get("notice_duration_seconds"), DRINK_READY_OVERRIDE_SECONDS, 5, 30
    )
    next_notice["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    ).isoformat().replace("+00:00", "Z")
    live_display_notice_override = next_notice


def cleanup_expired_display_notices() -> bool:
    global live_display_notice_override
    if not live_display_notice_override:
        return False
    expires_at = parse_utc_iso(live_display_notice_override.get("expires_at"))
    if expires_at and expires_at <= datetime.now(timezone.utc):
        activate_next_display_notice()
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

    source = str(raw_song.get("source", "admin") or "admin").strip()
    if source not in {"admin", "attendee_request", "admin_priority"}:
        source = "admin"
    priority_status = str(raw_song.get("priority_status", "none") or "none").strip()
    if priority_status not in DJ_PRIORITY_STATUSES:
        priority_status = "none"

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
        "source": source,
        "request_id": str(raw_song.get("request_id", "") or "").strip()[:120],
        "requester_name": str(raw_song.get("requester_name", "") or "").strip()[:80],
        "requested_at": str(raw_song.get("requested_at", "") or "").strip(),
        "approved_at": str(raw_song.get("approved_at", "") or "").strip(),
        "priority_status": priority_status,
        "served_at": str(raw_song.get("served_at", "") or "").strip(),
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


def public_dj_song(song: dict[str, object]) -> dict[str, object]:
    return {
        key: copy.deepcopy(song.get(key))
        for key in (
            "id",
            "apple_music_id",
            "title",
            "artist",
            "album",
            "artwork_url",
            "duration_ms",
            "explicit",
            "enabled",
        )
    }


def attendee_jukebox_state(user_id: str) -> dict[str, object]:
    receiver = dj_state.get("receiver", {})
    current_song = find_dj_song(str(receiver.get("current_song_id", "") if isinstance(receiver, dict) else ""))
    return {
        "now_playing": public_dj_song(current_song) if current_song else None,
        "playback_status": str(receiver.get("playback_status", "stopped") if isinstance(receiver, dict) else "stopped"),
        "playlist": [public_dj_song(song) for song in dj_playlist if bool(song.get("enabled", True))],
        "pending_requests": copy.deepcopy(user_dj_song_requests(user_id)),
        "request_limit": MAX_DJ_SONG_REQUESTS_PER_ATTENDEE,
        "update_version": display_update_version,
    }


def find_dj_song(song_id: str) -> dict[str, object] | None:
    return next((song for song in dj_playlist if str(song.get("id", "")) == song_id), None)


def find_dj_song_by_apple_music_id(apple_music_id: str) -> dict[str, object] | None:
    return next(
        (
            song
            for song in dj_playlist
            if str(song.get("apple_music_id", "")) == str(apple_music_id or "")
        ),
        None,
    )


def enabled_dj_song_ids() -> list[str]:
    return [str(song.get("id", "")) for song in dj_playlist if bool(song.get("enabled", True))]


def pending_dj_priority_songs() -> list[dict[str, object]]:
    pending = [
        song
        for song in dj_playlist
        if bool(song.get("enabled", True)) and song.get("priority_status") == "pending"
    ]
    return sorted(
        pending,
        key=lambda song: (
            str(song.get("requested_at", "") or song.get("approved_at", "") or song.get("created_at", "")),
            str(song.get("approved_at", "") or ""),
            str(song.get("id", "") or ""),
        ),
    )


def build_dj_queue_plan(action: str, song_id: str = "") -> dict[str, object] | None:
    """Build one priority-aware queue plan for every explicit start action."""
    enabled_ids = enabled_dj_song_ids()
    if not enabled_ids:
        return None

    priority_ids = [str(song.get("id", "")) for song in pending_dj_priority_songs()]
    regular_ids = [candidate_id for candidate_id in enabled_ids if candidate_id not in priority_ids]

    if action == "shuffle_playlist":
        random.SystemRandom().shuffle(regular_ids)
        queue_order = [*priority_ids, *regular_ids]
    elif action == "play_playlist":
        queue_order = [*priority_ids, *regular_ids]
    elif action == "play_song":
        selected = find_dj_song(song_id)
        if not selected or not bool(selected.get("enabled", True)):
            return None
        queue_order = [
            song_id,
            *[candidate_id for candidate_id in priority_ids if candidate_id != song_id],
            *[candidate_id for candidate_id in regular_ids if candidate_id != song_id],
        ]
        regular_ids = [candidate_id for candidate_id in regular_ids if candidate_id != song_id]
    else:
        return None

    if not queue_order:
        return None
    return {
        "song_id": str(queue_order[0]),
        "queue_order": queue_order,
        "base_queue_order": regular_ids,
    }


def mark_dj_priority_sync_needed() -> int:
    revision = int(dj_state.get("priority_revision", 0) or 0) + 1
    dj_state["priority_revision"] = revision
    dj_state["priority_sync_pending"] = True
    dj_state["priority_sync_error"] = ""
    return revision


def update_dj_priority_playback_status(current_song_id: str) -> bool:
    """Move requested songs through pending -> playing -> served from receiver truth."""
    changed = False
    now = _utc_now_iso()
    for song in dj_playlist:
        song_id = str(song.get("id", "") or "")
        status = str(song.get("priority_status", "none") or "none")
        if status == "playing" and song_id != current_song_id:
            song["priority_status"] = "served"
            song["served_at"] = now
            changed = True
        if current_song_id and song_id == current_song_id and status == "pending":
            song["priority_status"] = "playing"
            changed = True
    return changed


def build_active_dj_queue_order() -> list[str]:
    """Preserve the current track and rebuild only MusicKit's remaining queue."""
    receiver = dj_state.get("receiver", {})
    desired = dj_state.get("desired", {})
    if not isinstance(receiver, dict) or not isinstance(desired, dict):
        return []

    current_song_id = str(receiver.get("current_song_id", "") or "")
    current_song = find_dj_song(current_song_id)
    if not current_song or not bool(current_song.get("enabled", True)):
        return []

    enabled_ids = enabled_dj_song_ids()
    enabled_set = set(enabled_ids)
    priority_ids = [
        str(song.get("id", ""))
        for song in pending_dj_priority_songs()
        if str(song.get("id", "")) != current_song_id
    ]
    priority_set = set(priority_ids)

    actual_order = receiver.get("queue_order", [])
    if not isinstance(actual_order, list):
        actual_order = []
    try:
        current_index = int(receiver.get("current_queue_index", -1))
    except (TypeError, ValueError):
        current_index = -1
    if not (0 <= current_index < len(actual_order)):
        current_index = next(
            (index for index, candidate_id in enumerate(actual_order) if candidate_id == current_song_id),
            -1,
        )
    played_ids = {
        str(candidate_id)
        for candidate_id in (actual_order[:current_index] if current_index > 0 else [])
        if candidate_id
    }

    base_order = desired.get("base_queue_order", [])
    if not isinstance(base_order, list) or not base_order:
        base_order = desired.get("queue_order", [])
    candidates = [str(candidate_id) for candidate_id in base_order if candidate_id]
    candidates.extend(enabled_ids)
    regular_remainder: list[str] = []
    seen = {current_song_id, *priority_set, *played_ids}
    for candidate_id in candidates:
        if candidate_id in seen or candidate_id not in enabled_set:
            continue
        seen.add(candidate_id)
        regular_remainder.append(candidate_id)

    return [current_song_id, *priority_ids, *regular_remainder]


def dj_receiver_is_online(receiver: dict[str, object] | None = None) -> bool:
    source = receiver if isinstance(receiver, dict) else dj_state.get("receiver", {})
    if not isinstance(source, dict):
        return False
    last_seen = parse_utc_iso(source.get("last_seen_at"))
    return bool(last_seen and last_seen >= datetime.now(timezone.utc) - timedelta(seconds=DJ_RECEIVER_STALE_SECONDS))


def dj_receiver_is_ready(receiver: dict[str, object] | None = None) -> bool:
    source = receiver if isinstance(receiver, dict) else dj_state.get("receiver", {})
    return bool(
        isinstance(source, dict)
        and dj_receiver_is_online(source)
        and source.get("status") == "ready"
        and source.get("authorization_status") == "authorized"
        and source.get("audio_enabled")
    )


def normalize_dj_state(raw_state: object) -> dict[str, object]:
    state = copy.deepcopy(DEFAULT_DJ_STATE)
    if not isinstance(raw_state, dict):
        return state

    try:
        state["command_revision"] = max(0, int(raw_state.get("command_revision", 0) or 0))
    except (TypeError, ValueError):
        state["command_revision"] = 0
    try:
        state["priority_revision"] = max(0, int(raw_state.get("priority_revision", 0) or 0))
    except (TypeError, ValueError):
        state["priority_revision"] = 0
    state["priority_sync_pending"] = bool(raw_state.get("priority_sync_pending", False))
    try:
        state["priority_sync_attempted_revision"] = max(
            0, int(raw_state.get("priority_sync_attempted_revision", 0) or 0)
        )
    except (TypeError, ValueError):
        state["priority_sync_attempted_revision"] = 0
    state["priority_sync_error"] = str(raw_state.get("priority_sync_error", "") or "").strip()[:500]

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
        raw_queue_order = raw_receiver.get("queue_order", [])
        receiver["queue_order"] = (
            [str(song_id or "") for song_id in raw_queue_order[:500]]
            if isinstance(raw_queue_order, list)
            else []
        )
        try:
            receiver["current_queue_index"] = max(-1, int(raw_receiver.get("current_queue_index", -1)))
        except (TypeError, ValueError):
            receiver["current_queue_index"] = -1
        try:
            receiver["queue_revision"] = max(0, int(raw_receiver.get("queue_revision", 0) or 0))
        except (TypeError, ValueError):
            receiver["queue_revision"] = 0
        try:
            receiver["priority_revision"] = max(0, int(raw_receiver.get("priority_revision", 0) or 0))
        except (TypeError, ValueError):
            receiver["priority_revision"] = 0
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
        raw_base_queue_order = raw_desired.get("base_queue_order", [])
        desired["base_queue_order"] = (
            [str(song_id) for song_id in raw_base_queue_order]
            if isinstance(raw_base_queue_order, list)
            else []
        )
        desired["shuffle_enabled"] = bool(raw_desired.get("shuffle_enabled", False))

    for key in ("current_command", "last_command"):
        raw_command = raw_state.get(key)
        if isinstance(raw_command, dict):
            try:
                command_revision = max(0, int(raw_command.get("revision", 0) or 0))
            except (TypeError, ValueError):
                command_revision = 0
            try:
                command_priority_revision = max(
                    0, int(raw_command.get("priority_revision", 0) or 0)
                )
            except (TypeError, ValueError):
                command_priority_revision = 0
            state[key] = {
                "id": str(raw_command.get("id", "") or ""),
                "revision": command_revision,
                "action": str(raw_command.get("action", "") or ""),
                "song_id": str(raw_command.get("song_id", "") or ""),
                "queue_order": [str(song_id) for song_id in raw_command.get("queue_order", [])]
                if isinstance(raw_command.get("queue_order"), list)
                else [],
                "priority_revision": command_priority_revision,
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

    desired = dj_state["desired"]
    queue_order = copy.deepcopy(desired.get("queue_order", []))
    if action in {"play_song", "play_playlist", "shuffle_playlist"}:
        plan = build_dj_queue_plan(action, song_id)
        if not plan:
            return None
        song_id = str(plan["song_id"])
        queue_order = copy.deepcopy(plan["queue_order"])
        desired["base_queue_order"] = copy.deepcopy(plan["base_queue_order"])
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
        "priority_revision": int(dj_state.get("priority_revision", 0) or 0),
        "requested_at": _utc_now_iso(),
        "requested_by": requested_by,
        "status": "pending",
        "acknowledged_at": "",
        "error": "",
    }
    dj_state["current_command"] = command
    dj_state["last_reset"] = None
    if action in {"play_song", "play_playlist", "shuffle_playlist"}:
        dj_state["priority_sync_attempted_revision"] = int(dj_state.get("priority_revision", 0) or 0)
    return command


def maybe_queue_dj_priority_sync_command(requested_by: str = "Priority reconciliation") -> dict[str, object] | None:
    """Queue one non-interrupting remainder replacement when the receiver is ready."""
    if not bool(dj_state.get("priority_sync_pending", False)):
        return None
    if isinstance(dj_state.get("current_command"), dict):
        return None
    priority_revision = int(dj_state.get("priority_revision", 0) or 0)
    attempted_revision = int(dj_state.get("priority_sync_attempted_revision", 0) or 0)
    if attempted_revision >= priority_revision:
        return None
    if not dj_receiver_is_ready():
        return None
    receiver = dj_state.get("receiver", {})
    if not isinstance(receiver, dict) or receiver.get("playback_status") not in {"playing", "paused"}:
        return None

    queue_order = build_active_dj_queue_order()
    if not queue_order:
        return None

    revision = int(dj_state.get("command_revision", 0) or 0) + 1
    command = {
        "id": uuid4().hex,
        "revision": revision,
        "action": "sync_priority_queue",
        "song_id": queue_order[0],
        "queue_order": queue_order,
        "priority_revision": priority_revision,
        "requested_at": _utc_now_iso(),
        "requested_by": requested_by,
        "status": "pending",
        "acknowledged_at": "",
        "error": "",
    }
    dj_state["command_revision"] = revision
    dj_state["current_command"] = command
    dj_state["last_reset"] = None
    dj_state["desired"]["queue_order"] = copy.deepcopy(queue_order)
    dj_state["priority_sync_attempted_revision"] = priority_revision
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
        "priority_revision": int(dj_state.get("priority_revision", 0) or 0),
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
    if "current_song_id" in payload:
        reported_song_id = str(payload.get("current_song_id", "") or "")
        receiver["current_song_id"] = reported_song_id if not reported_song_id or find_dj_song(reported_song_id) else ""
    raw_queue_order = payload.get("queue_order")
    if isinstance(raw_queue_order, list):
        receiver["queue_order"] = [
            song_id if not song_id or find_dj_song(song_id) else ""
            for song_id in (str(candidate or "") for candidate in raw_queue_order[:500])
        ]
    if "current_queue_index" in payload:
        try:
            receiver["current_queue_index"] = max(-1, int(payload.get("current_queue_index", -1)))
        except (TypeError, ValueError):
            receiver["current_queue_index"] = -1
    if "queue_revision" in payload:
        try:
            receiver["queue_revision"] = max(0, int(payload.get("queue_revision", 0) or 0))
        except (TypeError, ValueError):
            receiver["queue_revision"] = 0
    if "priority_revision" in payload:
        try:
            receiver["priority_revision"] = max(0, int(payload.get("priority_revision", 0) or 0))
        except (TypeError, ValueError):
            receiver["priority_revision"] = 0
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

    if "current_song_id" in payload:
        update_dj_priority_playback_status(str(receiver.get("current_song_id", "") or ""))

    current_command = dj_state.get("current_command")
    acknowledged_id = str(payload.get("acknowledged_command_id", "") or "")
    if isinstance(current_command, dict) and acknowledged_id and acknowledged_id == current_command.get("id"):
        succeeded = bool(payload.get("command_succeeded", False))
        if current_command.get("action") == "reset":
            update_dj_priority_playback_status("")
            reset_record = copy.deepcopy(dj_state.get("last_reset") or {})
            reset_record["status"] = "acknowledged" if succeeded else "failed"
            reset_record["acknowledged_at"] = _utc_now_iso()
            reset_record["error"] = "" if succeeded else receiver["last_error"] or "The live display could not complete the DJ reset."
            reset_dj_workflow_state(reset_record)
            return
        current_command["status"] = "succeeded" if succeeded else "failed"
        current_command["acknowledged_at"] = _utc_now_iso()
        current_command["error"] = "" if succeeded else receiver["last_error"] or "The display could not complete the DJ command."
        if succeeded:
            dj_state["desired"]["playback_status"] = receiver["playback_status"]
            if receiver.get("current_song_id"):
                dj_state["desired"]["song_id"] = receiver["current_song_id"]
            command_priority_revision = int(current_command.get("priority_revision", 0) or 0)
            if current_command.get("action") in {
                "play_song",
                "play_playlist",
                "shuffle_playlist",
                "sync_priority_queue",
            } and command_priority_revision:
                receiver["priority_revision"] = command_priority_revision
                if command_priority_revision == int(dj_state.get("priority_revision", 0) or 0):
                    dj_state["priority_sync_pending"] = False
                    dj_state["priority_sync_error"] = ""
        elif current_command.get("action") == "sync_priority_queue":
            dj_state["priority_sync_error"] = current_command["error"]
        dj_state["last_command"] = copy.deepcopy(current_command)
        dj_state["current_command"] = None
        maybe_queue_dj_priority_sync_command()
        return

    maybe_queue_dj_priority_sync_command()


def dj_command_flow() -> list[dict[str, str]]:
    receiver = dj_state.get("receiver", {})
    current_command = dj_state.get("current_command")
    last_command = dj_state.get("last_command")
    last_reset = dj_state.get("last_reset")
    receiver_online = dj_receiver_is_online(receiver if isinstance(receiver, dict) else None)
    receiver_ready = dj_receiver_is_ready(receiver if isinstance(receiver, dict) else None)
    requested_state = "ready" if receiver_ready else "idle"
    requested_detail = "DJ controls are armed and ready for a song." if receiver_ready else "No command waiting."
    command_error = ""
    if isinstance(current_command, dict):
        requested_state = "pending"
        if current_command.get("action") == "reset":
            requested_detail = "DJ reset is waiting for the live display."
        elif current_command.get("action") == "sync_priority_queue":
            requested_detail = "MusicKit is updating the remaining queue without interrupting the current song."
        else:
            requested_detail = "Command saved in Redis."
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
    actual_queue_order = receiver.get("queue_order", []) if isinstance(receiver, dict) else []
    if not isinstance(actual_queue_order, list):
        actual_queue_order = []
    try:
        current_queue_index = int(receiver.get("current_queue_index", -1) if isinstance(receiver, dict) else -1)
    except (TypeError, ValueError):
        current_queue_index = -1
    current_song_id = str(current_song.get("id", "") if current_song else "")
    if not (0 <= current_queue_index < len(actual_queue_order)) and current_song_id:
        current_queue_index = next(
            (index for index, song_id in enumerate(actual_queue_order) if str(song_id) == current_song_id),
            -1,
        )
    next_song = None
    next_queue_index = current_queue_index + 1
    next_queue_item_exists = 0 <= next_queue_index < len(actual_queue_order)
    if next_queue_item_exists:
        next_song = find_dj_song(str(actual_queue_order[next_queue_index] or ""))
    priority_songs = pending_dj_priority_songs()
    priority_song = priority_songs[0] if priority_songs else None
    priority_sync_pending = bool(view.get("priority_sync_pending", False))
    priority_sync_error = str(view.get("priority_sync_error", "") or "")
    current_command = view.get("current_command")
    if isinstance(current_command, dict) and current_command.get("action") == "sync_priority_queue":
        priority_sync_status = "updating"
        priority_sync_message = "Updating MusicKit so the priority request plays next without interrupting the current song."
    elif priority_sync_error:
        priority_sync_status = "failed"
        priority_sync_message = f"Priority queue update failed: {priority_sync_error}"
    elif priority_sync_pending and not current_song:
        priority_sync_status = "waiting_playback"
        priority_sync_message = "The priority lane is saved and will lead the next Play or Shuffle queue."
    elif priority_sync_pending and not dj_receiver_is_ready(receiver if isinstance(receiver, dict) else None):
        priority_sync_status = "waiting_receiver"
        priority_sync_message = "The priority lane is saved and will synchronize when the display receiver is ready."
    elif priority_sync_pending:
        priority_sync_status = "pending"
        priority_sync_message = "The priority lane is waiting for MusicKit confirmation."
    elif priority_song and next_song and priority_song.get("id") == next_song.get("id"):
        priority_sync_status = "confirmed"
        priority_sync_message = f"Confirmed Up Next: {priority_song.get('title', 'priority request')}."
    elif priority_song:
        priority_sync_status = "queued"
        priority_sync_message = "The priority request is saved for the next queue start."
    else:
        priority_sync_status = "idle"
        priority_sync_message = "No priority requests are waiting."

    if next_song:
        next_song_detail = " · ".join(
            value for value in (str(next_song.get("artist", "") or ""), str(next_song.get("album", "") or "")) if value
        )
        next_song_meta = f"Queue position {next_queue_index + 1} of {len(actual_queue_order)}"
    elif next_queue_item_exists:
        next_song_detail = "MusicKit returned a queue item that could not be mapped to the saved playlist."
        next_song_meta = "Unrecognized MusicKit queue item"
    elif not current_song:
        next_song_detail = (
            f"Priority request waiting: {priority_song.get('title')} — {priority_song.get('artist')}."
            if priority_song
            else "Start Play or Shuffle to establish a confirmed MusicKit queue."
        )
        next_song_meta = "No active MusicKit queue"
    elif priority_sync_pending and priority_song:
        next_song_detail = f"Priority queue update pending: {priority_song.get('title')} — {priority_song.get('artist')}."
        next_song_meta = "Waiting for MusicKit confirmation"
    elif current_queue_index >= 0 and current_queue_index == len(actual_queue_order) - 1:
        next_song_detail = "The current song is the final confirmed queue item."
        next_song_meta = "End of the confirmed queue"
    else:
        next_song_detail = "MusicKit has not confirmed another queue item."
        next_song_meta = "No confirmed queue successor"
    desired_song = find_dj_song(str(view.get("desired", {}).get("song_id", ""))) if isinstance(view.get("desired"), dict) else None
    controls_ready = dj_receiver_is_ready(receiver if isinstance(receiver, dict) else None) and not isinstance(current_command, dict)
    if isinstance(current_command, dict) and current_command.get("action") == "sync_priority_queue":
        controls_message = "MusicKit is confirming the priority queue update."
    elif isinstance(current_command, dict):
        controls_message = "Wait for the live display to confirm the pending command."
    elif not bool(receiver.get("online") if isinstance(receiver, dict) else False):
        controls_message = "Open the live display on the playback device to connect the receiver."
    elif str(receiver.get("authorization_status", "") if isinstance(receiver, dict) else "") != "authorized":
        controls_message = "Authorize Apple Music on the live display before using playback controls."
    elif not bool(receiver.get("audio_enabled") if isinstance(receiver, dict) else False):
        controls_message = "Press Enable DJ Audio on the live display before using playback controls."
    else:
        controls_message = "Receiver connected, Apple Music authorized, and audio output ready."
    view["current_song"] = copy.deepcopy(current_song)
    view["next_song"] = copy.deepcopy(next_song)
    view["next_song_detail"] = next_song_detail
    view["next_song_meta"] = next_song_meta
    view["next_queue_item_unrecognized"] = bool(next_queue_item_exists and not next_song)
    view["priority_songs"] = copy.deepcopy(priority_songs)
    view["priority_song"] = copy.deepcopy(priority_song)
    view["priority_sync_status"] = priority_sync_status
    view["priority_sync_message"] = priority_sync_message
    view["desired_song"] = copy.deepcopy(desired_song)
    view["current_queue_position"] = current_queue_index + 1 if current_queue_index >= 0 else 0
    view["next_queue_position"] = next_queue_index + 1 if next_song else 0
    view["actual_queue_size"] = len(actual_queue_order)
    view["controls_ready"] = controls_ready
    view["controls_message"] = controls_message
    view["playlist"] = copy.deepcopy(dj_playlist)
    view["request_count"] = len(dj_song_requests)
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
        "account_id": signup.account_id,
    }


def costume_signup_from_dict(data: dict[str, object]) -> CostumeSignup:
    return CostumeSignup(
        id=str(data.get("id", "") or uuid4().hex),
        name=str(data.get("name", "") or ""),
        costume=str(data.get("costume", "") or ""),
        contact=str(data.get("contact", "") or ""),
        account_id=str(data.get("account_id", "") or ""),
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
    return signup.workflow.get("performance_status", "waiting") == "waiting"


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
            "label": "Called to stage" if performance == "called" else "On stage",
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
        return active_karaoke_signups()
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
        "singer_names": signup.singer_names,
        "singer_label": signup.singer_label,
        "singer_form_rows": karaoke_singer_form_rows(signup.singers),
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


def karaoke_user_is_participant(signup: KaraokeSignup, user_id: str) -> bool:
    if not user_id:
        return False
    if signup.requester_id == user_id:
        return True
    return any(
        str(singer.get("account_id", "") or "") == user_id
        for singer in normalize_karaoke_singers(signup.singers, signup.name)
    )


def karaoke_completion_is_dismissed(signup: KaraokeSignup, user_id: str) -> bool:
    if signup.workflow.get("performance_status") != "completed":
        return False
    completion_id = karaoke_completion_acknowledgement_value(signup)
    if not completion_id or not user_id:
        return False
    acknowledgements = normalize_karaoke_completion_acknowledgements(
        karaoke_completion_acknowledgements.get(user_id, {})
    )
    return acknowledgements.get(signup.id) == completion_id


def karaoke_completion_acknowledgement_value(signup: KaraokeSignup) -> str:
    if signup.workflow.get("performance_status") != "completed":
        return ""
    completed_at = str(signup.workflow.get("completed_at", "") or "")
    if completed_at:
        return completed_at
    for event in reversed(signup.history):
        if event.get("event") == "performance_completed" and event.get("at"):
            return str(event["at"])
    return f"legacy:{signup.id}"


def karaoke_attendee_signup_is_visible(signup: KaraokeSignup, user_id: str) -> bool:
    return (
        karaoke_user_is_participant(signup, user_id)
        and not karaoke_completion_is_dismissed(signup, user_id)
    )


def karaoke_attendee_notification_timestamp(signup: KaraokeSignup) -> float:
    workflow = signup.workflow
    for raw_timestamp in (
        workflow.get("completed_at"),
        workflow.get("started_at"),
        workflow.get("called_at"),
        workflow.get("approved_at"),
        signup.requested_at,
    ):
        timestamp = parse_utc_iso(raw_timestamp)
        if timestamp:
            return timestamp.timestamp()
    return 0.0


def karaoke_attendee_status(signup: KaraokeSignup) -> dict[str, object]:
    workflow = signup.workflow
    approval = str(workflow.get("approval_status", "pending") or "pending")
    playlist = str(workflow.get("playlist_sync_status", "not_started") or "not_started")
    validation = str(workflow.get("video_validation_status", "pending") or "pending")
    performance = str(workflow.get("performance_status", "waiting") or "waiting")
    if not app.config.get("YOUTUBE_KARAOKE_ENABLED"):
        approval = "approved"
        playlist = "synced"
        validation = "verified"
    current_id = str(karaoke_state.get("current_singer_id", "") or "")
    next_id = str(karaoke_state.get("next_singer_id", "") or "")
    stage_mode = str(karaoke_state.get("stage_mode", "standby") or "standby")
    party_started = bool(karaoke_state.get("party_started"))
    queue_position = next(
        (
            index + 1
            for index, entry in enumerate(active_karaoke_signups())
            if entry.id == signup.id
        ),
        None,
    )

    key = "waiting"
    label = "Waiting for karaoke"
    detail = "The host will update this song as the queue moves."
    tone = "neutral"
    priority = 10

    if approval == "cancelled":
        key, label, detail, tone, priority = (
            "cancelled",
            "Request cancelled",
            "This song is no longer in the active karaoke lineup.",
            "muted",
            5,
        )
    elif approval == "rejected":
        key, label, detail, tone, priority = (
            "rejected",
            "Request not approved",
            "Choose another song or ask the host for help.",
            "attention",
            35,
        )
    elif approval == "pending":
        key, label, detail, tone, priority = (
            "awaiting_approval",
            "Awaiting host approval",
            "Your selected karaoke video is waiting for host review.",
            "pending",
            30,
        )
    elif performance == "completed":
        key, label, detail, tone, priority = (
            "completed",
            "Performance complete",
            "Thanks for singing—your performance is marked complete.",
            "success",
            20,
        )
    elif performance == "skipped":
        key, label, detail, tone, priority = (
            "skipped",
            "Song skipped",
            "This song has been removed from the active run of show.",
            "muted",
            15,
        )
    elif performance == "on_stage" or (signup.id == current_id and stage_mode == "on_stage"):
        key, label, detail, tone, priority = (
            "on_stage",
            "You’re on stage",
            "Your karaoke performance is in progress.",
            "live",
            95,
        )
    elif performance == "called" or (signup.id == current_id and stage_mode == "called"):
        key, label, detail, tone, priority = (
            "called",
            "You’ve been called to the stage",
            "Head to the microphone now—the host is ready for you.",
            "urgent",
            100,
        )
    elif validation in {"failed", "unavailable"} or playlist in {
        "failed",
        "out_of_order",
        "removal_pending",
    }:
        key, label, detail, tone, priority = (
            "attention",
            "Host is resolving your song",
            "A video or playlist issue needs host attention before this song is ready.",
            "attention",
            70,
        )
    elif approval == "approved" and playlist != "synced" and app.config.get(
        "YOUTUBE_KARAOKE_ENABLED"
    ):
        key, label, detail, tone, priority = (
            "syncing",
            "Approved—playlist syncing",
            "The host approved this song and is adding it to the event playlist.",
            "pending",
            45,
        )
    elif (
        party_started
        and signup.id == next_id
        and stage_mode in {"called", "on_stage"}
    ):
        current = find_karaoke_signup(current_id)
        current_label = current.singer_label if current else "The current singers"
        key, label, detail, tone, priority = (
            "up_next",
            "You’re up next",
            f"{current_label} {'is' if len(current.singer_names) == 1 else 'are'} up now. Stay close to the microphone."
            if current
            else "Stay close to the microphone and be ready for the host’s call.",
            "urgent",
            90,
        )
    elif karaoke_entry_can_stage(signup):
        position_detail = (
            f"You’re number {queue_position} in the active run of show."
            if queue_position
            else "You’re in the active run of show."
        )
        key, label, detail, tone, priority = (
            "ready",
            "Ready for karaoke",
            position_detail,
            "success",
            55,
        )

    return {
        "key": key,
        "label": label,
        "detail": detail,
        "tone": tone,
        "priority": priority,
        "queue_position": queue_position,
        "is_current": signup.id == current_id,
        "is_up_next": key == "up_next",
        "dismissible": key == "completed",
    }


def karaoke_public_entry_view(signup: KaraokeSignup) -> dict[str, object]:
    status = karaoke_attendee_status(signup)
    public_status_key = status["key"] if status["key"] in {
        "called",
        "on_stage",
        "up_next",
    } else "ready"
    public_status_labels = {
        "called": "Called to stage",
        "on_stage": "Now singing",
        "up_next": "Up next",
        "ready": "Ready",
    }
    return {
        "id": signup.id,
        "singer_label": signup.singer_label,
        "song_title": signup.song_title,
        "artist": signup.artist,
        "queue_position": status["queue_position"],
        "status_key": public_status_key,
        "status_label": public_status_labels[public_status_key],
    }


def karaoke_attendee_entry_view(signup: KaraokeSignup, user_id: str) -> dict[str, object]:
    status = karaoke_attendee_status(signup)
    completion_id = karaoke_completion_acknowledgement_value(signup)
    return {
        "id": signup.id,
        "singer_label": signup.singer_label,
        "song_title": signup.song_title,
        "artist": signup.artist,
        "workflow": {
            key: str(signup.workflow.get(key, "") or "")
            for key in (
                "video_validation_status",
                "approval_status",
                "playlist_sync_status",
                "performance_status",
            )
        },
        "steps": karaoke_workflow_steps(signup),
        "status": status,
        "relationship": "requester" if signup.requester_id == user_id else "singer",
        "can_manage": signup.requester_id == user_id
        and signup.workflow.get("approval_status") == "pending",
        "dismiss_url": f"/api/party/karaoke/entries/{signup.id}/dismiss-completion"
        if status["dismissible"]
        else "",
        "completion_id": completion_id,
    }


def karaoke_attendee_template_entry(
    signup: KaraokeSignup, user_id: str
) -> dict[str, object]:
    entry = karaoke_signup_view(signup)
    attendee_entry = karaoke_attendee_entry_view(signup, user_id)
    entry["attendee_status"] = attendee_entry["status"]
    entry["relationship"] = attendee_entry["relationship"]
    entry["can_manage"] = attendee_entry["can_manage"]
    entry["dismiss_url"] = attendee_entry["dismiss_url"]
    entry["completion_id"] = attendee_entry["completion_id"]
    return entry


def karaoke_attendee_view_state(user_id: str) -> dict[str, object]:
    personal_signups = [
        signup
        for signup in karaoke_signups
        if karaoke_attendee_signup_is_visible(signup, user_id)
    ]
    personal_signups.sort(
        key=lambda signup: (
            -int(karaoke_attendee_status(signup).get("priority", 0) or 0),
            -karaoke_attendee_notification_timestamp(signup),
            int(karaoke_attendee_status(signup).get("queue_position") or 10_000),
        )
    )
    personal_entries = [
        karaoke_attendee_entry_view(signup, user_id) for signup in personal_signups
    ]
    current = find_karaoke_signup(str(karaoke_state.get("current_singer_id", "") or ""))
    next_signup = find_karaoke_signup(str(karaoke_state.get("next_singer_id", "") or ""))
    return {
        "display_update_version": display_update_version,
        "party_started": bool(karaoke_state.get("party_started")),
        "stage_mode": str(karaoke_state.get("stage_mode", "standby") or "standby"),
        "current": karaoke_public_entry_view(current) if current else None,
        "next": karaoke_public_entry_view(next_signup) if next_signup else None,
        "primary": personal_entries[0] if personal_entries else None,
        "personal_entries": personal_entries,
        "lineup": [
            karaoke_public_entry_view(signup)
            for signup in public_karaoke_signups()
        ],
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
        "highlight": signup.singer_label,
        "message": message,
        "image_url": str(signup.youtube.get("thumbnail_url", "") or ""),
        "details": [
            f'"{signup.song_title}"',
            f"by {signup.artist}",
        ],
    }


def call_karaoke_entry(signup: KaraokeSignup, *, actor_name: str = "admin") -> None:
    global live_display_event_override
    if not karaoke_entry_can_stage(signup):
        raise ValueError(
            "This singer is not ready. Resolve video approval and playlist synchronization first."
        )
    previous = find_karaoke_signup(
        str(karaoke_state.get("current_singer_id", "") or "")
    )
    if previous and previous.id != signup.id:
        previous_status = str(previous.workflow.get("performance_status", "waiting"))
        if previous_status == "on_stage":
            raise ValueError("Complete or skip the current singer before calling another.")
        if previous_status == "called":
            previous.workflow["performance_status"] = "waiting"
            previous.workflow["called_at"] = ""
            append_karaoke_history(
                previous,
                "returned_to_queue",
                detail="Another singer was called before this performance started.",
                actor_name=actor_name,
            )
    signup.workflow["performance_status"] = "called"
    signup.workflow["called_at"] = _utc_now_iso()
    signup.workflow["started_at"] = ""
    signup.workflow["completed_at"] = ""
    append_karaoke_history(signup, "called_to_stage", actor_name=actor_name)
    karaoke_state["party_started"] = True
    karaoke_state["current_singer_id"] = signup.id
    karaoke_state["stage_mode"] = "called"
    refresh_karaoke_stage_selection()
    live_display_event_override = build_karaoke_stage_override(signup, "call")


def show_karaoke_entry_card(signup: KaraokeSignup) -> None:
    global live_display_event_override
    performance = str(signup.workflow.get("performance_status", "waiting") or "waiting")
    mode = "on_stage" if performance == "on_stage" else "call"
    live_display_event_override = build_karaoke_stage_override(signup, mode)


def return_active_karaoke_entries_to_queue(*, event: str, detail: str) -> None:
    for signup in karaoke_signups:
        if signup.workflow.get("performance_status") not in {"called", "on_stage"}:
            continue
        signup.workflow["performance_status"] = "waiting"
        signup.workflow["called_at"] = ""
        signup.workflow["started_at"] = ""
        signup.workflow["completed_at"] = ""
        append_karaoke_history(
            signup,
            event,
            detail=detail,
            actor_name="admin",
        )


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
    singers = normalize_karaoke_singers(signup.singers, signup.name)
    singer_label = karaoke_singer_label(singers)
    return {
        "id": signup.id,
        "name": singer_label,
        "singers": copy.deepcopy(singers),
        "singer_names": karaoke_singer_names(singers),
        "singer_label": singer_label,
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
    singers = normalize_karaoke_singers(data.get("singers"), data.get("name"))
    return KaraokeSignup(
        id=str(data.get("id", "") or uuid4().hex),
        name=karaoke_singer_label(singers),
        song_title=str(data.get("song_title", "") or ""),
        artist=str(data.get("artist", "") or ""),
        youtube_link=canonical_watch_url(str(youtube.get("video_id", "") or "")) or youtube_link,
        requester_id=str(data.get("requester_id", "") or ""),
        requested_at=str(data.get("requested_at", "") or ""),
        youtube=youtube,
        workflow=workflow,
        history=normalize_karaoke_history(data.get("history")),
        singers=singers,
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
        "karaoke_completion_acknowledgements": copy.deepcopy(
            karaoke_completion_acknowledgements
        ),
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
        "display_config": copy.deepcopy(display_config),
        "display_runtime": copy.deepcopy(display_runtime),
        "display_custom_cards": copy.deepcopy(display_custom_cards),
        "bartender_tip_settings": copy.deepcopy(bartender_tip_settings),
        "games_state": copy.deepcopy(games_state),
        "event_editions": copy.deepcopy(event_editions),
        "result_archives": copy.deepcopy(result_archives),
        "recognition_credits": copy.deepcopy(recognition_credits),
        "live_display_event_override": copy.deepcopy(live_display_event_override),
        "live_display_notice_override": copy.deepcopy(live_display_notice_override),
        "live_display_notice_queue": copy.deepcopy(live_display_notice_queue),
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
    global user_accounts, karaoke_completion_acknowledgements, costume_ballots, submitted_costume_votes
    global live_display_event_override, live_display_notice_override, live_display_notice_queue
    global landing_page_target, event_experience_mode, party_code_hash, party_code_hint, party_details, display_settings, display_config, display_runtime, display_custom_cards, display_update_version
    global password_reset_tokens, menu_items, drink_orders, dj_playlist, dj_song_requests, dj_state, rsvp_notification_email, bartender_tip_settings, youtube_karaoke, games_state
    global event_editions, result_archives, recognition_credits

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
                    "karaoke_completion_acknowledgements": normalize_karaoke_completion_acknowledgements(
                        raw_account.get("karaoke_completion_acknowledgements", {})
                    ),
                    "roles": normalize_account_roles(raw_account.get("roles", [])),
                    "password_hash": password_hash,
                    "created_at": str(raw_account.get("created_at", "") or ""),
                }
    else:
        user_accounts = {}

    karaoke_completion_acknowledgements = (
        normalize_karaoke_completion_acknowledgement_ledger(
            data.get("karaoke_completion_acknowledgements", {})
        )
    )
    for account in user_accounts.values():
        account_id = str(account.get("id", "") or "").strip()
        legacy_acknowledgements = normalize_karaoke_completion_acknowledgements(
            account.get("karaoke_completion_acknowledgements", {})
        )
        if not account_id or not legacy_acknowledgements:
            continue
        karaoke_completion_acknowledgements[account_id] = (
            normalize_karaoke_completion_acknowledgements(
                {
                    **legacy_acknowledgements,
                    **karaoke_completion_acknowledgements.get(account_id, {}),
                }
            )
        )

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
    games_state = normalize_games_state(data.get("games_state", {}))
    event_editions = normalize_event_editions(
        data.get("event_editions", {}),
        current_year=str(app.config["PARTY_YEAR"]),
        current_title=str(app.config["PARTY_TITLE"]),
        current_date=str(app.config["PARTY_DATE_LABEL"]),
    )
    result_archives = normalize_result_archives(data.get("result_archives", []))
    recognition_credits = normalize_recognition_credits(data.get("recognition_credits", []))
    account_names_by_id = {
        str(account.get("id", "")): str(account.get("username", "") or "")
        for account in user_accounts.values()
        if isinstance(account, dict) and account.get("id")
    }
    for game_key in (MURDER_MARRY_FUCK_GAME_KEY, *PROMPT_GAME_KEYS):
        for user_id, participant in games_state[game_key].get("participants", {}).items():
            if isinstance(participant, dict) and not participant.get("display_name"):
                participant["display_name"] = str(
                    registered_users.get(user_id, "") or account_names_by_id.get(user_id, "")
                )[:80]

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

    display_config = normalize_display_config(data.get("display_config", {}))
    display_runtime = normalize_display_runtime(data.get("display_runtime", {}))
    display_custom_cards = []
    raw_custom_cards = data.get("display_custom_cards", [])
    if isinstance(raw_custom_cards, list):
        for raw_card in raw_custom_cards:
            normalized_card = normalize_display_custom_card(raw_card)
            if normalized_card:
                display_custom_cards.append(normalized_card)

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
    live_display_notice_queue = []
    raw_notice_queue = data.get("live_display_notice_queue", [])
    if isinstance(raw_notice_queue, list):
        for raw_notice in raw_notice_queue[-DISPLAY_NOTICE_QUEUE_LIMIT:]:
            if isinstance(raw_notice, dict) and str(raw_notice.get("type", "")) in display_notice_types():
                live_display_notice_queue.append(copy.deepcopy(raw_notice))
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
        "stage_mode": str(karaoke_state.get("stage_mode", "standby") or "standby"),
        "current_singer_id": karaoke_state.get("current_singer_id"),
        "next_singer_id": karaoke_state.get("next_singer_id"),
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


def two_truths_game() -> dict[str, object]:
    game = games_state.get(TWO_TRUTHS_GAME_KEY)
    if not isinstance(game, dict):
        games_state[TWO_TRUTHS_GAME_KEY] = empty_two_truths_game_state()
    return games_state[TWO_TRUTHS_GAME_KEY]


def two_truths_participant_by_submission(submission_id: str) -> dict[str, object] | None:
    for participant in two_truths_game().get("participants", {}).values():
        if participant.get("submission_id") == submission_id:
            return participant
    return None


def two_truths_winners(game: dict[str, object] | None = None) -> list[dict[str, object]]:
    current_game = game or two_truths_game()
    results = current_game.get("results", {})
    winner_ids = set(results.get("winner_ids", [])) if isinstance(results, dict) else set()
    scores = results.get("scores", []) if isinstance(results, dict) else []
    return [entry for entry in scores if entry.get("user_id") in winner_ids]


def build_two_truths_scoreboard_card(game: dict[str, object] | None = None) -> dict[str, object] | None:
    current_game = game or two_truths_game()
    results = current_game.get("results", {})
    scores = results.get("scores", []) if isinstance(results, dict) else []
    if not scores:
        return None
    rows = [
        {
            "rank": index + 1,
            "name": entry.get("name", "Guest"),
            "detail": f"{entry.get('correct', 0)} correct",
            "value_label": f"{entry.get('correct', 0)} pts",
            "meta_label": f"{entry.get('attempts', 0)} guesses · {entry.get('accuracy', 0):g}%",
        }
        for index, entry in enumerate(scores[:5])
    ]
    participant_names = [
        entry.get("name", "Guest")
        for entry in results.get("participant_results", [])
        if isinstance(entry, dict)
    ]
    participant_note = ", ".join(participant_names[:8])
    if len(participant_names) > 8:
        participant_note = f"{participant_note}, and {len(participant_names) - 8} more"
    return {
        "category": "Two Truths and a Lie",
        "primary": "Final Scores",
        "secondary": f"{len(participant_names)} participant{'s' if len(participant_names) != 1 else ''}",
        "tertiary": f"Players: {participant_note}" if participant_note else "Thanks for playing.",
        "scoreboard": {"entries": rows},
    }


def build_two_truths_winner_entry(game: dict[str, object] | None = None) -> dict[str, object] | None:
    winners = two_truths_winners(game)
    if not winners:
        return None
    winner_names = [str(entry.get("name", "Guest")) for entry in winners]
    top_score = int(winners[0].get("correct", 0) or 0)
    return {
        "category": "Two Truths and a Lie Winners" if len(winners) > 1 else "Two Truths and a Lie Winner",
        "primary": ", ".join(winner_names),
        "secondary": f"{top_score} correct guess{'es' if top_score != 1 else ''}",
        "tertiary": "A tie at the top!" if len(winners) > 1 else "Master of the mystery guests.",
    }


def two_truths_admin_view() -> dict[str, object]:
    game = two_truths_game()
    statistics = two_truths_statistics(game)
    participants = list(game.get("participants", {}).values())
    participants.sort(key=lambda entry: str(entry.get("answer_name", "")).casefold())
    raw_guesses = []
    participants_by_id = game.get("participants", {})
    for guesser_id, guesses in game.get("guesses", {}).items():
        guesser = participants_by_id.get(guesser_id, {})
        for submission_id, guess in guesses.items():
            target = two_truths_participant_by_submission(submission_id) or {}
            raw_guesses.append(
                {
                    "guesser_name": guesser.get("answer_name", "Guest"),
                    "target_name": target.get("answer_name", "Unknown"),
                    "guessed_name": guess.get("guessed_name", ""),
                    "correct": guess.get("normalized_name") == normalize_guess_name(target.get("answer_name", "")),
                    "submitted_at": guess.get("submitted_at", ""),
                }
            )
    raw_guesses.sort(key=lambda entry: str(entry.get("submitted_at", "")), reverse=True)
    return {
        **copy.deepcopy(game),
        "statistics": statistics,
        "participants_list": participants,
        "raw_guesses": raw_guesses,
        "winners": two_truths_winners(game),
    }


def party_game_state(game_key: str) -> dict[str, object]:
    game = games_state.get(game_key)
    if isinstance(game, dict):
        return game
    if game_key == TWO_TRUTHS_GAME_KEY:
        game = empty_two_truths_game_state()
    elif game_key == MURDER_MARRY_FUCK_GAME_KEY:
        game = empty_mmf_game_state()
    elif game_key in PROMPT_GAME_KEYS:
        game = empty_prompt_game_state(game_key)
    else:
        raise KeyError(game_key)
    games_state[game_key] = game
    return game


def enabled_game_keys() -> list[str]:
    return [game_key for game_key in GAME_CATALOG if party_game_state(game_key).get("enabled")]


def game_catalog_views(user_id: str = "") -> list[dict[str, object]]:
    views = []
    for game_key, metadata in GAME_CATALOG.items():
        game = party_game_state(game_key)
        participants = game.get("participants", {})
        views.append(
            {
                **metadata,
                "key": game_key,
                "enabled": bool(game.get("enabled")),
                "phase": str(game.get("phase", "signup")),
                "participant_count": len(participants),
                "participating": bool(user_id and user_id in participants),
            }
        )
    return views


def current_event_id() -> str:
    return event_id_for_year(app.config["PARTY_YEAR"])


def static_asset_url(filename: object) -> str:
    cleaned = str(filename or "").strip().lstrip("/")
    return f"/static/{cleaned}" if cleaned else ""


def game_art_url(game_key: str, *, winner: bool = False) -> str:
    metadata = GAME_CATALOG[game_key]
    filename = metadata.get("winner_image") if winner else metadata.get("image")
    return static_asset_url(filename)


FEATURE_ART: dict[str, str] = {
    "jukebox": "/static/images/features/jukebox.jpg",
    "bar": "/static/images/features/bar.jpg",
    "menu": "/static/images/features/menu.jpg",
    "karaoke": "/static/images/features/karaoke.jpg",
}


def game_public_score_rows(game_key: str, game: dict[str, object]) -> list[dict[str, object]]:
    if game.get("phase") != "ended":
        return []
    results = game.get("results", {}) if isinstance(game.get("results"), dict) else {}
    rows = []
    for index, score in enumerate(results.get("scores", [])):
        if not isinstance(score, dict):
            continue
        points = int(score.get("correct", score.get("points", 0)) or 0)
        row = {
            "rank": index + 1,
            "name": str(score.get("name", score.get("alias", "Player")) or "Player")[:80],
            "points": points,
        }
        if game_key == TWO_TRUTHS_GAME_KEY:
            row["detail"] = f"{int(score.get('attempts', 0) or 0)} guesses · {float(score.get('accuracy', 0) or 0):g}% accuracy"
        elif game_key == MURDER_MARRY_FUCK_GAME_KEY:
            row["detail"] = f"{int(score.get('completed_rounds', 0) or 0)} of {MMF_ROUND_COUNT} rounds"
        else:
            row["detail"] = "Anonymous alias" if score.get("anonymous") else "Party account name"
        rows.append(row)
    return rows


def game_public_winner_names(game_key: str, game: dict[str, object]) -> list[str]:
    return [
        str(winner.get("name", winner.get("alias", "Player")) or "Player")[:80]
        for winner in game_winners(game_key, game)
    ]


def safe_game_status_view(game_key: str, user_id: str = "") -> dict[str, object]:
    game = party_game_state(game_key)
    metadata = GAME_CATALOG[game_key]
    phase = str(game.get("phase", "signup") or "signup")
    participants = game.get("participants", {}) if isinstance(game.get("participants"), dict) else {}
    view: dict[str, object] = {
        "key": game_key,
        "slug": metadata["slug"],
        "title": metadata["title"],
        "short_title": metadata["short_title"],
        "description": metadata["description"],
        "image_url": game_art_url(game_key),
        "winner_image_url": game_art_url(game_key, winner=True),
        "enabled": bool(game.get("enabled")),
        "phase": phase,
        "status_label": "Final results" if phase == "ended" else ("Live now" if phase == "active" else "Enrollment open"),
        "participant_count": len(participants),
        "participating": bool(user_id and user_id in participants),
        "simulation": bool(game.get("simulation", {}).get("is_simulated")) if isinstance(game.get("simulation"), dict) else False,
        "metrics": [],
        "winners": [],
        "scores": [],
        "rounds": [],
    }
    if game_key == TWO_TRUTHS_GAME_KEY:
        stats = two_truths_statistics(game)
        view["metrics"] = [
            {"label": "Players", "value": stats.get("participant_count", 0)},
            {"label": "Guesses", "value": stats.get("submitted_guesses", 0)},
            {"label": "Possible", "value": stats.get("possible_guesses", 0)},
            {"label": "Complete", "value": f"{stats.get('completion_percent', 0):g}%"},
        ]
    elif game_key == MURDER_MARRY_FUCK_GAME_KEY:
        completed = sum(len(participant.get("answers", {})) for participant in participants.values() if isinstance(participant, dict))
        possible = len(participants) * MMF_ROUND_COUNT
        view["metrics"] = [
            {"label": "Players", "value": len(participants)},
            {"label": "Rounds saved", "value": completed},
            {"label": "Possible", "value": possible},
            {"label": "Complete", "value": f"{round((completed / possible * 100) if possible else 0):g}%"},
        ]
    else:
        current_round = prompt_round_for_game(game)
        responses = current_round.get("responses", {}) if isinstance(current_round, dict) and isinstance(current_round.get("responses"), dict) else {}
        votes = current_round.get("votes", {}) if isinstance(current_round, dict) and isinstance(current_round.get("votes"), dict) else {}
        if current_round:
            view["current_round"] = {
                "number": next((index + 1 for index, item in enumerate(game.get("rounds", [])) if item.get("id") == current_round.get("id")), 1),
                "phase": str(current_round.get("status", "submissions")),
                "prompt": str(current_round.get("prompt_text", "") or "")[:240],
                "blind_responses": [
                    {"id": str(response.get("id", "")), "text": str(response.get("text", "") or "")[:280]}
                    for response in responses.values()
                    if isinstance(response, dict)
                ] if current_round.get("status") in {"voting", "revealed"} else [],
            }
        view["metrics"] = [
            {"label": "Players", "value": len(participants)},
            {"label": "Rounds", "value": len(game.get("rounds", []))},
            {"label": "Responses", "value": len(responses)},
            {"label": "Votes", "value": len(votes)},
        ]
    if phase == "ended":
        view["winners"] = game_public_winner_names(game_key, game)
        view["scores"] = game_public_score_rows(game_key, game)
        if game_key == MURDER_MARRY_FUCK_GAME_KEY:
            view["rounds"] = copy.deepcopy(game.get("results", {}).get("round_results", []))
        elif game_key in PROMPT_GAME_KEYS:
            identities = {
                str(participant.get("player_id", "")): participant_public_name(
                    participant,
                    anonymous=bool(game.get("anonymous_mode")),
                )
                for participant in participants.values()
                if isinstance(participant, dict)
            }
            public_rounds = []
            for game_round in game.get("rounds", []):
                if not isinstance(game_round, dict) or game_round.get("status") != "revealed":
                    continue
                results = game_round.get("results", {}) if isinstance(game_round.get("results"), dict) else {}
                winner_ids = set(results.get("winner_response_ids", []))
                public_rounds.append(
                    {
                        "prompt": str(game_round.get("prompt_text", "") or "")[:240],
                        "vote_count": int(results.get("vote_count", 0) or 0),
                        "responses": [
                            {
                                "text": str(response.get("text", "") or "")[:280],
                                "votes": int(results.get("vote_counts", {}).get(response_id, 0) or 0),
                                "winner": response_id in winner_ids,
                                "winner_identity": identities.get(str(response.get("player_id", "")), "Player") if response_id in winner_ids else "",
                            }
                            for response_id, response in game_round.get("responses", {}).items()
                            if isinstance(response, dict)
                        ],
                    }
                )
            view["rounds"] = public_rounds
    revision_source = json.dumps(view, sort_keys=True, separators=(",", ":"))
    view["revision"] = hashlib.sha256(revision_source.encode("utf-8")).hexdigest()[:16]
    return view


def game_winner_links(game_key: str, game: dict[str, object]) -> list[dict[str, str]]:
    winners = game_winners(game_key, game)
    links: list[dict[str, str]] = []
    if game_key == TWO_TRUTHS_GAME_KEY:
        for winner in winners:
            user_id = str(winner.get("user_id", ""))
            links.append({"account_id": user_id, "public_identity": str(winner.get("name", "Guest"))[:80]})
        return links
    winner_player_ids = {str(winner.get("player_id", "")) for winner in winners}
    for account_id, participant in game.get("participants", {}).items():
        if not isinstance(participant, dict) or str(participant.get("player_id", "")) not in winner_player_ids:
            continue
        links.append(
            {
                "account_id": str(account_id),
                "public_identity": participant_public_name(participant, anonymous=bool(game.get("anonymous_mode"))),
            }
        )
    return links


def upsert_game_result_archive(game_key: str) -> dict[str, object] | None:
    game = party_game_state(game_key)
    if game.get("phase") != "ended":
        return None
    event_id = current_event_id()
    archive_id = f"{event_id}:game:{game_key}"
    existing = next((archive for archive in result_archives if archive.get("id") == archive_id), None)
    if existing and existing.get("status") == "official":
        return existing
    archive = {
        "id": archive_id,
        "event_id": event_id,
        "year": str(app.config["PARTY_YEAR"]),
        "kind": "game",
        "subject_key": game_key,
        "title": GAME_CATALOG[game_key]["title"],
        "image_url": game_art_url(game_key),
        "winner_image_url": game_art_url(game_key, winner=True),
        "status": str(existing.get("status", "draft")) if existing else "draft",
        "simulation": bool(game.get("simulation", {}).get("is_simulated")) if isinstance(game.get("simulation"), dict) else False,
        "finalized_at": str(game.get("ended_at", "") or game.get("results", {}).get("finalized_at", "") or _utc_now_iso()),
        "published_at": str(existing.get("published_at", "")) if existing else "",
        "summary": safe_game_status_view(game_key),
        "winner_links": game_winner_links(game_key, game),
    }
    if existing:
        existing.clear()
        existing.update(archive)
        return existing
    result_archives.append(archive)
    return archive


def upsert_costume_result_archive() -> dict[str, object] | None:
    winner = contest_state.get("winner")
    if not isinstance(winner, dict) or not contest_state.get("winner_locked"):
        return None
    event_id = current_event_id()
    archive_id = f"{event_id}:costume:contest"
    existing = next((archive for archive in result_archives if archive.get("id") == archive_id), None)
    if existing and existing.get("status") == "official":
        return existing
    winning_signup = next((signup for signup in costume_signups if signup.id == winner.get("id")), None)
    archive = {
        "id": archive_id,
        "event_id": event_id,
        "year": str(app.config["PARTY_YEAR"]),
        "kind": "costume",
        "subject_key": "costume_contest",
        "title": "Costume Contest",
        "image_url": "",
        "winner_image_url": "",
        "status": str(existing.get("status", "draft")) if existing else "draft",
        "simulation": False,
        "finalized_at": _utc_now_iso(),
        "published_at": str(existing.get("published_at", "")) if existing else "",
        "summary": {
            "winners": [str(winner.get("name", "Guest"))],
            "scores": [
                {
                    "rank": index + 1,
                    "name": str(entry.get("name", "Guest")),
                    "points": round(float(entry.get("average", 0) or 0), 2),
                    "detail": str(entry.get("costume", "")),
                }
                for index, entry in enumerate(rank_costume_entries(build_costume_scoreboard()[0])[:6])
            ],
        },
        "winner_links": [
            {
                "account_id": str(winning_signup.account_id if winning_signup else ""),
                "public_identity": str(winner.get("name", "Guest")),
            }
        ],
    }
    if existing:
        existing.clear()
        existing.update(archive)
        return existing
    result_archives.append(archive)
    return archive


def account_name_by_id(account_id: str) -> str:
    return next(
        (str(account.get("username", "")) for account in user_accounts.values() if str(account.get("id", "")) == account_id),
        "",
    )


def publish_result_archive(archive: dict[str, object]) -> int:
    if archive.get("simulation"):
        raise ValueError("Simulated results cannot be published as official history.")
    archive["status"] = "official"
    archive["published_at"] = archive.get("published_at") or _utc_now_iso()
    created = 0
    kind = "game_win" if archive.get("kind") == "game" else "costume_win"
    for winner in archive.get("winner_links", []):
        if not isinstance(winner, dict):
            continue
        account_id = str(winner.get("account_id", "") or "")
        public_identity = str(winner.get("public_identity", "") or "Guest")[:80]
        if not account_id:
            continue
        recipient_name = account_name_by_id(account_id) or public_identity
        if credit_exists(
            recognition_credits,
            kind=kind,
            account_id=account_id,
            event_id=str(archive.get("event_id", "")),
            subject_key=str(archive.get("subject_key", "")),
            source_ref=str(archive.get("id", "")),
        ):
            continue
        recognition_credits.append(
            new_credit(
                kind=kind,
                account_id=account_id,
                recipient_name=recipient_name,
                public_identity=public_identity,
                event_id=str(archive.get("event_id", "")),
                year=str(archive.get("year", "")),
                subject_key=str(archive.get("subject_key", "")),
                subject_label=str(archive.get("title", "")),
                source_ref=str(archive.get("id", "")),
            )
        )
        created += 1
    return created


def results_rewards_payload(user_id: str) -> dict[str, object]:
    games = [
        safe_game_status_view(game_key, user_id)
        for game_key in GAME_CATALOG
        if party_game_state(game_key).get("enabled") or party_game_state(game_key).get("phase") != "signup"
    ]
    archives = [copy.deepcopy(archive) for archive in result_archives if archive.get("status") == "official"]
    for archive in archives:
        archive.pop("winner_links", None)
    archives.sort(key=lambda archive: (str(archive.get("year", "")), str(archive.get("published_at", ""))), reverse=True)
    return {
        "games": games,
        "archives": archives,
        "achievements": achievement_views(recognition_credits, user_id),
        "display_update_version": display_update_version,
    }


def total_game_participations() -> int:
    return sum(len(party_game_state(game_key).get("participants", {})) for game_key in GAME_CATALOG)


def game_alias_participant(game: dict[str, object], user_id: str) -> dict[str, object] | None:
    participant = game.get("participants", {}).get(user_id)
    return participant if isinstance(participant, dict) else None


def add_alias_participant(
    game: dict[str, object],
    user_id: str,
    *,
    display_name: str = "",
) -> dict[str, object]:
    existing = game_alias_participant(game, user_id)
    if existing:
        normalized_name = re.sub(r"\s+", " ", str(display_name or "").strip())[:80]
        existing["display_name"] = normalized_name
        existing["updated_at"] = _utc_now_iso()
        return existing
    existing_aliases = {
        str(entry.get("alias", ""))
        for entry in game.get("participants", {}).values()
        if isinstance(entry, dict)
    }
    timestamp = _utc_now_iso()
    participant = {
        "player_id": uuid4().hex,
        "display_name": re.sub(r"\s+", " ", str(display_name or "").strip())[:80],
        "alias": generate_game_alias(existing_aliases),
        "answers": {},
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    game.setdefault("participants", {})[user_id] = participant
    return participant


def mmf_admin_view() -> dict[str, object]:
    game = party_game_state(MURDER_MARRY_FUCK_GAME_KEY)
    statistics = mmf_statistics(game)
    return {
        **copy.deepcopy(game),
        "key": MURDER_MARRY_FUCK_GAME_KEY,
        "metadata": GAME_CATALOG[MURDER_MARRY_FUCK_GAME_KEY],
        "statistics": statistics,
        "winners": game_winners(MURDER_MARRY_FUCK_GAME_KEY, game),
        "reset_phrase": "RESET MURDER MARRY FUCK",
    }


def prompt_admin_view(game_key: str) -> dict[str, object]:
    game = party_game_state(game_key)
    statistics = prompt_game_statistics(game)
    return {
        **copy.deepcopy(game),
        "key": game_key,
        "metadata": GAME_CATALOG[game_key],
        "statistics": statistics,
        "winners": game_winners(game_key, game),
        "reset_phrase": f"RESET {GAME_CATALOG[game_key]['short_title'].upper()}",
    }


def game_admin_view(game_key: str) -> dict[str, object]:
    if game_key == TWO_TRUTHS_GAME_KEY:
        view = two_truths_admin_view()
        view.update(
            {
                "key": TWO_TRUTHS_GAME_KEY,
                "metadata": GAME_CATALOG[TWO_TRUTHS_GAME_KEY],
                "reset_phrase": "RESET TWO TRUTHS AND A LIE",
            }
        )
        return view
    if game_key == MURDER_MARRY_FUCK_GAME_KEY:
        return mmf_admin_view()
    return prompt_admin_view(game_key)


def game_admin_summary(game_key: str) -> dict[str, object]:
    game = party_game_state(game_key)
    return {
        "key": game_key,
        "metadata": GAME_CATALOG[game_key],
        "enabled": bool(game.get("enabled")),
        "phase": str(game.get("phase", "signup")),
        "participant_count": len(game.get("participants", {})),
        "simulation": copy.deepcopy(game.get("simulation", {})),
    }


def all_games_admin_view(
    selected_key: str | None = None,
    *,
    include_selected: bool = True,
) -> dict[str, object]:
    game_summaries = {game_key: game_admin_summary(game_key) for game_key in GAME_CATALOG}
    selected_key = selected_key if selected_key in game_summaries else TWO_TRUTHS_GAME_KEY
    active_count = sum(1 for entry in game_summaries.values() if entry.get("phase") == "active")
    enabled_count = sum(1 for entry in game_summaries.values() if entry.get("enabled"))
    participant_count = sum(int(entry.get("participant_count", 0) or 0) for entry in game_summaries.values())
    return {
        "games": game_summaries,
        "catalog": GAME_CATALOG,
        "selected_key": selected_key,
        "selected": game_admin_view(selected_key) if include_selected else {},
        "active_count": active_count,
        "enabled_count": enabled_count,
        "participant_count": participant_count,
    }


def game_scoreboard_entry(game_key: str) -> dict[str, object] | None:
    if game_key == TWO_TRUTHS_GAME_KEY:
        return build_two_truths_scoreboard_card()
    game = party_game_state(game_key)
    scores = game.get("results", {}).get("scores", [])
    if not scores:
        return None
    rows = [
        {
            "rank": index + 1,
            "name": entry.get("name", entry.get("alias", "Player")),
            "detail": f"{entry.get('points', 0)} points",
            "value_label": f"{entry.get('points', 0)} pts",
            "meta_label": "Anonymous alias" if entry.get("anonymous") else "Party account name",
        }
        for index, entry in enumerate(scores[:6])
    ]
    return {
        "category": GAME_CATALOG[game_key]["title"],
        "primary": "Final Scores",
        "secondary": f"{len(game.get('participants', {}))} players",
        "tertiary": "Thanks for playing.",
        "scoreboard": {"entries": rows},
    }


def game_winner_entry(game_key: str) -> dict[str, object] | None:
    game = party_game_state(game_key)
    if game.get("phase") != "ended":
        return None
    if game_key == TWO_TRUTHS_GAME_KEY:
        return build_two_truths_winner_entry()
    winners = game_winners(game_key, game)
    if not winners:
        return None
    names = [str(entry.get("name", entry.get("alias", "Player"))) for entry in winners]
    points = int(winners[0].get("points", 0) or 0)
    return {
        "category": f"{GAME_CATALOG[game_key]['title']} Winner{'s' if len(winners) != 1 else ''}",
        "primary": ", ".join(names),
        "secondary": f"{points} point{'s' if points != 1 else ''}",
        "tertiary": "A tie at the top!" if len(winners) > 1 else "Tonight's champion.",
    }


def game_outcome_entry(game_key: str) -> dict[str, object] | None:
    game = party_game_state(game_key)
    if game.get("phase") != "ended":
        return None
    winner = game_winner_entry(game_key)
    if winner:
        return winner
    return {
        "category": f"{GAME_CATALOG[game_key]['title']} Results",
        "primary": "No Winner This Round",
        "secondary": "No positive score was recorded.",
        "tertiary": "Thanks for playing — the final standings are still available.",
    }


def _mmf_person_name(round_result: dict[str, object], person_id: str) -> str:
    for person in round_result.get("people", []):
        if str(person.get("id", "")) == person_id:
            return str(person.get("name", "Unknown"))
    return "Unknown"


def build_game_presentation_slides(game_key: str) -> list[dict[str, object]]:
    game = party_game_state(game_key)
    title = GAME_CATALOG[game_key]["title"]
    slides: list[dict[str, object]] = [
        {
            "type": "game_presentation",
            "title": title,
            "highlight": "Results are in",
            "message": "The host is revealing tonight's blind responses.",
            "details": [f"{len(game.get('participants', {}))} players"],
        }
    ]
    if game_key == MURDER_MARRY_FUCK_GAME_KEY:
        explicit_label = str(game.get("explicit_label", "F%$@"))
        labels = {"murder": "Murder", "marry": "Marry", "fuck": explicit_label}
        for index, result in enumerate(game.get("results", {}).get("round_results", [])):
            people = [str(person.get("name", "")) for person in result.get("people", [])]
            slides.append({"type": "game_presentation", "title": f"Round {index + 1}", "highlight": " · ".join(people), "message": "How did the party divide these three?", "details": [f"{result.get('respondent_count', 0)} completed ballots"]})
            for action in MMF_ACTIONS:
                winners = [_mmf_person_name(result, person_id) for person_id in result.get("winners", {}).get(action, [])]
                detail_rows = []
                for person in result.get("people", []):
                    person_id = str(person.get("id", ""))
                    detail_rows.append(f"{person.get('name', 'Unknown')}: {result.get('totals', {}).get(action, {}).get(person_id, 0)}")
                slides.append({"type": "game_presentation", "title": f"Round {index + 1} · {labels[action]}", "highlight": ", ".join(winners) if winners else "No votes", "message": f"The party's {labels[action]} choice", "details": detail_rows})
    else:
        for index, game_round in enumerate(game.get("rounds", [])):
            if game_round.get("status") != "revealed":
                continue
            results = game_round.get("results", {})
            winning_ids = results.get("winner_response_ids", [])
            winners = [game_round.get("responses", {}).get(response_id, {}) for response_id in winning_ids]
            identities_by_player = {
                entry.get("player_id"): participant_public_name(
                    entry,
                    anonymous=bool(game.get("anonymous_mode")),
                )
                for entry in game.get("participants", {}).values()
            }
            round_detail = "Solo spotlight · 1 point" if results.get("solo_spotlight") else f"{len(game_round.get('responses', {}))} responses · {results.get('vote_count', 0)} votes"
            slides.append({"type": "game_presentation", "title": f"Round {index + 1}", "highlight": game_round.get("prompt_text", ""), "message": "Blind responses are locked.", "details": [round_detail]})
            for response in winners:
                winner_detail = "Solo spotlight · 1 point" if results.get("solo_spotlight") else f"{results.get('vote_counts', {}).get(response.get('id'), 0)} votes"
                slides.append({"type": "game_presentation", "title": f"Round {index + 1} Winner", "highlight": response.get("text", ""), "message": identities_by_player.get(response.get("player_id"), "Player"), "details": [winner_detail]})
    scoreboard = game_scoreboard_entry(game_key)
    if scoreboard:
        slides.append({"type": "game_presentation", "title": title, "highlight": "Final leaderboard", "message": scoreboard.get("secondary", ""), "details": [f"#{row['rank']} {row['name']}: {row['value_label']}" for row in scoreboard["scoreboard"]["entries"]]})
    outcome = game_outcome_entry(game_key)
    if outcome:
        slides.append({"type": "game_winner", "title": outcome["category"], "highlight": outcome["primary"], "message": outcome["secondary"], "details": [outcome["tertiary"]]})
    for slide in slides:
        slide["image_url"] = game_art_url(
            game_key,
            winner=str(slide.get("type", "")) == "game_winner",
        )
        slide["media_treatment"] = "background"
    return slides


def set_game_presentation_slide(game_key: str, slide_index: int) -> bool:
    global live_display_event_override
    game = party_game_state(game_key)
    slides = build_game_presentation_slides(game_key)
    if not slides:
        return False
    clamped_index = min(max(0, slide_index), len(slides) - 1)
    game["presentation"] = {"active": True, "slide_index": clamped_index}
    live_display_event_override = copy.deepcopy(slides[clamped_index])
    live_display_event_override["presentation"] = {
        "game_key": game_key,
        "slide_index": clamped_index,
        "slide_count": len(slides),
    }
    return True


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
        "title": "Party Games",
        "content": "Open Games to join tonight's enabled challenges, submit answers, vote, and follow the host-selected player identity shown for each game.",
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


def _display_entry(source: str, entry_id: str, **content: object) -> dict[str, object]:
    return {
        "id": f"{source}:{entry_id}",
        "source": source,
        "duration_seconds": int(display_config.get("center_interval_seconds", 8) or 8),
        **content,
    }


def _display_fact(label: str, value: object) -> dict[str, str]:
    return {"label": str(label), "value": str(value)}


def _display_duration_label(seconds: object) -> str:
    duration = max(0, _safe_int(seconds, 0))
    if duration < 60:
        return "Under 1 min"
    minutes = max(1, round(duration / 60))
    return f"About {minutes} min"


def _display_contest_status() -> str:
    if contest_state.get("winner_locked"):
        return "Winner selected"
    if contest_state.get("voting_open"):
        return "Voting open"
    if contest_state.get("contest_started"):
        return "Judging live"
    return "Signup open"


def _display_karaoke_status() -> str:
    if karaoke_state.get("party_started"):
        return str(karaoke_state.get("stage_mode", "Live") or "Live").replace("_", " ").title()
    return "Queue open"


def _display_available_drinks() -> list[dict[str, object]]:
    return [
        item
        for item in menu_items
        if item.get("category") == "drink" and item.get("available") and item.get("orderable")
    ]


def game_result_card_is_enabled(card_id: str) -> bool:
    configured = display_config.get("game_result_card_enabled", {})
    if not isinstance(configured, dict):
        return True
    return bool(configured.get(card_id, True))


def generated_game_result_entries(*, include_hidden: bool = False) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for game_key in GAME_CATALOG:
        game = party_game_state(game_key)
        if game.get("phase") != "ended":
            continue
        outcome = game_outcome_entry(game_key)
        scoreboard = game_scoreboard_entry(game_key)
        cards = (("winner", "Winner / Outcome", outcome), ("scores", "Final Scores", scoreboard))
        for suffix, card_type, card in cards:
            if not card:
                continue
            entry = _display_entry("games", f"{game_key}-{suffix}", **card)
            entry["kind"] = "result" if suffix == "winner" else "scoreboard"
            entry["image_url"] = game_art_url(game_key, winner=suffix == "winner")
            entry["media_treatment"] = "background"
            entry["facts"] = [
                _display_fact("Game", GAME_CATALOG[game_key]["short_title"]),
                _display_fact("Players", len(game.get("participants", {}))),
                _display_fact("Status", "Final"),
            ]
            if suffix == "winner" and scoreboard and scoreboard.get("scoreboard"):
                entry["scoreboard"] = {
                    "entries": copy.deepcopy(scoreboard["scoreboard"].get("entries", []))[:3]
                }
            entry["action"] = {
                "label": "See every result",
                "url": f"{PARTY_SITE_URL}/party/games",
            }
            entry["game_key"] = game_key
            entry["game_title"] = GAME_CATALOG[game_key]["title"]
            entry["card_type"] = card_type
            entry["included"] = game_result_card_is_enabled(str(entry["id"]))
            if include_hidden or entry["included"]:
                entries.append(entry)
    return entries


def display_source_is_enabled(source: str) -> bool:
    enabled = display_config.get("source_enabled", {})
    return bool(isinstance(enabled, dict) and enabled.get(source, True))


def build_rotation_entries() -> List[dict[str, object]]:
    ensure_costume_votes_alignment()
    wifi_network = display_settings.get("wifi_network", DEFAULT_DISPLAY_SETTINGS["wifi_network"])
    wifi_password = display_settings.get("wifi_password", DEFAULT_DISPLAY_SETTINGS["wifi_password"])
    enabled_games = enabled_game_keys()
    available_drinks = _display_available_drinks()
    active_orders = active_drink_orders()
    active_game_count = sum(1 for key in enabled_games if party_game_state(key).get("phase") == "active")
    public_karaoke = public_karaoke_signups()
    public_karaoke_singer_count = sum(len(signup.singer_names) for signup in public_karaoke)
    grouped: dict[str, list[dict[str, object]]] = {source: [] for source in DISPLAY_SOURCE_KEYS}

    grouped["portal"].append(
        _display_entry(
            "portal",
            "wifi",
            category="Signup Portal",
            kind="access",
            primary="Connect to the party WiFi.",
            secondary=f"After you connect, browse to {PARTY_SITE_URL} to start the party experience.",
            cta=True,
            cta_details={
                "lede": "Get your phone connected, then open the party site.",
                "wifi_network": wifi_network,
                "wifi_password": wifi_password,
                "site_url": PARTY_SITE_URL,
            },
            facts=[
                _display_fact("Costumes", len(costume_signups)),
                _display_fact("Karaoke", len(public_karaoke)),
                _display_fact("Games live", active_game_count),
                _display_fact("Bar orders", len(active_orders)),
            ],
            steps=[
                "Connect to the party WiFi",
                "Open the party site on your phone",
                "Sign in to play, sing, enter, and order",
            ],
        )
    )

    grouped["costume"].append(
        _display_entry(
            "costume",
            "signup",
            category="Costume Contest",
            kind="action",
            primary="Add your costume to the live lineup.",
            secondary="Use the party portal to enter your name and costume before judging starts.",
            tertiary="New costume signups appear here automatically.",
            facts=[
                _display_fact("Entries", len(costume_signups)),
                _display_fact("Contest", _display_contest_status()),
                _display_fact("Scoring", "1–10 per costume"),
            ],
            steps=["Open Costumes", "Add your costume", "Return when voting opens"],
            action={"label": "Enter the costume contest", "url": f"{PARTY_SITE_URL}/party/costumes"},
        )
    )
    winner_entry = build_winner_entry()
    if winner_entry:
        grouped["costume"].append(_display_entry("costume", "winner", **winner_entry))
    if contest_state.get("show_scoreboard_card") and contest_state.get("scoreboard_card"):
        grouped["costume"].append(
            _display_entry("costume", "scoreboard", **copy.deepcopy(contest_state["scoreboard_card"]))
        )
    grouped["costume"].extend(
        _display_entry(
            "costume",
            signup.id,
            category="Costume Contest",
            kind="profile",
            primary=signup.name,
            secondary=f"Dressed as {signup.costume}",
            tertiary="Tonight's live costume lineup",
            facts=[
                _display_fact("Entry", index + 1),
                _display_fact("Lineup", len(costume_signups)),
                _display_fact("Contest", _display_contest_status()),
            ],
            action={"label": "Add your costume", "url": f"{PARTY_SITE_URL}/party/costumes"},
        )
        for index, signup in enumerate(costume_signups)
    )

    grouped["karaoke"].append(
        _display_entry(
            "karaoke",
            "signup",
            category="Karaoke Stage",
            kind="action",
            primary="Reserve your karaoke song.",
            image_url=FEATURE_ART["karaoke"],
            secondary="Use the party portal to queue the song you want to perform.",
            facts=[
                _display_fact("In lineup", len(public_karaoke)),
                _display_fact("Stage", _display_karaoke_status()),
                _display_fact("Video", "Host approved" if app.config.get("YOUTUBE_KARAOKE_ENABLED") else "Bring a song"),
            ],
            steps=["Open Karaoke", "Choose your exact song", "Watch for your stage call"],
            action={"label": "Join the karaoke queue", "url": f"{PARTY_SITE_URL}/party/karaoke"},
        )
    )
    grouped["karaoke"].extend(
        _display_entry(
            "karaoke",
            signup.id,
            category="Karaoke Stage",
            kind="profile",
            primary=signup.singer_label,
            secondary=f'Performing "{signup.song_title}"',
            tertiary=f"by {signup.artist}" if signup.artist else "",
            image_url=str(signup.youtube.get("thumbnail_url", "") or ""),
            facts=[
                _display_fact("Queue", index + 1),
                _display_fact("Singers", public_karaoke_singer_count),
                _display_fact("Stage", str(signup.workflow.get("performance_status", "waiting") or "waiting").replace("_", " ").title()),
            ],
            action={"label": "Reserve your song", "url": f"{PARTY_SITE_URL}/party/karaoke"},
        )
        for index, signup in enumerate(public_karaoke)
    )

    if enabled_games:
        grouped["games"].append(
            _display_entry(
                "games",
                "join",
                category="Party Games",
                kind="action",
                primary="Join tonight's party games.",
                image_url=game_art_url(enabled_games[0]),
                media_treatment="background",
                secondary="Open Games in the party portal to opt in, answer, and vote.",
                tertiary="Available: " + " · ".join(GAME_CATALOG[key]["short_title"] for key in enabled_games),
                facts=[
                    _display_fact("Available", len(enabled_games)),
                    _display_fact("Live now", active_game_count),
                    _display_fact("Players", total_game_participations()),
                ],
                steps=["Open Games", "Join any enabled game", "Submit, vote, and follow results"],
                action={"label": "Join party games", "url": f"{PARTY_SITE_URL}/party/games"},
            )
        )
    grouped["games"].extend(generated_game_result_entries())

    grouped["bar"].append(
        _display_entry(
            "bar",
            "ordering",
            category="Bar Queue",
            kind="action",
            primary="Order event drinks from your phone.",
            image_url=FEATURE_ART["menu"],
            secondary="Browse the menu, send available drinks to the bar, and watch the right stage for status.",
            tertiary="Completed drinks receive a ready alert here and by email.",
            facts=[
                _display_fact("Available", len(available_drinks)),
                _display_fact("Active orders", len(active_orders)),
                _display_fact("Average prep", _display_duration_label(average_drink_completion_seconds())),
            ],
            steps=["Open the Menu", "Choose an available drink", "Watch the right stage for pickup"],
            action={"label": "Browse drinks", "url": f"{PARTY_SITE_URL}/party/menu"},
        )
    )
    grouped["updates"].append(
        _display_entry(
            "updates",
            "live",
            category="Live Updates",
            kind="status",
            primary="Watch the party build in real time.",
            secondary="Costumes, karaoke, game results, drink status, and announcements update all night.",
            tertiary="Keep an eye on every stage after each signup.",
            facts=[
                _display_fact("Costumes", len(costume_signups)),
                _display_fact("Karaoke", len(public_karaoke)),
                _display_fact("Game players", total_game_participations()),
                _display_fact("Bar queue", len(active_orders)),
            ],
            steps=["Use your phone to participate", "Changes appear here live", "Ready alerts stay on the right"],
            action={"label": "Open the party hub", "url": PARTY_PORTAL_URL},
        )
    )

    for card in display_custom_cards:
        if not display_custom_card_is_active(card):
            continue
        grouped["custom"].append(
            _display_entry(
                "custom",
                str(card.get("id", "")),
                category=card.get("category", "Announcement"),
                kind="announcement",
                primary=card.get("primary", ""),
                secondary=card.get("secondary", ""),
                tertiary=card.get("tertiary", ""),
                image_url=card.get("image_url", ""),
                link=card.get("link", ""),
                link_label=card.get("link_label", ""),
                duration_seconds=card.get("duration_seconds", display_config.get("center_interval_seconds", 8)),
                custom=True,
            )
        )

    ordered_sources = display_config.get("source_order", list(DISPLAY_SOURCE_KEYS))
    rotation_entries: list[dict[str, object]] = []
    for source in ordered_sources if isinstance(ordered_sources, list) else DISPLAY_SOURCE_KEYS:
        if source in grouped and display_source_is_enabled(source):
            rotation_entries.extend(grouped[source])
    return rotation_entries


def build_game_stage_entries() -> list[dict[str, object]]:
    if display_config.get("game_mode") == "hidden":
        return []
    entries: list[dict[str, object]] = []
    for game_key in enabled_game_keys():
        game = party_game_state(game_key)
        phase = str(game.get("phase", "signup") or "signup")
        participants = game.get("participants", {}) if isinstance(game.get("participants"), dict) else {}
        title = GAME_CATALOG[game_key]["title"]
        entry: dict[str, object] = {
            "id": game_key,
            "game_key": game_key,
            "title": title,
            "image_url": game_art_url(game_key),
            "media_treatment": "background",
            "phase": phase,
            "status_label": phase.replace("_", " ").title(),
            "primary": GAME_CATALOG[game_key]["description"],
            "secondary": "Open Games in the party portal to join.",
            "metrics": [{"label": "Players", "value": len(participants)}],
            "steps": [
                "Open Games in the party portal",
                "Join this game",
                "Follow the live phase shown here",
            ],
            "action_label": "Join at tnq-halloween.com/party/games",
            "priority": 2 if phase == "active" else (1 if phase == "ended" else 0),
        }

        detail_entries: list[dict[str, object]] = []
        if game_key == TWO_TRUTHS_GAME_KEY:
            stats = two_truths_statistics(game)
            entry["primary"] = "Identify the mystery guests behind the clues."
            entry["metrics"] = [
                {"label": "Players", "value": stats.get("participant_count", 0)},
                {"label": "Guesses", "value": f"{stats.get('submitted_guesses', 0)}/{stats.get('possible_guesses', 0)}"},
            ]
            if phase == "ended":
                winners = two_truths_winners(game)
                entry["primary"] = ", ".join(str(winner.get("name", "Guest")) for winner in winners) or "Final results ready"
                entry["secondary"] = "Two Truths and a Lie winner" if len(winners) == 1 else "Two Truths and a Lie winners"
            else:
                for participant in participants.values():
                    statements = participant_statements(participant)
                    if len(statements) != 3:
                        continue
                    detail_entries.append(
                        {
                            **entry,
                            "id": f"{game_key}:{participant.get('submission_id', 'clue')}",
                            "status_label": "Mystery clue",
                            "primary": f"1. {statements[0]} · 2. {statements[1]} · 3. {statements[2]}",
                            "secondary": "Can you identify the mystery guest?",
                            "steps": statements,
                            "action_label": "Make your guess in Party Games",
                            "metrics": [],
                            "priority": 3 if phase == "active" else 1,
                        }
                    )
        elif game_key == MURDER_MARRY_FUCK_GAME_KEY:
            completed = sum(1 for participant in participants.values() if len(participant.get("answers", {})) >= 10)
            entry["primary"] = "Ten rounds · three choices · one private ballot."
            entry["metrics"] = [
                {"label": "Players", "value": len(participants)},
                {"label": "Complete", "value": f"{completed}/{len(participants)}"},
                {"label": "Rounds", "value": "10"},
            ]
            if phase == "ended":
                winners = game_winners(game_key, game)
                entry["primary"] = ", ".join(str(winner.get("name", winner.get("alias", "Player"))) for winner in winners) or "Final results ready"
                entry["secondary"] = "Game champions"
        elif game_key in PROMPT_GAME_KEYS:
            current_round = prompt_round_for_game(game)
            if current_round:
                round_status = str(current_round.get("status", "submissions"))
                responses = current_round.get("responses", {}) if isinstance(current_round.get("responses"), dict) else {}
                votes = current_round.get("votes", {}) if isinstance(current_round.get("votes"), dict) else {}
                entry["status_label"] = f"Round {int(game.get('current_round_index', 0) or 0) + 1} · {round_status.title()}"
                entry["primary"] = str(current_round.get("prompt_text", "") or "Responses are open.")
                entry["secondary"] = "Blind voting is open in Games." if round_status == "voting" else "Submit your response in Games."
                entry["metrics"] = [
                    {"label": "Answers", "value": len(responses)},
                    {"label": "Votes", "value": len(votes)},
                    {"label": "Players", "value": len(participants)},
                ]
                entry["steps"] = [
                    "Read the current prompt",
                    "Submit your response" if round_status == "submissions" else "Vote for another response",
                    "Watch for the reveal",
                ]
                entry["action_label"] = "Respond in Party Games" if round_status == "submissions" else "Vote now in Party Games"
                entry["priority"] = 3 if round_status in {"voting", "revealed"} else 2
                if round_status in {"voting", "revealed"}:
                    for response in responses.values():
                        detail_entries.append(
                            {
                                **entry,
                                "id": f"{game_key}:{response.get('id', 'response')}",
                                "status_label": f"Round {int(game.get('current_round_index', 0) or 0) + 1} · {round_status.title()}",
                                "primary": str(current_round.get("prompt_text", "") or "Prompt"),
                                "secondary": str(response.get("text", "") or "Anonymous response"),
                                "metrics": [
                                    {"label": "Answers", "value": len(responses)},
                                    {"label": "Votes", "value": len(votes)},
                                    {"label": "Players", "value": len(participants)},
                                ],
                                "steps": [
                                    "Open Party Games",
                                    "Read every blind response",
                                    "Vote for your favorite",
                                ],
                                "action_label": "Vote in Party Games",
                                "priority": 4,
                            }
                        )
            if phase == "ended":
                winners = game_winners(game_key, game)
                entry["primary"] = ", ".join(str(winner.get("name", winner.get("alias", "Player"))) for winner in winners) or "Final results ready"
                entry["secondary"] = "Game champions"

        if phase == "ended" and game_public_winner_names(game_key, game):
            entry["image_url"] = game_art_url(game_key, winner=True)
        entries.append(entry)
        entries.extend(detail_entries)

    pinned_game_key = str(display_config.get("pinned_game_key", "") or "")
    if pinned_game_key:
        pinned = [entry for entry in entries if entry["game_key"] == pinned_game_key]
        if pinned:
            return pinned
    entries.sort(key=lambda entry: (-int(entry.get("priority", 0)), str(entry.get("title", ""))))
    return entries


def build_bar_stage() -> dict[str, object]:
    orders = sorted(
        active_drink_orders(),
        key=lambda order: (drink_order_priority_bucket(order), str(order.get("created_at", ""))),
    )
    maximum = _bounded_int(display_config.get("max_bar_orders"), 4, 1, 8)
    public_orders = [
        {
            "id": str(order.get("id", "")),
            "name": str(order.get("username", "") or "Guest"),
            "drink": str(order.get("item_name", "") or "Drink"),
            "status": str(order.get("status", "received")),
            "status_label": "Mixing" if order.get("status") == "in_progress" else "Received",
            "estimated_ready_label": format_time_label(order.get("estimated_ready_at")),
            "position": index + 1,
        }
        for index, order in enumerate(orders[:maximum])
    ]
    available_drinks = _display_available_drinks()
    featured_drink = available_drinks[0] if available_drinks else None
    mode = str(display_config.get("bar_mode", "auto"))
    visible = mode != "hidden" and (mode == "always" or bool(public_orders) or bool(live_display_notice_override))
    return {
        "visible": visible,
        "orders": public_orders,
        "active_count": len(orders),
        "overflow_count": max(0, len(orders) - len(public_orders)),
        "notice": copy.deepcopy(live_display_notice_override),
        "queued_notice_count": len(live_display_notice_queue),
        "summary": {
            "mixing_count": sum(1 for order in orders if order.get("status") == "in_progress"),
            "waiting_count": sum(1 for order in orders if order.get("status") == "received"),
            "average_prep_label": _display_duration_label(average_drink_completion_seconds()),
            "available_drink_count": len(available_drinks),
        },
        "featured_item": (
            {
                "name": str(featured_drink.get("name", "") or ""),
                "description": str(featured_drink.get("description", "") or ""),
                "image_url": safe_image_url(str(featured_drink.get("image_url", "") or "")),
            }
            if featured_drink
            else None
        ),
        "action": {"label": "Order from your phone", "url": f"{PARTY_SITE_URL}/party/menu"},
        "image_url": FEATURE_ART["bar"],
        "pickup_note": "Pick up completed drinks at the bar when your name appears here.",
    }


def build_music_footer() -> dict[str, object]:
    dj = dj_view_state()
    receiver = dj.get("receiver", {}) if isinstance(dj.get("receiver"), dict) else {}
    current_song = dj.get("current_song")
    next_song = dj.get("next_song")
    mode = str(display_config.get("music_mode", "auto"))
    needs_attention = bool(apple_music_is_configured() and (not receiver.get("audio_enabled") or receiver.get("last_error")))
    visible = mode != "hidden" and (mode == "always" or bool(current_song) or needs_attention)
    return {
        "visible": visible,
        "state": dj,
        "current_song": copy.deepcopy(current_song),
        "next_song": copy.deepcopy(next_song),
        "needs_attention": needs_attention,
    }


def build_display_layout() -> dict[str, object]:
    entries = build_rotation_entries()
    game_entries = build_game_stage_entries()
    pinned_card_id = str(display_runtime.get("pinned_card_id", "") or "")
    if pinned_card_id and not any(str(entry.get("id", "")) == pinned_card_id for entry in entries):
        pinned_card_id = ""
    return {
        "header": {
            "costume_count": len(costume_signups),
            "karaoke_count": len(public_karaoke_signups()),
            "game_count": total_game_participations(),
        },
        "center": {
            "entries": entries,
            "override": copy.deepcopy(live_display_event_override),
            "paused": bool(display_runtime.get("center_paused")),
            "index": int(display_runtime.get("center_index", 0) or 0),
            "revision": int(display_runtime.get("center_revision", 0) or 0),
            "pinned_card_id": pinned_card_id,
            "interval_seconds": int(display_config.get("center_interval_seconds", 8) or 8),
        },
        "games": {
            "visible": display_config.get("game_mode") != "hidden" and bool(game_entries),
            "entries": game_entries,
            "interval_seconds": int(display_config.get("game_interval_seconds", 10) or 10),
            "pinned_game_key": str(display_config.get("pinned_game_key", "") or ""),
        },
        "bar": build_bar_stage(),
        "music": build_music_footer(),
        "density": str(display_config.get("density", "standard") or "standard"),
    }


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
    layout = build_display_layout()
    rotation_entries = layout["center"]["entries"]

    return render_template(
        "display.html",
        layout=layout,
        entries=rotation_entries,
        costume_count=len(costume_signups),
        karaoke_count=len(public_karaoke_signups()),
        game_count=total_game_participations(),
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
    layout = build_display_layout()
    rotation_entries = layout["center"]["entries"]

    return jsonify(
        {
            "entries": rotation_entries,
            "costume_count": len(costume_signups),
            "karaoke_count": len(public_karaoke_signups()),
            "game_count": total_game_participations(),
            "override": live_display_event_override,
            "event_override": live_display_event_override,
            "notice_override": live_display_notice_override,
            "dj": dj_view_state(),
            "layout": layout,
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
    game_user_id = str(session.get("user_id", "") or "")
    catalog_views = game_catalog_views(game_user_id)
    enabled_views = [entry for entry in catalog_views if entry["enabled"]]
    active_views = [entry for entry in enabled_views if entry["phase"] == "active"]
    primary_game = active_views[0] if active_views else (enabled_views[0] if enabled_views else None)
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
        "party_games_state": {
            "available": party_day_has_arrived() and bool(enabled_views),
            "enabled": bool(enabled_views),
            "phase": primary_game["phase"] if primary_game else "signup",
            "participating": bool(primary_game and primary_game["participating"]),
            "participant_count": sum(int(entry["participant_count"]) for entry in enabled_views),
            "enabled_count": len(enabled_views),
            "active_count": len(active_views),
            "primary": primary_game,
            "games": enabled_views,
        },
        "party_title": app.config["PARTY_TITLE"],
        "party_year": app.config["PARTY_YEAR"],
        "feature_art": FEATURE_ART,
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
    user_id = str(session.get("user_id", "") or "")
    user_orders = user_drink_orders(user_id)
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
        karaoke_attendee=karaoke_attendee_view_state(user_id) if party_day else None,
        karaoke_data_url=url_for("party_karaoke_data") if party_day else "",
        drink_orders=user_orders[:5] if party_day else [],
        ready_drink_orders=ready_orders,
        jukebox=attendee_jukebox_state(user_id) if party_day else None,
        jukebox_data_url=url_for("party_jukebox_data") if party_day else "",
        games_data_url=url_for("party_games_data"),
        feature_art=FEATURE_ART,
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
        achievements=achievement_views(recognition_credits, account_id),
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
                enqueue_display_notice(build_drink_ready_override(order))
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


@app.route("/party/results")
def party_results():
    user_id = str(session.get("user_id", "") or "")
    payload = results_rewards_payload(user_id)
    return render_template(
        "results.html",
        results_payload=payload,
        games_data_url=url_for("party_games_data"),
        feature_art=FEATURE_ART,
        show_admin_link=False,
    )


@app.route("/api/party/games-data")
def party_games_data():
    user_id = str(session.get("user_id", "") or "")
    response = jsonify(results_rewards_payload(user_id))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/party/games")
def party_games():
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))

    enabled_keys = enabled_game_keys()
    if not enabled_keys:
        return redirect(url_for("party_dashboard"))
    user_id = str(session.get("user_id", "") or "")
    if not user_id or not session.get("username"):
        return redirect(url_for("party_login", next=url_for("party_games")))

    requested_key = game_by_slug(request.args.get("game", ""))
    game_key = requested_key if requested_key in enabled_keys else enabled_keys[0]
    game = party_game_state(game_key)
    metadata = GAME_CATALOG[game_key]
    participant = game.get("participants", {}).get(user_id)
    phase = str(game.get("phase", "signup"))
    submissions = []
    if game_key == TWO_TRUTHS_GAME_KEY and participant and phase in {"active", "ended"}:
        own_submission_id = participant.get("submission_id")
        user_guesses = game.get("guesses", {}).get(user_id, {})
        for other in game.get("participants", {}).values():
            submission_id = str(other.get("submission_id", "") or "")
            if not submission_id or submission_id == own_submission_id:
                continue
            statements = participant_statements(other)
            if len(statements) != 3:
                continue
            submissions.append(
                {
                    "submission_id": submission_id,
                    "statements": statements,
                    "saved_guess": user_guesses.get(submission_id, {}).get("guessed_name", ""),
                    "answer_name": other.get("answer_name", "") if phase == "ended" else "",
                    "lie": other.get("lie", "") if phase == "ended" else "",
                }
            )

    prompt_round = prompt_round_for_game(game) if game_key in PROMPT_GAME_KEYS else None
    prompt_responses = []
    saved_response = None
    saved_vote = ""
    if participant and prompt_round:
        player_id = str(participant.get("player_id", ""))
        for response_id, response in prompt_round.get("responses", {}).items():
            response_view = {**response, "is_own": response.get("player_id") == player_id}
            prompt_responses.append(response_view)
            if response_view["is_own"]:
                saved_response = response_view
        saved_vote = str(prompt_round.get("votes", {}).get(player_id, ""))
        random.Random(str(prompt_round.get("id", ""))).shuffle(prompt_responses)

    identity_by_player = {
        str(entry.get("player_id", "")): participant_public_name(
            entry,
            anonymous=bool(game.get("anonymous_mode")),
        )
        for entry in game.get("participants", {}).values()
        if isinstance(entry, dict)
    }

    return render_template(
        "games.html",
        game_key=game_key,
        game_metadata=metadata,
        game_catalog=game_catalog_views(user_id),
        game=game,
        participant=participant,
        submissions=submissions,
        results=game.get("results", {}),
        winners=game_winners(game_key, game),
        prompt_round=prompt_round,
        prompt_responses=prompt_responses,
        saved_response=saved_response,
        saved_vote=saved_vote,
        participant_identity=participant_public_name(
            participant,
            anonymous=bool(game.get("anonymous_mode")),
        ) if participant else "",
        identity_by_player=identity_by_player,
        show_participation_form=request.args.get("participate") == "1",
        success=request.args.get("success", ""),
        error=request.args.get("error", ""),
        statement_max_length=GAME_STATEMENT_MAX_LENGTH,
        response_max_length=GAME_RESPONSE_MAX_LENGTH,
        mmf_actions=MMF_ACTIONS,
        games_data_url=url_for("party_games_data"),
        show_admin_link=False,
    )


@app.route("/party/games/two-truths-and-a-lie/opt-in", methods=["POST"])
def party_game_opt_in():
    game = two_truths_game()
    if not party_day_has_arrived() or not game.get("enabled"):
        return redirect(url_for("party_dashboard"))
    if game.get("phase") != "signup":
        return redirect(url_for("party_games", error="Enrollment has closed because the game has started."))
    if not session.get("user_id") or not session.get("username"):
        return redirect(url_for("party_login", next=url_for("party_games")))
    return redirect(url_for("party_games", participate="1"))


@app.route("/party/games/two-truths-and-a-lie/submission", methods=["POST"])
def party_game_submission():
    game = two_truths_game()
    if not party_day_has_arrived() or not game.get("enabled"):
        return redirect(url_for("party_dashboard"))
    if game.get("phase") != "signup":
        return redirect(url_for("party_games", error="Submissions are locked because the game has started."))
    if not session.get("user_id") or not session.get("username"):
        return redirect(url_for("party_login", next=url_for("party_games")))

    raw_statements = [
        request.form.get("truth_one", ""),
        request.form.get("truth_two", ""),
        request.form.get("lie", ""),
    ]
    if any(len(value.strip()) > GAME_STATEMENT_MAX_LENGTH for value in raw_statements):
        return redirect(url_for("party_games", participate="1", error=f"Each statement must be {GAME_STATEMENT_MAX_LENGTH} characters or fewer."))
    statements = [normalize_statement(value) for value in raw_statements]
    if not all(statements):
        return redirect(url_for("party_games", participate="1", error="Enter two truths and one lie."))
    if len({normalize_guess_name(value) for value in statements}) != 3:
        return redirect(url_for("party_games", participate="1", error="Each statement must be different."))

    user_id = str(session.get("user_id", "") or "")
    answer_name = re.sub(r"\s+", " ", str(session.get("username", "") or "Guest").strip())[:80]
    existing = game.get("participants", {}).get(user_id)
    timestamp = _utc_now_iso()
    display_order = list(existing.get("display_order", [])) if existing else [0, 1, 2]
    if not existing:
        random.shuffle(display_order)
    game["participants"][user_id] = {
        "submission_id": existing.get("submission_id") if existing else uuid4().hex,
        "user_id": user_id,
        "answer_name": answer_name,
        "truths": statements[:2],
        "lie": statements[2],
        "display_order": display_order,
        "created_at": existing.get("created_at", timestamp) if existing else timestamp,
        "updated_at": timestamp,
    }
    broadcast_display_update()
    return redirect(url_for("party_games", success="submission"))


@app.route("/party/games/two-truths-and-a-lie/guesses/<submission_id>", methods=["POST"])
def party_game_guess(submission_id: str):
    game = two_truths_game()
    if not party_day_has_arrived() or not game.get("enabled"):
        return redirect(url_for("party_dashboard"))
    if game.get("phase") != "active":
        return redirect(url_for("party_games", error="Guesses are only open while the game is active."))

    user_id = str(session.get("user_id", "") or "")
    if not user_id or not session.get("username"):
        return redirect(url_for("party_login", next=url_for("party_games")))
    guesser = game.get("participants", {}).get(user_id)
    target = two_truths_participant_by_submission(submission_id)
    if not guesser:
        return redirect(url_for("party_games", error="Only enrolled participants can submit guesses."))
    if not target:
        return redirect(url_for("party_games", error="That mystery submission could not be found."))
    if target.get("user_id") == user_id:
        return redirect(url_for("party_games", error="You cannot guess your own mystery card."))

    guessed_name = re.sub(r"\s+", " ", request.form.get("guessed_name", "").strip())
    if not guessed_name or len(guessed_name) > 80:
        return redirect(url_for("party_games", error="Enter a party-account name up to 80 characters."))
    game.setdefault("guesses", {}).setdefault(user_id, {})[submission_id] = {
        "guessed_name": guessed_name,
        "normalized_name": normalize_guess_name(guessed_name),
        "submitted_at": _utc_now_iso(),
    }
    broadcast_display_update()
    return redirect(url_for("party_games", success="guess"))


@app.route("/party/games/<game_slug>/join", methods=["POST"])
def party_game_join(game_slug: str):
    game_key = game_by_slug(game_slug)
    if not game_key or game_key == TWO_TRUTHS_GAME_KEY:
        return redirect(url_for("party_games"))
    game = party_game_state(game_key)
    if not party_day_has_arrived() or not game.get("enabled"):
        return redirect(url_for("party_dashboard"))
    if game.get("phase") != "signup":
        return redirect(url_for("party_games", game=game_slug, error="Enrollment has closed because the game has started."))
    user_id = str(session.get("user_id", "") or "")
    if not user_id or not session.get("username"):
        return redirect(url_for("party_login", next=url_for("party_games", game=game_slug)))
    display_name = re.sub(r"\s+", " ", str(session.get("username", "") or "").strip())[:80]
    participant = add_alias_participant(
        game,
        user_id,
        display_name=display_name,
    )
    broadcast_display_update()
    return redirect(url_for("party_games", game=game_slug, success="joined"))


@app.route("/party/games/murder-marry-fuck/answers", methods=["POST"])
def party_mmf_answers():
    game = party_game_state(MURDER_MARRY_FUCK_GAME_KEY)
    slug = GAME_CATALOG[MURDER_MARRY_FUCK_GAME_KEY]["slug"]
    if not party_day_has_arrived() or not game.get("enabled"):
        return redirect(url_for("party_dashboard"))
    if game.get("phase") != "active":
        return redirect(url_for("party_games", game=slug, error="Answers are only open while the game is active."))
    user_id = str(session.get("user_id", "") or "")
    participant = game_alias_participant(game, user_id)
    if not participant:
        return redirect(url_for("party_games", game=slug, error="Only enrolled players can submit answers."))
    round_id = str(request.form.get("round_id", "") or "")
    game_round = next((entry for entry in game.get("rounds", []) if entry.get("id") == round_id), None)
    if not game_round:
        return redirect(url_for("party_games", game=slug, error="That round could not be found."))
    valid_person_ids = {str(person.get("id", "")) for person in game_round.get("people", [])}
    answer = {action: str(request.form.get(action, "") or "") for action in MMF_ACTIONS}
    if set(answer.values()) != valid_person_ids or len(set(answer.values())) != 3:
        return redirect(url_for("party_games", game=slug, error="Use Murder, Marry, and F%$@ exactly once in the round."))
    participant.setdefault("answers", {})[round_id] = answer
    participant["updated_at"] = _utc_now_iso()
    broadcast_display_update()
    return redirect(url_for("party_games", game=slug, success="answer", round=round_id))


@app.route("/party/games/<game_slug>/response", methods=["POST"])
def party_prompt_response(game_slug: str):
    game_key = game_by_slug(game_slug)
    if game_key not in PROMPT_GAME_KEYS:
        return redirect(url_for("party_games"))
    game = party_game_state(game_key)
    if not party_day_has_arrived() or not game.get("enabled"):
        return redirect(url_for("party_dashboard"))
    user_id = str(session.get("user_id", "") or "")
    participant = game_alias_participant(game, user_id)
    game_round = prompt_round_for_game(game)
    if game.get("phase") != "active" or not game_round or game_round.get("status") != "submissions":
        return redirect(url_for("party_games", game=game_slug, error="Responses are not open right now."))
    if not participant:
        return redirect(url_for("party_games", game=game_slug, error="Only enrolled players can respond."))
    raw_text = request.form.get("response", "")
    text = normalize_response(raw_text)
    if not text or len(raw_text.strip()) > GAME_RESPONSE_MAX_LENGTH:
        return redirect(url_for("party_games", game=game_slug, error=f"Enter a response up to {GAME_RESPONSE_MAX_LENGTH} characters."))
    player_id = str(participant.get("player_id", ""))
    existing_id = next((response_id for response_id, entry in game_round.get("responses", {}).items() if entry.get("player_id") == player_id), "")
    response_id = existing_id or uuid4().hex
    game_round.setdefault("responses", {})[response_id] = {"id": response_id, "player_id": player_id, "text": text, "submitted_at": _utc_now_iso()}
    participant["updated_at"] = _utc_now_iso()
    broadcast_display_update()
    return redirect(url_for("party_games", game=game_slug, success="response"))


@app.route("/party/games/<game_slug>/vote", methods=["POST"])
def party_prompt_vote(game_slug: str):
    game_key = game_by_slug(game_slug)
    if game_key not in PROMPT_GAME_KEYS:
        return redirect(url_for("party_games"))
    game = party_game_state(game_key)
    user_id = str(session.get("user_id", "") or "")
    participant = game_alias_participant(game, user_id)
    game_round = prompt_round_for_game(game)
    if not party_day_has_arrived() or not game.get("enabled"):
        return redirect(url_for("party_dashboard"))
    if game.get("phase") != "active" or not game_round or game_round.get("status") != "voting":
        return redirect(url_for("party_games", game=game_slug, error="Voting is not open right now."))
    if not participant:
        return redirect(url_for("party_games", game=game_slug, error="Only enrolled players can vote."))
    response_id = str(request.form.get("response_id", "") or "")
    response = game_round.get("responses", {}).get(response_id)
    player_id = str(participant.get("player_id", ""))
    if not response:
        return redirect(url_for("party_games", game=game_slug, error="That response could not be found."))
    if response.get("player_id") == player_id:
        return redirect(url_for("party_games", game=game_slug, error="You cannot vote for your own response."))
    game_round.setdefault("votes", {})[player_id] = response_id
    broadcast_display_update()
    return redirect(url_for("party_games", game=game_slug, success="vote"))


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
    admin_new_karaoke_singer_rows = karaoke_singer_form_rows()
    global live_display_event_override, live_display_notice_override, live_display_notice_queue
    global submitted_costume_votes, costume_ballots, karaoke_state
    global landing_page_target, event_experience_mode, party_code_hash, party_code_hint, party_details, display_settings, display_config, display_runtime, rsvp_notification_email
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

    def dj_song_from_form(existing_song: dict[str, object] | None = None) -> dict[str, object] | None:
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
                "id": str(existing_song.get("id", "") if existing_song else "") or uuid4().hex,
                "title": title,
                "artist": artist,
                "apple_music_id": apple_music_id,
                "album": album,
                "artwork_url": normalized_artwork_url,
                "duration_ms": duration_ms,
                "explicit": request.form.get("explicit") == "yes",
                "enabled": request.form.get("enabled") == "yes",
                "created_at": str(existing_song.get("created_at", "") if existing_song else "") or _utc_now_iso(),
                "source": str(existing_song.get("source", "admin") if existing_song else "admin"),
                "request_id": str(existing_song.get("request_id", "") if existing_song else ""),
                "requester_name": str(existing_song.get("requester_name", "") if existing_song else ""),
                "requested_at": str(existing_song.get("requested_at", "") if existing_song else ""),
                "approved_at": str(existing_song.get("approved_at", "") if existing_song else ""),
                "priority_status": str(existing_song.get("priority_status", "none") if existing_song else "none"),
                "served_at": str(existing_song.get("served_at", "") if existing_song else ""),
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

    def display_custom_card_from_form(
        existing_id: str | None = None,
        existing_created_at: str | None = None,
    ) -> dict[str, object] | None:
        raw_image_url = request.form.get("image_url", "").strip()
        raw_link = request.form.get("link", "").strip()
        image_url = safe_image_url(raw_image_url)
        link = safe_display_link(raw_link)
        primary = request.form.get("primary", "").strip()
        starts_at = normalize_display_form_datetime(request.form.get("starts_at", ""))
        ends_at = normalize_display_form_datetime(request.form.get("ends_at", ""))
        if not primary:
            errors.append("Custom display card headline is required.")
        if raw_image_url and not image_url:
            errors.append("Display card image URL must be http, https, or a /static/ path.")
        if raw_link and not link:
            errors.append("Display card link must be http, https, or an internal path.")
        if request.form.get("starts_at") and not starts_at:
            errors.append("Enter a valid custom card start time.")
        if request.form.get("ends_at") and not ends_at:
            errors.append("Enter a valid custom card end time.")
        if starts_at and ends_at and parse_utc_iso(starts_at) >= parse_utc_iso(ends_at):
            errors.append("Custom card end time must be after its start time.")
        if errors:
            return None
        return normalize_display_custom_card(
            {
                "id": existing_id or uuid4().hex,
                "category": request.form.get("category", "Announcement"),
                "primary": primary,
                "secondary": request.form.get("secondary", ""),
                "tertiary": request.form.get("tertiary", ""),
                "image_url": image_url,
                "link": link,
                "link_label": request.form.get("link_label", ""),
                "enabled": request.form.get("enabled") == "yes",
                "duration_seconds": request.form.get("duration_seconds", "8"),
                "starts_at": starts_at,
                "ends_at": ends_at,
                "created_at": existing_created_at or _utc_now_iso(),
            }
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
            "show_karaoke_singer_card",
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

        generic_game_actions = {
            "simulate_game",
            "enable_game",
            "disable_game",
            "toggle_game_anonymity",
            "start_game",
            "end_game",
            "reset_game",
            "update_mmf_rounds",
            "add_game_prompt",
            "toggle_game_prompt",
            "delete_game_prompt",
            "start_prompt_round",
            "open_prompt_voting",
            "reveal_prompt_round",
            "start_game_presentation",
            "previous_game_slide",
            "next_game_slide",
            "show_game_winner",
            "show_game_results",
        }

        display_actions = {
            "update_display_layout",
            "move_display_source_up",
            "move_display_source_down",
            "add_display_card",
            "update_display_card",
            "delete_display_card",
            "move_display_card_up",
            "move_display_card_down",
            "pause_display_rotation",
            "resume_display_rotation",
            "previous_display_card",
            "next_display_card",
            "pin_display_entry",
            "pin_display_card",
            "clear_display_pin",
            "pin_display_game",
            "clear_display_game_pin",
            "dismiss_display_notice",
            "toggle_game_result_card",
            "show_game_result_card",
        }

        recognition_actions = {
            "publish_result_archive",
            "add_event_edition",
            "add_recognition_credit",
            "revoke_recognition_credit",
            "link_recognition_credit",
        }

        if action in recognition_actions:
            if action == "publish_result_archive":
                archive_id = str(request.form.get("archive_id", "") or "")
                archive = next((entry for entry in result_archives if entry.get("id") == archive_id), None)
                if not archive:
                    errors.append("That result archive could not be found.")
                elif archive.get("status") == "official":
                    messages.append("That result is already official.")
                else:
                    try:
                        write_state_backup_if_available("publish-official-result")
                        award_count = publish_result_archive(archive)
                    except ValueError as exc:
                        errors.append(str(exc))
                    else:
                        messages.append(
                            f"Published {archive.get('title', 'result')} as official history and granted {award_count} winner credit{'s' if award_count != 1 else ''}."
                        )
                        should_broadcast = True

            elif action == "add_event_edition":
                year = re.sub(r"[^0-9]", "", request.form.get("year", ""))[:4]
                title = request.form.get("title", "").strip()[:160]
                date_label = request.form.get("date", "").strip()[:80]
                if len(year) != 4:
                    errors.append("Enter a four-digit event year.")
                else:
                    event_id = event_id_for_year(year)
                    event_editions[event_id] = {
                        "id": event_id,
                        "year": year,
                        "title": title or f"Halloween Party {year}",
                        "date": date_label,
                    }
                    messages.append(f"Saved the {year} Halloween edition.")
                    should_broadcast = True

            elif action == "add_recognition_credit":
                kind = str(request.form.get("kind", "") or "")
                account_id = str(request.form.get("account_id", "") or "")
                account_name = account_name_by_id(account_id)
                recipient_name = account_name or request.form.get("recipient_name", "").strip()[:80]
                public_identity = request.form.get("public_identity", "").strip()[:80] or recipient_name
                event_id = str(request.form.get("event_id", "") or "")
                edition = event_editions.get(event_id, {})
                subject_key = request.form.get("subject_key", "").strip()[:100]
                subject_label = request.form.get("subject_label", "").strip()[:160]
                achievement_key = request.form.get("achievement_key", "").strip()[:100]
                if kind not in CREDIT_KINDS:
                    errors.append("Select a valid recognition type.")
                elif account_id and not account_name:
                    errors.append("Select a valid party account.")
                elif not recipient_name:
                    errors.append("Select an account or enter a legacy recipient name.")
                elif kind == "attendance" and not account_id:
                    errors.append("Attendance credits must be linked to a party account.")
                elif kind == "custom" and achievement_key not in ACHIEVEMENT_CATALOG:
                    errors.append("Select a valid custom achievement.")
                elif kind != "custom" and event_id not in event_editions:
                    errors.append("Select the Halloween edition for this credit.")
                elif kind == "attendance" and credit_exists(
                    recognition_credits,
                    kind=kind,
                    account_id=account_id,
                    event_id=event_id,
                ):
                    errors.append("That attendee already has credit for this Halloween edition.")
                else:
                    recognition_credits.append(
                        new_credit(
                            kind=kind,
                            account_id=account_id,
                            recipient_name=recipient_name,
                            public_identity=public_identity,
                            event_id=event_id,
                            year=str(edition.get("year", "")),
                            subject_key=subject_key,
                            subject_label=subject_label,
                            achievement_key=achievement_key,
                            note=request.form.get("note", ""),
                        )
                    )
                    messages.append(f"Added recognition credit for {recipient_name}.")
                    should_broadcast = True

            elif action == "revoke_recognition_credit":
                credit_id = str(request.form.get("credit_id", "") or "")
                credit = next((entry for entry in recognition_credits if entry.get("id") == credit_id), None)
                if not credit:
                    errors.append("That recognition credit could not be found.")
                elif credit.get("revoked_at"):
                    messages.append("That recognition credit is already revoked.")
                else:
                    credit["revoked_at"] = _utc_now_iso()
                    credit["revoked_reason"] = request.form.get("reason", "").strip()[:500]
                    messages.append(f"Revoked the recognition credit for {credit.get('recipient_name', 'guest')}.")
                    should_broadcast = True

            elif action == "link_recognition_credit":
                credit_id = str(request.form.get("credit_id", "") or "")
                account_id = str(request.form.get("account_id", "") or "")
                credit = next((entry for entry in recognition_credits if entry.get("id") == credit_id), None)
                account_name = account_name_by_id(account_id)
                if not credit:
                    errors.append("That recognition credit could not be found.")
                elif not account_name:
                    errors.append("Select a valid party account.")
                elif credit_exists(
                    recognition_credits,
                    kind=str(credit.get("kind", "")),
                    account_id=account_id,
                    event_id=str(credit.get("event_id", "")),
                    subject_key=str(credit.get("subject_key", "")),
                    source_ref=str(credit.get("source_ref", "")),
                ):
                    errors.append("That account already has this recognition credit.")
                else:
                    credit["account_id"] = account_id
                    credit["recipient_name"] = account_name
                    messages.append(f"Linked the recognition credit to {account_name}.")
                    should_broadcast = True

        elif action in display_actions:
            if action == "update_display_layout":
                enabled_sources = set(request.form.getlist("source_enabled"))
                requested = {
                    **display_config,
                    "source_enabled": {
                        source: source in enabled_sources for source in DISPLAY_SOURCE_KEYS
                    },
                    "center_interval_seconds": request.form.get("center_interval_seconds", "8"),
                    "game_interval_seconds": request.form.get("game_interval_seconds", "10"),
                    "game_mode": request.form.get("game_mode", "auto"),
                    "bar_mode": request.form.get("bar_mode", "auto"),
                    "music_mode": request.form.get("music_mode", "auto"),
                    "max_bar_orders": request.form.get("max_bar_orders", "4"),
                    "notice_duration_seconds": request.form.get("notice_duration_seconds", "10"),
                    "density": request.form.get("density", "standard"),
                }
                display_config = normalize_display_config(requested)
                messages.append("Live display layout settings updated.")
                should_broadcast = True

            elif action in {"move_display_source_up", "move_display_source_down"}:
                source = str(request.form.get("source", "") or "")
                order = list(display_config.get("source_order", DISPLAY_SOURCE_KEYS))
                if source not in order:
                    errors.append("That display source could not be found.")
                else:
                    index = order.index(source)
                    target = index + (-1 if action.endswith("_up") else 1)
                    if 0 <= target < len(order):
                        order[index], order[target] = order[target], order[index]
                        display_config["source_order"] = order
                        display_runtime["center_revision"] = int(display_runtime.get("center_revision", 0) or 0) + 1
                        messages.append(f"Moved {DISPLAY_SOURCE_LABELS[source]} in the display rotation.")
                        should_broadcast = True

            elif action == "add_display_card":
                card = display_custom_card_from_form()
                if card:
                    display_custom_cards.append(card)
                    messages.append(f"Added custom display card: {card['primary']}.")
                    should_broadcast = True

            elif action in {"update_display_card", "delete_display_card", "move_display_card_up", "move_display_card_down", "pin_display_card"}:
                card_id = str(request.form.get("card_id", "") or "")
                card_index = next(
                    (index for index, card in enumerate(display_custom_cards) if str(card.get("id", "")) == card_id),
                    None,
                )
                if card_index is None:
                    errors.append("That custom display card could not be found.")
                elif action == "update_display_card":
                    existing = display_custom_cards[card_index]
                    card = display_custom_card_from_form(card_id, str(existing.get("created_at", "") or ""))
                    if card:
                        display_custom_cards[card_index] = card
                        messages.append(f"Updated custom display card: {card['primary']}.")
                        should_broadcast = True
                elif action == "delete_display_card":
                    removed = display_custom_cards.pop(card_index)
                    if display_runtime.get("pinned_card_id") == f"custom:{card_id}":
                        display_runtime["pinned_card_id"] = ""
                    messages.append(f"Removed custom display card: {removed.get('primary', 'Announcement')}.")
                    should_broadcast = True
                elif action in {"move_display_card_up", "move_display_card_down"}:
                    target = card_index + (-1 if action.endswith("_up") else 1)
                    if 0 <= target < len(display_custom_cards):
                        display_custom_cards[card_index], display_custom_cards[target] = display_custom_cards[target], display_custom_cards[card_index]
                        messages.append("Moved the custom display card.")
                        should_broadcast = True
                else:
                    display_runtime["pinned_card_id"] = f"custom:{card_id}"
                    display_runtime["center_paused"] = True
                    display_runtime["center_revision"] = int(display_runtime.get("center_revision", 0) or 0) + 1
                    messages.append("Pinned the custom card to center stage.")
                    should_broadcast = True

            elif action == "pin_display_entry":
                entry_id = str(request.form.get("entry_id", "") or "")
                entries = build_rotation_entries()
                entry = next((item for item in entries if str(item.get("id", "")) == entry_id), None)
                if entry is None:
                    errors.append("That center-stage card is no longer available.")
                else:
                    display_runtime["pinned_card_id"] = entry_id
                    display_runtime["center_paused"] = True
                    display_runtime["center_revision"] = int(display_runtime.get("center_revision", 0) or 0) + 1
                    messages.append(f"Pinned {entry.get('primary', 'the selected card')} to center stage.")
                    should_broadcast = True

            elif action in {"toggle_game_result_card", "show_game_result_card"}:
                card_id = str(request.form.get("card_id", "") or "")
                available_cards = generated_game_result_entries(include_hidden=True)
                card = next((entry for entry in available_cards if entry.get("id") == card_id), None)
                if card is None:
                    errors.append("That generated game result card is no longer available.")
                else:
                    configured = display_config.setdefault("game_result_card_enabled", {})
                    if action == "toggle_game_result_card":
                        included = game_result_card_is_enabled(card_id)
                        configured[card_id] = not included
                        if included and display_runtime.get("pinned_card_id") == card_id:
                            display_runtime["pinned_card_id"] = ""
                            display_runtime["center_paused"] = False
                        messages.append(
                            f"{'Included' if not included else 'Hidden'} {card.get('game_title', 'game')} "
                            f"{str(card.get('card_type', 'result')).lower()} card."
                        )
                    else:
                        configured[card_id] = True
                        display_config.setdefault("source_enabled", {})["games"] = True
                        display_runtime["pinned_card_id"] = card_id
                        display_runtime["center_paused"] = True
                        messages.append(f"Pinned {card.get('primary', 'the game result')} to center stage.")
                    display_runtime["center_revision"] = int(display_runtime.get("center_revision", 0) or 0) + 1
                    should_broadcast = True

            elif action in {"pause_display_rotation", "resume_display_rotation", "previous_display_card", "next_display_card", "clear_display_pin"}:
                entries = build_rotation_entries()
                current_index = int(display_runtime.get("center_index", 0) or 0)
                if action == "pause_display_rotation":
                    display_runtime["center_paused"] = True
                    messages.append("Center-stage rotation paused.")
                elif action == "resume_display_rotation":
                    display_runtime["center_paused"] = False
                    display_runtime["pinned_card_id"] = ""
                    live_display_event_override = None
                    messages.append("Center-stage automatic rotation resumed.")
                elif action == "clear_display_pin":
                    display_runtime["pinned_card_id"] = ""
                    display_runtime["center_paused"] = False
                    messages.append("Center-stage pin cleared.")
                elif entries:
                    delta = -1 if action == "previous_display_card" else 1
                    display_runtime["center_index"] = (current_index + delta) % len(entries)
                    display_runtime["center_paused"] = True
                    display_runtime["pinned_card_id"] = ""
                    messages.append("Moved center stage to the previous card." if delta < 0 else "Moved center stage to the next card.")
                display_runtime["center_revision"] = int(display_runtime.get("center_revision", 0) or 0) + 1
                should_broadcast = True

            elif action == "pin_display_game":
                game_key = str(request.form.get("game_key", "") or "")
                if game_key not in GAME_CATALOG or not party_game_state(game_key).get("enabled"):
                    errors.append("Choose an enabled game to pin on the left stage.")
                else:
                    display_config["game_mode"] = "always"
                    display_config["pinned_game_key"] = game_key
                    messages.append(f"Pinned {GAME_CATALOG[game_key]['title']} on the left stage.")
                    should_broadcast = True

            elif action == "clear_display_game_pin":
                display_config["pinned_game_key"] = ""
                display_config["game_mode"] = "auto"
                messages.append("Left-stage automatic game rotation resumed.")
                should_broadcast = True

            elif action == "dismiss_display_notice":
                activate_next_display_notice()
                messages.append("Dismissed the current drink-ready notice.")
                should_broadcast = True

        elif action in generic_game_actions:
            game_key = str(request.form.get("game_key", "") or "")
            if game_key not in GAME_CATALOG:
                errors.append("Select a valid party game.")
            else:
                game = party_game_state(game_key)
                metadata = GAME_CATALOG[game_key]
                title = metadata["title"]

                if action == "simulate_game":
                    participants = game.get("participants", {}) if isinstance(game.get("participants"), dict) else {}
                    simulation = game.get("simulation", {})
                    is_simulated = bool(isinstance(simulation, dict) and simulation.get("is_simulated"))
                    if participants and not is_simulated:
                        errors.append(f"Reset {title} before replacing real participant data with a simulation.")
                    else:
                        player_count = _bounded_int(request.form.get("player_count"), 8, 2, 20)
                        write_state_backup_if_available(f"game-{game_key}-simulation")
                        games_state[game_key] = build_simulated_game_state(
                            game_key,
                            game,
                            player_count=player_count,
                            generated_at=_utc_now_iso(),
                        )
                        upsert_game_result_archive(game_key)
                        card_settings = display_config.setdefault("game_result_card_enabled", {})
                        card_settings[f"games:{game_key}-winner"] = True
                        card_settings[f"games:{game_key}-scores"] = True
                        display_config.setdefault("source_enabled", {})["games"] = True
                        if live_display_event_override and str(live_display_event_override.get("type", "")).startswith("game_"):
                            live_display_event_override = None
                        messages.append(f"Simulated {title} with {player_count} test players and finalized its results.")
                        should_broadcast = True

                elif action == "enable_game":
                    game["enabled"] = True
                    messages.append(f"{title} is enabled for attendees.")
                    should_broadcast = True

                elif action == "disable_game":
                    game["enabled"] = False
                    if live_display_event_override and str(live_display_event_override.get("type", "")).startswith("game_"):
                        live_display_event_override = None
                    messages.append(f"{title} is hidden from attendees. Existing data was preserved.")
                    should_broadcast = True

                elif action == "toggle_game_anonymity":
                    if game_key == TWO_TRUTHS_GAME_KEY:
                        errors.append("Two Truths and a Lie must use account names for identity guesses.")
                    elif game.get("phase") != "signup":
                        errors.append("Player anonymity can only be changed while enrollment is open.")
                    else:
                        game["anonymous_mode"] = not bool(game.get("anonymous_mode"))
                        mode_label = "anonymous aliases" if game["anonymous_mode"] else "signed-in names"
                        messages.append(f"{title} will use {mode_label} for every player.")
                        should_broadcast = True

                elif action == "start_game":
                    participant_count = len(game.get("participants", {}))
                    if game_key == TWO_TRUTHS_GAME_KEY:
                        errors.append("Use the existing Two Truths start control.")
                    elif not game.get("enabled"):
                        errors.append(f"Enable {title} before starting it.")
                    elif game.get("phase") != "signup":
                        errors.append(f"{title} can only start from enrollment.")
                    elif participant_count < 1:
                        errors.append(f"At least one participant must join {title} before it starts.")
                    elif game_key == MURDER_MARRY_FUCK_GAME_KEY and len(game.get("rounds", [])) != MMF_ROUND_COUNT:
                        errors.append(f"Configure exactly {MMF_ROUND_COUNT} complete rounds before starting {title}.")
                    else:
                        game["phase"] = "active"
                        game["started_at"] = _utc_now_iso()
                        game["ended_at"] = ""
                        game["presentation"] = {"active": False, "slide_index": 0}
                        if game_key == MURDER_MARRY_FUCK_GAME_KEY:
                            game["results"] = copy.deepcopy(empty_mmf_game_state()["results"])
                        else:
                            game["results"] = copy.deepcopy(empty_prompt_game_state(game_key)["results"])
                        write_state_backup_if_available(f"game-{game_key}-start")
                        messages.append(f"{title} started with {participant_count} players.")
                        should_broadcast = True

                elif action == "end_game":
                    if game_key == TWO_TRUTHS_GAME_KEY:
                        errors.append("Use the existing Two Truths end control.")
                    elif game.get("phase") != "active":
                        errors.append(f"Start {title} before ending it.")
                    elif game_key in PROMPT_GAME_KEYS and prompt_round_for_game(game) and prompt_round_for_game(game).get("status") != "revealed":
                        errors.append("Reveal the current prompt round before ending the game.")
                    elif game_key in PROMPT_GAME_KEYS and not any(entry.get("status") == "revealed" for entry in game.get("rounds", [])):
                        errors.append("Reveal at least one prompt round before ending the game.")
                    else:
                        finalized_at = _utc_now_iso()
                        game["phase"] = "ended"
                        game["ended_at"] = finalized_at
                        game["results"] = calculate_mmf_results(game, finalized_at=finalized_at) if game_key == MURDER_MARRY_FUCK_GAME_KEY else calculate_prompt_results(game, finalized_at=finalized_at)
                        upsert_game_result_archive(game_key)
                        write_state_backup_if_available(f"game-{game_key}-ended")
                        messages.append(f"{title} ended and its scores were finalized.")
                        should_broadcast = True

                elif action == "reset_game":
                    expected = "RESET TWO TRUTHS AND A LIE" if game_key == TWO_TRUTHS_GAME_KEY else ("RESET MURDER MARRY FUCK" if game_key == MURDER_MARRY_FUCK_GAME_KEY else f"RESET {metadata['short_title'].upper()}")
                    if request.form.get("confirmation", "").strip() != expected:
                        errors.append(f"Enter the exact reset phrase: {expected}")
                    else:
                        enabled = bool(game.get("enabled"))
                        write_state_backup_if_available(f"game-{game_key}-reset")
                        if game_key == TWO_TRUTHS_GAME_KEY:
                            games_state[game_key] = empty_two_truths_game_state(enabled=enabled)
                        elif game_key == MURDER_MARRY_FUCK_GAME_KEY:
                            games_state[game_key] = empty_mmf_game_state(enabled=enabled)
                        else:
                            games_state[game_key] = empty_prompt_game_state(game_key, enabled=enabled)
                        if live_display_event_override and str(live_display_event_override.get("type", "")).startswith("game_"):
                            live_display_event_override = None
                        messages.append(f"{title} was reset. Configuration defaults were restored and play data was cleared.")
                        should_broadcast = True

                elif action == "update_mmf_rounds":
                    if game_key != MURDER_MARRY_FUCK_GAME_KEY:
                        errors.append("That configuration form does not belong to this game.")
                    elif game.get("phase") != "signup":
                        errors.append("Murder, Marry, F%$@ rounds can only be edited during enrollment.")
                    else:
                        rounds = []
                        for round_index in range(MMF_ROUND_COUNT):
                            people = []
                            for person_index in range(3):
                                prefix = f"round_{round_index}_person_{person_index}"
                                name = re.sub(r"\s+", " ", request.form.get(f"{prefix}_name", "").strip())[:80]
                                raw_image_url = request.form.get(f"{prefix}_image_url", "").strip()
                                image_url = safe_image_url(raw_image_url)
                                if not name:
                                    errors.append(f"Round {round_index + 1}, person {person_index + 1} needs a name.")
                                if raw_image_url and not image_url:
                                    errors.append(f"Round {round_index + 1}, person {person_index + 1} has an invalid image URL.")
                                person_id = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:70] or uuid4().hex
                                people.append({"id": person_id, "name": name, "image_url": image_url})
                            if len({entry["id"] for entry in people}) != 3:
                                errors.append(f"Round {round_index + 1} must contain three different people.")
                            rounds.append({"id": f"mmf-{round_index + 1:02d}", "people": people})
                        explicit_label = request.form.get("explicit_label", "F%$@").strip()[:24] or "F%$@"
                        if not errors:
                            game["rounds"] = rounds
                            game["explicit_label"] = explicit_label
                            messages.append("Saved all ten Murder, Marry, F%$@ rounds.")
                            should_broadcast = True

                elif action == "add_game_prompt":
                    if game_key not in PROMPT_GAME_KEYS:
                        errors.append("Prompts are only available for response-and-voting games.")
                    elif game.get("phase") != "signup":
                        errors.append("Prompt decks can only be edited during enrollment.")
                    else:
                        raw_prompt = request.form.get("prompt_text", "")
                        prompt_text = normalize_prompt(raw_prompt)
                        if not prompt_text or len(raw_prompt.strip()) > GAME_PROMPT_MAX_LENGTH:
                            errors.append(f"Enter a prompt up to {GAME_PROMPT_MAX_LENGTH} characters.")
                        elif game_key == FILL_BLANK_GAME_KEY and "___" not in prompt_text:
                            errors.append("Fill in the Blank prompts must include ___.")
                        else:
                            game.setdefault("prompts", []).append({"id": uuid4().hex, "text": prompt_text, "enabled": True})
                            messages.append(f"Added a prompt to {title}.")
                            should_broadcast = True

                elif action in {"toggle_game_prompt", "delete_game_prompt"}:
                    prompt_id = str(request.form.get("prompt_id", "") or "")
                    prompt = next((entry for entry in game.get("prompts", []) if entry.get("id") == prompt_id), None)
                    if game_key not in PROMPT_GAME_KEYS or not prompt:
                        errors.append("That game prompt could not be found.")
                    elif game.get("phase") != "signup":
                        errors.append("Prompt decks can only be edited during enrollment.")
                    elif action == "toggle_game_prompt":
                        prompt["enabled"] = not bool(prompt.get("enabled"))
                        messages.append(f"Updated the prompt in {title}.")
                        should_broadcast = True
                    else:
                        game["prompts"] = [entry for entry in game.get("prompts", []) if entry.get("id") != prompt_id]
                        messages.append(f"Removed the prompt from {title}.")
                        should_broadcast = True

                elif action == "start_prompt_round":
                    prompt_id = str(request.form.get("prompt_id", "") or "")
                    prompt = next((entry for entry in game.get("prompts", []) if entry.get("id") == prompt_id and entry.get("enabled")), None)
                    current_round = prompt_round_for_game(game)
                    if game_key not in PROMPT_GAME_KEYS or game.get("phase") != "active":
                        errors.append("Start the prompt game before opening a round.")
                    elif current_round and current_round.get("status") != "revealed":
                        errors.append("Reveal the current round before starting another.")
                    elif not prompt:
                        errors.append("Select an enabled prompt.")
                    else:
                        round_id = uuid4().hex
                        game_round = {"id": round_id, "prompt_id": prompt_id, "prompt_text": prompt["text"], "status": "submissions", "responses": {}, "votes": {}, "results": {"vote_counts": {}, "winner_response_ids": [], "vote_count": 0}, "created_at": _utc_now_iso(), "revealed_at": ""}
                        game.setdefault("rounds", []).append(game_round)
                        game["current_round_id"] = round_id
                        messages.append(f"Opened a new {title} response round.")
                        should_broadcast = True

                elif action == "open_prompt_voting":
                    current_round = prompt_round_for_game(game)
                    if not current_round or current_round.get("status") != "submissions":
                        errors.append("There is no response round ready for voting.")
                    elif not current_round.get("responses"):
                        errors.append("At least one response is required before continuing.")
                    elif len(current_round.get("responses", {})) == 1:
                        current_round["status"] = "revealed"
                        current_round["revealed_at"] = _utc_now_iso()
                        current_round["results"] = finalize_prompt_round(current_round)
                        messages.append(f"Revealed the solo {title} spotlight and awarded one point.")
                        should_broadcast = True
                    else:
                        current_round["status"] = "voting"
                        messages.append(f"Voting is now open for {title}.")
                        should_broadcast = True

                elif action == "reveal_prompt_round":
                    current_round = prompt_round_for_game(game)
                    if not current_round or current_round.get("status") != "voting":
                        errors.append("Open voting before revealing this round.")
                    elif not current_round.get("votes"):
                        errors.append("At least one vote is required before revealing the round.")
                    else:
                        current_round["status"] = "revealed"
                        current_round["revealed_at"] = _utc_now_iso()
                        current_round["results"] = finalize_prompt_round(current_round)
                        messages.append(f"Revealed the current {title} round.")
                        should_broadcast = True

                elif action in {"start_game_presentation", "previous_game_slide", "next_game_slide"}:
                    if game.get("phase") != "ended":
                        errors.append("End the game before starting its result presentation.")
                    else:
                        current_index = int(game.get("presentation", {}).get("slide_index", 0) or 0)
                        requested_index = 0 if action == "start_game_presentation" else current_index + (-1 if action == "previous_game_slide" else 1)
                        if set_game_presentation_slide(game_key, requested_index):
                            messages.append(f"Showing {title} result slide {game['presentation']['slide_index'] + 1}.")
                            should_broadcast = True
                        else:
                            errors.append("No presentation slides are available for this game.")

                elif action == "show_game_winner":
                    winner = game_winner_entry(game_key)
                    if game.get("phase") != "ended":
                        errors.append("End the game before showing its winner.")
                    elif not winner:
                        errors.append("This game does not have a positive-score winner.")
                    else:
                        live_display_event_override = {"type": "game_winner", "title": winner["category"], "highlight": winner["primary"], "message": winner["secondary"], "details": [winner["tertiary"]], "image_url": game_art_url(game_key, winner=True), "media_treatment": "background"}
                        messages.append(f"Live display paused on the {title} winner.")
                        should_broadcast = True

                elif action == "show_game_results":
                    scoreboard = game_scoreboard_entry(game_key)
                    if game.get("phase") != "ended":
                        errors.append("End the game before showing final results.")
                    elif not scoreboard:
                        errors.append("No final scores are available.")
                    else:
                        live_display_event_override = {"type": "game_results", "title": f"{title} Results", "highlight": scoreboard["secondary"], "message": "Final standings", "details": [f"#{row['rank']} {row['name']}: {row['value_label']}" for row in scoreboard["scoreboard"]["entries"]], "image_url": game_art_url(game_key), "media_treatment": "background"}
                        messages.append(f"Live display paused on the {title} results.")
                        should_broadcast = True

        elif action == "set_role_preview":
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
                    approved_at = _utc_now_iso()
                    existing_song = find_dj_song_by_apple_music_id(
                        str(requested_song.get("apple_music_id", "") if isinstance(requested_song, dict) else "")
                    )
                    priority_metadata = {
                        "source": "attendee_request",
                        "request_id": str(request_entry.get("id", "") or ""),
                        "requester_name": str(request_entry.get("requester_name", "") or "")[:80],
                        "requested_at": str(request_entry.get("requested_at", "") or approved_at),
                        "approved_at": approved_at,
                        "priority_status": "pending",
                        "served_at": "",
                        "enabled": True,
                    }
                    if existing_song:
                        existing_song.update(priority_metadata)
                        playlist_song = normalize_dj_song(existing_song)
                        if playlist_song:
                            existing_index = dj_playlist.index(existing_song)
                            dj_playlist[existing_index] = playlist_song
                    else:
                        playlist_song = normalize_dj_song(
                            {
                                **requested_song,
                                "id": uuid4().hex,
                                "created_at": approved_at,
                                **priority_metadata,
                            }
                        )
                    if playlist_song is None:
                        errors.append("Song request could not be converted into a playlist entry.")
                        dj_song_requests.insert(request_index, request_entry)
                    else:
                        if not existing_song:
                            dj_playlist.append(playlist_song)
                        mark_dj_priority_sync_needed()
                        sync_command = maybe_queue_dj_priority_sync_command(requested_by="Approved attendee request")
                        if sync_command:
                            messages.append(
                                f"Approved {playlist_song['title']} and sent it to MusicKit as the next priority request."
                            )
                        elif dj_state.get("receiver", {}).get("current_song_id"):
                            messages.append(
                                f"Approved {playlist_song['title']}. Its priority queue update will run when the receiver is ready."
                            )
                        else:
                            messages.append(
                                f"Approved {playlist_song['title']}. It will lead the next Play or Shuffle queue."
                            )
                        should_broadcast = True
                else:
                    request_song = requested_song if isinstance(requested_song, dict) else {}
                    messages.append(f"Rejected {request_song.get('title', 'the song')} request from {request_entry.get('requester_name', 'a guest')}.")
                    should_broadcast = True

        elif action in {"prioritize_dj_song", "clear_dj_song_priority", "retry_dj_priority_sync"}:
            if action == "retry_dj_priority_sync":
                if not bool(dj_state.get("priority_sync_pending", False)):
                    messages.append("The MusicKit priority queue is already synchronized.")
                else:
                    priority_revision = int(dj_state.get("priority_revision", 0) or 0)
                    dj_state["priority_sync_attempted_revision"] = max(0, priority_revision - 1)
                    dj_state["priority_sync_error"] = ""
                    command = maybe_queue_dj_priority_sync_command(requested_by="Admin retry")
                    messages.append(
                        "Priority queue retry sent to MusicKit."
                        if command
                        else "Priority queue retry saved and will run when the receiver is ready."
                    )
                    should_broadcast = True
            else:
                song_id = request.form.get("song_id", "").strip()
                song = find_dj_song(song_id)
                if not song:
                    errors.append("DJ song could not be found.")
                elif action == "prioritize_dj_song":
                    now = _utc_now_iso()
                    song["source"] = song.get("source") if song.get("source") == "attendee_request" else "admin_priority"
                    song["requester_name"] = str(song.get("requester_name", "") or "Admin priority")
                    song["requested_at"] = str(song.get("requested_at", "") or now)
                    song["approved_at"] = now
                    song["priority_status"] = "pending"
                    song["served_at"] = ""
                    song["enabled"] = True
                    mark_dj_priority_sync_needed()
                    command = maybe_queue_dj_priority_sync_command(requested_by="Admin priority")
                    messages.append(
                        f"Prioritized {song['title']} and sent its queue update to MusicKit."
                        if command
                        else f"Prioritized {song['title']}; it will synchronize when the receiver is ready."
                    )
                    should_broadcast = True
                else:
                    song["priority_status"] = "served"
                    song["served_at"] = _utc_now_iso()
                    mark_dj_priority_sync_needed()
                    command = maybe_queue_dj_priority_sync_command(requested_by="Admin priority removal")
                    messages.append(
                        f"Removed priority from {song['title']} and sent the updated queue to MusicKit."
                        if command
                        else f"Removed priority from {song['title']}; the queue will reconcile when the receiver is ready."
                    )
                    should_broadcast = True

        elif action == "update_dj_song":
            song_id = request.form.get("song_id", "").strip()
            song_index = next((index for index, song in enumerate(dj_playlist) if song.get("id") == song_id), None)
            if song_index is None:
                errors.append("DJ song could not be found.")
            else:
                existing_song = dj_playlist[song_index]
                updated_song = dj_song_from_form(existing_song=existing_song)
                if updated_song:
                    dj_playlist[song_index] = updated_song
                    queue_affecting_change = any(
                        existing_song.get(field) != updated_song.get(field)
                        for field in ("apple_music_id", "enabled", "priority_status")
                    )
                    if queue_affecting_change and dj_state.get("receiver", {}).get("current_song_id"):
                        mark_dj_priority_sync_needed()
                        maybe_queue_dj_priority_sync_command(requested_by="Admin playlist update")
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
                elif song_id in dj_state.get("receiver", {}).get("queue_order", []):
                    mark_dj_priority_sync_needed()
                    maybe_queue_dj_priority_sync_command(requested_by="Admin playlist deletion")
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
            if not dj_receiver_is_ready():
                errors.append("Connect the live display, authorize Apple Music, and enable DJ audio before using playback controls.")
                command = None
            elif isinstance(dj_state.get("current_command"), dict):
                errors.append("Wait for the live display to confirm the pending DJ command before sending another one.")
                command = None
            else:
                command = queue_dj_command(action_map[action], request.form.get("song_id", "").strip(), requested_by="Admin")
            if command:
                messages.append("DJ command sent to the live display. Waiting for receiver confirmation.")
                should_broadcast = True
            elif not errors:
                errors.append("Add and enable at least one valid DJ song before sending this command.")

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
            account_id = str(request.form.get("account_id", "") or "")

            if not name:
                errors.append("Costume signup name is required.")
            if not costume:
                errors.append("Costume description is required.")
            if account_id and not account_name_by_id(account_id):
                errors.append("Select a valid party account for the costume entry.")

            if index is not None and name and costume and not errors:
                costume_signups[index] = CostumeSignup(
                    id=costume_signups[index].id,
                    name=name,
                    costume=costume,
                    contact=contact,
                    account_id=account_id,
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
                unlinked_credits = 0
                for credit in recognition_credits:
                    if str(credit.get("account_id", "")) != account_id:
                        continue
                    credit["account_id"] = ""
                    credit["recipient_name"] = str(
                        credit.get("recipient_name", "") or account.get("username", "Guest")
                    )[:80]
                    unlinked_credits += 1
                for archive in result_archives:
                    for winner_link in archive.get("winner_links", []):
                        if isinstance(winner_link, dict) and str(winner_link.get("account_id", "")) == account_id:
                            winner_link["account_id"] = ""
                for signup in costume_signups:
                    if signup.account_id == account_id:
                        signup.account_id = ""
                registered_users.pop(account_id, None)
                submitted_costume_votes.discard(account_id)
                costume_ballots.pop(account_id, None)
                for token_hash, record in list(password_reset_tokens.items()):
                    if (
                        str(record.get("account_id", "")) == account_id
                        or normalize_username(str(record.get("normalized_username", ""))) == account_key
                    ):
                        password_reset_tokens.pop(token_hash, None)
                history_note = (
                    f" Historical recognition preserved and unlinked ({unlinked_credits})."
                    if unlinked_credits
                    else ""
                )
                messages.append(f"Deleted account for {account.get('username')}.{history_note}")

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
            account_id = str(request.form.get("account_id", "") or "")

            if not name:
                errors.append("Costume signup name is required to add a new entry.")
            if not costume:
                errors.append("Costume description is required to add a new entry.")
            if account_id and not account_name_by_id(account_id):
                errors.append("Select a valid party account for the costume entry.")

            if name and costume and not errors and not block_if_voting_locked("Adding costume signups"):
                costume_signups.append(
                    CostumeSignup(
                        id=uuid4().hex,
                        name=name,
                        costume=costume,
                        contact=contact,
                        account_id=account_id,
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
            singers, singer_rows, singer_errors = parse_karaoke_singers_from_form()
            song_title = request.form.get("song_title", "").strip()
            artist = request.form.get("artist", "").strip()
            youtube_link = request.form.get("youtube_link", "").strip()

            errors.extend(singer_errors)
            if not song_title:
                errors.append("Song title is required.")
            if not artist:
                errors.append("Artist is required.")

            if index is not None and singers and song_title and artist and not singer_errors:
                existing_signup = karaoke_signups[index]
                existing_signup.singers = singers
                existing_signup.name = karaoke_singer_label(singers)
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
                messages.append(f"Updated karaoke signup for {existing_signup.singer_label}.")
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
            singers, singer_rows, singer_errors = parse_karaoke_singers_from_form()
            admin_new_karaoke_singer_rows = singer_rows
            song_title = request.form.get("song_title", "").strip()
            artist = request.form.get("artist", "").strip()
            youtube_link = request.form.get("youtube_link", "").strip()

            errors.extend(singer_errors)
            if not song_title:
                errors.append("Song title is required to add a new entry.")
            if not artist:
                errors.append("Artist is required to add a new entry.")

            if singers and song_title and artist and not singer_errors:
                singer_label = karaoke_singer_label(singers)
                karaoke_signups.append(
                    KaraokeSignup(
                        id=uuid4().hex,
                        name=singer_label,
                        song_title=song_title,
                        artist=artist,
                        youtube_link=youtube_link,
                        singers=singers,
                    )
                )
                messages.append(f"Added karaoke signup for {singer_label}.")
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

        elif action == "enable_two_truths_game":
            game = two_truths_game()
            game["enabled"] = True
            messages.append("Two Truths and a Lie enrollment is enabled.")
            should_broadcast = True

        elif action == "disable_two_truths_game":
            game = two_truths_game()
            game["enabled"] = False
            if live_display_event_override and str(live_display_event_override.get("type", "")).startswith("game_"):
                live_display_event_override = None
            messages.append("Two Truths and a Lie is hidden from attendees. Existing game data was preserved.")
            should_broadcast = True

        elif action == "start_two_truths_game":
            game = two_truths_game()
            participant_count = len(game.get("participants", {}))
            if not game.get("enabled"):
                errors.append("Enable Two Truths and a Lie before starting it.")
            elif game.get("phase") != "signup":
                errors.append("Two Truths and a Lie can only start from the signup phase.")
            elif participant_count < 2:
                errors.append("At least two participants must submit clues before the game can start.")
            else:
                game["phase"] = "active"
                game["started_at"] = _utc_now_iso()
                game["ended_at"] = ""
                game["results"] = copy.deepcopy(empty_two_truths_game_state()["results"])
                write_state_backup_if_available("two-truths-start")
                messages.append(f"Two Truths and a Lie started with {participant_count} participants. Guesses are open.")
                should_broadcast = True

        elif action == "end_two_truths_game":
            game = two_truths_game()
            if game.get("phase") != "active":
                errors.append("Start Two Truths and a Lie before ending it.")
            else:
                finalized_at = _utc_now_iso()
                game["phase"] = "ended"
                game["ended_at"] = finalized_at
                game["results"] = calculate_two_truths_results(game, finalized_at=finalized_at)
                upsert_game_result_archive(TWO_TRUTHS_GAME_KEY)
                winners = two_truths_winners(game)
                write_state_backup_if_available("two-truths-ended")
                if winners:
                    messages.append(f"Two Truths and a Lie ended with {len(winners)} winner{'s' if len(winners) != 1 else ''}.")
                else:
                    messages.append("Two Truths and a Lie ended. No player recorded a correct guess.")
                should_broadcast = True

        elif action == "reset_two_truths_game":
            confirmation = request.form.get("confirmation", "").strip()
            if confirmation != "RESET TWO TRUTHS AND A LIE":
                errors.append("Enter the exact reset confirmation phrase.")
            else:
                game = two_truths_game()
                enabled = bool(game.get("enabled"))
                write_state_backup_if_available("two-truths-reset")
                games_state[TWO_TRUTHS_GAME_KEY] = empty_two_truths_game_state(enabled=enabled)
                if live_display_event_override and str(live_display_event_override.get("type", "")).startswith("game_"):
                    live_display_event_override = None
                messages.append("Two Truths and a Lie was reset. Participants, guesses, scores, and winners were cleared.")
                should_broadcast = True

        elif action == "pause_game_display":
            live_display_event_override = {
                "type": "game_paused",
                "title": "Two Truths and a Lie",
                "highlight": "Game break",
                "message": "The live rotation is paused while the hosts prepare the next game update.",
                "details": ["Stay tuned for clues, scores, and results."],
            }
            messages.append("Live display paused on the Two Truths and a Lie game card.")
            should_broadcast = True

        elif action == "show_two_truths_winner":
            game = two_truths_game()
            winners = two_truths_winners(game)
            if game.get("phase") != "ended":
                errors.append("End the game before showing its winner.")
            elif not winners:
                errors.append("This game has no winner because nobody submitted a correct guess.")
            else:
                names = ", ".join(str(entry.get("name", "Guest")) for entry in winners)
                top_score = int(winners[0].get("correct", 0) or 0)
                live_display_event_override = {
                    "type": "game_winner",
                    "title": "Two Truths and a Lie",
                    "highlight": names,
                    "message": "Tonight's mystery-game winner!" if len(winners) == 1 else "Tonight's mystery-game winners!",
                    "details": [f"{top_score} correct guess{'es' if top_score != 1 else ''}"],
                    "image_url": game_art_url(TWO_TRUTHS_GAME_KEY, winner=True),
                    "media_treatment": "background",
                }
                messages.append("Live display paused on the game winner card.")
                should_broadcast = True

        elif action == "show_two_truths_results":
            game = two_truths_game()
            results = game.get("results", {})
            scores = results.get("scores", []) if isinstance(results, dict) else []
            if game.get("phase") != "ended":
                errors.append("End the game before showing final results.")
            else:
                details = [
                    f"#{index + 1} {entry.get('name', 'Guest')}: {entry.get('correct', 0)} correct of {entry.get('attempts', 0)}"
                    for index, entry in enumerate(scores[:6])
                ] or ["No completed guesses were submitted."]
                live_display_event_override = {
                    "type": "game_results",
                    "title": "Two Truths and a Lie Results",
                    "highlight": f"{len(game.get('participants', {}))} participants",
                    "message": "Final mystery-game standings",
                    "details": details,
                    "image_url": game_art_url(TWO_TRUTHS_GAME_KEY),
                    "media_treatment": "background",
                }
                messages.append("Live display paused on the final game results.")
                should_broadcast = True

        elif action == "resume_game_display":
            if live_display_event_override and str(live_display_event_override.get("type", "")).startswith("game_"):
                live_display_event_override = None
                for game_key in GAME_CATALOG:
                    party_game_state(game_key)["presentation"] = {"active": False, "slide_index": 0}
                messages.append("Live display resumed its normal rotation.")
                should_broadcast = True
            else:
                messages.append("The live display is not paused on a game card.")

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
            live_display_notice_queue.clear()
            display_runtime["pinned_card_id"] = ""
            display_runtime["center_paused"] = False
            display_runtime["center_revision"] = int(display_runtime.get("center_revision", 0) or 0) + 1
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
                        "name": signup.singer_label,
                        "singers": copy.deepcopy(signup.singers),
                        "singer_names": signup.singer_names,
                        "singer_label": signup.singer_label,
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
            else:
                try:
                    call_karaoke_entry(signup)
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    messages.append(f"Called {signup.singer_label} to the karaoke stage.")
                    should_broadcast = True

        elif action == "show_karaoke_singer_card":
            signup = find_karaoke_signup(
                request.form.get("entry_id", "").strip()
                or str(karaoke_state.get("current_singer_id", "") or "")
            )
            if not signup or signup.workflow.get("performance_status") not in {
                "called",
                "on_stage",
            }:
                errors.append("Call a singer before showing their stage card.")
            else:
                show_karaoke_entry_card(signup)
                messages.append(f"Showing {signup.singer_label}'s current stage card.")
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
                messages.append(f"Marked {signup.singer_label} on stage. Start the video in the official YouTube tab.")
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
                    messages.append(f"Completed {signup.singer_label}'s karaoke performance.")
                else:
                    signup.workflow["performance_status"] = "skipped"
                    signup.workflow["completed_at"] = _utc_now_iso()
                    append_karaoke_history(
                        signup,
                        "performance_skipped",
                        detail=request.form.get("reason", "").strip(),
                        actor_name="admin",
                    )
                    messages.append(f"Skipped {signup.singer_label} and advanced the lineup.")
                karaoke_state["current_singer_id"] = None
                karaoke_state["stage_mode"] = "standby"
                refresh_karaoke_stage_selection()
                next_signup = find_karaoke_signup(str(karaoke_state.get("next_singer_id", "") or ""))
                if next_signup:
                    call_karaoke_entry(next_signup)
                    messages.append(f"Called {next_signup.singer_label} to the karaoke stage.")
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
                was_current = entry_id == str(
                    karaoke_state.get("current_singer_id", "") or ""
                )
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
                    signup.workflow["called_at"] = ""
                    signup.workflow["started_at"] = ""
                    signup.workflow["completed_at"] = ""
                    append_karaoke_history(
                        signup,
                        "returned_to_queue",
                        detail="The host changed this song's run-of-show position.",
                        actor_name="admin",
                    )
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
                if was_current:
                    karaoke_state["current_singer_id"] = None
                    karaoke_state["stage_mode"] = "standby"
                    if live_display_event_override and str(
                        live_display_event_override.get("type", "")
                    ).startswith("karaoke_"):
                        live_display_event_override = None
                refresh_karaoke_stage_selection()
                messages.append(f"Updated {signup.singer_label}'s karaoke lineup position.")
                should_broadcast = True

        elif action == "stop_karaoke_party":
            return_active_karaoke_entries_to_queue(
                event="party_stopped_requeued",
                detail="Karaoke was stopped before this performance completed.",
            )
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
            return_active_karaoke_entries_to_queue(
                event="party_reset_requeued",
                detail="Karaoke stage state was reset by the host.",
            )
            karaoke_state.clear()
            karaoke_state.update(copy.deepcopy(DEFAULT_KARAOKE_STATE))
            if live_display_event_override and str(
                live_display_event_override.get("type", "")
            ).startswith("karaoke_"):
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
                upsert_costume_result_archive()
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
    selected_admin_game = str(request.args.get("game", "") or TWO_TRUTHS_GAME_KEY) if admin_view == "games" else None
    if selected_admin_game not in GAME_CATALOG:
        selected_admin_game = TWO_TRUTHS_GAME_KEY if admin_view == "games" else None

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
        display_config=display_config,
        display_runtime=display_runtime,
        display_custom_cards=display_custom_cards,
        display_source_labels=DISPLAY_SOURCE_LABELS,
        display_layout=build_display_layout(),
        display_form_datetime_value=display_form_datetime_value,
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
        karaoke_attendees=karaoke_attendee_options(),
        karaoke_custom_singer_value=KARAOKE_CUSTOM_SINGER_VALUE,
        karaoke_max_singers=KARAOKE_MAX_SINGERS,
        admin_new_karaoke_singer_rows=admin_new_karaoke_singer_rows,
        games_admin=all_games_admin_view(
            selected_admin_game,
            include_selected=admin_view == "games",
        ),
        game_result_cards=generated_game_result_entries(include_hidden=True),
        selected_game_archive=next(
            (
                archive
                for archive in result_archives
                if admin_view == "games"
                and archive.get("event_id") == current_event_id()
                and archive.get("kind") == "game"
                and archive.get("subject_key") == selected_admin_game
            ),
            None,
        ),
        event_editions=event_editions,
        result_archives=result_archives,
        recognition_credits=recognition_credits,
        achievement_catalog=ACHIEVEMENT_CATALOG,
        account_achievement_views={
            str(account.get("id", "")): achievement_views(recognition_credits, str(account.get("id", "")))
            for account in user_accounts.values()
        },
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


@app.route("/admin/export/games")
def export_games():
    if redis_state_available:
        load_state_from_redis()
    exported_games = copy.deepcopy(games_state)
    for game_key in (MURDER_MARRY_FUCK_GAME_KEY, *PROMPT_GAME_KEYS):
        exported_game = exported_games.get(game_key, {})
        if not isinstance(exported_game, dict):
            continue
        participants = party_game_state(game_key).get("participants", {}).values()
        exported_game["participants"] = [
            {
                "player_id": participant.get("player_id", ""),
                "name": participant_public_name(
                    participant,
                    anonymous=bool(exported_game.get("anonymous_mode")),
                ),
                "anonymous": bool(exported_game.get("anonymous_mode")),
                **(
                    {"completed_rounds": len(participant.get("answers", {}))}
                    if game_key == MURDER_MARRY_FUCK_GAME_KEY
                    else {}
                ),
            }
            for participant in participants
            if isinstance(participant, dict)
        ]
    return send_json_export(
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "exported_at": _utc_now_iso(),
            "privacy_note": "Game exports use the admin-selected public identity mode without account IDs. Murder, Marry, F%$@ includes aggregate results only and never account-linked selections.",
            "games_state": exported_games,
        },
        "halloween-games.json",
    )


@app.route("/admin/export/recognition")
def export_recognition():
    if redis_state_available:
        load_state_from_redis()
    return send_json_export(
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "exported_at": _utc_now_iso(),
            "event_editions": copy.deepcopy(event_editions),
            "result_archives": copy.deepcopy(result_archives),
            "recognition_credits": copy.deepcopy(recognition_credits),
        },
        "halloween-recognition-history.json",
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
                    account_id=str(session.get("user_id", "") or ""),
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

    requester_id = str(session.get("user_id", "") or "").strip()
    requester_name = str(session.get("username", "") or "").strip()
    karaoke_form = {
        "singers": karaoke_singer_form_rows(
            default_account_id=requester_id,
            default_name=requester_name,
        ),
        "song_title": "",
        "artist": "",
        "youtube_link": "",
        "youtube_video_id": "",
    }
    selected_youtube: dict[str, object] | None = None
    if request.method == "POST":
        singers, singer_rows, singer_errors = parse_karaoke_singers_from_form()
        singer_label = karaoke_singer_label(singers)
        song_title = request.form.get("song_title", "").strip()
        artist = request.form.get("artist", "").strip()
        youtube_link = request.form.get("youtube_link", "").strip()
        youtube_video_id = request.form.get("youtube_video_id", "").strip()
        karaoke_form.update(
            {
                "singers": singer_rows,
                "song_title": song_title,
                "artist": artist,
                "youtube_link": youtube_link,
                "youtube_video_id": youtube_video_id,
            }
        )

        errors.extend(singer_errors)
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
                        requester_id=requester_id,
                        requested_at=_utc_now_iso(),
                        name=singer_label,
                        song_title=song_title,
                        artist=artist,
                        youtube_link=str(verified_video.get("watch_url", "") or ""),
                        youtube=normalize_karaoke_youtube(verified_video),
                        workflow=workflow,
                        singers=singers,
                    )
                    append_karaoke_history(
                        signup,
                        "submitted",
                        actor_id=requester_id,
                        actor_name=requester_name,
                    )
                    append_karaoke_history(signup, "video_verified")
                else:
                    signup = KaraokeSignup(
                        id=uuid4().hex,
                        requester_id=requester_id,
                        requested_at=_utc_now_iso(),
                        name=singer_label,
                        song_title=song_title,
                        artist=artist,
                        youtube_link=youtube_link,
                        singers=singers,
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

    user_id = requester_id
    return render_template(
        "karaoke_signup.html",
        errors=errors,
        submitted=submitted,
        karaoke_signups=public_karaoke_signups(),
        own_karaoke_requests=[
            karaoke_attendee_template_entry(signup, user_id)
            for signup in karaoke_signups
            if karaoke_attendee_signup_is_visible(signup, user_id)
        ],
        karaoke_attendee=karaoke_attendee_view_state(user_id),
        karaoke_data_url=url_for("party_karaoke_data"),
        youtube_karaoke_enabled=bool(app.config.get("YOUTUBE_KARAOKE_ENABLED")),
        youtube_search_configured=youtube_config().search_configured,
        youtube_search_url=url_for("party_karaoke_search"),
        karaoke_form=karaoke_form,
        selected_youtube=selected_youtube,
        karaoke_attendees=karaoke_attendee_options(),
        karaoke_custom_singer_value=KARAOKE_CUSTOM_SINGER_VALUE,
        karaoke_max_singers=KARAOKE_MAX_SINGERS,
        show_admin_link=False,
    )


@app.get("/api/party/karaoke-data")
def party_karaoke_data():
    if not party_day_has_arrived():
        return jsonify({"error": "Karaoke is not open yet."}), 403
    return jsonify(
        karaoke_attendee_view_state(str(session.get("user_id", "") or ""))
    )


@app.post("/api/party/karaoke/entries/<entry_id>/dismiss-completion")
def party_karaoke_dismiss_completion(entry_id: str):
    user_id = str(session.get("user_id", "") or "")
    payload = request.get_json(silent=True)
    expected_completion_id = str(
        payload.get("completion_id", "") if isinstance(payload, dict) else ""
    )

    def dismiss_completion() -> None:
        signup = find_karaoke_signup(entry_id)
        if not signup or not karaoke_user_is_participant(signup, user_id):
            raise LookupError("Completed karaoke performance could not be found.")
        if signup.workflow.get("performance_status") != "completed":
            raise RuntimeError("Only a completed karaoke performance can be dismissed.")
        completion_id = karaoke_completion_acknowledgement_value(signup)
        if not expected_completion_id or expected_completion_id != completion_id:
            raise RuntimeError("This performance changed. Refresh before dismissing it.")
        acknowledgements = normalize_karaoke_completion_acknowledgements(
            karaoke_completion_acknowledgements.get(user_id, {})
        )
        acknowledgements.pop(signup.id, None)
        acknowledgements[signup.id] = completion_id
        karaoke_completion_acknowledgements[user_id] = (
            normalize_karaoke_completion_acknowledgements(acknowledgements)
        )

    try:
        explicit_state_mutation(dismiss_completion, broadcast=False)
    except StateMutationBusy as exc:
        return jsonify({"error": str(exc)}), 503
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(karaoke_attendee_view_state(user_id))


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
