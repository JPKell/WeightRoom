"""weightroom.services.job_kinds — what each job kind does (spec §7.10).

Each executor takes a :class:`~weightroom.services.jobs.JobContext`, writes what an operator
should read into its output, checks ``context.cancelled()`` between steps, and returns an
:class:`~weightroom.services.jobs.Outcome` — a failure is an outcome in words, not an exception.

* ``freeweight_suite_run`` — ``freeweight run start --model … --suite … [--adapter …] --json``,
  which executes the run in the child and exits with its outcome. It is launched inside
  ``systemd-run --user --scope`` under ``[host] memory_high``/``memory_max``: a run starts
  ``llama-server`` beneath whatever launched it, WeightRoomGym's own unit carries no cap
  (ADR-0125 rule 6), and ADR-0119 decision 4's wrapper is what a run started outside FreeWeight's
  unit wears — never dropped silently when ``systemd-run`` is missing. When another process holds
  FreeWeight's one execution slot (exit 7) the run stays queued there, and the job follows it with
  ``freeweight run wait``. Whether a benchmark may render an overridden prompt is FreeWeight's
  rule: the job passes ``--allow-prompt-override`` only when its own parameter says so, and
  FreeWeight refuses otherwise (prompt standards §6). ``--adapter`` is one more argument to the
  same command (row WPF2): an adapter FreeWeight cannot serve is refused by name, never replaced
  by its base (ADR-0058, ADR-0140). A ``cooldown_seconds`` parameter holds the job, before it
  launches anything, until that long after the previous suite run finished.
* ``freeweight_goal_calibrate`` — ``freeweight goals calibrate <slug> --progress --json`` (row WP4):
  a goal's jury grading its held-out samples, under the same scope, prefix and cap as a suite run —
  the jurors are model loads — its output one JSON line per holdout sample judged, naming no grade,
  and the report last.
* ``backup`` — each application's own ``db backup`` (``db_curated.run_curated``), and
  WeightRoomGym's own in-process.
* ``model_refresh`` — ``models refresh --json`` on FreeWeight and LoadCoach, then the catalog join.
* ``retention_trim`` — WeightRoomGym's own retention (finished job rows after 90 days, data model
  §3; guarded-write backups after ``guarded_backup_days``, ADR-0134 rule 3) and, only when
  ``freeweight_older_than_days`` is set, FreeWeight's own deletion of older results through its
  API, previewed and confirmed with its token (ADR-0134 rule 2). LoadCoach and PromptCadence trim
  their own content inside their own processes (``storage.content_retention_hours``); IdeaPress
  keeps everything. This kind reaches no further than that.
* ``docs_index`` — the documentation search index rebuilt from ``[docs] root``.
* ``self_restore`` — handed to a transient unit (``services/self_restore.py``, ADR-0136).
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from baseaicore import SuiteError

from weightroom.config import APPLICATIONS
from weightroom.domain.jobs import SUITE_RUN_SCOPE_PREFIX
from weightroom.services.apps import AppNotInstalled
from weightroom.services.catalog import catalog_entries
from weightroom.services.db_curated import delete_results, run_curated, run_self_curated
from weightroom.services.db_guard import list_backups
from weightroom.services.docs import DocsRootMissing, resolve_docs_root
from weightroom.services.docs_index import rebuild_index
from weightroom.services.jobs import (
    FINISHED_RETENTION_DAYS,
    Executor,
    Outcome,
    list_jobs,
    run_streaming,
    trim_finished_jobs,
)
from weightroom.services.processes import child_environment, executable_for, run_command
from weightroom.services.self_restore import hand_off

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from weightroom.services.jobs import JobContext, StreamResult

__all__ = [
    "EXECUTORS",
    "backup",
    "docs_index",
    "freeweight_goal_calibrate",
    "freeweight_suite_run",
    "model_refresh",
    "retention_trim",
    "run_id_in",
]

SUITE_RUN_TIMEOUT_SECONDS: Final = 12 * 3600.0
_REFRESH_TIMEOUT_SECONDS: Final = 600.0
_RUN_SLOT_TAKEN: Final = 7
"""``freeweight run start``'s exit when another process holds the machine's execution slot."""
_RUN_CANCELLED: Final = 6


def _which(context: JobContext) -> Callable[[str], str | None]:
    return context.services.which or shutil.which


def _brief(value: Any) -> str:  # noqa: ANN401 — an application's JSON or text, whatever it printed
    """The last line of what an application printed, for one line of job output."""
    if value is None:
        return "no output"
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    lines = text.strip().splitlines()
    return lines[-1][:300] if lines else "no output"


def _stream(context: JobContext, argv: Sequence[str], *, timeout_seconds: float) -> StreamResult:
    context.output.line("$ " + " ".join(argv))
    return run_streaming(
        argv,
        child_environment(),
        output=context.output,
        cancelled=context.cancelled,
        timeout_seconds=timeout_seconds,
        launcher=context.services.launcher,
    )


def run_id_in(text: str) -> str | None:
    """The run id ``freeweight run start --json`` prints as soon as the run is persisted.

    Also how the Runs page follows a run it started as a job (row WP3).
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            body = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(body, dict) and isinstance(body.get("run_id"), str):
            return str(body["run_id"])
    return None


def _capped(context: JobContext, wrapper: str, executable: str) -> list[str]:
    """``systemd-run --user --scope`` under ADR-0119's cap, then the FreeWeight executable.

    The scope is named with :data:`SUITE_RUN_SCOPE_PREFIX` and the job's id, so the memory-cap alert
    recognises a kill inside any FreeWeight workload the console starts.
    """
    host = context.settings.host
    return [
        wrapper, "--user", "--scope", "--quiet", f"--unit={SUITE_RUN_SCOPE_PREFIX}{context.job.id}",
        "-p", f"MemoryHigh={host.memory_high}", "-p", f"MemoryMax={host.memory_max}",
        "-p", "MemorySwapMax=0", executable,
    ]  # fmt: skip


def freeweight_goal_calibrate(context: JobContext) -> Outcome:
    """One goal's calibration, capped, FreeWeight's progress printed as its jury works (row WP4).

    ``freeweight goals calibrate`` partitions the graded set and has the jury grade the holdout —
    model loads, so it runs in the same capped scope as a suite run, and one at a time with the
    console's other jobs. It is not idempotent: a second execution is a second set of model loads,
    so a lost lease fails it rather than requeueing it.
    """
    params = context.job.params
    which = _which(context)
    executable = executable_for(context.settings, "freeweight", which=which)
    if executable is None:
        return Outcome("failed", "FreeWeight is not installed: set [apps.freeweight] executable.")
    wrapper = which("systemd-run")
    if wrapper is None:
        return Outcome(
            "failed",
            "ADR-0119: a calibration started by the console runs its jury under the host memory "
            "cap "
            f"([host] memory_max = {context.settings.host.memory_max}), and systemd-run is not on "
            "PATH to apply it. Nothing was started.",
        )
    argv = [*_capped(context, wrapper, executable), "goals", "calibrate", str(params["goal"])]
    argv += ["--progress", "--json"]
    if params.get("graded_by"):
        argv += ["--graded-by", str(params["graded_by"])]
    result = _stream(context, argv, timeout_seconds=SUITE_RUN_TIMEOUT_SECONDS)
    if result.cancelled:
        return Outcome("cancelled", "the calibration stopped on the operator's cancel")
    if result.timed_out:
        return Outcome("failed", "the calibration did not finish within 12 hours and was stopped")
    if result.ok:
        return Outcome("completed")
    return Outcome("failed", f"freeweight exited {result.returncode}")


def _cooled_down(context: JobContext, seconds: int) -> bool:
    """Wait until ``seconds`` after the previous suite run finished; ``False`` if cancelled.

    The previous run is the newest finished ``freeweight_suite_run`` job other than this one.
    None, or one that finished long enough ago, waits nothing.
    """
    if seconds <= 0:
        return True
    recent, _ = list_jobs(context.database, limit=10, kind="freeweight_suite_run")
    finished = [job.finished_at for job in recent if job.id != context.job.id and job.finished_at]
    if not finished:
        return True
    last, now = max(finished), context.now()
    if (last.tzinfo is None) != (now.tzinfo is None):  # both UTC; one stored without its zone
        last, now = last.replace(tzinfo=None), now.replace(tzinfo=None)
    remaining = seconds - (now - last).total_seconds()
    if remaining <= 0:
        return True
    context.output.line(f"Cooling down {remaining:.0f} s after the previous run.")
    deadline = time.monotonic() + remaining
    while (left := deadline - time.monotonic()) > 0:
        if context.cancelled():
            return False
        time.sleep(min(1.0, left))
    return True


def freeweight_suite_run(context: JobContext) -> Outcome:
    """One FreeWeight suite run, capped, followed to its end (module docstring)."""
    params = context.job.params
    which = _which(context)
    executable = executable_for(context.settings, "freeweight", which=which)
    if executable is None:
        return Outcome("failed", "FreeWeight is not installed: set [apps.freeweight] executable.")
    host = context.settings.host
    wrapper = which("systemd-run")
    if wrapper is None:
        return Outcome(
            "failed",
            "ADR-0119: a FreeWeight run started by the console runs under the host memory cap "
            f"([host] memory_max = {host.memory_max}), and systemd-run is not on PATH to apply it. "
            "The run was not started.",
        )
    argv = [*_capped(context, wrapper, executable), "run", "start"]
    argv += ["--model", str(params["model"]), "--suite", str(params["suite"]), "--json"]
    if params.get("label"):
        argv += ["--label", str(params["label"])]
    if params.get("adapter"):
        # One more argument to the same command: an adapter run is a run, and FreeWeight refuses an
        # adapter it cannot serve by name (ADR-0058, ADR-0140). The console decides nothing here.
        argv += ["--adapter", str(params["adapter"])]
    if params.get("allow_prompt_override"):
        argv.append("--allow-prompt-override")
    if not _cooled_down(context, int(params.get("cooldown_seconds") or 0)):
        return Outcome("cancelled", "the run was cancelled during its cooldown")
    started = time.monotonic()
    result = _stream(context, argv, timeout_seconds=SUITE_RUN_TIMEOUT_SECONDS)
    if result.returncode == _RUN_SLOT_TAKEN and not (result.cancelled or result.timed_out):
        run_id = run_id_in(context.output.text())
        if run_id is None:
            return Outcome(
                "failed",
                "FreeWeight said another run holds the machine and named no run to follow.",
            )
        remaining = max(SUITE_RUN_TIMEOUT_SECONDS - (time.monotonic() - started), 60.0)
        wait = [executable, "run", "wait", run_id, "--json", "--timeout", f"{remaining:.0f}"]
        result = _stream(context, wait, timeout_seconds=remaining + 60.0)
    if result.cancelled or result.returncode == _RUN_CANCELLED:
        return Outcome("cancelled", "the run stopped on the operator's cancel")
    if result.timed_out:
        return Outcome("failed", "the run did not finish within 12 hours and was stopped")
    if result.ok:
        return Outcome("completed")
    return Outcome("failed", f"freeweight exited {result.returncode}")


def backup(context: JobContext) -> Outcome:
    """Every named application's own ``db backup``; WeightRoomGym's own in-process."""
    failed: list[str] = []
    runner = context.services.runner or run_command
    for app in context.job.params["apps"]:
        if context.cancelled():
            return Outcome("cancelled", "cancelled between backups")
        try:
            if app == "weightroom":
                result = run_self_curated(
                    context.database,
                    "backup",
                    backup_retention=context.settings.storage.backup_retention,
                )
            else:
                result = run_curated(
                    context.settings, context.services.controller, app, "backup", runner=runner
                )
        except AppNotInstalled:
            context.output.line(f"{app}: not installed; skipped")
            continue
        except SuiteError as exc:
            context.output.line(f"{app}: {exc.message}")
            failed.append(app)
            continue
        if result.ok:
            context.output.line(f"{app}: backed up — {_brief(result.output)}")
        else:
            context.output.line(f"{app}: failed — {result.error}")
            failed.append(app)
    if failed:
        return Outcome("failed", f"no backup of {', '.join(failed)}")
    return Outcome("completed")


def model_refresh(context: JobContext) -> Outcome:
    """``models refresh`` on each named application, then the catalog join."""
    failed: list[str] = []
    runner = context.services.runner or run_command
    which = _which(context)
    for app in context.job.params["apps"]:
        if context.cancelled():
            return Outcome("cancelled", "cancelled between refreshes")
        executable = executable_for(context.settings, app, which=which)
        if executable is None:
            context.output.line(f"{app}: not installed; skipped")
            continue
        result = runner(
            [executable, "models", "refresh", "--json"],
            child_environment(),
            _REFRESH_TIMEOUT_SECONDS,
        )
        if result.ok:
            context.output.line(f"{app}: {_brief(result.stdout)}")
        else:
            context.output.line(f"{app}: failed — {result.failure_text}")
            failed.append(app)
    entries = catalog_entries(
        context.settings,
        context.database,
        urls=context.services.urls,
        monotonic=time.monotonic(),
        ollama_client=context.services.ollama_http,
    )
    context.output.line(f"catalog: {len(entries)} model(s) joined across FreeWeight and LoadCoach")
    if failed:
        return Outcome("failed", f"models refresh failed on {', '.join(failed)}")
    return Outcome("completed")


def _trim_freeweight(context: JobContext, older_than_days: int) -> str | None:
    """FreeWeight's own deletion of runs before the cutoff; the failure text, or ``None``."""
    selector = (context.now() - timedelta(days=older_than_days)).isoformat()
    client = context.services.http
    preview = delete_results(
        context.settings, client, "freeweight", scope="before", selector=selector
    )
    if not preview.ok:
        context.output.line(f"freeweight: {preview.error}")
        return preview.error
    answer: Mapping[str, Any] = preview.output if isinstance(preview.output, dict) else {}
    runs, token = answer.get("run_count"), answer.get("token")
    if not runs:
        context.output.line(f"freeweight: no runs created before {selector}")
        return None
    if not isinstance(token, str) or not token:
        context.output.line("freeweight: its deletion preview carried no token")
        return "FreeWeight's deletion preview carried no token"
    done = delete_results(
        context.settings,
        client,
        "freeweight",
        scope="before",
        selector=selector,
        token=token,
        typed=selector,
    )
    if not done.ok:
        context.output.line(f"freeweight: {done.error}")
        return done.error
    context.output.line(
        f"freeweight: {runs} run(s) created before {selector} deleted by FreeWeight"
    )
    return None


def retention_trim(context: JobContext) -> Outcome:
    """WeightRoomGym's own retention, and FreeWeight's when asked (module docstring)."""
    now = context.now()
    params = context.job.params
    removed = trim_finished_jobs(context.database, now=now)
    context.output.line(
        f"weightroom: {removed} finished job row(s) older than {FINISHED_RETENTION_DAYS} days "
        "removed; their audit rows stay"
    )
    days = int(params["guarded_backup_days"])
    if days == 0:
        context.output.line(
            "weightroom: guarded-write backups kept for ever (guarded_backup_days 0)"
        )
    else:
        cutoff = now - timedelta(days=days)
        gone = 0
        for app in APPLICATIONS:
            for one in list_backups(app):
                if one.modified_at < cutoff:
                    one.path.unlink(missing_ok=True)
                    gone += 1
        context.output.line(
            f"weightroom: {gone} guarded-write backup(s) older than {days} days removed "
            "(ADR-0134 rule 3)"
        )
    failure = None
    older = params["freeweight_older_than_days"]
    if older is None:
        context.output.line("freeweight: not trimmed (freeweight_older_than_days is not set)")
    elif context.cancelled():
        return Outcome("cancelled", "cancelled before FreeWeight's deletion")
    else:
        failure = _trim_freeweight(context, int(older))
    context.output.line(
        "loadcoach, promptcadence: trim their own content inside their own processes "
        "(storage.content_retention_hours); ideapress keeps everything"
    )
    return Outcome("failed", failure) if failure else Outcome("completed")


def docs_index(context: JobContext) -> Outcome:
    """Rebuild the documentation search index."""
    try:
        root = resolve_docs_root(context.settings)
    except DocsRootMissing as exc:
        return Outcome("failed", exc.message)
    count = rebuild_index(context.database, root)
    context.output.line(f"indexed {count} document(s) from {root}")
    return Outcome("completed")


EXECUTORS: Final[dict[str, Executor]] = {
    "freeweight_suite_run": freeweight_suite_run,
    "freeweight_goal_calibrate": freeweight_goal_calibrate,
    "retention_trim": retention_trim,
    "backup": backup,
    "model_refresh": model_refresh,
    "docs_index": docs_index,
    "self_restore": hand_off,
}
"""Every kind in :data:`~weightroom.domain.jobs.JOB_KINDS`, and nothing else (a test holds it)."""
