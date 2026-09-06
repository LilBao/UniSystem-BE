import asyncio
import json
from typing import Any

import httpx

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError


class JsonHttpClient:
    def __init__(self, settings: Settings, *, base_url: str, api_key: str) -> None:
        self.settings = settings
        self.base_url = base_url
        self.api_key = api_key

    async def request(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> Any:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with asyncio.timeout(self.settings.parser_timeout_seconds):
                async with httpx.AsyncClient(
                    base_url=self.base_url.rstrip("/") + "/",
                    headers=headers,
                    follow_redirects=False,
                    timeout=self.settings.parser_timeout_seconds,
                ) as client:
                    request = client.build_request("POST", endpoint, json=payload)
                    return await self._read(client, request)
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            raise AppError(ErrorCode.PARSER_ERROR, "JSON HTTP request failed") from exc

    async def _read(self, client: httpx.AsyncClient, request: httpx.Request) -> Any:
        response = await client.send(request, stream=True)
        try:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes(64 * 1024):
                body.extend(chunk)
                if len(body) > self.settings.parser_max_response_bytes:
                    raise AppError(ErrorCode.PARSER_ERROR, "Parser response exceeds quota")
            return json.loads(body)
        finally:
            await response.aclose()
