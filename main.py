from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from threading import Condition, Thread
from urllib.parse import quote_plus, unquote, urlparse
from uuid import uuid4
import copy
import io
import json
import os
import time

import redis
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
app.config["PARTY_START"] = os.environ.get("HALLOWEEN_PARTY_START", "2026-10-31T19:00:00-06:00")
app.config["PARTY_DATE_LABEL"] = os.environ.get("HALLOWEEN_PARTY_DATE_LABEL", "Saturday, October 31")
app.config["PARTY_TIME_LABEL"] = os.environ.get("HALLOWEEN_PARTY_TIME_LABEL", "7:00 PM until late")
app.config["PARTY_LOCATION_LABEL"] = os.environ.get("HALLOWEEN_PARTY_LOCATION_LABEL", "Qiana and Tony's place")
app.config["PARTY_OVERVIEW"] = os.environ.get(
    "HALLOWEEN_PARTY_OVERVIEW",
    "Costumes encouraged, karaoke expected, dramatic entrances welcomed.",
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


@dataclass
class RSVPSignup:
    name: str
    contact: str = ""
    guest_count: int = 1
    note: str = ""
    created_at: str = ""
    id: str = ""


@dataclass
class RSVPUpdate:
    title: str
    message: str
    created_at: str = ""
    id: str = ""


DEFAULT_CONTEST_STATE: dict[str, object] = {
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
}

DEFAULT_PARTY_DETAILS: dict[str, str] = {
    "date": app.config["PARTY_DATE_LABEL"],
    "time": app.config["PARTY_TIME_LABEL"],
    "location": app.config["PARTY_LOCATION_LABEL"],
    "map_address": app.config["PARTY_LOCATION_LABEL"],
    "overview": app.config["PARTY_OVERVIEW"],
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
user_accounts: dict[str, dict[str, str]] = {}
rsvp_signups: List[RSVPSignup] = []
rsvp_updates: List[RSVPUpdate] = []
submitted_costume_votes: set[str] = set()
live_display_override: dict[str, object] | None = None
landing_page_target = DEFAULT_LANDING_PAGE_TARGET
party_code_hash = generate_password_hash(app.config["PARTY_CODE"]) if app.config["PARTY_CODE"] else ""
party_code_hint = ""

display_update_condition = Condition()
display_update_version = 0


contest_state: dict[str, object] = copy.deepcopy(DEFAULT_CONTEST_STATE)
karaoke_state: dict[str, object] = copy.deepcopy(DEFAULT_KARAOKE_STATE)
party_details: dict[str, str] = copy.deepcopy(DEFAULT_PARTY_DETAILS)
redis_state_available = False
display_pubsub_listener_started = False
STATE_MUTATION_ENDPOINTS = {
    "party_login",
    "party_register",
    "rsvp",
    "admin_portal",
    "party_costumes",
    "party_karaoke",
    "party_costume_voting",
}
STATE_REFRESH_ENDPOINTS = {
    "rsvp",
    "admin_portal",
    "party_dashboard",
    "party_costumes",
    "party_karaoke",
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
REGULAR_USER_ENDPOINTS = {
    "party_dashboard",
    "party_costumes",
    "party_karaoke",
    "party_costume_voting",
}
DISPLAY_ENDPOINTS = {
    "live_display",
    "display_updates",
    "display_data",
}
ROLE_LOGIN_ENDPOINTS = {
    "regular": "party_login",
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


def normalize_username(username: str) -> str:
    return " ".join(username.strip().lower().split())


def create_user_account(username: str, password: str) -> dict[str, str]:
    return {
        "id": uuid4().hex,
        "username": username.strip(),
        "password_hash": generate_password_hash(password),
        "created_at": _utc_now_iso(),
    }


def normalize_landing_page_target(raw_target: object) -> str:
    target = str(raw_target or "").strip()
    if target in LANDING_PAGE_TARGETS:
        return target
    return DEFAULT_LANDING_PAGE_TARGET


def landing_page_endpoint() -> str:
    target = normalize_landing_page_target(landing_page_target)
    return LANDING_PAGE_TARGETS[target]["endpoint"]


def party_code_is_configured() -> bool:
    return bool(party_code_hash)


def party_code_is_verified() -> bool:
    return session_has_role("regular") or bool(session.get("party_code_verified"))


def verify_party_code(raw_code: str) -> bool:
    return bool(raw_code) and party_code_is_configured() and check_password_hash(party_code_hash, raw_code)


def render_party_code_gate(
    *,
    errors: list[str] | None = None,
    next_page: str | None = None,
    destination: str = "party",
) -> str:
    return render_template(
        "party_code_gate.html",
        errors=errors or [],
        next_page=next_page or url_for("party_dashboard"),
        destination=destination,
        party_code_configured=party_code_is_configured(),
        party_code_hint=party_code_hint,
        show_admin_link=False,
    )


def rsvp_signup_to_dict(signup: RSVPSignup) -> dict[str, object]:
    return {
        "id": signup.id,
        "name": signup.name,
        "contact": signup.contact,
        "guest_count": signup.guest_count,
        "note": signup.note,
        "created_at": signup.created_at,
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
    }


def karaoke_signup_from_dict(data: dict[str, object]) -> KaraokeSignup:
    return KaraokeSignup(
        id=str(data.get("id", "") or uuid4().hex),
        name=str(data.get("name", "") or ""),
        song_title=str(data.get("song_title", "") or ""),
        artist=str(data.get("artist", "") or ""),
        youtube_link=str(data.get("youtube_link", "") or ""),
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
        "live_display_override": copy.deepcopy(live_display_override),
        "landing_page_target": normalize_landing_page_target(landing_page_target),
        "party_code_hash": party_code_hash,
        "party_code_hint": party_code_hint,
        "display_update_version": display_update_version,
        "updated_at": _utc_now_iso(),
    }


def apply_state_snapshot(data: dict[str, object]) -> None:
    global costume_signups, karaoke_signups, costume_votes, registered_users, rsvp_signups, rsvp_updates
    global user_accounts, costume_ballots, submitted_costume_votes, live_display_override
    global landing_page_target, party_code_hash, party_code_hint, party_details, display_update_version

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
                    "password_hash": password_hash,
                    "created_at": str(raw_account.get("created_at", "") or ""),
                }
    else:
        user_accounts = {}

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

    raw_override = data.get("live_display_override")
    live_display_override = copy.deepcopy(raw_override) if isinstance(raw_override, dict) else None
    landing_page_target = normalize_landing_page_target(data.get("landing_page_target"))
    party_code_hash = str(data.get("party_code_hash", party_code_hash) or "")
    party_code_hint = str(data.get("party_code_hint", party_code_hint) or "").strip()

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
    if endpoint in REGULAR_USER_ENDPOINTS:
        return "regular"
    return None


@app.before_request
def protect_role_routes():
    required_role = required_role_for_endpoint(request.endpoint)
    if not required_role:
        return None

    if session_has_role(required_role):
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


# Demo slides to rotate on the home page
SLIDES = [
    {
        "title": "Tonight's Lineup",
        "content": "Costume contest judging kicks off at 9:30 PM followed by karaoke at 10:15 PM. Make sure you're signed up!",
    },
    {
        "title": "Welcome to the Halloween Bash!",
        "content": "Check out the event schedule and make sure to submit your signups.",
    },
    {
        "title": "Costume Contest Highlights",
        "content": "Show off your creativity! Sign up to compete for spooky bragging rights.",
    },
    {
        "title": "Karaoke Night",
        "content": "Pick your favorite song and take center stage on karaoke night.",
    },
]


def build_rotation_entries() -> List[dict[str, object]]:
    ensure_costume_votes_alignment()

    if not party_has_started():
        pre_party_entries: List[dict[str, object]] = [
            {
                "category": "RSVP",
                "primary": "RSVP for Qiana and Tony's Halloween Party",
                "secondary": "Visit tnq-halloween.com, enter the party code, and let the hosts know you are coming.",
                "cta": True,
                "link": "https://tnq-halloween.com",
                "link_label": "Open the RSVP page",
                "cta_details": {
                    "lede": "RSVP before party night",
                    "wifi_network": "",
                    "wifi_password": "",
                    "portal_url": "tnq-halloween.com",
                    "portal_label": "tnq-halloween.com",
                    "portal_note": "Use the party code from your invite to see details and RSVP.",
                    "reminder": "",
                },
            }
        ]
        for card in party_info_cards():
            pre_party_entries.append(
                {
                    "category": "Party Details",
                    "primary": card["title"],
                    "secondary": card["message"],
                }
            )
        for update in sorted_rsvp_updates():
            pre_party_entries.append(
                {
                    "id": update.id,
                    "category": "RSVP Update",
                    "primary": update.title,
                    "secondary": update.message,
                    "tertiary": update.created_at,
                }
            )
        return pre_party_entries

    rotation_entries: List[dict[str, object]] = [
        {
            "category": "Signup Portal",
            "primary": "Get guests connected and ready to register.",
            "secondary": "Share the WiFi credentials and direct them to the Halloween signup page.",
            "cta": True,
            "link": "http://tnq.com/party",
            "link_label": "Open the signup portal",
            "cta_details": {
                "lede": "Sign Up Instructions!",
                "wifi_network": "Halloween Party WiFi",
                "wifi_password": "halloween",
                "portal_url": "http://tnq.com/party",
                "portal_label": "http://tnq.com/party",
                "portal_note": "Type the address exactly as shown and add a bookmark for quick access later.",
                "reminder": "",
            },
        },
        {
            "category": "Event Spotlight",
            "primary": "Tonight's Lineup",
            "secondary": "Costume contest judging kicks off at 9:30 PM followed by karaoke at 11:00 PM. Make sure you're signed up!",
        },
        {
            "category": "Event Spotlight",
            "primary": "Welcome to the Halloween Bash!",
            "secondary": "Check out the event schedule and make sure to submit your signups.",
        },
        {
            "category": "Event Spotlight",
            "primary": "Costume Contest",
            "secondary": "Summon your most sinister look—compete for spine-tingling glory, devilish loot, and the Trophy of Terror.",
        },
        {
            "category": "Event Spotlight",
            "primary": "Karaoke Night",
            "secondary": "Choose your eerie anthem and send shivers down the spine.",
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


@app.route("/")
def index():
    return redirect(url_for(landing_page_endpoint()))


@app.route("/health")
def health():
    payload, status_code = build_health_payload()
    return jsonify(payload), status_code


@app.route("/live-display")
def live_display():
    rotation_entries = build_rotation_entries()

    return render_template(
        "display.html",
        entries=rotation_entries,
        costume_count=len(costume_signups),
        karaoke_count=len(karaoke_signups),
        override=live_display_override,
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
    rotation_entries = build_rotation_entries()

    return jsonify(
        {
            "entries": rotation_entries,
            "costume_count": len(costume_signups),
            "karaoke_count": len(karaoke_signups),
            "override": live_display_override,
            "display_update_version": display_update_version,
        }
    )


@app.context_processor
def inject_contest_state():
    return {
        "costume_contest_state": {
            "voting_open": bool(contest_state.get("voting_open")),
            "winner_locked": bool(contest_state.get("winner_locked")),
            "winner": contest_state.get("winner"),
        },
        "csrf_token": get_csrf_token,
        "admin_authenticated": bool(session.get("admin_authenticated")),
        "regular_authenticated": session_has_role("regular"),
    }


@app.route("/halloween")
def legacy_halloween_overview():
    return redirect(url_for("party_dashboard"), code=301)


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

    if not party_code_is_verified():
        if request.method == "POST":
            provided_code = request.form.get("party_code", "").strip()
            if verify_party_code(provided_code):
                session["party_code_verified"] = True
                return redirect(url_for("rsvp"))
            if not party_code_is_configured():
                errors.append("The party code is not configured yet. Please ask the hosts.")
            else:
                errors.append("That party code did not match. Please try again.")

        return render_template(
            "rsvp.html",
            errors=errors,
            party_code_verified=False,
            party_code_configured=party_code_is_configured(),
            party_code_hint=party_code_hint,
            submitted_rsvp=submitted_rsvp,
            party_info_cards=party_info_cards(),
            maps_urls=google_maps_urls(party_details.get("map_address", "")),
            rsvp_updates=sorted_rsvp_updates(),
            show_admin_link=False,
        )

    if request.method == "POST" and request.form.get("action") == "submit_rsvp":
        username = request.form.get("username", "").strip()
        contact = request.form.get("contact", "").strip()
        note = request.form.get("note", "").strip()
        try:
            guest_count = int(request.form.get("guest_count", "1") or 1)
        except ValueError:
            guest_count = 1

        if not username:
            errors.append("Name is required.")
        elif len(username) > 80:
            errors.append("Name must be 80 characters or fewer.")
        if len(contact) > 120:
            errors.append("Contact must be 120 characters or fewer.")
        if not 1 <= guest_count <= 12:
            errors.append("Guest count must be between 1 and 12.")
        if len(note) > 240:
            errors.append("Note must be 240 characters or fewer.")

        if not errors:
            submitted_rsvp = RSVPSignup(
                id=uuid4().hex,
                name=username,
                contact=contact,
                guest_count=guest_count,
                note=note,
                created_at=_utc_now_iso(),
            )
            rsvp_signups.append(submitted_rsvp)
            session["rsvp_id"] = submitted_rsvp.id
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
        show_admin_link=False,
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

    slides = list(SLIDES)
    winner = contest_state.get("winner")
    if winner:
        slides.append(
            {
                "title": "Costume Contest Champion",
                "content": f"Congratulations to {winner['name']} for {winner['costume']}! Average score: {winner['average']:.2f}.",
            }
        )

    return render_template(
        "index.html",
        slides=slides,
        costume_signups=costume_signups,
        karaoke_signups=karaoke_signups,
        show_admin_link=False,
    )


@app.route("/party/login", methods=["GET", "POST"])
def party_login():
    errors: List[str] = []
    next_page = normalize_next_page(
        request.args.get("next") or request.form.get("next"),
        url_for("party_dashboard"),
    )

    if not party_code_is_verified():
        if request.method == "POST":
            provided_code = request.form.get("party_code", "").strip()
            if verify_party_code(provided_code):
                session["party_code_verified"] = True
                return redirect(url_for("party_login", next=next_page))
            if not party_code_is_configured():
                errors.append("The party code is not configured yet. Please ask the hosts.")
            else:
                errors.append("That party code did not match. Please try again.")

        return render_party_code_gate(
            errors=errors,
            next_page=next_page,
            destination="sign in",
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
            registered_users[user_id] = display_name
            persist_state_if_available()

            return redirect(next_page)

    return render_template(
        "halloween_login.html",
        errors=errors,
        next_page=next_page,
        show_admin_link=False,
    )


@app.route("/party/register", methods=["GET", "POST"])
def party_register():
    errors: List[str] = []
    next_page = normalize_next_page(
        request.args.get("next") or request.form.get("next"),
        url_for("party_dashboard"),
    )

    if not party_code_is_verified():
        if request.method == "POST":
            provided_code = request.form.get("party_code", "").strip()
            if verify_party_code(provided_code):
                session["party_code_verified"] = True
                return redirect(url_for("party_register", next=next_page))
            if not party_code_is_configured():
                errors.append("The party code is not configured yet. Please ask the hosts.")
            else:
                errors.append("That party code did not match. Please try again.")

        return render_party_code_gate(
            errors=errors,
            next_page=next_page,
            destination="create an account",
        )

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        provided_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        normalized_username = normalize_username(username)

        if not username:
            errors.append("Username is required.")
        elif len(username) > 80:
            errors.append("Username must be 80 characters or fewer.")
        elif normalized_username in user_accounts:
            errors.append("That username is already registered.")

        if len(provided_password) < 8:
            errors.append("Password must be at least 8 characters.")
        elif provided_password != confirm_password:
            errors.append("Passwords do not match.")

        if not errors:
            account = create_user_account(username, provided_password)
            user_accounts[normalized_username] = account
            session["user_id"] = account["id"]
            session["username"] = account["username"]
            grant_session_role("regular")
            registered_users[account["id"]] = account["username"]
            persist_state_if_available()
            return redirect(next_page)

    return render_template(
        "halloween_register.html",
        errors=errors,
        next_page=next_page,
        show_admin_link=False,
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
    global live_display_override, submitted_costume_votes, costume_ballots, karaoke_state
    global landing_page_target, party_code_hash, party_code_hint, party_details

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

        elif action == "update_party_code":
            new_party_code = request.form.get("party_code", "").strip()
            new_party_code_hint = request.form.get("party_code_hint", "").strip()
            if len(new_party_code_hint) > 120:
                errors.append("Party code hint must be 120 characters or fewer.")
            if not new_party_code and not party_code_hash:
                errors.append("Enter a party code before opening guest RSVP or login.")
            if new_party_code and len(new_party_code) < 4:
                errors.append("Party code must be at least 4 characters.")
            if not errors:
                if new_party_code:
                    party_code_hash = generate_password_hash(new_party_code)
                party_code_hint = new_party_code_hint
                messages.append("Party code settings updated.")

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
            elif len(message) > 2000:
                errors.append("RSVP update message must be 2000 characters or fewer.")
            if not errors:
                rsvp_updates.append(
                    RSVPUpdate(
                        id=uuid4().hex,
                        title=title,
                        message=message,
                        created_at=_utc_now_iso(),
                    )
                )
                messages.append("RSVP update posted.")
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
                karaoke_signups[index] = KaraokeSignup(
                    id=karaoke_signups[index].id,
                    name=name,
                    song_title=song_title,
                    artist=artist,
                    youtube_link=youtube_link,
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
            live_display_override = {
                "type": "contest_start",
                "title": "The Costume Contest Has Begun!",
                "highlight": "Submit your votes now",
                "message": "Visit the costume voting page to rate every competitor from 1-10.",
                "details": [
                    f"Open {voting_url} on your device to cast your ballot.",
                ],
            }
            messages.append("Live display updated with costume contest kickoff message.")
            contest_state["voting_open"] = True
            contest_state["winner"] = None
            contest_state["winner_locked"] = False
            contest_state["scoreboard_card"] = None
            contest_state["show_scoreboard_card"] = False
            costume_ballots.clear()
            submitted_costume_votes.clear()
            write_state_backup_if_available("contest-start")
            should_broadcast = True

        elif action == "show_costume_winner":
            winner = contest_state.get("winner")
            if winner:
                live_display_override = {
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
            live_display_override = None
            messages.append("Live display has been restored to the rotating schedule.")
            if contest_state.get("winner_locked") and contest_state.get("scoreboard_card"):
                contest_state["show_scoreboard_card"] = True
            should_broadcast = True

        elif action == "start_karaoke_party":
            if karaoke_signups:
                lineup_entries = [
                    {
                        "id": signup.id,
                        "name": signup.name,
                        "song_title": signup.song_title,
                        "artist": signup.artist,
                    }
                    for signup in karaoke_signups
                ]

                karaoke_state["party_started"] = True
                karaoke_state["current_singer_index"] = None
                karaoke_state["current_singer_id"] = karaoke_signups[0].id if karaoke_signups else None

                mountain_offset = timezone(timedelta(hours=-7), name="MST")
                now_mountain = datetime.now(mountain_offset)
                countdown_target = now_mountain.replace(
                    hour=23, minute=0, second=0, microsecond=0
                )
                if countdown_target <= now_mountain:
                    countdown_target += timedelta(days=1)

                live_display_override = {
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
                    "Add at least one karaoke signup before starting the karaoke party."
                )

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

    return render_template(
        "admin.html",
        costume_signups=costume_signups,
        karaoke_signups=karaoke_signups,
        errors=errors,
        messages=messages,
        show_admin_link=True,
        costume_scores=costume_scores,
        costume_leader=costume_leader,
        live_override=live_display_override,
        top_costume_rankings=top_costume_rankings,
        karaoke_state=karaoke_state,
        costume_lineup_locked=is_costume_lineup_locked_for_voting(),
        landing_page_target=normalize_landing_page_target(landing_page_target),
        landing_page_targets=LANDING_PAGE_TARGETS,
        party_code_configured=party_code_is_configured(),
        party_code_hint=party_code_hint,
        party_details=party_details,
        rsvp_signups=rsvp_signups,
        rsvp_guest_total=sum(signup.guest_count for signup in rsvp_signups),
        rsvp_updates=sorted_rsvp_updates(),
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

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        song_title = request.form.get("song_title", "").strip()
        artist = request.form.get("artist", "").strip()
        youtube_link = request.form.get("youtube_link", "").strip()

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
                    youtube_link=youtube_link,
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

    if not contest_state.get("voting_open") or contest_state.get("winner_locked"):
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
