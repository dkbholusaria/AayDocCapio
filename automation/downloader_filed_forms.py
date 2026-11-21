"""Download every form filed by an assessee from e-File > Income Tax Forms.

The portal's "View Filed Forms" page groups filings into category cards per
Income-tax Act tab (2025 / 1961 / Other Acts). Opening a category lists every
filing of that form, and each filing exposes one or more download buttons:
Download Form (PDF or ZIP), Download Receipt (PDF), Download Attachments
(ZIP), Download JSON, Download XML.

Confirmed live on 2026-11-20 (see PlansofThisProject/F-63_evidence/):
  - Form 15CA, 10IE, 10-IC, 35, 3CB-3CD, 3CA-3CD all follow this same shape.
  - Form 3CD is delivered inside the 3CB-3CD / 3CA-3CD ZIP.
  - Portal filenames are not unique across clients, so every saved file is
    prefixed with the form code and acknowledgement number.
"""

import asyncio
import os
import re
from datetime import datetime

from playwright.async_api import Page

from automation.downloader import make_step_logger, update_browser_status
from automation._nav_helpers import open_hamburger

_ACT_TABS = (
    "Forms as per Income Tax Act 2025",
    "Forms as per Income Tax Act 1961",
    "Forms as per Other Acts",
)

_ARTIFACT_BUTTONS = (
    "Download Form",
    "Download Receipt",
    "Download JSON",
    "Download XML",
)

_FORM_RE = re.compile(r"\bForm\s+([0-9]{1,3}[A-Z]*(?:-[A-Z0-9]+)?)", re.I)
_ACK_RE = re.compile(r"Acknowledgement\s+No\.?\s*[:\-]?\s*([0-9]+)", re.I)
_AY_RE = re.compile(r"A\.?\s*Y\.?\s*[:\-]?\s*(\d{4}\s*[-/]\s*\d{2,4})", re.I)
_FY_RE = re.compile(r"Financial\s+Year\s*[:\-]?\s*(\d{4}\s*[-/]\s*\d{2,4})", re.I)
_FILING_DATE_RE = re.compile(
    r"Filing\s+Date\s*[:\-]?\s*(\d{1,2}[-/][A-Za-z]{3}[-/]\d{4})", re.I)
_FILING_TYPE_RE = re.compile(r"Filing\s+Type\s*:\s*([A-Za-z]+)", re.I)


# ── Pure parsing / naming helpers (unit-tested offline) ──────────────────────

def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "")
    return re.sub(r"_+", "_", cleaned).strip("_") or "unknown"


def form_code_from_text(text: str) -> str:
    """Return the portal form code, e.g. '3CB-3CD', '15CA', '35'."""
    match = _FORM_RE.search(text or "")
    return match.group(1) if match else "Unknown_Form"


def filing_year_from_text(text: str) -> str:
    """Reporting period for the filing: FY for 15CA, otherwise AY."""
    lowered = (text or "").lower()
    pattern = _FY_RE if ("financial year" in lowered and "a.y" not in lowered) else _AY_RE
    match = pattern.search(text or "")
    if not match and pattern is _FY_RE:
        match = _AY_RE.search(text or "")
    if not match:
        return "Unknown_Year"
    return safe_name(match.group(1).replace("/", "-").replace(" ", ""))


def parse_filing_text(text: str) -> dict:
    """Pull the stable identifiers out of one filing card's plain text."""
    raw = normalize_space(text)
    ack = _ACK_RE.search(raw)
    filing_date = _FILING_DATE_RE.search(raw)
    filing_type = _FILING_TYPE_RE.search(raw)
    return {
        "ack": ack.group(1) if ack else "",
        "year": filing_year_from_text(raw),
        "filing_date": filing_date.group(1) if filing_date else "",
        "filing_type": filing_type.group(1) if filing_type else "",
        "text": raw,
    }


def filing_stem(form_code: str, parsed: dict) -> str:
    """Unique, filesystem-safe prefix for every artifact of one filing."""
    ack = parsed.get("ack") or ""
    if ack:
        return f"Form_{safe_name(form_code)}_{ack}"
    stamp = parsed.get("filing_date") or datetime.now().strftime("%Y%m%d")
    return f"Form_{safe_name(form_code)}_{safe_name(stamp)}"


def artifact_path(folder: str, stem: str, form_code: str, suggested: str,
                  suffix: str | None = None) -> str:
    """Build a deterministic, collision-free path for one downloaded file.

    Portal names are reused across clients (e.g. 'Form 35_Filed Form.pdf'),
    so they are always prefixed with the filing stem. ``suffix`` is used for
    modal-driven downloads (attachments) that have no suggested filename.
    """
    suggested = suggested or ""
    ext = os.path.splitext(suggested)[1].lower() or ".bin"
    suggested_stem = safe_name(os.path.splitext(os.path.basename(suggested))[0])
    ack = stem.rsplit("_", 1)[-1]
    # Drop the portal's leading "Form <code>_" from its own name — the stem
    # already carries the canonical code. Older filings use variants such as
    # "Form F3CB-3CD_...", so match any Form_<token>_ prefix, not just the
    # exact code seen on the category card.
    stripped = re.sub(r"^Form_[^_]+_", "", suggested_stem, count=1)
    if stripped != suggested_stem:
        suggested_stem = stripped.lstrip("_")
    if suggested_stem == ack or suggested_stem.lower() in ("", "unknown"):
        suggested_stem = ""
    if suffix:
        suggested_stem = safe_name(suffix)
    name = f"{stem}_{suggested_stem}{ext}" if suggested_stem else f"{stem}{ext}"
    return os.path.join(folder, name)


_ARTIFACT_PROBES = {
    "Download Form": "Filed_Form",
    "Download Receipt": "ARN",
    "Download JSON": "JSON",
    "Download XML": "XML",
}


def existing_artifact(folder: str, stem: str, probe: str) -> str | None:
    """Return an already-downloaded path for this artifact, if present."""
    if not os.path.isdir(folder):
        return None
    names = os.listdir(folder)
    if probe in ("JSON", "XML"):
        ext = "." + probe.lower()
        for name in names:
            if name == f"{stem}{ext}" or (
                    name.startswith(stem + "_") and name.lower().endswith(ext)):
                return os.path.join(folder, name)
        return None
    prefix = f"{stem}_{probe}."
    for name in names:
        if name.startswith(prefix):
            return os.path.join(folder, name)
    return None


# ── Portal UI helpers ────────────────────────────────────────────────────────

async def _wait_overlay(page: Page, timeout: int = 20) -> None:
    """Wait for the portal's loading overlay to disappear, if one is shown."""
    try:
        overlay = page.locator(
            ".cdk-overlay-backdrop-showing, .customLoaderBackdrop").first
        if not await overlay.count():
            return
        await overlay.wait_for(state="hidden", timeout=timeout * 1000)
    except Exception:
        pass


async def _stuck_reason(page: Page) -> str:
    """After a failed click, describe any portal overlay that is blocking the
    page (Session Timeout / 'Request not authenticated' / loader). An empty
    string means the page looks clickable, so the failure was filing-specific."""
    try:
        blocked = await page.evaluate("""() => {
            const visible = el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            };
            const parts = [];
            for (const m of document.querySelectorAll('.modal.show')) {
                if (visible(m)) {
                    parts.push(((m.innerText || '').replace(/\\s+/g, ' ')
                        .trim().slice(0, 120)));
                }
            }
            for (const b of document.querySelectorAll(
                    '.cdk-overlay-backdrop-showing, .customLoaderBackdrop')) {
                if (visible(b)) { parts.push('loading overlay'); break; }
            }
            return parts.join(' | ');
        }""")
    except Exception:
        return ""
    text = (blocked or "").lower()
    for key in ("session timeout", "session is about to expire",
                "not authenticated", "session expired",
                "loading overlay"):
        if key in text:
            return key
    return ""


async def _refresh_session(page: Page, step) -> bool:
    """The portal shows a 'Session Timeout' modal during long scans. Clicking
    its Continue button keeps the session alive; closing it or ignoring it
    makes every later click fail."""
    try:
        modals = page.locator(".modal.show")
        count = await modals.count()
        for i in range(count):
            modal = modals.nth(i)
            try:
                if not await modal.is_visible():
                    continue
                text = normalize_space(await modal.inner_text()).lower()
                if not any(k in text for k in (
                        "session timeout", "session is about to expire",
                        "stay logged in", "session time")):
                    continue
                button = modal.locator(
                    "button:has-text('Continue'), button:has-text('Yes'), "
                    "button:has-text('OK')").first
                if await button.count():
                    try:
                        await button.click(force=True, timeout=5000)
                    except Exception:
                        await button.evaluate("b => b.click()")
                    await asyncio.sleep(2)
                    step("Session Timeout refreshed")
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


async def _dismiss_modal(page: Page, step) -> bool:
    """Close any blocking modal. The security modal offers YES (logout) and
    No — always choose No; never click YES. A Session Timeout modal is
    refreshed instead (it must not be closed)."""
    if await _refresh_session(page, step):
        await _wait_overlay(page, timeout=10)
        return True
    try:
        modal = page.locator(".modal.show").first
        if not await modal.count() or not await modal.is_visible():
            return False
        text = normalize_space(await modal.inner_text())
        step(f"Dismissing portal modal: {text[:140]}")
        if "logout" in text.lower() or "security" in text.lower():
            candidates = (".modal.show button:has-text('No')",)
        else:
            candidates = (
                ".modal.show .close",
                ".modal.show button:has-text('Cancel')",
                ".modal.show button:has-text('No')",
                ".modal.show button:has-text('OK')",
            )
        for sel in candidates:
            button = page.locator(sel).first
            if await button.count() and await button.is_visible():
                try:
                    await button.click(force=True, timeout=5000)
                except Exception:
                    await button.evaluate("b => b.click()")
                await asyncio.sleep(1)
                return True
    except Exception as e:
        step(f"Modal dismissal skipped: {e}")
    return False


async def _click_first_visible(page: Page, selector: str, timeout: int = 15000) -> bool:
    locator = page.locator(selector)
    count = await locator.count()
    for i in range(count):
        item = locator.nth(i)
        try:
            if await item.is_visible():
                await item.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


async def navigate_to_filed_forms(page: Page, log_callback) -> Page:
    """Open e-File > Income Tax Forms > View Filed Forms using menu clicks.

    Never navigate by changing window.location.hash: the portal treats that
    as a browser Back/Refresh and shows a "Logout?" security modal.
    """
    step = make_step_logger(log_callback, "FILED-FORMS")
    await _dismiss_modal(page, step)
    await page.evaluate("window.scrollTo(0, 0)")
    await open_hamburger(page, log_callback, "FILED-FORMS")

    for attempt in range(6):
        try:
            await _refresh_session(page, step)
            efile = page.locator("//*[normalize-space(.)='e-File']").first
            await efile.wait_for(state="visible", timeout=20000)
            await efile.click(timeout=15000)
            await asyncio.sleep(1.5)
            break
        except Exception as e:
            if attempt == 5:
                raise
            step(f"e-File menu not ready (attempt {attempt + 1}/6) — {str(e)[:100]}")
            # A blocked click usually means a Session Timeout / loader overlay
            # is covering the nav — refresh it and wait for the spinner.
            await _refresh_session(page, step)
            await _wait_overlay(page, timeout=20)
            await asyncio.sleep(4)

    await _wait_overlay(page, timeout=15)
    itf = page.locator("//*[normalize-space(.)='Income Tax Forms']").first
    await itf.wait_for(state="visible", timeout=20000)
    await itf.hover()
    await asyncio.sleep(1.5)

    clicked = await _click_first_visible(page, "button:has-text('View Filed Forms')")
    if not clicked:
        await itf.click()
        await asyncio.sleep(1)
        clicked = await _click_first_visible(page, "button:has-text('View Filed Forms')")
    if not clicked:
        raise RuntimeError("View Filed Forms menu item was not found.")

    # The SPA takes a few seconds to mount the forms screen; URL and tabs
    # arrive together, so wait for either instead of a fixed sleep.
    for _ in range(40):
        await asyncio.sleep(0.5)
        if "viewFiledForms" in page.url:
            break
        try:
            if await page.locator(".mdc-tab, mat-tab-label").count():
                break
        except Exception:
            pass
    else:
        raise RuntimeError("View Filed Forms page did not load.")
    await asyncio.sleep(2)
    await _dismiss_modal(page, step)
    step("View Filed Forms opened", page)
    return page


async def _maximize_page_size(page: Page, step) -> None:
    """Select the largest available 'Forms per Page' value, if the paginator
    exposes a numeric size selector. Best-effort — pagination still works."""
    try:
        select = page.locator("mat-paginator mat-select").first
        if not await select.count() or not await select.is_visible():
            return
        await select.click(force=True, timeout=4000)
        await asyncio.sleep(0.5)
        options = page.locator("mat-option")
        count = await options.count()
        best_index, best_value = -1, -1
        for i in range(count):
            text = normalize_space(await options.nth(i).inner_text())
            if text.isdigit() and int(text) > best_value:
                best_index, best_value = i, int(text)
        if best_index >= 0:
            await options.nth(best_index).click(timeout=4000)
            await asyncio.sleep(1.5)
            step(f"Forms per Page set to {best_value}")
        else:
            await page.keyboard.press("Escape")
    except Exception as e:
        step(f"Page-size picker skipped: {e}")


async def _pager(page: Page, label: str) -> bool:
    """Click a paginator arrow (Next page / First page) if it is enabled."""
    for sel in (f"button[aria-label='{label}']",):
        button = page.locator(sel).first
        try:
            if (await button.count() and await button.is_visible()
                    and not await button.is_disabled()):
                await button.click()
                await asyncio.sleep(2)
                return True
        except Exception:
            pass
    return False


async def _read_category_cards(page: Page) -> list[str]:
    return await page.evaluate("""() => {
        const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };
        return [...document.querySelectorAll('.eachMatCardStyle')]
            .filter(visible)
            .map(el => (el.innerText || '').replace(/\\s+/g, ' ').trim())
            .filter(Boolean);
    }""")


async def _collect_categories(page: Page, step) -> list[str]:
    await _pager(page, "First page")
    seen: list[str] = []
    for _ in range(50):
        for text in await _read_category_cards(page):
            if text not in seen:
                seen.append(text)
        if not await _pager(page, "Next page"):
            break
    await _pager(page, "First page")
    return seen


async def _open_category(page: Page, category_text: str, step) -> bool:
    await _pager(page, "First page")
    wanted = normalize_space(category_text)
    wanted_prefix = wanted[:80]
    for _ in range(50):
        cards = page.locator(".eachMatCardStyle")
        count = await cards.count()
        for i in range(count):
            card = cards.nth(i)
            try:
                text = normalize_space(await card.inner_text())
            except Exception:
                continue
            if text == wanted or (wanted_prefix and text.startswith(wanted_prefix)):
                await card.scroll_into_view_if_needed()
                await card.click()
                await asyncio.sleep(4)
                await _dismiss_modal(page, step)
                return True
        if not await _pager(page, "Next page"):
            break
    return False


async def _back_to_categories(page: Page, step) -> bool:
    await _refresh_session(page, step)
    if await _click_first_visible(page, "button:has-text('Back')", timeout=10000):
        await asyncio.sleep(3)
        await _dismiss_modal(page, step)
        return True
    return False


# ── Downloading ──────────────────────────────────────────────────────────────

async def _download_click(page: Page, locator, folder: str, stem: str,
                          form_code: str, probe: str, step,
                          label: str) -> tuple[str, str | None]:
    existing = existing_artifact(folder, stem, probe)
    if existing:
        step(f"{label}: already present — skipped")
        return "skipped", existing

    async def _attempt():
        async with page.expect_download(timeout=45000) as info:
            await locator.click(timeout=8000)
        return await info.value

    try:
        await _refresh_session(page, step)
        try:
            download = await _attempt()
        except Exception:
            # A blocked/overlay click can leave the Angular loader spinner
            # running; wait for it to clear before deciding the filing is
            # genuinely stuck (otherwise the next filing is written off too).
            await _wait_overlay(page, timeout=25)
            if await _refresh_session(page, step):
                download = await _attempt()
            else:
                raise
        target = artifact_path(folder, stem, form_code,
                               download.suggested_filename)
        if os.path.exists(target):
            base, ext = os.path.splitext(target)
            n = 2
            while os.path.exists(f"{base}_{n}{ext}"):
                n += 1
            target = f"{base}_{n}{ext}"
        await download.save_as(target)
        step(f"{label}: saved {os.path.basename(target)} "
             f"({os.path.getsize(target)} bytes)")
        return "saved", target
    except Exception as e:
        step(f"{label}: download failed — {str(e)[:160]}")
        # A failed/blocked click often leaves an informational modal or a
        # Session Timeout overlay behind, which would then block every later
        # button on the page. Clear it before moving on.
        await _dismiss_modal(page, step)
        stuck = await _stuck_reason(page)
        if stuck:
            raise RuntimeError(f"portal blocked: {stuck}")
        return "failed", None


async def _download_attachments(page: Page, folder: str, stem: str,
                                button, step) -> list[str]:
    """Open the Attachments modal, tick every file, and save whatever the
    modal's Download button produces (usually one ZIP)."""
    if os.path.isdir(folder) and any(
            name.startswith(stem + "_Attachments")
            for name in os.listdir(folder)):
        step("Attachments: already present — skipped")
        return []

    pending: list[str] = []
    seq = {"n": 0}

    async def _save(download):
        seq["n"] += 1
        ext = os.path.splitext(download.suggested_filename)[1].lower() or ".zip"
        suffix = "Attachments" if seq["n"] == 1 else f"Attachments_{seq['n']}"
        path = os.path.join(folder, f"{stem}_{suffix}{ext}")
        try:
            await download.save_as(path)
            pending.append(path)
            step(f"Attachments: saved {os.path.basename(path)} "
                 f"({os.path.getsize(path)} bytes)")
        except Exception as e:
            step(f"Attachments: save failed — {e}")

    def _handler(download):
        asyncio.create_task(_save(download))

    page.on("download", _handler)
    try:
        await _refresh_session(page, step)
        await button.click(timeout=8000)
        await asyncio.sleep(2)
        modal = page.locator("#attachmentModel")
        try:
            await modal.wait_for(state="visible", timeout=8000)
        except Exception:
            step("Attachments: modal did not open")
            return []

        checkboxes = modal.locator("mat-checkbox input[type='checkbox']")
        count = await checkboxes.count()
        for i in range(count):
            box = checkboxes.nth(i)
            try:
                if not await box.is_checked():
                    await box.check(force=True)
            except Exception:
                pass
        await asyncio.sleep(1)

        modal_download = modal.locator("button:has-text('Download')").first
        if not await modal_download.count() or await modal_download.is_disabled():
            step("Attachments: modal Download button is unavailable")
            return []
        await modal_download.click(timeout=8000)

        for i in range(25):
            await asyncio.sleep(1)
            if pending:
                break
            if i and i % 5 == 0:
                await _refresh_session(page, step)
        if not pending:
            step("Attachments: no file was produced (portal may deliver these "
                 "individually inside the ZIP)")
        return pending
    except Exception as e:
        step(f"Attachments: failed — {str(e)[:160]}")
        await _dismiss_modal(page, step)
        return []
    finally:
        try:
            page.remove_listener("download", _handler)
        except Exception:
            pass
        close = page.locator("#attachmentModel .close").first
        try:
            if await close.count() and await close.is_visible():
                await close.click()
                await asyncio.sleep(1)
        except Exception:
            pass


async def _process_filing(page: Page, sub_card, form_code: str,
                          folder_root: str, step, saved: list[dict],
                          skipped: dict, warnings: list[str]) -> None:
    text = normalize_space(await sub_card.inner_text())
    parsed = parse_filing_text(text)
    folder = os.path.join(folder_root, safe_name(form_code), parsed["year"])
    os.makedirs(folder, exist_ok=True)
    stem = filing_stem(form_code, parsed)
    step(f"Filing {parsed['ack'] or '(no ack)'} — {parsed['year']} "
         f"{parsed['filing_type']}".strip())

    for label in _ARTIFACT_BUTTONS:
        button = sub_card.locator(f"button:has-text('{label}')").first
        try:
            if not await button.count() or not await button.is_visible():
                continue
            if await button.is_disabled():
                step(f"{label}: unavailable for this filing — skipped")
                continue
            status, path = await _download_click(
                page, button, folder, stem, form_code,
                _ARTIFACT_PROBES[label], step, label)
            if status == "saved" and path:
                saved.append({"path": path, "form": form_code,
                              "year": parsed["year"], "ack": parsed["ack"],
                              "kind": label})
            elif status == "skipped":
                skipped["n"] += 1
            elif status == "failed":
                warnings.append(
                    f"{parsed['ack'] or form_code}: {label} failed")
        except Exception as e:
            raise RuntimeError(f"{form_code}: {str(e)[:120]}") from e

    attachments = sub_card.locator(
        "button:has-text('Download Attachments')").first
    try:
        if await attachments.count() and await attachments.is_visible():
            produced = await _download_attachments(
                page, folder, stem, attachments, step)
            for path in produced:
                saved.append({"path": path, "form": form_code,
                              "year": parsed["year"], "ack": parsed["ack"],
                              "kind": "Download Attachments"})
            if not produced and any(
                    name.startswith(stem + "_Attachments")
                    for name in os.listdir(folder)):
                skipped["n"] += 1
    except Exception as e:
        warnings.append(
            f"{parsed['ack'] or form_code}: attachments — {str(e)[:100]}")


async def _process_category(page: Page, category_text: str, download_root: str,
                            step, saved: list[dict], skipped: dict,
                            warnings: list[str], is_running) -> int:
    form_code = form_code_from_text(category_text)
    await _maximize_page_size(page, step)
    filings = 0
    page_no = 0
    while page_no < 50:
        cards = page.locator(".subCard")
        count = await cards.count()
        step(f"{form_code}: {count} filing(s) on page {page_no + 1}")
        for i in range(count):
            if is_running is not None and not is_running():
                return filings
            try:
                await _refresh_session(page, step)
                await _process_filing(page, cards.nth(i), form_code,
                                      download_root, step, saved, skipped,
                                      warnings)
                filings += 1
            except Exception as e:
                warnings.append(f"{form_code}: filing {i + 1} — {str(e)[:120]}")
        if not await _pager(page, "Next page"):
            break
        page_no += 1
    return filings


async def download_filed_forms(page: Page, download_root: str, log_callback,
                               pan: str = "", is_running=None
                               ) -> tuple[bool, str, list[dict]]:
    """Download every filed Income-tax form for the already-logged-in client.

    Returns ``(ok, msg, saved)`` — same broad contract as the other
    downloaders. ``ok=False`` means navigation failed outright. No forms is
    a successful empty result (``msg`` starts with "No filed IT forms").
    """
    step = make_step_logger(log_callback, "FILED-FORMS")
    saved: list[dict] = []
    warnings: list[str] = []
    skipped = {"n": 0}
    filings_total = 0

    try:
        await navigate_to_filed_forms(page, log_callback)
    except Exception as e:
        step(f"Navigation failed: {e}")
        return False, f"Navigation failed: {str(e)[:120]}", []

    await update_browser_status(page, "Filed IT Forms: Scanning portal...")
    tabs_seen = 0
    for tab_label in _ACT_TABS:
        if is_running is not None and not is_running():
            break
        try:
            tab = page.locator(
                f".mdc-tab:has-text('{tab_label}'), mat-tab-label:has-text('{tab_label}')"
            ).first
            if not await tab.count():
                continue
            tabs_seen += 1
            await tab.click()
            await asyncio.sleep(4)
            await _dismiss_modal(page, step)
            await _maximize_page_size(page, step)

            categories = await _collect_categories(page, step)
            step(f"{tab_label}: {len(categories)} form category card(s)")
            for category in categories:
                if is_running is not None and not is_running():
                    break
                form_code = form_code_from_text(category)
                await update_browser_status(
                    page, f"Filed IT Forms: {form_code}...")
                if not await _open_category(page, category, step):
                    warnings.append(f"{form_code}: category could not be opened")
                    continue
                try:
                    filings_total += await _process_category(
                        page, category, download_root, step, saved, skipped,
                        warnings, is_running)
                finally:
                    if not await _back_to_categories(page, step):
                        step(f"{form_code}: Back button missing — re-opening list")
                        await navigate_to_filed_forms(page, log_callback)
                        again = page.locator(
                            f".mdc-tab:has-text('{tab_label}'), "
                            f"mat-tab-label:has-text('{tab_label}')").first
                        if await again.count():
                            await again.click()
                            await asyncio.sleep(3)
        except Exception as e:
            step(f"{tab_label}: skipped — {str(e)[:160]}")
            warnings.append(f"{tab_label}: {str(e)[:100]}")

    await update_browser_status(page, "Filed IT Forms: Complete")
    step(f"Summary: {filings_total} filing(s), {len(saved)} new file(s), "
         f"{skipped['n']} already present, {len(warnings)} warning(s)")

    if tabs_seen == 0:
        return False, "View Filed Forms page did not expose any Act tab.", []
    if filings_total == 0 and not warnings:
        return True, "No filed IT forms found", []
    if not saved:
        if skipped["n"]:
            return True, f"Up to date ({skipped['n']} file(s) already present)", []
        if warnings:
            return False, "; ".join(warnings[:3]), []
        return True, "No filed IT forms found", []
    if warnings:
        return True, f"{len(warnings)} warning(s): {'; '.join(warnings[:3])}", saved
    return True, "", saved
