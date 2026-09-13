"""weightroom.services.loadcoach_actions — what an operator does to LoadCoach (row WP2).

Every action is one call to LoadCoach's own API, which validates the request and refuses in its own
words; nothing here re-decides what LoadCoach decides. What is done here and nowhere else is turning
a form's text fields into the wire body — a blank field into an absent key, a number into a number —
and refusing a field that cannot parse before anything is sent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Final

from baseaicore import DataClassification, SuiteError

from weightroom.services.app_api import call
from weightroom.services.loadcoach_pages import APP, segment

if TYPE_CHECKING:
    import httpx

    from weightroom.config import Settings

__all__ = [
    "CLASSIFICATIONS",
    "QUEUE_VERBS",
    "RUNTIME_PROFILE_FIELDS",
    "SECURITY_FIELDS",
    "LoadCoachFormInvalid",
    "cancel_job",
    "delete_registration",
    "discover",
    "evidence_bundle",
    "explain",
    "feedback_body",
    "freeweight_pull",
    "import_evidence",
    "job_body",
    "queue_control",
    "registration_values",
    "route_body",
    "save_registration",
    "send_feedback",
    "set_enabled",
    "submit_job",
    "touched",
    "warm",
]

RUNTIME_PROFILE_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("context_size", "int"),
    ("gpu_layers", "int"),
    ("threads", "int"),
    ("batch_size", "int"),
    ("kv_cache_precision", "text"),
    ("keep_alive", "text"),
    ("flash_attention", "bool"),
)
"""``overrides.runtime_profile``'s keys (routing §10) and how the form's text becomes each."""

_DISCOVER_TIMEOUT_SECONDS: Final = 120.0
"""A scan asks every registration what it serves; a llama.cpp directory is hashed on the way."""
_ACTION_TIMEOUT_SECONDS: Final = 30.0


class LoadCoachFormInvalid(SuiteError):
    """A field the page sent cannot become LoadCoach's body; nothing was sent."""

    code: ClassVar[str] = "VALIDATION_ERROR"


def _number(label: str, raw: str, *, minimum: int) -> int | None:
    text = raw.strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError as exc:
        message = f"{label} must be a whole number; got {text!r}."
        raise LoadCoachFormInvalid(message, details={"field": label}) from exc
    if value < minimum:
        message = f"{label} must be at least {minimum}; got {value}."
        raise LoadCoachFormInvalid(message, details={"field": label})
    return value


def route_body(  # noqa: PLR0913 — one keyword per field of POST /route's body
    *,
    task: str,
    estimated_input_tokens: str,
    max_output_tokens: str,
    requires_capabilities: str,
    model: str,
    adapter: str,
    runtime_profile: Mapping[str, str],
    disallow_fallback: bool,
    require_evidence: bool,
    ignore_residency: bool,
) -> dict[str, Any]:
    """The ``POST /route`` body the explain form describes (api.md §3, routing §10).

    ``POST /route`` takes no data classification — only ``/generate`` and ``/jobs`` do, where an
    adapter's classification is joined with the caller's — so the form offers none.

    Args:
        task: The task profile id. Required.
        estimated_input_tokens: A whole number, or blank.
        max_output_tokens: A whole number of at least 1, or blank.
        requires_capabilities: Capability ids, comma-separated, or blank.
        model: A canonical id to pin, or blank.
        adapter: An adapter's manifest name to pin, or blank.
        runtime_profile: ``overrides.runtime_profile`` keys to their form text; blanks are dropped.
        disallow_fallback: Refuse a fallback candidate.
        require_evidence: Refuse a candidate with no measured evidence.
        ignore_residency: Zero both residency terms for this call.

    Returns:
        The JSON body; ``overrides`` only when one of them was set.

    Raises:
        LoadCoachFormInvalid: The task is blank, or a number does not parse.
    """
    if not task.strip():
        message = "Choose a task profile; routing ranks candidates against one."
        raise LoadCoachFormInvalid(message, details={"field": "task"})
    body: dict[str, Any] = {"task": task.strip()}
    tokens_in = _number("Estimated input tokens", estimated_input_tokens, minimum=0)
    if tokens_in is not None:
        body["estimated_input_tokens"] = tokens_in
    tokens_out = _number("Max output tokens", max_output_tokens, minimum=1)
    if tokens_out is not None:
        body["max_output_tokens"] = tokens_out
    capabilities = [part.strip() for part in requires_capabilities.split(",") if part.strip()]
    if capabilities:
        body["constraints"] = {"requires_capabilities": capabilities}
    profile: dict[str, Any] = {}
    for name, kind in RUNTIME_PROFILE_FIELDS:
        raw = str(runtime_profile.get(name) or "").strip()
        if not raw:
            continue
        if kind == "int":
            profile[name] = _number(name, raw, minimum=0)
        elif kind == "bool":
            profile[name] = raw == "true"
        else:
            profile[name] = raw
    overrides: dict[str, Any] = {}
    if model.strip():
        overrides["model"] = model.strip()
    if adapter.strip():
        overrides["adapter"] = adapter.strip()
    if profile:
        overrides["runtime_profile"] = profile
    for key, flag in (
        ("disallow_fallback", disallow_fallback),
        ("require_evidence", require_evidence),
        ("ignore_residency", ignore_residency),
    ):
        if flag:
            overrides[key] = True
    if overrides:
        body["overrides"] = overrides
    return body


def explain(client: httpx.Client, settings: Settings, body: Mapping[str, Any]) -> dict[str, Any]:
    """``POST /route``: the full routing explanation, without executing anything.

    Raises:
        AppRefused: ``TASK_PROFILE_NOT_FOUND``, ``NO_ELIGIBLE_MODEL`` (every candidate and its
            rejection in ``app_details``), ``ADAPTER_NOT_FOUND``, ``VALIDATION_ERROR``.
        AppUnreachable: It did not answer.
    """
    document = call(
        client, settings, APP, "POST", "route", body=dict(body),
        timeout_seconds=_ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(document) if isinstance(document, Mapping) else {}


def discover(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``POST /models/discover``: one discovery pass over every registration.

    Raises:
        AppRefused: LoadCoach refused (the console's token below ``admin``).
        AppUnreachable: It did not answer.
    """
    document = call(
        client, settings, APP, "POST", "models/discover", timeout_seconds=_DISCOVER_TIMEOUT_SECONDS
    )
    return dict(document) if isinstance(document, Mapping) else {}


def warm(client: httpx.Client, settings: Settings, model_ref: str) -> dict[str, Any]:
    """``POST /models/{ref}/warm``: one small pinned job through the ordinary queue.

    Raises:
        AppRefused: ``MODEL_NOT_FOUND``, ``QUEUE_FULL``, or another refusal.
        AppUnreachable: It did not answer.
    """
    document = call(
        client, settings, APP, "POST", f"models/{segment(model_ref)}/warm",
        timeout_seconds=_ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(document) if isinstance(document, Mapping) else {}


def set_enabled(
    client: httpx.Client, settings: Settings, model_ref: str, *, enabled: bool
) -> dict[str, Any]:
    """ADR-0118's flag, through the catalog's own call (row W8) rather than a second one.

    Raises:
        CatalogRefused: LoadCoach did not answer, or refused (its message carried through).
    """
    from weightroom.services.catalog import set_enabled as catalog_set_enabled

    return catalog_set_enabled(settings, APP, segment(model_ref), enabled=enabled, client=client)


# --- Queue and jobs -------------------------------------------------------------------------------

CLASSIFICATIONS: Final[tuple[str, ...]] = tuple(level.value for level in DataClassification)

QUEUE_VERBS: Final[dict[str, str]] = {
    "pause": (
        "Pausing stops LoadCoach dispatching queued jobs — anything submitted to POST /jobs, a "
        "warm, a job from this page — until it is resumed. Nothing is dropped, and work already "
        "executing finishes. Synchronous generation is not held: PromptCadence (POST /generate), "
        "IdeaPress and this console's chat (POST /generate/stream) are served as before."
    ),
    "resume": (
        "Resuming lets LoadCoach dispatch again and clears a drain: waiting jobs start on the "
        "scheduler's next tick."
    ),
    "drain": (
        "Draining finishes the jobs already executing and dispatches nothing new, for a clean "
        "shutdown; queued jobs wait until the queue is resumed. Synchronous generation — "
        "PromptCadence, IdeaPress, this console's chat — is not held."
    ),
}
"""What each queue control stops, said before it is sent (read from LoadCoach's code: the flags
gate the worker's dispatch, and ``/generate`` never consults them)."""

_NOTES_CHARS: Final = 4000
_IDEMPOTENCY_KEY_CHARS: Final = 128
_IMPORT_TIMEOUT_SECONDS: Final = 120.0


def queue_control(client: httpx.Client, settings: Settings, verb: str) -> dict[str, Any]:
    """``POST /queue/pause|resume|drain``: the durable flag the scheduler reads every second.

    Raises:
        ValueError: ``verb`` is not one of :data:`QUEUE_VERBS`.
        AppRefused: LoadCoach refused (the console's token below ``admin``).
        AppUnreachable: It did not answer.
    """
    if verb not in QUEUE_VERBS:
        message = f"{verb!r} is not a queue control"
        raise ValueError(message)
    document = call(client, settings, APP, "POST", f"queue/{verb}")
    return dict(document) if isinstance(document, Mapping) else {}


def _decimal(label: str, raw: str, *, lowest: float, highest: float) -> float | None:
    text = raw.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        message = f"{label} must be a number; got {text!r}."
        raise LoadCoachFormInvalid(message, details={"field": label}) from exc
    if not lowest <= value <= highest:
        message = f"{label} must be between {lowest} and {highest}; got {value}."
        raise LoadCoachFormInvalid(message, details={"field": label})
    return value


def job_body(  # noqa: PLR0913 — one keyword per field of POST /jobs' body
    *,
    task: str,
    prompt: str,
    system: str,
    job_class: str,
    priority: str,
    max_wait_seconds: str,
    idempotent: bool,
    stream: bool,
    data_classification: str,
    model: str,
    adapter: str,
    temperature: str,
    max_output_tokens: str,
    think: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """The ``POST /jobs`` body the Submit form describes (api.md §4–§5).

    ``idempotency_key`` is minted when the page renders, so a form sent twice — a double click, a
    resubmitted page — returns the first job rather than queueing a second. Blank fields are left
    out, so LoadCoach's own defaults and the task profile's execution block apply.

    Raises:
        LoadCoachFormInvalid: The task or the prompt is blank, or a number does not parse.
    """
    if not task.strip():
        message = "Choose a task profile; LoadCoach routes the job against one."
        raise LoadCoachFormInvalid(message, details={"field": "task"})
    if not prompt.strip():
        message = "The prompt is empty; a job needs something to send."
        raise LoadCoachFormInvalid(message, details={"field": "prompt"})
    body: dict[str, Any] = {
        "task": task.strip(),
        "prompt": prompt,
        "class": job_class.strip() or "normal",
        "idempotent": idempotent,
        "stream": stream,
    }
    if system.strip():
        body["system"] = system
    level = _number("Priority", priority, minimum=0)
    if level is not None:
        body["priority"] = level
    wait = _number("Max wait seconds", max_wait_seconds, minimum=1)
    if wait is not None:
        body["max_wait_seconds"] = wait
    if data_classification.strip():
        body["data_classification"] = data_classification.strip()
    sampling: dict[str, Any] = {}
    heat = _decimal("Temperature", temperature, lowest=0.0, highest=2.0)
    if heat is not None:
        sampling["temperature"] = heat
    tokens = _number("Max output tokens", max_output_tokens, minimum=1)
    if tokens is not None:
        sampling["max_output_tokens"] = tokens
    if think in {"true", "false"}:
        sampling["think"] = think == "true"
    if sampling:
        body["sampling"] = sampling
    overrides = {
        key: value.strip()
        for key, value in (("model", model), ("adapter", adapter))
        if value.strip()
    }
    if overrides:
        body["overrides"] = overrides
    if idempotency_key.strip():
        body["idempotency_key"] = idempotency_key.strip()[:_IDEMPOTENCY_KEY_CHARS]
    return body


def submit_job(client: httpx.Client, settings: Settings, body: Mapping[str, Any]) -> dict[str, Any]:
    """``POST /jobs``: the queued job's document (``202``), or the original one for a repeated key.

    Raises:
        AppRefused: ``TASK_PROFILE_NOT_FOUND``, ``VALIDATION_ERROR`` (a priority outside its class's
            band), ``QUEUE_FULL``, in LoadCoach's words.
        AppUnreachable: It did not answer.
    """
    document = call(
        client, settings, APP, "POST", "jobs", body=dict(body),
        timeout_seconds=_ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(document) if isinstance(document, Mapping) else {}


def cancel_job(client: httpx.Client, settings: Settings, job_id: str) -> dict[str, Any]:
    """``POST /jobs/{id}/cancel``: at once while waiting, at the next chunk while executing.

    Raises:
        AppRefused: ``JOB_NOT_CANCELLABLE`` for a finished job, ``JOB_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    document = call(
        client, settings, APP, "POST", f"jobs/{segment(job_id)}/cancel",
        timeout_seconds=_ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(document) if isinstance(document, Mapping) else {}


def feedback_body(
    *, accepted: str, quality_score: str, edited: bool, validation_passed: str, notes: str
) -> dict[str, Any]:
    """The ``POST /jobs/{id}/feedback`` body (api.md §6); ``source`` is LoadCoach's to set.

    Raises:
        LoadCoachFormInvalid: ``accepted`` is not stated, or the quality is not in ``[0, 1]``.
    """
    if accepted not in {"true", "false"}:
        message = "Say whether the output was accepted."
        raise LoadCoachFormInvalid(message, details={"field": "accepted"})
    body: dict[str, Any] = {"accepted": accepted == "true", "edited": edited}
    quality = _decimal("Quality", quality_score, lowest=0.0, highest=1.0)
    if quality is not None:
        body["quality_score"] = quality
    if validation_passed in {"true", "false"}:
        body["validation"] = {"passed": validation_passed == "true"}
    if notes.strip():
        body["notes"] = notes.strip()[:_NOTES_CHARS]
    return body


def send_feedback(
    client: httpx.Client, settings: Settings, job_id: str, body: Mapping[str, Any]
) -> dict[str, Any]:
    """``POST /jobs/{id}/feedback``; idempotent per ``(job, source)``.

    Raises:
        AppRefused: ``JOB_NOT_FOUND``, ``VALIDATION_ERROR``.
        AppUnreachable: It did not answer.
    """
    document = call(
        client, settings, APP, "POST", f"jobs/{segment(job_id)}/feedback", body=dict(body),
        timeout_seconds=_ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(document) if isinstance(document, Mapping) else {}


# --- Evidence -------------------------------------------------------------------------------------


def evidence_bundle(raw: bytes) -> dict[str, Any]:
    """An uploaded file as the JSON object ``POST /evidence/import`` takes; LoadCoach validates it.

    Raises:
        LoadCoachFormInvalid: The file is empty, not UTF-8 JSON, or not an object.
    """
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        message = (
            "The file is not a JSON document; export a benchmark.evidence_bundle from FreeWeight."
        )
        raise LoadCoachFormInvalid(message, details={"field": "file"}) from exc
    if not isinstance(document, dict):
        message = "The file is JSON but not an object; a bundle is one envelope."
        raise LoadCoachFormInvalid(message, details={"field": "file"})
    return document


def freeweight_pull(settings: Settings) -> dict[str, Any]:
    """The pull form's body: FreeWeight's URL from this console's own ``[apps.freeweight]``.

    LoadCoach's fetch allowlist decides whether it may be read (ADR-0026 §3); nothing here does.
    """
    return {"url": str(settings.apps.freeweight.base_url).rstrip("/")}


def import_evidence(
    client: httpx.Client, settings: Settings, body: Mapping[str, Any]
) -> dict[str, Any]:
    """``POST /evidence/import``: counts imported, updated, unmatched and rejected, with reasons.

    Raises:
        AppRefused: ``EVIDENCE_SOURCE_REFUSED``, ``SCHEMA_VERSION_UNSUPPORTED``,
            ``API_VERSION_UNSUPPORTED``, ``VALIDATION_ERROR``, in LoadCoach's words.
        AppUnreachable: It did not answer.
    """
    document = call(
        client, settings, APP, "POST", "evidence/import", body=dict(body),
        timeout_seconds=_IMPORT_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(document) if isinstance(document, Mapping) else {}


# --- Providers ------------------------------------------------------------------------------------

SECURITY_FIELDS: Final[frozenset[str]] = frozenset({"kind", "base_url", "remote"})
"""A registration's keys whose change asks for the operator's password (spec §7.4): where prompts go
and whether that place is declared remote. They are the registration's form of the keys LoadCoach's
own ``config schema --json`` names security-relevant — ``provider.kind``, ``provider.base_url`` and
``providers.allow_remote`` — which do not name ``providers.<name>.*`` because a table's name is the
operator's."""


def registration_values(  # noqa: PLR0913 — one keyword per writable key (ADR-0117)
    *,
    kind: str,
    base_url: str,
    timeout_seconds: str,
    remote: bool,
    model_directory: str,
    state_dir: str,
    server_path: str,
    enabled: bool,
) -> dict[str, Any]:
    """The ``PUT /providers/{name}`` values the form describes; LoadCoach validates them.

    Every text key is sent, blank included: an empty optional key removes it from the table, as it
    does on LoadCoach's own page. ``timeout_seconds`` is left out when blank, so the table keeps it.
    ``enabled`` is sent as the checkbox stands (row WX9) — unticked is ``false``, which is what
    an unticked box means; LoadCoach refuses the write that would leave no registration enabled.

    Raises:
        LoadCoachFormInvalid: ``kind`` is blank, or the timeout is not a positive number.
    """
    if not kind.strip():
        message = "A registration needs a kind: ollama, llamacpp or fake."
        raise LoadCoachFormInvalid(message, details={"field": "kind"})
    values: dict[str, Any] = {
        "kind": kind.strip(),
        "base_url": base_url.strip(),
        "model_directory": model_directory.strip(),
        "state_dir": state_dir.strip(),
        "server_path": server_path.strip(),
        "remote": remote,
        "enabled": enabled,
    }
    timeout = _decimal("Timeout seconds", timeout_seconds, lowest=0.1, highest=86400.0)
    if timeout is not None:
        values["timeout_seconds"] = timeout
    return values


def touched(
    current: Mapping[str, Any] | None, values: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    """``(changed keys, changed security keys)``; every key of a new registration is a change."""
    changed = sorted(
        key for key, value in values.items() if current is None or current.get(key) != value
    )
    return changed, sorted(SECURITY_FIELDS.intersection(changed))


def save_registration(
    client: httpx.Client,
    settings: Settings,
    name: str,
    values: Mapping[str, Any],
    *,
    base_digest: str,
) -> dict[str, Any]:
    """``PUT /providers/{name}``: LoadCoach writes its file and re-registers.

    Raises:
        AppRefused: ``VALIDATION_ERROR`` naming the key, ``CONFLICT`` when the file changed since
            ``base_digest`` was read, in LoadCoach's words.
        AppUnreachable: It did not answer.
    """
    body = {**values, **({"base_digest": base_digest} if base_digest else {})}
    document = call(
        client, settings, APP, "PUT", f"providers/{segment(name)}", body=body,
        timeout_seconds=_ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(document) if isinstance(document, Mapping) else {}


def delete_registration(client: httpx.Client, settings: Settings, name: str) -> dict[str, Any]:
    """``DELETE /providers/{name}``.

    Raises:
        AppRefused: The last registration, or an unknown one, in LoadCoach's words.
        AppUnreachable: It did not answer.
    """
    document = call(
        client, settings, APP, "DELETE", f"providers/{segment(name)}",
        timeout_seconds=_ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(document) if isinstance(document, Mapping) else {}
