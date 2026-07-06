from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from threading import Condition, Thread
from urllib.parse import unquote, urlparse
from uuid import uuid4
import copy
import io
import json
import os
import time

import redis

from flask import (
    Flask,
    Response,
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


STATE_SCHEMA_VERSION = 1


@dataclass
class CostumeSignup:
    name: str
    costume: str
    contact: str = ""


@dataclass
class KaraokeSignup:
    name: str
    song_title: str
    artist: str
    youtube_link: str = ""


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
}


# Redis is the persistence target. These globals remain as the process-local
# state cache while the app is migrated route by route.
costume_signups: List[CostumeSignup] = []
karaoke_signups: List[KaraokeSignup] = []
costume_votes: List[List[int]] = []
registered_users: dict[str, str] = {}
submitted_costume_votes: set[str] = set()
live_display_override: dict[str, object] | None = None

display_update_condition = Condition()
display_update_version = 0


contest_state: dict[str, object] = copy.deepcopy(DEFAULT_CONTEST_STATE)
karaoke_state: dict[str, object] = copy.deepcopy(DEFAULT_KARAOKE_STATE)
redis_state_available = False
display_pubsub_listener_started = False
STATE_MUTATION_ENDPOINTS = {
    "halloween_login",
    "admin_portal",
    "costume_signup",
    "karaoke_signup",
    "costume_voting_page",
}
STATE_LOCK_TIMEOUT_SECONDS = 10
STATE_BACKUP_TTL_SECONDS = 60 * 60 * 24 * 30


def broadcast_display_update() -> None:
    global display_update_version
    with display_update_condition:
        display_update_version += 1
        persist_state_if_available()
        publish_display_update("state-change")
        display_update_condition.notify_all()


def ensure_costume_votes_alignment() -> None:
    while len(costume_votes) < len(costume_signups):
        costume_votes.append([])
    while len(costume_votes) > len(costume_signups):
        costume_votes.pop()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def costume_signup_to_dict(signup: CostumeSignup) -> dict[str, str]:
    return {
        "name": signup.name,
        "costume": signup.costume,
        "contact": signup.contact,
    }


def costume_signup_from_dict(data: dict[str, object]) -> CostumeSignup:
    return CostumeSignup(
        name=str(data.get("name", "") or ""),
        costume=str(data.get("costume", "") or ""),
        contact=str(data.get("contact", "") or ""),
    )


def karaoke_signup_to_dict(signup: KaraokeSignup) -> dict[str, str]:
    return {
        "name": signup.name,
        "song_title": signup.song_title,
        "artist": signup.artist,
        "youtube_link": signup.youtube_link,
    }


def karaoke_signup_from_dict(data: dict[str, object]) -> KaraokeSignup:
    return KaraokeSignup(
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


def snapshot_state() -> dict[str, object]:
    ensure_costume_votes_alignment()

    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "costume_signups": [
            costume_signup_to_dict(signup) for signup in costume_signups
        ],
        "karaoke_signups": [
            karaoke_signup_to_dict(signup) for signup in karaoke_signups
        ],
        "costume_votes": copy.deepcopy(costume_votes),
        "registered_users": copy.deepcopy(registered_users),
        "submitted_costume_votes": sorted(submitted_costume_votes),
        "contest_state": copy.deepcopy(contest_state),
        "karaoke_state": copy.deepcopy(karaoke_state),
        "live_display_override": copy.deepcopy(live_display_override),
        "display_update_version": display_update_version,
        "updated_at": _utc_now_iso(),
    }


def apply_state_snapshot(data: dict[str, object]) -> None:
    global costume_signups, karaoke_signups, costume_votes, registered_users
    global submitted_costume_votes, live_display_override, display_update_version

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

    costume_votes = _normalize_vote_rows(data.get("costume_votes"))

    raw_registered_users = data.get("registered_users", {})
    if isinstance(raw_registered_users, dict):
        registered_users = {
            str(user_id): str(username)
            for user_id, username in raw_registered_users.items()
        }
    else:
        registered_users = {}

    raw_submitted_votes = data.get("submitted_costume_votes", [])
    if isinstance(raw_submitted_votes, list):
        submitted_costume_votes = {str(user_id) for user_id in raw_submitted_votes}
    else:
        submitted_costume_votes = set()

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

    raw_override = data.get("live_display_override")
    live_display_override = copy.deepcopy(raw_override) if isinstance(raw_override, dict) else None

    try:
        display_update_version = int(data.get("display_update_version", 0) or 0)
    except (TypeError, ValueError):
        display_update_version = 0

    ensure_costume_votes_alignment()


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
        "current_singer_index": karaoke_state.get("current_singer_index"),
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
        blocking_timeout=None,
        thread_local=False,
    )

    state_lock.acquire(blocking=True)

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
            persist_state_if_available()
        finally:
            release_state_lock(state_lock)
            g.redis_state_lock = None
            g.redis_state_lock_owned = False

    return response


def build_costume_scoreboard() -> Tuple[List[dict[str, object]], dict[str, object] | None]:
    ensure_costume_votes_alignment()

    scoreboard: List[dict[str, object]] = []
    max_average = 0.0
    leader_index: int | None = None

    for index, signup in enumerate(costume_signups):
        votes = costume_votes[index] if index < len(costume_votes) else []
        total = sum(votes)
        vote_count = len(votes)
        average = total / vote_count if vote_count else 0.0

        entry = {
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

    rotation_entries: List[dict[str, object]] = [
        {
            "category": "Signup Portal",
            "primary": "Get guests connected and ready to register.",
            "secondary": "Share the WiFi credentials and direct them to the Halloween signup page.",
            "cta": True,
            "link": "http://tnq.com/halloween",
            "link_label": "Open the signup portal",
            "cta_details": {
                "lede": "Sign Up Instructions!",
                "wifi_network": "Halloween Party WiFi",
                "wifi_password": "halloween",
                "portal_url": "http://tnq.com/halloween",
                "portal_label": "http://tnq.com/halloween",
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
            "category": "Costume Contest",
            "primary": signup.name,
            "secondary": f"Dressed as {signup.costume}",
            "tertiary": f"Contact: {signup.contact}" if signup.contact else "",
        }
        for signup in costume_signups
    ]

    karaoke_entries = [
        {
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
    return redirect(url_for("live_display"))


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
        }
    )


@app.context_processor
def inject_contest_state():
    return {
        "costume_contest_state": {
            "voting_open": bool(contest_state.get("voting_open")),
            "winner_locked": bool(contest_state.get("winner_locked")),
            "winner": contest_state.get("winner"),
        }
    }


@app.route("/halloween")
def halloween_overview():
    if "user_id" not in session or "username" not in session:
        return redirect(url_for("halloween_login", next=url_for("halloween_overview")))

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


@app.route("/halloween/login", methods=["GET", "POST"])
def halloween_login():
    errors: List[str] = []
    next_page = request.args.get("next") or url_for("halloween_overview")

    if request.method == "POST":
        provided_next = request.form.get("next")
        if provided_next:
            next_page = provided_next

        username = request.form.get("username", "").strip()

        if not username:
            errors.append("Please share your name so we know who has checked in.")
        else:
            user_id = session.get("user_id")
            if not user_id:
                user_id = uuid4().hex

            session["user_id"] = user_id
            session["username"] = username
            registered_users[user_id] = username
            persist_state_if_available()

            return redirect(next_page)

    return render_template(
        "halloween_login.html",
        errors=errors,
        next_page=next_page,
        show_admin_link=False,
    )


@app.route("/admin", methods=["GET", "POST"])
def admin_portal():
    errors: List[str] = []
    messages: List[str] = []
    global live_display_override, submitted_costume_votes, karaoke_state

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

    if request.method == "POST":
        action = request.form.get("action", "")
        should_broadcast = False

        if action == "update_costume":
            index = parse_index(request.form.get("index"), len(costume_signups), "costume signup")
            name = request.form.get("name", "").strip()
            costume = request.form.get("costume", "").strip()
            contact = request.form.get("contact", "").strip()

            if not name:
                errors.append("Costume signup name is required.")
            if not costume:
                errors.append("Costume description is required.")

            if index is not None and name and costume:
                costume_signups[index] = CostumeSignup(name=name, costume=costume, contact=contact)
                messages.append(f"Updated costume signup for {name}.")
                should_broadcast = True

        elif action == "delete_costume":
            index = parse_index(request.form.get("index"), len(costume_signups), "costume signup")
            if index is not None:
                removed = costume_signups.pop(index)
                costume_votes.pop(index)
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

            if name and costume:
                costume_signups.append(CostumeSignup(name=name, costume=costume, contact=contact))
                costume_votes.append([])
                messages.append(f"Added costume signup for {name}.")
                should_broadcast = True

        elif action == "update_karaoke":
            index = parse_index(request.form.get("index"), len(karaoke_signups), "karaoke signup")
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
                    name=name,
                    song_title=song_title,
                    artist=artist,
                    youtube_link=youtube_link,
                )
                messages.append(f"Updated karaoke signup for {name}.")
                should_broadcast = True

        elif action == "delete_karaoke":
            index = parse_index(request.form.get("index"), len(karaoke_signups), "karaoke signup")
            if index is not None:
                removed = karaoke_signups.pop(index)
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
                        name=name,
                        song_title=song_title,
                        artist=artist,
                        youtube_link=youtube_link,
                    )
                )
                messages.append(f"Added karaoke signup for {name}.")
                should_broadcast = True

        elif action == "move_costume_up":
            index = parse_index(request.form.get("index"), len(costume_signups), "costume signup")
            if index is not None:
                if index == 0:
                    messages.append("Costume signup is already at the top.")
                else:
                    moved_signup = costume_signups[index]
                    costume_signups[index - 1], costume_signups[index] = (
                        costume_signups[index],
                        costume_signups[index - 1],
                    )
                    costume_votes[index - 1], costume_votes[index] = (
                        costume_votes[index],
                        costume_votes[index - 1],
                    )
                    messages.append(f"Moved costume signup for {moved_signup.name} up.")
                    should_broadcast = True

        elif action == "move_costume_down":
            index = parse_index(request.form.get("index"), len(costume_signups), "costume signup")
            if index is not None:
                if index == len(costume_signups) - 1:
                    messages.append("Costume signup is already at the bottom.")
                else:
                    moved_signup = costume_signups[index]
                    costume_signups[index + 1], costume_signups[index] = (
                        costume_signups[index],
                        costume_signups[index + 1],
                    )
                    costume_votes[index + 1], costume_votes[index] = (
                        costume_votes[index],
                        costume_votes[index + 1],
                    )
                    messages.append(f"Moved costume signup for {moved_signup.name} down.")
                    should_broadcast = True

        elif action == "start_costume_contest":
            voting_url = url_for("costume_voting_page", _external=True)
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
                        "name": signup.name,
                        "song_title": signup.song_title,
                        "artist": signup.artist,
                    }
                    for signup in karaoke_signups
                ]

                karaoke_state["party_started"] = True
                karaoke_state["current_singer_index"] = None

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
                    "name": leader["name"],
                    "costume": leader["costume"],
                    "average": leader["average"],
                    "count": leader["count"],
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
            index = parse_index(request.form.get("index"), len(karaoke_signups), "karaoke signup")
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
            index = parse_index(request.form.get("index"), len(karaoke_signups), "karaoke signup")
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


@app.route("/costume-signup", methods=["GET", "POST"])
def costume_signup():
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
            costume_signups.append(CostumeSignup(name=name, costume=costume, contact=contact))
            costume_votes.append([])
            submitted = True
            broadcast_display_update()
            return redirect(url_for("costume_signup", success="1"))

    if request.args.get("success") == "1":
        submitted = True

    return render_template(
        "costume_signup.html",
        errors=errors,
        submitted=submitted,
        costume_signups=costume_signups,
        show_admin_link=False,
    )


@app.route("/karaoke-signup", methods=["GET", "POST"])
def karaoke_signup():
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
                    name=name,
                    song_title=song_title,
                    artist=artist,
                    youtube_link=youtube_link,
                )
            )
            submitted = True
            broadcast_display_update()
            return redirect(url_for("karaoke_signup", success="1"))

    if request.args.get("success") == "1":
        submitted = True

    return render_template(
        "karaoke_signup.html",
        errors=errors,
        submitted=submitted,
        karaoke_signups=karaoke_signups,
        show_admin_link=False,
    )


@app.route("/costume-voting", methods=["GET", "POST"])
def costume_voting_page():
    errors: List[str] = []
    submitted = False

    ensure_costume_votes_alignment()

    if not contest_state.get("voting_open") or contest_state.get("winner_locked"):
        return redirect(url_for("halloween_overview"))

    user_id = session.get("user_id")
    username = session.get("username")

    if not user_id or user_id not in registered_users:
        return redirect(url_for("halloween_login", next=url_for("costume_voting_page")))

    user_has_voted = user_id in submitted_costume_votes
    submitted = user_has_voted

    if request.method == "POST":
        if user_has_voted:
            errors.append("Our records show you've already submitted your costume contest scores. Thank you!")
        elif not costume_signups:
            errors.append("There are no costume entries to rate yet.")
        else:
            ratings: List[int] = []
            for index, signup in enumerate(costume_signups):
                field_name = f"rating_{index}"
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

                ratings.append(rating_value)

            if not errors:
                for index, rating in enumerate(ratings):
                    costume_votes[index].append(rating)

                submitted_costume_votes.add(user_id)
                broadcast_display_update()

                return redirect(url_for("costume_voting_page", success="1"))

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
