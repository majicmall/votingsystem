from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


class MegaverseError(Exception):
    """Base exception for MajicMall Megaverse integration errors."""


class MegaverseConfigurationError(MegaverseError):
    """Raised when the MajicMall Megaverse API is not configured."""


class MegaverseConnectionError(MegaverseError):
    """Raised when ATL's Hottest cannot reach MajicMall Megaverse."""


class MegaverseAPIError(MegaverseError):
    """Raised when MajicMall Megaverse returns an unsuccessful response."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MegaverseResponse:
    status_code: int
    data: Any


class MegaverseClient:
    """
    Server-to-server client for the MajicMall Megaverse integration API.

    MajicMall Megaverse remains authoritative for shared commerce data.
    ATL's Hottest consumes that data through this boundary instead of
    importing or duplicating Megaverse commerce models.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = (
            settings.MEGAVERSE_API_BASE_URL if base_url is None else base_url
        ).rstrip("/")
        self.api_key = settings.MEGAVERSE_API_KEY if api_key is None else api_key
        self.timeout = (
            settings.MEGAVERSE_API_TIMEOUT if timeout is None else float(timeout)
        )

    def _validate_configuration(self) -> None:
        if not self.base_url:
            raise MegaverseConfigurationError(
                "MEGAVERSE_API_BASE_URL is not configured."
            )

        if not self.api_key:
            raise MegaverseConfigurationError(
                "MEGAVERSE_API_KEY is not configured."
            )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> MegaverseResponse:
        self._validate_configuration()

        normalized_path = "/" + path.lstrip("/")
        url = f"{self.base_url}{normalized_path}"

        if query:
            clean_query = {
                key: value
                for key, value in query.items()
                if value is not None
            }
            if clean_query:
                url = f"{url}?{urlencode(clean_query, doseq=True)}"

        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "ATLsHottest-MegaverseBridge/1.0",
        }

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            url=url,
            data=body,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                status_code = response.getcode()
                raw_body = response.read().decode("utf-8")

        except HTTPError as exc:
            try:
                raw_error = exc.read().decode("utf-8")
                error_data = json.loads(raw_error) if raw_error else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_data = {}

            message = (
                error_data.get("detail")
                or error_data.get("error")
                or f"MajicMall Megaverse API returned HTTP {exc.code}."
            )

            raise MegaverseAPIError(
                str(message),
                status_code=exc.code,
            ) from exc

        except (URLError, TimeoutError, OSError) as exc:
            raise MegaverseConnectionError(
                "Unable to connect to the MajicMall Megaverse API."
            ) from exc

        if not raw_body:
            data = None
        else:
            try:
                data = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise MegaverseAPIError(
                    "MajicMall Megaverse API returned invalid JSON.",
                    status_code=status_code,
                ) from exc

        return MegaverseResponse(
            status_code=status_code,
            data=data,
        )

    def get(
        self,
        path: str,
        *,
        query: dict[str, Any] | None = None,
    ) -> MegaverseResponse:
        return self._request("GET", path, query=query)

    def post(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> MegaverseResponse:
        return self._request("POST", path, payload=payload)
