"""
automation/downloader_e_proceedings.py
=======================================
F-60 — download documents from the ITD e-Filing portal's e-Proceedings
section (top bar: Pending Actions → e-Proceedings) for one already-logged-in
client. Everything confirmed live on 2026-11-18 across three test PANs —
see PlansofThisProject/F-60_e_proceedings_download.md for the exploration
record; captured HTML fixtures in /tmp/f60_explore (transient).

Flow per client:
  1. Pending Actions hover menu → e-Proceedings (in-page SPA route,
     #/dashboard/eProceedings). The menu item is a <button> — clicking the
     inner <span> does nothing (confirmed live).
  2. Read the "For your Action" tab, then the "For your Information" tab.
     Each tab renders a list of proceeding cards (div.card-container —
     the page's single outer mat-card wraps the WHOLE list, so per-card
     anchoring must use .card-container) with a
     "View Notices/Orders (n)" button per proceeding.
  3. Per proceeding: open View Notices/Orders
     (#/dashboard/eProceedings/viewNotices/all) — one block per notice
     (Reference ID, section, DIN, Description, Issued On, Response Due
     Date). Download each notice's PDF: "Notice/Letter Pdf" button →
     in-page #/dashboard/eProceedings/viewNotices/viewDetailedNotice —
     attachment card(s) with .subtitle2.fileName name + button.downloadPdf
     download trigger.
  4. If a notice shows "View Response" (client already replied): open it
     (#/dashboard/eProceedings/viewNotices/viewResponse) and download each
     attachment (span.hyperLink, direct download on click) plus the
     "Acknowledgement" button (aria-label="Download Acknowledgement").
  5. PDFs are NOT user-password-protected (confirmed 20/20 plain during
      exploration). A few client-uploaded response attachments carry
      owner-only encryption (open without password, /Encrypt set) — those
      are re-saved decrypted in place by _strip_owner_encryption.

Output layout: <client_year_dir>/e-Proceedings/<Proc Name>-<issued list
index>/ keeps files from different proceedings apart (proceeding names
repeat — "Issue Letter" x4 observed on one PAN). Files keep the
portal-suggested filenames, which already embed PAN/type/reference/date
(e.g. "7000000082960357_..._[REDACTED_PAN]_Notice us 221_...(1)_01122023.pdf").
Duplicate filenames WITHIN one proceeding (e.g. response attachments re-
downloaded) are suffixed (1), (2)… before the extension.

Each proceeding folder also gets `_meta.json` (written best-effort, never
aborts the run): the proceeding's name/AY/status + download timestamp, and
one entry per notice with reference ID, description, section ("Notice u/s"
line), Issued On / Response Due Date, responded flag ("View Response" button
seen = client already replied), "Response viewed by AO on" date, order flag
("order" in description) and the relative paths of the saved notice/response
files — so the UI can show issue dates, due dates and responded status
without re-parsing portal pages or PDFs.

e-Proceedings is not year-scoped (many proceedings show "Assessment Year :
Not Available"), so this module downloads everything found in one pass and
ignores the batch's year selection — the handler records the same terminal
status against every selected year row so the grid/progress stay consistent.

Never aborts the whole run for one failed artifact: every download is
individually try/except'd (same pattern as downloader_filed_returns).
"""
import asyncio
import json
import os
import re
from datetime import datetime

from playwright.async_api import Page

from automation.downloader import make_step_logger, update_browser_status

# e-Proceedings SPA route fragments (confirmed live)
_EPROC_HASH = "#/dashboard/eProceedings"
_VIEW_NOTICES_HASH = "#/dashboard/eProceedings/viewNotices"
_STEPPER_STATES = ("error", "done", "edit", "number")


def _sanitize_name(raw: str, fallback: str = "document") -> str:
    """Make a portal filename/label safe for the filesystem (names arrive
    with spaces and parens — both kept; only path-hostile chars replaced)."""
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", (raw or "").strip())
    return cleaned[:150] if cleaned else fallback


async def _dismiss_portal_popups(page: Page, step) -> None:
    """Best-effort dismissal of the recurring info modals seen during
    exploration ("account deactivated" OK, Outstanding Demand Close,
    Disclaimer Continue). Never raises."""
    for _ in range(4):
        try:
            clicked = await page.evaluate(
                """() => {
                for (const b of document.querySelectorAll(
                        '.cdk-overlay-pane button, .modal.show button, .modal button')) {
                    const r = b.getBoundingClientRect();
                    if (r.width === 0) continue;
                    const t = (b.innerText || '').trim();
                    if (/^(OK|Close|Confirm|Continue Session|Proceed)$/.test(t)) {
                        b.click(); return t;
                    }
                }
                return null;
            }"""
            )
        except Exception:
            return
        if not clicked:
            return
        step(f"Dismissed portal popup: {clicked}")
        await asyncio.sleep(1.2)


async def navigate_to_e_proceedings(page: Page, log_callback) -> Page:
    """One-time navigation: top-bar 'Pending Actions' hover menu →
    'e-Proceedings' button. Returns the same page on the e-Proceedings
    route. Raises on failure (caller decides how to report it)."""
    step = make_step_logger(log_callback, "EPROC")
    step("Navigating: Pending Actions → e-Proceedings")
    await update_browser_status(page, "e-Proceedings: Opening section...")

    # The hover menu needs its item clicked as a BUTTON — confirmed live that
    # clicking the inner <span> leaves the dashboard unchanged.
    pa_btn = page.locator("a:has-text('Pending Actions')").first
    await pa_btn.hover(timeout=30000)
    await asyncio.sleep(2)

    item = page.locator(
        ".cdk-overlay-pane button:has-text('e-Proceedings'), "
        ".cdk-overlay-pane [role='menuitem']:has-text('e-Proceedings')"
    ).first
    await item.wait_for(state="visible", timeout=15000)
    before_url = page.url
    try:
        await item.click(timeout=10000)
    except Exception:
        # Overlay can be intercepted by a stale backdrop — retry via JS on
        # the <button> ancestor (the span itself does nothing).
        step("Direct click failed — retrying via JS on button ancestor")
        await page.evaluate(
            """() => {
            const els = [...document.querySelectorAll('.cdk-overlay-pane *')];
            const t = els.find(e => (e.innerText || '').trim() === 'e-Proceedings'
                                    && e.children.length === 0);
            if (!t) return;
            let p = t;
            while (p && p.tagName !== 'BUTTON' && p.tagName !== 'A'
                   && !(p.getAttribute && p.getAttribute('role') === 'menuitem')) {
                p = p.parentElement;
            }
            (p || t).click();
        }"""
        )
    await asyncio.sleep(3)
    if page.url == before_url and _EPROC_HASH not in page.url:
        await asyncio.sleep(5)  # SPA routing can lag a beat — give it once more
    if _EPROC_HASH not in page.url:
        raise RuntimeError(
            f"e-Proceedings did not open (still on {page.url.split('#')[-1]})")
    step("e-Proceedings list loaded")
    await asyncio.sleep(4)  # allow card list render + counts to settle
    return page


def _parse_proceeding_card_text(raw: str) -> dict | None:
    """Parse one proceeding card's innerText into its metadata. Pure function
    (unit-testable against captured fixtures). Returns None for non-cards.
    Card text shape (confirmed live):
        Proceeding Name :
        Issue Letter
        Assessment Year :
        Not Available
        PAN
        [REDACTED_PAN]
        Name of Assessee
        [REDACTED_NAME]
        Proceeding Status
        Open
        ..."""
    # None only when the Proceeding Name LABEL is absent (not a card);
    # a present label with a missing/blank value line yields "".
    if not re.search(r"Proceeding Name\s*:?", raw):
        return None

    known_labels = ("Proceeding Name", "Assessment Year", "Proceeding Status",
                    "PAN", "Name of Assessee", "Financial Year",
                    "Applicable Act", "Proceeding Limitation Date")

    def _field(label):
        # Value on the same line after the colon ('Assessment Year : 2016-17')
        # or on the next line; a blank/absent value line stays "".
        m = re.search(rf"{re.escape(label)}[ \t]*:?[ \t]*([^\n]*)\n([^\n]*)", raw)
        if not m:
            return ""
        value = m.group(1).strip()
        if not value:
            nxt = m.group(2).strip()
            if nxt and nxt.rstrip(":").strip() not in known_labels:
                value = nxt
        return value

    return {
        "name": _field("Proceeding Name"),
        "ay": _field("Assessment Year"),
        "status": _field("Proceeding Status"),
    }


def _parse_notices_page_text(raw: str) -> list[dict]:
    """Split a View Notices page's innerText into per-notice metadata.
    Pure function (unit-testable). Each notice block starts at
    'Notice/ Communication Reference ID : <id>' and carries
    'Description : [ITBA]<desc>', 'Issued On : <date>' and optionally
    'Response Due Date : <date>' plus button labels.

    Extra per-block fields (confirmed live on 40_fyi0_body.txt /
    40_p6_Assessment_Proceedin_body.txt):
      - the section number line appears ABOVE the 'Notice u/s' label
        (e.g. "250\\nNotice u/s", "142(1)\\nNotice u/s");
      - 'View Response' button => client HAS responded, 'Submit Response'
        => not yet;
      - 'Response viewed by AO on : <date>' when the AO has seen it."""
    notices: list[dict] = []
    blocks = re.split(r"Notices?/?\s*Communication Reference ID\s*:\s*", raw)[1:]
    for block in blocks:
        ref = (block.splitlines() or [""])[0].strip()
        desc_m = re.search(r"Description\s*:\s*\[ITBA\]\s*([^\n]+)", block)
        issued_m = re.search(r"Issued On\s*:\s*([^\n]+)", block)
        due_m = re.search(r"Response Due Date\s*:\s*([^\n]+)", block)
        sec_m = re.search(r"\n(\d{1,4}[A-Z]?(?:\([0-9A-Za-z]+\))?)\nNotice u/s",
                          block)
        ao_m = re.search(r"Response viewed by AO on\s*:\s*([^\n]+)", block)
        description = desc_m.group(1).strip() if desc_m else ""
        notices.append({
            "ref_id": ref,
            "description": description,
            "issued_on": issued_m.group(1).strip() if issued_m else "",
            "response_due": due_m.group(1).strip() if due_m else "",
            "responded": "View Response" in block,
            "section": sec_m.group(1) if sec_m else "",
            "viewed_by_ao": ao_m.group(1).strip() if ao_m else "",
            "is_order": "order" in description.lower(),
        })
    return notices


def _build_proc_meta(proc_meta: dict, notices: list[dict],
                     notice_files: dict[int, list[str]],
                     response_files: dict[int, list[str]],
                     downloaded_at: str) -> dict:
    """Assemble the per-proceeding `_meta.json` payload. Pure function
    (unit-testable). notice_files/response_files map the download loop
    index k (0-based) to that notice's saved basenames; notice k falls
    back to {} when the portal rendered fewer parseable blocks than
    downloadable buttons. File paths are stored relative to the
    proceeding dir ('notice-NN/<file>', 'response-NN/<file>')."""
    entries: list[dict] = []
    indices = sorted(set(notice_files) | set(response_files)
                     | set(range(len(notices))))
    for k in indices:
        src = notices[k] if k < len(notices) else {}
        entry = {
            "index": k + 1,
            "ref_id": src.get("ref_id", ""),
            "description": src.get("description", ""),
            "issued_on": src.get("issued_on", ""),
            "response_due": src.get("response_due", ""),
            "responded": bool(src.get("responded", False)),
            "section": src.get("section", ""),
            "viewed_by_ao": src.get("viewed_by_ao", ""),
            "is_order": bool(src.get("is_order", False)),
            "files": [f"notice-{k + 1:02d}/{os.path.basename(p)}"
                      for p in notice_files.get(k, [])],
            "response_files": [f"response-{k + 1:02d}/{os.path.basename(p)}"
                               for p in response_files.get(k, [])],
        }
        entries.append(entry)
    return {
        "proceeding": {
            "name": proc_meta.get("name", ""),
            "ay": proc_meta.get("ay", ""),
            "status": proc_meta.get("status", ""),
        },
        "downloaded_at": downloaded_at,
        "notices": entries,
    }


async def _read_proceedings_on_active_tab(page: Page, step) -> list[dict]:
    """Read the currently-rendered proceeding cards with their positions.
    Cards render only for the ACTIVE tab — caller switches tabs and calls
    this again. Anchored on each card's 'View Notices/Orders' BUTTON (not
    the card list index): a card without a view button is skipped, and the
    returned index is the button's own position among all visible view
    buttons, so page.locator(...).nth(index) always opens the right
    proceeding. The per-proceeding card is div.card-container — the page
    has ONE outer mat-card wrapping the entire tab list, so closest
    ('mat-card') would return the same wrapper for every button (verified
    against live HTML 2026-11-18). Returns
    [{'button_index', 'name', 'ay', 'status'}]."""
    cards = await page.evaluate(
        """() => {
        const out = [];
        const viewBtns = [...document.querySelectorAll('button')]
            .filter(b => b.getBoundingClientRect().width > 0
                         && !b.disabled
                         && /View Notices\\/Orders/.test(b.innerText || ''));
        for (let bi = 0; bi < viewBtns.length; bi++) {
            let card = viewBtns[bi].closest('.card-container')
                       || viewBtns[bi].closest('mat-card');
            if (!card) continue;
            const nameEl = card.querySelector('.heading5.mNoWrap.mEclipse');
            const txt = card.innerText || '';
            const statusM = txt.match(/Proceeding Status\\s*:?\\s*\\n?\\s*([^\\n]+)/);
            const ayM = txt.match(/Assessment Year\\s*:?\\s*\\n?\\s*([^\\n]+)/);
            out.push({
                button_index: bi,
                name: nameEl ? (nameEl.innerText || '').trim() : '',
                ay: ayM ? ayM[1].trim() : '',
                status: statusM ? statusM[1].trim() : '',
            });
        }
        return out;
    }"""
    )
    return [
        {"button_index": c.get("button_index", i), "name": c.get("name", ""),
         "ay": c.get("ay", ""), "status": c.get("status", "")}
        for i, c in enumerate(cards)
    ]


async def _download_attachments_on_page(page: Page, step, save_dir: str, tag: str) -> list[str]:
    """On a Detailed Notices / View Response page, download every attachment
    card / hyperLink with expect_download. Returns list of saved paths.
    Duplicate portal filenames get (n) suffixes rather than overwriting.
    Some portal-served PDFs (client-uploaded response attachments) carry
    owner-only encryption (open without a password, but /Encrypt present);
    those are re-saved decrypted in-place so downstream consumers see plain
    PDFs — live-confirmed on [REDACTED_PAN] 2026-11-18."""
    saved: list[str] = []
    os.makedirs(save_dir, exist_ok=True)

    # (a) attachment cards with explicit Download buttons (detailed notice view)
    dl_btns = page.locator("button.downloadPdf")
    n = await dl_btns.count()
    step(f"Attachment download buttons found: {n}")
    for k in range(n):
        try:
            async with page.expect_download(timeout=30000) as dl_info:
                await dl_btns.nth(k).click(timeout=10000)
            download = await dl_info.value
            fname = _sanitize_name(download.suggested_filename or f"{tag}.pdf")
            path = _dedupe_path(save_dir, fname)
            await download.save_as(path)
            _strip_owner_encryption(path)
            saved.append(path)
            step(f"[Victory] Saved: {os.path.basename(path)}")
        except Exception as e:
            step(f"[Warning] Attachment download {k} failed: {e}")

    # (b) response attachments (span.hyperLink, filename ends .pdf) — direct
    # download on click (confirmed live in View Response)
    links = page.locator("span.hyperLink")
    ln = await links.count()
    for k in range(ln):
        try:
            label = (await links.nth(k).inner_text()).strip()
        except Exception:
            continue
        if not label.lower().endswith(".pdf"):
            continue
        try:
            async with page.expect_download(timeout=30000) as dl_info:
                await links.nth(k).click(timeout=10000)
            download = await dl_info.value
            fname = _sanitize_name(download.suggested_filename or label)
            path = _dedupe_path(save_dir, fname)
            await download.save_as(path)
            _strip_owner_encryption(path)
            saved.append(path)
            step(f"[Victory] Saved response attachment: {os.path.basename(path)}")
        except Exception as e:
            step(f"[Warning] Response attachment '{label}' failed: {e}")

    # (c) Acknowledgement button (View Response page)
    ack = page.locator("button[aria-label='Download Acknowledgement']")
    if await ack.count():
        try:
            async with page.expect_download(timeout=30000) as dl_info:
                await ack.first.click(timeout=10000)
            download = await dl_info.value
            fname = _sanitize_name(download.suggested_filename or "Acknowledgement.pdf")
            path = _dedupe_path(save_dir, fname)
            await download.save_as(path)
            _strip_owner_encryption(path)
            saved.append(path)
            step(f"[Victory] Saved acknowledgement: {os.path.basename(path)}")
        except Exception as e:
            step(f"[Warning] Acknowledgement download failed: {e}")

    return saved


def _dedupe_path(save_dir: str, fname: str) -> str:
    base, ext = os.path.splitext(fname)
    candidate = os.path.join(save_dir, fname)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(save_dir, f"{base} ({n}){ext}")
        n += 1
    return candidate


def _strip_owner_encryption(path: str) -> None:
    """If a saved PDF is encrypted but opens WITHOUT a password (owner-only
    restrictions, common on client-uploaded response attachments), re-save
    it decrypted in place. Files needing a real password are left untouched
    (unlock_pdf handles those at a higher layer with PAN+DOB candidates).
    Never raises — worst case the original file is kept as downloaded."""
    try:
        import pikepdf
    except ImportError:
        return
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if b"/Encrypt" not in raw:
            return
        with pikepdf.open(path) as pdf:  # raises PasswordError if pw needed
            tmp = path + ".plain.tmp"
            pdf.save(tmp)
        os.replace(tmp, path)
    except Exception:
        try:
            tmp = path + ".plain.tmp"
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


async def _resolve_viewer_page(page: Page, before_pages) -> Page:
    """Return the page the detail viewer opened in. The detailed-notice and
    View Response screens were in-page during the final exploration run but
    popups in earlier runs — never trust either; check the context's page
    set and prefer a NEW page (the popup), falling back to the main page."""
    try:
        pages = [p for p in page.context.pages if p is not page]
        if pages:
            popup = pages[-1]
            try:
                if not popup.is_closed():
                    await popup.wait_for_load_state(
                        "domcontentloaded", timeout=8000)
            except Exception:
                pass
            return popup
    except Exception:
        pass
    return page


async def _close_extra_pages(page: Page) -> None:
    """Close any popup pages the portal left behind, keeping `page` alive."""
    try:
        for p in page.context.pages:
            if p is not page:
                try:
                    await p.close()
                except Exception:
                    pass
    except Exception:
        pass


async def _process_proceeding(page: Page, button_index: int, proc_meta: dict,
                              download_root: str, log_callback, pan: str,
                              step) -> tuple[list[str], list[str]]:
    """Open one proceeding's View Notices/Orders and download every
    document reachable from it. Returns (saved_paths, warnings)."""
    saved: list[str] = []
    warns: list[str] = []
    notice_files: dict[int, list[str]] = {}
    response_files: dict[int, list[str]] = {}
    proc_label = _sanitize_name(proc_meta.get("name") or f"Proceeding {button_index + 1}")
    proc_dir = os.path.join(download_root, f"{button_index + 1:02d}-{proc_label}")
    os.makedirs(proc_dir, exist_ok=True)

    try:
        btn = page.locator("button:has-text('View Notices/Orders')").nth(button_index)
        await btn.click(timeout=15000)
    except Exception as e:
        step(f"[Warning] Could not open proceeding {button_index + 1}: {e}")
        return [], [f"{proc_label}: could not open ({str(e)[:60]})"]
    await asyncio.sleep(5)
    await _dismiss_portal_popups(page, step)
    await _close_extra_pages(page)

    # Notices list — parse for the record; navigation confirmed in-page
    body_text = ""
    try:
        body_text = await page.inner_text("body")
    except Exception:
        pass
    notices = _parse_notices_page_text(body_text)
    step(f"Proceeding '{proc_label}': {len(notices)} notice block(s)")

    # Each notice has its own 'Notice/Letter Pdf' button — download each
    pdf_btns = page.locator("button:has-text('Notice/Letter Pdf')")
    n_pdfs = await pdf_btns.count()
    step(f"Notice/Letter Pdf buttons: {n_pdfs}")
    for k in range(n_pdfs):
        try:
            await pdf_btns.nth(k).click(timeout=15000)
        except Exception as e:
            step(f"[Warning] Notice PDF button {k} click failed: {e}")
            warns.append(f"{proc_label}: notice PDF {k + 1} click failed")
            continue
        await asyncio.sleep(5)
        await _dismiss_portal_popups(page, step)

        # Detail viewer may render in-page or as a popup (both observed live)
        viewer = await _resolve_viewer_page(page, None)
        # Give the detailed-notice attachments a beat to render (portal can
        # lag between the notices list and the detailed view — live run 1
        # once saw notice-09 render empty at 5s and fine later).
        try:
            await viewer.wait_for_selector(
                "button.downloadPdf, .subtitle2.fileName",
                state="visible", timeout=10000)
        except Exception:
            pass  # keep going — the download loop logs what it finds
        notice_dir = os.path.join(proc_dir, f"notice-{k + 1:02d}")
        got = await _download_attachments_on_page(viewer, step, notice_dir,
                                                  f"{proc_label}-notice{k + 1}")
        saved.extend(got)
        notice_files[k] = list(got)
        if not got:
            warns.append(f"{proc_label}: notice {k + 1} PDF download failed")

        # Back to the notices list for the next notice
        try:
            if viewer is not page:
                await _close_extra_pages(page)
            else:
                await page.locator("button:has-text('Back')").first.click(timeout=8000)
                await asyncio.sleep(4)
        except Exception as e:
            step(f"[Warning] Back from detailed notice {k + 1} failed: {e}")
            warns.append(f"{proc_label}: navigation lost after notice {k + 1}")
            return saved, warns

    # Per-notice View Response (client's submitted response + attachments)
    vr_btns = page.locator("button:has-text('View Response')")
    n_vr = await vr_btns.count()
    step(f"View Response buttons: {n_vr}")
    for k in range(n_vr):
        try:
            await vr_btns.nth(k).click(timeout=15000)
        except Exception as e:
            step(f"[Warning] View Response {k} click failed: {e}")
            continue
        await asyncio.sleep(5)
        await _dismiss_portal_popups(page, step)
        viewer = await _resolve_viewer_page(page, None)
        try:
            await viewer.wait_for_selector(
                "span.hyperLink, button[aria-label='Download Acknowledgement'], "
                ".subtitle2.fileName",
                state="visible", timeout=10000)
        except Exception:
            pass  # keep going — the download loop logs what it finds
        resp_dir = os.path.join(proc_dir, f"response-{k + 1:02d}")
        got = await _download_attachments_on_page(viewer, step, resp_dir,
                                                  f"{proc_label}-response{k + 1}")
        saved.extend(got)
        # k may exceed the parsed notice blocks (portal data gaps) — the
        # meta builder guards unmapped indices, keep the files regardless.
        response_files[k] = list(got)
        try:
            if viewer is not page:
                await _close_extra_pages(page)
            else:
                await page.locator("button:has-text('Back')").first.click(timeout=8000)
                await asyncio.sleep(4)
        except Exception as e:
            step(f"[Warning] Back from response {k + 1} failed: {e}")
            warns.append(f"{proc_label}: navigation lost after response {k + 1}")
            return saved, warns

    # Persist per-proceeding metadata for the UI (issue dates, due dates,
    # responded status, orders). Best-effort — a write failure must never
    # abort the run.
    try:
        meta = _build_proc_meta(proc_meta, notices, notice_files,
                                response_files,
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        meta_path = os.path.join(proc_dir, "_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        step(f"Saved metadata: {os.path.basename(meta_path)}")
    except Exception as e:
        step(f"[Warning] Could not write _meta.json for '{proc_label}': {e}")
        warns.append(f"{proc_label}: metadata save failed")

    # Back to the proceedings list
    try:
        await page.locator("button:has-text('Back')").first.click(timeout=8000)
        await asyncio.sleep(4)
    except Exception as e:
        step(f"[Warning] Back to proceedings list failed: {e}")
        warns.append(f"{proc_label}: could not return to list")
    return saved, warns


async def download_e_proceedings(page: Page, download_root: str, log_callback,
                                 pan: str = "", is_running=None) -> tuple[bool, str, list[dict]]:
    """F-60 entry point. Downloads every document under e-Proceedings (both
    tabs, all proceedings) for the already-logged-in client on `page`.

    Returns (ok, msg, saved_files) where saved_files is a list of
    {"path", "proceeding", "kind"} dicts — the same broad (ok, msg, saved)
    contract handle_challans/handle_filed_returns hand back to the caller.
    ok=False means nothing could be fetched at all (nav failure / empty).
    Partial failures keep ok=True with a warning in msg."""
    step = make_step_logger(log_callback, "EPROC")
    saved_files: list[dict] = []
    warnings: list[str] = []

    def _stopped():
        return (is_running is not None and not is_running())

    try:
        await navigate_to_e_proceedings(page, log_callback)
    except Exception as e:
        step(f"[Error] Navigation failed: {e}")
        return False, f"Navigation failed: {str(e)[:100]}", []

    # Both tabs — For your Action, then For your Information. Counts come
    # from the tab labels; we just read whatever cards render after click.
    tab_defs = [
        ("For your Action", "action"),
        ("For your Information", "info"),
    ]
    for tab_label, kind in tab_defs:
        if _stopped():
            break
        step(f"Switching to tab: {tab_label}")
        try:
            tab = page.locator(f".mat-mdc-tab:has-text('{tab_label}')").first
            await tab.click(timeout=15000)
        except Exception as e:
            step(f"[Warning] Could not open tab '{tab_label}': {e}")
            warnings.append(f"{tab_label} tab could not be opened")
            continue
        await asyncio.sleep(5)
        await _dismiss_portal_popups(page, step)

        body_text = ""
        try:
            body_text = await page.inner_text("body")
        except Exception:
            pass
        if "No e-Proceedings records are found" in body_text:
            step(f"Tab '{tab_label}': no records")
            continue

        procs = await _read_proceedings_on_active_tab(page, step)
        step(f"Tab '{tab_label}': {len(procs)} proceeding card(s) with view buttons")
        for proc in procs:
            if _stopped():
                break
            meta = _parse_proceeding_card_text(f"Proceeding Name :\n{proc['name']}\n"
                                               f"Assessment Year :\n{proc['ay']}\n"
                                               f"Proceeding Status\n{proc['status']}")
            saved, warns = await _process_proceeding(
                page, proc["button_index"], meta or proc, download_root, log_callback, pan, step)
            saved_files.extend(
                {"path": p, "proceeding": proc["name"], "kind": kind} for p in saved)
            warnings.extend(warns)

    await update_browser_status(page, "e-Proceedings: Download Complete!")
    step(f"Done: {len(saved_files)} file(s), {len(warnings)} warning(s)")

    if not saved_files:
        if warnings:
            return False, "; ".join(warnings), []
        return False, "No e-Proceedings found", []
    if warnings:
        return True, "; ".join(warnings), saved_files
    return True, "", saved_files
