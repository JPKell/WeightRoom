"""weightroom.services.freeweight_actions — what FreeWeight's tab asks FreeWeight to do (row WP3).

Every call goes through :mod:`~weightroom.services.app_api`, so FreeWeight validates and refuses in
its own words (arc index §2 item 4). Two actions are not here, because they already exist: starting
a run is W9's ``freeweight_suite_run`` job, which runs under ADR-0119's cap and is enqueued through
the jobs route's own helper; enabling a model is W8's ``catalog.set_enabled``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Final

from baseaicore import SuiteError

from weightroom.services.app_api import call
from weightroom.services.freeweight_pages import APP, segment

if TYPE_CHECKING:
    import httpx

    from weightroom.config import Settings

__all__ = [
    "SECURITY_FIELDS",
    "FreeWeightFormInvalid",
    "cancel_run",
    "discover",
    "provider_values",
    "repeat_run",
    "save_provider",
    "set_machine_nickname",
    "touched",
]

_DISCOVER_TIMEOUT_SECONDS: Final = 120.0
"""Discovery asks the provider for every model and its descriptor; LoadCoach's takes as long."""
_ACTION_TIMEOUT_SECONDS: Final = 30.0


def _answer(body: Any) -> dict[str, Any]:  # noqa: ANN401 — the application's JSON body
    return dict(body) if isinstance(body, Mapping) else {}


def discover(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``POST /models/discover``: the added, updated, unchanged and total counts.

    Raises:
        AppRefused: ``PROVIDER_UNAVAILABLE`` and the like, in FreeWeight's words.
        AppUnreachable: It did not answer.
    """
    return _answer(
        call(client, settings, APP, "POST", "models/discover",
             timeout_seconds=_DISCOVER_TIMEOUT_SECONDS)
    )  # fmt: skip


def cancel_run(client: httpx.Client, settings: Settings, run_id: str) -> dict[str, Any]:
    """``POST /runs/{id}/cancel``: the run's new state — ``cancelling`` for one that is running.

    Raises:
        AppRefused: ``409 RUN_NOT_CANCELLABLE`` for a finished run, ``RUN_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    return _answer(
        call(client, settings, APP, "POST", f"runs/{segment(run_id)}/cancel",
             timeout_seconds=_ACTION_TIMEOUT_SECONDS)
    )  # fmt: skip


def repeat_run(
    client: httpx.Client, settings: Settings, run_id: str, *, force: bool, label: str
) -> dict[str, Any]:
    """``POST /runs/{id}/repeat``: a new run with the original's frozen configuration.

    FreeWeight checks this machine against the original's fingerprint first and refuses by name;
    ``force`` proceeds and records the divergence on the new run, where its page shows it.

    Args:
        client: The pooled HTTP client.
        settings: The validated settings.
        run_id: The run to repeat.
        force: Proceed past every blocker, recording the divergence.
        label: A label for the new run; blank takes FreeWeight's default.

    Raises:
        AppRefused: ``REPEAT_REFUSED`` with every blocker in its details, ``RUN_NOT_FOUND``.
        AppUnreachable: It did not answer.
    """
    return _answer(
        call(
            client, settings, APP, "POST", f"runs/{segment(run_id)}/repeat",
            params={"force": "true" if force else None, "label": label.strip() or None},
            timeout_seconds=_ACTION_TIMEOUT_SECONDS,
        )
    )  # fmt: skip


def set_machine_nickname(
    client: httpx.Client, settings: Settings, machine_id: str, *, nickname: str
) -> dict[str, Any]:
    """``PATCH /machines/{id}``: the operator's own label for one machine (row WX7).

    A blank field clears it. The label identifies nothing — FreeWeight still attributes every
    measurement to the fingerprint — so this is the one machine field a console may write.

    Raises:
        AppRefused: ``NOT_FOUND`` when no machine has that ULID, in FreeWeight's words.
        AppUnreachable: It did not answer.
    """
    return _answer(
        call(client, settings, APP, "PATCH", f"machines/{segment(machine_id)}",
             body={"nickname": nickname.strip() or None},
             timeout_seconds=_ACTION_TIMEOUT_SECONDS)
    )  # fmt: skip


# --- Provider -------------------------------------------------------------------------------------

SECURITY_FIELDS: Final[frozenset[str]] = frozenset({"kind", "base_url"})
"""The ``[provider]`` keys whose change asks for the operator's password (spec §7.4): where every
prompt goes. FreeWeight's own ``config schema --json`` names ``provider.base_url`` security-relevant
(its ``CONFIG_ONLY_KEYS``); ``kind`` joins it for the reason LoadCoach's registrations carry it
(row WP2's handoff §2 item 8) — changing it changes which server receives every prompt."""


class FreeWeightFormInvalid(SuiteError):
    """A form field that cannot become what FreeWeight's route takes; nothing was sent."""

    code: ClassVar[str] = "VALIDATION_ERROR"


def provider_values(  # noqa: PLR0913 — one keyword per writable key (ADR-0117)
    *,
    kind: str,
    base_url: str,
    timeout_seconds: str,
    model_directory: str,
    state_dir: str,
    server_path: str,
) -> dict[str, Any]:
    """``PUT /provider``'s values from the form, as FreeWeight's own Provider page sends them.

    Every text key is sent, blank included — a blank optional key removes it from the block, as on
    FreeWeight's page; ``timeout_seconds`` is left out when blank, so the block keeps it.
    FreeWeight validates every value.

    Raises:
        FreeWeightFormInvalid: ``kind`` is blank, or the timeout is not a number.
    """
    if not kind.strip():
        message = "The provider needs a kind: ollama, llamacpp or fake."
        raise FreeWeightFormInvalid(message, details={"field": "kind"})
    values: dict[str, Any] = {
        "kind": kind.strip(),
        "base_url": base_url.strip(),
        "model_directory": model_directory.strip(),
        "state_dir": state_dir.strip(),
        "server_path": server_path.strip(),
    }
    if timeout_seconds.strip():
        try:
            values["timeout_seconds"] = float(timeout_seconds)
        except ValueError as exc:
            message = f"timeout_seconds must be a number of seconds, not {timeout_seconds!r}."
            raise FreeWeightFormInvalid(message, details={"field": "timeout_seconds"}) from exc
    return values


def touched(current: Mapping[str, Any], values: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """``(changed keys, changed security keys)`` between the block as read and the form."""
    changed = sorted(key for key, value in values.items() if current.get(key) != value)
    return changed, sorted(SECURITY_FIELDS.intersection(changed))


def save_provider(
    client: httpx.Client, settings: Settings, values: Mapping[str, Any], *, base_digest: str
) -> dict[str, Any]:
    """``PUT /provider``: FreeWeight writes its block, keeps the ``.bak`` and re-opens its provider.

    Raises:
        AppRefused: ``VALIDATION_ERROR`` naming the key, ``CONFLICT`` when the file changed since
            ``base_digest`` was read, in FreeWeight's words.
        AppUnreachable: It did not answer.
    """
    body = {**values, **({"base_digest": base_digest} if base_digest else {})}
    return _answer(
        call(client, settings, APP, "PUT", "provider", body=body,
             timeout_seconds=_ACTION_TIMEOUT_SECONDS)
    )  # fmt: skip
