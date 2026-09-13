"""weightroom.web.rendering — the one Jinja environment every page renders through.

MirrorWall's environment: the shell, the macros, the tokens and the filters come from the
package; this module supplies what is WeightRoomGym's — the product name, the navigation and the
template directory. Built once and cached.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mirrorwall import create_template_environment

from weightroom.__about__ import __version__
from weightroom.config import APP_LABELS
from weightroom.services.db_reader import cell_text
from weightroom.services.health import APP_STATUS_DOT
from weightroom.services.tls import trust_steps

if TYPE_CHECKING:
    from jinja2 import Environment

    from weightroom.config import Settings
    from weightroom.services.tls import HostIdentity, TlsStatus

__all__ = [
    "CONSOLE_PAGES",
    "CONSOLE_SIDE_NAV",
    "NAV_ITEMS",
    "PILL_TONES",
    "app_side_nav",
    "app_side_nav_stubs",
    "docs_action",
    "pill_status",
    "pill_tone",
    "render",
    "templates",
    "trust_context",
]

_TEMPLATES_DIR = Path(__file__).parent / "templates"

NAV_ITEMS: tuple[dict[str, str], ...] = (
    {"key": "shell", "href": "/", "label": "Overview"},
    {"key": "apps", "href": "/apps", "label": "Applications"},
    {"key": "ollama", "href": "/ollama", "label": "Ollama"},
    {"key": "llamacpp", "href": "/llamacpp", "label": "llama.cpp"},
    {"key": "logs", "href": "/logs", "label": "Logs"},
    {"key": "audit", "href": "/audit", "label": "Audit"},
    {"key": "doctor", "href": "/doctor", "label": "Doctor"},
    {"key": "settings", "href": "/settings", "label": "Settings"},
    {"key": "trust", "href": "/trust", "label": "Trust"},
)

CONSOLE_PAGES: tuple[dict[str, str], ...] = (
    {"label": "Chat", "href": "/chat"},
    {"label": "Docs", "href": "/docs"},
    {"label": "Database", "href": "/database"},
    {"label": "Costs", "href": "/costs"},
    {"label": "Backups", "href": "/backups"},
    {"label": "Jobs", "href": "/jobs"},
)
"""The console's own *tools* — the second section of its left menu (row WX3, which moved them out
of the top bar). A built one carries ``href``; an unbuilt one carries ``phase`` and is left out of
the menu rather than rendered as a link that goes nowhere."""

_APP_PAGES: dict[str, tuple[str, ...]] = {
    "freeweight": (
        "Overview",
        "Models",
        "Runs",
        "Results",
        "Evidence",
        "Goals",
        "Adapters",
        "Prompts",
        "System",
        "Settings",
        "Provider",
        "Logs",
        "Database",
    ),
    "loadcoach": (
        "Overview",
        "Models",
        "Routing",
        "Queue",
        "Evidence",
        "Adapters",
        "Reliability",
        "System",
        "Settings",
        "Providers",
        "Tokens",
        "Logs",
        "Database",
    ),
    "ideapress": (
        "Overview",
        "Projects",
        "Units",
        "Workflows",
        "Backends",
        "Prompts",
        "Settings",
        "Logs",
        "Database",
    ),
    "promptcadence": (
        "Overview",
        "Trajectories",
        "Approvals",
        "Tiers",
        "Tools",
        "Ledger",
        "Egress",
        "System",
        "Settings",
        "Tokens",
        "Logs",
        "Database",
    ),
}
"""Spec §7.3's menu, per application; :data:`_PAGE_HREF` says which of them this build serves."""

_PAGE_PHASE: dict[tuple[str, str], str] = {}
"""The row in ``roadmap/weightroom-work.md`` that builds each still-unbuilt page, keyed by
application as well as label: FreeWeight's Models and LoadCoach's are two rows. W3 left every
page *not yet scheduled* (its handoff §2.4); the WP rows schedule them all."""

_PAGE_HREF: dict[str | tuple[str, str], str] = {
    "Overview": "/apps/{app}",
    "Settings": "/apps/{app}/settings",
    "Tokens": "/apps/{app}/tokens",
    "Prompts": "/apps/{app}/prompts",
    "Database": "/apps/{app}/database",
    "Logs": "/apps/{app}/logs",
    # PromptCadence's own pages (row WP1); no other application's menu names these labels.
    "Trajectories": "/apps/{app}/trajectories",
    "Approvals": "/apps/{app}/approvals",
    "Tiers": "/apps/{app}/tiers",
    "Tools": "/apps/{app}/tools",
    "Ledger": "/apps/{app}/ledger",
    "Egress": "/apps/{app}/egress",
    "System": "/apps/{app}/system",
    # LoadCoach's own pages (row WP2), keyed by application: FreeWeight's Models, Evidence and
    # Adapters are other pages, built by another row.
    ("loadcoach", "Models"): "/apps/loadcoach/models",
    ("loadcoach", "Routing"): "/apps/loadcoach/routing",
    ("loadcoach", "Reliability"): "/apps/loadcoach/reliability",
    ("loadcoach", "Queue"): "/apps/loadcoach/queue",
    ("loadcoach", "Evidence"): "/apps/loadcoach/evidence",
    ("loadcoach", "Adapters"): "/apps/loadcoach/adapters",
    "Providers": "/apps/{app}/providers",
    # IdeaPress's own pages (row WP5); no other application's menu names these labels.
    "Projects": "/apps/{app}/projects",
    "Units": "/apps/{app}/units",
    "Workflows": "/apps/{app}/workflows",
    "Backends": "/apps/{app}/backends",
    # FreeWeight's own pages (row WP3). Machines has no menu entry: its pages open from Runs and
    # Results, which link every machine they name; nor does Dashboard, which row WX8 merged into
    # the Overview (`/apps/freeweight`, its old path a redirect).
    ("freeweight", "Models"): "/apps/freeweight/models",
    ("freeweight", "Runs"): "/apps/freeweight/runs",
    ("freeweight", "Results"): "/apps/freeweight/results",
    ("freeweight", "Evidence"): "/apps/freeweight/evidence",
    ("freeweight", "Adapters"): "/apps/freeweight/adapters",
    # FreeWeight's goals, drafts, calibration and grading (row WP4); Judges open from Goals.
    ("freeweight", "Goals"): "/apps/freeweight/goals",
    # FreeWeight's one [provider] block; LoadCoach's plural registrations are `Providers` (WP2).
    "Provider": "/apps/{app}/provider",
}
"""Where a built page lives — by label for a page every application shares, by ``(app, label)`` for
one only that application has; anything absent is still a stub."""


def _page_href(app_name: str, label: str) -> str | None:
    """The built page's path, or ``None`` for a stub."""
    href = _PAGE_HREF.get((app_name, label)) or _PAGE_HREF.get(label)
    return None if href is None else href.format(app=app_name)


_ADMIN_PAGES: frozenset[str] = frozenset(
    {"System", "Settings", "Provider", "Providers", "Tokens", "Prompts", "Logs", "Database"}
)
"""The administrative pages, below the rule in an application's menu (design brief §4): the
application's own subjects first, then what the console does to it."""

_NO_TOKENS: frozenset[str] = frozenset({"ideapress"})
"""IdeaPress has no token surface at all — no ``token`` CLI verb and no token table (W4)."""


def _built_pages(app_name: str) -> tuple[str, ...]:
    """Every spec §7.3 page for ``app_name`` this build actually serves."""
    return tuple(
        label
        for label in _APP_PAGES.get(app_name, ())
        if _page_href(app_name, label) and not (label == "Tokens" and app_name in _NO_TOKENS)
    )


def app_label(name: str) -> str:
    """The display name of an application.

    Args:
        name: The lowercase identifier a route, unit or CLI uses (``loadcoach``).

    Returns:
        Its display name (``LoadCoach``), or ``name`` unchanged when it is not one the suite knows,
        so an unexpected name still renders as itself rather than as nothing.
    """
    return APP_LABELS.get(name, name)


def docs_action(app_name: str) -> dict[str, str]:
    """The page bar's *Docs* action for an application's page (row WY1).

    Args:
        app_name: The lowercase identifier (``loadcoach``).

    Returns:
        ``{"label": "Docs", "href": …}`` pointing at the application's folder in the docs tree
        (``folder_anchor`` in ``_docs_tree.html``). A docs root without that folder still opens;
        the anchor matches nothing, which is never a 500 (row WX2).
    """
    return {"label": "Docs", "href": f"/docs?section=apps#docs-apps-{app_name}"}


def app_side_nav(app_name: str, *, selected: str = "Overview") -> tuple[dict[str, Any], ...]:
    """The sections :func:`~mirrorwall.side_nav` renders under an application's tab.

    The application's own subjects come first under its name, then the macro's rule, then the
    administrative pages (:data:`_ADMIN_PAGES`, design brief §4). Nothing of the console's own:
    row WY1 stopped appending :data:`CONSOLE_SIDE_NAV` here on the operator's instruction,
    reversing WX3 — the brand links to ``/`` and Chat is in the top bar, so the tab is no dead
    end. The macro's
    ``link`` shape has no inert state, so a page this build has not shipped yet is never handed to
    it as a dead ``href=""`` link — :func:`app_side_nav_stubs` renders those separately, in
    WeightRoomGym's own markup (design brief §5: one consumer stays here).
    """
    links = [
        {
            "label": label,
            "href": _page_href(app_name, label),
            "selected": label == selected,
        }
        for label in _built_pages(app_name)
    ]
    return (
        {
            "title": app_label(app_name),
            "links": [x for x in links if x["label"] not in _ADMIN_PAGES],
        },
        {"title": "", "links": [x for x in links if x["label"] in _ADMIN_PAGES]},
    )


def app_side_nav_stubs(app_name: str) -> tuple[dict[str, str], ...]:
    """Every page spec §7.3 names for ``app_name`` that this build does not serve.

    Each carries the row that will build it where the roadmap already says so, and "not yet
    scheduled" where it does not — a documentation gap noted rather than invented an answer to.
    """
    built = _built_pages(app_name)
    stubs = []
    for label in _APP_PAGES.get(app_name, ()):
        if label in built:
            continue
        if label == "Tokens":
            title = f"{app_label(app_name)} has no API tokens"
        else:
            row = _PAGE_PHASE.get((app_name, label))
            title = f"coming in row {row}" if row else "not yet scheduled"
        stubs.append({"label": label, "title": title})
    return tuple(stubs)


CONSOLE_SIDE_NAV: tuple[dict[str, Any], ...] = (
    {
        "title": "Console",
        "links": [{"label": item["label"], "href": item["href"]} for item in NAV_ITEMS],
    },
    {
        "title": "Tools",
        "links": [
            {"label": page["label"], "href": page["href"]}
            for page in CONSOLE_PAGES
            if page.get("href")
        ],
    },
)
"""The console's own navigation, in two sections, on the console's own pages (row WX3).

The top bar carried the tools until WX3 and dropped them into a *Menu* dropdown below 1080 px, so
which pages existed depended on the window's width. They are a left-menu section: the host's own
pages first, then the tools that reach across applications. Row WY1 took them off an
application's tab and the docs viewer, on the operator's instruction; those menus list only their
own subject.
"""


PILL_TONES: dict[str, str] = {
    "ok": "success",
    "starting": "warning",
    "stopping": "warning",
    "stopped": "neutral",
    "failed": "danger",
    "version mismatch": "danger",
    "not installed": "neutral",
    "unsupported": "neutral",
}
"""How :attr:`~weightroom.services.apps.AppView.pill` colours.

*stopped* and *not installed* are **neutral**, not warnings: an operator who has deliberately
stopped an application should not be shown a page of amber. Only a state nobody chose — a failed
unit, a version outside the range — is coloured as a problem.
"""


def pill_tone(pill: str) -> str:
    """The badge tone for a status pill; unknown words are neutral rather than alarming."""
    return PILL_TONES.get(pill, "neutral")


def pill_status(pill: str) -> str:
    """The status-dot word (design brief §3) for an :class:`AppView` pill; the same map health
    already reads a component's status from — one vocabulary, read two ways.
    """
    return APP_STATUS_DOT.get(pill, "unknown")


@lru_cache(maxsize=1)
def templates() -> Environment:
    """Return the process-wide Jinja environment, building it on first use."""
    environment = create_template_environment(
        app_template_dirs=(_TEMPLATES_DIR,),
        globals_={
            # The name an operator reads. The distribution, CLI and ADRs keep WeightRoomGym/wr-gym;
            # the header says WeightRoom and links home (operator decision, 2026-09-10).
            "product_name": "WeightRoom",
            "product_href": "/",
            # No version in the header (operator, 2026-09-10). The login page is LAN-facing, and a
            # version string there tells a stranger which advisories apply; the operator menu and
            # the pages that compare versions read `console_version` instead.
            "product_version": "",
            "console_version": __version__,
            "nav_items": NAV_ITEMS,
            # A page bar's Docs action (`_app_page.html` `page_nav`, row WY1): one application's
            # entry in the docs tree, the same anchor `docs_link` renders.
            "docs_action": docs_action,
            "theme_storage_key": "weightroom-theme",
            # ADR-0128: every fragment swap and SSE region in the shell is htmx, vendored by
            # MirrorWall 0.3 and opt-in per page — WeightRoomGym opts every page in at once
            # (design brief §4), since the log pane and the guard dialog both want it.
            "mirrorwall": {"htmx": True, "echarts": False},
        },
    )
    environment.filters["pill_tone"] = pill_tone
    environment.filters["pill_status"] = pill_status
    environment.filters["app_label"] = app_label
    environment.filters["cell_text"] = cell_text
    return environment


def render(template_name: str, /, **context: Any) -> str:
    """Render ``template_name`` with ``context``."""
    return templates().get_template(template_name).render(**context)


def trust_context(settings: Settings, *, tls: TlsStatus, identity: HostIdentity) -> dict[str, Any]:
    """What both trust pages and ``wr-gym trust`` show: fingerprint, URLs, steps."""
    hosts = [f"{identity.hostname}.local", *identity.addresses]
    return {
        "fingerprint": tls.ca_fingerprint_sha256,
        "ca_subject": tls.ca_subject,
        "ca_not_after": tls.ca_not_after.date().isoformat(),
        "ca_file": str(tls.paths.ca_crt),
        "console_urls": [f"https://{host}:{settings.server.port}" for host in hosts],
        "trust_urls": [f"http://{host}:{settings.server.trust_port}/trust" for host in hosts],
        "root_urls": [f"http://{host}:{settings.server.trust_port}/root.crt" for host in hosts],
        "steps": trust_steps(identity.hostname),
    }
