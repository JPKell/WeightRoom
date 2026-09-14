"""weightroom.domain.audit — the closed vocabulary and the redaction rule (data model §2).

``audit_log.action`` is one of :data:`ACTIONS` and nothing else; a test asserts the set and
every writer goes through :func:`weightroom.services.audit.record`, which refuses a name outside
it. ``params`` is redacted here before a row exists: any key shaped like a secret, and any URL
credential, is replaced.
"""

from __future__ import annotations

import re
from typing import Any, Final

__all__ = ["ACTIONS", "ACTORS", "OUTCOMES", "REDACTED", "redact_params"]

ACTIONS: Final[frozenset[str]] = frozenset(
    {
        # Phase 1
        "login",
        "logout",
        "reauth",
        "operator.create",
        "operator.password",
        "tls.rotate",
        "setup.run",
        # Named by data-model.md §2 for later phases; a row's writer arrives with its phase.
        "unit.sync",
        "unit.start",
        "unit.stop",
        "unit.restart",
        "ollama.restart",
        "settings.write",
        # W4. A validation changes nothing, but it launches the application's own loader over
        # operator-supplied text, and the outcome is what the operator wants to find later; the
        # row says `pending`, which is the outcome vocabulary's word for "no state moved".
        "settings.validate",
        # W4. An API token is a credential; its creation and its revocation are both trail
        # entries, and neither row ever carries the secret (`params` is redacted regardless).
        "token.create",
        "token.revoke",
        # W6. Starting, sending to, attaching to and deleting a conversation. The row names the
        # conversation and counts; message text and attachment contents are never in it.
        "chat.create",
        "chat.message",
        "chat.attachment",
        "chat.delete",
        # W6. Granting or denying a PromptCadence approval from a thread: the one chat action that
        # authorises spend or egress, so its row names the trajectory and the request it resolved.
        "chat.approve",
        "chat.deny",
        "db.guarded_write",
        # W7. The console's one SELECT: nothing moves, but what was read, and by whom, is the
        # trail's. A refused statement is a row too.
        "db.query",
        # W7. A guarded write's rolled-back dry run: the count the operator is about to confirm.
        "db.dry_run",
        "db.curated",
        "catalog.pull",
        # W8. Every other catalog action: enabling or disabling a model on one application, a
        # GGUF drop-in, and a catalog delete (the preview and the confirmed removal both — a
        # preview changes nothing but is the row that shows what was about to happen).
        "catalog.enabled",
        "catalog.dropin",
        "catalog.delete",
        "prompt.override",
        # W9. Removing an override, so the application renders its shipped record again.
        "prompt.delete",
        "job.run",
        # W9. Enqueueing a job is a person's action (the run itself is `job.run`, actor `job`);
        # so are cancelling one and changing a schedule's cron, parameters or enabled flag.
        "job.enqueue",
        "job.cancel",
        "job.schedule",
        "alert.ack",
        # WP1. From PromptCadence's tab: submitting and cancelling a trajectory, and granting or
        # denying its pending request — the last two `security` rows, as `chat.approve` is.
        "trajectory.submit",
        "trajectory.cancel",
        "trajectory.approve",
        "trajectory.deny",
        # WP2. From LoadCoach's tab (enabling a model reuses `catalog.enabled`, W8's call): a
        # discovery pass, a warm job, and an explanation — `POST /route` persists its decision.
        "loadcoach.discover",
        "loadcoach.warm",
        # CF4. A measured context fit written into LoadCoach's config.toml (ADR-0149 §1).
        "loadcoach.context_fit_applied",
        "loadcoach.route",
        # WP2 Gate B. Pause, resume and drain (an unconfirmed post is a `pending` row), a job
        # submitted, cancelled or given feedback, and an evidence import.
        "loadcoach.queue_pause",
        "loadcoach.queue_resume",
        "loadcoach.queue_drain",
        "loadcoach.job_submit",
        "loadcoach.job_cancel",
        "loadcoach.job_feedback",
        "loadcoach.evidence_import",
        # WP2 Gate C. A provider registration saved or removed through LoadCoach's API; a removal's
        # preview is a `pending` row, and a changed security key or a removal is a `security` row.
        "loadcoach.provider_save",
        "loadcoach.provider_delete",
        # WP5 Gate B. From IdeaPress's tab: a project created, edited or deleted (the delete's
        # preview is a `pending` row), and a backend's round-trip test.
        "ideapress.project_create",
        "ideapress.project_update",
        "ideapress.project_delete",
        "ideapress.backend_test",
        # WP5 Gate C. The plan run and edited, research run, a stage run and cancelled, a unit
        # revised or resumed, and an export written into the project's directory.
        "ideapress.plan_run",
        "ideapress.plan_edit",
        "ideapress.research_run",
        "ideapress.stage_run",
        "ideapress.stage_cancel",
        "ideapress.unit_revise",
        "ideapress.unit_resume",
        "ideapress.export_write",
        # WX12. A workflow created or saved as a new version through IdeaPress's own API
        # (ADR-0143). One action for both: a save is a save, and which one it was is the
        # `version` in the row's params.
        "ideapress.workflow_save",
        # WP3. From FreeWeight's tab (enabling a model reuses `catalog.enabled`; starting a run is
        # the `job.enqueue` of W9's `freeweight_suite_run`): a discovery pass, a run cancelled or
        # repeated, and the `[provider]` block saved — a `security` row when kind or base_url moved.
        "freeweight.discover",
        "freeweight.run_cancel",
        "freeweight.run_repeat",
        "freeweight.provider_save",
        "freeweight.machine_nickname",
        # WX8. A manifest *draft* written beside an unmanifested artifact (ADR-0145): a
        # proposal nothing registers, so the row records who proposed it and for what base.
        "freeweight.adapter_draft",
        # WP4 Gate A. From FreeWeight's Goals page: a goal created from a pack, forked from a
        # starter, edited (a separating edit's preview is a `pending` row), deleted (its preview a
        # `pending` row) or imported; a wizard draft begun, stepped, saved as a pack or abandoned.
        "freeweight.goal_create",
        "freeweight.goal_fork",
        "freeweight.goal_edit",
        "freeweight.goal_delete",
        "freeweight.goal_import",
        "freeweight.draft_start",
        "freeweight.draft_edit",
        "freeweight.draft_save",
        "freeweight.draft_delete",
        # WP4 Gate B. Calibration samples added (pasted, or a run's promoted), one sample's grades
        # recorded on a calibration set or on a goal run (`failed` when FreeWeight did not answer
        # mid-save). Running the calibration is the `job.enqueue` of `freeweight_goal_calibrate`.
        "freeweight.calibration_samples",
        "freeweight.calibration_grades",
        "freeweight.run_grades",
    }
)
"""The closed action vocabulary."""

ACTORS: Final[frozenset[str]] = frozenset({"operator", "job", "alerts", "cli"})
OUTCOMES: Final[frozenset[str]] = frozenset({"pending", "ok", "failed", "refused"})

REDACTED: Final = "********"
_SECRET_KEY: Final = re.compile(r"(?i)(token|key|secret|password|authorization|cookie)")
_URL_CREDENTIAL: Final = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)([^/@\s]+)@")


def redact_params(value: Any) -> Any:  # noqa: ANN401 — JSON-shaped input, JSON-shaped output
    """Return ``value`` with secret-shaped keys and URL credentials replaced.

    Args:
        value: Any JSON-shaped structure.

    Returns:
        A copy: a mapping key matching ``token|key|secret|password|authorization|cookie`` has its
        value replaced whole; a string carrying ``scheme://user:pass@`` keeps the scheme and the
        host and loses the credential.
    """
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if _SECRET_KEY.search(str(key)) else redact_params(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_params(item) for item in value]
    if isinstance(value, str):
        return _URL_CREDENTIAL.sub(rf"\1{REDACTED}@", value)
    return value
