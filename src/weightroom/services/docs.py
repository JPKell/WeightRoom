"""weightroom.services.docs — the documentation tree: root, containment, rendering, the ADR index.

Read-only (spec §3): no route here ever writes to `[docs] root`. Three ideas carry the module:

**Resolution before comparison** (security standards §5, mirrored from ToolYard's
`PathContainment` — read as the containment vector set, never imported: ADR-0123 rule 4 forbids
the dependency). A candidate path is turned into an absolute, symlink-free path first
(``os.path.realpath(strict=False)`` — a docs path is always expected to exist, so the strict
probe that ToolYard uses for a *write* candidate that may not exist yet is not needed here), and
only the result is compared against the root by ancestry, never by string prefix. A relative
candidate resolves against the document's own directory, not the process CWD.

**Sanitised by construction, not by a second pass.** ``mistune.HTMLRenderer(escape=True)`` —
the default — already escapes raw HTML in a markdown source to plain text, so ``<script>`` and
a stray Jinja ``{{ }}`` both render as literal characters on the page; nothing here scrubs the
output afterward because nothing unsafe reaches it in the first place. Renderer instances are
never shared across requests or reused between calls (Starlette runs a sync route in a
threadpool; a shared instance's ``outline``/``has_mermaid`` state would race).

**A relative link is rewritten only when it resolves inside the root**, to
``/docs/page?path=<relative path>``; one that resolves outside is rendered as plain text — never
as a link a reader could click into somewhere this viewer refuses to serve. Non-markdown targets
(images, other file types) are out of this row's scope: there is no raw-asset route in api.md §8,
so a relative link to one renders as plain text too, same as a link outside the root.
"""

from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final

import mistune
from baseaicore import SuiteError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from weightroom.config import Settings

__all__ = [
    "APP_BLURBS",
    "MARKDOWN_PLUGINS",
    "AdrRow",
    "DocPage",
    "DocsPageOutsideRoot",
    "DocsRootMissing",
    "TreeNode",
    "build_tree",
    "parse_adr_index",
    "render_markdown",
    "resolve_docs_root",
    "resolve_doc_path",
]

logger = logging.getLogger(__name__)

MARKDOWN_PLUGINS: Final = ("table", "footnotes", "task_lists", "url", "strikethrough")

_SLUG_TAG_RE = re.compile(r"<[^>]+>")
_SLUG_NONWORD_RE = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_WS_RE = re.compile(r"[\s_-]+")
_FRAGMENT_RE = re.compile(r"#.*$")
_ADR_ROW_RE = re.compile(r"^\|\s*\[(\d+)\]\(([^)]+)\)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")

APP_BLURBS: Final[dict[str, str]] = {
    # Applications — `docs/apps/<name>/spec.md` §1, one sentence each.
    "freeweight": "Measures how well a model performs on this machine, for a given capability, "
    "under given settings, with evidence a user can inspect and reproduce.",
    "loadcoach": "Decides which installed model should do a task, and how, from the hardware's "
    "live state and whatever measured evidence exists.",
    "ideapress": "Turns an idea into finished content through configurable workflows in which "
    "Python owns the control flow and models perform bounded tasks.",
    "promptcadence": "Runs a multi-turn, tool-using agent loop over LoadCoach in which every "
    "step is planned and approved against governance policy and budget before it executes.",
    "weightroom": "The host operator's one console over the four applications: what the machine "
    "is doing, starting and stopping units, editing configuration, and the machine's databases.",
    # Packages — `docs/packages/<name>/spec.md` §1, one sentence each.
    "baseaicore": "The smallest stable set of domain types every component of the suite agrees "
    "on: model identity, machine identity, an unsupported measurement, and the rest.",
    "setspec": "Owns every data contract that crosses an application boundary, versioned so a "
    "reader and a writer on different releases still agree on the payload's shape.",
    "modelrack": "The suite's only model client: one normalized, provider-neutral implementation "
    "of talking to a local inference runtime, so no application writes its own.",
    "sweatmeter": "Reports what the machine is doing and what it is — CPU, RAM, GPU, VRAM, "
    "temperatures, power, clocks, disks — accurately and without ever inventing a number.",
    "weightsdb": "Gives every application the same database plumbing — engine, sessions, "
    "migrations, backup and health — without giving them a shared schema.",
    "mirrorwall": "Lets the four applications look and behave like one product family without "
    "sharing a single page: tokens, layout, components, streaming and JSON conventions.",
    "loadledger": "Accumulates cost and usage across a multi-step run and enforces ceilings "
    "against it, over BaseAiCore's own money and token-usage primitives.",
    "cutctx": "The suite's one answer to a transcript that has outgrown its window: decides, "
    "deterministically and explicably, what to keep without touching a model.",
    "toolyard": "The one place in the suite that executes a real, side-effecting tool call on a "
    "model's behalf, and so the one place that risk and discipline concentrate.",
    "commissioner": "Turns the suite's egress behaviour into an egress record: one decision "
    "ledger for every case an application already lets a call reach the outside world.",
}
"""One sentence per application and package, from each's own ``spec.md`` §1 — the docs viewer's
section listing and the *apps*/*packages* section pages use it to say what a folder is before a
reader opens anything in it. A folder with no entry here (a future component, or one docs has not
covered) renders with no blurb rather than an invented one."""


class DocsRootMissing(SuiteError):
    """``[docs] root`` is unset and no ``docs/`` sits beside the installed package."""

    code: ClassVar[str] = "DOCS_ROOT_MISSING"


class DocsPageOutsideRoot(SuiteError):
    """A requested or linked path resolves outside ``[docs] root``."""

    code: ClassVar[str] = "DOCS_PAGE_OUTSIDE_ROOT"


def resolve_docs_root(settings: Settings) -> Path:
    """``[docs] root``, else the ``docs/`` beside this checkout, else refuse by name.

    Raises:
        DocsRootMissing: Neither exists, or the configured root is not a directory.
    """
    configured = settings.docs.root.strip()
    if configured:
        root = Path(configured)
        if not root.is_dir():
            raise DocsRootMissing(
                f"[docs] root is set to {configured!r}, which is not a directory.",
                details={"root": configured},
            )
        return root.resolve()
    import weightroom

    beside_checkout = Path(weightroom.__file__).resolve().parents[2] / "docs"
    if beside_checkout.is_dir():
        return beside_checkout.resolve()
    raise DocsRootMissing(
        "No [docs] root is configured, and no docs/ sits beside this installation. Set "
        "[docs] root in WeightRoomGym's configuration.",
        details={"checked": str(beside_checkout)},
    )


def _resolve_within(root: Path, candidate: Path) -> Path | None:
    """Resolve ``candidate`` fully, then check ancestry against ``root``. ``None`` on escape."""
    try:
        resolved = Path(os.path.realpath(candidate, strict=False))
    except (OSError, ValueError):
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def resolve_doc_path(root: Path, relative: str) -> Path:
    """Resolve a ``path=`` query value against ``root``. Root-relative, never CWD-relative.

    Args:
        root: The resolved docs root.
        relative: A slash-separated path, as a reader's URL or a rendered link carries it.

    Returns:
        The resolved, contained, existing file.

    Raises:
        DocsPageOutsideRoot: The candidate is blank, escapes the root, or names something that
            is not a readable file under it.
    """
    cleaned = relative.strip().replace("\x00", "")
    if not cleaned or cleaned.startswith("/"):
        raise DocsPageOutsideRoot(
            f"{relative!r} is not a path under the docs root.", details={"path": relative}
        )
    resolved = _resolve_within(root, root / cleaned)
    if resolved is None or not resolved.is_file():
        raise DocsPageOutsideRoot(
            f"{relative!r} does not resolve to a file under the docs root.",
            details={"path": relative},
        )
    return resolved


@dataclass(frozen=True, slots=True)
class TreeNode:
    """One entry in the docs tree — a directory with children, or a file."""

    name: str
    path: str
    is_dir: bool
    children: tuple[TreeNode, ...] = ()

    def as_json(self) -> dict[str, Any]:
        """The ``GET /docs/tree`` shape, recursively."""
        return {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "children": [child.as_json() for child in self.children],
        }


_SKIP_DIRS = frozenset({".git", ".obsidian", "__pycache__", "scripts"})


def build_tree(root: Path, *, current: Path | None = None) -> TreeNode:
    """The directory tree under ``root``: directories first, then ``*.md`` files, both sorted.

    Args:
        root: The docs root.
        current: Defaults to ``root`` on the top call; the recursion argument otherwise.
    """
    at = current if current is not None else root
    entries = sorted(
        (entry for entry in at.iterdir() if entry.name not in _SKIP_DIRS),
        key=lambda entry: (not entry.is_dir(), entry.name.lower()),
    )
    children = []
    for entry in entries:
        if entry.is_dir():
            sub = build_tree(root, current=entry)
            if sub.children:  # an empty directory (no markdown anywhere under it) is not shown
                children.append(sub)
        elif entry.suffix == ".md":
            children.append(
                TreeNode(name=entry.name, path=entry.relative_to(root).as_posix(), is_dir=False)
            )
    return TreeNode(
        name=at.name if at != root else "docs",
        path="" if at == root else at.relative_to(root).as_posix(),
        is_dir=True,
        children=tuple(children),
    )


SECTION_ORDER: tuple[str, ...] = (
    "",
    "apps",
    "packages",
    "standards",
    "architecture",
    "adr",
    "roadmap",
    "history",
    "reviews",
)
"""The docs viewer's left menu, in the operator's order (2026-09-10). ``""`` is Home: the root's
own files. A top-level folder not named here is appended after these, alphabetically, rather than
hidden — a new folder should appear, not vanish."""

_SECTION_LABELS: dict[str, str] = {"": "Home", "adr": "ADR"}


@dataclass(frozen=True, slots=True)
class DocSection:
    """One entry in the docs viewer's left menu.

    Attributes:
        key: The top-level folder's name, or ``""`` for Home.
        label: What the menu shows.
        node: The folder's tree — for Home, the root with its folders left out.
    """

    key: str
    label: str
    node: TreeNode

    @property
    def href(self) -> str:
        """The section's page: ``/docs`` for Home, ``/docs?section=<key>`` otherwise."""
        return f"/docs?section={self.key}" if self.key else "/docs"


def docs_sections(tree: TreeNode) -> tuple[DocSection, ...]:
    """The left menu's sections, in :data:`SECTION_ORDER`.

    Args:
        tree: :func:`build_tree` of the docs root.

    Returns:
        Home first when the root has markdown files of its own, then each top-level folder that
        has any markdown under it: the named ones in order, the rest alphabetically. A section is
        looked up by name among these, never turned into a path.
    """
    home = TreeNode(
        name="Home",
        path="",
        is_dir=True,
        children=tuple(child for child in tree.children if not child.is_dir),
    )
    folders = {child.name: child for child in tree.children if child.is_dir}
    keys = [key for key in SECTION_ORDER if key in folders]
    keys += sorted((key for key in folders if key not in SECTION_ORDER), key=str.lower)
    sections = [DocSection(key="", label="Home", node=home)] if home.children else []
    for key in keys:
        label = _SECTION_LABELS.get(key) or key.replace("-", " ").replace("_", " ").title()
        sections.append(DocSection(key=key, label=label, node=folders[key]))
    return tuple(sections)


def section_of(path: str) -> str:
    """The section a document belongs to.

    Args:
        path: A document's path relative to the docs root (``apps/loadcoach/spec.md``).

    Returns:
        Its top-level folder (``apps``), or ``""`` — Home — for a file in the root itself.
    """
    head, separator, _ = path.partition("/")
    return head if separator else ""


def _slugify(raw_text: str, *, seen: dict[str, int]) -> str:
    plain = html.unescape(_SLUG_TAG_RE.sub("", raw_text))
    plain = _SLUG_NONWORD_RE.sub("", plain).strip().lower()
    slug = _SLUG_WS_RE.sub("-", plain) or "section"
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


class _LinkKind:
    EXTERNAL = "external"
    INTERNAL = "internal"
    OUTSIDE = "outside"


def _classify_link(url: str, *, root: Path, current_dir: Path) -> tuple[str, str]:
    """``(kind, value)``: ``external``/``value=url`` unchanged, ``internal``/``value=rewritten
    href``, or ``outside``/``value=""``.

    Only a **relative** path ending in ``.md`` is ever rewritten. A scheme (``http:``,
    ``mailto:``, …), a bare ``#fragment``, a site-absolute path (``/…``) and anything not ending
    in ``.md`` (an image, an asset — no raw-asset route this row) all fall outside that one case.
    """
    stripped = url.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("/"):
        return _LinkKind.EXTERNAL if stripped.startswith("#") else _LinkKind.OUTSIDE, url
    scheme_end = stripped.find(":")
    if 0 < scheme_end <= 10 and "/" not in stripped[:scheme_end]:
        return _LinkKind.EXTERNAL, url  # http:, https:, mailto:, … — safe_url judges the rest
    path_part = _FRAGMENT_RE.sub("", stripped)
    fragment = stripped[len(path_part) :]
    if not path_part or not path_part.endswith(".md"):
        return _LinkKind.OUTSIDE, ""
    resolved = _resolve_within(root, current_dir / Path(path_part))
    if resolved is None:
        return _LinkKind.OUTSIDE, ""
    rel = resolved.relative_to(root).as_posix()
    return _LinkKind.INTERNAL, f"/docs/page?path={rel}{fragment}"


class _DocsRenderer(mistune.HTMLRenderer):
    """One render's worth of state: the outline, whether a mermaid fence was seen, link rewrites.

    Built fresh per call to :func:`render_markdown` — never shared or reused (this module's
    docstring).
    """

    def __init__(self, *, root: Path, current_dir: Path) -> None:
        super().__init__(escape=True)
        self._root = root
        self._current_dir = current_dir
        self._slug_seen: dict[str, int] = {}
        self.outline: list[dict[str, Any]] = []
        self.has_mermaid = False

    def heading(self, text: str, level: int, **attrs: Any) -> str:
        slug = _slugify(text, seen=self._slug_seen)
        self.outline.append({"level": level, "id": slug, "text": _SLUG_TAG_RE.sub("", text)})
        tag = f"h{level}"
        return f'<{tag} id="{slug}">{text}</{tag}>\n'

    def block_code(self, code: str, info: str | None = None) -> str:
        lang = (info or "").split(None, 1)[0] if info else ""
        if lang == "mermaid":
            self.has_mermaid = True
            return f'<pre class="mermaid">{mistune.escape(code)}</pre>\n'
        return super().block_code(code, info=info)

    def link(self, text: str, url: str, title: str | None = None) -> str:
        kind, value = _classify_link(url, root=self._root, current_dir=self._current_dir)
        if kind == _LinkKind.OUTSIDE:
            return text
        return super().link(text, value, title=title)

    def image(self, text: str, url: str, title: str | None = None) -> str:
        kind, _value = _classify_link(url, root=self._root, current_dir=self._current_dir)
        if kind != _LinkKind.EXTERNAL:
            return text  # no raw-asset route this row (this module's docstring)
        return super().image(text, url, title=title)


@dataclass(frozen=True, slots=True)
class DocPage:
    """One rendered document."""

    title: str
    html: str
    outline: tuple[dict[str, Any], ...]
    has_mermaid: bool


def _title_of(path: Path, html_body: str, outline: Sequence[dict[str, Any]]) -> str:
    for entry in outline:
        if entry["level"] == 1:
            return str(entry["text"])
    del html_body
    return path.stem.replace("-", " ").replace("_", " ").strip().capitalize()


def render_markdown(root: Path, path: Path) -> DocPage:
    """Render one document: sanitised HTML, its heading outline, whether it uses mermaid.

    Args:
        root: The resolved docs root.
        path: A file already resolved and contained by :func:`resolve_doc_path`.
    """
    source = path.read_text(encoding="utf-8")
    renderer = _DocsRenderer(root=root, current_dir=path.parent)
    convert = mistune.create_markdown(renderer=renderer, plugins=list(MARKDOWN_PLUGINS))
    body = convert(source)
    assert isinstance(body, str)  # noqa: S101 — the "html" renderer always returns str, never a list
    return DocPage(
        title=_title_of(path, body, renderer.outline),
        html=body,
        outline=tuple(renderer.outline),
        has_mermaid=renderer.has_mermaid,
    )


@dataclass(frozen=True, slots=True)
class AdrRow:
    """One row of the ADR index."""

    number: str
    path: str
    title: str
    status: str


def parse_adr_index(root: Path) -> tuple[AdrRow, ...]:
    """``adr/README.md``'s own table — never the filenames (decisions already taken).

    Returns:
        Every row, in the file's own order. An empty tuple when the index file is absent or has
        no table rows — never an error: a missing index is a page that says so, not a 500.
    """
    index_path = root / "adr" / "README.md"
    try:
        text = index_path.read_text(encoding="utf-8")
    except OSError:
        return ()
    rows = []
    for line in text.splitlines():
        match = _ADR_ROW_RE.match(line)
        if match is None:
            continue
        number, link, title, status = match.groups()
        rows.append(AdrRow(number=number, path=f"adr/{link}", title=title, status=status))
    return tuple(rows)
