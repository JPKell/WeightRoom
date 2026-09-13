"""weightroom.services.catalog — every model FreeWeight and LoadCoach know, joined by identity.

The console's Catalog page is gone (ADR-0146); what stays here is what a remaining path calls.
:func:`set_enabled` is ADR-0118's switch on the LoadCoach and FreeWeight tabs, and it still audits
as ``catalog.enabled``. :func:`catalog_entries` is the join ``model_refresh`` reports after each
refresh.

Only these two applications own a ``models`` table at all (ADR-0008, ADR-0118), so the join is
over two databases, read on the read-only engine ``services/db_reader.py`` opens for each.
Evidence freshness is always FreeWeight's answer; residency comes first from LoadCoach's own
``residency`` table and, for an Ollama-kind row LoadCoach does not carry, from ModelRack's
``/api/ps`` client (``services/ollama.resident_models``).

**A slow call is not a refusal** (row WPF11): ``set_enabled`` raises
:class:`~weightroom.services.app_api.AppTimedOut` on a timeout and :class:`CatalogRefused` for
anything the far side actually answered no to; callers audit with ``app_api.outcome_of``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Final

import httpx
from baseaicore import SuiteError
from sqlalchemy import func, select

from weightroom.services.app_api import AppTimedOut
from weightroom.services.apps import bearer_token
from weightroom.services.db_reader import AppDatabaseUnavailable, open_app_database, reflect_table
from weightroom.services.ollama import resident_models

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sqlalchemy import Engine

    from weightroom.config import Settings
    from weightroom.services.database import Database
    from weightroom.services.db_reader import DatabaseUrlCache

__all__ = [
    "CATALOG_APPS",
    "CatalogAppRow",
    "CatalogEntry",
    "CatalogRefused",
    "catalog_entries",
    "set_enabled",
]

CATALOG_APPS: Final[tuple[str, ...]] = ("freeweight", "loadcoach")
_HTTP_TIMEOUT_SECONDS: Final = 10.0


class CatalogRefused(SuiteError):
    """An application answered an enable or disable with an error, or did not answer at all."""

    code: ClassVar[str] = "VALIDATION_ERROR"


# --- The join -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogAppRow:
    """One application's own row for a model the catalog has joined by canonical identity.

    Attributes:
        model_id: The application's own primary key — what ``POST /models/{model_id}/enabled``
            on that application takes, never the canonical id (ADR-0024).
        provider_kind: This application's own record of it (identical across apps by construction
            of the join key, kept per-row rather than assumed).
        provider_model_name: Ditto — the ``ollama pull`` name, or the GGUF file's name for
            ``llamacpp``.
        enabled: ADR-0118's flag, this application's own.
        available: The provider's own last-seen reachability, where the application tracks it
            (LoadCoach only — FreeWeight benchmarks on demand and keeps no such fact).
        size_bytes: The weights' size, where known.
        max_context: The trained context length, where known.
        resident: Whether this application currently holds the model loaded, or ``None`` when
            this build has no way to know (ADR-0016 — never a guessed ``False``).
        evidence_measured_at: The newest ``capability_evidence.measured_at`` FreeWeight holds for
            this model, or ``None`` for a model never benchmarked.
    """

    model_id: str
    provider_kind: str
    provider_model_name: str
    enabled: bool
    available: bool | None
    size_bytes: int | None
    max_context: int | None
    resident: bool | None
    evidence_measured_at: datetime | None


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One model, joined across every application that knows it.

    Attributes:
        canonical_id: The join key (ADR-0008).
        provider_kind: ``ollama``, ``llamacpp``, ``openai_compatible``, … — from whichever
            application's row supplied the identity first.
        provider_model_name: Ditto.
        family: The model family, when a descriptor states one.
        quantization: Ditto.
        apps: Every application that has a row for this model, keyed by name.
    """

    canonical_id: str
    provider_kind: str
    provider_model_name: str
    family: str | None
    quantization: str | None
    apps: Mapping[str, CatalogAppRow]


def _freeweight_rows(
    engine: Engine,
) -> list[tuple[str, str | None, str | None, CatalogAppRow]]:
    """FreeWeight's own models, their latest descriptor and their evidence freshness."""
    models = reflect_table(engine, "models")
    if models is None:
        return []
    descriptors = reflect_table(engine, "model_descriptors")
    evidence = reflect_table(engine, "capability_evidence")
    latest: dict[str, tuple[int | None, int | None, str | None, str | None]] = {}
    if descriptors is not None:
        with engine.connect() as connection:
            statement = select(
                descriptors.c.model_id,
                descriptors.c.size_bytes,
                descriptors.c.max_context,
                descriptors.c.family,
                descriptors.c.quantization,
            ).order_by(descriptors.c.model_id, descriptors.c.observed_at.desc())
            for row in connection.execute(statement):
                # The first row seen per model_id is the newest (the ORDER BY above); a later one
                # for the same model is older and never overwrites it.
                latest.setdefault(
                    row.model_id, (row.size_bytes, row.max_context, row.family, row.quantization)
                )
    freshness: dict[str, datetime] = {}
    if evidence is not None:
        with engine.connect() as connection:
            statement = (
                select(evidence.c.model_id, func.max(evidence.c.measured_at).label("measured_at"))
                .where(evidence.c.model_id.is_not(None))
                .group_by(evidence.c.model_id)
            )
            freshness = {row.model_id: row.measured_at for row in connection.execute(statement)}
    out: list[tuple[str, str | None, str | None, CatalogAppRow]] = []
    with engine.connect() as connection:
        for row in connection.execute(select(models)):
            size_bytes, max_context, family, quantization = latest.get(
                row.id, (None, None, None, None)
            )
            out.append(
                (
                    row.canonical_id,
                    family,
                    quantization,
                    CatalogAppRow(
                        model_id=row.id,
                        provider_kind=row.provider_kind,
                        provider_model_name=row.provider_model_name,
                        enabled=row.enabled,
                        available=None,
                        size_bytes=size_bytes,
                        max_context=max_context,
                        resident=None,
                        evidence_measured_at=freshness.get(row.id),
                    ),
                )
            )
    return out


def _loadcoach_rows(engine: Engine) -> list[tuple[str, str | None, str | None, CatalogAppRow]]:
    """LoadCoach's own models, with the residency it already tracks per model."""
    models = reflect_table(engine, "models")
    if models is None:
        return []
    residency = reflect_table(engine, "residency")
    resident_ids: set[str] = set()
    if residency is not None:
        with engine.connect() as connection:
            statement = select(residency.c.model_id).where(residency.c.resident.is_(True))
            resident_ids = {row.model_id for row in connection.execute(statement)}
    out: list[tuple[str, str | None, str | None, CatalogAppRow]] = []
    with engine.connect() as connection:
        for row in connection.execute(select(models)):
            out.append(
                (
                    row.canonical_id,
                    row.family,
                    row.quantization,
                    CatalogAppRow(
                        model_id=row.id,
                        provider_kind=row.provider_kind,
                        provider_model_name=row.provider_model_name,
                        enabled=row.enabled,
                        available=row.available,
                        size_bytes=row.size_bytes,
                        max_context=row.max_context,
                        resident=row.id in resident_ids,
                        evidence_measured_at=None,
                    ),
                )
            )
    return out


_APP_READERS: Final[
    dict[str, Callable[[Engine], list[tuple[str, str | None, str | None, CatalogAppRow]]]]
] = {"freeweight": _freeweight_rows, "loadcoach": _loadcoach_rows}


def catalog_entries(
    settings: Settings,
    database: Database,
    *,
    urls: DatabaseUrlCache,
    monotonic: float,
    ollama_client: httpx.Client | None = None,
) -> tuple[CatalogEntry, ...]:
    """Every model FreeWeight and LoadCoach know, joined by canonical identity.

    Args:
        settings: The validated settings.
        database: WeightRoomGym's own database, for the ``known_revisions`` check.
        urls: The effective-database-URL cache.
        monotonic: A monotonic clock reading, for that cache.
        ollama_client: A transport carrying Ollama's ``base_url``, for the residency fallback;
            ``None`` skips it (a row LoadCoach does not carry residency for then reports ``None``).

    Returns:
        Every joined row, sorted by canonical id. An application whose database is unreachable or
        at a revision this build does not know contributes nothing, silently — the join is a
        best-effort read of what answers, not a page that fails because one side is down.
    """
    by_canonical: dict[str, dict[str, CatalogAppRow]] = {}
    identity: dict[str, tuple[str, str, str | None, str | None]] = {}
    for app in CATALOG_APPS:
        try:
            with open_app_database(
                settings, database, app, urls=urls, now=monotonic, require_known=False
            ) as handle:
                if not handle.revision.is_known:
                    continue
                rows = _APP_READERS[app](handle.engine)
        except AppDatabaseUnavailable:
            continue
        for canonical_id, family, quantization, app_row in rows:
            by_canonical.setdefault(canonical_id, {})[app] = app_row
            prior = identity.get(canonical_id)
            if prior is None:
                identity[canonical_id] = (
                    app_row.provider_kind,
                    app_row.provider_model_name,
                    family,
                    quantization,
                )
            else:
                pk, pmn, fam, quant = prior
                identity[canonical_id] = (
                    pk,
                    pmn,
                    fam if fam is not None else family,
                    quant if quant is not None else quantization,
                )
    ollama_names: set[str] | None = None
    if ollama_client is not None:
        resident, error = resident_models(settings, client=ollama_client)
        if error is None:
            ollama_names = {view.name for view in resident}
    entries: list[CatalogEntry] = []
    for canonical_id, apps in by_canonical.items():
        if ollama_names is not None:
            for app_name, app_row in list(apps.items()):
                if app_row.resident is None and app_row.provider_kind == "ollama":
                    apps[app_name] = replace(
                        app_row, resident=app_row.provider_model_name in ollama_names
                    )
        provider_kind, provider_model_name, family, quantization = identity[canonical_id]
        entries.append(
            CatalogEntry(
                canonical_id, provider_kind, provider_model_name, family, quantization, apps
            )
        )
    return tuple(sorted(entries, key=lambda entry: entry.canonical_id))


# --- Talking to the two applications ----------------------------------------------------------


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"{response.status_code} {response.text[:200]}"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return f"{response.status_code} {error['message']}"
    return str(response.status_code)


def _timed_out(app: str, method: str, path: str) -> AppTimedOut:
    """The console gave up waiting on ``method path``; reuses WPF1's wording verbatim (app_api's
    own ``_unreachable``, not exported) so an operator sees one sentence for every slow call."""
    return AppTimedOut(
        f"{app} has not answered {method} {path} within {_HTTP_TIMEOUT_SECONDS:g} s, so the "
        f"console stopped waiting. The work may still be running — nothing was cancelled and "
        f"nothing was sent again. Check the page again shortly.",
        details={"app": app, "path": path, "timeout_seconds": _HTTP_TIMEOUT_SECONDS},
    )


def set_enabled(
    settings: Settings, app: str, model_id: str, *, enabled: bool, client: httpx.Client
) -> dict[str, Any]:
    """``POST {app}/api/v1/models/{model_id}/enabled`` — ADR-0118, api.md §5.

    Raises:
        AppTimedOut: ``app`` did not answer within the timeout; it may still be working
            (row WPF11) — the caller audits this ``pending`` via ``app_api.outcome_of``, not
            ``refused``.
        CatalogRefused: The application answered with an error, or did not answer for a reason
            that is not a timeout (connection refused, DNS, TLS, …).
    """
    base_url = getattr(settings.apps, app).base_url
    path = f"/api/v1/models/{model_id}/enabled"
    headers = {}
    token = bearer_token(settings, app)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = client.post(
            f"{base_url.rstrip('/')}{path}",
            json={"enabled": enabled},
            headers=headers,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise _timed_out(app, "POST", path) from exc
    except httpx.HTTPError as exc:
        raise CatalogRefused(f"{app} did not answer: {exc}", details={"app": app}) from exc
    if not response.is_success:
        raise CatalogRefused(
            f"{app} refused: {_error_message(response)}",
            details={"app": app, "status": response.status_code},
        )
    try:
        return dict(response.json())
    except ValueError:
        return {}
