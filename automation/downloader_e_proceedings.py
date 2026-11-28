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

Incremental sync: before downloading, each proceeding's `_meta.json` is
matched against the portal's current notice list by (ref_id, issued_on).
Notices/responses already recorded there whose files still exist on disk are
SKIPPED — only new/changed documents are fetched. A repeat run over unchanged
data downloads nothing and reports "Up to date".

Never aborts the whole run for one failed artifact: every download is
individually try/except'd (same pattern as downloader_filed_returns).
"""
import asyncio
import json
import os
import re
from datetime import datetime

from playwright.async_api import Page

from automation.doc_types import e_proceeding_doc_label
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
                    if (/^(OK|Close|Confirm|Continue Session|Proceed|Continue)$/.test(t)) {
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


async def _close_blocking_overlays(page: Page) -> None:
    """Best-effort removal of lingering Bootstrap/Angular overlays that
    intercept pointer events (e.g. a stuck #downloadClosurePopup backdrop).
    Never raises — every click/evaluation is individually guarded."""
    for selector in (
        "#downloadClosurePopup button:has-text('Cancel')",
        "#downloadClosurePopup .close",
        ".modal.show button:has-text('Cancel')",
        ".modal.show .close",
        "#efNotificationPopUp_continue",
        "#securityReasonPopup button:has-text('No')",
    ):
        try:
            loc = page.locator(selector).first
            if await loc.is_visible():
                await loc.click(timeout=3000)
        except Exception:
            pass
    try:
        await page.evaluate(
            """() => {
            document.querySelectorAll(
                '.modal-backdrop, .cdk-overlay-backdrop-showing'
            ).forEach(el => el.remove());
            document.querySelectorAll('.modal.show').forEach(el => {
                el.classList.remove('show');
                el.style.display = 'none';
                el.setAttribute('aria-hidden', 'true');
            });
        }"""
        )
    except Exception:
        pass


async def _activate_eproc_tab(page: Page, tab_label: str, step) -> bool:
    """Switch to an e-Proceedings tab, clearing lingering overlays before each
    attempt. Falls back to a JS click when Playwright's click keeps being
    intercepted. Returns True when the tab was activated."""
    for attempt in range(1, 4):
        await _close_blocking_overlays(page)
        try:
            tab = page.locator(f".mat-mdc-tab:has-text('{tab_label}')").first
            await tab.click(timeout=15000)
            step(f"Opened tab '{tab_label}' (attempt {attempt})")
            return True
        except Exception as e:
            step(f"[Warning] Tab '{tab_label}' click attempt {attempt} failed: {e}")
            if attempt < 3:
                await asyncio.sleep(2)
    try:
        clicked = await page.evaluate(
            """(label) => {
            const tabs = [...document.querySelectorAll('.mat-mdc-tab')];
            const tab = tabs.find(t => (t.innerText || '').includes(label));
            if (!tab) return false;
            tab.click();
            return true;
        }""",
            tab_label,
        )
    except Exception as e:
        step(f"[Warning] JS tab click for '{tab_label}' failed: {e}")
        return False
    ok = bool(clicked)
    if ok:
        step(f"Opened tab '{tab_label}' via JS fallback")
    else:
        step(f"[Warning] Could not open tab '{tab_label}'")
    return ok


async def navigate_to_e_proceedings(page: Page, log_callback) -> Page:
    """One-time navigation: top-bar 'Pending Actions' hover menu →
    'e-Proceedings' button. Returns the same page on the e-Proceedings
    route. Raises on failure (caller decides how to report it)."""
    step = make_step_logger(log_callback, "EPROC")
    step("Navigating: Pending Actions → e-Proceedings")
    await update_browser_status(page, "e-Proceedings: Opening section...")

    # Already on the e-Proceedings SPA route (resumed session / prior nav) —
    # the hover menu is not rendered there, so skip straight to the list.
    if _EPROC_HASH in page.url:
        step("Already on e-Proceedings — skipping navigation")
        await asyncio.sleep(3)
        return page

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


def _notice_key(notice: dict) -> str:
    """Stable diff key for one notice: '<ref_id>|<issued_on>'. Empty string
    when the portal gave no reference id — an unknown notice is never
    treated as already-synced (safe fallback: always re-fetch)."""
    ref = (notice.get("ref_id") or "").strip()
    issued = (notice.get("issued_on") or "").strip()
    return f"{ref}|{issued}" if ref else ""


# ── Virtual hearing (VC) parsing ──────────────────────────────────────────
# The VC screen (#/dashboard/eProceedings/viewNotices/seekVideoConferencing)
# renders an ag-Grid request table. Confirmed live 2026-11-23 on AABCP1234F:
# columns (col-id -> meaning): date (request), rfsvca (reason),
# vcdt (VC date & Time), sa (status), itdrd (ITD response date),
# vcld (VC Recording link), itdR (VC Schedule Notice / Status and VC).
_VC_COLS = ("date", "rfsvca", "vcdt", "sa", "itdrd", "vcld", "itdR")


def _parse_vc_table(rows: list[dict]) -> list[dict]:
    """Normalize raw ag-Grid rows into hearing dicts. Pure function
    (unit-testable). Each raw row is {col_id: {"text": str,
    "links": [{"txt", "cls"}]}}. The portal renders '-' as a placeholder for
    a value it has not set yet (e.g. an open VC request not yet scheduled),
    which is normalized to ''."""
    out: list[dict] = []

    def _clean(value: str) -> str:
        value = (value or "").strip()
        return "" if value in ("-", "--", "\u2013", "\u2014") else value

    for row in rows or []:
        def _text(cid: str) -> str:
            return _clean((row.get(cid) or {}).get("text") or "")

        vc_datetime = _text("vcdt")
        status = _text("sa")
        request_date = _text("date")
        reason = _text("rfsvca")
        itd_response = _text("itdrd")
        links: list[str] = []
        for cid in ("vcld", "itdR"):
            for link in ((row.get(cid) or {}).get("links") or []):
                label = (link.get("txt") or "").strip()
                if label and label not in links:
                    links.append(label)
        if not any((vc_datetime, status, request_date, reason, itd_response)) \
                and not links:
            continue
        out.append({
            "request_date": request_date,
            "reason": reason,
            "vc_datetime": vc_datetime,
            "status": status,
            "itd_response_date": itd_response,
            "links": links,
        })
    return out


def _hearing_key(hearing: dict) -> str:
    """Diff key for one hearing: '<notice_ref>|<when>' where 'when' is the VC
    date/time, falling back to the assessee request date for an open (not yet
    scheduled) VC request. Empty only when the ref is missing."""
    ref = (hearing.get("notice_ref") or "").strip()
    when = ((hearing.get("vc_datetime") or "").strip()
            or (hearing.get("request_date") or "").strip())
    return f"{ref}|{when}" if ref else ""


def _synced_hearing_keys(meta: dict) -> set[str]:
    """Keys of hearings already recorded (recording URL, files, VC date or an
    open-request request_date)."""
    out: set[str] = set()
    for hearing in (meta.get("hearings") or []):
        key = _hearing_key(hearing)
        if not key:
            continue
        if (hearing.get("recording_url") or hearing.get("files")
                or hearing.get("vc_datetime") or hearing.get("request_date")
                or hearing.get("status")):
            out.add(key)
    return out


def _synced_hearing_notice_refs(meta: dict) -> set[str]:
    """Notice refs that already have a recorded hearing (scheduled, completed
    or an open request) — used to skip re-opening that notice's VC screen."""
    refs: set[str] = set()
    for hearing in (meta.get("hearings") or []):
        ref = (hearing.get("notice_ref") or "").strip()
        if ref:
            refs.add(ref)
    return refs


async def _read_vc_rows(page: Page) -> list[dict]:
    """Extract the VC request table's ag-Grid rows as raw {col_id: {text,
    links}} dicts (fed to _parse_vc_table). Returns [] when absent/empty."""
    try:
        return await page.evaluate(
            """() => {
            const rows = [];
            for (const row of document.querySelectorAll('.ag-row')) {
                const cells = {};
                for (const c of row.querySelectorAll('[col-id]')) {
                    const cid = c.getAttribute('col-id');
                    const links = [...c.querySelectorAll('a.hyperLink, span.hyperLink')]
                        .map(a => ({txt: (a.innerText || '').trim(),
                                    cls: (a.className && a.className.toString) ? a.className.toString() : ''}));
                    cells[cid] = {text: (c.innerText || '').trim(), links};
                }
                if (Object.keys(cells).length) rows.push(cells);
            }
            return rows;
        }"""
        ) or []
    except Exception:
        return []


async def _close_modal(page: Page) -> None:
    """Close an open portal modal/overlay (best-effort, never raises)."""
    for sel in (".modal.show button:has-text('Close')",
                "#attachmentsPopup button.close-btn",
                "#linkPassModal button.close-btn",
                ".modal.show .close-btn", ".modal.show .close",
                ".cdk-overlay-pane button:has-text('Close')"):
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=600):
                await loc.click(timeout=3000)
                await asyncio.sleep(1)
                return
        except Exception:
            continue


async def _click_vc_hyperlink(page: Page, label: str) -> bool:
    """Click a hyperlink in the VC table by its visible label."""
    clicked = await page.evaluate(
        """(sub) => {
        const links = [...document.querySelectorAll('a.hyperLink, span.hyperLink, a')]
            .filter(a => a.getBoundingClientRect().width > 0
                && (a.innerText || '').trim().toLowerCase().includes(sub.toLowerCase()));
        if (!links.length) return false;
        links[0].scrollIntoView({block: 'center'});
        links[0].click();
        return true;
    }""", label)
    if clicked:
        await asyncio.sleep(4)
    return bool(clicked)


async def _read_modal(page: Page) -> dict:
    """Read the currently-open modal: {text, links: [{txt, href}]}."""
    try:
        return await page.evaluate(
            """() => {
            const m = document.querySelector('.modal.show, .cdk-overlay-pane');
            if (!m) return {text: '', links: []};
            const links = [...m.querySelectorAll('a.hyperLink, span.hyperLink, a[href]')]
                .map(a => ({txt: (a.innerText || '').trim(),
                            href: a.getAttribute('href') || ''}))
                .filter(x => x.txt);
            return {text: (m.innerText || ''), links};
        }"""
        ) or {"text": "", "links": []}
    except Exception:
        return {"text": "", "links": []}


async def _vc_recording_url(page: Page, step) -> str:
    """Open the 'VC Recording' modal and return the recording URL (stored,
    not downloaded). Empty when absent."""
    if not await _click_vc_hyperlink(page, "VC Recording"):
        return ""
    modal = await _read_modal(page)
    url = ""
    for link in modal.get("links") or []:
        txt = (link.get("txt") or "").strip()
        if txt.startswith("http://") or txt.startswith("https://"):
            url = txt
            break
    if not url:
        m = re.search(r"https?://\S+", modal.get("text") or "")
        url = m.group(0) if m else ""
    await _close_modal(page)
    if url:
        step(f"VC recording link captured: {url[:80]}...")
    return url


async def _vc_join_credentials(page: Page) -> dict:
    """Read '#linkPassModal' (VC Password Details) join link + password.
    Only populated within 2 hours of the scheduled VC; usually empty."""
    try:
        text = await page.locator("#linkPassModal").first.inner_text(timeout=1500)
    except Exception:
        return {"join_link": "", "vc_password": ""}
    join_link = ""
    m = re.search(r"https?://\S+", text or "")
    if m:
        join_link = m.group(0).strip()
    pwd = ""
    pm = re.search(r"VC Password\s*[:\-]?\s*([^\n]+)", text or "", re.IGNORECASE)
    if pm:
        candidate = pm.group(1).strip()
        if candidate.lower() not in ("details", "close", ""):
            pwd = candidate
    return {"join_link": join_link, "vc_password": pwd}


async def _download_vc_pdf(page: Page, page_label: str, save_dir: str, step,
                           before_download=None) -> str:
    """Download the PDF behind a VC-table hyperlink (Minutes of Meeting /
    Schedule Notice). Returns the saved path ('' on failure)."""
    if not await _click_vc_hyperlink(page, page_label):
        return ""
    modal = await _read_modal(page)
    pdf_link = ""
    for link in modal.get("links") or []:
        if (link.get("txt") or "").lower().endswith(".pdf"):
            pdf_link = link["txt"]
            break
    if not pdf_link:
        await _close_modal(page)
        return ""
    os.makedirs(save_dir, exist_ok=True)
    saved_path = ""
    try:
        if before_download:
            await before_download()
        async with page.expect_download(timeout=45000) as dl_info:
            clicked = await page.evaluate(
                """(label) => {
                const m = document.querySelector('.modal.show, .cdk-overlay-pane');
                if (!m) return false;
                const a = [...m.querySelectorAll('a.hyperLink, span.hyperLink, a')]
                    .find(x => (x.innerText || '').trim() === label);
                if (a) { a.click(); return true; }
                return false;
            }""", pdf_link)
            if not clicked:
                raise RuntimeError("PDF link not found in modal")
        download = await dl_info.value
        fname = _sanitize_name(download.suggested_filename or pdf_link)
        path = _dedupe_path(save_dir, fname)
        await download.save_as(path)
        _strip_owner_encryption(path)
        saved_path = path
        step(f"[Victory] Saved VC document: {os.path.basename(path)}")
    except Exception as e:
        step(f"[Warning] VC document '{page_label}' download failed: {e}")
    await _close_modal(page)
    return saved_path


async def _vc_button_notice_refs(page: Page) -> list[str]:
    """Return the notice reference IDs whose block shows a visible 'Seek
    Video Conferencing' button, in DOM order (confirmed live 2026-11-23)."""
    try:
        return await page.evaluate(
            """() => {
            const out = [];
            const btns = [...document.querySelectorAll('button')]
                .filter(b => b.getBoundingClientRect().width > 0
                    && /Seek Video Conferencing/i.test(b.innerText || ''));
            for (const b of btns) {
                let node = b, ref = '';
                for (let up = 0; up < 12 && node; up++) {
                    const m = (node.innerText || '').match(
                        /Communication Reference ID\\s*:\\s*([0-9A-Za-z]+)/);
                    if (m) { ref = m[1]; break; }
                    node = node.parentElement;
                }
                if (ref && !out.includes(ref)) out.push(ref);
            }
            return out;
        }"""
        ) or []
    except Exception:
        return []


async def _return_to_notices(page: Page, step) -> None:
    """Navigate from the VC page back to the notices list."""
    for sel in ("button:has-text('Back')", "a:has-text('Back')"):
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible(timeout=1500):
                await loc.click(timeout=8000)
                await asyncio.sleep(4)
                return
        except Exception:
            continue
    step("[Warning] Could not navigate back to notices list after VC")


async def _sync_notice_hearing(page: Page, notice_ref: str, notice: dict,
                               proc_dir: str, index: int, step,
                               before_download=None) -> dict | None:
    """Open the 'Seek Video Conferencing' screen for `notice_ref` and capture
    its hearing data. Returns a hearing dict or None."""
    section = (notice.get("section") or "").strip()

    clicked = await page.evaluate(
        """(ref) => {
        const btns = [...document.querySelectorAll('button')]
            .filter(b => b.getBoundingClientRect().width > 0
                && /Seek Video Conferencing/i.test(b.innerText || ''));
        for (const b of btns) {
            let node = b, found = '';
            for (let up = 0; up < 12 && node; up++) {
                const m = (node.innerText || '').match(
                    /Communication Reference ID\\s*:\\s*([0-9A-Za-z]+)/);
                if (m) { found = m[1]; break; }
                node = node.parentElement;
            }
            if (found === ref) {
                b.scrollIntoView({block: 'center'}); b.click(); return true;
            }
        }
        return false;
    }""", notice_ref)
    if not clicked:
        return None
    await asyncio.sleep(5)
    await _dismiss_portal_popups(page, step)

    rows = await _read_vc_rows(page)
    parsed = _parse_vc_table(rows)
    step(f"Hearing(s) on notice {notice_ref}: {len(parsed)}")

    hearing: dict | None = dict(parsed[0]) if parsed else None

    recording_url = await _vc_recording_url(page, step)
    creds = await _vc_join_credentials(page)

    vc_dir = os.path.join(proc_dir, f"vc-{index + 1:02d}")
    files: list[str] = []
    for page_label in ("Status and VC recording", "VC Schedule Notice"):
        path = await _download_vc_pdf(page, page_label, vc_dir, step,
                                      before_download=before_download)
        if path:
            files.append(f"vc-{index + 1:02d}/{os.path.basename(path)}")

    if hearing is None:
        if not (recording_url or files or creds.get("join_link")):
            await _return_to_notices(page, step)
            return None
        hearing = {}

    hearing.setdefault("request_date", "")
    hearing.setdefault("reason", "")
    hearing.setdefault("vc_datetime", "")
    hearing.setdefault("status", "")
    hearing.setdefault("itd_response_date", "")
    hearing.pop("links", None)
    hearing["notice_ref"] = notice_ref
    hearing["notice_section"] = section
    hearing["recording_url"] = recording_url
    hearing["join_link"] = creds.get("join_link", "")
    hearing["vc_password"] = creds.get("vc_password", "")
    hearing["files"] = files
    step(f"Captured hearing for notice {notice_ref} "
         f"({hearing.get('vc_datetime') or 'no date'}): "
         f"recording={'yes' if recording_url else 'no'}, "
         f"{len(files)} document(s)")

    await _return_to_notices(page, step)
    return hearing


def _merge_hearings(old_meta: dict, new_hearings: list[dict]) -> list[dict]:
    """Merge freshly captured hearings with the previous run's, keyed by
    (notice_ref, vc_datetime). Pure function (unit-testable)."""
    old_by_key = {}
    for h in (old_meta.get("hearings") or []):
        key = _hearing_key(h)
        if key:
            old_by_key[key] = h
    merged: list[dict] = []
    used: set[str] = set()
    for h in new_hearings:
        key = _hearing_key(h)
        prev = old_by_key.get(key) if key else None
        entry = dict(h)
        if prev:
            if not entry.get("recording_url"):
                entry["recording_url"] = prev.get("recording_url", "")
            entry["files"] = _merge_rel_files(
                prev.get("files") or [], entry.get("files") or [])
        entry.pop("all_hearings", None)
        merged.append(entry)
        if key:
            used.add(key)
    for key, prev in old_by_key.items():
        if key not in used and (prev.get("recording_url") or prev.get("files")):
            merged.append(prev)
    return merged


def _load_existing_meta(proc_dir: str) -> dict:
    """Read a proceeding's `_meta.json`; {} on anything missing/corrupt."""
    try:
        with open(os.path.join(proc_dir, "_meta.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def _meta_entries_by_key(meta: dict) -> dict[str, dict]:
    """Map diff key -> existing meta entry (last wins on duplicates)."""
    out: dict[str, dict] = {}
    for entry in (meta.get("notices") or []):
        key = _notice_key(entry)
        if key:
            out[key] = entry
    return out


def _files_present(proc_dir: str, rel_files) -> bool:
    """True when every relative path in `rel_files` exists on disk."""
    rels = rel_files or []
    if not rels:
        return False
    return all(os.path.exists(os.path.join(proc_dir, r)) for r in rels)


def _synced_keys(proc_dir: str, meta: dict, field: str) -> set[str]:
    """Keys already synced AND still on disk for `field` ('files' for the
    notice PDF, 'response_files' for the client's response)."""
    out: set[str] = set()
    for entry in (meta.get("notices") or []):
        key = _notice_key(entry)
        if key and _files_present(proc_dir, entry.get(field)):
            out.add(key)
    return out


def _merge_rel_files(old: list[str], new: list[str]) -> list[str]:
    """Keep old relative paths and append genuinely new basenames."""
    merged = list(old or [])
    seen = {os.path.basename(p) for p in merged}
    for path in new or []:
        if os.path.basename(path) not in seen:
            merged.append(path)
            seen.add(os.path.basename(path))
    return merged


def _diff_build_meta(proc_meta: dict, notices: list[dict],
                     notice_files: dict[int, list[str]],
                     response_files: dict[int, list[str]],
                     old_meta: dict, downloaded_at: str,
                     orders: list[dict] | None = None,
                     hearings: list[dict] | None = None,
                     vc_requestable: bool = False) -> dict:
    """Build `_meta.json` by merging the portal's CURRENT notice list with the
    previous run's meta. Only entries whose ref_id/issued_on are new (or whose
    files vanished) carry freshly downloaded paths; already-synced entries
    reuse their old files. Old entries no longer shown by the portal are
    preserved (the portal hides history; local documents are not deleted)."""
    old_by_key = _meta_entries_by_key(old_meta)
    entries: list[dict] = []
    used: set[str] = set()

    for k, src in enumerate(notices):
        key = _notice_key(src)
        old = old_by_key.get(key) if key else None
        files = old.get("files", []) if old else []
        files = _merge_rel_files(
            files,
            [f"notice-{k + 1:02d}/{os.path.basename(p)}"
             for p in notice_files.get(k, [])])
        resp = old.get("response_files", []) if old else []
        resp = _merge_rel_files(
            resp,
            [f"response-{k + 1:02d}/{os.path.basename(p)}"
             for p in response_files.get(k, [])])
        entries.append({
            "index": k + 1,
            "ref_id": src.get("ref_id", ""),
            "description": src.get("description", ""),
            "issued_on": src.get("issued_on", ""),
            "response_due": src.get("response_due", ""),
            "responded": bool(src.get("responded", False)),
            "section": src.get("section", ""),
            "viewed_by_ao": src.get("viewed_by_ao", ""),
            "is_order": bool(src.get("is_order", False)),
            "files": files,
            "response_files": resp,
        })
        if key:
            used.add(key)

    for offset, (key, old) in enumerate(
            (kv for kv in old_by_key.items() if kv[0] not in used), start=1):
        kept = dict(old)
        # Renumber past the current portal list so doc ids stay unique even
        # though the notice is no longer rendered by the portal.
        kept["index"] = len(notices) + offset
        entries.append(kept)

    # Orders: merge the freshly downloaded entries with previously recorded
    # ones (matched by title) so a cached order keeps its file paths.
    old_orders = { (o.get("title") or "").strip(): o
                   for o in (old_meta.get("orders") or []) }
    merged_orders: list[dict] = []
    seen_titles: set[str] = set()
    for order in (orders or []):
        title = (order.get("title") or "").strip()
        prev = old_orders.get(title)
        files = list(order.get("files") or [])
        if not files and prev:
            files = list(prev.get("files") or [])
        # De-duplicate file entries defensively (older runs could record the
        # same portal document more than once inside one order block).
        uniq_files: list[str] = []
        seen_rel: set[str] = set()
        for rel in files:
            base = os.path.basename(rel)
            if base in seen_rel:
                continue
            seen_rel.add(base)
            uniq_files.append(rel)
        files = uniq_files
        merged_orders.append({
            "title": order.get("title", ""),
            "filename": order.get("filename") or (prev or {}).get("filename", ""),
            "files": files,
        })
        seen_titles.add(title)
    seen_files = {os.path.basename(rel)
                  for o in merged_orders for rel in (o.get("files") or [])}
    for title, prev in old_orders.items():
        prev_files = [rel for rel in (prev.get("files") or [])
                      if os.path.basename(rel) not in seen_files]
        if prev_files:
            kept = dict(prev)
            kept["files"] = prev_files
            merged_orders.append(kept)

    # A proceeding with an order (closure order / assessment order) is a
    # CLOSED case — the UI uses this to separate open vs closed matters.
    has_order = any(o.get("files") for o in merged_orders)
    status = proc_meta.get("status", "")
    closed = has_order or "clos" in (status or "").lower()

    merged_hearings = _merge_hearings(old_meta, hearings or [])

    return {
        "proceeding": {
            "name": proc_meta.get("name", ""),
            "ay": proc_meta.get("ay", ""),
            "status": status,
        },
        "closed": closed,
        "downloaded_at": downloaded_at,
        "notices": entries,
        "orders": merged_orders,
        "hearings": merged_hearings,
        "vc_requestable": bool(vc_requestable),
    }


def _build_proc_meta(proc_meta: dict, notices: list[dict],
                     notice_files: dict[int, list[str]],
                     response_files: dict[int, list[str]],
                     downloaded_at: str,
                     orders: list[dict] | None = None,
                     hearings: list[dict] | None = None,
                     vc_requestable: bool = False) -> dict:
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
    merged_orders = [o for o in (orders or []) if o.get("files")]
    has_order = bool(merged_orders)
    status = proc_meta.get("status", "")
    return {
        "proceeding": {
            "name": proc_meta.get("name", ""),
            "ay": proc_meta.get("ay", ""),
            "status": status,
        },
        "closed": has_order or "clos" in (status or "").lower(),
        "downloaded_at": downloaded_at,
        "notices": entries,
        "orders": merged_orders,
        "hearings": list(hearings or []),
        "vc_requestable": bool(vc_requestable),
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
        const allCards = [...document.querySelectorAll('.card-container')]
            .filter(c => c.getBoundingClientRect().width > 0);
        for (let bi = 0; bi < viewBtns.length; bi++) {
            let card = viewBtns[bi].closest('.card-container')
                       || viewBtns[bi].closest('mat-card');
            if (!card) continue;
            const nameEl = card.querySelector('.heading5.mNoWrap.mEclipse');
            const txt = card.innerText || '';
            const statusM = txt.match(/Proceeding Status\\s*:?\\s*\\n?\\s*([^\\n]+)/);
            const ayM = txt.match(/Assessment Year\\s*:?\\s*\\n?\\s*([^\\n]+)/);
            const orderBtns = [...card.querySelectorAll('button')]
                .map(b => (b.innerText || '').trim())
                .filter(t => t && /order/i.test(t)
                             && !/view notices/i.test(t));
            out.push({
                button_index: bi,
                card_index: allCards.indexOf(card),
                name: nameEl ? (nameEl.innerText || '').trim() : '',
                ay: ayM ? ayM[1].trim() : '',
                status: statusM ? statusM[1].trim() : '',
                order_buttons: orderBtns,
            });
        }
        return out;
    }"""
    )
    return [
        {"button_index": c.get("button_index", i),
         "card_index": c.get("card_index", -1),
         "name": c.get("name", ""),
         "ay": c.get("ay", ""), "status": c.get("status", ""),
         "order_buttons": c.get("order_buttons", [])}
        for i, c in enumerate(cards)
    ]


async def _download_attachments_on_page(page: Page, step, save_dir: str, tag: str,
                                       before_download=None) -> list[str]:
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
        if before_download:
            await before_download()
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
        if before_download:
            await before_download()
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
        if before_download:
            await before_download()
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


def _order_title(modal_title: str, filename: str) -> str:
    """Prefer the document type encoded in the portal filename — assessment
    and penalty closures publish an Order, a Computation sheet and a Demand
    notice together, all under one 'Closure Order' modal caption.

    Shares :func:`automation.doc_types.e_proceeding_doc_label` with the UI so
    the stored title and the displayed attachment label cannot drift."""
    recognized = e_proceeding_doc_label(filename, default="")
    if recognized:
        return recognized
    return (modal_title or "Order").strip()


async def _visible_download_button(page: Page):
    """Return the first VISIBLE 'Download' button inside a portal overlay
    (the Closure/Order modal renders one). None when no overlay is open."""
    try:
        btns = page.locator(
            ".cdk-overlay-pane button:has-text('Download'), "
            ".modal.show button:has-text('Download')")
        for i in range(await btns.count()):
            candidate = btns.nth(i)
            try:
                if await candidate.is_visible(timeout=800):
                    return candidate
            except Exception:
                continue
    except Exception:
        pass
    return None


def _order_download_targets(rows: list[dict]) -> list[dict]:
    """Return one target per distinct document row in a closure-order modal.

    The portal lists each document in its own ``.row.marginTopModel`` block
    with a filename and its own Download button. Iterating visible Download
    buttons by position is not enough: the first button stays first after a
    download, so a "click the first visible button" loop re-downloads the
    same file. Targets keep the original row order, drop blank filenames and
    ignore duplicate filenames (some modals repeat a row).
    """
    targets: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        filename = (row.get("filename") or "").strip()
        if not filename or filename in seen:
            continue
        seen.add(filename)
        targets.append({"row_index": row.get("row_index", 0),
                        "filename": filename})
    return targets


async def _read_order_modal_rows(page: Page) -> list[dict]:
    """Read the per-document rows of the open Closure Order modal.

    Returns ``[{"row_index": int, "filename": str}]``. Empty when the open
    overlay is not the closure-order modal (the caller then falls back to the
    generic Download-button scan).
    """
    try:
        return await page.evaluate(
            """() => {
                const root = document.querySelector('#downloadClosurePopup')
                          || document.querySelector('.modal.show');
                if (!root) return [];
                const rows = [...root.querySelectorAll('.row.marginTopModel')];
                const out = [];
                rows.forEach((row, i) => {
                    const nameEl = row.querySelector('.modelName');
                    const btn = row.querySelector('button.downloadTemplate')
                              || row.querySelector('button');
                    if (!nameEl || !btn) return;
                    out.push({
                        row_index: i,
                        filename: (nameEl.innerText || '').trim(),
                    });
                });
                return out;
            }"""
        )
    except Exception:
        return []


async def _download_proceeding_orders(page: Page, card_index: int, proc_dir: str,
                                      proc_label: str, old_orders: list[dict],
                                      step, before_download=None) -> tuple[list[str], list[dict], list[str]]:
    """Download order documents attached to a proceeding CARD (e.g. the
    'Download Closure Order' button on a closed appeal). Confirmed live:
    clicking it opens a modal titled e.g. 'Closure Order' with one row per
    document (order + computation sheet + demand notice on assessment/penalty
    closures) and a Download button per row.

    Orders already recorded in `_meta.json` with their file still on disk are
    skipped (incremental sync), same as notices.

    Returns (saved_paths, order_entries, warnings). Each order entry is
    {"title", "filename", "files": ["order-NN/<name>"]}.
    """
    saved: list[str] = []
    entries: list[dict] = []
    warns: list[str] = []
    if card_index < 0:
        return saved, entries, warns

    card = page.locator(".card-container").nth(card_index)
    try:
        buttons = await card.evaluate(
            """c => [...c.querySelectorAll('button')]
                .map((b, i) => ({i, t: (b.innerText || '').trim(), d: b.disabled}))
                .filter(x => x.t && /order/i.test(x.t) && !/view notices/i.test(x.t)
                             && !x.d)"""
        )
    except Exception as e:
        step(f"[Warning] Order button scan failed: {e}")
        return saved, entries, warns

    if not buttons:
        return saved, entries, warns
    step(f"Order button(s) on this proceeding: {[b['t'] for b in buttons]}")

    known_files = {os.path.basename(rel)
                   for o in (old_orders or [])
                   for rel in (o.get("files") or [])}

    for n, b in enumerate(buttons, start=1):
        label = b["t"]
        if before_download:
            await before_download()
        try:
            await card.locator("button").nth(b["i"]).click(timeout=12000)
        except Exception as e:
            step(f"[Warning] Could not click order button '{label}': {e}")
            warns.append(f"{proc_label}: order '{label}' click failed")
            continue
        await asyncio.sleep(4)

        dl_btn = await _visible_download_button(page)
        if dl_btn is None:
            step(f"[Warning] No Download button appeared for order '{label}'")
            warns.append(f"{proc_label}: order '{label}' modal did not open")
            await _dismiss_portal_popups(page, step)
            continue

        # Overlay text carries the title and full portal filename.
        overlay_text = ""
        try:
            overlay_text = await page.locator(
                ".cdk-overlay-pane, .modal.show").last.inner_text()
        except Exception:
            pass
        modal_title = (overlay_text.splitlines() or [label])[0].strip() or label

        # The modal can carry MORE THAN ONE document (order + computation
        # sheet + demand notice are published together on assessment/penalty
        # closures). Click every visible Download button rather than only the
        # first, and name each record from its own portal filename.
        order_dir = os.path.join(proc_dir, f"order-{n:02d}")
        os.makedirs(order_dir, exist_ok=True)
        downloads_here = []
        seen_this_modal: set[str] = set()

        # Each document is its own row with its own Download button. Read the
        # rows first, then click the button for each row by index — never
        # "the first visible button", which would return the same document
        # again after the first download and drop the rest.
        rows = await _read_order_modal_rows(page)
        targets = _order_download_targets(rows)

        if targets:
            for target in targets:
                row_index = target["row_index"]
                row = page.locator(
                    "#downloadClosurePopup .row.marginTopModel"
                    ", .modal.show .row.marginTopModel").nth(row_index)
                btn = row.locator("button.downloadTemplate, button").first
                try:
                    if not await btn.is_visible(timeout=2000):
                        continue
                    if before_download:
                        await before_download()
                    async with page.expect_download(timeout=45000) as dl_info:
                        await btn.click(timeout=10000)
                    download = await dl_info.value
                    fname = _sanitize_name(
                        download.suggested_filename or target["filename"]
                        or "order.pdf")
                    staging = os.path.join(proc_dir, ".staging_order.pdf")
                    await download.save_as(staging)
                    if fname in seen_this_modal:
                        os.remove(staging)
                        continue
                    seen_this_modal.add(fname)
                    if fname in known_files:
                        os.remove(staging)
                        step(f"Cached (unchanged): order document '{fname}'")
                        downloads_here.append(fname)
                        continue
                    path = _dedupe_path(order_dir, fname)
                    os.replace(staging, path)
                    saved.append(path)
                    downloads_here.append(os.path.basename(path))
                    step(f"[Victory] Saved order document: "
                         f"{os.path.basename(path)}")
                except Exception as e:
                    step(f"[Warning] Order download failed for row "
                         f"{row_index}: {e}")
                    warns.append(f"{proc_label}: order download failed")
                await asyncio.sleep(2)
        else:
            # Generic overlays have no filename rows: click each visible
            # Download button once, in order, instead of only the first.
            btns = page.locator(
                ".cdk-overlay-pane button:has-text('Download'), "
                ".modal.show button:has-text('Download')")
            count = 0
            try:
                count = await btns.count()
            except Exception:
                count = 0
            for i in range(count):
                try:
                    btn = btns.nth(i)
                    if not await btn.is_visible(timeout=800):
                        continue
                    if before_download:
                        await before_download()
                    async with page.expect_download(timeout=45000) as dl_info:
                        await btn.click(timeout=10000)
                    download = await dl_info.value
                    fname = _sanitize_name(
                        download.suggested_filename or "order.pdf")
                    staging = os.path.join(proc_dir, ".staging_order.pdf")
                    await download.save_as(staging)
                    if fname in seen_this_modal:
                        os.remove(staging)
                        continue
                    seen_this_modal.add(fname)
                    if fname in known_files:
                        os.remove(staging)
                        step(f"Cached (unchanged): order document '{fname}'")
                        downloads_here.append(fname)
                        continue
                    path = _dedupe_path(order_dir, fname)
                    os.replace(staging, path)
                    saved.append(path)
                    downloads_here.append(os.path.basename(path))
                    step(f"[Victory] Saved order document: "
                         f"{os.path.basename(path)}")
                except Exception as e:
                    step(f"[Warning] Order download failed: {e}")
                    warns.append(f"{proc_label}: order download failed")
                await asyncio.sleep(2)

        if downloads_here:
            entries.append({
                "title": _order_title(modal_title, downloads_here[0]),
                "filename": downloads_here[0],
                "files": [f"order-{n:02d}/{f}" for f in downloads_here],
            })
        # Close the modal so the next button is clickable.
        for sel in ("#downloadClosurePopup button:has-text('Cancel')",
                    "#downloadClosurePopup .close-btn",
                    ".modal.show button:has-text('Cancel')",
                    ".cdk-overlay-pane button:has-text('Cancel')",
                    ".cdk-overlay-pane button:has-text('close')"):
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=800):
                    await loc.click(timeout=4000)
                    break
            except Exception:
                continue
        await asyncio.sleep(2)
        await _dismiss_portal_popups(page, step)

    return saved, entries, warns


async def _process_proceeding(page: Page, button_index: int, proc_meta: dict,
                              download_root: str, log_callback, pan: str,
                              step, card_index: int = -1,
                              before_download=None) -> tuple[list[str], list[str], int, dict]:
    """Open one proceeding's View Notices/Orders and sync its documents.

    Diff-first: notices/responses whose (ref_id, issued_on) already exist in
    this proceeding's `_meta.json` AND whose files are still on disk are
    skipped — no portal click, no download. Returns
    (saved_paths, warnings, skipped_count)."""
    saved: list[str] = []
    warns: list[str] = []
    skipped = 0
    notice_files: dict[int, list[str]] = {}
    response_files: dict[int, list[str]] = {}
    proc_label = _sanitize_name(proc_meta.get("name") or f"Proceeding {button_index + 1}")
    proc_dir = os.path.join(download_root, f"{button_index + 1:02d}-{proc_label}")
    os.makedirs(proc_dir, exist_ok=True)

    old_meta = _load_existing_meta(proc_dir)
    synced_notices = _synced_keys(proc_dir, old_meta, "files")
    synced_responses = _synced_keys(proc_dir, old_meta, "response_files")
    synced_hearing_refs = _synced_hearing_notice_refs(old_meta)
    hearings: list[dict] = []
    vc_requestable = False
    if synced_notices or synced_responses:
        step(f"Previous sync: {len(synced_notices)} notice(s), "
             f"{len(synced_responses)} response(s) already on disk")

    # Order documents hang off the proceeding CARD itself (e.g. "Download
    # Closure Order" on a closed appeal) — grab them while the list is still
    # on screen, before navigating away.
    order_paths, order_entries, order_warns = await _download_proceeding_orders(
        page, card_index, proc_dir, proc_label,
        old_meta.get("orders") or [], step, before_download=before_download)
    saved.extend(order_paths)
    warns.extend(order_warns)
    if order_entries:
        step(f"Orders on this proceeding: {len(order_entries)}")

    try:
        btn = page.locator("button:has-text('View Notices/Orders')").nth(button_index)
        await btn.click(timeout=15000)
    except Exception as e:
        step(f"[Warning] Could not open proceeding {button_index + 1}: {e}")
        return [], [f"{proc_label}: could not open ({str(e)[:60]})"], 0, {}
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

    # Each notice has its own 'Notice/Letter Pdf' button — sync each
    pdf_btns = page.locator("button:has-text('Notice/Letter Pdf')")
    n_pdfs = await pdf_btns.count()
    step(f"Notice/Letter Pdf buttons: {n_pdfs}")
    for k in range(n_pdfs):
        key = _notice_key(notices[k]) if k < len(notices) else ""
        if key and key in synced_notices:
            step(f"Cached (unchanged): notice {k + 1} [{key}]")
            skipped += 1
            continue
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
                                                  f"{proc_label}-notice{k + 1}",
                                                  before_download=before_download)
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
            return saved, warns, skipped, {}

    # Virtual hearings: notices in faceless proceedings can expose a
    # "Seek Video Conferencing" button. Capture the VC date/time, recording
    # link (stored, not downloaded), Minutes of Meeting / Schedule Notice
    # PDFs, and join+password (only within 2h of a scheduled VC). Each open
    # returns to the notices list, so re-read the button map each pass.
    try:
        vc_refs = await _vc_button_notice_refs(page)
    except Exception:
        vc_refs = []
    if vc_refs:
        # A still-open, faceless notice with this button means the user can
        # still apply for a VC — flag it so the UI can prompt them.
        vc_requestable = True
        step(f"Video Conferencing notice(s): {len(vc_refs)}")
        notice_by_ref = {(n.get("ref_id") or "").strip(): n for n in notices}
        vc_index = 0
        attempted: set[str] = set()
        while True:
            remaining = [r for r in vc_refs if r not in attempted]
            if not remaining:
                break
            ref = remaining[0]
            attempted.add(ref)
            notice = notice_by_ref.get(ref) or {}
            if ref in synced_hearing_refs:
                step(f"Cached (unchanged): hearing for notice {ref}")
                skipped += 1
                continue
            try:
                hearing = await _sync_notice_hearing(
                    page, ref, notice, proc_dir, vc_index, step,
                    before_download=before_download)
            except Exception as e:
                step(f"[Warning] Hearing capture for notice {ref} failed: {e}")
                warns.append(f"{proc_label}: hearing for notice {ref} failed")
                try:
                    if "seekVideoConferencing" in page.url:
                        await _return_to_notices(page, step)
                except Exception:
                    pass
                hearing = None
            if hearing:
                hearings.append(hearing)
                vc_index += 1

    # Per-notice View Response (client's submitted response + attachments).
    # Only RESPONDED notices render a View Response button, so button k maps
    # to the k-th notice flagged `responded` — not to notices[k].
    vr_btns = page.locator("button:has-text('View Response')")
    n_vr = await vr_btns.count()
    step(f"View Response buttons: {n_vr}")
    responded_indices = [i for i, n in enumerate(notices) if n.get("responded")]
    for j in range(n_vr):
        notice_index = (responded_indices[j]
                        if j < len(responded_indices) else j)
        key = (_notice_key(notices[notice_index])
               if notice_index < len(notices) else "")
        if key and key in synced_responses:
            step(f"Cached (unchanged): response {j + 1} [{key}]")
            skipped += 1
            continue
        try:
            await vr_btns.nth(j).click(timeout=15000)
        except Exception as e:
            step(f"[Warning] View Response {j} click failed: {e}")
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
        resp_dir = os.path.join(proc_dir, f"response-{notice_index + 1:02d}")
        got = await _download_attachments_on_page(viewer, step, resp_dir,
                                                  f"{proc_label}-response{notice_index + 1}",
                                                  before_download=before_download)
        saved.extend(got)
        # The mapped notice index may exceed the parsed blocks (portal data
        # gaps) — the meta builder guards unmapped indices, keep the files.
        response_files[notice_index] = list(got)
        try:
            if viewer is not page:
                await _close_extra_pages(page)
            else:
                await page.locator("button:has-text('Back')").first.click(timeout=8000)
                await asyncio.sleep(4)
        except Exception as e:
            step(f"[Warning] Back from response {j + 1} failed: {e}")
            warns.append(f"{proc_label}: navigation lost after response {j + 1}")
            return saved, warns, skipped, {}

    # Persist per-proceeding metadata for the UI (issue dates, due dates,
    # responded status, orders). MERGED with the previous run so unchanged
    # notices keep their existing file paths. Best-effort — a write failure
    # must never abort the run.
    try:
        meta = _diff_build_meta(proc_meta, notices, notice_files,
                                response_files, old_meta,
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                orders=order_entries, hearings=hearings,
                                vc_requestable=vc_requestable)
        meta_path = os.path.join(proc_dir, "_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        step(f"Saved metadata: {os.path.basename(meta_path)} "
             f"({len(saved)} new, {skipped} unchanged)")
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
    return saved, warns, skipped, {"orders": order_entries,
                                   "hearings": hearings,
                                   "vc_requestable": vc_requestable}


async def download_e_proceedings(page: Page, download_root: str, log_callback,
                                 pan: str = "", is_running=None,
                                 before_download=None) -> tuple[bool, str, list[dict]]:
    """F-60 entry point. Syncs e-Proceedings documents (both tabs, all
    proceedings) for the already-logged-in client on `page`.

    Incremental: a notice/response already recorded in the proceeding's
    `_meta.json` (matched by portal ref_id + issued_on) with its files still
    on disk is skipped — only new/changed documents are downloaded.

    Returns (ok, msg, saved_files) where saved_files is a list of
    {"path", "proceeding", "kind"} dicts — the same broad (ok, msg, saved)
    contract handle_challans/handle_filed_returns hand back to the caller.
    ok=False means nothing could be fetched at all (nav failure / empty).
    When everything was already synced, returns
    ok=True, msg="Up to date (N unchanged)", saved=[] so the caller shows
    "up to date" rather than a failure. Partial failures keep ok=True with a
    warning in msg."""
    step = make_step_logger(log_callback, "EPROC")
    saved_files: list[dict] = []
    warnings: list[str] = []
    skipped_total = 0

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
        if not await _activate_eproc_tab(page, tab_label, step):
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
            saved, warns, skipped, extra = await _process_proceeding(
                page, proc["button_index"], meta or proc, download_root,
                log_callback, pan, step, card_index=proc.get("card_index", -1),
                before_download=before_download)
            saved_files.extend(
                {"path": p, "proceeding": proc["name"], "kind": kind} for p in saved)
            warnings.extend(warns)
            skipped_total += skipped

    await update_browser_status(page, "e-Proceedings: Sync Complete!")
    step(f"Sync summary: {len(saved_files)} new file(s), "
         f"{skipped_total} unchanged (skipped), {len(warnings)} warning(s)")

    if not saved_files:
        if warnings:
            return False, "; ".join(warnings), []
        if skipped_total:
            return True, f"Up to date ({skipped_total} unchanged)", []
        return False, "No e-Proceedings found", []
    if warnings:
        return True, "; ".join(warnings), saved_files
    return True, "", saved_files
