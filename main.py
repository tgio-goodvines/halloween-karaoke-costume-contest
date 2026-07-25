from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import List, Tuple
from threading import Condition, Thread
from urllib.parse import parse_qs, quote, quote_plus, urlencode, unquote, urlparse
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError, URLError
from uuid import uuid4
import copy
import hashlib
import io
import json
import os
import re
import secrets
import time
import random

import redis
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from flask import (
    Flask,
    Response,
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


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("HALLOWEEN_APP_SECRET", "dev-secret-key")
app.config["ADMIN_PASSWORD"] = os.environ.get("HALLOWEEN_ADMIN_PASSWORD", "")
app.config["PARTY_CODE"] = os.environ.get("HALLOWEEN_PARTY_CODE", "")
app.config["PARTY_TITLE"] = os.environ.get(
    "HALLOWEEN_PARTY_TITLE",
    "Qiana and Tony's 3rd Annual Halloween Party",
)
YOUTUBE_API_KEY_ENV_VALUE = os.environ.get("HALLOWEEN_YOUTUBE_API_KEY", "")
app.config["YOUTUBE_API_KEY"] = YOUTUBE_API_KEY_ENV_VALUE
app.config["APPLE_MUSIC_DEVELOPER_TOKEN"] = os.environ.get("HALLOWEEN_APPLE_MUSIC_DEVELOPER_TOKEN", "")
app.config["APPLE_MUSIC_STOREFRONT"] = os.environ.get("HALLOWEEN_APPLE_MUSIC_STOREFRONT", "us")
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


STATE_SCHEMA_VERSION = 2


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
    youtube_video_id: str = ""
    youtube_watch_url: str = ""
    youtube_embed_status: str = "missing"
    youtube_title: str = ""
    youtube_channel: str = ""
    youtube_thumbnail_url: str = ""
    youtube_duration: str = ""
    youtube_last_checked_at: str = ""


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
    "stage_mode": "intro",
}

DEFAULT_JUKEBOX_SETTINGS: dict[str, object] = {
    "enabled": False,
    "provider": "apple_music",
    "mode": "manual_playlist",
    "requests_enabled": True,
    "approval_required": True,
    "explicit_allowed": True,
    "max_requests_per_user": 2,
    "request_insert_min_position": 2,
    "request_insert_max_position": 6,
    "duplicate_cooldown": 8,
    "loop_playlist": True,
    "shuffle_playlist": False,
    "autoplay_fallback": True,
    "seed_kind": "song",
    "seed_id": "",
    "seed_title": "",
    "seed_artist": "",
}
DEFAULT_JUKEBOX_PLAYLIST_NAME = "Main Party Playlist"
DEFAULT_JUKEBOX_PLAYBACK_CONTROL: dict[str, object] = {
    "id": "",
    "command": "",
    "queue_item_id": "",
    "status": "idle",
    "issued_at": "",
    "acknowledged_at": "",
    "error": "",
}
JUKEBOX_REQUEST_STATUSES = {
    "pending",
    "approved",
    "queued",
    "playing",
    "played",
    "rejected",
    "skipped",
}
JUKEBOX_QUEUE_STATUSES = {"queued", "playing", "played", "skipped"}
JUKEBOX_DJ_COMMANDS = {"connect", "play", "pause", "stop", "skip", "restart_playlist"}
JUKEBOX_CONTROL_STATUSES = {"idle", "pending", "acknowledged", "error"}
JUKEBOX_PROVIDERS = {"apple_music"}
JUKEBOX_MODES = {"manual_playlist", "autoplay_seed"}

YOUTUBE_EMBED_STATUSES = {
    "missing",
    "verified_embeddable",
    "not_embeddable",
    "unverified",
    "invalid",
}
YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

DEFAULT_DRINK_ESTIMATE_SECONDS = 8 * 60
DRINK_READY_OVERRIDE_SECONDS = 10
DRINK_READY_DASHBOARD_SECONDS = 5 * 60
SPECIALTY_DRINK_INCLUDED_LIMIT = 3
SPECIALTY_EXTRA_ORDER_HOUR = 23
DRINK_ORDER_STATUSES = ("received", "in_progress", "complete")
DISPLAY_PAIRING_TOKEN_TTL_SECONDS = 10 * 60
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
party_details: dict[str, str] = copy.deepcopy(DEFAULT_PARTY_DETAILS)
display_settings: dict[str, str] = copy.deepcopy(DEFAULT_DISPLAY_SETTINGS)
bartender_tip_settings: dict[str, object] = copy.deepcopy(DEFAULT_BARTENDER_TIP_SETTINGS)
jukebox_settings: dict[str, object] = copy.deepcopy(DEFAULT_JUKEBOX_SETTINGS)
jukebox_playlist: list[dict[str, object]] = []
jukebox_playlists: list[dict[str, object]] = []
jukebox_active_playlist_id = ""
jukebox_requests: list[dict[str, object]] = []
jukebox_queue: list[dict[str, object]] = []
jukebox_now_playing: dict[str, object] = {}
jukebox_playback_control: dict[str, object] = copy.deepcopy(DEFAULT_JUKEBOX_PLAYBACK_CONTROL)
display_pairing_tokens: dict[str, dict[str, str]] = {}
redis_state_available = False
display_pubsub_listener_started = False
STATE_MUTATION_ENDPOINTS = {
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
    "party_karaoke",
    "party_jukebox",
    "party_costume_voting",
    "jukebox_playback_event",
    "jukebox_dj_command",
}
STATE_REFRESH_ENDPOINTS = {
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
    "party_jukebox",
    "party_costume_voting",
    "live_display",
    "display_data",
}
ADMIN_ENDPOINTS = {
    "admin_portal",
    "export_state",
    "export_costume_results",
    "export_karaoke_lineup",
}
BAR_ENDPOINTS = {
    "bartender_portal",
    "bartender_queue_data",
}
REGULAR_USER_ENDPOINTS = {
    "party_dashboard",
    "party_menu",
    "party_bartender_tip",
    "party_costumes",
    "party_karaoke",
    "party_jukebox",
    "party_costume_voting",
}
DISPLAY_ENDPOINTS = {
    "live_display",
    "display_updates",
    "display_data",
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


def hash_password_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_display_pairing_token(token: str) -> str:
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


def parse_youtube_video_id(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if YOUTUBE_VIDEO_ID_PATTERN.match(value):
        return value

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if YOUTUBE_VIDEO_ID_PATTERN.match(candidate) else ""
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
            return candidate if YOUTUBE_VIDEO_ID_PATTERN.match(candidate) else ""
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts", "live"}:
            candidate = path_parts[1]
            return candidate if YOUTUBE_VIDEO_ID_PATTERN.match(candidate) else ""
    return ""


def youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else ""


def youtube_thumbnail_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""


def youtube_duration_label(duration: str) -> str:
    if not duration:
        return ""
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        duration,
    )
    if not match:
        return ""
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0) + days * 24
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def youtube_api_get(path: str, params: dict[str, object]) -> dict[str, object]:
    api_key = app.config.get("YOUTUBE_API_KEY", "")
    if not api_key:
        raise RuntimeError("YouTube API key is not configured.")
    query_params = {**params, "key": api_key}
    url = f"{YOUTUBE_API_BASE_URL}/{path}?{urlencode(query_params)}"
    request_object = UrlRequest(url, headers={"Accept": "application/json"})
    with urlopen(request_object, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def verify_youtube_video(video_id: str) -> dict[str, str]:
    if not video_id:
        return {
            "youtube_video_id": "",
            "youtube_watch_url": "",
            "youtube_embed_status": "missing",
            "youtube_title": "",
            "youtube_channel": "",
            "youtube_thumbnail_url": "",
            "youtube_duration": "",
            "youtube_last_checked_at": "",
        }

    metadata = {
        "youtube_video_id": video_id,
        "youtube_watch_url": youtube_watch_url(video_id),
        "youtube_embed_status": "unverified",
        "youtube_title": "",
        "youtube_channel": "",
        "youtube_thumbnail_url": youtube_thumbnail_url(video_id),
        "youtube_duration": "",
        "youtube_last_checked_at": "",
    }

    if not app.config.get("YOUTUBE_API_KEY", ""):
        return metadata

    try:
        response = youtube_api_get(
            "videos",
            {
                "part": "snippet,status,contentDetails",
                "id": video_id,
                "maxResults": 1,
            },
        )
    except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        app.logger.warning("Unable to verify YouTube video %s: %s", video_id, exc)
        return metadata

    items = response.get("items", [])
    if not items:
        metadata["youtube_embed_status"] = "invalid"
        metadata["youtube_last_checked_at"] = _utc_now_iso()
        return metadata

    video = items[0] if isinstance(items[0], dict) else {}
    snippet = video.get("snippet", {}) if isinstance(video.get("snippet"), dict) else {}
    status = video.get("status", {}) if isinstance(video.get("status"), dict) else {}
    content_details = (
        video.get("contentDetails", {}) if isinstance(video.get("contentDetails"), dict) else {}
    )
    thumbnails = snippet.get("thumbnails", {}) if isinstance(snippet.get("thumbnails"), dict) else {}
    thumbnail = ""
    for thumbnail_key in ("high", "medium", "default"):
        candidate = thumbnails.get(thumbnail_key, {})
        if isinstance(candidate, dict) and candidate.get("url"):
            thumbnail = str(candidate.get("url") or "")
            break

    metadata.update(
        {
            "youtube_embed_status": (
                "verified_embeddable" if bool(status.get("embeddable")) else "not_embeddable"
            ),
            "youtube_title": str(snippet.get("title", "") or ""),
            "youtube_channel": str(snippet.get("channelTitle", "") or ""),
            "youtube_thumbnail_url": thumbnail or metadata["youtube_thumbnail_url"],
            "youtube_duration": youtube_duration_label(str(content_details.get("duration", "") or "")),
            "youtube_last_checked_at": _utc_now_iso(),
        }
    )
    return metadata


def karaoke_video_status_label(status: str) -> str:
    return {
        "verified_embeddable": "Playable on live display",
        "not_embeddable": "Not embeddable",
        "unverified": "Unverified",
        "invalid": "Invalid link",
        "missing": "No video selected",
    }.get(status, "Unverified")


def youtube_api_key_is_configured() -> bool:
    return bool(str(app.config.get("YOUTUBE_API_KEY", "") or "").strip())


def youtube_api_key_source() -> str:
    configured_key = str(app.config.get("YOUTUBE_API_KEY", "") or "")
    if not configured_key:
        return "Not configured"
    if YOUTUBE_API_KEY_ENV_VALUE and configured_key == YOUTUBE_API_KEY_ENV_VALUE:
        return "Environment or Vault"
    return "Admin runtime override"


def test_youtube_api_key(api_key: str) -> tuple[bool, str]:
    previous_key = app.config.get("YOUTUBE_API_KEY", "")
    app.config["YOUTUBE_API_KEY"] = api_key
    try:
        response = youtube_api_get(
            "videos",
            {
                "part": "id,status",
                "id": "dQw4w9WgXcQ",
                "maxResults": 1,
            },
        )
    except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        app.config["YOUTUBE_API_KEY"] = previous_key
        return False, str(exc)

    if not response.get("items"):
        app.config["YOUTUBE_API_KEY"] = previous_key
        return False, "YouTube did not return a test video for this key."

    return True, ""


def infer_song_fields_from_youtube_title(title: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", title).strip()
    cleaned = re.sub(r"\s*\[[^\]]*karaoke[^\]]*\]\s*", " ", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*\([^)]*karaoke[^)]*\)\s*", " ", cleaned, flags=re.IGNORECASE).strip()
    if " - " in cleaned:
        artist, song_title = cleaned.split(" - ", 1)
        return song_title.strip(" -\"'"), artist.strip(" -\"'")
    return cleaned.strip(" -\"'"), ""


def build_youtube_result(item: dict[str, object], details_by_id: dict[str, dict[str, object]]) -> dict[str, str]:
    id_data = item.get("id", {}) if isinstance(item.get("id"), dict) else {}
    video_id = str(id_data.get("videoId", "") or "")
    snippet = item.get("snippet", {}) if isinstance(item.get("snippet"), dict) else {}
    details = details_by_id.get(video_id, {})
    status = details.get("status", {}) if isinstance(details.get("status"), dict) else {}
    content_details = (
        details.get("contentDetails", {}) if isinstance(details.get("contentDetails"), dict) else {}
    )
    thumbnails = snippet.get("thumbnails", {}) if isinstance(snippet.get("thumbnails"), dict) else {}
    thumbnail = ""
    for thumbnail_key in ("high", "medium", "default"):
        candidate = thumbnails.get(thumbnail_key, {})
        if isinstance(candidate, dict) and candidate.get("url"):
            thumbnail = str(candidate.get("url") or "")
            break
    title = str(snippet.get("title", "") or "")
    suggested_song, suggested_artist = infer_song_fields_from_youtube_title(title)
    embed_status = "verified_embeddable" if bool(status.get("embeddable")) else "not_embeddable"
    return {
        "video_id": video_id,
        "watch_url": youtube_watch_url(video_id),
        "title": title,
        "channel": str(snippet.get("channelTitle", "") or ""),
        "thumbnail_url": thumbnail or youtube_thumbnail_url(video_id),
        "duration": youtube_duration_label(str(content_details.get("duration", "") or "")),
        "embed_status": embed_status,
        "embed_status_label": karaoke_video_status_label(embed_status),
        "suggested_song_title": suggested_song,
        "suggested_artist": suggested_artist,
    }


def youtube_search_results(query: str, max_results: int = 8) -> list[dict[str, str]]:
    response = youtube_api_get(
        "search",
        {
            "part": "snippet",
            "type": "video",
            "videoEmbeddable": "true",
            "videoSyndicated": "true",
            "safeSearch": "none",
            "maxResults": max(1, min(max_results, 10)),
            "q": query,
        },
    )
    items = [item for item in response.get("items", []) if isinstance(item, dict)]
    video_ids = [
        str(item.get("id", {}).get("videoId", "") or "")
        for item in items
        if isinstance(item.get("id"), dict) and item.get("id", {}).get("videoId")
    ]
    details_by_id: dict[str, dict[str, object]] = {}
    if video_ids:
        details_response = youtube_api_get(
            "videos",
            {
                "part": "status,contentDetails",
                "id": ",".join(video_ids),
                "maxResults": len(video_ids),
            },
        )
        for video in details_response.get("items", []):
            if isinstance(video, dict) and video.get("id"):
                details_by_id[str(video.get("id"))] = video
    return [
        build_youtube_result(item, details_by_id)
        for item in items
        if isinstance(item.get("id"), dict) and item.get("id", {}).get("videoId")
    ]


def karaoke_signup_video_metadata_from_form(existing_signup: KaraokeSignup | None = None) -> dict[str, str]:
    form_video_id = parse_youtube_video_id(request.form.get("youtube_video_id", ""))
    link_video_id = parse_youtube_video_id(request.form.get("youtube_link", ""))
    video_id = form_video_id or link_video_id
    metadata = verify_youtube_video(video_id)

    youtube_link = request.form.get("youtube_link", "").strip()
    if video_id:
        metadata["youtube_watch_url"] = youtube_watch_url(video_id)
        metadata["youtube_video_id"] = video_id
        youtube_link = metadata["youtube_watch_url"]
    elif youtube_link:
        metadata["youtube_embed_status"] = "invalid"

    if (
        existing_signup
        and video_id
        and existing_signup.youtube_video_id == video_id
        and existing_signup.youtube_embed_status in YOUTUBE_EMBED_STATUSES
        and existing_signup.youtube_embed_status != "missing"
        and metadata.get("youtube_embed_status") in {"unverified", "missing"}
    ):
        metadata["youtube_embed_status"] = existing_signup.youtube_embed_status

    for key in ("youtube_title", "youtube_channel", "youtube_thumbnail_url", "youtube_duration"):
        submitted_value = request.form.get(key, "").strip()
        if submitted_value and not metadata.get(key):
            metadata[key] = submitted_value

    metadata["youtube_link"] = youtube_link
    if not metadata.get("youtube_embed_status") in YOUTUBE_EMBED_STATUSES:
        metadata["youtube_embed_status"] = "unverified" if video_id else "missing"
    return metadata


def karaoke_signup_video_dict(signup: KaraokeSignup) -> dict[str, str | bool]:
    status = signup.youtube_embed_status if signup.youtube_embed_status in YOUTUBE_EMBED_STATUSES else "unverified"
    return {
        "video_id": signup.youtube_video_id,
        "watch_url": signup.youtube_watch_url or youtube_watch_url(signup.youtube_video_id),
        "embed_status": status,
        "embed_status_label": karaoke_video_status_label(status),
        "playable": status == "verified_embeddable",
        "title": signup.youtube_title,
        "channel": signup.youtube_channel,
        "thumbnail_url": signup.youtube_thumbnail_url,
        "duration": signup.youtube_duration,
    }


def find_karaoke_signup_index(signup_id: str) -> int | None:
    for index, signup in enumerate(karaoke_signups):
        if signup.id == signup_id:
            return index
    return None


def build_karaoke_stage_override(
    signup: KaraokeSignup,
    *,
    mode: str = "intro",
    lineup_index: int | None = None,
) -> dict[str, object]:
    if lineup_index is None:
        lineup_index = find_karaoke_signup_index(signup.id)
    next_signup = None
    if lineup_index is not None and lineup_index + 1 < len(karaoke_signups):
        next_signup = karaoke_signups[lineup_index + 1]
    video = karaoke_signup_video_dict(signup)
    video_enabled = mode == "video" and bool(video["playable"]) and bool(video["video_id"])
    return {
        "type": "karaoke_stage",
        "mode": "video" if video_enabled else "intro",
        "title": "Halloween Karaoke Party",
        "highlight": signup.name,
        "message": f'“{signup.song_title}” by {signup.artist}',
        "singer_id": signup.id,
        "singer_name": signup.name,
        "song_title": signup.song_title,
        "artist": signup.artist,
        "youtube": video,
        "video_enabled": video_enabled,
        "video_playable": bool(video["playable"]),
        "next_singer": (
            {
                "id": next_signup.id,
                "name": next_signup.name,
                "song_title": next_signup.song_title,
                "artist": next_signup.artist,
            }
            if next_signup
            else None
        ),
    }


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


def clamp_int(raw_value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def normalize_jukebox_settings(raw_settings: object) -> dict[str, object]:
    settings = copy.deepcopy(DEFAULT_JUKEBOX_SETTINGS)
    if isinstance(raw_settings, dict):
        settings.update(copy.deepcopy(raw_settings))

    settings["enabled"] = bool(settings.get("enabled"))
    provider = str(settings.get("provider", "apple_music") or "apple_music")
    settings["provider"] = provider if provider in JUKEBOX_PROVIDERS else "apple_music"
    mode = str(settings.get("mode", "manual_playlist") or "manual_playlist")
    settings["mode"] = mode if mode in JUKEBOX_MODES else "manual_playlist"
    for key in ("requests_enabled", "approval_required", "explicit_allowed", "loop_playlist", "shuffle_playlist", "autoplay_fallback"):
        settings[key] = bool(settings.get(key))
    settings["max_requests_per_user"] = clamp_int(settings.get("max_requests_per_user"), 2, 0, 10)
    settings["request_insert_min_position"] = clamp_int(settings.get("request_insert_min_position"), 2, 1, 50)
    settings["request_insert_max_position"] = clamp_int(settings.get("request_insert_max_position"), 6, 1, 50)
    if int(settings["request_insert_max_position"]) < int(settings["request_insert_min_position"]):
        settings["request_insert_max_position"] = settings["request_insert_min_position"]
    settings["duplicate_cooldown"] = clamp_int(settings.get("duplicate_cooldown"), 8, 0, 50)
    settings["seed_kind"] = str(settings.get("seed_kind", "song") or "song")[:40]
    settings["seed_id"] = str(settings.get("seed_id", "") or "")[:160]
    settings["seed_title"] = str(settings.get("seed_title", "") or "").strip()[:160]
    settings["seed_artist"] = str(settings.get("seed_artist", "") or "").strip()[:160]
    return settings


def normalize_jukebox_track(data: dict[str, object], existing_id: str | None = None) -> dict[str, object] | None:
    apple_music_id = str(data.get("apple_music_id", "") or data.get("id", "") or "").strip()
    title = str(data.get("title", "") or "").strip()
    artist = str(data.get("artist", "") or "").strip()
    if not apple_music_id or not title:
        return None
    return {
        "id": existing_id or str(data.get("id", "") or uuid4().hex),
        "apple_music_id": apple_music_id[:160],
        "title": title[:160],
        "artist": artist[:160],
        "album": str(data.get("album", "") or "").strip()[:160],
        "artwork_url": safe_image_url(str(data.get("artwork_url", "") or "")),
        "duration_ms": clamp_int(data.get("duration_ms"), 0, 0, 24 * 60 * 60 * 1000),
        "explicit": bool(data.get("explicit", False)),
        "created_at": str(data.get("created_at", "") or _utc_now_iso()),
    }


def jukebox_duration_label(duration_ms: int) -> str:
    total_seconds = max(0, int(duration_ms or 0) // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def jukebox_tracks_duration_ms(tracks: list[dict[str, object]]) -> int:
    return sum(int(track.get("duration_ms", 0) or 0) for track in tracks)


def normalize_jukebox_playlist_record(data: dict[str, object]) -> dict[str, object] | None:
    raw_tracks = data.get("tracks", [])
    tracks: list[dict[str, object]] = []
    if isinstance(raw_tracks, list):
        for raw_track in raw_tracks:
            if isinstance(raw_track, dict):
                track = normalize_jukebox_track(raw_track)
                if track:
                    tracks.append(track)
    name = str(data.get("name", "") or "").strip()[:80]
    return {
        "id": str(data.get("id", "") or uuid4().hex),
        "name": name or DEFAULT_JUKEBOX_PLAYLIST_NAME,
        "tracks": tracks,
        "created_at": str(data.get("created_at", "") or _utc_now_iso()),
        "updated_at": str(data.get("updated_at", "") or _utc_now_iso()),
    }


def ensure_jukebox_playlists() -> None:
    global jukebox_playlist, jukebox_playlists, jukebox_active_playlist_id
    normalized_playlists = [
        playlist
        for playlist in (
            normalize_jukebox_playlist_record(playlist)
            for playlist in jukebox_playlists
            if isinstance(playlist, dict)
        )
        if playlist
    ]
    if not normalized_playlists:
        normalized_playlists = [
            normalize_jukebox_playlist_record(
                {
                    "name": DEFAULT_JUKEBOX_PLAYLIST_NAME,
                    "tracks": jukebox_playlist,
                }
            )
        ]
    jukebox_playlists = [playlist for playlist in normalized_playlists if playlist]
    if not jukebox_playlists:
        jukebox_playlist = []
        jukebox_active_playlist_id = ""
        return
    if not any(str(playlist.get("id", "")) == jukebox_active_playlist_id for playlist in jukebox_playlists):
        jukebox_active_playlist_id = str(jukebox_playlists[0].get("id", ""))
    active_playlist = active_jukebox_playlist()
    jukebox_playlist = active_playlist["tracks"] if active_playlist else []


def active_jukebox_playlist() -> dict[str, object] | None:
    if not jukebox_playlists:
        return None
    return next(
        (playlist for playlist in jukebox_playlists if str(playlist.get("id", "")) == jukebox_active_playlist_id),
        jukebox_playlists[0],
    )


def set_active_jukebox_playlist_tracks(tracks: list[dict[str, object]]) -> None:
    global jukebox_playlist
    ensure_jukebox_playlists()
    active_playlist = active_jukebox_playlist()
    if not active_playlist:
        jukebox_playlist = []
        return
    active_playlist["tracks"] = tracks
    active_playlist["updated_at"] = _utc_now_iso()
    jukebox_playlist = active_playlist["tracks"]


def jukebox_playlist_summaries() -> list[dict[str, object]]:
    ensure_jukebox_playlists()
    summaries = []
    for playlist in jukebox_playlists:
        tracks = playlist.get("tracks", [])
        if not isinstance(tracks, list):
            tracks = []
        duration_ms = jukebox_tracks_duration_ms(tracks)
        summaries.append(
            {
                "id": str(playlist.get("id", "")),
                "name": str(playlist.get("name", "") or DEFAULT_JUKEBOX_PLAYLIST_NAME),
                "track_count": len(tracks),
                "duration_ms": duration_ms,
                "duration_label": jukebox_duration_label(duration_ms),
                "is_active": str(playlist.get("id", "")) == jukebox_active_playlist_id,
            }
        )
    return summaries


def active_jukebox_queue_duration_ms() -> int:
    return jukebox_tracks_duration_ms(queued_jukebox_items())


def normalize_jukebox_request(data: dict[str, object]) -> dict[str, object] | None:
    track = normalize_jukebox_track(data)
    if not track:
        return None
    status = str(data.get("status", "pending") or "pending")
    if status not in JUKEBOX_REQUEST_STATUSES:
        status = "pending"
    return {
        **track,
        "id": str(data.get("id", "") or uuid4().hex),
        "requester_user_id": str(data.get("requester_user_id", "") or ""),
        "requester_name": str(data.get("requester_name", "") or "").strip()[:80],
        "note": str(data.get("note", "") or "").strip()[:240],
        "status": status,
        "submitted_at": str(data.get("submitted_at", "") or _utc_now_iso()),
        "decided_at": str(data.get("decided_at", "") or ""),
        "queued_at": str(data.get("queued_at", "") or ""),
        "played_at": str(data.get("played_at", "") or ""),
    }


def normalize_jukebox_queue_item(data: dict[str, object]) -> dict[str, object] | None:
    track = normalize_jukebox_track(data)
    if not track:
        return None
    status = str(data.get("status", "queued") or "queued")
    if status not in JUKEBOX_QUEUE_STATUSES:
        status = "queued"
    return {
        **track,
        "id": str(data.get("id", "") or uuid4().hex),
        "source": str(data.get("source", "playlist") or "playlist")[:40],
        "playlist_track_id": str(data.get("playlist_track_id", "") or data.get("track_id", "") or ""),
        "request_id": str(data.get("request_id", "") or ""),
        "requester_user_id": str(data.get("requester_user_id", "") or ""),
        "requester_name": str(data.get("requester_name", "") or "").strip()[:80],
        "status": status,
        "queued_at": str(data.get("queued_at", "") or _utc_now_iso()),
        "started_at": str(data.get("started_at", "") or ""),
        "played_at": str(data.get("played_at", "") or ""),
    }


def normalize_jukebox_now_playing(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        return {}
    item = normalize_jukebox_queue_item(data)
    if not item:
        return {}
    item["playback_state"] = str(data.get("playback_state", "") or "")
    return item


def normalize_jukebox_playback_control(data: object) -> dict[str, object]:
    control = copy.deepcopy(DEFAULT_JUKEBOX_PLAYBACK_CONTROL)
    if isinstance(data, dict):
        control.update(copy.deepcopy(data))
    command = str(control.get("command", "") or "").strip()
    control["command"] = command if command in JUKEBOX_DJ_COMMANDS else ""
    status = str(control.get("status", "idle") or "idle").strip()
    control["status"] = status if status in JUKEBOX_CONTROL_STATUSES else "idle"
    control["id"] = str(control.get("id", "") or "")[:80]
    control["queue_item_id"] = str(control.get("queue_item_id", "") or "")[:80]
    control["issued_at"] = str(control.get("issued_at", "") or "")
    control["acknowledged_at"] = str(control.get("acknowledged_at", "") or "")
    control["error"] = str(control.get("error", "") or "").strip()[:240]
    if not control["command"]:
        control["status"] = "idle"
    return control


def cleanup_display_pairing_tokens() -> None:
    now = datetime.now(timezone.utc)
    expired_keys = [
        token_hash
        for token_hash, token_record in display_pairing_tokens.items()
        if parse_utc_iso(token_record.get("expires_at")) is None
        or parse_utc_iso(token_record.get("expires_at")) <= now
        or str(token_record.get("used_at", "") or "")
    ]
    for token_hash in expired_keys:
        display_pairing_tokens.pop(token_hash, None)


def create_display_pairing_token() -> str:
    cleanup_display_pairing_tokens()
    raw_token = secrets.token_urlsafe(32)
    display_pairing_tokens[hash_display_pairing_token(raw_token)] = {
        "created_at": _utc_now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=DISPLAY_PAIRING_TOKEN_TTL_SECONDS))
        .isoformat()
        .replace("+00:00", "Z"),
        "used_at": "",
    }
    return raw_token


def consume_display_pairing_token(raw_token: str) -> bool:
    cleanup_display_pairing_tokens()
    token_hash = hash_display_pairing_token(str(raw_token or ""))
    token_record = display_pairing_tokens.get(token_hash)
    expires_at = parse_utc_iso(token_record.get("expires_at")) if token_record else None
    if not token_record or not expires_at or expires_at <= datetime.now(timezone.utc):
        return False
    if str(token_record.get("used_at", "") or ""):
        return False
    token_record["used_at"] = _utc_now_iso()
    session["display_authorized"] = True
    session["display_authorized_at"] = _utc_now_iso()
    return True


def session_has_display_authorization() -> bool:
    return bool(session.get("display_authorized")) or session_has_role("admin")


def session_has_jukebox_playback_access() -> bool:
    return session_has_role("admin") or bool(session.get("display_authorized"))


def issue_jukebox_dj_command(command: str, queue_item_id: str = "") -> dict[str, object]:
    normalized_command = str(command or "").strip()
    if normalized_command not in JUKEBOX_DJ_COMMANDS:
        raise ValueError("Choose a valid jukebox DJ command.")
    normalized_queue_item_id = str(queue_item_id or "").strip()
    return {
        "id": uuid4().hex,
        "command": normalized_command,
        "queue_item_id": normalized_queue_item_id if normalized_command in {"play", "restart_playlist"} else "",
        "status": "pending",
        "issued_at": _utc_now_iso(),
        "acknowledged_at": "",
        "error": "",
    }


def request_jukebox_dj_command(command: str, queue_item_id: str = "") -> tuple[dict[str, object] | None, str | None]:
    requested_command = str(command or "").strip()
    requested_queue_item_id = str(queue_item_id or "").strip()
    if requested_queue_item_id:
        queue_item = find_jukebox_queue_item(requested_queue_item_id)
        if requested_command != "play":
            return None, "Specific queue songs can only be targeted with Play."
        if not queue_item or str(queue_item.get("status", "")) not in {"queued", "playing"}:
            return None, "Choose a queued jukebox song to play."
    try:
        return issue_jukebox_dj_command(requested_command, requested_queue_item_id), None
    except ValueError as exc:
        return None, str(exc)


def acknowledge_jukebox_dj_command(command_id: str, error: str = "") -> None:
    command_id = str(command_id or "").strip()
    if not command_id or command_id != str(jukebox_playback_control.get("id", "")):
        return
    jukebox_playback_control["status"] = "error" if error else "acknowledged"
    jukebox_playback_control["acknowledged_at"] = _utc_now_iso()
    jukebox_playback_control["error"] = str(error or "").strip()[:240]


def jukebox_developer_token_configured() -> bool:
    return bool(str(app.config.get("APPLE_MUSIC_DEVELOPER_TOKEN", "") or "").strip())


def jukebox_active_request_count(user_id: str) -> int:
    return sum(
        1
        for request_item in jukebox_requests
        if str(request_item.get("requester_user_id", "")) == user_id
        and str(request_item.get("status", "")) in {"pending", "approved", "queued"}
    )


def jukebox_recent_track_ids(limit: int | None = None) -> list[str]:
    completed = [
        str(item.get("apple_music_id", ""))
        for item in jukebox_queue
        if str(item.get("status", "")) in {"played", "skipped", "playing"}
    ]
    if limit is None:
        return [track_id for track_id in completed if track_id]
    return [track_id for track_id in completed if track_id][-limit:]


def find_jukebox_request(request_id: str) -> dict[str, object] | None:
    return next((item for item in jukebox_requests if str(item.get("id", "")) == request_id), None)


def find_jukebox_queue_item(queue_item_id: str) -> dict[str, object] | None:
    return next((item for item in jukebox_queue if str(item.get("id", "")) == queue_item_id), None)


def find_jukebox_queue_index(queue_item_id: str) -> int | None:
    return next((index for index, item in enumerate(jukebox_queue) if str(item.get("id", "")) == queue_item_id), None)


def jukebox_track_identity_matches(left: dict[str, object], right: dict[str, object]) -> bool:
    left_apple_id = str(left.get("apple_music_id", "") or "")
    right_apple_id = str(right.get("apple_music_id", "") or "")
    if left_apple_id and right_apple_id:
        return left_apple_id == right_apple_id
    return (
        str(left.get("title", "") or "").strip().casefold(),
        str(left.get("artist", "") or "").strip().casefold(),
    ) == (
        str(right.get("title", "") or "").strip().casefold(),
        str(right.get("artist", "") or "").strip().casefold(),
    )


def remove_jukebox_queue_rows_for_item(removed_item: dict[str, object], queue_item_id: str = "") -> int:
    global jukebox_queue
    playlist_track_id = str(removed_item.get("playlist_track_id", "") or "")
    request_id = str(removed_item.get("request_id", "") or "")
    original_count = len(jukebox_queue)
    jukebox_queue = [
        queue_item
        for queue_item in jukebox_queue
        if not (
            (queue_item_id and str(queue_item.get("id", "") or "") == queue_item_id)
            or (playlist_track_id and str(queue_item.get("playlist_track_id", "") or "") == playlist_track_id)
            or (request_id and str(queue_item.get("request_id", "") or "") == request_id)
            or (
                not playlist_track_id
                and not request_id
                and jukebox_track_identity_matches(queue_item, removed_item)
            )
        )
    ]
    return original_count - len(jukebox_queue)


def remove_matching_active_playlist_tracks(removed_item: dict[str, object]) -> int:
    playlist_track_id = str(removed_item.get("playlist_track_id", "") or "")
    original_tracks = list(jukebox_playlist)
    updated_tracks = [
        track
        for track in original_tracks
        if not (
            (playlist_track_id and str(track.get("id", "") or "") == playlist_track_id)
            or (not playlist_track_id and jukebox_track_identity_matches(track, removed_item))
        )
    ]
    if len(updated_tracks) != len(original_tracks):
        set_active_jukebox_playlist_tracks(updated_tracks)
    return len(original_tracks) - len(updated_tracks)


def remove_matching_jukebox_requests(removed_item: dict[str, object], request_id: str = "") -> int:
    global jukebox_requests
    requested_id = str(request_id or removed_item.get("request_id", "") or "")
    original_count = len(jukebox_requests)
    jukebox_requests = [
        request_item
        for request_item in jukebox_requests
        if not (
            (requested_id and str(request_item.get("id", "") or "") == requested_id)
            or (
                str(removed_item.get("source", "") or "") == "request"
                and jukebox_track_identity_matches(request_item, removed_item)
            )
        )
    ]
    return original_count - len(jukebox_requests)


def active_jukebox_queue_indices() -> list[int]:
    return [
        index
        for index, item in enumerate(jukebox_queue)
        if str(item.get("status", "")) in {"queued", "playing"}
    ]


def next_jukebox_queue_item() -> dict[str, object] | None:
    return next((item for item in jukebox_queue if str(item.get("status", "")) == "queued"), None)


def queued_jukebox_items() -> list[dict[str, object]]:
    return [item for item in jukebox_queue if str(item.get("status", "")) in {"queued", "playing"}]


def create_jukebox_queue_item(
    track: dict[str, object],
    source: str = "playlist",
    request_item: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": uuid4().hex,
        "apple_music_id": str(track.get("apple_music_id", "")),
        "title": str(track.get("title", "")),
        "artist": str(track.get("artist", "")),
        "album": str(track.get("album", "")),
        "artwork_url": str(track.get("artwork_url", "")),
        "duration_ms": int(track.get("duration_ms", 0) or 0),
        "explicit": bool(track.get("explicit", False)),
        "source": source,
        "playlist_track_id": str(track.get("id", "") if source == "playlist" else ""),
        "request_id": str(request_item.get("id", "") if request_item else ""),
        "requester_user_id": str(request_item.get("requester_user_id", "") if request_item else ""),
        "requester_name": str(request_item.get("requester_name", "") if request_item else ""),
        "status": "queued",
        "queued_at": _utc_now_iso(),
        "started_at": "",
        "played_at": "",
    }


def regenerate_jukebox_queue() -> None:
    global jukebox_queue
    ensure_jukebox_playlists()
    existing_done = [
        item for item in jukebox_queue if str(item.get("status", "")) in {"played", "skipped"}
    ][-50:]
    queue_items = [
        create_jukebox_queue_item(track, source="playlist")
        for track in jukebox_playlist
        if normalize_jukebox_track(track)
    ]
    rng = random.SystemRandom()
    if bool(jukebox_settings.get("shuffle_playlist")):
        rng.shuffle(queue_items)
    if not queue_items and jukebox_settings.get("mode") == "autoplay_seed" and jukebox_settings.get("seed_id"):
        seed_track = {
            "apple_music_id": jukebox_settings.get("seed_id", ""),
            "title": jukebox_settings.get("seed_title", "Apple Music Autoplay Seed"),
            "artist": jukebox_settings.get("seed_artist", ""),
        }
        normalized_seed = normalize_jukebox_track(seed_track)
        if normalized_seed:
            queue_items.append(create_jukebox_queue_item(normalized_seed, source="seed"))

    cooldown = int(jukebox_settings.get("duplicate_cooldown", 0) or 0)
    recent_ids = set(jukebox_recent_track_ids(cooldown))
    requester_window: list[str] = []
    approved_requests = [
        item
        for item in jukebox_requests
        if str(item.get("status", "")) in {"approved", "queued"}
        and str(item.get("apple_music_id", "")) not in recent_ids
    ]
    min_position = 1
    max_position = 2
    for request_item in approved_requests:
        requester_id = str(request_item.get("requester_user_id", ""))
        if requester_id and requester_id in requester_window[-2:]:
            insert_at = min(len(queue_items), max_position)
        else:
            upper = min(max_position, max(len(queue_items), min_position))
            lower = min(min_position, upper)
            insert_at = rng.randint(lower, upper) if upper >= lower else len(queue_items)
        queue_items.insert(insert_at, create_jukebox_queue_item(request_item, source="request", request_item=request_item))
        request_item["status"] = "queued"
        request_item["queued_at"] = _utc_now_iso()
        if requester_id:
            requester_window.append(requester_id)

    jukebox_queue = existing_done + queue_items


def reset_jukebox_playlist_queue() -> None:
    global jukebox_queue, jukebox_now_playing
    for request_item in jukebox_requests:
        if str(request_item.get("status", "")) in {"queued", "playing", "played", "skipped"}:
            request_item["status"] = "approved"
            request_item["played_at"] = ""
    jukebox_now_playing = {}
    jukebox_queue = []
    regenerate_jukebox_queue()


def restart_jukebox_playlist() -> dict[str, object]:
    global jukebox_playback_control
    reset_jukebox_playlist_queue()
    first_item = next_jukebox_queue_item()
    jukebox_playback_control = issue_jukebox_dj_command(
        "restart_playlist",
        str(first_item.get("id", "")) if first_item else "",
    )
    return jukebox_playback_control


def jukebox_state_payload() -> dict[str, object]:
    ensure_jukebox_playlists()
    upcoming = queued_jukebox_items()[:20]
    active_playlist = active_jukebox_playlist() or {}
    active_queue_duration = active_jukebox_queue_duration_ms()
    now_playing = copy.deepcopy(jukebox_now_playing)
    display_active = bool(jukebox_settings.get("enabled")) and bool(upcoming or now_playing)
    return {
        "settings": copy.deepcopy(jukebox_settings),
        "enabled": bool(jukebox_settings.get("enabled")),
        "display_active": display_active,
        "provider": str(jukebox_settings.get("provider", "apple_music")),
        "developer_token_configured": jukebox_developer_token_configured(),
        "storefront": str(app.config.get("APPLE_MUSIC_STOREFRONT", "us") or "us"),
        "playlists": jukebox_playlist_summaries(),
        "playlist_count": len(jukebox_playlists),
        "active_playlist_id": jukebox_active_playlist_id,
        "active_playlist_name": str(active_playlist.get("name", "") or DEFAULT_JUKEBOX_PLAYLIST_NAME),
        "active_playlist_count": len(jukebox_playlist),
        "active_playlist_duration_ms": active_queue_duration,
        "active_playlist_duration_label": jukebox_duration_label(active_queue_duration),
        "request_count": len(jukebox_requests),
        "pending_request_count": sum(1 for item in jukebox_requests if item.get("status") == "pending"),
        "queue": upcoming,
        "now_playing": now_playing,
        "playback_control": normalize_jukebox_playback_control(jukebox_playback_control),
        "display_authorized": session_has_display_authorization() if has_request_context() else False,
    }


def apple_music_catalog_search(query: str, limit: int = 8, offset: int = 0) -> list[dict[str, object]]:
    token = str(app.config.get("APPLE_MUSIC_DEVELOPER_TOKEN", "") or "").strip()
    if not token:
        raise RuntimeError("Apple Music developer token is not configured.")
    storefront = quote(str(app.config.get("APPLE_MUSIC_STOREFRONT", "us") or "us"))
    params = urlencode(
        {
            "term": query,
            "types": "songs",
            "limit": max(1, min(limit, 25)),
            "offset": max(0, offset),
        }
    )
    url = f"https://api.music.apple.com/v1/catalog/{storefront}/search?{params}"
    api_request = UrlRequest(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(api_request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))

    songs = (
        payload.get("results", {}).get("songs", {}).get("data", [])
        if isinstance(payload, dict)
        else []
    )
    results: list[dict[str, object]] = []
    for song in songs:
        if not isinstance(song, dict):
            continue
        attributes = song.get("attributes", {})
        if not isinstance(attributes, dict):
            continue
        artwork = attributes.get("artwork", {})
        artwork_url = ""
        if isinstance(artwork, dict):
            artwork_url = str(artwork.get("url", "") or "").replace("{w}", "512").replace("{h}", "512")
        normalized = normalize_jukebox_track(
            {
                "apple_music_id": song.get("id", ""),
                "title": attributes.get("name", ""),
                "artist": attributes.get("artistName", ""),
                "album": attributes.get("albumName", ""),
                "artwork_url": artwork_url,
                "duration_ms": attributes.get("durationInMillis", 0),
                "explicit": str(attributes.get("contentRating", "") or "").lower() == "explicit",
            }
        )
        if normalized:
            results.append(normalized)
    return results


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


def karaoke_signup_to_dict(signup: KaraokeSignup) -> dict[str, str]:
    return {
        "id": signup.id,
        "name": signup.name,
        "song_title": signup.song_title,
        "artist": signup.artist,
        "youtube_link": signup.youtube_link,
        "youtube_video_id": signup.youtube_video_id,
        "youtube_watch_url": signup.youtube_watch_url,
        "youtube_embed_status": signup.youtube_embed_status,
        "youtube_title": signup.youtube_title,
        "youtube_channel": signup.youtube_channel,
        "youtube_thumbnail_url": signup.youtube_thumbnail_url,
        "youtube_duration": signup.youtube_duration,
        "youtube_last_checked_at": signup.youtube_last_checked_at,
    }


def karaoke_signup_from_dict(data: dict[str, object]) -> KaraokeSignup:
    youtube_link = str(data.get("youtube_link", "") or "")
    youtube_video_id = str(data.get("youtube_video_id", "") or "") or parse_youtube_video_id(youtube_link)
    youtube_watch = str(data.get("youtube_watch_url", "") or "") or youtube_watch_url(youtube_video_id)
    embed_status = str(data.get("youtube_embed_status", "") or "")
    if not embed_status:
        embed_status = "unverified" if youtube_video_id else "missing"
    return KaraokeSignup(
        id=str(data.get("id", "") or uuid4().hex),
        name=str(data.get("name", "") or ""),
        song_title=str(data.get("song_title", "") or ""),
        artist=str(data.get("artist", "") or ""),
        youtube_link=youtube_link,
        youtube_video_id=youtube_video_id,
        youtube_watch_url=youtube_watch,
        youtube_embed_status=embed_status if embed_status in YOUTUBE_EMBED_STATUSES else "unverified",
        youtube_title=str(data.get("youtube_title", "") or ""),
        youtube_channel=str(data.get("youtube_channel", "") or ""),
        youtube_thumbnail_url=str(data.get("youtube_thumbnail_url", "") or ""),
        youtube_duration=str(data.get("youtube_duration", "") or ""),
        youtube_last_checked_at=str(data.get("youtube_last_checked_at", "") or ""),
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
    cleanup_display_pairing_tokens()
    ensure_jukebox_playlists()

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
        "party_details": copy.deepcopy(party_details),
        "display_settings": copy.deepcopy(display_settings),
        "bartender_tip_settings": copy.deepcopy(bartender_tip_settings),
        "jukebox_settings": copy.deepcopy(jukebox_settings),
        "jukebox_playlist": copy.deepcopy(jukebox_playlist),
        "jukebox_playlists": copy.deepcopy(jukebox_playlists),
        "jukebox_active_playlist_id": jukebox_active_playlist_id,
        "jukebox_requests": copy.deepcopy(jukebox_requests),
        "jukebox_queue": copy.deepcopy(jukebox_queue),
        "jukebox_now_playing": copy.deepcopy(jukebox_now_playing),
        "jukebox_playback_control": normalize_jukebox_playback_control(jukebox_playback_control),
        "display_pairing_tokens": copy.deepcopy(display_pairing_tokens),
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
    global password_reset_tokens, menu_items, drink_orders, rsvp_notification_email, bartender_tip_settings
    global jukebox_settings, jukebox_playlist, jukebox_playlists, jukebox_active_playlist_id
    global jukebox_requests, jukebox_queue, jukebox_now_playing, jukebox_playback_control
    global display_pairing_tokens

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

    bartender_tip_settings = normalize_bartender_tip_settings(data.get("bartender_tip_settings", {}))

    jukebox_settings = normalize_jukebox_settings(data.get("jukebox_settings", {}))
    legacy_jukebox_playlist: list[dict[str, object]] = []
    raw_jukebox_playlist = data.get("jukebox_playlist", [])
    if isinstance(raw_jukebox_playlist, list):
        for raw_track in raw_jukebox_playlist:
            if isinstance(raw_track, dict):
                track = normalize_jukebox_track(raw_track)
                if track:
                    legacy_jukebox_playlist.append(track)

    jukebox_playlists = []
    raw_jukebox_playlists = data.get("jukebox_playlists", [])
    if isinstance(raw_jukebox_playlists, list):
        for raw_playlist in raw_jukebox_playlists:
            if isinstance(raw_playlist, dict):
                playlist = normalize_jukebox_playlist_record(raw_playlist)
                if playlist:
                    jukebox_playlists.append(playlist)
    if not jukebox_playlists and legacy_jukebox_playlist:
        migrated_playlist = normalize_jukebox_playlist_record(
            {
                "name": DEFAULT_JUKEBOX_PLAYLIST_NAME,
                "tracks": legacy_jukebox_playlist,
            }
        )
        if migrated_playlist:
            jukebox_playlists.append(migrated_playlist)
    jukebox_active_playlist_id = str(data.get("jukebox_active_playlist_id", "") or "")
    jukebox_playlist = legacy_jukebox_playlist
    ensure_jukebox_playlists()

    jukebox_requests = []
    raw_jukebox_requests = data.get("jukebox_requests", [])
    if isinstance(raw_jukebox_requests, list):
        for raw_request in raw_jukebox_requests:
            if isinstance(raw_request, dict):
                request_item = normalize_jukebox_request(raw_request)
                if request_item:
                    jukebox_requests.append(request_item)

    jukebox_queue = []
    raw_jukebox_queue = data.get("jukebox_queue", [])
    if isinstance(raw_jukebox_queue, list):
        for raw_item in raw_jukebox_queue:
            if isinstance(raw_item, dict):
                queue_item = normalize_jukebox_queue_item(raw_item)
                if queue_item:
                    jukebox_queue.append(queue_item)
    jukebox_now_playing = normalize_jukebox_now_playing(data.get("jukebox_now_playing", {}))
    jukebox_playback_control = normalize_jukebox_playback_control(data.get("jukebox_playback_control", {}))
    display_pairing_tokens = {}
    raw_display_pairing_tokens = data.get("display_pairing_tokens", {})
    if isinstance(raw_display_pairing_tokens, dict):
        for token_hash, raw_record in raw_display_pairing_tokens.items():
            if not isinstance(raw_record, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(token_hash)):
                continue
            expires_at = str(raw_record.get("expires_at", "") or "")
            if not parse_utc_iso(expires_at):
                continue
            display_pairing_tokens[str(token_hash)] = {
                "created_at": str(raw_record.get("created_at", "") or ""),
                "expires_at": expires_at,
                "used_at": str(raw_record.get("used_at", "") or ""),
            }
    cleanup_display_pairing_tokens()

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
    if request.endpoint in DISPLAY_ENDPOINTS:
        if session_has_display_authorization():
            return None
        if request.endpoint == "live_display" and request.args.get("display_token"):
            return None
        login_endpoint = ROLE_LOGIN_ENDPOINTS["admin"]
        next_page = normalize_next_page(request.full_path, url_for(login_endpoint))
        return redirect(url_for(login_endpoint, next=next_page))

    required_role = required_role_for_endpoint(request.endpoint)
    if not required_role:
        return None

    if session_has_role(required_role):
        return None

    if required_role == "bartender" and session_has_role("admin"):
        return None

    login_endpoint = ROLE_LOGIN_ENDPOINTS[required_role]
    next_page = normalize_next_page(request.full_path, url_for(login_endpoint))
    return redirect(url_for(login_endpoint, next=next_page))


@app.before_request
def validate_csrf_token():
    if request.method != "POST" or app.config.get("TESTING"):
        return None

    expected_token = session.get("csrf_token")
    provided_token = request.form.get("csrf_token")
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
            "category": "Jukebox",
            "primary": "Request a song for the room.",
            "secondary": "Use the party portal to send Apple Music requests into the party mix.",
            "tertiary": "Approved requests are shuffled into the upcoming playlist.",
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
        for signup in karaoke_signups
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


def display_drink_order_summary(order: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(order.get("id", "") or ""),
        "guest": str(order.get("username", "") or "Guest"),
        "drink": str(order.get("item_name", "") or "Drink"),
        "status": str(order.get("status", "") or "received"),
        "status_label": drink_order_status_label(order.get("status")),
        "image_url": str(order.get("item_image_url", "") or ""),
        "estimated_ready_at": str(order.get("estimated_ready_at", "") or ""),
        "completed_at": str(order.get("completed_at", "") or ""),
        "drink_type": normalize_drink_type(order.get("drink_type")),
    }


def display_ready_drink_orders(limit: int = 6) -> list[dict[str, object]]:
    visible_orders = [
        order
        for order in drink_orders
        if ready_order_is_visible_on_dashboard(order)
    ]
    visible_orders.sort(key=lambda order: str(order.get("completed_at", "") or ""), reverse=True)
    return [display_drink_order_summary(order) for order in visible_orders[:limit]]


def live_display_activity_payload() -> dict[str, object]:
    active_orders = sorted(
        active_drink_orders(),
        key=lambda order: (
            drink_order_priority_bucket(order),
            str(order.get("created_at", "") or ""),
        ),
    )
    ready_orders = display_ready_drink_orders(limit=6)
    costume_preview = [
        {
            "id": signup.id,
            "name": signup.name,
            "costume": signup.costume,
        }
        for signup in costume_signups[:6]
    ]
    karaoke_preview = [
        {
            "id": signup.id,
            "name": signup.name,
            "song_title": signup.song_title,
            "artist": signup.artist,
        }
        for signup in karaoke_signups[:6]
    ]

    return {
        "drink_orders": [display_drink_order_summary(order) for order in active_orders[:6]],
        "ready_drinks": ready_orders,
        "costumes": costume_preview,
        "karaoke": karaoke_preview,
        "counts": {
            "active_drink_orders": len(active_orders),
            "ready_drinks": len(ready_orders),
            "costumes": len(costume_signups),
            "karaoke": len(karaoke_signups),
            "pending_jukebox_requests": sum(
                1 for request_item in jukebox_requests if request_item.get("status") == "pending"
            ),
        },
    }


def live_display_layout_payload(
    activity: dict[str, object] | None = None,
    jukebox: dict[str, object] | None = None,
) -> dict[str, object]:
    activity_payload = activity or live_display_activity_payload()
    jukebox_payload = jukebox or jukebox_state_payload()
    counts = activity_payload.get("counts", {}) if isinstance(activity_payload, dict) else {}
    active_order_count = int(counts.get("active_drink_orders", 0) or 0)
    ready_drink_count = int(counts.get("ready_drinks", 0) or 0)
    costume_count = int(counts.get("costumes", 0) or 0)
    karaoke_count = int(counts.get("karaoke", 0) or 0)
    jukebox_enabled = bool(jukebox_payload.get("display_active")) if isinstance(jukebox_payload, dict) else False
    has_activity = any((active_order_count, ready_drink_count, costume_count, karaoke_count))
    mode = "dashboard" if jukebox_enabled or has_activity else "idle"

    return {
        "mode": mode,
        "left_rail_enabled": jukebox_enabled,
        "right_rail_enabled": bool(has_activity),
        "reasons": {
            "jukebox": jukebox_enabled,
            "bartender": bool(active_order_count or ready_drink_count),
            "costumes": bool(costume_count),
            "karaoke": bool(karaoke_count),
        },
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
    display_token = request.args.get("display_token", "").strip()
    if display_token:
        if consume_display_pairing_token(display_token):
            persist_state_if_available()
            return redirect(url_for("live_display"))
        return redirect(url_for("admin_login", next=url_for("live_display")))

    cleanup_expired_display_notices()
    rotation_entries = build_rotation_entries()
    jukebox_payload = jukebox_state_payload()
    activity_payload = live_display_activity_payload()
    layout_payload = live_display_layout_payload(activity_payload, jukebox_payload)

    return render_template(
        "display.html",
        entries=rotation_entries,
        costume_count=len(costume_signups),
        karaoke_count=len(karaoke_signups),
        override=live_display_event_override,
        notice_override=live_display_notice_override,
        jukebox=jukebox_payload,
        display_layout=layout_payload,
        display_activity=activity_payload,
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
    jukebox_payload = jukebox_state_payload()
    activity_payload = live_display_activity_payload()
    layout_payload = live_display_layout_payload(activity_payload, jukebox_payload)

    return jsonify(
        {
            "entries": rotation_entries,
            "costume_count": len(costume_signups),
            "karaoke_count": len(karaoke_signups),
            "override": live_display_event_override,
            "event_override": live_display_event_override,
            "notice_override": live_display_notice_override,
            "jukebox": jukebox_payload,
            "layout": layout_payload,
            "activity": activity_payload,
            "display_update_version": display_update_version,
        }
    )


@app.context_processor
def inject_contest_state():
    return {
        "costume_contest_state": {
            "contest_started": bool(contest_state.get("contest_started")),
            "voting_open": bool(contest_state.get("voting_open")),
            "voting_visible": costume_voting_is_visible(),
            "winner_locked": bool(contest_state.get("winner_locked")),
            "winner": contest_state.get("winner"),
        },
        "csrf_token": get_csrf_token,
        "admin_authenticated": bool(session.get("admin_authenticated")),
        "regular_authenticated": session_has_role("regular"),
        "bartender_authenticated": session_has_role("bartender"),
        "format_time_label": format_time_label,
        "karaoke_video_status_label": karaoke_video_status_label,
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
        karaoke_signups=karaoke_signups,
        drink_orders=user_orders[:5] if party_day else [],
        ready_drink_orders=ready_orders,
        bartender_tip_settings=bartender_tip_settings,
        jukebox_settings=jukebox_settings,
        party_day_has_arrived=party_day,
        show_admin_link=False,
    )


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
            grant_session_role("regular")
            if account_has_role(account, "bartender"):
                grant_session_role("bartender")
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
            grant_session_role("regular")
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


@app.route("/party/jukebox", methods=["GET", "POST"])
def party_jukebox():
    errors: List[str] = []
    messages: List[str] = []
    user_id = str(session.get("user_id", "") or "")
    account = current_user_account()

    if not user_id or not account:
        return redirect(url_for("party_login", next=url_for("party_jukebox")))
    if not party_day_has_arrived():
        return redirect(url_for("party_dashboard"))

    if request.method == "POST":
        if not jukebox_settings.get("enabled"):
            errors.append("The jukebox is not taking requests right now.")
        if not jukebox_settings.get("requests_enabled"):
            errors.append("Song requests are paused right now.")

        track = normalize_jukebox_track(
            {
                "apple_music_id": request.form.get("apple_music_id", "").strip(),
                "title": request.form.get("title", "").strip(),
                "artist": request.form.get("artist", "").strip(),
                "album": request.form.get("album", "").strip(),
                "artwork_url": request.form.get("artwork_url", "").strip(),
                "duration_ms": request.form.get("duration_ms", "0"),
                "explicit": request.form.get("explicit") == "yes",
            }
        )
        if not track:
            errors.append("Choose a valid Apple Music song before requesting it.")
        elif track.get("explicit") and not jukebox_settings.get("explicit_allowed"):
            errors.append("Explicit songs are not available for jukebox requests right now.")

        max_active = int(jukebox_settings.get("max_requests_per_user", 0) or 0)
        if max_active and jukebox_active_request_count(user_id) >= max_active:
            errors.append(f"You already have {max_active} active jukebox request{'s' if max_active != 1 else ''}.")

        duplicate_ids = {
            str(item.get("apple_music_id", ""))
            for item in queued_jukebox_items()
        } | set(jukebox_recent_track_ids(int(jukebox_settings.get("duplicate_cooldown", 0) or 0)))
        if track and str(track.get("apple_music_id", "")) in duplicate_ids:
            errors.append("That song is already in the recent or upcoming jukebox mix.")

        if not errors and track:
            request_item = normalize_jukebox_request(
                {
                    **track,
                    "requester_user_id": user_id,
                    "requester_name": str(account.get("username", session.get("username", "Guest"))),
                    "note": request.form.get("note", "").strip(),
                    "status": "pending" if jukebox_settings.get("approval_required") else "approved",
                    "submitted_at": _utc_now_iso(),
                    "decided_at": "" if jukebox_settings.get("approval_required") else _utc_now_iso(),
                }
            )
            if request_item:
                jukebox_requests.append(request_item)
                if request_item["status"] == "approved":
                    regenerate_jukebox_queue()
                    messages.append(f"{request_item['title']} was added to the jukebox queue.")
                else:
                    messages.append(f"{request_item['title']} was sent to the hosts for approval.")
                persist_state_if_available()
                broadcast_display_update()
                return redirect(url_for("party_jukebox", requested="1"))

    if request.args.get("requested") == "1":
        messages.append("Your song request was received.")

    user_requests = sorted(
        [
            request_item
            for request_item in jukebox_requests
            if str(request_item.get("requester_user_id", "")) == user_id
        ],
        key=lambda request_item: str(request_item.get("submitted_at", "")),
        reverse=True,
    )
    return render_template(
        "jukebox.html",
        errors=errors,
        messages=messages,
        jukebox=jukebox_state_payload(),
        user_requests=user_requests,
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


@app.route("/api/youtube-search")
def youtube_search():
    if not (session_has_role("regular") or session_has_role("admin")):
        return jsonify({"error": "Sign in before searching YouTube."}), 401
    if session_has_role("regular") and not session_has_role("admin") and not party_day_has_arrived():
        return jsonify({"error": "Karaoke song search opens on the party date."}), 403

    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"error": "Enter a song or artist to search."}), 400
    if len(query) > 160:
        return jsonify({"error": "Search terms must be 160 characters or fewer."}), 400
    if not app.config.get("YOUTUBE_API_KEY", ""):
        return jsonify({"error": "YouTube search is not configured yet."}), 503

    try:
        results = youtube_search_results(query)
    except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        app.logger.warning("Unable to search YouTube for karaoke query %r: %s", query, exc)
        return jsonify({"error": "YouTube search is unavailable right now."}), 502

    return jsonify({"results": results})


@app.route("/api/jukebox-search")
def jukebox_search():
    if not (session_has_role("regular") or session_has_role("admin")):
        return jsonify({"error": "Sign in to the party app before searching Apple Music."}), 401
    if session_has_role("regular") and not session_has_role("admin") and not party_day_has_arrived():
        return jsonify({"error": "Jukebox requests open on the party date."}), 403

    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"error": "Enter a song or artist to search."}), 400
    if len(query) > 160:
        return jsonify({"error": "Search terms must be 160 characters or fewer."}), 400
    try:
        requested_limit = int(request.args.get("limit", "8") or 8)
    except ValueError:
        requested_limit = 8
    try:
        requested_offset = int(request.args.get("offset", "0") or 0)
    except ValueError:
        requested_offset = 0
    result_limit = max(1, min(requested_limit, 12))
    result_offset = max(0, min(requested_offset, 200))
    if not jukebox_developer_token_configured():
        return jsonify({"error": "Apple Music search is not configured yet."}), 503

    try:
        fetched_results = apple_music_catalog_search(query, limit=result_limit + 1, offset=result_offset)
    except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        app.logger.warning("Unable to search Apple Music for jukebox query %r: %s", query, exc)
        return jsonify({"error": "Apple Music search is unavailable right now."}), 502

    has_more = len(fetched_results) > result_limit
    results = fetched_results[:result_limit]
    if not jukebox_settings.get("explicit_allowed"):
        results = [item for item in results if not item.get("explicit")]
    return jsonify(
        {
            "results": results,
            "limit": result_limit,
            "offset": result_offset,
            "next_offset": result_offset + result_limit,
            "has_more": has_more,
        }
    )


@app.route("/api/apple-music-token")
def apple_music_token():
    if not session_has_jukebox_playback_access():
        return jsonify({"error": "Pair the live display from admin before Apple Music playback authorization."}), 401
    token = str(app.config.get("APPLE_MUSIC_DEVELOPER_TOKEN", "") or "").strip()
    if not token:
        return jsonify({"error": "Apple Music developer token is not configured."}), 503
    return jsonify(
        {
            "developer_token": token,
            "storefront": str(app.config.get("APPLE_MUSIC_STOREFRONT", "us") or "us"),
        }
    )


@app.route("/api/jukebox-state")
def jukebox_state_api():
    if not (session_has_role("regular") or session_has_role("admin") or session_has_display_authorization()):
        return jsonify({"error": "Sign in before viewing jukebox state."}), 401
    if session_has_role("regular") and not session_has_jukebox_playback_access() and not party_day_has_arrived():
        return jsonify({"error": "Jukebox opens on the party date."}), 403
    payload = jukebox_state_payload()
    if session_has_jukebox_playback_access():
        visible_requests = jukebox_requests
    else:
        user_id = str(session.get("user_id", "") or "")
        visible_requests = [
            request_item
            for request_item in jukebox_requests
            if str(request_item.get("requester_user_id", "")) == user_id
        ]
    payload["requests"] = sorted(
        copy.deepcopy(visible_requests),
        key=lambda request_item: str(request_item.get("submitted_at", "")),
        reverse=True,
    )
    return jsonify(payload)


@app.route("/api/jukebox/playback-event", methods=["POST"])
def jukebox_playback_event():
    if not session_has_jukebox_playback_access():
        return jsonify({"error": "Pair the live display from admin before jukebox playback."}), 401

    global jukebox_now_playing
    event_type = request.form.get("event", "").strip()
    queue_item_id = request.form.get("queue_item_id", "").strip()
    command_id = request.form.get("command_id", "").strip()
    command_error = request.form.get("error", "").strip()
    item = find_jukebox_queue_item(queue_item_id) if queue_item_id else None
    now_iso = _utc_now_iso()

    if event_type == "command_error":
        acknowledge_jukebox_dj_command(command_id, command_error or "Live display could not complete the DJ command.")
        broadcast_display_update()
    elif event_type == "started":
        if not item:
            item = next_jukebox_queue_item()
        if not item:
            return jsonify({"error": "No queued jukebox song is ready to mark as playing."}), 400
        for queue_item in jukebox_queue:
            if queue_item is not item and queue_item.get("status") == "playing":
                queue_item["status"] = "played"
                queue_item["played_at"] = now_iso
        item["status"] = "playing"
        item["started_at"] = now_iso
        jukebox_now_playing = copy.deepcopy(item)
        jukebox_now_playing["playback_state"] = "playing"
        request_item = find_jukebox_request(str(item.get("request_id", "")))
        if request_item:
            request_item["status"] = "playing"
        acknowledge_jukebox_dj_command(command_id)
        broadcast_display_update()
    elif event_type in {"paused", "stopped"}:
        if jukebox_now_playing:
            jukebox_now_playing["playback_state"] = event_type
        if item:
            item["status"] = "playing"
        acknowledge_jukebox_dj_command(command_id)
        broadcast_display_update()
    elif event_type in {"ended", "skipped"} and item:
        item["status"] = "skipped" if event_type == "skipped" else "played"
        item["played_at"] = now_iso
        request_item = find_jukebox_request(str(item.get("request_id", "")))
        if request_item:
            request_item["status"] = "skipped" if event_type == "skipped" else "played"
            request_item["played_at"] = now_iso
        next_item = next_jukebox_queue_item()
        jukebox_now_playing = copy.deepcopy(next_item) if next_item else {}
        if not next_item and bool(jukebox_settings.get("loop_playlist")) and jukebox_playlist:
            regenerate_jukebox_queue()
        acknowledge_jukebox_dj_command(command_id)
        broadcast_display_update()
    elif event_type == "sync":
        acknowledge_jukebox_dj_command(command_id)
        broadcast_display_update()
    else:
        return jsonify({"error": "Unknown jukebox playback event."}), 400

    return jsonify(jukebox_state_payload())


@app.route("/api/jukebox/dj-command", methods=["POST"])
def jukebox_dj_command():
    if not session_has_role("admin"):
        return jsonify({"error": "Admin access is required."}), 401

    global jukebox_playback_control
    command, error = request_jukebox_dj_command(
        request.form.get("jukebox_command", ""),
        request.form.get("queue_item_id", ""),
    )
    if error:
        return jsonify({"error": error}), 400

    jukebox_playback_control = command or copy.deepcopy(DEFAULT_JUKEBOX_PLAYBACK_CONTROL)
    broadcast_display_update()
    return jsonify(
        {
            "message": f"Sent DJ command to the live display: {jukebox_playback_control.get('command', '')}.",
            "jukebox": jukebox_state_payload(),
            "display_update_version": display_update_version,
        }
    )


@app.route("/party/logout", methods=["POST"])
@app.route("/admin/logout", methods=["POST"])
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("party_login"))


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


@app.route("/admin", methods=["GET", "POST"])
def admin_portal():
    errors: List[str] = []
    messages: List[str] = []
    global live_display_event_override, live_display_notice_override
    global submitted_costume_votes, costume_ballots, karaoke_state
    global landing_page_target, event_experience_mode, party_code_hash, party_code_hint, party_details, display_settings, rsvp_notification_email
    global bartender_tip_settings
    global jukebox_settings, jukebox_playlist, jukebox_playlists, jukebox_active_playlist_id
    global jukebox_requests, jukebox_queue, jukebox_now_playing, jukebox_playback_control

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

    def jukebox_track_from_form() -> dict[str, object] | None:
        track = normalize_jukebox_track(
            {
                "apple_music_id": request.form.get("apple_music_id", "").strip(),
                "title": request.form.get("title", "").strip(),
                "artist": request.form.get("artist", "").strip(),
                "album": request.form.get("album", "").strip(),
                "artwork_url": request.form.get("artwork_url", "").strip(),
                "duration_ms": request.form.get("duration_ms", "0"),
                "explicit": request.form.get("explicit") == "yes",
            }
        )
        if not track:
            errors.append("Choose a valid Apple Music song before saving it to the jukebox.")
        elif track.get("explicit") and not jukebox_settings.get("explicit_allowed"):
            errors.append("Explicit songs are disabled for the jukebox.")
        return track

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

        if action == "update_costume":
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

        elif action == "update_youtube_api_key":
            submitted_key = request.form.get("youtube_api_key", "").strip()
            if not submitted_key:
                errors.append("Paste a YouTube Data API key before saving.")
            elif len(submitted_key) > 200:
                errors.append("YouTube API key must be 200 characters or fewer.")
            else:
                key_ok, key_error = test_youtube_api_key(submitted_key)
                if key_ok:
                    app.config["YOUTUBE_API_KEY"] = submitted_key
                    messages.append(
                        "YouTube API key validated and enabled for this running app. Add it to Vault as youtube_api_key for production restarts."
                    )
                else:
                    errors.append(f"YouTube API key could not be validated: {key_error}")

        elif action == "clear_youtube_api_key_override":
            app.config["YOUTUBE_API_KEY"] = YOUTUBE_API_KEY_ENV_VALUE
            if YOUTUBE_API_KEY_ENV_VALUE:
                messages.append("YouTube API key reset to the environment/Vault value.")
            else:
                messages.append("YouTube API key runtime override cleared. YouTube search is disabled until a key is configured.")

        elif action == "pair_live_display":
            display_token = create_display_pairing_token()
            jukebox_playback_control = issue_jukebox_dj_command("connect")
            broadcast_display_update()
            return redirect(url_for("live_display", display_token=display_token))

        elif action == "update_jukebox_settings":
            requested_settings = normalize_jukebox_settings(
                {
                    "enabled": request.form.get("jukebox_enabled") == "yes",
                    "provider": "apple_music",
                    "mode": request.form.get("jukebox_mode", "manual_playlist"),
                    "requests_enabled": request.form.get("jukebox_requests_enabled") == "yes",
                    "approval_required": request.form.get("jukebox_approval_required") == "yes",
                    "explicit_allowed": request.form.get("jukebox_explicit_allowed") == "yes",
                    "max_requests_per_user": request.form.get("jukebox_max_requests_per_user", "2"),
                    "request_insert_min_position": request.form.get("jukebox_insert_min", "2"),
                    "request_insert_max_position": request.form.get("jukebox_insert_max", "6"),
                    "duplicate_cooldown": request.form.get("jukebox_duplicate_cooldown", "8"),
                    "loop_playlist": request.form.get("jukebox_loop_playlist") == "yes",
                    "shuffle_playlist": request.form.get("jukebox_shuffle_playlist") == "yes",
                    "autoplay_fallback": request.form.get("jukebox_autoplay_fallback") == "yes",
                    "seed_kind": request.form.get("jukebox_seed_kind", "song"),
                    "seed_id": request.form.get("jukebox_seed_id", "").strip(),
                    "seed_title": request.form.get("jukebox_seed_title", "").strip(),
                    "seed_artist": request.form.get("jukebox_seed_artist", "").strip(),
                }
            )
            if requested_settings["enabled"] and not jukebox_developer_token_configured():
                messages.append("Jukebox settings saved. Add an Apple Music developer token before live playback/search will work.")
            jukebox_settings = requested_settings
            regenerate_jukebox_queue()
            messages.append("Jukebox settings updated.")
            should_broadcast = True

        elif action == "create_jukebox_playlist":
            playlist_name = request.form.get("playlist_name", "").strip()[:80]
            new_playlist = normalize_jukebox_playlist_record(
                {
                    "name": playlist_name or f"Playlist {len(jukebox_playlists) + 1}",
                    "tracks": [],
                }
            )
            if new_playlist:
                ensure_jukebox_playlists()
                jukebox_playlists.append(new_playlist)
                jukebox_active_playlist_id = str(new_playlist.get("id", ""))
                jukebox_playlist = new_playlist["tracks"]
                reset_jukebox_playlist_queue()
                messages.append(f"Created and activated playlist: {new_playlist.get('name')}.")
                should_broadcast = True

        elif action == "set_active_jukebox_playlist":
            playlist_id = request.form.get("playlist_id", "").strip()
            ensure_jukebox_playlists()
            selected_playlist = next(
                (playlist for playlist in jukebox_playlists if str(playlist.get("id", "")) == playlist_id),
                None,
            )
            if not selected_playlist:
                errors.append("Choose a valid jukebox playlist.")
            else:
                jukebox_active_playlist_id = playlist_id
                jukebox_playlist = selected_playlist["tracks"]
                reset_jukebox_playlist_queue()
                messages.append(f"Activated playlist: {selected_playlist.get('name')}.")
                should_broadcast = True

        elif action == "rename_jukebox_playlist":
            playlist_id = request.form.get("playlist_id", "").strip()
            playlist_name = request.form.get("playlist_name", "").strip()[:80]
            ensure_jukebox_playlists()
            selected_playlist = next(
                (playlist for playlist in jukebox_playlists if str(playlist.get("id", "")) == playlist_id),
                None,
            )
            if not selected_playlist:
                errors.append("Choose a valid jukebox playlist.")
            elif not playlist_name:
                errors.append("Playlist name is required.")
            else:
                selected_playlist["name"] = playlist_name
                selected_playlist["updated_at"] = _utc_now_iso()
                messages.append(f"Renamed playlist: {playlist_name}.")

        elif action == "delete_jukebox_playlist":
            playlist_id = request.form.get("playlist_id", "").strip()
            ensure_jukebox_playlists()
            if len(jukebox_playlists) <= 1:
                errors.append("Keep at least one jukebox playlist.")
            elif not any(str(playlist.get("id", "")) == playlist_id for playlist in jukebox_playlists):
                errors.append("Choose a valid jukebox playlist.")
            else:
                removed_playlist = next(
                    playlist for playlist in jukebox_playlists if str(playlist.get("id", "")) == playlist_id
                )
                jukebox_playlists = [
                    playlist for playlist in jukebox_playlists if str(playlist.get("id", "")) != playlist_id
                ]
                if jukebox_active_playlist_id == playlist_id:
                    jukebox_active_playlist_id = str(jukebox_playlists[0].get("id", ""))
                    jukebox_playlist = jukebox_playlists[0]["tracks"]
                    reset_jukebox_playlist_queue()
                    should_broadcast = True
                messages.append(f"Deleted playlist: {removed_playlist.get('name')}.")

        elif action == "add_jukebox_track":
            track = jukebox_track_from_form()
            if track and not errors:
                ensure_jukebox_playlists()
                if any(item.get("apple_music_id") == track.get("apple_music_id") for item in jukebox_playlist):
                    errors.append("That song is already in the jukebox playlist.")
                else:
                    jukebox_playlist.append(track)
                    active_playlist = active_jukebox_playlist()
                    if active_playlist:
                        active_playlist["updated_at"] = _utc_now_iso()
                    regenerate_jukebox_queue()
                    messages.append(f"Added {track['title']} to the active playlist.")
                    should_broadcast = True

        elif action == "jukebox_dj_command":
            requested_command = request.form.get("jukebox_command", "").strip()
            queue_item_id = request.form.get("queue_item_id", "").strip()
            command, command_error = request_jukebox_dj_command(requested_command, queue_item_id)
            if command_error:
                errors.append(command_error)
            else:
                jukebox_playback_control = command or copy.deepcopy(DEFAULT_JUKEBOX_PLAYBACK_CONTROL)
                label = {
                    "connect": "Connect Apple Music",
                    "play": "Play",
                    "pause": "Pause",
                    "stop": "Stop",
                    "skip": "Skip",
                    "restart_playlist": "Restart Playlist",
                }.get(requested_command, requested_command.title())
                if queue_item_id:
                    targeted_item = find_jukebox_queue_item(queue_item_id)
                    if targeted_item:
                        label = f"Play {targeted_item.get('title')}"
                messages.append(f"Sent DJ command to the live display: {label}.")
                should_broadcast = True

        elif action in {"move_jukebox_queue_item_up", "move_jukebox_queue_item_down", "remove_jukebox_queue_item"}:
            queue_item_id = request.form.get("queue_item_id", "").strip()
            queue_index = find_jukebox_queue_index(queue_item_id)
            if queue_index is None:
                errors.append("Jukebox playlist song could not be found.")
            elif action == "remove_jukebox_queue_item":
                removed_item = copy.deepcopy(jukebox_queue[queue_index])
                request_id = str(removed_item.get("request_id", "") or "")
                source = str(removed_item.get("source", "") or "playlist")
                was_now_playing = str(jukebox_now_playing.get("id", "") or "") == queue_item_id
                removed_playlist_count = 0
                removed_request_count = 0
                remove_jukebox_queue_rows_for_item(removed_item, queue_item_id)
                if source == "playlist":
                    removed_playlist_count = remove_matching_active_playlist_tracks(removed_item)
                if request_id:
                    removed_request_count = remove_matching_jukebox_requests(removed_item, request_id)
                if was_now_playing:
                    jukebox_now_playing = {}
                if source == "playlist" and removed_playlist_count:
                    regenerate_jukebox_queue()
                if not queued_jukebox_items():
                    jukebox_now_playing = {}
                    if was_now_playing:
                        jukebox_playback_control = issue_jukebox_dj_command("stop")
                if source == "request" and not removed_request_count:
                    removed_request_count = remove_matching_jukebox_requests(removed_item)
                if removed_playlist_count or removed_request_count or source not in {"playlist", "request"}:
                    messages.append(f"Removed {removed_item.get('title')} from the active playlist.")
                    should_broadcast = True
                else:
                    errors.append("That jukebox song could not be removed from the saved playlist.")
            else:
                active_indices = active_jukebox_queue_indices()
                active_position = active_indices.index(queue_index) if queue_index in active_indices else None
                if active_position is None:
                    errors.append("Only active playlist songs can be reordered.")
                elif action == "move_jukebox_queue_item_up":
                    if active_position == 0:
                        messages.append("That active playlist song is already at the top.")
                    else:
                        swap_index = active_indices[active_position - 1]
                        jukebox_queue[swap_index], jukebox_queue[queue_index] = (
                            jukebox_queue[queue_index],
                            jukebox_queue[swap_index],
                        )
                        moving_playlist_track_id = str(jukebox_queue[swap_index].get("playlist_track_id", "") or "")
                        swapped_playlist_track_id = str(jukebox_queue[queue_index].get("playlist_track_id", "") or "")
                        if moving_playlist_track_id and swapped_playlist_track_id:
                            playlist_indices = {
                                str(track.get("id", "")): index for index, track in enumerate(jukebox_playlist)
                            }
                            moving_playlist_index = playlist_indices.get(moving_playlist_track_id)
                            swapped_playlist_index = playlist_indices.get(swapped_playlist_track_id)
                            if moving_playlist_index is not None and swapped_playlist_index is not None:
                                jukebox_playlist[moving_playlist_index], jukebox_playlist[swapped_playlist_index] = (
                                    jukebox_playlist[swapped_playlist_index],
                                    jukebox_playlist[moving_playlist_index],
                                )
                                active_playlist = active_jukebox_playlist()
                                if active_playlist:
                                    active_playlist["updated_at"] = _utc_now_iso()
                        messages.append("Moved active playlist song up.")
                        should_broadcast = True
                elif action == "move_jukebox_queue_item_down":
                    if active_position == len(active_indices) - 1:
                        messages.append("That active playlist song is already at the bottom.")
                    else:
                        swap_index = active_indices[active_position + 1]
                        jukebox_queue[swap_index], jukebox_queue[queue_index] = (
                            jukebox_queue[queue_index],
                            jukebox_queue[swap_index],
                        )
                        moving_playlist_track_id = str(jukebox_queue[swap_index].get("playlist_track_id", "") or "")
                        swapped_playlist_track_id = str(jukebox_queue[queue_index].get("playlist_track_id", "") or "")
                        if moving_playlist_track_id and swapped_playlist_track_id:
                            playlist_indices = {
                                str(track.get("id", "")): index for index, track in enumerate(jukebox_playlist)
                            }
                            moving_playlist_index = playlist_indices.get(moving_playlist_track_id)
                            swapped_playlist_index = playlist_indices.get(swapped_playlist_track_id)
                            if moving_playlist_index is not None and swapped_playlist_index is not None:
                                jukebox_playlist[moving_playlist_index], jukebox_playlist[swapped_playlist_index] = (
                                    jukebox_playlist[swapped_playlist_index],
                                    jukebox_playlist[moving_playlist_index],
                                )
                                active_playlist = active_jukebox_playlist()
                                if active_playlist:
                                    active_playlist["updated_at"] = _utc_now_iso()
                        messages.append("Moved active playlist song down.")
                        should_broadcast = True

        elif action in {"remove_jukebox_track", "move_jukebox_track_up", "move_jukebox_track_down"}:
            track_id = request.form.get("track_id", "").strip()
            track_index = next(
                (index for index, item in enumerate(jukebox_playlist) if str(item.get("id", "")) == track_id),
                None,
            )
            if track_index is None:
                errors.append("Jukebox playlist song could not be found.")
            elif action == "remove_jukebox_track":
                updated_tracks = list(jukebox_playlist)
                removed_track = updated_tracks.pop(track_index)
                set_active_jukebox_playlist_tracks(updated_tracks)
                regenerate_jukebox_queue()
                messages.append(f"Removed {removed_track.get('title')} from the active playlist.")
                should_broadcast = True
            elif action == "move_jukebox_track_up":
                if track_index == 0:
                    messages.append("That jukebox song is already at the top.")
                else:
                    jukebox_playlist[track_index - 1], jukebox_playlist[track_index] = (
                        jukebox_playlist[track_index],
                        jukebox_playlist[track_index - 1],
                    )
                    active_playlist = active_jukebox_playlist()
                    if active_playlist:
                        active_playlist["updated_at"] = _utc_now_iso()
                    regenerate_jukebox_queue()
                    messages.append("Moved active playlist song up.")
                    should_broadcast = True
            elif action == "move_jukebox_track_down":
                if track_index == len(jukebox_playlist) - 1:
                    messages.append("That jukebox song is already at the bottom.")
                else:
                    jukebox_playlist[track_index + 1], jukebox_playlist[track_index] = (
                        jukebox_playlist[track_index],
                        jukebox_playlist[track_index + 1],
                    )
                    active_playlist = active_jukebox_playlist()
                    if active_playlist:
                        active_playlist["updated_at"] = _utc_now_iso()
                    regenerate_jukebox_queue()
                    messages.append("Moved active playlist song down.")
                    should_broadcast = True

        elif action in {"approve_jukebox_request", "reject_jukebox_request", "skip_jukebox_request"}:
            request_id = request.form.get("request_id", "").strip()
            request_item = find_jukebox_request(request_id)
            if not request_item:
                errors.append("Jukebox request could not be found.")
            elif action == "approve_jukebox_request":
                request_item["status"] = "approved"
                request_item["decided_at"] = _utc_now_iso()
                regenerate_jukebox_queue()
                messages.append(f"Approved request and added it into the active playlist queue: {request_item.get('title')}.")
                should_broadcast = True
            elif action == "reject_jukebox_request":
                removed_item = copy.deepcopy(request_item)
                remove_matching_jukebox_requests(removed_item, request_id)
                remove_jukebox_queue_rows_for_item(
                    {
                        **removed_item,
                        "source": "request",
                        "request_id": request_id,
                    },
                )
                messages.append(f"Rejected jukebox request: {request_item.get('title')}.")
                should_broadcast = True
            elif action == "skip_jukebox_request":
                request_item["status"] = "skipped"
                request_item["played_at"] = _utc_now_iso()
                for queue_item in jukebox_queue:
                    if str(queue_item.get("request_id", "")) == request_id and queue_item.get("status") in {"queued", "playing"}:
                        queue_item["status"] = "skipped"
                        queue_item["played_at"] = request_item["played_at"]
                messages.append(f"Skipped jukebox request: {request_item.get('title')}.")
                should_broadcast = True

        elif action == "reset_jukebox_playlist":
            reset_jukebox_playlist_queue()
            messages.append("Active playlist reset. Songs and approved requests were rebuilt without deleting playlist songs.")
            should_broadcast = True

        elif action == "restart_jukebox_playlist":
            restart_jukebox_playlist()
            messages.append("Active playlist restarted from the beginning and sent to the live display.")
            should_broadcast = True

        elif action == "clear_jukebox_queue":
            jukebox_queue = []
            jukebox_now_playing = {}
            for request_item in jukebox_requests:
                if request_item.get("status") in {"queued", "playing"}:
                    request_item["status"] = "approved"
            messages.append("Jukebox queue cleared. Approved requests were kept for the next regeneration.")
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
            existing_signup = karaoke_signups[index] if index is not None else None
            youtube_metadata = karaoke_signup_video_metadata_from_form(existing_signup)

            if not name:
                errors.append("Karaoke signup name is required.")
            if not song_title:
                errors.append("Song title is required.")
            if not artist:
                errors.append("Artist is required.")

            if index is not None and name and song_title and artist:
                karaoke_signups[index] = KaraokeSignup(
                    id=karaoke_signups[index].id,
                    name=name,
                    song_title=song_title,
                    artist=artist,
                    youtube_link=youtube_metadata["youtube_link"] or youtube_link,
                    youtube_video_id=youtube_metadata["youtube_video_id"],
                    youtube_watch_url=youtube_metadata["youtube_watch_url"],
                    youtube_embed_status=youtube_metadata["youtube_embed_status"],
                    youtube_title=youtube_metadata["youtube_title"],
                    youtube_channel=youtube_metadata["youtube_channel"],
                    youtube_thumbnail_url=youtube_metadata["youtube_thumbnail_url"],
                    youtube_duration=youtube_metadata["youtube_duration"],
                    youtube_last_checked_at=youtube_metadata["youtube_last_checked_at"],
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
                removed = karaoke_signups.pop(index)
                if karaoke_state.get("current_singer_id") == removed.id:
                    karaoke_state["current_singer_id"] = None
                    karaoke_state["current_singer_index"] = None
                    if (
                        live_display_event_override
                        and live_display_event_override.get("type") == "karaoke_stage"
                        and live_display_event_override.get("singer_id") == removed.id
                    ):
                        live_display_event_override = None
                messages.append(f"Removed karaoke signup for {removed.name}.")
                should_broadcast = True

        elif action == "add_karaoke":
            name = request.form.get("name", "").strip()
            song_title = request.form.get("song_title", "").strip()
            artist = request.form.get("artist", "").strip()
            youtube_link = request.form.get("youtube_link", "").strip()
            youtube_metadata = karaoke_signup_video_metadata_from_form()

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
                        youtube_link=youtube_metadata["youtube_link"] or youtube_link,
                        youtube_video_id=youtube_metadata["youtube_video_id"],
                        youtube_watch_url=youtube_metadata["youtube_watch_url"],
                        youtube_embed_status=youtube_metadata["youtube_embed_status"],
                        youtube_title=youtube_metadata["youtube_title"],
                        youtube_channel=youtube_metadata["youtube_channel"],
                        youtube_thumbnail_url=youtube_metadata["youtube_thumbnail_url"],
                        youtube_duration=youtube_metadata["youtube_duration"],
                        youtube_last_checked_at=youtube_metadata["youtube_last_checked_at"],
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
            if karaoke_signups:
                karaoke_state["party_started"] = True
                karaoke_state["current_singer_index"] = 0
                karaoke_state["current_singer_id"] = karaoke_signups[0].id if karaoke_signups else None
                karaoke_state["stage_mode"] = "intro"
                contest_state["contest_started"] = False
                contest_state["voting_open"] = False
                live_display_event_override = build_karaoke_stage_override(
                    karaoke_signups[0], mode="intro", lineup_index=0
                )
                messages.append(
                    f"Live display staged {karaoke_signups[0].name} as the opening karaoke singer."
                )
                write_state_backup_if_available("karaoke-start")
                should_broadcast = True
            else:
                errors.append(
                    "Add at least one karaoke signup before starting the karaoke party."
                )

        elif action in {"set_karaoke_stage", "start_karaoke_song"}:
            index = parse_entry_index(
                karaoke_signups,
                "karaoke signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            if index is not None:
                signup = karaoke_signups[index]
                requested_mode = "video" if action == "start_karaoke_song" else "intro"
                if requested_mode == "video" and signup.youtube_embed_status != "verified_embeddable":
                    errors.append(
                        f"{signup.name}'s YouTube video is not marked playable on the live display."
                    )
                else:
                    karaoke_state["party_started"] = True
                    karaoke_state["current_singer_index"] = index
                    karaoke_state["current_singer_id"] = signup.id
                    karaoke_state["stage_mode"] = requested_mode
                    contest_state["contest_started"] = False
                    contest_state["voting_open"] = False
                    live_display_event_override = build_karaoke_stage_override(
                        signup, mode=requested_mode, lineup_index=index
                    )
                    if requested_mode == "video":
                        messages.append(f"Live display is playing {signup.name}'s karaoke video.")
                    else:
                        messages.append(f"Live display staged {signup.name}.")
                    write_state_backup_if_available(f"karaoke-{requested_mode}")
                    should_broadcast = True

        elif action == "next_karaoke_singer":
            if not karaoke_signups:
                errors.append("Add at least one karaoke signup before advancing singers.")
            else:
                current_index = find_karaoke_signup_index(str(karaoke_state.get("current_singer_id") or ""))
                next_index = 0 if current_index is None else current_index + 1
                if next_index >= len(karaoke_signups):
                    errors.append("There are no more singers in the karaoke lineup.")
                else:
                    signup = karaoke_signups[next_index]
                    karaoke_state["party_started"] = True
                    karaoke_state["current_singer_index"] = next_index
                    karaoke_state["current_singer_id"] = signup.id
                    karaoke_state["stage_mode"] = "intro"
                    live_display_event_override = build_karaoke_stage_override(
                        signup, mode="intro", lineup_index=next_index
                    )
                    messages.append(f"Live display advanced to {signup.name}.")
                    write_state_backup_if_available("karaoke-next")
                    should_broadcast = True

        elif action == "return_karaoke_stage_intro":
            current_index = find_karaoke_signup_index(str(karaoke_state.get("current_singer_id") or ""))
            if current_index is None:
                errors.append("Choose a karaoke singer before returning to the stage card.")
            else:
                signup = karaoke_signups[current_index]
                karaoke_state["stage_mode"] = "intro"
                live_display_event_override = build_karaoke_stage_override(
                    signup, mode="intro", lineup_index=current_index
                )
                messages.append(f"Live display returned to {signup.name}'s stage card.")
                write_state_backup_if_available("karaoke-intro")
                should_broadcast = True

        elif action == "stop_karaoke_party":
            karaoke_state["party_started"] = False
            karaoke_state["current_singer_index"] = None
            karaoke_state["current_singer_id"] = None
            karaoke_state["stage_mode"] = "intro"
            if live_display_event_override and live_display_event_override.get("type") in {
                "karaoke_start",
                "karaoke_stage",
            }:
                live_display_event_override = None
            messages.append("Karaoke party stopped.")
            write_state_backup_if_available("karaoke-stop")
            should_broadcast = True

        elif action == "reset_karaoke_party":
            karaoke_state.clear()
            karaoke_state.update(copy.deepcopy(DEFAULT_KARAOKE_STATE))
            if live_display_event_override and live_display_event_override.get("type") in {
                "karaoke_start",
                "karaoke_stage",
            }:
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

        elif action == "move_karaoke_up":
            index = parse_entry_index(
                karaoke_signups,
                "karaoke signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            if index is not None:
                if index == 0:
                    messages.append("Karaoke signup is already at the top.")
                else:
                    moved_signup = karaoke_signups[index]
                    karaoke_signups[index - 1], karaoke_signups[index] = (
                        karaoke_signups[index],
                        karaoke_signups[index - 1],
                    )
                    messages.append(f"Moved karaoke signup for {moved_signup.name} up.")
                    should_broadcast = True

        elif action == "move_karaoke_down":
            index = parse_entry_index(
                karaoke_signups,
                "karaoke signup",
                request.form.get("entry_id"),
                request.form.get("index"),
            )
            if index is not None:
                if index == len(karaoke_signups) - 1:
                    messages.append("Karaoke signup is already at the bottom.")
                else:
                    moved_signup = karaoke_signups[index]
                    karaoke_signups[index + 1], karaoke_signups[index] = (
                        karaoke_signups[index],
                        karaoke_signups[index + 1],
                    )
                    messages.append(f"Moved karaoke signup for {moved_signup.name} down.")
                    should_broadcast = True

        else:
            errors.append("Unknown action submitted. Please try again.")

        ensure_costume_votes_alignment()

        if should_broadcast:
            broadcast_display_update()

    costume_scores, costume_leader = build_costume_scoreboard()
    top_costume_rankings = rank_costume_entries(costume_scores)[:5]
    current_karaoke_index = find_karaoke_signup_index(str(karaoke_state.get("current_singer_id") or ""))
    current_karaoke_signup = (
        karaoke_signups[current_karaoke_index] if current_karaoke_index is not None else None
    )
    ensure_jukebox_playlists()
    current_jukebox_queue = queued_jukebox_items()
    active_jukebox_duration_ms = active_jukebox_queue_duration_ms()
    jukebox_request_queue_positions = {
        str(item.get("request_id", "")): index
        for index, item in enumerate(current_jukebox_queue, start=1)
        if str(item.get("request_id", ""))
    }
    current_active_playlist = active_jukebox_playlist() or {}

    return render_template(
        "admin.html",
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
        current_karaoke_signup=current_karaoke_signup,
        current_karaoke_index=current_karaoke_index,
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
        youtube_api_configured=youtube_api_key_is_configured(),
        youtube_api_key_source=youtube_api_key_source(),
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
        jukebox_settings=jukebox_settings,
        jukebox_playlist=jukebox_playlist,
        jukebox_playlists=jukebox_playlist_summaries(),
        jukebox_active_playlist_id=jukebox_active_playlist_id,
        jukebox_active_playlist_name=str(current_active_playlist.get("name", "") or DEFAULT_JUKEBOX_PLAYLIST_NAME),
        jukebox_requests=sorted(
            jukebox_requests,
            key=lambda request_item: str(request_item.get("submitted_at", "")),
            reverse=True,
        ),
        jukebox_queue=current_jukebox_queue,
        jukebox_active_duration_ms=active_jukebox_duration_ms,
        jukebox_active_duration_label=jukebox_duration_label(active_jukebox_duration_ms),
        jukebox_duration_label=jukebox_duration_label,
        jukebox_request_queue_positions=jukebox_request_queue_positions,
        jukebox_now_playing=jukebox_now_playing,
        jukebox_playback_control=normalize_jukebox_playback_control(jukebox_playback_control),
        jukebox_developer_token_configured=jukebox_developer_token_configured(),
        user_accounts=user_accounts,
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

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        song_title = request.form.get("song_title", "").strip()
        artist = request.form.get("artist", "").strip()
        youtube_link = request.form.get("youtube_link", "").strip()
        youtube_metadata = karaoke_signup_video_metadata_from_form()

        if not name:
            errors.append("Name is required.")
        if not song_title:
            errors.append("Song title is required.")
        if not artist:
            errors.append("Artist is required.")

        if not errors:
            karaoke_signups.append(
                KaraokeSignup(
                    id=uuid4().hex,
                    name=name,
                    song_title=song_title,
                    artist=artist,
                    youtube_link=youtube_metadata["youtube_link"] or youtube_link,
                    youtube_video_id=youtube_metadata["youtube_video_id"],
                    youtube_watch_url=youtube_metadata["youtube_watch_url"],
                    youtube_embed_status=youtube_metadata["youtube_embed_status"],
                    youtube_title=youtube_metadata["youtube_title"],
                    youtube_channel=youtube_metadata["youtube_channel"],
                    youtube_thumbnail_url=youtube_metadata["youtube_thumbnail_url"],
                    youtube_duration=youtube_metadata["youtube_duration"],
                    youtube_last_checked_at=youtube_metadata["youtube_last_checked_at"],
                )
            )
            submitted = True
            broadcast_display_update()
            return redirect(url_for("party_karaoke", success="1"))

    if request.args.get("success") == "1":
        submitted = True

    return render_template(
        "karaoke_signup.html",
        errors=errors,
        submitted=submitted,
        karaoke_signups=karaoke_signups,
        show_admin_link=False,
    )


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
