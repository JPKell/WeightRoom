"""weightroom.services.doctor — one pass over the host, in the words of the documents.

``wr-gym doctor`` and the Doctor page answer one question per rule: *is this machine set up the
way the suite's own documents say it should be?* Every rule names the document it comes from,
shows the evidence it read, and — where there is a fix — **prints the command rather than running
it**. Nothing here writes anything, and nothing here is root: ``MEMORY_SAFETY.md`` §2.1 edits a
file under ``/etc``, and a console reachable from the LAN does not get to do that
([ADR-0125](../../../docs/adr/0125-weightroom-drives-the-applications-through-systemd-user-units-it-writes.md)
rules 4–5).

The rubric is ``MEMORY_SAFETY.md`` §2.1, §2.2 and §6, and ``LAN_ACCESS.md`` §4 and §5, plus the
things this console already knows and would otherwise only show one page at a time: whether each
application's version and schema revision are in the range it speaks to, whether the certificate
is near expiry, whether the session lingers, whether the polkit rule is in.

Every reading is a fact this console can obtain **without asking anything of root and without
starting anything**. Where a fact cannot be read at all, the finding is ``unknown`` and says so:
*not read* and *not configured* are different, and reporting the first as the second is how a
checklist stops being believed.
"""

from __future__ import annotations

import getpass
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from weightroom.config import APPLICATIONS, LOOPBACK_HOSTS, data_dir
from weightroom.domain.ollama import APPLY_SCRIPT
from weightroom.domain.units import MEMORY_CAPPED, unit_name
from weightroom.services.apps import AppUnreachable, app_health
from weightroom.services.ollama import POLKIT_INSTALL_COMMAND, POLKIT_RULE_PATH, ollama_report
from weightroom.services.processes import UnitUnsupported

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import httpx

    from weightroom.config import Settings
    from weightroom.services.apps import AppView
    from weightroom.services.database import Database
    from weightroom.services.processes import SystemdController
    from weightroom.services.settings_forms import SettingsForm
    from weightroom.services.tls import TlsStatus

__all__ = [
    "CADDY_MARKER",
    "MEMORY_PROPERTIES",
    "MINIMUM_FREE_BYTES",
    "SEVERITIES",
    "Finding",
    "Report",
    "diagnose",
    "unit_cap_findings",
]

SEVERITIES: Final[tuple[str, ...]] = ("failure", "warning", "notice", "unknown", "ok")
"""Worst first; the report sorts by this so the page's first line is the worst line."""

MEMORY_PROPERTIES: Final[tuple[str, ...]] = ("MemoryHigh", "MemoryMax", "MemorySwapMax")
"""``MEMORY_SAFETY.md`` §2.2's three lines, which ``wr-gym units sync`` writes."""

MINIMUM_FREE_BYTES: Final = 5 * 1024**3
"""Below this under a data root, the finding is a warning.

Five gigabytes is not a measured threshold and does not pretend to be: it is roughly one model
pull plus a database backup, which is what the operator is about to be unable to do.
"""

CADDY_MARKER: Final = "Caddy fronts it at"
"""The comment the retired ``expose_on_lan.sh`` appended to each application's ``config.toml``.

The marker rather than a heuristic about ``[server]`` blocks: the script wrote this exact line
and nothing else does, so the rule has no false positives and needs no judgement.
"""

_TLS_WARNING_DAYS: Final = 30


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule's answer.

    Attributes:
        rule: A stable identifier (``memory.ollama.MemoryMax``), for a script that greps.
        severity: One of :data:`SEVERITIES`.
        summary: One sentence, in the operator's terms.
        evidence: What was actually read, so the operator can check the conclusion.
        command: The fix, to be **printed** and never run; ``""`` when there is nothing to run.
        document: Where the rule comes from (``MEMORY_SAFETY.md §2.1``).
        app: The application concerned, or ``""``.
    """

    rule: str
    severity: str
    summary: str
    evidence: str = ""
    command: str = ""
    document: str = ""
    app: str = ""

    def as_json(self) -> dict[str, str]:
        """The wire shape."""
        return {
            "rule": self.rule,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "command": self.command,
            "document": self.document,
            "app": self.app,
        }


@dataclass(frozen=True, slots=True)
class Report:
    """Every finding, worst first."""

    findings: tuple[Finding, ...]

    @property
    def counts(self) -> dict[str, int]:
        """How many findings of each severity."""
        return {
            severity: sum(1 for one in self.findings if one.severity == severity)
            for severity in SEVERITIES
        }

    @property
    def healthy(self) -> bool:
        """Whether nothing failed and nothing warned; a notice is not a problem."""
        counts = self.counts
        return counts["failure"] == 0 and counts["warning"] == 0

    @property
    def worst(self) -> str:
        """The worst severity present, or ``ok`` for a clean machine."""
        counts = self.counts
        return next((one for one in SEVERITIES if counts[one]), "ok")

    def as_json(self) -> dict[str, Any]:
        """The ``GET /doctor`` shape."""
        return {
            "healthy": self.healthy,
            "worst": self.worst,
            "counts": self.counts,
            "findings": [one.as_json() for one in self.findings],
        }


def _ollama_findings(
    settings: Settings,
    *,
    controller: SystemdController,
    database: Database | None,
    client: httpx.Client | None,
) -> list[Finding]:
    """``MEMORY_SAFETY.md`` §2.1 and ``LAN_ACCESS.md`` §5, from the same one ``systemctl show``."""
    report = ollama_report(
        settings, controller=controller, client=client, database=database, residency=False
    )
    findings = [
        Finding(
            rule=f"memory.ollama.{one.key}",
            severity={"pass": "ok", "fail": "failure"}.get(one.outcome, "unknown"),
            summary=one.why if one.outcome != "pass" else f"{one.key} is as §2.1 asks.",
            evidence=f"found {one.found}, expected {one.expected}",
            command="" if one.outcome == "pass" else APPLY_SCRIPT,
            document="MEMORY_SAFETY.md §2.1",
            app="ollama",
        )
        for one in report.findings
    ]
    host = _ollama_host(report.properties)
    if host is not None:
        listening_wide = host.split(":", 1)[0] in {"0.0.0.0", "::", "*"}  # noqa: S104 — a read
        findings.append(
            Finding(
                rule="lan.ollama_host",
                severity="notice" if listening_wide else "ok",
                summary=(
                    "Ollama listens on the LAN, unauthenticated. That is the operator's daemon "
                    "and the operator's choice; it is the one thing besides this console that "
                    "answers from another room."
                    if listening_wide
                    else "Ollama listens on loopback only."
                ),
                evidence=f"OLLAMA_HOST={host}",
                command=(
                    "# LAN_ACCESS.md §5: set OLLAMA_HOST=127.0.0.1:11434 in the override, then\n"
                    "sudo systemctl edit ollama.service && "
                    "sudo systemctl restart ollama.service"
                )
                if listening_wide
                else "",
                document="LAN_ACCESS.md §5",
                app="ollama",
            )
        )
    findings.append(
        Finding(
            rule="polkit.ollama_restart",
            severity={"permitted": "ok", "not_permitted": "notice"}.get(report.grant, "unknown"),
            summary={
                "permitted": "Restarting Ollama from the console is permitted.",
                "not_permitted": "Restarting Ollama from the console was refused by polkit.",
            }.get(
                report.grant,
                "Whether the console may restart Ollama is not yet known — nothing has been "
                "tried, and polkit will not answer the question in advance (row W2).",
            ),
            evidence=f"rule file {POLKIT_RULE_PATH}",
            command="" if report.grant == "permitted" else POLKIT_INSTALL_COMMAND,
            document="ADR-0125 rules 4–5",
            app="ollama",
        )
    )
    return findings


def _ollama_host(properties: Mapping[str, str]) -> str | None:
    """``OLLAMA_HOST`` from the unit's environment, or ``None`` when it was not read."""
    from weightroom.domain.ollama import environment_of

    if not properties:
        return None
    return environment_of(dict(properties)).get("OLLAMA_HOST", "127.0.0.1:11434")


def unit_cap_findings(settings: Settings, *, controller: SystemdController) -> list[Finding]:
    """``MEMORY_SAFETY.md`` §2.2: each application's unit carries the three ``Memory*`` lines.

    Public since row WX3, which shows the same three lines on the ``/llamacpp`` pane. It is the
    same function rather than a second reading of the same properties so that the doctor and that
    page cannot come to different conclusions about whether a unit is capped.
    """
    findings = []
    # `MEMORY_SAFETY.md` §2.2 and ADR-0125 rule 1 cap the two units that launch `llama-server`,
    # not all four: IdeaPress and PromptCadence hold no model in their own cgroup, and flagging
    # their units would be a permanent red line the operator is right to ignore — which is how a
    # checklist stops being read (found on the reference machine at row W4).
    for app in sorted(MEMORY_CAPPED):
        unit = unit_name(app)
        try:
            properties = controller.properties(unit, MEMORY_PROPERTIES, scope="user")
        except (UnitUnsupported, Exception):  # noqa: BLE001 — an absent unit is a fact, not a crash
            findings.append(
                Finding(
                    rule=f"memory.unit.{app}",
                    severity="unknown",
                    summary=f"{unit} could not be read, so its memory cap is not known.",
                    evidence=f"systemctl --user show {unit}",
                    command="wr-gym units sync",
                    document="MEMORY_SAFETY.md §2.2",
                    app=app,
                )
            )
            continue
        missing = [
            name for name in MEMORY_PROPERTIES if not _capped(name, properties.get(name, ""))
        ]
        findings.append(
            Finding(
                rule=f"memory.unit.{app}",
                severity="failure" if missing else "ok",
                summary=(
                    f"{unit} does not cap memory ({', '.join(missing)}), so a model server it "
                    f"launches can take the machine down with it."
                    if missing
                    else f"{unit} carries the three §2.2 lines."
                ),
                evidence=", ".join(
                    f"{name}={properties.get(name, '?')}" for name in MEMORY_PROPERTIES
                ),
                command="wr-gym units sync" if missing else "",
                document="MEMORY_SAFETY.md §2.2",
                app=app,
            )
        )
    return findings


def _capped(name: str, value: str) -> bool:
    """Whether one ``Memory*`` property actually caps anything."""
    from weightroom.domain.ollama import parse_bytes

    text = value.strip()
    if name == "MemorySwapMax":
        return text == "0"
    parsed = parse_bytes(text)
    return parsed is not None and parsed > 0


def _token_scope_findings(settings: Settings) -> list[Finding]:
    """ADR-0130: the console's own token on each application carries ``admin``.

    An install made before that record keeps a ``write`` token, and the first symptom is a
    settings write refused in the application's own words. This finds it first.
    """
    from weightroom.services.setup import TOKEN_SCOPES
    from weightroom.services.tokens import TokensUnsupported, list_tokens

    findings = []
    for app, wanted in TOKEN_SCOPES.items():
        try:
            records = list_tokens(settings, app)
        except (TokensUnsupported, Exception):  # noqa: BLE001 — an unreadable list is unknown
            findings.append(
                Finding(
                    rule=f"token.scope.{app}",
                    severity="unknown",
                    summary=f"{app}'s token list could not be read.",
                    evidence=f"{app} token list --json",
                    document="ADR-0130",
                    app=app,
                )
            )
            continue
        mine = next((one for one in records if one.name == "weightroom" and not one.revoked), None)
        held = set(_scopes(mine.scope)) if mine is not None else set()
        needed = set(_scopes(wanted))
        missing = sorted(needed - held)
        findings.append(
            Finding(
                rule=f"token.scope.{app}",
                severity="ok" if mine is not None and not missing else "warning",
                summary=(
                    f"WeightRoomGym has no active token on {app}, so its runtime settings cannot "
                    f"be changed from the console."
                    if mine is None
                    else f"WeightRoomGym's token on {app} lacks {', '.join(missing)}; a runtime "
                    f"settings write is refused (ADR-0130)."
                    if missing
                    else f"WeightRoomGym's token on {app} carries {wanted}."
                ),
                evidence=f"scope {mine.scope!r}"
                if mine is not None
                else "no token named weightroom",
                command=(
                    f"{app} token revoke weightroom\n"
                    f"{app} token create weightroom --scope {wanted} --json"
                )
                if mine is None or missing
                else "",
                document="ADR-0130",
                app=app,
            )
        )
    return findings


def _scopes(text: str) -> list[str]:
    """One application's scope string, however it spells the separator."""
    return [part.strip() for part in text.replace(",", " ").split() if part.strip()]


def _bind_findings(forms: Mapping[str, SettingsForm]) -> list[Finding]:
    """``LAN_ACCESS.md`` §1: every application stays on loopback; only the console is exposed."""
    findings = []
    for app, form in forms.items():
        if app == "weightroom":
            continue
        field = form.field_for("server.host")
        if field is None:
            continue
        host = str(field.value or "")
        loopback = host in LOOPBACK_HOSTS or not host
        findings.append(
            Finding(
                rule=f"lan.bind.{app}",
                severity="ok" if loopback else "warning",
                summary=(
                    f"{app} is bound off loopback. LAN_ACCESS.md §1 puts one service on the LAN "
                    f"— this console — and leaves the four behind it."
                    if not loopback
                    else f"{app} is on loopback."
                ),
                evidence=f"server.host = {host!r} ({field.source})",
                command=f"# on /apps/{app}/settings, or in {form.config_path}"
                if not loopback
                else "",
                document="LAN_ACCESS.md §1",
                app=app,
            )
        )
    return findings


def _caddy_findings(forms: Mapping[str, SettingsForm]) -> list[Finding]:
    """The ``[server]`` block the retired ``expose_on_lan.sh`` appended (LAN_ACCESS.md, W0)."""
    findings = []
    for app, form in forms.items():
        if CADDY_MARKER not in form.raw_toml:
            continue
        findings.append(
            Finding(
                rule=f"lan.caddy_leftover.{app}",
                severity="notice",
                summary=(
                    f"{app}'s configuration still carries the [server] block the retired "
                    f"expose_on_lan.sh appended for Caddy. It is harmless and it is stale — "
                    f"WeightRoomGym terminates TLS now (ADR-0126)."
                ),
                evidence=f"{form.config_path} contains {CADDY_MARKER!r}",
                command=f"# review and remove the block on /apps/{app}/settings/raw",
                document="LAN_ACCESS.md",
                app=app,
            )
        )
    return findings


def _version_findings(views: Sequence[AppView]) -> list[Finding]:
    """Spec §19: each application's version is inside the range this console speaks to."""
    findings = []
    for view in views:
        if not view.installed:
            findings.append(
                Finding(
                    rule=f"version.{view.name}",
                    severity="notice",
                    summary=f"{view.name} is not installed.",
                    evidence=f"no executable for {view.name}",
                    command=f"# set [apps.{view.name}] executable, then: wr-gym units sync",
                    document="spec §19",
                    app=view.name,
                )
            )
            continue
        if view.verdict == "unreadable":
            findings.append(
                Finding(
                    rule=f"version.{view.name}",
                    severity="unknown",
                    summary=f"{view.name}'s version was not read; it is not running.",
                    evidence=f"unit {view.unit_state}",
                    document="spec §19",
                    app=view.name,
                )
            )
            continue
        ok = view.verdict == "ok"
        findings.append(
            Finding(
                rule=f"version.{view.name}",
                severity="ok" if ok else "warning",
                summary=(
                    f"{view.name} {view.version} is outside the range this console speaks to; "
                    f"its pages degrade by name rather than guess."
                    if not ok
                    else f"{view.name} {view.version} is in range."
                ),
                evidence=f"{view.version} against {view.supported_range}",
                command=f"# upgrade {view.name}, or upgrade wr-gym" if not ok else "",
                document="spec §19",
                app=view.name,
            )
        )
    return findings


def _promptcadence_loadcoach_findings(
    settings: Settings, views: Sequence[AppView], *, http: httpx.Client | None
) -> list[Finding]:
    """PromptCadence's own check that LoadCoach answers and accepts its token, on its card.

    Read from PromptCadence's ``/api/v1/health`` — the ``loadcoach`` component's
    ``data.token_accepted`` (``promptcadence`` ≥ the W10 build; W6 §8 item 4) — never re-derived
    here: the token PromptCadence presents is the one that matters, and only it can present it.
    """
    view = next((one for one in views if one.name == "promptcadence"), None)
    if view is None or not view.installed:
        return []
    document = "spec §7.6; PromptCadence api.md §1"
    if http is None or not view.running or view.verdict == "unreadable":
        return [
            Finding(
                rule="promptcadence.loadcoach_token",
                severity="unknown",
                summary="PromptCadence's LoadCoach token check was not read; it is not running.",
                evidence=f"unit {view.unit_state}",
                document=document,
                app="promptcadence",
            )
        ]
    try:
        body = app_health(settings, "promptcadence", view, client=http)
    except AppUnreachable as exc:
        return [
            Finding(
                rule="promptcadence.loadcoach_token",
                severity="unknown",
                summary="PromptCadence's health did not answer, so its LoadCoach check is unread.",
                evidence=exc.message,
                document=document,
                app="promptcadence",
            )
        ]
    components = body.get("components") if isinstance(body, Mapping) else None
    component = next(
        (
            one
            for one in (components or [])
            if isinstance(one, Mapping) and one.get("name") == "loadcoach"
        ),
        None,
    )
    data = component.get("data") if isinstance(component, Mapping) else None
    accepted = data.get("token_accepted") if isinstance(data, Mapping) else None
    detail = str(component.get("detail") or "") if isinstance(component, Mapping) else ""
    if component is None or accepted is None:
        return [
            Finding(
                rule="promptcadence.loadcoach_token",
                severity="unknown",
                summary=(
                    "PromptCadence did not say whether LoadCoach accepts its token"
                    + (": LoadCoach did not answer it." if component is not None else ".")
                ),
                evidence=detail or "no loadcoach component in its health",
                command="" if component is not None else "# upgrade promptcadence",
                document=document,
                app="promptcadence",
            )
        ]
    if accepted is True:
        return [
            Finding(
                rule="promptcadence.loadcoach_token",
                severity="ok",
                summary="LoadCoach answers PromptCadence and accepts its token.",
                evidence=detail,
                document=document,
                app="promptcadence",
            )
        ]
    return [
        Finding(
            rule="promptcadence.loadcoach_token",
            severity="failure",
            summary=(
                "LoadCoach refuses the token PromptCadence presents; nothing it runs can reach "
                "a model."
            ),
            evidence=detail,
            command=(
                "# re-issue it from /apps/promptcadence/tokens, or: "
                "loadcoach token create promptcadence --scope write"
            ),
            document=document,
            app="promptcadence",
        )
    ]


def _revision_findings(settings: Settings, database: Database | None) -> list[Finding]:
    """Each application's schema revision is one this console knows (``SCHEMA_UNKNOWN``)."""
    if database is None:
        return []
    from weightroom.services.db_reader import (
        effective_database_url,
        known_revision,
        open_read_only,
        read_revision,
    )

    findings = []
    for app in APPLICATIONS:
        url, reason = effective_database_url(settings, app)
        if url is None:
            findings.append(
                Finding(
                    rule=f"revision.{app}",
                    severity="unknown",
                    summary=f"{app}'s database could not be located.",
                    evidence=str(reason),
                    document="spec §19",
                    app=app,
                )
            )
            continue
        other = open_read_only(url)
        try:
            revision = read_revision(other)
            known = known_revision(database, app, revision)
        finally:
            other.dispose()
        findings.append(
            Finding(
                rule=f"revision.{app}",
                severity="ok" if known else "warning",
                summary=(
                    f"{app}'s schema is at {revision or 'no revision'}, which this console does "
                    f"not know; its pages degrade by name."
                    if not known
                    else f"{app}'s schema revision {revision} is known."
                ),
                evidence=f"alembic_version = {revision}",
                command=f"# upgrade wr-gym, or: {app} db upgrade" if not known else "",
                document="spec §19",
                app=app,
            )
        )
    return findings


def _tls_finding(settings: Settings, tls: TlsStatus | None) -> list[Finding]:
    """The leaf certificate renews itself; this says so before it is a surprise."""
    if tls is None:
        return [
            Finding(
                rule="tls.expiry",
                severity="unknown",
                summary="No certificate status was established for this process.",
                document="ADR-0126",
            )
        ]
    warn_below = max(settings.tls.renew_before_days, _TLS_WARNING_DAYS)
    expiring = tls.days_left <= warn_below
    return [
        Finding(
            rule="tls.expiry",
            severity="warning" if tls.days_left <= 0 else ("notice" if expiring else "ok"),
            summary=(
                f"The console's certificate expires in {tls.days_left} days. It renews itself at "
                f"startup inside {settings.tls.renew_before_days} days; the root is unchanged, so "
                f"no client needs to re-trust."
                if expiring
                else f"The console's certificate is good for {tls.days_left} days."
            ),
            evidence=f"leaf not_after {tls.leaf_not_after.date().isoformat()}",
            command="wr-gym tls renew" if expiring else "",
            document="LAN_ACCESS.md §4",
        )
    ]


def _linger_finding(controller: SystemdController, *, user: str) -> list[Finding]:
    """ADR-0125 rule 2: without lingering, every unit stops at logout."""
    try:
        lingers = controller.linger_enabled(user)
    except UnitUnsupported:
        lingers = None
    return [
        Finding(
            rule="linger",
            severity={True: "ok", False: "failure"}.get(bool(lingers), "unknown")
            if lingers is not None
            else "unknown",
            summary=(
                f"{user} does not linger, so every application stops at logout."
                if lingers is False
                else f"{user} lingers; the units survive a logout."
                if lingers
                else "Whether this session lingers could not be read."
            ),
            evidence=f"loginctl show-user {user} --property=Linger",
            command=f"loginctl enable-linger {user}" if lingers is not True else "",
            document="ADR-0125 rule 2",
        )
    ]


def _disk_findings(settings: Settings, forms: Mapping[str, SettingsForm]) -> list[Finding]:
    """Free space under each data root, the console's own included."""
    roots: dict[str, Path] = {"weightroom": data_dir()}
    for app, form in forms.items():
        if app == "weightroom":
            continue
        root = _sqlite_parent(form)
        if root is not None:
            roots[app] = root
    findings = []
    seen: set[Path] = set()
    for app, root in roots.items():
        existing = _nearest_existing(root)
        if existing is None or existing in seen:
            continue
        seen.add(existing)
        usage = shutil.disk_usage(existing)
        low = usage.free < MINIMUM_FREE_BYTES
        findings.append(
            Finding(
                rule=f"disk.{app}",
                severity="warning" if low else "ok",
                summary=(
                    f"{root} has under {MINIMUM_FREE_BYTES // 1024**3} GB free — about one model "
                    f"pull and one backup away from failing."
                    if low
                    else f"{root} has {usage.free // 1024**3} GB free."
                ),
                evidence=f"{usage.free} bytes free of {usage.total} on {existing}",
                command=f"df -h {existing}" if low else "",
                document="spec §15",
                app=app,
            )
        )
    return findings


def _sqlite_parent(form: SettingsForm) -> Path | None:
    """The directory an application's SQLite database lives in, from its own settings."""
    field = form.field_for("storage.database_url")
    url = str((field.value if field else "") or "")
    if not url.startswith("sqlite:"):
        return None
    _scheme, _sep, rest = url.partition(":///")
    return Path(rest).parent if rest else None


def _nearest_existing(path: Path) -> Path | None:
    """``path`` or its nearest existing ancestor, for a ``statvfs`` that will not raise."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def diagnose(
    settings: Settings,
    *,
    controller: SystemdController,
    forms: Mapping[str, SettingsForm],
    views: Sequence[AppView] = (),
    tls: TlsStatus | None = None,
    database: Database | None = None,
    client: httpx.Client | None = None,
    http: httpx.Client | None = None,
    user: str | None = None,
) -> Report:
    """Run every rule and return the findings, worst first.

    Args:
        settings: The validated settings.
        controller: The systemd boundary.
        forms: Each application's settings form — where the bind, the database URL and the file's
            own text are read from, so the doctor asks the applications the same way every other
            page does rather than growing a second reader.
        views: The applications' views, for the version rules.
        tls: The certificate status.
        database: The console's own database, for the known-revision and polkit-grant rules.
        client: An HTTP client; unused by the rules that read Ollama's unit, present for the ones
            that may later need it.
        http: The client the applications are reached with, for PromptCadence's LoadCoach token
            check; ``None`` leaves that finding ``unknown``.
        user: Whose lingering to check; the process owner by default.

    Returns:
        The report. Never raises: a rule that cannot read its fact answers ``unknown``.
    """
    owner = user if user is not None else getpass.getuser()
    findings: list[Finding] = []
    findings.extend(
        _ollama_findings(settings, controller=controller, database=database, client=client)
    )
    findings.extend(unit_cap_findings(settings, controller=controller))
    findings.extend(_bind_findings(forms))
    findings.extend(_token_scope_findings(settings))
    findings.extend(_caddy_findings(forms))
    findings.extend(_version_findings(views))
    findings.extend(_promptcadence_loadcoach_findings(settings, views, http=http))
    findings.extend(_revision_findings(settings, database))
    findings.extend(_tls_finding(settings, tls))
    findings.extend(_linger_finding(controller, user=owner))
    findings.extend(_disk_findings(settings, forms))
    return Report(findings=tuple(_sorted(findings)))


def _sorted(findings: Iterable[Finding]) -> list[Finding]:
    order = {severity: index for index, severity in enumerate(SEVERITIES)}
    return sorted(findings, key=lambda one: (order.get(one.severity, len(order)), one.rule))
