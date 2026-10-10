"""The HTTP client the MCP tools share.

The MCP server is a **client of the REST API**, not a second implementation of
it (TRD §3: "an MCP server wrapping the REST API"). Every tool ends up here, and
here ends up making an ordinary HTTP request with an ordinary API key. Nothing
in this package imports :mod:`app`, touches the database, or knows a single
trading rule — so a permission fixed in the API is fixed for MCP agents in the
same commit, and an MCP agent can never do something an HTTP client could not.

The transport is injectable so tests can point the whole tool surface at a
FastAPI ``TestClient`` and exercise it end to end without a running server.
"""

from __future__ import annotations

from typing import Any

import httpx

#: The header every request authenticates with (TRD §6).
API_KEY_HEADER = "X-API-Key"


class FundAPIError(Exception):
    """The API refused or could not serve the request.

    Carries the status code and the API's own ``detail`` string, because that
    text is written for the agent reading it — "pod 2 is not your pod" tells an
    LLM what to do next, "HTTP 403" does not.
    """

    def __init__(self, status_code: int, detail: str, *, path: str = "") -> None:
        location = f" ({path})" if path else ""
        super().__init__(f"{status_code}: {detail}{location}")
        self.status_code = status_code
        self.detail = detail
        self.path = path


class FundClient:
    """Thin async wrapper over the fund API.

    Args:
        base_url: where the API lives, e.g. ``http://127.0.0.1:8000``.
        api_key: the acting agent's key. Its role decides what the tools can do.
        transport: override for tests (an ``httpx.ASGITransport`` over the app).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={API_KEY_HEADER: api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FundClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Call one endpoint and return its parsed JSON body.

        Raises:
            FundAPIError: any non-2xx response, or an unreachable server.
        """
        try:
            response = await self._client.request(
                method,
                path,
                # Unset optional arguments must not become "param=None" in the
                # query string — FastAPI would reject the literal string "None".
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json,
            )
        except httpx.HTTPError as exc:
            raise FundAPIError(
                503, f"could not reach the fund API: {exc}", path=path
            ) from exc

        if response.status_code >= 400:
            raise FundAPIError(
                response.status_code, _detail_of(response), path=path
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: dict[str, Any] | None = None, **params: Any) -> Any:
        return await self.request("POST", path, params=params, json=body or {})

    async def delete(self, path: str, **params: Any) -> Any:
        return await self.request("DELETE", path, params=params)


def _detail_of(response: httpx.Response) -> str:
    """Pull the most useful human-readable message out of an error response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase

    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
        if isinstance(detail, str):
            return detail
        # FastAPI validation errors are a list of per-field objects; flatten them
        # into one line an agent can actually read and correct.
        if isinstance(detail, list):
            return "; ".join(
                f"{'.'.join(str(p) for p in item.get('loc', [])[1:])}: {item.get('msg')}"
                if isinstance(item, dict)
                else str(item)
                for item in detail
            )
    return str(payload)
