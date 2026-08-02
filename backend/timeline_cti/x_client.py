from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import Settings
from .state import StateStore


class XApiError(RuntimeError):
    pass


class XRateLimitError(XApiError):
    def __init__(self, reset_at: int) -> None:
        super().__init__("X API rate limit reached")
        self.reset_at = reset_at


@dataclass(frozen=True)
class TimelinePage:
    posts: list[dict[str, Any]]
    users: dict[str, dict[str, Any]]
    newest_id: str | None
    next_token: str | None


class XClient:
    TOKEN_URL = "https://api.x.com/2/oauth2/token"  # noqa: S105  # nosec B105
    REQUIRED_SCOPES = frozenset({"tweet.read", "users.read", "offline.access"})

    def __init__(self, settings: Settings, state_store: StateStore) -> None:
        self.settings = settings
        self.state_store = state_store

    def build_authorization_url(self) -> str:
        if not self.settings.X_CLIENT_ID:
            raise XApiError("X_CLIENT_ID is not configured")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        self.state_store.store_oauth_state(state, {"verifier": verifier})
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.X_CLIENT_ID,
                "redirect_uri": self.settings.X_REDIRECT_URI,
                "scope": "tweet.read users.read offline.access",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self.settings.X_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str, state: str) -> str:
        stored = self.state_store.consume_oauth_state(state)
        if stored is None:
            raise XApiError("OAuth state is invalid, expired, or already consumed")
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "client_id": self.settings.X_CLIENT_ID,
            "redirect_uri": self.settings.X_REDIRECT_URI,
            "code_verifier": str(stored["verifier"]),
        }
        token = await self._token_request(data)
        self._validate_scopes(token)
        user = await self.get_me(str(token["access_token"]))
        self._add_expiry(token)
        self.state_store.store_oauth_token(token, str(user["id"]))
        return str(user["id"])

    async def refresh_if_needed(self) -> tuple[dict[str, Any], str]:
        stored = self.state_store.get_oauth_token()
        if stored is None:
            raise XApiError("X OAuth connection has not been completed")
        token, user_id = stored
        if int(token.get("expires_at", 0)) > int(time.time()) + 120:
            return token, user_id
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise XApiError("OAuth refresh token is unavailable")
        refreshed = await self._token_request(
            {
                "refresh_token": str(refresh_token),
                "grant_type": "refresh_token",
                "client_id": self.settings.X_CLIENT_ID,
            }
        )
        if "refresh_token" not in refreshed:
            refreshed["refresh_token"] = refresh_token
        if "scope" not in refreshed:
            refreshed["scope"] = token.get("scope", "")
        self._validate_scopes(refreshed)
        self._add_expiry(refreshed)
        self.state_store.store_oauth_token(refreshed, user_id)
        return refreshed, user_id

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        auth: httpx.BasicAuth | None = None
        client_secret = self.settings.X_CLIENT_SECRET.get_secret_value()
        if client_secret:
            auth = httpx.BasicAuth(self.settings.X_CLIENT_ID, client_secret)
        async with httpx.AsyncClient(timeout=20) as client:
            if auth is None:
                response = await client.post(self.TOKEN_URL, data=data)
            else:
                response = await client.post(self.TOKEN_URL, data=data, auth=auth)
        if response.status_code >= 400:
            raise XApiError(f"OAuth token exchange failed with status {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict) or "access_token" not in payload:
            raise XApiError("OAuth token response is malformed")
        return payload

    @staticmethod
    def _add_expiry(token: dict[str, Any]) -> None:
        token["expires_at"] = int(time.time()) + int(token.get("expires_in", 7200))

    @classmethod
    def _validate_scopes(cls, token: dict[str, Any]) -> None:
        granted = set(str(token.get("scope", "")).split())
        if not granted >= cls.REQUIRED_SCOPES:
            raise XApiError("OAuth token is missing one or more required scopes")

    async def get_me(self, access_token: str) -> dict[str, Any]:
        payload = await self._get_json(
            f"{self.settings.X_API_BASE_URL}/2/users/me",
            access_token,
            params={"user.fields": "id,username,name,protected"},
        )
        user = payload.get("data")
        if not isinstance(user, dict) or not user.get("id"):
            raise XApiError("X /users/me response is malformed")
        return user

    async def fetch_home_page(
        self,
        access_token: str,
        user_id: str,
        since_id: str | None = None,
        pagination_token: str | None = None,
        max_results: int = 100,
    ) -> TimelinePage:
        params: dict[str, str | int] = {
            "max_results": max(1, min(100, max_results)),
            "tweet.fields": (
                "id,text,author_id,conversation_id,created_at,lang,entities,public_metrics,"
                "referenced_tweets,edit_history_tweet_ids"
            ),
            "expansions": "author_id,referenced_tweets.id",
            "user.fields": "id,username,name,verified,protected",
        }
        if since_id:
            params["since_id"] = since_id
        if pagination_token:
            params["pagination_token"] = pagination_token
        payload = await self._get_json(
            f"{self.settings.X_API_BASE_URL}/2/users/{user_id}/timelines/reverse_chronological",
            access_token,
            params=params,
        )
        posts = payload.get("data", [])
        includes = payload.get("includes", {})
        users = {
            str(user["id"]): user
            for user in includes.get("users", [])
            if isinstance(user, dict) and user.get("id")
        }
        referenced = {
            str(post["id"]): post
            for post in includes.get("tweets", [])
            if isinstance(post, dict) and post.get("id")
        }
        prepared: list[dict[str, Any]] = []
        for post in posts if isinstance(posts, list) else []:
            if not isinstance(post, dict):
                continue
            post["_referenced_posts"] = referenced
            prepared.append(post)
        meta = payload.get("meta", {})
        return TimelinePage(
            posts=prepared,
            users=users,
            newest_id=str(meta["newest_id"]) if meta.get("newest_id") else None,
            next_token=str(meta["next_token"]) if meta.get("next_token") else None,
        )

    async def _get_json(
        self,
        url: str,
        access_token: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        # Rate-limit metadatası içerik veya token taşımaz; durum ekranında kullanılabilir.
        if remaining := response.headers.get("x-rate-limit-remaining"):
            self.state_store.set_value("x_rate_limit_remaining", remaining)
        if reset := response.headers.get("x-rate-limit-reset"):
            self.state_store.set_value("x_rate_limit_reset", reset)
        if response.status_code == 429:
            raise XRateLimitError(
                int(response.headers.get("x-rate-limit-reset", time.time() + 900))
            )
        if response.status_code >= 400:
            raise XApiError(f"X API request failed with status {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise XApiError("X API response is malformed")
        return payload
