# Architecture Decision Records

Each ADR captures one significant technical choice: what was decided, why, and what was rejected.

---

## ADR-01 — UI framework: PyQt6 (replacing CustomTkinter)

**Date:** 2026-05 (v1.0.0)  
**Status:** Accepted

### Context
The initial prototype was built on CustomTkinter. As the feature set grew (sortable tables, modal dialogs, complex theming, per-row custom delegates), CustomTkinter's widget set became a bottleneck — complex layouts required awkward workarounds.

### Decision
Rewrite the UI layer in **PyQt6**.

### Reasons
- Native `QTableWidget` with full drag-to-resize, sort, delegate, and hyperlink support
- `QDialog` modal pattern for add/edit forms
- `QMenu` / `QToolButton` for the ••• row action menu and Run split-button
- Comprehensive stylesheet theming with a single `build_stylesheet()` call
- Signals/slots make thread-safe UI updates (from background download worker) straightforward

### Rejected alternatives
- **CustomTkinter:** Insufficient table and dialog primitives
- **tkinter (stdlib):** Even more limited; no stylesheet theming
- **Electron / web UI:** Cross-language bridge complexity; much larger distribution size

---

## ADR-02 — Browser automation: Playwright (not Selenium)

**Date:** 2026-04 (initial prototype)  
**Status:** Accepted

### Context
The ITD e-Filing portal is an Angular SPA. Element selectors must wait for the framework to hydrate; navigation events are asynchronous.

### Decision
Use **Playwright** (Python async API).

### Reasons
- `page.wait_for_selector()` and auto-wait semantics handle Angular hydration without explicit sleeps
- `page.expect_download()` context manager makes download capture deterministic
- `BrowserContext` isolation — each client gets a fresh context with separate cookies/localStorage, preventing session bleed
- Built-in `page.goto()` timeout and network-idle wait modes
- Async model keeps the Qt event loop alive via `asyncio.run()` in a background thread

### Rejected alternatives
- **Selenium:** No native download event API; context isolation is harder; slower async story
- **Requests + BeautifulSoup:** Portal is a JavaScript SPA; server-side HTML scraping is not viable

---

## ADR-03 — Must use real Google Chrome (not bundled Chromium) for AIS/TIS

**Date:** 2026-05  
**Status:** Accepted

### Context
After fixing the `expect_download` bug (see ADR-06), AIS downloads worked instantly — but only when launched with `channel="chrome"`. With Playwright's bundled Chromium, the portal's Angular download handlers silently failed.

### Decision
Launch Chrome with `channel="chrome"` for all AIS/TIS operations. Fall back to bundled Chromium for 26AS only, with a user-visible warning that AIS/TIS requires Chrome.

### Reasons
- Confirmed by inspecting a competitor's Node/Electron tool: their logs showed AIS only downloaded after `npx playwright install chrome` — i.e., after real Chrome was installed
- The Insight portal likely uses Chrome-specific APIs or fingerprints the user-agent in ways that differ between Chrome and Chromium
- Headless real-Chrome works (tested for 2025-26, 2023-24) — the requirement is the engine, not a visible window

### Implications
- Google Chrome must be installed on end-user machines
- Documented prominently in README and installer

---

## ADR-04 — Fixed viewport 1600×900 (no `--start-maximized`)

**Date:** 2026-05  
**Status:** Accepted

### Context
Early versions passed `--start-maximized` to Chrome. The ITD portal's responsive nav collapsed into a hamburger menu at certain widths, and `--start-maximized` conflicted with Playwright's fixed-viewport model, distorting the aspect ratio and pushing the nav off-screen.

### Decision
Use `viewport={"width": 1600, "height": 900}` with no `--start-maximized`, no `bypass_csp`.

### Reasons
- At 1600px the ITD dashboard nav is consistently visible; 1280px sometimes collapses it
- Playwright's viewport model is predictable and reproducible; `--start-maximized` depends on the OS display resolution
- Even at 1600px the nav can be scrolled out of view — the download flow now includes `window.scrollTo(0,0)` + hamburger fallback before clicking nav items

---

## ADR-05 — No pandas in vault; use openpyxl + csv directly

**Date:** 2026-05 (v1.0.0)  
**Status:** Accepted

### Context
The initial requirements listed pandas as a dependency for bulk import/export.

### Decision
Remove pandas. Use **openpyxl** for `.xlsx` and Python's stdlib **csv** for `.csv`.

### Reasons
- Pandas adds ~25 MB to the frozen binary (NumPy transitive dep); openpyxl adds ~3 MB
- The import/export operations are simple row-by-row reads and writes — pandas' DataFrame abstraction is unnecessary overhead
- Fewer dependencies reduces the attack surface and installer size

### Implications
- `vault.import_bulk()` iterates rows with `ws.iter_rows(values_only=True)` — sufficient for the use case
- Date parsing (Excel date serials, string normalisation) is handled explicitly in `_normalise_dob()`

---

## ADR-06 — `expect_download` must be called on Page, not BrowserContext

**Date:** 2026-05 (bug discovery)  
**Status:** Accepted (documents a critical past mistake)

### Context
For weeks, AIS downloads appeared to "succeed" in logs but no file was ever saved. Every click strategy was tried (see DEVELOPMENT_LOG.md §4). The root cause was a one-line API misuse:

```python
# WRONG — BrowserContext has no expect_download
async with portal.context.expect_download() as dl_info:
    ...
# CORRECT — Page has expect_download
async with portal.expect_download() as dl_info:
    ...
```

A bare `except` block swallowed the resulting `AttributeError`, and the code fell through to "queued / Reference ID: N/A". The download was never attempted.

### Decision
Fix all 7 call sites across `downloader_ais_tis.py` and `downloader.py`. Add the rule to CONTRIBUTING.md. Never use bare `except` in automation code — always catch specific exception types so API misuse surfaces immediately.

### Lesson
Once fixed, AIS downloaded instantly for every year tested. The elaborate two-phase "Request → wait → Activity History" flow, implemented as a fallback, is rarely needed in practice.

---

## ADR-07 — Nuitka for Windows builds (not PyInstaller)

**Date:** 2026-05 (first Windows release)  
**Status:** Accepted

### Context
PyInstaller was the original packaging choice. It bundles Python bytecode into a single exe.

### Decision
Switch to **Nuitka** (`--standalone` mode) for Windows distribution.

### Reasons
- Nuitka compiles Python to C and then to native machine code — substantially lower false-positive rate with antivirus engines compared to PyInstaller (which wraps bytecode in a known exe structure that AV tools frequently flag)
- Smaller startup time
- PyInstaller's `--onefile` mode extracts to a temp directory on every launch, which some corporate AV policies block

### Trade-offs
- Nuitka build time is longer (~5 min vs ~1 min)
- Nuitka requires `ordered-set` and `zstandard` as build-time deps
- Debugging compiled output is harder — source runs are always preferred during development

---

## ADR-08 — Per-client BrowserContext isolation with 5-second cooldown

**Date:** 2026-05  
**Status:** Accepted

### Context
Early prototypes reused a single browser context across clients, which caused session data to bleed between clients — a logged-out client's cookies could interfere with the next client's login.

### Decision
Create a **fresh BrowserContext** for every client. Destroy it immediately after logout. Insert a **5-second cooldown** between clients.

### Reasons
- Separate cookies, localStorage, and session state per client: no bleed
- The ITD portal enforces a `loginMaxAttemptsPopup` rate limit on rapid consecutive logins; 5 seconds reduces the risk materially
- If the rate-limit popup does fire, `auth.py` adds an extra 6-second recovery pause to let the Angular router re-initialise

### Implications
- Slightly longer total batch time, but far more reliable
- Live countdown (`⏸ Cooling down... 5s / 4s / 3s / …`) shown in the Batch Progress dialog
