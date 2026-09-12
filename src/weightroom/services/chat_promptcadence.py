"""weightroom.services.chat_promptcadence — one reply as a PromptCadence trajectory.

PromptCadence is the other way chat reaches a model (spec §3, §11 contract 6), and every model call
inside it goes through LoadCoach (ADR-0045); nothing here knows a provider. This module speaks
PromptCadence's wire and nothing else.

**One trajectory per message.** A conversation's earlier turns are prepended to the new message as
context in ``task``; the trajectory runs its own plan, steps and tools. The message records the
trajectory id (``remote_job_id``) and the conversation keeps the latest one.

**The stream becomes cards, not deltas.** PromptCadence streams governance events, not tokens
(api.md §3): ``plan.drafted`` → a ``plan`` card; ``step.started``/``step.completed`` → ``step``;
``tool.call.started``/``tool.call.completed`` → ``tool_call``; ``approval.requested``/``granted``/
``denied`` → ``approval_pending`` with its status; ``trajectory.completed`` → the answer, read
from the last assistant turn (``GET /trajectories/{id}/turns``), then ``done``;
``trajectory.halted``/``failed``/``cancelled`` and ``plan.rejected`` → ``halt`` with PromptCadence's
own ``cause``, verbatim. Every event body is the envelope's ``payload.data``.

**Egress decisions are read at the end.** ``egress.evaluated`` is in PromptCadence's event
vocabulary but no code path emits it (found at W6), so the decisions a trajectory recorded are
fetched from ``GET /egress-decisions?trajectory_id=`` once it is terminal and shown as cards then.

**Thinking.** PromptCadence streams no reasoning, so a PromptCadence reply shows no thinking block
(the state machine's rule 6).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

import httpx

from weightroom.services.chat_loadcoach import BackendRefused, context_block, iter_frames

if TYPE_CHECKING:
    from weightroom.config import Settings

__all__ = [
    "APPROVE_SCOPE_TTL_SECONDS",
    "CARD_EVENTS",
    "HALT_EVENTS",
    "approval_decision",
    "build_task",
    "card_for",
    "fetch_answer",
    "fetch_egress",
    "fetch_tier_remote",
    "registered_tool_names",
    "stream_trajectory",
    "submit_trajectory",
    "token_can_approve",
]

STREAM_TIMEOUT: Final = httpx.Timeout(connect=5.0, read=900.0, write=30.0, pool=5.0)
"""Planning on a local model can be quiet for minutes between events."""

HALT_EVENTS: Final[frozenset[str]] = frozenset(
    {"trajectory.halted", "trajectory.failed", "trajectory.cancelled", "plan.rejected"}
)
CARD_EVENTS: Final[dict[str, str]] = {
    "plan.drafted": "plan",
    "plan.approved": "plan",
    "step.started": "step",
    "step.completed": "step",
    "step.retried": "step",
    "turn.completed": "step",
    "tool.call.started": "tool_call",
    "tool.call.completed": "tool_call",
    "egress.evaluated": "egress_decision",
    "approval.requested": "approval_pending",
    "approval.granted": "approval_pending",
    "approval.denied": "approval_pending",
}
"""PromptCadence event → the console's structured card kind (data model §2)."""

APPROVE_SCOPE_TTL_SECONDS: Final = 60.0


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _base(settings: Settings) -> str:
    return str(settings.apps.promptcadence.base_url).rstrip("/")


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"PromptCadence refused with {response.status_code}."
    error = body.get("error") if isinstance(body, Mapping) else None
    if isinstance(error, Mapping) and error.get("message"):
        code = f" ({error['code']})" if error.get("code") else ""
        return f"PromptCadence refused: {error['message']}{code}"
    return f"PromptCadence refused with {response.status_code}."


def build_task(history: Sequence[tuple[str, str]], attachments: Sequence[tuple[str, str]]) -> str:
    """The trajectory's ``task``: files, the earlier conversation, then the new message.

    Args:
        history: ``(role, content)`` pairs, oldest first; the last is the operator's new message.
        attachments: ``(filename, text)`` for every attachment of the conversation.
    """
    *earlier, (_role, message) = history
    parts = []
    if attachments:
        parts.append(context_block(attachments))
    if earlier:
        transcript = "\n\n".join(
            f"{'Operator' if role == 'user' else 'Assistant'}: {content}"
            for role, content in earlier
        )
        parts.append(f"The conversation so far:\n\n{transcript}\n")
    parts.append(message if not parts else f"The operator's new message:\n\n{message}")
    return "\n".join(parts)


def submit_trajectory(
    client: httpx.Client,
    settings: Settings,
    *,
    token: str | None,
    task: str,
    classification: str | None,
    tools: Sequence[str] | None,
    tier: str | None,
) -> str:
    """``POST /trajectories``; return the trajectory id.

    Raises:
        BackendRefused: PromptCadence refused the submission, in its own words.
        httpx.HTTPError: It did not answer.
    """
    # `tools` is always sent, empty when the conversation allows none: PromptCadence treats an
    # omitted allowlist as every configured tool (write_file, run_command, http_fetch included —
    # seen on the reference machine at W6), so leaving it out would grant what nobody chose.
    body: dict[str, Any] = {"task": task, "tools": list(tools or [])}
    if classification:
        body["data_classification"] = classification
    if tier:
        body["tier"] = tier
    response = client.post(
        f"{_base(settings)}/api/v1/trajectories", json=body, headers=_headers(token), timeout=30.0
    )
    if response.status_code >= 400:  # noqa: PLR2004 — the HTTP error boundary
        raise BackendRefused(_error_text(response))
    trajectory_id = response.json().get("trajectory_id")
    if not isinstance(trajectory_id, str) or not trajectory_id:
        raise BackendRefused("PromptCadence accepted the trajectory but returned no id.")
    return trajectory_id


def card_for(event: str, data: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The console's card kind and payload for one PromptCadence event, or ``None`` to ignore it.

    The payload is PromptCadence's own event body plus ``event`` (which transition it was) and,
    for an approval, ``status``. Nothing is rewritten; the page renders every field escaped.
    """
    kind = CARD_EVENTS.get(event)
    if kind is None:
        return None
    payload = {key: value for key, value in data.items() if key != "trajectory_id"}
    payload["event"] = event
    if kind == "approval_pending":
        payload["status"] = event.rsplit(".", 1)[-1]
    if kind == "tool_call":
        payload["title"] = str(data.get("tool_name") or "")
    elif kind == "step":
        payload["title"] = str(data.get("step_id") or "")
    return kind, payload


def stream_trajectory(
    client: httpx.Client, settings: Settings, *, token: str | None, trajectory_id: str
) -> Iterator[tuple[str, Any]]:
    """Follow one trajectory's stream.

    Yields:
        ``("card", (kind, payload))`` per structured event; ``("completed", data)`` for
        ``trajectory.completed``; ``("halt", cause)`` for a terminal halt. A stream that ends with
        neither yields a halt naming that.

    Raises:
        BackendRefused: PromptCadence refused the stream.
        httpx.HTTPError: The connection failed.
    """
    url = f"{_base(settings)}/api/v1/trajectories/{trajectory_id}/stream"
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with client.stream("GET", url, headers=headers, timeout=STREAM_TIMEOUT) as response:
        if response.status_code >= 400:  # noqa: PLR2004
            response.read()
            raise BackendRefused(_error_text(response))
        for frame in iter_frames(response.iter_lines()):
            body = frame.data.get("payload") if isinstance(frame.data, Mapping) else None
            data = body.get("data") if isinstance(body, Mapping) else None
            data = data if isinstance(data, Mapping) else {}
            if frame.event == "trajectory.completed":
                yield "completed", dict(data)
                return
            if frame.event in HALT_EVENTS:
                cause = data.get("cause") or data.get("reason") or frame.event
                code = f" ({data['error_code']})" if data.get("error_code") else ""
                yield "halt", f"PromptCadence: {cause}{code}"
                return
            card = card_for(frame.event, data)
            if card is not None:
                yield "card", card
    yield "halt", "PromptCadence's stream ended before the trajectory finished."


def fetch_answer(
    client: httpx.Client, settings: Settings, *, token: str | None, trajectory_id: str
) -> tuple[str, dict[str, Any] | None]:
    """The trajectory's answer — its last assistant turn — and the turns' summed token classes.

    A class any turn left unreported stays ``"unsupported"`` rather than being summed as zero
    (ADR-0016, ADR-0070).
    """
    response = client.get(
        f"{_base(settings)}/api/v1/trajectories/{trajectory_id}/turns",
        headers=_headers(token),
        timeout=30.0,
    )
    if response.status_code >= 400:  # noqa: PLR2004
        raise BackendRefused(_error_text(response))
    body = response.json()
    turns = body.get("items", body) if isinstance(body, Mapping) else body
    turns = [turn for turn in turns if isinstance(turn, Mapping)] if isinstance(turns, list) else []
    answer = next(
        (
            str(turn.get("content") or "")
            for turn in reversed(turns)
            if turn.get("role") == "assistant" and turn.get("content")
        ),
        "",
    )
    usage: dict[str, Any] = {}
    for turn in turns:
        for key, value in (turn.get("usage") or {}).items():
            if value == "unsupported" or usage.get(key) == "unsupported":
                usage[key] = "unsupported"
            elif isinstance(value, int) and not isinstance(value, bool):
                usage[key] = int(usage.get(key) or 0) + value
    return answer, (usage or None)


def fetch_egress(
    client: httpx.Client, settings: Settings, *, token: str | None, trajectory_id: str
) -> list[dict[str, Any]]:
    """The egress decisions the trajectory recorded; ``[]`` when PromptCadence does not answer."""
    try:
        response = client.get(
            f"{_base(settings)}/api/v1/egress-decisions",
            params={"trajectory_id": trajectory_id},
            headers=_headers(token),
            timeout=15.0,
        )
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    if response.status_code >= 400:  # noqa: PLR2004
        return []
    items = body.get("items", body) if isinstance(body, Mapping) else body
    return (
        [dict(item) for item in items if isinstance(item, Mapping)]
        if isinstance(items, list)
        else []
    )


def approval_decision(
    client: httpx.Client,
    settings: Settings,
    *,
    token: str | None,
    trajectory_id: str,
    decision: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """``POST /trajectories/{id}/approve|deny`` with the ``approve``-scoped token (ADR-0049).

    Raises:
        ValueError: ``decision`` is neither ``approve`` nor ``deny``.
        BackendRefused: PromptCadence refused (nothing pending, wrong scope), in its own words.
        httpx.HTTPError: It did not answer.
    """
    if decision not in {"approve", "deny"}:
        message = f"{decision!r} is not approve or deny"
        raise ValueError(message)
    body = {"reason": reason[:2000]} if (decision == "deny" and reason) else None
    response = client.post(
        f"{_base(settings)}/api/v1/trajectories/{trajectory_id}/{decision}",
        json=body,
        headers=_headers(token),
        timeout=30.0,
    )
    if response.status_code >= 400:  # noqa: PLR2004
        raise BackendRefused(_error_text(response))
    result = response.json()
    return dict(result) if isinstance(result, Mapping) else {}


_SCOPE_CACHE: dict[str, tuple[float, bool | None]] = {}
_SCOPE_LOCK = threading.Lock()


def token_can_approve(settings: Settings, *, now: float | None = None) -> bool | None:
    """Whether the console's PromptCadence token holds ``approve`` (``admin`` contains it).

    Read from PromptCadence's own ``token list`` (W4's token service), cached for a minute.
    ``None`` when it cannot be read — the page then says so rather than guessing either way.
    """
    from weightroom.services.tokens import list_tokens

    moment = now if now is not None else time.monotonic()
    with _SCOPE_LOCK:
        held = _SCOPE_CACHE.get("promptcadence")
        if held is not None and moment - held[0] < APPROVE_SCOPE_TTL_SECONDS:
            return held[1]
    try:
        records = list_tokens(settings, "promptcadence")
    except Exception:  # noqa: BLE001 — an unreadable list is "not known", never "yes"
        answer: bool | None = None
    else:
        mine = next((one for one in records if one.name == "weightroom" and not one.revoked), None)
        scopes = {part.strip() for part in (mine.scope if mine else "").replace(",", " ").split()}
        answer = bool(scopes & {"approve", "admin"}) if mine is not None else False
    with _SCOPE_LOCK:
        _SCOPE_CACHE["promptcadence"] = (moment, answer)
    return answer


def registered_tool_names(client: httpx.Client, settings: Settings) -> list[str]:
    """The names PromptCadence's registry has **registered**, sorted, for the chat composer.

    A configured tool PromptCadence withheld (``registered`` false — no sandbox rung, a bad
    signature) is left out: it cannot run, and "allow all tools" writes a snapshot of what exists
    now, never a standing grant that a later registration would silently join.

    Raises:
        AppRefused: PromptCadence refused ``GET /tools``.
        AppUnreachable: It did not answer.
    """
    from weightroom.services.promptcadence_pages import tools_api

    report = tools_api(client, settings)
    tools = report.get("tools")
    names = {
        str(one.get("name"))
        for one in (tools if isinstance(tools, list) else [])
        if isinstance(one, Mapping) and one.get("registered") and one.get("name")
    }
    return sorted(names)


def fetch_tier_remote(
    client: httpx.Client, settings: Settings, *, token: str | None, tier: str
) -> bool | None:
    """Whether the named tier is remote, from PromptCadence's own ``GET /tiers`` rows.

    ``None`` when it cannot be read or the tier is not listed — the cost line then says so
    rather than assuming a local model costs nothing.
    """
    if not tier:
        return None
    try:
        response = client.get(
            f"{_base(settings)}/api/v1/tiers", headers=_headers(token), timeout=15.0
        )
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    rows = body.get("rows") if isinstance(body, Mapping) else None
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, Mapping) and row.get("name") == tier:
            value = row.get("is_remote")
            return value if isinstance(value, bool) else None
    return None
