"""weightroom.services.app_api — one client for the four applications' own ``/api/v1`` (row WP1).

Every application page the WP rows add reads and acts through here: the bearer from
``api_key_file`` (ADR-0126 rule 8), a timeout per call, and a refusal carried through in the
application's own words and code — never re-coded into one of the console's, because the operator
acts on what the application said. Nothing here retries: a non-idempotent call that timed out may
have landed, and whether to send it again is the operator's decision, not a loop's.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Final

import httpx
from baseaicore import SuiteError
from mirrorwall import Event, format_frame
from setspec import GeneratorInfo

from weightroom.__about__ import __version__
from weightroom.services.apps import AppUnreachable, bearer_token

if TYPE_CHECKING:
    from weightroom.config import Settings

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "AppRefused",
    "AppTimedOut",
    "call",
    "outcome_of",
    "refusal",
    "stream",
]

DEFAULT_TIMEOUT_SECONDS: Final = 10.0
STREAM_TIMEOUT: Final = httpx.Timeout(connect=5.0, read=900.0, write=30.0, pool=5.0)
"""A trajectory or a stage can be quiet for minutes between events; the connect stays short."""

_GENERATOR = GeneratorInfo(name="weightroom", version=__version__)


class AppRefused(SuiteError):
    """The application answered with an error status.

    ``details`` carries ``app``, ``app_code`` (the application's own code, or ``HTTP_<status>``
    when its body named none), ``status`` and ``app_details`` (the error's own ``details``, ``{}``
    when it sent none — LoadCoach's ``NO_ELIGIBLE_MODEL`` carries every candidate and rejection
    there); the message is the application's own.
    """

    code: ClassVar[str] = "APP_REFUSED"


class AppTimedOut(AppUnreachable):
    """The console gave up waiting. The application may still be doing the work.

    A distinct type, and the same ``APP_UNREACHABLE`` code: a client that branches on the code is
    right either way — nothing came back — while the console itself must not report the two the
    same way. WP6 watched *Refresh from provider* be audited ``refused`` while FreeWeight went on
    hashing 195 GB and stored 27 models four minutes later (finding 3): the call was slow, and
    FreeWeight had refused nothing. :func:`outcome_of` is where that distinction reaches a row.
    """


def outcome_of(error: BaseException) -> str:
    """The audit outcome for one failed call: ``pending`` for a timeout, else ``refused``.

    Args:
        error: The exception a route caught around an application call.

    Returns:
        ``pending`` — the outcome vocabulary's word for *no state moved that we know of* — when
        the console stopped waiting, because whether the application did the work is exactly what
        is not known; ``refused`` for anything the application itself said no to.
    """
    return "pending" if isinstance(error, AppTimedOut) else "refused"


def _unreachable(
    app: str, method: str, path: str, exc: httpx.HTTPError, timeout_seconds: float
) -> AppUnreachable:
    """The error for a call that brought nothing back, saying which of the two it was."""
    route = f"{method} /api/v1/{path.lstrip('/')}"
    if isinstance(exc, httpx.TimeoutException):
        # Never `app.capitalize()` in the sentence: the applications' names are `FreeWeight`,
        # `LoadCoach`, `IdeaPress`, `PromptCadence`, and a sentence-initial `Freeweight` is a
        # misspelling of the thing the operator is looking at (row WPF1's live proof).
        return AppTimedOut(
            f"{app} has not answered {route} within {timeout_seconds:g} s, so the console stopped "
            f"waiting. The work may still be running — nothing was cancelled and nothing was sent "
            f"again. Check the page again shortly.",
            details={"app": app, "path": path, "timeout_seconds": timeout_seconds},
        )
    return AppUnreachable(
        f"{app} did not answer {route}: {exc}", details={"app": app, "path": path}
    )


def _url(settings: Settings, app: str, path: str) -> str:
    base = str(getattr(settings.apps, app).base_url).rstrip("/")
    return f"{base}/api/v1/{path.lstrip('/')}"


def _headers(
    settings: Settings, app: str, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    headers = dict(extra or {})
    token = bearer_token(settings, app)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def refusal(app: str, response: httpx.Response) -> AppRefused:
    """The :class:`AppRefused` for one error response, in the application's own words.

    Args:
        app: The application that answered.
        response: Its response, status 400 or above, body already read.

    Returns:
        The error. Never raises: a body that is not the suite's error envelope still yields an
        error naming the HTTP status.
    """
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, Mapping) else None
    code = error.get("code") if isinstance(error, Mapping) else None
    message = error.get("message") if isinstance(error, Mapping) else None
    details = error.get("details") if isinstance(error, Mapping) else None
    return AppRefused(
        f"{app} refused: {message}"
        if message
        else f"{app} refused with HTTP {response.status_code}.",
        details={
            "app": app,
            "app_code": str(code) if code else f"HTTP_{response.status_code}",
            "status": response.status_code,
            "app_details": dict(details) if isinstance(details, Mapping) else {},
        },
    )


def call(
    client: httpx.Client,
    settings: Settings,
    app: str,
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    body: Any = None,  # noqa: ANN401 — whatever JSON body the application's route takes
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:  # noqa: ANN401 — the application's own JSON document
    """One request to an application's API, answered as its parsed JSON body.

    Args:
        client: The pooled HTTP client.
        settings: The validated settings (base URL and token file).
        app: One of the four.
        method: ``GET``, ``POST``, ``PUT``, ``PATCH`` or ``DELETE``.
        path: The path under ``/api/v1`` (``trajectories/01J…``).
        params: Query parameters; ``None`` values are dropped rather than sent as ``"None"``.
        body: A JSON body, or ``None`` for none.
        timeout_seconds: The whole call's timeout.

    Returns:
        The parsed body, or ``None`` for an empty one.

    Raises:
        AppRefused: The application answered 400 or above, in its own words.
        AppTimedOut: It had not answered within ``timeout_seconds``; it may still be working.
        AppUnreachable: It did not answer, or answered with a body that is not JSON.
    """
    query = {key: value for key, value in (params or {}).items() if value is not None}
    try:
        response = client.request(
            method,
            _url(settings, app, path),
            params=query,
            json=body,
            headers=_headers(settings, app),
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise _unreachable(app, method, path, exc, timeout_seconds) from exc
    if response.status_code >= 400:  # noqa: PLR2004 — the HTTP error boundary
        raise refusal(app, response)
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise AppUnreachable(
            f"{app} answered {method} /api/v1/{path.lstrip('/')} with a body that is not JSON.",
            details={"app": app, "path": path},
        ) from exc


def text(
    client: httpx.Client,
    settings: Settings,
    app: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """One ``GET`` whose body is a document rather than JSON — an export — as it was served.

    Args:
        client: The pooled HTTP client.
        settings: The validated settings (base URL and token file).
        app: One of the four.
        path: The path under ``/api/v1``.
        params: Query parameters; ``None`` values are dropped.
        timeout_seconds: The whole call's timeout.

    Returns:
        ``(media type, text)``.

    Raises:
        AppRefused: The application answered 400 or above, in its own words.
        AppTimedOut: It had not answered within ``timeout_seconds``; it may still be working.
        AppUnreachable: It did not answer.
    """
    query = {key: value for key, value in (params or {}).items() if value is not None}
    try:
        response = client.request(
            "GET",
            _url(settings, app, path),
            params=query,
            headers=_headers(settings, app),
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise _unreachable(app, "GET", path, exc, timeout_seconds) from exc
    if response.status_code >= 400:  # noqa: PLR2004 — the HTTP error boundary
        raise refusal(app, response)
    return response.headers.get("content-type", "text/plain; charset=utf-8"), response.text


def _error_frame(code: str, message: str) -> str:
    """The console's own terminal pair: why the stream ended, then that it did.

    An ``EventSource`` cannot tell an ended stream from a dropped one and retries both; the pages
    close on ``stream.closed``, as the log pane closes on ``log.closed``.
    """
    return format_frame(
        Event(sequence=0, type="error", payload={"code": code, "message": message}),
        generator=_GENERATOR,
    ) + format_frame(
        Event(sequence=0, type="stream.closed", payload={"reason": code}), generator=_GENERATOR
    )


def stream(
    client: httpx.Client,
    settings: Settings,
    app: str,
    path: str,
    *,
    last_event_id: str | None = None,
) -> Iterator[str]:
    """Proxy one of an application's SSE streams to the browser, frame text unchanged.

    The applications bind loopback (ADR-0126), so a browser on the LAN reaches their streams only
    through the console. ``Last-Event-ID`` is carried through, so the application's own replay
    decides what a reconnecting page is sent.

    Args:
        client: The pooled HTTP client.
        settings: The validated settings.
        app: One of the four.
        path: The stream's path under ``/api/v1``.
        last_event_id: The browser's ``Last-Event-ID``, when it sent one.

    Yields:
        The application's stream text as it arrives. A refusal or a dropped connection yields the
        console's ``error`` frame with the application's own code, then ``stream.closed``.
    """
    headers = {"Accept": "text/event-stream"}
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    try:
        with client.stream(
            "GET",
            _url(settings, app, path),
            headers=_headers(settings, app, headers),
            timeout=STREAM_TIMEOUT,
        ) as response:
            if response.status_code >= 400:  # noqa: PLR2004
                response.read()
                refused = refusal(app, response)
                yield _error_frame(str(refused.details["app_code"]), refused.message)
                return
            yield from response.iter_text()
    except httpx.HTTPError as exc:
        yield _error_frame(AppUnreachable.code, f"{app} did not answer: {exc}")


def download(
    client: httpx.Client,
    settings: Settings,
    app: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], Iterator[bytes]]:
    """Open one of an application's streamed downloads, refused before the first byte is sent.

    The status is read before the body, so an application's refusal (FreeWeight's 500-run export
    limit) reaches the page as itself rather than as an error glued onto a half-sent file.

    Args:
        client: The pooled HTTP client.
        settings: The validated settings.
        app: One of the four.
        path: The download's path under ``/api/v1``.
        params: Query parameters; ``None`` values are dropped.

    Returns:
        ``(headers, body)``: the application's ``content-type`` and ``content-disposition``, and
        its bytes as they arrive — the connection closes when the body is exhausted or dropped.

    Raises:
        AppRefused: The application answered 400 or above, in its own words.
        AppUnreachable: It did not answer.
    """
    query = {key: value for key, value in (params or {}).items() if value is not None}
    request = client.build_request(
        "GET",
        _url(settings, app, path),
        params=query,
        headers=_headers(settings, app),
        timeout=STREAM_TIMEOUT,
    )
    try:
        response = client.send(request, stream=True)
    except httpx.HTTPError as exc:
        raise _unreachable(app, "GET", path, exc, STREAM_TIMEOUT.read or 0.0) from exc
    if response.status_code >= 400:  # noqa: PLR2004 — the HTTP error boundary
        response.read()
        response.close()
        raise refusal(app, response)
    kept = {
        name: response.headers[name]
        for name in ("content-type", "content-disposition")
        if name in response.headers
    }

    def body() -> Iterator[bytes]:
        try:
            yield from response.iter_bytes()
        finally:
            response.close()

    return kept, body()


def lines(chunks: Iterable[str]) -> Iterator[str]:
    """Stream text chunks as whole lines; a chunk boundary can fall anywhere in a frame."""
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        *complete, buffer = buffer.split("\n")
        for line in complete:
            yield line.removesuffix("\r")
    if buffer:
        yield buffer.removesuffix("\r")


def as_text(document: Any) -> str:  # noqa: ANN401 — any JSON-safe document
    """A JSON document as pretty text, for a page that shows a record whole and escaped."""
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True)
