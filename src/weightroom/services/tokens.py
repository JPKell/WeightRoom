"""weightroom.services.tokens — each application's API tokens, through its own CLI.

Spec §7.3's *Tokens* page. There is no HTTP surface for this in any application — a token is
minted in *local* mode against the application's own database — so the console does what an
operator at the terminal does: it runs ``<app> token list|create|revoke --json`` with the same
subprocess discipline as everything else here (explicit argv, an allowlisted environment, a
timeout, a capped output).

**The secret is shown once and never stored.** ``token create --json`` prints the token in its
answer; this module hands it to the page that asked for it and keeps no copy — not in the
database, not in the audit row (``params`` is redacted regardless), not in a log. A token that is
lost is revoked and re-minted, which is the only honest recovery.

Two of the four have this surface, and the page says so for the other two rather than inventing
one: **LoadCoach** and **PromptCadence** carry a ``token`` verb; **FreeWeight**'s bearer tokens
are a configuration key (``auth.tokens``, a security key on its settings page); **IdeaPress** has
no token surface at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Final

from baseaicore import SuiteError

from weightroom.services.processes import child_environment, executable_for, run_command

if TYPE_CHECKING:
    from collections.abc import Sequence

    from weightroom.config import Settings
    from weightroom.services.processes import Runner

__all__ = [
    "CONFIG_TOKEN_APPS",
    "MULTI_SCOPE_APPS",
    "NO_TOKEN_APPS",
    "SCOPES_BY_APP",
    "TOKEN_APPS",
    "TOKEN_TIMEOUT_SECONDS",
    "TokenRecord",
    "TokensUnsupported",
    "create_token",
    "list_tokens",
    "revoke_token",
    "token_surface",
]

TOKEN_APPS: Final[frozenset[str]] = frozenset({"loadcoach", "promptcadence"})
"""The applications with a ``token`` CLI verb — the only ones this page can drive."""

SCOPES_BY_APP: Final[dict[str, tuple[str, ...]]] = {
    "loadcoach": ("read", "write", "admin"),
    "promptcadence": ("read", "write", "approve", "admin"),
}
"""Each app's own scope vocabulary (its ``token create --help``), for the page's ``<select>``.

LoadCoach's is cumulative (``--scope`` takes one value; ``admin`` already carries ``write`` and
``read``) — a single-select. PromptCadence's four are independent (ADR-0049 rule 2 deliberately
keeps ``approve`` out of ``write``, and ``admin`` "contains the rest") — a multi-select, joined
with commas the way its own ``--scope`` reads a comma list."""

MULTI_SCOPE_APPS: Final[frozenset[str]] = frozenset({"promptcadence"})
"""Which apps in :data:`SCOPES_BY_APP` take several scopes at once, comma-separated."""

CONFIG_TOKEN_APPS: Final[frozenset[str]] = frozenset({"freeweight"})
"""FreeWeight's tokens are ``auth.tokens`` in its own file, edited on its settings page."""

NO_TOKEN_APPS: Final[frozenset[str]] = frozenset({"ideapress", "weightroom"})
"""No token surface at all. WeightRoomGym's own API is for its own pages (spec §21)."""

TOKEN_TIMEOUT_SECONDS: Final = 30.0


class TokensUnsupported(SuiteError):
    """This application has no token surface for the console to drive."""

    code: ClassVar[str] = "UNIT_UNSUPPORTED"


class TokenCommandFailed(SuiteError):
    """The application's own ``token`` verb refused; its message is carried through."""

    code: ClassVar[str] = "VALIDATION_ERROR"


@dataclass(frozen=True, slots=True)
class TokenRecord:
    """One token as the application lists it — never the secret.

    Attributes:
        name: The operator's name for it, which is also its identity to the application.
        scope: What it may do, in the application's own words.
        created_at: When, as the application printed it.
        expires_at: When it stops working, or ``""``.
        revoked: Whether it has been revoked.
        extra: Every other field the application printed, unread and unrenamed.
    """

    name: str
    scope: str = ""
    created_at: str = ""
    expires_at: str = ""
    revoked: bool = False
    extra: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TokenRecord:
        """Read one record out of an application's JSON, keeping what it says.

        The four applications do not agree on the field names beyond ``name`` — and this console
        does not reconcile them (spec §11 contract 9): the named fields below are read where they
        exist, and everything else is carried in ``extra`` for the page to show as it came.
        """
        known = {
            "name",
            "scope",
            "scopes",
            "created_at",
            "created",
            "expires_at",
            "revoked",
            "revoked_at",
            "active",
        }
        scope = payload.get("scope") or payload.get("scopes") or ""
        return cls(
            name=str(payload.get("name", "")),
            scope=", ".join(scope) if isinstance(scope, (list, tuple)) else str(scope),
            created_at=str(payload.get("created_at") or payload.get("created") or ""),
            expires_at=str(payload.get("expires_at") or ""),
            revoked=_is_revoked(payload),
            extra={key: value for key, value in payload.items() if key not in known} or None,
        )

    def as_json(self) -> dict[str, Any]:
        """The wire shape; never carries a secret, because this object never holds one."""
        return {
            "name": self.name,
            "scope": self.scope,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "extra": self.extra or {},
        }


def _is_revoked(payload: dict[str, Any]) -> bool:
    """Whether one record is revoked, in whichever of the three ways it is said.

    LoadCoach carries `revoked_at`, PromptCadence carries `active`, and a `revoked` boolean is
    the shape this console's own JSON uses. Reading only one of them reports every revoked token
    as live, which is the wrong way round for a credential.
    """
    if "revoked" in payload:
        return bool(payload["revoked"])
    if payload.get("revoked_at"):
        return True
    if "active" in payload:
        return not bool(payload["active"])
    return False


def token_surface(app: str) -> str:
    """What kind of token surface ``app`` has: ``cli``, ``config`` or ``none``."""
    if app in TOKEN_APPS:
        return "cli"
    if app in CONFIG_TOKEN_APPS:
        return "config"
    return "none"


def _run(
    settings: Settings, app: str, argv_tail: Sequence[str], *, runner: Runner = run_command
) -> Any:  # noqa: ANN401 — whatever the application printed
    """Run one ``<app> token …`` verb and parse its JSON.

    Raises:
        TokensUnsupported: The application has no token verb, or is not installed.
        TokenCommandFailed: It ran and refused, with its own message.
    """
    if app not in TOKEN_APPS:
        raise TokensUnsupported(
            f"{app} has no `token` verb; the console does not invent one.",
            details={"app": app, "surface": token_surface(app)},
        )
    executable = executable_for(settings, app)
    if executable is None:
        raise TokensUnsupported(
            f"{app} is not installed, so its tokens cannot be listed or changed.",
            details={"app": app, "surface": "cli"},
        )
    argv = [executable, "token", *argv_tail]
    result = runner(argv, child_environment(), TOKEN_TIMEOUT_SECONDS)
    if not result.ok:
        raise TokenCommandFailed(
            f"{app} refused: {result.failure_text}",
            details={"app": app, "verb": argv_tail[0] if argv_tail else ""},
        )
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise TokenCommandFailed(
            f"{app}'s token verb did not print JSON: {exc}",
            details={"app": app},
        ) from exc


def list_tokens(
    settings: Settings, app: str, *, runner: Runner = run_command
) -> tuple[TokenRecord, ...]:
    """Every token the application knows, revoked ones included, never the secret.

    Raises:
        TokensUnsupported: No token verb, or not installed.
        TokenCommandFailed: The verb refused.
    """
    payload = _run(settings, app, ["list", "--json"], runner=runner)
    rows: Any = payload
    if isinstance(payload, dict):
        # `{"items": […]}` since ADR-0131 (LoadCoach 1.4.0 renamed its `tokens`). The old name
        # is read too, for one console major: the console and the applications upgrade on
        # different days (ADR-0129 rule 3). Records are left as they came (spec §11 contract 9).
        rows = next((payload[key] for key in ("tokens", "items", "results") if key in payload), [])
    if not isinstance(rows, list):
        return ()
    return tuple(TokenRecord.from_payload(row) for row in rows if isinstance(row, dict))


def create_token(
    settings: Settings,
    app: str,
    name: str,
    *,
    scope: str = "read",
    expires_days: int | None = None,
    runner: Runner = run_command,
) -> tuple[TokenRecord, str]:
    """Mint a token and return it with its secret, **once**.

    Args:
        settings: The validated settings.
        app: One of :data:`TOKEN_APPS`.
        name: The token's name, which is also its identity to the application.
        scope: The application's own scope vocabulary, passed through unread.
        expires_days: Days until expiry, where the application accepts it.
        runner: The process-launch boundary, injected.

    Returns:
        The record and the secret. The caller shows the secret once and keeps no copy; nothing in
        this repository writes it anywhere.

    Raises:
        TokensUnsupported: No token verb, or not installed.
        TokenCommandFailed: The verb refused — a taken name, an unknown scope.
    """
    argv = ["create", name, "--scope", scope, "--json"]
    if expires_days is not None:
        argv.extend(["--expires-days", str(expires_days)])
    payload = _run(settings, app, argv, runner=runner)
    if not isinstance(payload, dict):
        raise TokenCommandFailed(
            f"{app} did not print a token record.", details={"app": app, "name": name}
        )
    secret = str(payload.get("token") or payload.get("secret") or "")
    return TokenRecord.from_payload({k: v for k, v in payload.items() if k != "token"}), secret


def revoke_token(settings: Settings, app: str, name: str, *, runner: Runner = run_command) -> None:
    """Revoke the active token with that name.

    Raises:
        TokensUnsupported: No token verb, or not installed.
        TokenCommandFailed: There is no such active token.
    """
    _run(settings, app, ["revoke", name], runner=runner)
