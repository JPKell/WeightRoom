# MirrorWall — Specification

**Type:** Python package (web/UI toolkit) · **Import/distribution name:** `mirrorwall` · **Layer:** 3
**Status:** Implemented and published as `mirrorwall 0.2.2`; **`0.3.0` prepared (unpublished,
row WM)** — the WeightRoomGym design brief's dense-console tokens and seven generic components
(Phase 4). **Extracted at:** LoadCoach Phase 4, from FreeWeight's web layer
([ADR-0011](../../adr/0011-shared-package-boundaries.md)); adopted by FreeWeight at its Phase 12,
and by PromptCadence from its first web layer.
**Decision records:** [ADR-0020](../../adr/0020-ui-rendering-strategy.md), [ADR-0004](../../adr/0004-sse-vs-websockets.md),
[ADR-0128](../../adr/0128-mirrorwall-vendors-htmx-and-applications-may-adopt-it.md) (0.3: vendors
htmx and its SSE extension, opt-in per page), [ADR-0142](../../adr/0142-echarts-is-vendored-and-budgeted-by-name.md)
(vendors ECharts the same way, opt-in per page; supersedes ADR-0139 for this one library by name).

---

## 1. Purpose

Let four applications look and behave like one product family without sharing a single page. It
supplies the tokens, layout, components, streaming plumbing and JSON conventions that all three need;
it knows nothing about benchmarks, routing or content.

## 2. Scope

**Backend:** JSON response and error envelope helpers, request-ID middleware, SSE response helper
and event-store protocol, static asset mounting with hashed URLs, health-payload primitives,
Jinja2 environment construction with the shared template path and filters.

The `measurement` filter is the **only** sanctioned way a template touches a `Measurement`.
`UNSUPPORTED` refuses `__bool__`, so `{% if value %}` on a measurement raises rather than rendering
blank — correct, and worth knowing before it happens. Templates use `{{ value | measurement }}` and
`{% if value | is_supported %}`; a template-lint test scans for a bare truthiness test on a
measurement-typed context variable.

**Frontend:** design tokens (CSS + JSON), base layout templates, component macros, the telemetry bar,
theme handling, table interaction module, drawer/dialog/toast modules, SSE client module, chart
container with theming and an accessible table alternative, vendored assets (charting library,
fonts, icons).

## 3. Explicit non-goals

* **No application pages**, no navigation trees, no route definitions beyond the static/asset mount.
* No benchmark, routing or workflow vocabulary — not in templates, not in CSS class names, not in
  JS module names.
* No SPA framework, no npm, no bundler, no build step.
* No database access, no provider access, no telemetry collection (it *renders* a telemetry payload;
  SweatMeter produces it).
* No authentication logic (it renders auth states; the application enforces them).
* No opinion about an application's information architecture.

## 4. Responsibilities

| Responsibility | Detail |
|---|---|
| Design tokens | `tokens.css` and `tokens.json` per [UI/UX Standards](../../standards/ui-ux-standards.md), with per-application accent override |
| Base layout | Shell template: header slot, telemetry bar, content block, footer, theme bootstrap script |
| Components | Jinja macros: button, input, select, checkbox/radio/switch, card (default or `figure`), table (dense or comfortable, mono columns), badge, status dot, app tab, tabs, drawer, dialog, toast, tooltip, progress, empty state, pagination, filter bar, key–value list, code/JSON viewer, chart container, log pane, side nav |
| Telemetry bar | Macro + JS module consuming a generic telemetry payload, rendering `—` for unsupported values |
| Theme | System/light/dark, no-flash bootstrap, `localStorage` persistence, chart re-theme hook |
| SSE | Server helpers (`sse_response`; `log_pane_response` for the log pane) and client module with reconnect and `Last-Event-ID` |
| Envelopes | `json_response`, `error_response`, `paginated_response` producing SetSpec-shaped bodies |
| Request IDs | Middleware: accept or generate, bind to logging context, return in `X-Request-ID` |
| Static assets | Mounting, content-hashed URLs, correct cache headers, path-traversal-safe resolution |
| Accessibility | Every component keyboard-operable with correct ARIA, verified by tests |

## 5. Dependencies

`baseaicore`, `setspec` (event and error envelopes), `jinja2>=3.1,<4`, `starlette` (via the
application's FastAPI; declared as a dependency for the middleware and response helpers).

## 6. Consumers

FreeWeight, LoadCoach, IdeaPress, PromptCadence.

## 7. Public API

```python
# Templating
def create_template_environment(*, app_template_dirs: Sequence[Path],
                                globals_: Mapping[str, Any] | None = None) -> Environment:
    """Jinja2 environment with MirrorWall's macros on the search path, autoescaping on,
    StrictUndefined, and the shared filters (bytes, duration, timestamp, measurement)."""

# Responses
def json_response(payload: Any, *, status: int = 200, request_id: str | None = None) -> JSONResponse
def error_response(error: SuiteError | ErrorEnvelope, *, status: int, request_id: str) -> JSONResponse
def paginated_response(items, *, limit, next_cursor, has_more, total=None, request_id=None) -> JSONResponse

# Streaming
class EventSource(Protocol):
    def replay(self, *, stream_id: str, after_sequence: int) -> Iterator[EventEnvelope]: ...
    def subscribe(self, *, stream_id: str) -> AbstractContextManager[Iterator[EventEnvelope]]: ...

def sse_response(source: EventSource, *, stream_id: str, last_event_id: str | None,
                 heartbeat_seconds: float = 15.0, queue_size: int = 256) -> StreamingResponse:
    """SSE with gap-free replay-then-live handoff, heartbeats and bounded subscriber queues.

    ``EventSource`` is deliberately **synchronous** — an application implements it over its own
    repositories — while the handler holding this response is ``async def``. Every call into the
    source is therefore dispatched with ``anyio.to_thread.run_sync``, here, once, so no application
    can put a blocking ``SELECT`` on the event loop
    (:doc:`ADR-0003 §6-8 <../../adr/0003-sync-vs-async-strategy>`). Replay is read in bounded
    batches rather than one round trip per event, and the steady-state stream is served from the
    in-memory fan-out without touching the database at all.

    Every frame carries the SetSpec event envelope, except ``event: token``, which is bare — the one
    documented exception (:doc:`ADR-0025 §3 <../../adr/0025-envelope-boundaries>`).
    """

def log_pane_response(source: EventSource, *, stream_id: str, last_event_id: str | None,
                      render_line: Callable[[Event], str | None], generator: GeneratorInfo,
                      terminal_events: frozenset[str] = ..., ...) -> StreamingResponse:
    """The server half of ``log_pane`` (0.3.1, row WM2): the same replay-then-live loop as
    ``sse_response`` over the same source, each event rendered by the application as one
    ``event: log`` frame whose data is a ``log_line`` fragment, and ``event: log.closed`` after a
    terminal event — the ``sse-close`` the pane needs to stop reconnecting. An event the renderer
    answers ``None`` for is skipped."""

def log_line(text: str, *, level: str = "info") -> str:
    """The escaped ``.log-pane-line`` fragment a ``log`` frame carries."""

# Middleware and mounting
class RequestIdMiddleware: ...
class HostValidationMiddleware:
    """Rejects a request whose ``Host`` is not allowed, with 421, before routing and before auth.

    Loopback binds allow ``localhost``, ``127.0.0.1``, ``[::1]`` and the bound address; other binds
    require an explicit list. Shared here so all four applications behave identically — this is what
    closes DNS rebinding against an unauthenticated loopback service
    (:doc:`ADR-0026 §1 <../../adr/0026-local-http-hardening>`).
    """
class CsrfMiddleware:
    """Double-submit token on HTML form posts; the JSON API is exempt on stated grounds
    (:doc:`ADR-0026 §2 <../../adr/0026-local-http-hardening>`)."""
def mount_static(app, *, extra_dirs: Mapping[str, Path] | None = None) -> None
def asset_url(path: str) -> str          # content-hashed, cache-friendly

# Health primitives
class ComponentStatus(StrEnum): OK, DEGRADED, UNAVAILABLE, NOT_CONFIGURED
def health_payload(*, application: str, version: str, components: Sequence[ComponentHealth]) -> dict
def worst_status(components) -> ComponentStatus

# Template macros (Jinja)
{% from "mirrorwall/components.html" import button, table, badge, drawer, dialog,
   empty_state, filter_bar, kv_list, json_viewer, progress, chart_container, telemetry_bar %}
```

## 8. Inputs

Template directories, static directories, telemetry payloads, event sources, health components,
theme preference, an application accent token.

## 9. Outputs

Rendered HTML fragments, JSON responses, SSE streams, static asset URLs, health payloads.

## 10. Data ownership

None. It renders what it is given and stores nothing beyond the viewer's `localStorage` theme and
table preferences. The keys are contract: the theme lives under `DEFAULT_THEME_STORAGE_KEY`
(`mirrorwall-theme`) unless the application configures its own, and `table.js` keeps column
visibility under `mirrorwall-columns:<table id>` — an application that swaps its own table script
for this one orphans its old keys silently rather than migrating them.

## 11. Public contracts

1. A component's rendered markup and its `data-` attribute API are the contract; class names are
   internal and may change within a major version.
2. SSE streams are gap-free: subscribe-before-replay, dedupe by sequence, no duplicate across the
   handoff.
3. A slow subscriber is dropped when its bounded queue fills; it is never allowed to grow memory.
4. Error bodies are `{"error": {…}}` with the inner object matching `setspec.ErrorEnvelope`, and are
   **not** SetSpec-wrapped. Event frames **are** SetSpec-wrapped, with the event as `payload` and the
   envelope fields as its siblings. `token` frames are bare. There is exactly one shape for each
   ([ADR-0025](../../adr/0025-envelope-boundaries.md)).
4a. No call into an application's `EventSource` runs on the event loop.
5. Autoescaping is always on; no macro renders unescaped user or model content.
6. Every component is keyboard-operable and meets the contrast requirement in both themes.
7. Upgrading MirrorWall never requires an application to change its pages within a major version.

## 12. Configuration

Constructor arguments only: template dirs, static dirs, accent token override, heartbeat interval,
queue size, asset cache policy.

## 13. Error behaviour

| Condition | Behaviour |
|---|---|
| Template not found | Jinja error surfaced at startup by a template-preload check, not at first request |
| Undefined template variable | `StrictUndefined` raises — a missing variable is a bug, never a blank cell |
| Static path escapes the root | 404, logged at WARNING with the attempted path |
| SSE subscriber queue full | Subscriber dropped, DEBUG logged; client reconnects and replays |
| Event source raises during replay | Stream closed with a terminal `stream.failed` event so the client stops cleanly |
| Unsupported measurement in a payload | Rendered as `—` with the reason in a tooltip; never `0`, never blank |

## 14. Security considerations

* Autoescaping on, `StrictUndefined`, no `|safe` on any value derived from user or model content.
* A `markdown` filter exists only with a strict allowlist sanitizer, and is tested against
  `<script>`, event handlers, `javascript:` URLs and embedded SVG.
* Static serving resolves and verifies containment; symlinks escaping the root are refused.
* CSP-friendly: no inline event handlers, no `eval`; the only inline script is the theme bootstrap,
  which is nonce-able and documented.
* No external requests from any page: no CDN, no remote fonts, no analytics — verified by a test that
  scans rendered templates and CSS for absolute external URLs.
* Request IDs are validated before echoing (charset and length capped) so a header cannot inject into
  logs.

## 15. Performance

| Measure | Target |
|---|---|
| Template render, typical page | ≤ 30 ms |
| SSE per-event overhead | ≤ 1 ms |
| Memory per idle SSE subscriber | ≤ 64 KiB |
| Concurrent SSE subscribers per process | ≥ 200 |
| JS shipped per page (excluding charting vendor) | ≤ 60 KB uncompressed |
| Charting vendor (vendored, cached) | ≤ 1 MB; ECharts 6.1.0 measures 1 121 883 bytes (1.07 MiB) at row WX6 — ADR-0142 records the overage rather than trimming to a build that lacks the heatmap a later row wants |
| Table sort, 1 000 rows × 20 columns | ≤ 150 ms |

## 16. Cross-platform

Fully portable server-side. Browser support: current Chrome, Firefox, Safari and Edge; no polyfills
and no transpilation — native ES modules only.

## 17. Observability

* Request-ID middleware binds the ID into the logging context for every request.
* SSE lifecycle events (subscribe, replay count, drop, close) logged at DEBUG.
* `X-Response-Time-Ms` added by the middleware.
* No INFO+ logging from the library.

## 18. Test strategy

| Area | Tests |
|---|---|
| Macros | Snapshot tests for every component in both themes; required ARIA attributes present; `data-` API honoured |
| Escaping | User/model content containing `<script>`, `{{ }}`, quotes and unicode renders inert |
| SSE | Ordered delivery; replay from `Last-Event-ID` with no gap or duplicate; heartbeat cadence; slow-consumer drop; source failure produces a terminal event; 200 concurrent subscribers |
| Envelopes | Bodies validate against SetSpec models; request ID present on success and error |
| Static | Hashed URLs; cache headers; traversal refused; missing file 404 |
| Theme | No-flash bootstrap; persistence; chart re-theme hook fires |
| Accessibility | Contrast over every token pair in both themes; keyboard traversal of table, drawer, dialog, tabs; focus trap and restore |
| Offline | No absolute external URL anywhere in templates, CSS or JS |
| Two consumers | Both applications' template suites render against the current version in CI. The suites are obtained from the applications' published distributions as a **test-only** dependency of MirrorWall's `dev` extra — the same channel that gives consumers the OpenAPI snapshots ([Testing Standards §8](../../standards/testing-standards.md)) — never by importing application code, which `lint-imports` continues to forbid |
| Host and CSRF middleware | Disallowed `Host` ⇒ 421 before routing and before auth; forged form post ⇒ 403; cross-origin JSON post rejected |
| SSE threading | An `EventSource` whose `replay` blocks for 200 ms does not delay the event loop (measured with an event-loop lag probe) |
| JS modules | Unit-tested with a lightweight DOM harness (no browser, no npm): table sort/filter, SSE client reconnect, theme toggle |

Coverage floor: **95 %** for Python; JS modules covered by the DOM harness with an equivalent target.

## 19. Compatibility and versioning

* Semantic versioning; pre-1.0 `0.x`.
* Rendered markup structure and `data-` attributes are the contract; a breaking change to either is a
  major bump.
* Token *values* may change in a minor bump; token *names* may not.
* Both applications' page suites are rendered against every release candidate in CI — that is the
  mechanism that keeps "upgrade without changing pages" true.

## 20. Acceptance criteria

1. Two applications share components while keeping entirely different navigation and pages.
2. Upgrading MirrorWall requires no change to either application's templates — proven in CI.
3. No application vocabulary appears anywhere in the package (asserted by a term scan for
   "benchmark", "run", "job", "route", "project", "stage" in template, CSS and JS identifiers).
4. Every component passes keyboard and ARIA tests; contrast passes for all token pairs in both themes.
5. A page loads and functions with the machine offline; no external request is attempted.
6. SSE replay after a forced disconnect produces no gap and no duplicate.
7. `mypy --strict`, `ruff`, `lint-imports` clean; coverage ≥ 95 %.

## 21. Future extensions

* ~~A small chart-spec wrapper so applications declare charts in Python and MirrorWall emits the
  vendor-specific configuration.~~ Delivered at row WX6: `chart_container(option=...)` takes the
  ECharts option as a plain Python dict; the application never touches ECharts' JS API directly.
* Printable/report stylesheet.
* Additional vendored icon set entries as applications need them.
* A component gallery page (`mirrorwall.gallery`) served by any application in development mode.
