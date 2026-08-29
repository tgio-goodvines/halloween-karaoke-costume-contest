from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


ACHIEVEMENT_CATALOG: dict[str, dict[str, object]] = {
    "party_attendee": {
        "title": "Party Attendee",
        "description": "Attended a Halloween party.",
        "image": "images/achievements/returning-reveler.png",
        "attendance_count": 1,
    },
    "returning_reveler": {
        "title": "Returning Reveler",
        "description": "Attended two Halloween parties.",
        "image": "images/achievements/returning-reveler.png",
        "attendance_count": 2,
    },
    "seasoned_spirit": {
        "title": "Seasoned Spirit",
        "description": "Attended three Halloween parties.",
        "image": "images/achievements/seasoned-spirit.png",
        "attendance_count": 3,
    },
    "halloween_legend": {
        "title": "Halloween Legend",
        "description": "Attended five Halloween parties.",
        "image": "images/achievements/halloween-legend.png",
        "attendance_count": 5,
    },
    "game_champion": {
        "title": "Game Champion",
        "description": "Won an official party game.",
        "image": "images/achievements/game-champion.png",
    },
    "costume_champion": {
        "title": "Costume Champion",
        "description": "Won an official costume contest.",
        "image": "images/achievements/costume-champion.png",
    },
    "multi_game_master": {
        "title": "Multi-Game Master",
        "description": "Won at least two official party games.",
        "image": "images/achievements/multi-game-master.png",
    },
}

CREDIT_KINDS = {"attendance", "game_win", "costume_win", "custom"}
ARCHIVE_KINDS = {"game", "costume"}
ARCHIVE_STATUSES = {"draft", "official"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def event_id_for_year(year: object) -> str:
    cleaned = "".join(character for character in str(year or "") if character.isdigit())[:4]
    return f"{cleaned or 'unknown'}-halloween"


def normalize_event_editions(
    raw: object,
    *,
    current_year: str,
    current_title: str,
    current_date: str,
) -> dict[str, dict[str, str]]:
    editions: dict[str, dict[str, str]] = {}
    if isinstance(raw, dict):
        for raw_id, raw_edition in raw.items():
            if not isinstance(raw_edition, dict):
                continue
            event_id = str(raw_id or "").strip()[:80]
            year = str(raw_edition.get("year", "") or "").strip()[:12]
            if not event_id or not year:
                continue
            editions[event_id] = {
                "id": event_id,
                "year": year,
                "title": str(raw_edition.get("title", "") or f"Halloween Party {year}").strip()[:160],
                "date": str(raw_edition.get("date", "") or "").strip()[:80],
            }
    current_id = event_id_for_year(current_year)
    editions.setdefault(
        current_id,
        {
            "id": current_id,
            "year": str(current_year),
            "title": str(current_title)[:160],
            "date": str(current_date)[:80],
        },
    )
    return editions


def normalize_result_archives(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    archives: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_archive in raw:
        if not isinstance(raw_archive, dict):
            continue
        archive_id = str(raw_archive.get("id", "") or "").strip()[:160]
        kind = str(raw_archive.get("kind", "") or "")
        event_id = str(raw_archive.get("event_id", "") or "").strip()[:80]
        subject_key = str(raw_archive.get("subject_key", "") or "").strip()[:100]
        if not archive_id or archive_id in seen or kind not in ARCHIVE_KINDS or not event_id or not subject_key:
            continue
        status = str(raw_archive.get("status", "draft") or "draft")
        winner_links = []
        for winner in raw_archive.get("winner_links", []) if isinstance(raw_archive.get("winner_links"), list) else []:
            if not isinstance(winner, dict):
                continue
            winner_links.append(
                {
                    "account_id": str(winner.get("account_id", "") or "")[:120],
                    "public_identity": str(winner.get("public_identity", "") or "Guest").strip()[:80],
                }
            )
        archive = {
            "id": archive_id,
            "event_id": event_id,
            "year": str(raw_archive.get("year", "") or "")[:12],
            "kind": kind,
            "subject_key": subject_key,
            "title": str(raw_archive.get("title", "") or "Results")[:160],
            "image_url": str(raw_archive.get("image_url", "") or "")[:500],
            "winner_image_url": str(raw_archive.get("winner_image_url", "") or "")[:500],
            "status": status if status in ARCHIVE_STATUSES else "draft",
            "simulation": bool(raw_archive.get("simulation")),
            "finalized_at": str(raw_archive.get("finalized_at", "") or "")[:180],
            "published_at": str(raw_archive.get("published_at", "") or "")[:180],
            "summary": raw_archive.get("summary", {}) if isinstance(raw_archive.get("summary"), dict) else {},
            "winner_links": winner_links,
        }
        archives.append(archive)
        seen.add(archive_id)
    return archives


def normalize_recognition_credits(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    credits: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_credit in raw:
        if not isinstance(raw_credit, dict):
            continue
        credit_id = str(raw_credit.get("id", "") or "").strip()[:160]
        kind = str(raw_credit.get("kind", "") or "")
        recipient_name = str(raw_credit.get("recipient_name", "") or "").strip()[:80]
        if not credit_id or credit_id in seen or kind not in CREDIT_KINDS or not recipient_name:
            continue
        credits.append(
            {
                "id": credit_id,
                "kind": kind,
                "account_id": str(raw_credit.get("account_id", "") or "")[:120],
                "recipient_name": recipient_name,
                "public_identity": str(raw_credit.get("public_identity", "") or recipient_name).strip()[:80],
                "event_id": str(raw_credit.get("event_id", "") or "")[:80],
                "year": str(raw_credit.get("year", "") or "")[:12],
                "subject_key": str(raw_credit.get("subject_key", "") or "")[:100],
                "subject_label": str(raw_credit.get("subject_label", "") or "")[:160],
                "achievement_key": str(raw_credit.get("achievement_key", "") or "")[:100],
                "source_ref": str(raw_credit.get("source_ref", "") or "")[:160],
                "note": str(raw_credit.get("note", "") or "")[:500],
                "created_at": str(raw_credit.get("created_at", "") or "")[:180],
                "revoked_at": str(raw_credit.get("revoked_at", "") or "")[:180],
                "revoked_reason": str(raw_credit.get("revoked_reason", "") or "")[:500],
            }
        )
        seen.add(credit_id)
    return credits


def active_credits(credits: list[dict[str, object]]) -> list[dict[str, object]]:
    return [credit for credit in credits if not credit.get("revoked_at")]


def account_credits(credits: list[dict[str, object]], account_id: str) -> list[dict[str, object]]:
    return [credit for credit in active_credits(credits) if str(credit.get("account_id", "")) == account_id]


def achievement_views(credits: list[dict[str, object]], account_id: str) -> dict[str, object]:
    personal = account_credits(credits, account_id)
    attendance = {str(credit.get("event_id", "")) for credit in personal if credit.get("kind") == "attendance"}
    game_wins = [credit for credit in personal if credit.get("kind") == "game_win"]
    costume_wins = [credit for credit in personal if credit.get("kind") == "costume_win"]
    custom_keys = {
        str(credit.get("achievement_key", ""))
        for credit in personal
        if credit.get("kind") == "custom" and credit.get("achievement_key") in ACHIEVEMENT_CATALOG
    }
    earned_keys = set(custom_keys)
    for key, definition in ACHIEVEMENT_CATALOG.items():
        threshold = definition.get("attendance_count")
        if isinstance(threshold, int) and len(attendance) >= threshold:
            earned_keys.add(key)
    if game_wins:
        earned_keys.add("game_champion")
    if costume_wins:
        earned_keys.add("costume_champion")
    if len(game_wins) >= 2:
        earned_keys.add("multi_game_master")
    achievements = [
        {"key": key, **definition}
        for key, definition in ACHIEVEMENT_CATALOG.items()
        if key in earned_keys
    ]
    next_attendance = next(
        (
            {"key": key, **definition, "progress": len(attendance)}
            for key, definition in ACHIEVEMENT_CATALOG.items()
            if isinstance(definition.get("attendance_count"), int)
            and len(attendance) < int(definition["attendance_count"])
        ),
        None,
    )
    return {
        "achievements": achievements,
        "attendance_count": len(attendance),
        "attendance_years": sorted(
            {str(credit.get("year", "")) for credit in personal if credit.get("kind") == "attendance" and credit.get("year")},
            reverse=True,
        ),
        "game_wins": game_wins,
        "costume_wins": costume_wins,
        "next_attendance": next_attendance,
    }


def new_credit(
    *,
    kind: str,
    recipient_name: str,
    account_id: str = "",
    public_identity: str = "",
    event_id: str = "",
    year: str = "",
    subject_key: str = "",
    subject_label: str = "",
    achievement_key: str = "",
    source_ref: str = "",
    note: str = "",
) -> dict[str, object]:
    return {
        "id": uuid4().hex,
        "kind": kind,
        "account_id": account_id,
        "recipient_name": recipient_name.strip()[:80],
        "public_identity": (public_identity or recipient_name).strip()[:80],
        "event_id": event_id[:80],
        "year": year[:12],
        "subject_key": subject_key[:100],
        "subject_label": subject_label[:160],
        "achievement_key": achievement_key[:100],
        "source_ref": source_ref[:160],
        "note": note.strip()[:500],
        "created_at": utc_now_iso(),
        "revoked_at": "",
        "revoked_reason": "",
    }


def credit_exists(
    credits: list[dict[str, object]],
    *,
    kind: str,
    account_id: str,
    event_id: str,
    subject_key: str = "",
    source_ref: str = "",
) -> bool:
    return any(
        not credit.get("revoked_at")
        and credit.get("kind") == kind
        and str(credit.get("account_id", "")) == account_id
        and str(credit.get("event_id", "")) == event_id
        and str(credit.get("subject_key", "")) == subject_key
        and (not source_ref or str(credit.get("source_ref", "")) == source_ref)
        for credit in credits
    )
