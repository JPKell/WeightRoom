"""weightroom.services.freeweight_pages — the data behind FreeWeight's tab (row WP3).

Each page has a reader over FreeWeight's own ``/api/v1`` (through
:mod:`~weightroom.services.app_api`) for while it answers, and — for what spec §7.3 has the
database answer when FreeWeight is stopped: the models and runs listings, one run, its samples, one
sample — a reader over its database that shapes rows into the API document's names, so one template
renders both. Which one runs is :mod:`~weightroom.services.app_pages`' decision, never this
module's. What only FreeWeight's own arithmetic produces — whether a model has results, a telemetry
window, a comparison verdict, an export — has no database reader and renders ``—`` when stopped
(ADR-0016), never a number recomputed here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Final
from urllib.parse import quote

from baseaicore import SuiteError
from mirrorwall import Event, format_frame
from setspec import GeneratorInfo

from weightroom.__about__ import __version__
from weightroom.services.app_api import AppRefused, call, lines
from weightroom.services.app_pages import rows_where
from weightroom.services.chat_loadcoach import iter_frames

if TYPE_CHECKING:
    import httpx

    from weightroom.config import Settings
    from weightroom.services.db_reader import AppDatabase

__all__ = [
    "APP",
    "DASHBOARD_FILTERS",
    "EVIDENCE_FILTERS",
    "EXPORT_FORMATS",
    "EXPORT_SCOPES",
    "MODEL_FILTERS",
    "RESULT_FILTERS",
    "RUN_FILTERS",
    "RUN_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "NotRecorded",
    "adapter_api",
    "adapter_db",
    "adapters_api",
    "adapters_db",
    "bar_charts_by_test",
    "benchmarks_api",
    "charts",
    "compare_api",
    "compare_bar_options",
    "context_fit_api",
    "model_facets",
    "dashboard_api",
    "database_stats_api",
    "evidence_api",
    "evidence_record",
    "export_params",
    "machine_api",
    "machine_db",
    "machines_api",
    "machines_db",
    "model_api",
    "model_db",
    "models_api",
    "models_db",
    "provider_api",
    "results_api",
    "run_api",
    "run_db",
    "run_log_frames",
    "runs_api",
    "runs_db",
    "sample_api",
    "sample_db",
    "samples_api",
    "score_heatmap_option",
    "samples_db",
    "segment",
    "system_api",
]

APP: Final = "freeweight"
PAGE_ROWS: Final = 50
"""Unused in this module since row WX5 (every reader here takes ``page_rows`` from the caller,
read from ``settings.ui.page_rows``); kept for :mod:`~weightroom.services.freeweight_goals`,
which is not a page reader and does not have a request's settings to read."""
LIST_CAP: Final = 500
"""A table larger than this is read in part when FreeWeight is stopped; its API pages everything."""

RUN_STATUSES: Final[tuple[str, ...]] = (
    "queued",
    "preparing",
    "warming",
    "running",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
)
"""FreeWeight's ``RunStatus`` members, in its declaration order."""
TERMINAL_RUN_STATUSES: Final[frozenset[str]] = frozenset(
    {"completed", "failed", "cancelled", "interrupted"}
)
TERMINAL_RUN_EVENTS: Final[frozenset[str]] = frozenset(
    {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}
)
"""FreeWeight's ``_TERMINAL_EVENT_TYPES``: its stream closes after one of these."""
RUN_FILTERS: Final[tuple[str, ...]] = (
    "status",
    "model",
    "suite",
    "machine",
    "label",
    "adapter",
    "since",
    "until",
)
"""``GET /runs``' filters (api.md §4), in the order the Runs page's form offers them."""

_ERROR_EVENTS: Final[frozenset[str]] = frozenset({"run.failed", "test.failed", "sample.failed"})
_WARNING_EVENTS: Final[frozenset[str]] = frozenset(
    {"run.cancelled", "run.interrupted", "run.degraded", "test.skipped"}
)
_GENERATOR = GeneratorInfo(name="weightroom", version=__version__)


class NotRecorded(SuiteError):
    """FreeWeight's database holds no such record, or more than one matches a prefix."""

    code: ClassVar[str] = "NOT_FOUND"


def segment(value: str) -> str:
    """``value`` quoted as one path segment, so an id can never add a segment or a query."""
    return quote(value, safe="")


def _loads(value: Any) -> Any:  # noqa: ANN401 — a stored JSON column, whatever it holds
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _document(body: Any) -> dict[str, Any]:  # noqa: ANN401 — the application's JSON body
    return dict(body) if isinstance(body, Mapping) else {}


def _listed(body: Any, key: str) -> list[dict[str, Any]]:  # noqa: ANN401 — a JSON body
    found = body.get(key) if isinstance(body, Mapping) else None
    return [dict(one) for one in found or [] if isinstance(one, Mapping)]


def _one(handle: AppDatabase, table_name: str, ref: str, what: str) -> dict[str, Any]:
    """One row by its ULID or an unambiguous prefix of it (ADR-0024).

    Raises:
        NotRecorded: Nothing matches, or more than one row does.
    """
    wanted = ref.strip()
    if wanted:
        exact = rows_where(handle, table_name, equals={"id": wanted}, limit=1)
        if exact:
            return exact[0]
    matches = [
        row
        for row in rows_where(handle, table_name, limit=LIST_CAP)
        if wanted and str(row.get("id") or "").startswith(wanted)
    ]
    if len(matches) == 1:
        return matches[0]
    raise NotRecorded(
        f"FreeWeight's database holds no {what} {ref!r}."
        if not matches
        else f"{ref!r} is ambiguous: {len(matches)} {what}s start with it.",
        details={what: ref},
    )


def _names(handle: AppDatabase) -> dict[str, dict[Any, Any]]:
    """The ids a run row carries, mapped to the names its API document uses."""
    return {
        "models": {
            row.get("id"): row.get("canonical_id")
            for row in rows_where(handle, "models", limit=LIST_CAP)
        },
        "suites": {
            row.get("id"): (row.get("key"), row.get("version"))
            for row in rows_where(handle, "benchmark_suites", limit=LIST_CAP)
        },
        "machines": {
            row.get("id"): row.get("machine_fingerprint")
            for row in rows_where(handle, "machines", limit=LIST_CAP)
        },
        "profiles": {
            row.get("id"): row.get("profile_hash")
            for row in rows_where(handle, "runtime_profiles", limit=LIST_CAP)
        },
        "adapters": {
            row.get("id"): row.get("name") for row in rows_where(handle, "adapters", limit=LIST_CAP)
        },
    }


# --- Models ---------------------------------------------------------------------------------------


MODEL_FILTERS: Final[tuple[str, ...]] = (
    "has_results",
    "provider_kind",
    "family",
    "quantization",
    "min_parameters",
    "max_parameters",
)
"""Every ``GET /models`` filter the Models page offers, by FreeWeight's own parameter name."""


def models_api(
    client: httpx.Client,
    settings: Settings,
    *,
    sort: str | None,
    filters: Mapping[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """``GET /models``: every identity with its latest descriptor, ``enabled`` and ``has_results``.

    Args:
        client: The pooled HTTP client.
        settings: The validated settings.
        sort: ``last_seen_at`` or ``canonical_id``, ``-`` for descending.
        filters: Any of :data:`MODEL_FILTERS`; a blank or missing one is not sent.

    Raises:
        AppRefused: FreeWeight refused (``VALIDATION_ERROR`` for an unknown ``sort``).
        AppUnreachable: It did not answer.
    """
    wanted = {key: (filters or {}).get(key) or None for key in MODEL_FILTERS}
    body = call(
        client, settings, APP, "GET", "models",
        params={**wanted, "sort": sort}, timeout_seconds=30.0,
    )  # fmt: skip
    return _listed(body, "items")


def model_facets(models: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """The provider, family and quantization values a model list actually holds.

    The Models page's three selects are built from this rather than from a vocabulary the console
    keeps: a family FreeWeight has never seen is not a filter anyone can want, and a list that
    grew one is a select that grew an option with no console release.

    Args:
        models: The rows ``GET /models`` returned.

    Returns:
        ``{"provider_kind": [...], "family": [...], "quantization": [...]}``, each sorted, each
        without the blank a row that reported nothing leaves.
    """
    keys = ("provider_kind", "family", "quantization")
    return {key: sorted({str(row.get(key)) for row in models if row.get(key)}) for key in keys}


def _descriptor(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``model_descriptors`` row under ``GET /models/{ref}``' descriptor names."""
    keys = (
        "observed_at", "family", "architecture", "parameter_count", "active_parameter_count",
        "expert_count", "quantization", "weight_format", "size_bytes", "max_context",
        "embedding_dim", "layers", "attention_heads",
    )  # fmt: skip
    return {key: row.get(key) for key in keys}


def _identity(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "canonical_id", "provider_kind", "provider_model_name", "artifact_digest",
        "identity_confidence", "first_seen_at", "last_seen_at",
    )  # fmt: skip
    return {**{key: row.get(key) for key in keys}, "enabled": bool(row.get("enabled"))}


def models_db(handle: AppDatabase, *, sort: str | None) -> list[dict[str, Any]]:
    """The ``models`` table with each one's latest descriptor, newest sighting first.

    ``has_results`` is ``None``: it is FreeWeight's join over its runs and metrics, and a stopped
    FreeWeight's page says so rather than recomputing it.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    latest: dict[Any, Mapping[str, Any]] = {}
    for row in rows_where(handle, "model_descriptors", order_by="observed_at", limit=LIST_CAP * 4):
        latest.setdefault(row.get("model_id"), row)
    models = []
    for row in rows_where(handle, "models", order_by="last_seen_at", limit=LIST_CAP):
        descriptor = latest.get(row.get("id")) or {}
        models.append(
            {
                **_identity(row),
                "quantization": descriptor.get("quantization"),
                "parameter_count": descriptor.get("parameter_count"),
                "max_context": descriptor.get("max_context"),
                "family": descriptor.get("family"),
                "has_results": None,
            }
        )
    key = (sort or "").removeprefix("-")
    if key in {"canonical_id", "last_seen_at"}:
        models.sort(key=lambda one: str(one.get(key) or ""), reverse=(sort or "").startswith("-"))
    return models


def evidence_record(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """One ``capability.evidence`` envelope's payload, with the columns the pages show lifted out.

    ``payload`` stays whole beside them, so a page can show the record as FreeWeight exported it.
    """
    payload = _document(_document(envelope).get("payload"))
    model = _document(payload.get("model"))
    adapter = _document(payload.get("adapter"))
    return {
        "capability_id": payload.get("capability_id"),
        "subject": model.get("canonical_id"),
        "adapter": adapter.get("name") or None,
        "score": payload.get("score"),
        "confidence": payload.get("confidence"),
        "sample_count": payload.get("sample_count"),
        "excluded_count": payload.get("excluded_count"),
        "measured_at": payload.get("measured_at"),
        "computed_at": payload.get("computed_at"),
        "runtime_profile_hash": payload.get("runtime_profile_hash"),
        "machine_fingerprint": payload.get("machine_fingerprint"),
        "policy_version": payload.get("policy_version"),
        "contributing_metrics": payload.get("contributing_metrics") or [],
        "source_run_ids": payload.get("source_run_ids") or [],
        "goal_hash": payload.get("goal_hash"),
        "score_method_mix": payload.get("score_method_mix"),
        "judge_set": payload.get("judge_set"),
        "calibration": payload.get("calibration"),
        "judge_validity_factor": payload.get("judge_validity_factor"),
        "schema_version": _document(envelope).get("schema_version"),
        "payload": payload,
    }


def model_api(
    client: httpx.Client,
    settings: Settings,
    model_ref: str,
    *,
    suite: str | None,
    runtime_profile: str | None,
    cursor: str | None,
    page_rows: int,
) -> dict[str, Any]:
    """``GET /models/{ref}``, a page of its ``/results`` and its ``GET /evidence?model=``.

    The evidence is read separately and a refusal of it leaves ``None``, so the identity and the
    results still render.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        AppRefused: ``MODEL_NOT_FOUND``, an ambiguous prefix, or a refused results filter.
        AppUnreachable: It did not answer.
    """
    path = f"models/{segment(model_ref)}"
    model = _document(call(client, settings, APP, "GET", path, timeout_seconds=30.0))
    results = _document(
        call(
            client, settings, APP, "GET", f"{path}/results",
            params={"suite": suite, "runtime_profile_hash": runtime_profile, "cursor": cursor,
                    "limit": page_rows},
            timeout_seconds=30.0,
        )
    )  # fmt: skip
    evidence: list[dict[str, Any]] | None
    try:
        body = call(
            client, settings, APP, "GET", "evidence",
            params={"model": model.get("id") or model_ref, "limit": LIST_CAP},
        )  # fmt: skip
        evidence = [evidence_record(item) for item in _listed(body, "items")]
    except AppRefused:
        evidence = None
    return {
        "model": model,
        "results": _listed(results, "items"),
        "next_cursor": results.get("next_cursor"),
        "evidence": evidence,
    }


def model_db(handle: AppDatabase, model_ref: str) -> dict[str, Any]:
    """One model by ULID or prefix, its descriptor history and its stored evidence rows.

    Its results are FreeWeight's query over five tables, read only from its API (``None``).

    Raises:
        NotRecorded: Nothing matches ``model_ref``, or more than one model does.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    row = _one(handle, "models", model_ref, "model")
    history = [
        _descriptor(one)
        for one in rows_where(
            handle, "model_descriptors", equals={"model_id": row.get("id")},
            order_by="observed_at", limit=LIST_CAP,
        )
    ]  # fmt: skip
    names = _names(handle)
    evidence = [
        {
            "capability_id": one.get("capability_id"),
            "subject": one.get("subject_canonical_id"),
            "adapter": names["adapters"].get(one.get("adapter_id")),
            "score": one.get("score"),
            "confidence": one.get("confidence"),
            "sample_count": one.get("sample_count"),
            "excluded_count": one.get("excluded_count"),
            "measured_at": one.get("measured_at"),
            "computed_at": one.get("computed_at"),
            "runtime_profile_hash": names["profiles"].get(one.get("runtime_profile_id")),
            "machine_fingerprint": names["machines"].get(one.get("machine_id")),
            "policy_version": one.get("policy_version"),
            "contributing_metrics": _loads(one.get("contributing_metrics_json")) or [],
            "source_run_ids": _loads(one.get("source_run_ids_json")) or [],
            "goal_hash": one.get("goal_hash"),
            "score_method_mix": _loads(one.get("score_method_mix_json")),
            "judge_set": _loads(one.get("judge_set_json")),
            "calibration": _loads(one.get("calibration_json")),
            "judge_validity_factor": one.get("judge_validity_factor"),
            "schema_version": None,
            "payload": None,
        }
        for one in rows_where(
            handle, "capability_evidence", equals={"model_id": row.get("id")},
            order_by="capability_id", descending=False, limit=LIST_CAP,
        )
    ]  # fmt: skip
    return {
        "model": {
            **_identity(row),
            "aliases": _loads(row.get("aliases_json")) or [],
            "resolved_alias": None,
            "latest_descriptor": history[0] if history else None,
            "descriptor_history": history,
        },
        "results": None,
        "next_cursor": None,
        "evidence": evidence,
    }


def benchmarks_api(client: httpx.Client, settings: Settings) -> list[dict[str, Any]]:
    """``GET /benchmarks``: the suites the run engine can execute — what *Start* may name.

    Raises:
        AppRefused: FreeWeight refused.
        AppUnreachable: It did not answer.
    """
    return _listed(call(client, settings, APP, "GET", "benchmarks", timeout_seconds=30.0), "items")


# --- Runs -----------------------------------------------------------------------------------------


def runs_api(
    client: httpx.Client,
    settings: Settings,
    filters: Mapping[str, str | None],
    cursor: str | None,
    page_rows: int,
) -> dict[str, Any]:
    """``GET /runs``: one page, newest first, filtered as api.md §4 allows.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        AppRefused: A refused filter (``MODEL_NOT_FOUND``, a malformed instant, a forged cursor).
        AppUnreachable: It did not answer.
    """
    params = {key: filters.get(key) or None for key in RUN_FILTERS}
    body = call(
        client, settings, APP, "GET", "runs",
        params={**params, "cursor": cursor, "limit": page_rows}, timeout_seconds=30.0,
    )  # fmt: skip
    page = _document(_document(body).get("page"))
    return {
        "items": _listed(body, "runs"),
        "next_cursor": page.get("next_cursor"),
        "next_page": None,
    }


def _run_row(row: Mapping[str, Any], names: Mapping[str, Mapping[Any, Any]]) -> dict[str, Any]:
    """A ``runs`` row under ``GET /runs``' names."""
    key, version = names["suites"].get(row.get("suite_id"), (None, None))
    return {
        "id": row.get("id"),
        "status": row.get("status"),
        "suite": {"key": key, "version": version},
        "model": names["models"].get(row.get("model_id")),
        "label": row.get("label"),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "reproducibility_fingerprint": row.get("reproducibility_fingerprint"),
        "error": (
            {"code": row.get("error_code"), "message": row.get("error_text")}
            if row.get("error_code")
            else None
        ),
        "machine_fingerprint": names["machines"].get(row.get("machine_id")),
        "runtime_profile_hash": names["profiles"].get(row.get("runtime_profile_id")),
        "adapter": names["adapters"].get(row.get("adapter_id")),
    }


def runs_db(
    handle: AppDatabase, filters: Mapping[str, str | None], page: int, page_rows: int
) -> dict[str, Any]:
    """The ``runs`` table, newest first, one numbered page.

    ``status`` and ``label`` filter in the query; ``model`` (by canonical ID), ``suite``,
    ``machine`` and ``adapter`` filter the rows read; ``since`` and ``until`` apply only while
    FreeWeight answers, since the stored timestamp's text is not RFC 3339 and is never parsed here.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    page = max(1, page)
    names = _names(handle)
    rows = rows_where(
        handle, "runs", equals={"status": filters.get("status"), "label": filters.get("label")},
        order_by="created_at", limit=LIST_CAP,
    )  # fmt: skip
    wanted = {key: filters.get(key) for key in ("model", "suite", "machine", "adapter")}
    runs = []
    for run in (_run_row(row, names) for row in rows):
        found = {
            "model": run["model"],
            "suite": run["suite"]["key"],
            "machine": run["machine_fingerprint"],
            "adapter": run["adapter"],
        }
        if all(not value or found[key] == value for key, value in wanted.items()):
            runs.append(run)
    start = (page - 1) * page_rows
    return {
        "items": runs[start : start + page_rows],
        "next_cursor": None,
        "next_page": page + 1 if len(runs) > start + page_rows else None,
    }


def _chart(key: str, label: str, unit: str, values: Sequence[Any]) -> dict[str, Any] | None:
    """One series as an inline SVG polyline in a 100 × 100 box, axis from zero.

    FreeWeight's own run page draws it this way: a reading nobody could take is left out of the
    line rather than drawn as zero, and a series with no reading at all is no chart.
    """
    numbers = [value for value in values if isinstance(value, (int, float))]
    if not numbers:
        return None
    top = max(numbers)
    span = top if top > 0 else 1.0
    step = 100.0 / (len(values) - 1) if len(values) > 1 else 0.0
    points = " ".join(
        f"{index * step:.2f},{100.0 - (value / span) * 100.0:.2f}"
        for index, value in enumerate(values)
        if isinstance(value, (int, float))
    )
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "points": points,
        "minimum": min(numbers),
        "maximum": top,
        "mean": sum(numbers) / len(numbers),
        "reported": len(numbers),
        "missing": len(values) - len(numbers),
    }


def charts(telemetry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``GET /runs/{id}/telemetry`` as the run page's charts: host first, then per device.

    Per device, never combined: there is no machine-wide GPU figure (ADR-0027 §5).
    """
    series: list[tuple[str, str, str, Sequence[Any]]] = [
        ("cpu", "Host CPU utilization (%)", "%", telemetry.get("cpu_percent") or []),
        ("ram", "Host RAM used (bytes)", "bytes", telemetry.get("ram_used_bytes") or []),
    ]
    for gpu in _listed(telemetry, "gpus"):
        index = gpu.get("gpu_index")
        series += [
            (f"gpu{index}-util", f"GPU {index} utilization (%)", "%",
             gpu.get("utilization_percent") or []),
            (f"gpu{index}-vram", f"GPU {index} VRAM used (bytes)", "bytes",
             gpu.get("vram_used_bytes") or []),
            (f"gpu{index}-power", f"GPU {index} power (W)", "W", gpu.get("power_watts") or []),
            (f"gpu{index}-temp", f"GPU {index} temperature (°C)", "°C",
             gpu.get("temperature_c") or []),
        ]  # fmt: skip
    return [chart for chart in (_chart(*one) for one in series) if chart is not None]


def run_api(client: httpx.Client, settings: Settings, run_id: str) -> dict[str, Any]:
    """``GET /runs/{id}`` and ``GET /runs/{id}/telemetry`` as the page's charts.

    A refused telemetry read leaves ``charts`` ``None``, so the run still renders.

    Raises:
        AppRefused: ``RUN_NOT_FOUND`` or an ambiguous prefix.
        AppUnreachable: It did not answer.
    """
    run = _document(call(client, settings, APP, "GET", f"runs/{segment(run_id)}"))
    full = str(run.get("id") or run_id)
    try:
        telemetry: dict[str, Any] | None = _document(
            call(client, settings, APP, "GET", f"runs/{segment(full)}/telemetry",
                 timeout_seconds=30.0)
        )  # fmt: skip
    except AppRefused:
        telemetry = None
    return {
        "run": run,
        "charts": None if telemetry is None else charts(telemetry),
        "telemetry_samples": None if telemetry is None else telemetry.get("sample_count"),
        "events": None,
    }


def run_db(handle: AppDatabase, run_id: str) -> dict[str, Any]:
    """One run's rows under ``GET /runs/{id}``' names, with its stored events for the timeline.

    Its telemetry charts are ``None``: the series is FreeWeight's reading of its telemetry tables,
    served by its API.

    Raises:
        NotRecorded: Nothing matches ``run_id``, or more than one run does.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    row = _one(handle, "runs", run_id, "run")
    run = _run_row(row, _names(handle))
    mine = {"run_id": row.get("id")}
    definitions = {
        one.get("id"): one
        for one in rows_where(
            handle, "benchmark_tests", equals={"suite_id": row.get("suite_id")}, limit=LIST_CAP
        )
    }
    tests = []
    for one in rows_where(handle, "run_tests", equals=mine, limit=LIST_CAP):
        definition = definitions.get(one.get("test_id")) or {}
        tests.append(
            {
                "id": one.get("id"),
                "key": definition.get("key") or "unknown",
                "name": definition.get("name") or "unknown",
                "status": one.get("status"),
                "skip_reason": one.get("skip_reason"),
                "completed_cases": one.get("completed_cases"),
                "total_cases": one.get("total_cases"),
                "repetitions": one.get("repetitions"),
                "error": (
                    {"code": one.get("error_code"), "message": one.get("error_text")}
                    if one.get("error_code")
                    else None
                ),
            }
        )
    # ponytail: the per-sample metric rows are read and dropped here, capped; a run with more than
    # the cap's metric rows shows only some aggregates when stopped. A `sample_id IS NULL` filter in
    # rows_where would lift it.
    metrics = [
        {
            "metric_key": one.get("metric_key"),
            "run_test_id": one.get("run_test_id"),
            "value": "unsupported" if one.get("unavailable_reason") else one.get("numeric_value"),
            "unavailable_reason": one.get("unavailable_reason"),
            "unit": one.get("unit"),
            "aggregation": one.get("aggregation"),
            "higher_is_better": bool(one.get("higher_is_better")),
            "sample_count": one.get("sample_count"),
            "excluded_count": one.get("excluded_count"),
            "gpu_index": one.get("gpu_index"),
            "stddev": one.get("stddev"),
            "coefficient_of_variation": one.get("coefficient_of_variation"),
        }
        for one in rows_where(
            handle, "metric_values", equals=mine, order_by="metric_key", descending=False,
            limit=LIST_CAP * 4,
        )
        if one.get("sample_id") is None
    ]  # fmt: skip
    events = rows_where(
        handle, "run_events", equals=mine, order_by="sequence", descending=False, limit=LIST_CAP * 2
    )
    run.update(
        {
            "effective_config": _loads(row.get("effective_config_json")),
            "last_event_sequence": events[-1].get("sequence") if events else 0,
            "tests": tests,
            "metrics": metrics,
            "provenance": {
                "served_context": row.get("served_context"),
                "served_context_source": row.get("served_context_source"),
                "gpu_index": row.get("gpu_index"),
                "multi_gpu_visible": bool(row.get("multi_gpu_visible")),
                "telemetry_overhead_percent": row.get("telemetry_overhead_percent"),
                "prompt_pack": {
                    "id": row.get("prompt_pack_id"),
                    "version": row.get("prompt_pack_version"),
                    "hash": row.get("prompt_pack_hash"),
                },
                "fingerprint_document": _loads(row.get("fingerprint_document_json")) or {},
            },
            "degradations": _loads(row.get("degradations_json")) or [],
        }
    )
    return {
        "run": run,
        "charts": None,
        "telemetry_samples": None,
        "events": [
            {
                "sequence": one.get("sequence"),
                "timestamp": one.get("timestamp"),
                "type": one.get("event_type"),
                "message": one.get("message"),
            }
            for one in events
        ],
    }


def run_log_frames(chunks: Iterable[str]) -> Iterator[str]:
    """FreeWeight's ``/runs/{id}/events`` as the console's log-pane frames.

    Each frame keeps **FreeWeight's own sequence** as its SSE ``id``, so a pane whose connection
    drops reconnects with ``Last-Event-ID``, the proxy carries it through, and FreeWeight replays
    from there: no event is shown twice or lost. The pane closes with ``log.closed`` on the terminal
    event, on the console's own ``error`` frame, or when FreeWeight closes the stream.

    Args:
        chunks: :func:`~weightroom.services.app_api.stream`'s text.

    Yields:
        SSE frames, ``log`` then one ``log.closed``.
    """
    sequence = 0

    def frame(kind: str, payload: dict[str, Any]) -> str:
        return format_frame(
            Event(sequence=sequence, type=kind, payload=payload), generator=_GENERATOR
        )

    for one in iter_frames(lines(chunks)):
        if one.event == "stream.closed":
            break
        envelope = _document(one.data)
        payload = _document(envelope.get("payload"))
        if one.event == "error":
            message = f"{payload.get('code')}: {payload.get('message')}"
            yield frame("log", {"at": envelope.get("generated_at"), "app": "error", "level": "err",
                                "message": message})  # fmt: skip
            break
        if isinstance(payload.get("sequence"), int):
            sequence = int(payload["sequence"])
        progress = _document(payload.get("progress"))
        message = str(payload.get("message") or "")
        if progress:
            message = f"{message} ({progress.get('completed')}/{progress.get('total')})".strip()
        level = (
            "err" if one.event in _ERROR_EVENTS
            else "warning" if one.event in _WARNING_EVENTS
            else "info"
        )  # fmt: skip
        yield frame(
            "log",
            {"at": payload.get("timestamp"), "app": one.event, "level": level, "message": message},
        )
        if one.event in TERMINAL_RUN_EVENTS:
            break
    yield frame("log.closed", {"reason": "the run's stream ended"})


# --- Samples --------------------------------------------------------------------------------------


def _test_of(run: Mapping[str, Any], run_test_id: str) -> dict[str, Any] | None:
    return next((one for one in _listed(run, "tests") if one.get("id") == run_test_id), None)


def samples_api(
    client: httpx.Client,
    settings: Settings,
    run_id: str,
    run_test_id: str,
    cursor: str | None,
    page_rows: int,
) -> dict[str, Any]:
    """The run, its test, and one page of ``GET /runs/{id}/tests/{test}/samples``.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        AppRefused: ``RUN_NOT_FOUND`` for a run or a test that is not the run's, or a forged cursor.
        AppUnreachable: It did not answer.
    """
    run = _document(call(client, settings, APP, "GET", f"runs/{segment(run_id)}"))
    body = _document(
        call(
            client, settings, APP, "GET",
            f"runs/{segment(run_id)}/tests/{segment(run_test_id)}/samples",
            params={"limit": page_rows, "cursor": cursor}, timeout_seconds=30.0,
        )
    )  # fmt: skip
    page = _document(body.get("page"))
    return {
        "run": run,
        "test": _test_of(run, run_test_id),
        "items": _listed(body, "samples"),
        "next_cursor": page.get("next_cursor"),
        "next_page": None,
    }


def _sample_row(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "case_id", "ordinal", "repetition", "status", "score", "score_method",
        "response_hash", "response_text", "output_chars", "input_tokens", "output_tokens",
        "client_wall_ms", "finish_reason", "prompt_id", "prompt_version", "client_ttft_ms",
    )  # fmt: skip
    return {
        **{key: row.get(key) for key in keys},
        "error": (
            {"code": row.get("error_code"), "message": row.get("error_text")}
            if row.get("error_code")
            else None
        ),
        "detail": _loads(row.get("result_json")) or {},
    }


def samples_db(
    handle: AppDatabase, run_id: str, run_test_id: str, page: int, page_rows: int
) -> dict[str, Any]:
    """The run, its test, and one numbered page of the test's samples in declaration order.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        NotRecorded: No such run, or the test is not one of its tests.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    page = max(1, page)
    run = run_db(handle, run_id)["run"]
    test = _test_of(run, run_test_id)
    if test is None:
        raise NotRecorded(
            f"Run {run.get('id')!r} has no test {run_test_id!r}.",
            details={"run": run.get("id"), "run_test": run_test_id},
        )
    rows = sorted(
        rows_where(handle, "samples", equals={"run_test_id": run_test_id}, limit=LIST_CAP * 4),
        key=lambda one: (one.get("ordinal") or 0, one.get("repetition") or 0, str(one.get("id"))),
    )
    start = (page - 1) * page_rows
    return {
        "run": run,
        "test": test,
        "items": [_sample_row(one) for one in rows[start : start + page_rows]],
        "next_cursor": None,
        "next_page": page + 1 if len(rows) > start + page_rows else None,
    }


def sample_api(client: httpx.Client, settings: Settings, sample_id: str) -> dict[str, Any]:
    """``GET /samples/{id}``: the case inspector's document.

    Raises:
        AppRefused: ``NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(client, settings, APP, "GET", f"samples/{segment(sample_id)}", timeout_seconds=30.0)
    )


def sample_db(handle: AppDatabase, sample_id: str) -> dict[str, Any]:
    """One sample, its tool calls, criterion scores and juror verdicts, from the database.

    The telemetry inside the sample's window is FreeWeight's reconstruction (``None`` here).

    Raises:
        NotRecorded: No such sample.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(handle, "samples", equals={"id": sample_id}, limit=1) if sample_id else []
    if not found:
        raise NotRecorded(
            f"FreeWeight's database holds no sample {sample_id!r}.", details={"sample": sample_id}
        )
    row = found[0]

    def first(table_name: str, row_id: Any) -> dict[str, Any]:  # noqa: ANN401 — a stored id
        found = rows_where(handle, table_name, equals={"id": row_id}, limit=1) if row_id else []
        return found[0] if found else {}

    run_test = first("run_tests", row.get("run_test_id"))
    definition = first("benchmark_tests", run_test.get("test_id"))
    run = first("runs", run_test.get("run_id"))
    scores = []
    for score in rows_where(
        handle, "criterion_scores", equals={"sample_id": row.get("id")}, order_by="criterion_key",
        descending=False, limit=LIST_CAP,
    ):  # fmt: skip
        verdicts = rows_where(
            handle, "judge_verdicts", equals={"criterion_score_id": score.get("id")},
            order_by="juror_ordinal", descending=False, limit=LIST_CAP,
        )  # fmt: skip
        scores.append(
            {
                **{key: score.get(key) for key in ("criterion_key", "rung", "raw_score", "weight",
                                                    "status", "skip_reason")},
                "gated": bool(score.get("gated")),
                "verdicts": [
                    {
                        **{key: one.get(key) for key in ("juror_canonical_id", "repetition",
                                                          "grade", "pairwise_choice", "rationale",
                                                          "refused_reason")},
                        "remote": bool(one.get("remote")),
                    }
                    for one in verdicts
                ],
            }
        )  # fmt: skip
    sample_keys = (
        "id", "case_id", "ordinal", "repetition", "status", "created_at", "started_at",
        "finish_reason", "prompt_id", "prompt_version", "prompt_hash", "rendered_prompt_hash",
        "response_hash", "response_text", "score", "score_method", "input_tokens",
        "output_tokens", "thinking_tokens", "output_chars", "client_wall_ms", "client_ttft_ms",
    )  # fmt: skip
    return {
        "sample": {
            **{key: row.get(key) for key in sample_keys},
            "error": (
                {"code": row.get("error_code"), "message": row.get("error_text")}
                if row.get("error_code")
                else None
            ),
            "result": _loads(row.get("result_json")),
        },
        "run_id": run.get("id"),
        "run_status": run.get("status"),
        "run_test_id": row.get("run_test_id"),
        "run_test_key": definition.get("key"),
        "tool_calls": [
            {
                **{key: one.get(key) for key in ("turn_index", "call_index", "tool_name",
                                                  "expected_tool", "correct_tool",
                                                  "correct_arguments", "status", "latency_ms")},
                "schema_valid": bool(one.get("schema_valid")),
                "arguments": _loads(one.get("arguments_json")),
            }
            for one in rows_where(
                handle, "tool_calls", equals={"sample_id": row.get("id")}, order_by="turn_index",
                descending=False, limit=LIST_CAP,
            )
        ],
        "criterion_scores": scores,
        "telemetry": None,
    }  # fmt: skip


# --- Results, compare, export ---------------------------------------------------------------------

RESULT_FILTERS: Final[tuple[str, ...]] = (
    "model",
    "suite",
    "metric_key",
    "machine",
    "runtime_profile",
    "adapter",
    "since",
    "until",
    "status",
)
"""``GET /results``' filters under FreeWeight's own names (api.md §5)."""
EXPORT_SCOPES: Final[tuple[str, ...]] = ("all", "run", "model", "suite", "comparison")
EXPORT_FORMATS: Final[tuple[str, ...]] = ("json", "jsonl", "csv")
EVIDENCE_FILTERS: Final[tuple[str, ...]] = (
    "capability",
    "model",
    "machine",
    "runtime_profile",
    "min_confidence",
)
"""``GET /evidence``' filters (api.md §6); the bundle takes these and ``since``."""

DASHBOARD_FILTERS: Final[tuple[str, ...]] = ("suite", "model", "machine", "since")
"""``GET /dashboard``'s filters (api.md §5a) — the same four the HTML page's filter bar takes."""


def results_api(
    client: httpx.Client,
    settings: Settings,
    filters: Mapping[str, str | None],
    cursor: str | None,
    page_rows: int,
) -> dict[str, Any]:
    """``GET /results``: one page of stored metrics, newest run first.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        AppRefused: A refused filter — ``MODEL_NOT_FOUND``, a malformed instant, a forged cursor.
        AppUnreachable: It did not answer.
    """
    params = {key: filters.get(key) or None for key in RESULT_FILTERS}
    body = call(
        client, settings, APP, "GET", "results",
        params={**params, "cursor": cursor, "limit": page_rows}, timeout_seconds=30.0,
    )  # fmt: skip
    page = _document(_document(body).get("page"))
    return {"items": _listed(body, "items"), "next_cursor": page.get("next_cursor")}


def context_fit_api(client: httpx.Client, settings: Settings) -> dict[str, dict[str, Any]]:
    """``GET /results/context-fit``: the largest context each model was *measured* to fit.

    FreeWeight's ``memory_kv`` benchmark is the only place in the suite that measures this, and
    row WX7 added the endpoint that carries it out of FreeWeight. One row per (model, runtime
    profile, machine): a single number per model would be a lie, because the answer moves with
    the runtime profile it was measured under and with the card it was measured on.

    Read by LoadCoach's Models page, which is a **cross-application** read the console makes on
    the operator's behalf — LoadCoach never learns this and never should (no application reads
    another's database, and this is not routing's business).

    Returns:
        ``canonical_id`` → the newest row for it, carrying ``max_successful_context_tokens``,
        ``capped_by_configuration``, ``observed_mb_per_1k_context``, ``runtime_profile_hash``
        and ``machine_fingerprint``. A model FreeWeight has never measured is simply absent, and
        the caller renders ``—`` for it rather than a number nobody measured (ADR-0016).

    Raises:
        AppRefused: FreeWeight refused — including the ``404`` of a FreeWeight older than WX7.
        AppUnreachable: It did not answer.
    """
    body = call(client, settings, APP, "GET", "results/context-fit", timeout_seconds=30.0)
    found: dict[str, dict[str, Any]] = {}
    for row in _listed(body, "items"):
        canonical = str(row.get("canonical_id") or "")
        if canonical:
            found.setdefault(canonical, dict(row))
    return found


def compare_api(
    client: httpx.Client, settings: Settings, subjects: str, suite: str | None
) -> dict[str, Any]:
    """``GET /results/compare``: aligned metrics with every comparability verdict and separation.

    Raises:
        AppRefused: ``COMPARISON_REFUSED`` (a subject outside the suite, a run named twice, fewer
            than two), ``COMPARISON_SUBJECT_NOT_FOUND`` or ``VALIDATION_ERROR``, each with its
            reason in FreeWeight's words.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(
            client, settings, APP, "GET", "results/compare",
            params={"subjects": subjects, "suite": suite}, timeout_seconds=60.0,
        )
    )  # fmt: skip


def compare_bar_options(
    comparison: Mapping[str, Any], chosen: Sequence[str]
) -> list[dict[str, Any]]:
    """One horizontal-bar ECharts option per chosen metric of a comparison (row WX7, ADR-0142).

    **A separated metric is never charted.** FreeWeight marks a metric row ``mergeable: false``
    when its cells sit in groups that must not be read against each other, and a bar chart is
    exactly the reading it refuses — bars in one axis *are* a comparison. Those metrics are left
    out here and the page says why beside the table, which keeps every cell and its group.

    A cell with no value is left out of the series rather than plotted at zero (ADR-0016).

    Args:
        comparison: ``GET /results/compare``'s body.
        chosen: The metric keys the reader ticked. Anything not in the comparison is ignored.

    Returns:
        ``[{"metric_key", "unit", "higher_is_better", "option"}, …]`` in the comparison's own
        metric order, with ``option`` an ECharts dict carrying no colour — ``charts.js`` themes it
        at draw time. Empty when nothing chosen is chartable.
    """
    labels = {
        str(one.get("run_id")): str(one.get("label") or (one.get("run_id") or "")[:8])
        for one in comparison.get("subjects") or []
    }
    wanted = set(chosen)
    charts: list[dict[str, Any]] = []
    for row in comparison.get("metrics") or []:
        key = str(row.get("metric_key") or "")
        if key not in wanted or not row.get("mergeable"):
            continue
        points = [
            (labels.get(str(cell.get("run_id")), "—"), cell.get("value"))
            for cell in row.get("cells") or []
            if isinstance(cell.get("value"), int | float)
            and not isinstance(cell.get("value"), bool)
        ]
        if not points:
            continue
        charts.append(
            {
                "metric_key": key,
                "unit": row.get("unit") or "",
                "higher_is_better": bool(row.get("higher_is_better")),
                "option": {
                    # Categories run bottom-to-top on a horizontal bar, so the order is reversed
                    # to put the comparison's first subject at the top where a reader starts.
                    "xAxis": {"type": "value", "name": row.get("unit") or ""},
                    "yAxis": {"type": "category", "data": [name for name, _ in reversed(points)]},
                    "series": [
                        {
                            "name": key,
                            "type": "bar",
                            "data": [value for _, value in reversed(points)],
                        }
                    ],
                },
            }
        )
    return charts


def _row_labels(models: Sequence[str]) -> list[str]:
    """Each model's provider-side name (``smollm2:135m`` out of ``ollama/smollm2:135m@sha256:…``),
    or every canonical ID the moment two models would share one label."""
    short = [model.rsplit("/", 1)[-1].split("@", 1)[0] for model in models]
    return short if len(set(short)) == len(models) else list(models)


def _number(value: Any) -> float | None:  # noqa: ANN401 — a JSON value
    """A JSON number as a float; ``"unsupported"``, ``null`` or a boolean is ``None``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def score_heatmap_option(dashboard: Mapping[str, Any]) -> dict[str, Any] | None:
    """``GET /dashboard``'s tests matrix as an ECharts heatmap of mean sample scores, or ``None``.

    Models down, tests across, each square a cell's ``mean_score`` on one ``0``–``1`` scale: a
    failed sample counts ``0`` and a skipped one is left out (FreeWeight's rule, api.md §5a). A cell
    with no scorable sample, or a test the model never ran, is left out of the series rather than
    drawn at zero (ADR-0016). The option carries no colour: ``charts.js`` themes it (ADR-0142).

    Args:
        dashboard: ``GET /dashboard``'s body.

    Returns:
        The option, or ``None`` when no cell has a score — a FreeWeight older than ``mean_score``
        included.
    """
    matrix = dashboard.get("tests_matrix") or {}
    models = [str(one) for one in matrix.get("models") or []]
    tests = [str(one) for one in matrix.get("tests") or []]
    points: list[dict[str, Any]] = []
    for cell in matrix.get("cells") or []:
        score = _number(cell.get("mean_score"))
        model, test = str(cell.get("model")), str(cell.get("test"))
        if score is None or model not in models or test not in tests:
            continue
        points.append(
            {
                "value": [tests.index(test), models.index(model), round(score, 4)],
                "name": f"{model} · {test} · {score:.2f}",
            }
        )
    if not points:
        return None
    return {
        "tooltip": {"formatter": "{b}"},
        "grid": {"containLabel": True, "left": 8, "right": 8, "top": 8, "bottom": 56},
        # No split-area shading: an alternating background paints an unmeasured square as
        # convincingly as a measured one.
        "xAxis": {"type": "category", "data": tests, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "category", "data": _row_labels(models)},
        "visualMap": {
            "min": 0,
            "max": 1,
            "calculable": False,
            "orient": "horizontal",
            "left": "center",
            "bottom": 0,
            "text": ["1 — every sample scored", "0"],
        },
        "series": [{"type": "heatmap", "data": points, "label": {"show": False}}],
    }


def bar_charts_by_test(dashboard: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One bar chart per test from ``GET /dashboard``'s ``test_metrics``: every model in scope along
    the axis, one series per metric.

    Only a test's first metric starts shown — its metrics are in different units (``ms`` beside
    ``tokens/s``) and the page's checkboxes add the others. A metric a model has no number for is
    no bar, never a zero bar (ADR-0016).

    Args:
        dashboard: ``GET /dashboard``'s body.

    Returns:
        ``{"test", "metrics": [{"key", "unit"}], "option", "head", "rows"}`` per test, in test
        order — ``head`` and ``rows`` are the chart's table alternative. Empty for a FreeWeight
        older than ``test_metrics``.
    """
    models = [str(one) for one in (dashboard.get("tests_matrix") or {}).get("models") or []]
    values: dict[str, dict[str, dict[str, float | None]]] = {}
    units: dict[tuple[str, str], str] = {}
    for row in dashboard.get("test_metrics") or []:
        test, metric = str(row.get("test")), str(row.get("metric_key"))
        model = str(row.get("model"))
        if model not in models:
            models.append(model)
        values.setdefault(test, {}).setdefault(metric, {}).setdefault(
            model, _number(row.get("value"))
        )
        units.setdefault((test, metric), str(row.get("unit") or ""))
    labels = _row_labels(models)
    charts: list[dict[str, Any]] = []
    for test, by_metric in sorted(values.items()):
        metrics = sorted(by_metric)
        named = [f"{m} ({units[(test, m)]})" if units[(test, m)] else m for m in metrics]
        charts.append(
            {
                "test": test,
                "metrics": [{"key": m, "unit": units[(test, m)]} for m in metrics],
                "option": {
                    "tooltip": {"trigger": "axis"},
                    "legend": {
                        "show": False,
                        "selected": {m: index == 0 for index, m in enumerate(metrics)},
                    },
                    "grid": {"containLabel": True, "left": 8, "right": 8, "top": 16, "bottom": 8},
                    "xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 30}},
                    "yAxis": {"type": "value"},
                    "series": [
                        {
                            "name": m,
                            "type": "bar",
                            "data": [by_metric[m].get(model) for model in models],
                        }
                        for m in metrics
                    ],
                },
                "head": [
                    {"label": "Model", "mono": True},
                    *({"label": name, "numeric": True} for name in named),
                ],
                "rows": [
                    [label, *(_shown(by_metric[m].get(model)) for m in metrics)]
                    for model, label in zip(models, labels, strict=True)
                ],
            }
        )
    return charts


def _shown(value: float | None) -> str:
    """A bar's figure for the table beside the chart: ``—`` for no number, never ``0``."""
    return "—" if value is None else f"{value:.4g}"


def export_params(form: Mapping[str, str]) -> dict[str, str]:
    """``GET /results/export``'s query from the page's form; FreeWeight validates every value.

    A ticked box is ``true`` and an unticked one is left out, so FreeWeight's own default applies;
    a blank field is left out for the same reason.
    """
    params = {key: form.get(key) or "" for key in ("format", "scope", "selector", "since", "until")}
    for flag in ("include_samples", "include_prompts", "include_prompt_text"):
        params[flag] = "true" if form.get(flag) == "true" else ""
    return {key: value for key, value in params.items() if value}


# --- Evidence -------------------------------------------------------------------------------------


def evidence_api(
    client: httpx.Client,
    settings: Settings,
    filters: Mapping[str, str | None],
    cursor: str | None,
    page_rows: int,
) -> dict[str, Any]:
    """``GET /evidence``: one page of current records, each lifted by :func:`evidence_record`.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        AppRefused: A refused filter (``MODEL_NOT_FOUND``, a minimum confidence out of range).
        AppUnreachable: It did not answer.
    """
    params = {key: filters.get(key) or None for key in EVIDENCE_FILTERS}
    body = call(
        client, settings, APP, "GET", "evidence",
        params={**params, "cursor": cursor, "limit": page_rows}, timeout_seconds=30.0,
    )  # fmt: skip
    page = _document(_document(body).get("page"))
    items = [evidence_record(item) for item in _listed(body, "items")]
    # FreeWeight's reading of each record at this instant — staleness and the confidence factors —
    # travels beside the envelopes, one per item in the same order (api.md §6, row WP4).
    for item, explained in zip(items, _listed(body, "explanations"), strict=False):
        item["explanation"] = explained
    return {"items": items, "next_cursor": page.get("next_cursor")}


# --- Machines -------------------------------------------------------------------------------------


def _machine_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``machines`` row under ``GET /machines``' names; which one is this host is FreeWeight's."""
    keys = (
        "id", "machine_fingerprint", "hostname", "os_name", "os_version", "cpu_model",
        "logical_cores", "ram_bytes", "first_seen_at", "last_seen_at",
    )  # fmt: skip
    return {**{key: row.get(key) for key in keys}, "is_current": None}


def machines_api(client: httpx.Client, settings: Settings) -> list[dict[str, Any]]:
    """``GET /machines``: every machine measured on, the current one flagged.

    Raises:
        AppRefused: FreeWeight refused.
        AppUnreachable: It did not answer.
    """
    return _listed(call(client, settings, APP, "GET", "machines", timeout_seconds=30.0), "items")


def machines_db(handle: AppDatabase) -> list[dict[str, Any]]:
    """The ``machines`` table, oldest sighting first, as FreeWeight lists it.

    Raises:
        TableUnknown: The database has no ``machines`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    rows = rows_where(
        handle, "machines", order_by="first_seen_at", descending=False, limit=LIST_CAP
    )
    return [_machine_row(row) for row in rows]


def machine_api(client: httpx.Client, settings: Settings, machine_id: str) -> dict[str, Any]:
    """``GET /machines/{id}``.

    Raises:
        AppRefused: ``NOT_FOUND``, or an ambiguous prefix.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", f"machines/{segment(machine_id)}"))


def machine_db(handle: AppDatabase, machine_id: str) -> dict[str, Any]:
    """One machine by ULID or prefix.

    Raises:
        NotRecorded: Nothing matches, or more than one machine does.
        TableUnknown: The database has no ``machines`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    return _machine_row(_one(handle, "machines", machine_id, "machine"))


# --- Adapters, provider, database -----------------------------------------------------------------


def adapters_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /adapters``: the directory's reading beside the ``adapters`` table (api.md §2a).

    Raises:
        AppRefused: FreeWeight refused, or is older than the route (``HTTP_404``).
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", "adapters", timeout_seconds=30.0))


def adapters_db(handle: AppDatabase) -> dict[str, Any]:
    """FreeWeight's ``adapters`` table, each row with the runs created under it.

    The directory is read only by the running FreeWeight, so availability, the manifests it could
    not read and the drafts are ``None`` here, and so is each adapter's per-base scores, which are
    FreeWeight's join over its evidence.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    # ponytail: the newest LIST_CAP runs are read for the counts; a longer history undercounts
    # when stopped. A per-adapter count in the query would lift it.
    runs = rows_where(handle, "runs", order_by="created_at", limit=LIST_CAP)
    adapters = []
    for row in rows_where(handle, "adapters", order_by="name", descending=False, limit=LIST_CAP):
        mine = [one for one in runs if one.get("adapter_id") == row.get("id")]
        declared = _loads(row.get("declared_capabilities_json"))
        keys = (
            "name", "artifact_sha256", "artifact_path", "source_sha256", "base_model_name",
            "base_artifact_digest", "base_confidence", "data_classification", "notes",
        )  # fmt: skip
        adapters.append(
            {
                **{key: row.get(key) for key in keys},
                "declared_capabilities": declared if isinstance(declared, list) else [],
                "manifest_path": None,
                "available": None,
                "unavailable_reason": None,
                "in_directory": None,
                "measured": True,
                "run_count": len(mine),
                "last_run_at": mine[0].get("created_at") if mine else None,
                "subjects": None,
            }
        )
    return {
        "enabled": None,
        "directory": None,
        "note": None,
        "adapters": adapters,
        "invalid": [],
        "drafts": [],
        "unmanifested": [],
    }


def _named(catalog: Mapping[str, Any], adapter: str) -> list[dict[str, Any]]:
    """The adapters ``adapter`` names — by name or by artifact digest.

    Raises:
        NotRecorded: None does.
    """
    found = [
        one
        for one in _listed(catalog, "adapters")
        if adapter in (one.get("name"), one.get("artifact_sha256"))
    ]
    if not found:
        raise NotRecorded(f"FreeWeight knows no adapter {adapter!r}.", details={"adapter": adapter})
    return found


def adapter_api(
    client: httpx.Client, settings: Settings, adapter: str, *, page_rows: int
) -> dict[str, Any]:
    """One adapter from ``GET /adapters``, with ``GET /runs`` and ``GET /results`` under it.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        NotRecorded: FreeWeight knows no adapter by that name or digest.
        AppRefused: FreeWeight refused.
        AppUnreachable: It did not answer.
    """
    found = _named(adapters_api(client, settings), adapter)
    runs = runs_api(client, settings, {"adapter": adapter}, None, page_rows)
    results = results_api(client, settings, {"adapter": adapter, "status": "any"}, None, page_rows)
    return {"adapters": found, "runs": runs["items"], "results": results["items"]}


def adapter_db(handle: AppDatabase, adapter: str, *, page_rows: int) -> dict[str, Any]:
    """One adapter's row and the runs created under it; its results are FreeWeight's query.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        NotRecorded: The table holds no adapter by that name or digest.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = _named(adapters_db(handle), adapter)
    names = {str(one.get("name")) for one in found}
    runs = [
        run for run in runs_db(handle, {}, 1, page_rows)["items"] if run.get("adapter") in names
    ]
    return {"adapters": found, "runs": runs, "results": None}


def provider_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /provider``: the ``[provider]`` block, its file, the file's digest, what shadows it.

    The block lives in FreeWeight's configuration file, not its database, so a stopped FreeWeight's
    page says it reads only from the running API.

    Raises:
        AppRefused: FreeWeight refused.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", "provider"))


def database_stats_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /database/stats``: what ``db status`` also says, and its backups and artifacts.

    Raises:
        AppRefused: FreeWeight refused.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", "database/stats", timeout_seconds=30.0))


# --- Dashboard and System (row WPF5) ---------------------------------------------------------


def dashboard_api(
    client: httpx.Client, settings: Settings, filters: Mapping[str, str | None]
) -> dict[str, Any]:
    """``GET /dashboard`` (api.md §5a): the summary cards and the comparison heatmap.

    The cross-model view Results and Compare do not offer (WP6's finding): Results is a
    metric-level query and Compare works per subject. FreeWeight's own *separated* marking travels
    on the heatmap, so this page never recomputes comparability.

    Raises:
        AppRefused: A refused filter (``MODEL_NOT_FOUND``, a malformed ``since``).
        AppUnreachable: It did not answer.
    """
    params = {key: filters.get(key) or None for key in DASHBOARD_FILTERS}
    return _document(
        call(client, settings, APP, "GET", "dashboard", params=params, timeout_seconds=30.0)
    )


def system_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /health`` (row WPF5): version, overall status and FreeWeight's ten health components.

    ``/health`` answers ``503`` when a component is unavailable; the console's client reads any
    status of 400 or above as a refusal, so that case renders as the page's refusal rather than a
    component table with nothing in it.

    Raises:
        AppRefused: FreeWeight answered 503 or otherwise refused.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", "health"))
