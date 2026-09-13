"""weightroom.services.freeweight_goals — the data and calls behind FreeWeight's Goals (row WP4).

A goal is FreeWeight's: its pack on disk, its rows, its hash, its lint and its calibration, and a
goal still being authored is a FreeWeight draft row (spec §10). Every write here goes to
FreeWeight's API through :mod:`~weightroom.services.app_api`, which answers or refuses in
FreeWeight's own words (arc index §2 item 4); this module parses a form into the body FreeWeight's
route takes and nothing more.

While FreeWeight is stopped, the goal listing, one goal's criteria and tasks, and its stored
calibration report read FreeWeight's database — the rows it projected from each pack and the report
it wrote. What only FreeWeight computes — lint, rule proposals, the declared score mix, a report's
band, a draft's proposals — is not recomputed here; a page says it reads it from the running API.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Final

from baseaicore import SuiteError

from weightroom.services.app_api import AppRefused, call
from weightroom.services.app_pages import rows_where
from weightroom.services.freeweight_pages import (
    APP,
    LIST_CAP,
    PAGE_ROWS,
    NotRecorded,
    _document,
    _listed,
    _loads,
    segment,
)

if TYPE_CHECKING:
    import httpx

    from weightroom.config import Settings
    from weightroom.services.db_reader import AppDatabase

__all__ = [
    "DRAFT_STEPS",
    "GoalFormInvalid",
    "commit_edit",
    "create_goal",
    "delete_draft",
    "delete_goal",
    "draft_api",
    "draft_body",
    "draft_step",
    "fork_starter",
    "goal_api",
    "goal_db",
    "goals_api",
    "goals_db",
    "import_bundle",
    "pack_from_form",
    "preview_edit",
    "report_from_rows",
    "save_draft",
    "start_draft",
    "suggest_api",
    "add_pasted",
    "calibration_api",
    "calibration_db",
    "grades_from_form",
    "grading_api",
    "grading_view",
    "judges_api",
    "pick_sample",
    "promote_run",
    "report_api",
    "report_db",
    "run_grading_api",
    "submit_grades",
    "submit_run_grades",
    "validate_api",
]

_TIMEOUT_SECONDS: Final = 30.0
DRAFT_STEPS: Final[tuple[str, ...]] = ("criteria", "rules", "tasks")
"""The draft steps a form posts to, in FreeWeight's own route names (``/goals/drafts/{id}/…``)."""


class GoalFormInvalid(SuiteError):
    """A form field that cannot become the body FreeWeight's route takes; nothing was sent."""

    code: ClassVar[str] = "VALIDATION_ERROR"


def _json_field(text: str, field: str) -> Any:  # noqa: ANN401 — whatever JSON the field holds
    try:
        return json.loads(text)
    except ValueError as exc:
        message = f"{field} is not JSON: {exc}. Nothing was sent."
        raise GoalFormInvalid(message, details={"field": field}) from exc


# --- Reading --------------------------------------------------------------------------------------


def goals_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /goals``, ``GET /goals/starters`` and ``GET /goals/drafts``: the Goals page.

    Raises:
        AppRefused: A read FreeWeight refused.
        AppUnreachable: It did not answer.
    """
    listed = call(client, settings, APP, "GET", "goals", timeout_seconds=_TIMEOUT_SECONDS)
    starters = call(client, settings, APP, "GET", "goals/starters")
    drafts = call(client, settings, APP, "GET", "goals/drafts")
    return {
        "goals": _listed(listed, "items"),
        "starters": _listed(starters, "items"),
        "drafts": _listed(drafts, "items"),
    }


def _goal_level(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The goal's own report row — the one no criterion names — newest first."""
    level = [one for one in reports if one.get("goal_criterion_id") is None]
    return max(level, key=lambda one: str(one.get("measured_at") or ""), default=None)


def _goal_row(row: Mapping[str, Any], report: Mapping[str, Any] | None) -> dict[str, Any]:
    """A ``goals`` row under ``GET /goals``' names; what FreeWeight computes is ``None``."""
    measured = report is not None
    stored = dict(report or {})
    return {
        "slug": row.get("slug"),
        "name": row.get("name"),
        "intent": row.get("intent"),
        "goal_hash": row.get("goal_hash"),
        "goal_pack_version": row.get("goal_pack_version"),
        "capability_id": row.get("capability_id"),
        "contributes_to": row.get("contributes_to"),
        "score_method_mix": None,
        "unforked": bool(row.get("unforked")),
        "forked_from": row.get("forked_from"),
        "calibration_state": (
            None
            if report is None
            else "calibrated"
            if stored.get("passed_gate")
            else "uncalibrated"
        ),
        "kappa_w": stored.get("kappa_w"),
        "n_holdout": stored.get("n_holdout"),
        "calibrated_at": stored.get("measured_at"),
        "calibration_stale": measured and stored.get("goal_hash") != row.get("goal_hash"),
    }


def goals_db(handle: AppDatabase) -> dict[str, Any]:
    """Every goal FreeWeight projected into its database, with its stored calibration.

    Starters ship inside FreeWeight's package and drafts are read back through its API, so both
    are ``None`` here.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    reports: dict[Any, list[dict[str, Any]]] = {}
    for one in rows_where(handle, "calibration_reports", limit=LIST_CAP * 4):
        reports.setdefault(one.get("goal_id"), []).append(one)
    return {
        "goals": [
            _goal_row(row, _goal_level(reports.get(row.get("id"), [])))
            for row in rows_where(
                handle, "goals", order_by="slug", descending=False, limit=LIST_CAP
            )
        ],
        "starters": None,
        "drafts": None,
    }


def goal_api(client: httpx.Client, settings: Settings, slug: str) -> dict[str, Any]:
    """``GET /goals/{slug}`` and the goal's results (``GET /results?suite=goal.<slug>``).

    A refused results read leaves ``results`` ``None``, so the goal still renders.

    Raises:
        AppRefused: ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    goal = _document(
        call(
            client, settings, APP, "GET", f"goals/{segment(slug)}", timeout_seconds=_TIMEOUT_SECONDS
        )
    )
    try:
        results: list[dict[str, Any]] | None = _listed(
            call(
                client, settings, APP, "GET", "results",
                params={"suite": f"goal.{goal.get('slug') or slug}", "limit": PAGE_ROWS},
                timeout_seconds=_TIMEOUT_SECONDS,
            ),
            "items",
        )  # fmt: skip
    except AppRefused:
        results = None
    return {"goal": goal, "results": results}


def report_from_rows(
    criteria: list[dict[str, Any]], reports: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """A stored calibration report, from the rows FreeWeight wrote, under the report's names.

    FreeWeight writes one row for the goal and one per judged criterion together, and replaces the
    set on every calibration. The goal-level band is FreeWeight's reading of the coefficient and is
    not stored, so it is ``None``; each criterion's band and lint are stored beside its figures.
    """
    level = _goal_level(reports)
    if level is None:
        return None
    by_id = {one.get("id"): one for one in criteria}
    detail = _document(_loads(level.get("disagreement_json")))
    rows = []
    for one in reports:
        criterion = by_id.get(one.get("goal_criterion_id"))
        if criterion is None:
            continue
        stored = _document(_loads(one.get("disagreement_json")))
        rows.append(
            {
                "criterion": criterion.get("key"),
                "weight": criterion.get("weight"),
                "kappa_w": one.get("kappa_w"),
                "rho": one.get("rho"),
                "mae": one.get("mae"),
                "bias": one.get("bias"),
                "n_holdout": one.get("n_holdout"),
                "inter_juror_alpha": one.get("inter_juror_alpha"),
                "judge_validity_factor": one.get("judge_validity_factor"),
                "band": stored.get("band"),
                "lint": stored.get("lint"),
                "disagreements": _listed(stored, "samples"),
            }
        )
    return {
        "goal_hash": level.get("goal_hash"),
        "calibration_state": "calibrated" if level.get("passed_gate") else "uncalibrated",
        "passed_gate": bool(level.get("passed_gate")),
        "weighted_kappa_w": level.get("kappa_w"),
        "min_agreement": level.get("min_agreement"),
        "judge_validity_factor": level.get("judge_validity_factor"),
        "n_holdout": level.get("n_holdout"),
        "n_anchor": level.get("n_anchor"),
        "band": None,
        "criteria": rows,
        "judge_set": _loads(level.get("judge_set_json")),
        "graded_by": level.get("graded_by"),
        "measured_at": level.get("measured_at"),
        "policy_version": level.get("policy_version"),
        "warnings": [str(one) for one in detail.get("warnings") or []],
    }


def goal_db(handle: AppDatabase, slug: str) -> dict[str, Any]:
    """One goal's rows under ``GET /goals/{slug}``' names: criteria, tasks, lint and its report.

    The pack's documents live on disk, read by FreeWeight, so ``pack`` is ``None``; so are the
    goal's results, which are FreeWeight's metric query.

    Raises:
        NotRecorded: FreeWeight's database holds no goal with that slug.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(handle, "goals", equals={"slug": slug}, limit=1)
    if not found:
        raise NotRecorded(f"FreeWeight's database holds no goal {slug!r}.", details={"goal": slug})
    row = found[0]
    mine = {"goal_id": row.get("id")}
    criteria = rows_where(
        handle, "goal_criteria", equals=mine, order_by="ordinal", descending=False, limit=LIST_CAP
    )
    tasks = rows_where(
        handle, "goal_tasks", equals=mine, order_by="ordinal", descending=False, limit=LIST_CAP
    )
    reports = rows_where(handle, "calibration_reports", equals=mine, limit=LIST_CAP)
    goal = _goal_row(row, _goal_level(reports))
    goal.update(
        {
            "criteria": [
                {
                    "key": one.get("key"),
                    "name": one.get("name"),
                    "rung": one.get("rung"),
                    "weight": one.get("weight"),
                    "gate": bool(one.get("is_gate")),
                    "rule_type": _document(_loads(one.get("rule_json"))).get("type"),
                    "scale_points": one.get("scale_points"),
                    "has_scale_descriptors": bool(_loads(one.get("scale_descriptors_json"))),
                }
                for one in criteria
            ],
            "tasks": [
                {
                    "key": one.get("key"),
                    "name": one.get("name"),
                    "prompt_id": one.get("prompt_id"),
                    "prompt_version": one.get("prompt_version"),
                    "prompt_sha256": one.get("prompt_sha256"),
                    "rendered_prompt_hash": one.get("rendered_prompt_hash"),
                    "is_starter": bool(one.get("is_starter")),
                    "has_source": _loads(one.get("source_json")) is not None,
                }
                for one in tasks
            ],
            "findings": [
                dict(one) for one in _loads(row.get("lint_json")) or [] if isinstance(one, Mapping)
            ],
            "pack": None,
            "calibration": report_from_rows(criteria, reports),
        }
    )
    return {"goal": goal, "results": None}


def draft_api(client: httpx.Client, settings: Settings, draft_id: str) -> dict[str, Any]:
    """``GET /goals/drafts/{id}``: the draft with its proposals, weight shift and grading cost.

    Raises:
        AppRefused: ``NOT_FOUND`` for an unknown or expired draft.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", f"goals/drafts/{segment(draft_id)}"))


def validate_api(client: httpx.Client, settings: Settings, slug: str) -> dict[str, Any]:
    """``POST /goals/{slug}/validate``: every finding with its severity. A read, though a POST.

    Raises:
        AppRefused: ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "POST", f"goals/{segment(slug)}/validate"))


def suggest_api(client: httpx.Client, settings: Settings, slug: str) -> dict[str, Any]:
    """``POST /goals/{slug}/suggest-rules``: proposals with their parameters, never applied.

    Raises:
        AppRefused: ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "POST", f"goals/{segment(slug)}/suggest-rules"))


# --- Acting ---------------------------------------------------------------------------------------


def pack_from_form(*, goal_text: str, tasks_text: str) -> dict[str, Any]:
    """The ``{"goal", "tasks"}`` body ``POST /goals`` and ``PUT /goals/{slug}`` take, from a form.

    Raises:
        GoalFormInvalid: A field is not JSON, the goal is not an object, or the tasks are not a
            list of objects. FreeWeight validates everything else.
    """
    goal = _json_field(goal_text, "goal.json")
    tasks = _json_field(tasks_text.strip() or "[]", "tasks")
    if not isinstance(goal, dict):
        raise GoalFormInvalid("goal.json must be a JSON object.", details={"field": "goal.json"})
    if not isinstance(tasks, list) or not all(isinstance(one, dict) for one in tasks):
        message = "tasks must be a JSON list of task prompt records."
        raise GoalFormInvalid(message, details={"field": "tasks"})
    return {"goal": goal, "tasks": tasks}


def create_goal(
    client: httpx.Client, settings: Settings, pack: Mapping[str, Any]
) -> dict[str, Any]:
    """``POST /goals``: the goal with its lint findings, which never block creation.

    Raises:
        AppRefused: ``GOAL_INVALID``, ``CONFLICT`` for a slug in use, ``VALIDATION_ERROR``.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(
            client,
            settings,
            APP,
            "POST",
            "goals",
            body=dict(pack),
            timeout_seconds=_TIMEOUT_SECONDS,
        )
    )


def fork_starter(
    client: httpx.Client, settings: Settings, starter: str, *, slug: str
) -> dict[str, Any]:
    """``POST /goals/starters/{key}/fork``: the forked goal, ``unforked`` until it is edited.

    Raises:
        AppRefused: ``NOT_FOUND`` for an unknown starter, ``CONFLICT`` for a slug in use.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(
            client, settings, APP, "POST", f"goals/starters/{segment(starter)}/fork",
            body={"slug": slug.strip() or None}, timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip


def start_draft(
    client: httpx.Client, settings: Settings, *, intent: str, name: str, starter: str | None
) -> dict[str, Any]:
    """``POST /goals/drafts``: a draft from step 1's intent, or from a starter to customise.

    Raises:
        AppRefused: ``VALIDATION_ERROR`` for an empty intent, ``NOT_FOUND`` for an unknown starter.
        AppUnreachable: It did not answer.
    """
    body: dict[str, Any] = {"starter": starter} if starter else {"intent": intent, "name": name}
    return _document(call(client, settings, APP, "POST", "goals/drafts", body=body))


def _tristate(value: str) -> bool | None:
    return True if value == "yes" else False if value == "no" else None


def draft_body(step: str, fields: Mapping[str, str]) -> dict[str, Any]:
    """The body one draft step takes, from its form, as FreeWeight's own wizard page posts it.

    Args:
        step: ``criteria``, ``rules`` or ``tasks``.
        fields: The form's text fields.

    Raises:
        GoalFormInvalid: An action the criteria step does not have, a scale size that is not a
            whole number, or rule parameters that are not a JSON object. Nothing is sent.
    """
    if step == "rules":
        text = fields.get("parameters", "").strip()
        parameters = _json_field(text, "parameters") if text else None
        if parameters is not None and not isinstance(parameters, dict):
            raise GoalFormInvalid(
                "The rule parameters must be a JSON object; nothing was accepted.",
                details={"field": "parameters"},
            )
        return {
            "criterion": fields.get("criterion", ""),
            "rule_type": fields.get("rule_type", ""),
            "parameters": parameters,
        }
    if step == "tasks":
        return {"name": fields.get("name", ""), "prompt_text": fields.get("prompt_text", "")}
    action = fields.get("action", "")
    criterion = fields.get("criterion", "")
    if action == "add":
        return {
            "action": action,
            "name": fields.get("name", ""),
            "intent": fields.get("intent", ""),
        }
    if action == "answer":
        return {
            "action": action,
            "criterion": criterion,
            "graded_alike": _tristate(fields.get("graded_alike", "")),
            "one_quality": _tristate(fields.get("one_quality", "")),
        }
    if action == "describe":
        try:
            points = int(fields.get("points") or "5")
        except ValueError as exc:
            message = "The scale size must be a whole number of points."
            raise GoalFormInvalid(message, details={"field": "points"}) from exc
        return {
            "action": action, "criterion": criterion, "points": points,
            "top": fields.get("top", ""), "middle": fields.get("middle", ""),
            "bottom": fields.get("bottom", ""),
        }  # fmt: skip
    if action == "split":
        return {
            "action": action, "criterion": criterion,
            "first": fields.get("first", ""), "second": fields.get("second", ""),
        }  # fmt: skip
    raise GoalFormInvalid(
        f"{action!r} is not one of step 2's actions.", details={"field": "action"}
    )


def draft_step(
    client: httpx.Client, settings: Settings, draft_id: str, step: str, body: Mapping[str, Any]
) -> dict[str, Any]:
    """``POST /goals/drafts/{id}/{criteria|rules|tasks}``: the draft after the step.

    Raises:
        AppRefused: The wizard's own refusal (``VALIDATION_ERROR``), ``NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(
            client, settings, APP, "POST", f"goals/drafts/{segment(draft_id)}/{segment(step)}",
            body=dict(body),
        )
    )  # fmt: skip


def save_draft(
    client: httpx.Client, settings: Settings, draft_id: str, *, slug: str, name: str
) -> dict[str, Any]:
    """``POST /goals/drafts/{id}/save``: ``{"draft", "goal"}`` — the pack it wrote, or already had.

    Raises:
        AppRefused: ``VALIDATION_ERROR`` (no criterion, no task, an unanchored scale), ``CONFLICT``.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(
            client, settings, APP, "POST", f"goals/drafts/{segment(draft_id)}/save",
            body={"slug": slug.strip(), "name": name.strip()}, timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip


def delete_draft(client: httpx.Client, settings: Settings, draft_id: str) -> None:
    """``DELETE /goals/drafts/{id}``.

    Raises:
        AppRefused: ``NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    call(client, settings, APP, "DELETE", f"goals/drafts/{segment(draft_id)}")


def preview_edit(
    client: httpx.Client, settings: Settings, slug: str, pack: Mapping[str, Any]
) -> dict[str, Any]:
    """``PUT /goals/{slug}?dry_run=true``: the replacement built and discarded, its ``hash_change``.

    Raises:
        AppRefused: ``GOAL_INVALID``, a rename refused, ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(
            client, settings, APP, "PUT", f"goals/{segment(slug)}", params={"dry_run": "true"},
            body=dict(pack), timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip


def commit_edit(
    client: httpx.Client, settings: Settings, slug: str, pack: Mapping[str, Any]
) -> dict[str, Any]:
    """``PUT /goals/{slug}``: the replacement applied, with the ``hash_change`` it made.

    Raises:
        AppRefused: As :func:`preview_edit`.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(
            client, settings, APP, "PUT", f"goals/{segment(slug)}", body=dict(pack),
            timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip


def delete_goal(
    client: httpx.Client, settings: Settings, slug: str, *, confirm: bool
) -> dict[str, Any]:
    """``DELETE /goals/{slug}``: FreeWeight's preview, or — confirmed — the deletion it previews.

    Raises:
        AppRefused: ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(
            client, settings, APP, "DELETE", f"goals/{segment(slug)}",
            params={"dry_run": "false"} if confirm else None, timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip


def import_bundle(
    client: httpx.Client, settings: Settings, *, bundle_text: str, slug: str
) -> dict[str, Any]:
    """``POST /goals/import``: FreeWeight's size cap, containment and hash checks, then the goal.

    Raises:
        GoalFormInvalid: The bundle is not a JSON object; nothing was sent.
        AppRefused: ``PAYLOAD_TOO_LARGE``, ``GOAL_PATH_UNSAFE``, ``GOAL_HASH_MISMATCH``,
            ``CONFLICT``
            naming the existing ``goal_hash``.
        AppUnreachable: It did not answer.
    """
    bundle = _json_field(bundle_text, "bundle")
    if not isinstance(bundle, dict):
        raise GoalFormInvalid("The bundle must be a JSON object.", details={"field": "bundle"})
    return _document(
        call(
            client, settings, APP, "POST", "goals/import",
            body={"bundle": bundle, "slug": slug.strip() or None}, timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip


# --- Calibration, grading, the report, judges (Gate B) --------------------------------------------


def _partitions(
    items: list[dict[str, Any]], graded: dict[str, int], criteria: int
) -> dict[str, Any]:
    """Counts by partition and by origin, and how many samples every criterion has graded.

    Counts only: a page that listed samples one by one with their origin or partition would unblind
    the grading page, which shows neither.
    """
    partitions: dict[str, dict[str, Any]] = {}
    origins: dict[str, int] = {}
    complete = 0
    for item in items:
        done = criteria > 0 and graded.get(str(item.get("id")), 0) >= criteria
        complete += int(done)
        name = str(item.get("partition") or "—")
        one = partitions.setdefault(name, {"partition": name, "samples": 0, "complete": 0})
        one["samples"] += 1
        one["complete"] += int(done)
        origin = str(item.get("origin") or "—")
        origins[origin] = origins.get(origin, 0) + 1
    return {
        "samples": len(items),
        "complete_samples": complete,
        "partitions": sorted(partitions.values(), key=lambda one: str(one["partition"])),
        "origins": origins,
    }


def calibration_api(client: httpx.Client, settings: Settings, slug: str) -> dict[str, Any]:
    """``GET /goals/{slug}/calibration`` as counts, beside the goal, its runs and the models.

    The completed runs of ``goal.<slug>`` are what a promotion reads from; the enabled models are
    what a generation run can be started on. A refused read of either leaves it ``None``.

    Raises:
        AppRefused: ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    from weightroom.services.freeweight_pages import models_api

    goal = _document(
        call(
            client, settings, APP, "GET", f"goals/{segment(slug)}", timeout_seconds=_TIMEOUT_SECONDS
        )
    )
    body = _document(
        call(
            client, settings, APP, "GET", f"goals/{segment(slug)}/calibration",
            timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip
    progress = _document(body.get("progress"))
    criteria = int(progress.get("judged_criteria") or 0)
    remaining: dict[str, int] = {}
    for pair in _listed(progress, "remaining"):
        remaining[str(pair.get("sample_id"))] = remaining.get(str(pair.get("sample_id")), 0) + 1
    items = _listed(body, "items")
    graded = {
        str(item.get("id")): criteria - remaining.get(str(item.get("id")), 0) for item in items
    }
    runs: list[dict[str, Any]] | None
    models: list[dict[str, Any]] | None
    try:
        runs = _listed(
            call(
                client, settings, APP, "GET", "runs",
                params={"suite": f"goal.{slug}", "status": "completed", "limit": PAGE_ROWS},
            ),
            "runs",
        )  # fmt: skip
    except AppRefused:
        runs = None
    try:
        models = [
            one for one in models_api(client, settings, sort="canonical_id") if one.get("enabled")
        ]
    except AppRefused:
        models = None
    return {
        "goal": goal,
        **_partitions(items, graded, criteria),
        "recorded_grades": progress.get("recorded_grades"),
        "expected_grades": progress.get("expected_grades"),
        "min_samples": progress.get("min_samples"),
        "target_samples": progress.get("target_samples"),
        "runs": runs,
        "models": models,
    }


def calibration_db(handle: AppDatabase, slug: str) -> dict[str, Any]:
    """The calibration set's rows, counted: samples by partition and origin, grades recorded.

    Raises:
        NotRecorded: FreeWeight's database holds no goal with that slug.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(handle, "goals", equals={"slug": slug}, limit=1)
    if not found:
        raise NotRecorded(f"FreeWeight's database holds no goal {slug!r}.", details={"goal": slug})
    row = found[0]
    mine = {"goal_id": row.get("id")}
    graded_ids = {
        one.get("id")
        for one in rows_where(handle, "goal_criteria", equals=mine, limit=LIST_CAP)
        if one.get("rung") in ("judge", "human")
    }
    items = rows_where(handle, "calibration_samples", equals=mine, limit=LIST_CAP)
    ids = {str(item.get("id")) for item in items}
    graded: dict[str, int] = {}
    for grade in rows_where(handle, "calibration_grades", limit=LIST_CAP * 8):
        sample = str(grade.get("calibration_sample_id"))
        if sample in ids and grade.get("goal_criterion_id") in graded_ids:
            graded[sample] = graded.get(sample, 0) + 1
    config = _document(_loads(row.get("calibration_config_json")))
    reports = rows_where(handle, "calibration_reports", equals=mine, limit=LIST_CAP)
    return {
        "goal": _goal_row(row, _goal_level(reports)),
        **_partitions(items, graded, len(graded_ids)),
        "recorded_grades": sum(graded.values()),
        "expected_grades": len(items) * len(graded_ids),
        "min_samples": config.get("min_samples"),
        "target_samples": config.get("target_samples"),
        "runs": None,
        "models": None,
    }


def add_pasted(
    client: httpx.Client, settings: Settings, slug: str, *, content: str, task: str
) -> dict[str, Any]:
    """``POST /goals/{slug}/calibration/samples`` with one pasted text: ``sent`` and ``added``.

    Raises:
        AppRefused: ``VALIDATION_ERROR`` for an empty text, ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    body = _document(
        call(
            client, settings, APP, "POST", f"goals/{segment(slug)}/calibration/samples",
            body={"samples": [{"content": content, "goal_task_key": task.strip() or None}]},
        )
    )  # fmt: skip
    return {"sent": 1, "added": body.get("count")}


def promote_run(client: httpx.Client, settings: Settings, slug: str, run_id: str) -> dict[str, Any]:
    """Promote every completed sample of one run into the calibration set: ``sent`` and ``added``.

    The run's samples are read test by test through FreeWeight's own cursor; each is then named by
    ``source_sample_id`` alone, so FreeWeight reads the text it stored and refuses a sample that is
    not a completed sample of a run of this goal.

    Raises:
        GoalFormInvalid: The run has no completed sample; nothing was sent.
        AppRefused: ``RUN_NOT_FOUND``, or FreeWeight's refusal of a sample it will not promote.
        AppUnreachable: It did not answer.
    """
    run = _document(call(client, settings, APP, "GET", f"runs/{segment(run_id)}"))
    full = str(run.get("id") or run_id)
    sample_ids: list[str] = []
    for test in _listed(run, "tests"):
        cursor: str | None = None
        while True:
            body = call(
                client, settings, APP, "GET",
                f"runs/{segment(full)}/tests/{segment(str(test.get('id')))}/samples",
                params={"cursor": cursor, "limit": 1000}, timeout_seconds=_TIMEOUT_SECONDS,
            )  # fmt: skip
            sample_ids += [
                str(one.get("id"))
                for one in _listed(body, "samples")
                if one.get("status") == "completed"
            ]
            cursor = _document(_document(body).get("page")).get("next_cursor")
            if not cursor:
                break
    if not sample_ids:
        message = f"Run {full} has no completed sample to promote."
        raise GoalFormInvalid(message, details={"run_id": full})
    added = _document(
        call(
            client, settings, APP, "POST", f"goals/{segment(slug)}/calibration/samples",
            body={"samples": [{"source_sample_id": one} for one in sample_ids]},
            timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip
    return {"sent": len(sample_ids), "added": added.get("count")}


def grading_view(document: Mapping[str, Any], *, run: bool) -> dict[str, Any]:
    """FreeWeight's blinded grading view — a calibration set's or a run's — in one page's names.

    Only what FreeWeight's view carries: each sample's text and its grades so far, the criteria with
    their scales and descriptors, and the progress. Nothing here can unblind a sample, because the
    view FreeWeight serves holds nothing that could.
    """
    if run:
        samples = [
            {
                "sample_id": one.get("sample_id"),
                "case_id": one.get("case_id"),
                "text": one.get("response_text"),
                "grades": _document(one.get("grades")),
            }
            for one in _listed(document, "samples")
        ]
        return {
            "criteria": _listed(document, "criteria"),
            "samples": samples,
            "recorded": document.get("recorded_grades"),
            "expected": document.get("expected_grades"),
            "complete": bool(document.get("complete")),
            "name": document.get("goal_name") or document.get("goal_slug"),
        }
    progress = _document(document.get("progress"))
    return {
        "criteria": _listed(document, "criteria"),
        "samples": [
            {
                "sample_id": one.get("sample_id"),
                "case_id": None,
                "text": one.get("content"),
                "grades": _document(one.get("grades")),
            }
            for one in _listed(document, "samples")
        ],  # fmt: skip
        "recorded": progress.get("recorded_grades"),
        "expected": progress.get("expected_grades"),
        "complete": bool(progress.get("complete")),
        "name": document.get("slug"),
    }


def grading_api(client: httpx.Client, settings: Settings, slug: str) -> dict[str, Any]:
    """``GET /goals/{slug}/calibration/grading`` as :func:`grading_view`.

    Raises:
        AppRefused: ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    path = f"goals/{segment(slug)}/calibration/grading"
    return grading_view(
        _document(call(client, settings, APP, "GET", path, timeout_seconds=_TIMEOUT_SECONDS)),
        run=False,
    )


def run_grading_api(client: httpx.Client, settings: Settings, run_id: str) -> dict[str, Any]:
    """``GET /runs/{id}/grading`` as :func:`grading_view`.

    Raises:
        AppRefused: ``RUN_NOT_FOUND``, ``RUN_NOT_GRADEABLE`` naming why.
        AppUnreachable: It did not answer.
    """
    path = f"runs/{segment(run_id)}/grading"
    return grading_view(
        _document(call(client, settings, APP, "GET", path, timeout_seconds=_TIMEOUT_SECONDS)),
        run=True,
    )


def pick_sample(
    samples: list[dict[str, Any]], criteria: int, *, sample: str | None, after: str | None
) -> int | None:
    """Which sample the grading page opens at: the one asked for, else the next one not finished.

    Args:
        samples: The view's samples, in FreeWeight's order.
        criteria: How many criteria each sample is graded on.
        sample: A sample the operator navigated to.
        after: The sample just saved: the search for an unfinished one starts after it and wraps.

    Returns:
        The index to show, or ``None`` when there is no sample. With every sample finished, the one
        just saved (or the first), so the page never jumps somewhere the operator did not go.
    """
    ids = [str(one.get("sample_id")) for one in samples]
    if not ids:
        return None
    if sample in ids:
        return ids.index(sample)
    start = ids.index(after) + 1 if after in ids else 0
    for offset in range(len(ids)):
        index = (start + offset) % len(ids)
        if len(_document(samples[index].get("grades"))) < criteria:
            return index
    return ids.index(after) if after in ids else 0


def grades_from_form(
    *, sample_id: str, criteria: list[str], grades: list[str], notes: list[str]
) -> list[dict[str, Any]]:
    """One sample's grades from the page's aligned ``criterion``, ``grade`` and ``note`` fields.

    A criterion left ungraded is left out, so a partial submission records what was given and
    nothing else.

    Raises:
        GoalFormInvalid: The three lists do not line up, or a grade is not a whole number.
    """
    if not (len(criteria) == len(grades) == len(notes)):
        message = "The grading form's criteria, grades and notes do not line up; nothing was sent."
        raise GoalFormInvalid(message, details={"sample_id": sample_id})
    batch = []
    for criterion, grade, note in zip(criteria, grades, notes, strict=True):
        if not grade.strip():
            continue
        try:
            value = int(grade)
        except ValueError as exc:
            message = f"{grade!r} is not a grade; nothing was sent."
            raise GoalFormInvalid(message, details={"criterion": criterion}) from exc
        batch.append({"sample_id": sample_id, "criterion": criterion, "grade": value, "note": note})
    return batch


def submit_grades(
    client: httpx.Client,
    settings: Settings,
    slug: str,
    grades: list[dict[str, Any]],
    *,
    graded_by: str,
) -> dict[str, Any]:
    """``POST /goals/{slug}/calibration/grades``, upserted per ``(sample, criterion)``.

    Raises:
        AppRefused: ``VALIDATION_ERROR`` (a grade off the scale, a sample the goal does not have).
        AppUnreachable: It did not answer — some of the batch may have landed.
    """
    return _document(
        call(
            client, settings, APP, "POST", f"goals/{segment(slug)}/calibration/grades",
            body={"grades": grades, "graded_by": graded_by}, timeout_seconds=_TIMEOUT_SECONDS,
        )
    )  # fmt: skip


def submit_run_grades(
    client: httpx.Client,
    settings: Settings,
    run_id: str,
    grades: list[dict[str, Any]],
    *,
    graded_by: str,
) -> dict[str, Any]:
    """``POST /runs/{id}/grades``: upserted, and the run's composites and evidence recomputed.

    Raises:
        AppRefused: ``RUN_NOT_GRADEABLE``, ``VALIDATION_ERROR``.
        AppUnreachable: It did not answer — some of the batch may have landed.
    """
    return _document(
        call(
            client, settings, APP, "POST", f"runs/{segment(run_id)}/grades",
            body={"grades": grades, "graded_by": graded_by}, timeout_seconds=120.0,
        )
    )  # fmt: skip


def report_api(client: httpx.Client, settings: Settings, slug: str) -> dict[str, Any]:
    """``GET /goals/{slug}`` and ``GET /goals/{slug}/calibration/report``.

    Raises:
        AppRefused: ``GOAL_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    goal = _document(
        call(
            client, settings, APP, "GET", f"goals/{segment(slug)}", timeout_seconds=_TIMEOUT_SECONDS
        )
    )
    report = _document(
        call(client, settings, APP, "GET", f"goals/{segment(slug)}/calibration/report")
    )
    return {"goal": goal, "report": report}


def report_db(handle: AppDatabase, slug: str) -> dict[str, Any]:
    """The stored report from FreeWeight's rows (:func:`report_from_rows`), beside its goal.

    A goal with no stored report says only that: ``calibration_state`` ``None``.

    Raises:
        NotRecorded: FreeWeight's database holds no goal with that slug.
    """
    goal = goal_db(handle, slug)["goal"]
    return {"goal": goal, "report": goal.get("calibration") or {"calibration_state": None}}


def judges_api(
    client: httpx.Client, settings: Settings, *, goal: str | None, candidate: str | None
) -> dict[str, Any]:
    """``GET /judges``, the goals to choose from, and — asked for — ``POST /judges/validate``.

    Raises:
        AppRefused: A refused read, or the dry run's refusal (an unknown goal).
        AppUnreachable: It did not answer.
    """
    judges = _document(
        call(client, settings, APP, "GET", "judges", params={"candidate": candidate},
             timeout_seconds=_TIMEOUT_SECONDS)
    )  # fmt: skip
    goals = [
        str(one.get("slug"))
        for one in _listed(call(client, settings, APP, "GET", "goals"), "items")
    ]
    validation = None
    if goal or candidate:
        validation = _document(
            call(
                client, settings, APP, "POST", "judges/validate",
                body={"goal": goal, "candidate": candidate}, timeout_seconds=_TIMEOUT_SECONDS,
            )
        )  # fmt: skip
    return {"judges": judges, "goals": goals, "validation": validation}
