from __future__ import annotations

import copy
from collections import Counter
from typing import Any

from party_games import (
    GAME_CATALOG,
    MURDER_MARRY_FUCK_GAME_KEY,
    PROMPT_GAME_KEYS,
    TWO_TRUTHS_GAME_KEY,
    game_winners,
    normalize_games_state,
)


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _bounded_float(value: object, maximum: float = 100.0) -> float:
    try:
        return max(0.0, min(maximum, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _text(value: object, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def chart_rows(
    rows: list[dict[str, Any]],
    *,
    value_key: str = "value",
    label_key: str = "label",
) -> list[dict[str, Any]]:
    maximum = max((_bounded_float(row.get(value_key), 1_000_000_000) for row in rows), default=0.0)
    rendered = []
    for row in rows:
        value = _bounded_float(row.get(value_key), 1_000_000_000)
        rendered.append(
            {
                **copy.deepcopy(row),
                "label": _text(row.get(label_key), 160) or "Unknown",
                "value": value,
                "percent": round((value / maximum * 100) if maximum else 0.0, 1),
            }
        )
    return rendered


def format_duration(total_ms: object) -> str:
    milliseconds = _nonnegative_int(total_ms)
    total_minutes = milliseconds // 60_000
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} hr {minutes} min"
    if hours:
        return f"{hours} hr"
    return f"{minutes} min"


def build_playlist_snapshot(raw_playlist: object, raw_dj_state: object = None) -> list[dict[str, Any]]:
    playlist = [song for song in raw_playlist if isinstance(song, dict) and bool(song.get("enabled", True))] if isinstance(raw_playlist, list) else []
    songs_by_id = {_text(song.get("id"), 120): song for song in playlist if _text(song.get("id"), 120)}
    order: list[str] = []
    if isinstance(raw_dj_state, dict):
        receiver = raw_dj_state.get("receiver", {})
        if isinstance(receiver, dict):
            candidate = receiver.get("actual_queue_order", [])
            if isinstance(candidate, list):
                mapped = [_text(song_id, 120) for song_id in candidate if _text(song_id, 120) in songs_by_id]
                if len(mapped) == len(songs_by_id) and len(set(mapped)) == len(mapped):
                    order = mapped
    if not order:
        order = [_text(song.get("id"), 120) for song in playlist]

    snapshot = []
    for index, song_id in enumerate(order):
        song = songs_by_id.get(song_id)
        if not song:
            continue
        apple_music_id = _text(song.get("apple_music_id"), 160)
        snapshot.append(
            {
                "position": index + 1,
                "title": _text(song.get("title"), 180) or "Unknown song",
                "artist": _text(song.get("artist"), 180) or "Unknown artist",
                "album": _text(song.get("album"), 180),
                "artwork_url": _text(song.get("artwork_url"), 500),
                "duration_ms": _nonnegative_int(song.get("duration_ms")),
                "explicit": bool(song.get("explicit")),
                "apple_music_id": apple_music_id,
                "apple_music_url": f"https://music.apple.com/song/{apple_music_id}" if apple_music_id else "",
                "source": _text(song.get("source"), 40) or "admin",
                "requester_name": _text(song.get("requester_name"), 80),
            }
        )
    return snapshot


def _score_rows(game_key: str, game: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, score in enumerate(game.get("results", {}).get("scores", [])):
        if not isinstance(score, dict):
            continue
        value = _nonnegative_int(score.get("correct")) if game_key == TWO_TRUTHS_GAME_KEY else _nonnegative_int(score.get("points"))
        rows.append(
            {
                "rank": index + 1,
                "name": _text(score.get("name") or score.get("alias"), 80) or "Player",
                "value": value,
                "value_label": f"{value} {'correct' if game_key == TWO_TRUTHS_GAME_KEY else 'pts'}",
            }
        )
    return rows


def build_game_result_snapshots(raw_games: object, *, include_incomplete: bool = False) -> list[dict[str, Any]]:
    games = normalize_games_state(raw_games)
    snapshots = []
    for game_key, metadata in GAME_CATALOG.items():
        game = games[game_key]
        participant_count = len(game.get("participants", {}))
        if not participant_count and not include_incomplete:
            continue
        ended = game.get("phase") == "ended"
        winners = game_winners(game_key, game) if ended else []
        winner_names = [
            _text(winner.get("name") or winner.get("alias"), 80) or "Player"
            for winner in winners
        ]
        snapshots.append(
            {
                "game_key": game_key,
                "title": metadata["title"],
                "short_title": metadata["short_title"],
                "engine": metadata["engine"],
                "phase": str(game.get("phase", "signup")),
                "participant_count": participant_count,
                "simulation": bool(game.get("simulation", {}).get("is_simulated")),
                "winner_names": winner_names,
                "winner_label": ", ".join(winner_names) if winner_names else ("No Winner" if ended else "Pending"),
                "scores": _score_rows(game_key, game),
            }
        )
    return snapshots


def _game_activity(game_key: str, game: dict[str, Any]) -> tuple[int, str]:
    if game_key == TWO_TRUTHS_GAME_KEY:
        return sum(len(guesses) for guesses in game.get("guesses", {}).values()), "guesses"
    if game_key == MURDER_MARRY_FUCK_GAME_KEY:
        return sum(len(participant.get("answers", {})) for participant in game.get("participants", {}).values()), "ballots"
    if game_key in PROMPT_GAME_KEYS:
        responses = sum(len(game_round.get("responses", {})) for game_round in game.get("rounds", []))
        votes = sum(len(game_round.get("votes", {})) for game_round in game.get("rounds", []))
        return responses + votes, "responses + votes"
    return 0, "interactions"


def build_recap_analytics(
    raw_games: object,
    *,
    attendee_count: int,
    costume_scores: list[dict[str, Any]] | None = None,
    playlist_snapshot: list[dict[str, Any]] | None = None,
    credit_count: int = 0,
    achievement_count: int = 0,
) -> dict[str, Any]:
    games = normalize_games_state(raw_games)
    participation_rows = []
    activity_rows = []
    participation_by_account: Counter[str] = Counter()
    leaderboard: dict[str, list[dict[str, Any]]] = {}
    for game_key, metadata in GAME_CATALOG.items():
        game = games[game_key]
        participants = game.get("participants", {})
        participant_count = len(participants)
        if participant_count:
            participation_rows.append(
                {
                    "game_key": game_key,
                    "label": metadata["short_title"],
                    "value": participant_count,
                    "detail": f"{round(participant_count / attendee_count * 100, 1) if attendee_count else 0}% of attendees",
                }
            )
            for account_id in participants:
                participation_by_account[str(account_id)] += 1
        activity_value, activity_label = _game_activity(game_key, game)
        if participant_count or activity_value:
            activity_rows.append(
                {
                    "game_key": game_key,
                    "label": metadata["short_title"],
                    "value": activity_value,
                    "detail": activity_label,
                }
            )
        if game.get("phase") == "ended":
            leaderboard[game_key] = chart_rows(_score_rows(game_key, game)[:3])

    depth_counts = Counter(participation_by_account.values())
    depth_rows = [
        {"label": "1 game", "value": depth_counts.get(1, 0)},
        {"label": "2 games", "value": depth_counts.get(2, 0)},
        {"label": "3 games", "value": depth_counts.get(3, 0)},
        {"label": "4+ games", "value": sum(count for depth, count in depth_counts.items() if depth >= 4)},
    ]

    costume_rows = []
    for index, entry in enumerate((costume_scores or [])[:5]):
        value = round(_bounded_float(entry.get("average"), 10), 2)
        costume_rows.append(
            {
                "rank": index + 1,
                "label": _text(entry.get("costume") or entry.get("name"), 120) or "Costume",
                "name": _text(entry.get("name"), 80),
                "value": value,
                "value_label": f"{value:g} avg",
            }
        )

    playlist = playlist_snapshot or []
    sources = Counter(
        "attendee" if song.get("source") == "attendee_request" else "host"
        for song in playlist
    )
    artists = Counter(_text(song.get("artist"), 180) or "Unknown artist" for song in playlist)
    playlist_source_rows = chart_rows(
        [
            {"label": "Attendee requests", "value": sources.get("attendee", 0)},
            {"label": "Host selections", "value": sources.get("host", 0)},
        ]
    )
    top_artist_rows = chart_rows(
        [{"label": artist, "value": count} for artist, count in artists.most_common(5)]
    )
    total_duration_ms = sum(_nonnegative_int(song.get("duration_ms")) for song in playlist)

    return {
        "attendee_count": _nonnegative_int(attendee_count),
        "games_played": sum(1 for game in games.values() if game.get("participants")),
        "total_game_participations": sum(len(game.get("participants", {})) for game in games.values()),
        "total_game_interactions": sum(_game_activity(game_key, game)[0] for game_key, game in games.items()),
        "participation_by_game": chart_rows(participation_rows),
        "activity_by_game": chart_rows(activity_rows),
        "participation_depth": chart_rows(depth_rows),
        "leaderboards": leaderboard,
        "costume_leaderboard": chart_rows(costume_rows),
        "costume_ballot_count": max(
            (
                _nonnegative_int(entry.get("vote_count", entry.get("count", 0)))
                for entry in (costume_scores or [])
            ),
            default=0,
        ),
        "playlist": {
            "track_count": len(playlist),
            "duration_ms": total_duration_ms,
            "duration_label": format_duration(total_duration_ms),
            "unique_artist_count": len(artists),
            "explicit_count": sum(1 for song in playlist if song.get("explicit")),
            "source_rows": playlist_source_rows,
            "top_artist_rows": top_artist_rows,
            "guest_powered_percent": round((sources.get("attendee", 0) / len(playlist) * 100) if playlist else 0.0, 1),
        },
        "credit_count": _nonnegative_int(credit_count),
        "achievement_count": _nonnegative_int(achievement_count),
    }


def build_sample_recap_payload() -> dict[str, Any]:
    participation = chart_rows(
        [
            {"label": "Two Truths", "value": 15},
            {"label": "Murder / Marry / F%$@", "value": 12},
            {"label": "Fill in the Blank", "value": 10},
            {"label": "Bad Advice", "value": 9},
            {"label": "Wrong Answers", "value": 8},
        ]
    )
    costume = chart_rows(
        [
            {"rank": 1, "label": "Radioactive Vampire", "name": "Specimen Seven", "value": 9.6, "value_label": "9.6 avg"},
            {"rank": 2, "label": "Haunted Astronaut", "name": "Morgan", "value": 9.1, "value_label": "9.1 avg"},
            {"rank": 3, "label": "Lab Witch", "name": "Jamie", "value": 8.7, "value_label": "8.7 avg"},
        ]
    )
    playlist = [
        {"position": 1, "title": "Thriller", "artist": "Michael Jackson", "album": "Thriller", "duration_ms": 357_000, "explicit": False, "source": "admin", "apple_music_url": "https://music.apple.com/song/269572838"},
        {"position": 2, "title": "Abracadabra", "artist": "Lady Gaga", "album": "MAYHEM", "duration_ms": 223_000, "explicit": False, "source": "attendee_request", "apple_music_url": "https://music.apple.com"},
        {"position": 3, "title": "Red Wine Supernova", "artist": "Chappell Roan", "album": "The Rise and Fall of a Midwest Princess", "duration_ms": 192_000, "explicit": True, "source": "attendee_request", "apple_music_url": "https://music.apple.com"},
    ]
    return {
        "event_id": "sample-halloween",
        "year": "2026",
        "title": "Qiana and Tony's Halloween Party",
        "date": "October 31, 2026",
        "test_mode": "sample",
        "recipient_name": "Specimen Seven",
        "game_results": [
            {"title": "Two Truths and a Lie", "winner_label": "Specimen Seven", "participant_count": 15},
            {"title": "Murder, Marry, F%$@", "winner_label": "Jamie and Morgan", "participant_count": 12},
            {"title": "Fill in the Blank: After Dark", "winner_label": "No Winner", "participant_count": 10},
            {"title": "Bad Advice Hotline", "winner_label": "Dr. Disaster", "participant_count": 9},
            {"title": "Wrong Answers Only", "winner_label": "Specimen Seven", "participant_count": 8},
        ],
        "costume_result": {"winner": "Specimen Seven", "costume": "Radioactive Vampire"},
        "playlist_snapshot": playlist,
        "analytics_snapshot": {
            "attendee_count": 18,
            "games_played": 5,
            "total_game_participations": 54,
            "total_game_interactions": 187,
            "participation_by_game": participation,
            "costume_leaderboard": costume,
            "playlist": {
                "track_count": 30,
                "duration_label": "2 hr 11 min",
                "unique_artist_count": 24,
                "guest_powered_percent": 60,
                "source_rows": chart_rows([{"label": "Attendee requests", "value": 18}, {"label": "Host selections", "value": 12}]),
                "top_artist_rows": chart_rows([{"label": "Lady Gaga", "value": 5}, {"label": "Chappell Roan", "value": 4}, {"label": "Michael Jackson", "value": 3}]),
            },
            "credit_count": 23,
            "achievement_count": 14,
        },
        "new_achievements": ["Party Attendee", "Game Champion", "Multi-Game Master"],
        "personal_summary": {"games_joined": 3, "wins": 2, "jukebox_requests": 1, "karaoke_appearances": 1},
    }
