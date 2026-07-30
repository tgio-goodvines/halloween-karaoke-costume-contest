"""YouTube Data API and OAuth helpers for the karaoke workflow.

This module deliberately owns no Flask or Redis state.  It presents a small,
mockable boundary around Google's generated client and the production Vault
secret used to retain the host account's refresh token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse
import json
import re
import socket

import hvac
import httplib2
import requests
from google_auth_httplib2 import AuthorizedHttp
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


YOUTUBE_PLAYLIST_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
YOUTUBE_SCOPES = [YOUTUBE_PLAYLIST_SCOPE]
YOUTUBE_HTTP_TIMEOUT_SECONDS = 10
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?$"
)
ALLOWED_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


@dataclass(frozen=True)
class YouTubeConfig:
    api_key: str = ""
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    region_code: str = "US"

    @property
    def search_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def oauth_client_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def playlist_configured(self) -> bool:
        return bool(self.oauth_client_configured and self.refresh_token)


class YouTubeApiError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
        uncertain: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.uncertain = uncertain


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_youtube_video_id(raw_value: object) -> str:
    value = str(raw_value or "").strip()
    if YOUTUBE_VIDEO_ID_RE.fullmatch(value):
        return value

    try:
        parsed = urlparse(value)
    except ValueError:
        return ""

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_YOUTUBE_HOSTS:
        return ""

    candidate = ""
    if host.endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/", 1)[0]
    else:
        path_parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts", "live"}:
            candidate = path_parts[1]

    return candidate if YOUTUBE_VIDEO_ID_RE.fullmatch(candidate) else ""


def canonical_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}" if YOUTUBE_VIDEO_ID_RE.fullmatch(video_id) else ""


def parse_iso_duration_seconds(raw_duration: object) -> int:
    match = ISO_DURATION_RE.fullmatch(str(raw_duration or ""))
    if not match:
        return 0
    values = {key: int(value or 0) for key, value in match.groupdict().items()}
    return (
        values["days"] * 86400
        + values["hours"] * 3600
        + values["minutes"] * 60
        + values["seconds"]
    )


def _thumbnail_url(snippet: dict[str, Any]) -> str:
    thumbnails = snippet.get("thumbnails", {})
    if not isinstance(thumbnails, dict):
        return ""
    for key in ("maxres", "standard", "high", "medium", "default"):
        thumbnail = thumbnails.get(key, {})
        if isinstance(thumbnail, dict) and thumbnail.get("url"):
            return str(thumbnail["url"])
    return ""


def normalize_video_resource(raw_video: object, *, region_code: str = "US") -> dict[str, Any] | None:
    if not isinstance(raw_video, dict):
        return None
    video_id = str(raw_video.get("id", "") or "")
    if not YOUTUBE_VIDEO_ID_RE.fullmatch(video_id):
        return None

    snippet = raw_video.get("snippet", {})
    content_details = raw_video.get("contentDetails", {})
    status = raw_video.get("status", {})
    if not isinstance(snippet, dict):
        snippet = {}
    if not isinstance(content_details, dict):
        content_details = {}
    if not isinstance(status, dict):
        status = {}

    region = str(region_code or "US").upper()
    region_restriction = content_details.get("regionRestriction", {})
    if not isinstance(region_restriction, dict):
        region_restriction = {}
    allowed_regions = region_restriction.get("allowed")
    blocked_regions = region_restriction.get("blocked")
    region_allowed = True
    if isinstance(allowed_regions, list):
        region_allowed = region in {str(item).upper() for item in allowed_regions}
    elif isinstance(blocked_regions, list):
        region_allowed = region not in {str(item).upper() for item in blocked_regions}

    content_rating = content_details.get("contentRating", {})
    if not isinstance(content_rating, dict):
        content_rating = {}
    privacy_status = str(status.get("privacyStatus", "") or "")
    upload_status = str(status.get("uploadStatus", "processed") or "processed")
    available = (
        privacy_status in {"", "public", "unlisted"}
        and upload_status not in {"deleted", "failed", "rejected"}
        and region_allowed
    )

    return {
        "video_id": video_id,
        "title": str(snippet.get("title", "") or "").strip()[:300],
        "channel_id": str(snippet.get("channelId", "") or "").strip()[:120],
        "channel_title": str(snippet.get("channelTitle", "") or "").strip()[:180],
        "thumbnail_url": _thumbnail_url(snippet),
        "duration_seconds": parse_iso_duration_seconds(content_details.get("duration")),
        "privacy_status": privacy_status or "public",
        "upload_status": upload_status,
        "embeddable": bool(status.get("embeddable", False)),
        "age_restricted": content_rating.get("ytRating") == "ytAgeRestricted",
        "region_allowed": region_allowed,
        "available": available,
        "last_verified_at": utc_now_iso(),
        "watch_url": canonical_watch_url(video_id),
    }


def _http_error_details(exc: HttpError) -> tuple[str, str, int | None]:
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = ""
    message = ""
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        errors = error.get("errors", []) if isinstance(error, dict) else []
        if errors and isinstance(errors[0], dict):
            reason = str(errors[0].get("reason", "") or "")
        message = str(error.get("message", "") or "") if isinstance(error, dict) else ""
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return reason or f"http_{status or 'error'}", message, status


def translate_google_error(exc: Exception, action: str) -> YouTubeApiError:
    if isinstance(exc, YouTubeApiError):
        return exc
    if isinstance(exc, HttpError):
        reason, raw_message, status = _http_error_details(exc)
        safe_messages = {
            "authError": "YouTube authorization is no longer valid. Reconnect the host account.",
            "forbidden": "The connected YouTube account is not allowed to perform this action.",
            "insufficientPermissions": "The YouTube connection does not have playlist-management permission.",
            "playlistNotFound": "The selected YouTube playlist could not be found.",
            "playlistItemsNotAccessible": "The selected playlist is not writable by the connected account.",
            "videoNotFound": "The selected YouTube video is no longer available.",
            "quotaExceeded": "The YouTube API quota is exhausted for today.",
            "dailyLimitExceeded": "The YouTube API quota is exhausted for today.",
            "manualSortRequired": "Set the YouTube playlist ordering to Manual, then retry.",
        }
        message = safe_messages.get(
            reason,
            f"YouTube could not {action}. Try again or review the connection.",
        )
        retryable = bool(status and (status >= 500 or status == 429))
        return YouTubeApiError(
            reason,
            message,
            http_status=status,
            retryable=retryable,
            uncertain=retryable and action in {"add the playlist item", "move the playlist item", "remove the playlist item"},
        )
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return YouTubeApiError(
            "network_timeout",
            f"The YouTube request timed out while trying to {action}. Reconcile before retrying.",
            retryable=True,
            uncertain=True,
        )
    if isinstance(exc, (socket.timeout, httplib2.HttpLib2Error)):
        return YouTubeApiError(
            "network_timeout",
            f"The YouTube request timed out while trying to {action}. Reconcile before retrying.",
            retryable=True,
            uncertain=action in {
                "add the playlist item",
                "move the playlist item",
                "remove the playlist item",
            },
        )
    return YouTubeApiError(
        "youtube_unavailable",
        f"YouTube could not {action}. Try again or review the connection.",
        retryable=True,
    )


class YouTubeService:
    def __init__(self, config: YouTubeConfig):
        self.config = config

    def _public_client(self):
        if not self.config.search_configured:
            raise YouTubeApiError("not_configured", "YouTube search is not configured.")
        return build(
            "youtube",
            "v3",
            developerKey=self.config.api_key,
            http=httplib2.Http(timeout=YOUTUBE_HTTP_TIMEOUT_SECONDS),
            cache_discovery=False,
        )

    def _credentials(self) -> Credentials:
        if not self.config.playlist_configured:
            raise YouTubeApiError(
                "not_connected",
                "Connect the host YouTube account before managing the playlist.",
            )
        return Credentials(
            token=None,
            refresh_token=self.config.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            scopes=YOUTUBE_SCOPES,
        )

    def _authorized_client(self):
        authorized_http = AuthorizedHttp(
            self._credentials(),
            http=httplib2.Http(timeout=YOUTUBE_HTTP_TIMEOUT_SECONDS),
        )
        return build(
            "youtube",
            "v3",
            http=authorized_http,
            cache_discovery=False,
        )

    def search_videos(self, query: str, *, page_token: str = "", limit: int = 8) -> dict[str, Any]:
        cleaned_query = str(query or "").strip()
        if not cleaned_query:
            return {"items": [], "next_page_token": "", "previous_page_token": ""}
        try:
            client = self._public_client()
            search_params: dict[str, Any] = {
                "part": "snippet",
                "q": cleaned_query,
                "type": "video",
                "maxResults": max(1, min(limit, 8)),
                "regionCode": self.config.region_code,
                "safeSearch": "moderate",
            }
            if page_token:
                search_params["pageToken"] = page_token
            search_payload = client.search().list(**search_params).execute(num_retries=1)
            video_ids = [
                str(item.get("id", {}).get("videoId", ""))
                for item in search_payload.get("items", [])
                if isinstance(item, dict)
            ]
            videos = self.get_videos(video_ids, client=client)
            return {
                "items": videos,
                "next_page_token": str(search_payload.get("nextPageToken", "") or ""),
                "previous_page_token": str(search_payload.get("prevPageToken", "") or ""),
            }
        except Exception as exc:
            raise translate_google_error(exc, "search for videos") from exc

    def get_videos(self, video_ids: list[str], *, client=None) -> list[dict[str, Any]]:
        valid_ids = list(dict.fromkeys(video_id for video_id in video_ids if YOUTUBE_VIDEO_ID_RE.fullmatch(video_id)))
        if not valid_ids:
            return []
        try:
            api_client = client or self._public_client()
            payload = (
                api_client.videos()
                .list(
                    part="snippet,contentDetails,status",
                    id=",".join(valid_ids[:50]),
                )
                .execute(num_retries=1)
            )
            normalized_by_id = {}
            for raw_video in payload.get("items", []):
                normalized = normalize_video_resource(raw_video, region_code=self.config.region_code)
                if normalized:
                    normalized_by_id[normalized["video_id"]] = normalized
            return [normalized_by_id[video_id] for video_id in valid_ids if video_id in normalized_by_id]
        except Exception as exc:
            raise translate_google_error(exc, "verify the video") from exc

    def connection_status(self) -> dict[str, str]:
        try:
            payload = (
                self._authorized_client()
                .channels()
                .list(part="id,snippet", mine=True, maxResults=1)
                .execute(num_retries=1)
            )
            items = payload.get("items", [])
            if not items:
                raise YouTubeApiError("channel_not_found", "The connected account has no available YouTube channel.")
            channel = items[0]
            snippet = channel.get("snippet", {}) if isinstance(channel, dict) else {}
            return {
                "channel_id": str(channel.get("id", "") or ""),
                "channel_title": str(snippet.get("title", "") or ""),
            }
        except Exception as exc:
            raise translate_google_error(exc, "verify the connected account") from exc

    def list_owned_playlists(self, *, page_token: str = "", limit: int = 25) -> dict[str, Any]:
        try:
            params: dict[str, Any] = {
                "part": "id,snippet,status",
                "mine": True,
                "maxResults": max(1, min(limit, 50)),
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._authorized_client().playlists().list(**params).execute(num_retries=1)
            items = []
            for raw in payload.get("items", []):
                if not isinstance(raw, dict):
                    continue
                snippet = raw.get("snippet", {})
                status = raw.get("status", {})
                items.append(
                    {
                        "playlist_id": str(raw.get("id", "") or ""),
                        "title": str(snippet.get("title", "") or "") if isinstance(snippet, dict) else "",
                        "privacy": str(status.get("privacyStatus", "") or "") if isinstance(status, dict) else "",
                    }
                )
            return {"items": items, "next_page_token": str(payload.get("nextPageToken", "") or "")}
        except Exception as exc:
            raise translate_google_error(exc, "list playlists") from exc

    def create_playlist(self, title: str, *, privacy: str = "private") -> dict[str, str]:
        requested_privacy = privacy if privacy in {"private", "unlisted"} else "private"
        try:
            payload = (
                self._authorized_client()
                .playlists()
                .insert(
                    part="snippet,status",
                    body={
                        "snippet": {
                            "title": str(title or "").strip()[:150],
                            "description": "Managed by the Halloween party karaoke queue.",
                        },
                        "status": {"privacyStatus": requested_privacy},
                    },
                )
                .execute(num_retries=0)
            )
            return {
                "playlist_id": str(payload.get("id", "") or ""),
                "title": str(payload.get("snippet", {}).get("title", title) or title),
                "privacy": str(payload.get("status", {}).get("privacyStatus", requested_privacy) or requested_privacy),
            }
        except Exception as exc:
            raise translate_google_error(exc, "create the playlist") from exc

    def list_playlist_items(self, playlist_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = ""
        try:
            client = self._authorized_client()
            while True:
                params: dict[str, Any] = {
                    "part": "id,snippet,contentDetails,status",
                    "playlistId": playlist_id,
                    "maxResults": 50,
                }
                if page_token:
                    params["pageToken"] = page_token
                payload = client.playlistItems().list(**params).execute(num_retries=1)
                for raw in payload.get("items", []):
                    if not isinstance(raw, dict):
                        continue
                    snippet = raw.get("snippet", {})
                    content = raw.get("contentDetails", {})
                    resource = snippet.get("resourceId", {}) if isinstance(snippet, dict) else {}
                    items.append(
                        {
                            "playlist_item_id": str(raw.get("id", "") or ""),
                            "video_id": str(resource.get("videoId", "") or "") if isinstance(resource, dict) else "",
                            "position": int(snippet.get("position", 0) or 0) if isinstance(snippet, dict) else 0,
                            "note": str(content.get("note", "") or "") if isinstance(content, dict) else "",
                        }
                    )
                page_token = str(payload.get("nextPageToken", "") or "")
                if not page_token:
                    return items
        except Exception as exc:
            raise translate_google_error(exc, "read the playlist") from exc

    def insert_playlist_item(
        self,
        playlist_id: str,
        video_id: str,
        *,
        position: int,
        note: str,
    ) -> dict[str, Any]:
        try:
            payload = (
                self._authorized_client()
                .playlistItems()
                .insert(
                    part="id,snippet,contentDetails",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "position": max(0, int(position)),
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        },
                        "contentDetails": {"note": str(note or "")[:280]},
                    },
                )
                .execute(num_retries=0)
            )
            return {
                "playlist_item_id": str(payload.get("id", "") or ""),
                "position": int(payload.get("snippet", {}).get("position", position) or position),
            }
        except Exception as exc:
            raise translate_google_error(exc, "add the playlist item") from exc

    def move_playlist_item(
        self,
        playlist_item_id: str,
        playlist_id: str,
        video_id: str,
        *,
        position: int,
        note: str,
    ) -> dict[str, Any]:
        try:
            payload = (
                self._authorized_client()
                .playlistItems()
                .update(
                    part="id,snippet,contentDetails",
                    body={
                        "id": playlist_item_id,
                        "snippet": {
                            "playlistId": playlist_id,
                            "position": max(0, int(position)),
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        },
                        "contentDetails": {"note": str(note or "")[:280]},
                    },
                )
                .execute(num_retries=0)
            )
            return {
                "playlist_item_id": str(payload.get("id", playlist_item_id) or playlist_item_id),
                "position": int(payload.get("snippet", {}).get("position", position) or position),
            }
        except Exception as exc:
            raise translate_google_error(exc, "move the playlist item") from exc

    def delete_playlist_item(self, playlist_item_id: str) -> None:
        try:
            self._authorized_client().playlistItems().delete(id=playlist_item_id).execute(num_retries=0)
        except Exception as exc:
            raise translate_google_error(exc, "remove the playlist item") from exc

    def revoke_credentials(self) -> None:
        if not self.config.refresh_token:
            return
        try:
            response = requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": self.config.refresh_token},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=8,
            )
            if response.status_code not in {200, 400}:
                raise YouTubeApiError(
                    "revoke_failed",
                    "Google did not confirm the YouTube disconnection.",
                    http_status=response.status_code,
                    retryable=response.status_code >= 500,
                )
        except Exception as exc:
            raise translate_google_error(exc, "disconnect the account") from exc


def build_oauth_flow(
    config: YouTubeConfig,
    *,
    redirect_uri: str,
    state: str | None = None,
) -> Flow:
    if not config.oauth_client_configured:
        raise YouTubeApiError(
            "oauth_not_configured",
            "YouTube OAuth client credentials are not configured.",
        )
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=YOUTUBE_SCOPES,
        state=state,
    )
    flow.redirect_uri = redirect_uri
    return flow


class VaultYouTubeSecretStore:
    """Read/write one dedicated KV v1 secret through AWS IAM auth."""

    def __init__(
        self,
        *,
        vault_addr: str,
        aws_auth_role: str,
        secret_path: str = "appsecrets/halloween_youtube",
    ):
        self.vault_addr = vault_addr
        self.aws_auth_role = aws_auth_role
        cleaned = secret_path.strip("/")
        self.mount_point, _, self.path = cleaned.partition("/")
        if not self.mount_point or not self.path:
            raise ValueError("Vault secret path must include mount and path.")

    def _client(self):
        client = hvac.Client(url=self.vault_addr)
        client.auth.aws.iam_login(role=self.aws_auth_role)
        if not client.is_authenticated():
            raise RuntimeError("Vault AWS authentication failed.")
        return client

    def read(self) -> dict[str, str]:
        try:
            response = self._client().secrets.kv.v1.read_secret(
                path=self.path,
                mount_point=self.mount_point,
            )
        except hvac.exceptions.InvalidPath:
            return {}
        data = response.get("data", {})
        return {str(key): str(value or "") for key, value in data.items()} if isinstance(data, dict) else {}

    def update_refresh_token(self, refresh_token: str) -> None:
        client = self._client()
        try:
            response = client.secrets.kv.v1.read_secret(path=self.path, mount_point=self.mount_point)
            existing = response.get("data", {})
            secret = dict(existing) if isinstance(existing, dict) else {}
        except hvac.exceptions.InvalidPath:
            secret = {}
        secret["oauth_refresh_token"] = str(refresh_token or "")
        client.secrets.kv.v1.create_or_update_secret(
            path=self.path,
            secret=secret,
            mount_point=self.mount_point,
        )
