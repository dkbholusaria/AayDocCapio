"""Fetch GST notices and orders (Services → User Services → View Notices and Orders).

This is the GST counterpart of :mod:`automation.downloader_e_proceedings`, but
GST has its own portal, routes, table layout and metadata schema, so it is a
separate module rather than a reuse of the Income Tax parser.

The pure functions (``normalise_rows``, ``notice_key``, ``merge_meta``) are
deliberately free of Playwright so they can be tested against synthetic rows.

Live routes and table headers must be confirmed once test credentials are
available. Navigation therefore tries the direct route first and falls back to
the menu path, and row extraction is header-mapped (not position-based) so
column reordering does not break parsing.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin

from playwright.async_api import Page, TimeoutError as PWTimeout

from automation.downloader import make_step_logger, update_browser_status

GST_LOGIN_URL = "https://services.gst.gov.in/services/login"
_OPEN_NOTICES_LABELS = (
    "VIEW NOTICE(S) AND ORDER(S)",
    "View Notice(s) and Order(s)",
    "View Notices and Orders",
    "Notices and Orders",
)
_MENU_STEPS = ("Services", "User Services", "View Notices and Orders")

_SCHEMA = 1

_HEADER_ALIASES = {
    "gstin": ("gstin", "gstin uin", "gstin/uin", "gstin of taxpayer"),
    "trade_name": ("trade name", "legal name", "name of taxpayer", "taxpayer name"),
    "notice_type": ("notice order type", "notice/order type", "notice type",
                    "order type", "type of notice", "document type", "type"),
    "ref_id": ("reference no", "reference number", "ref no", "ref no.",
               "notice order reference no", "notice/order reference no",
               "notice reference no", "order reference no", "reference id",
               "notice no", "order no", "arn", "notice demand order id",
               "notice/order id", "notice order id", "demand order id",
               "order id", "case id"),
    "description": ("description", "subject", "particulars", "details",
                    "notice description", "notice order description",
                    "notice/order description"),
    "issued_on": ("notice order date", "notice/order date", "date of issue",
                  "issuance date", "date of issuance", "issue date",
                  "issued on", "notice date", "order date", "date"),
    "due_date": ("due date", "reply due date", "response due date",
                 "due date for reply"),
    "status": ("status", "reply status", "notice status", "order status",
               "action taken", "current status"),
    "section": ("section", "section/act", "section act"),
}

_ACTION_RE = re.compile(r"view|download|click here|details|open|reply|pdf", re.I)
_PDF_RE = re.compile(r"\.pdf($|\?)", re.I)


def _norm_header(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return re.sub(r"\s+", " ", text)


def _field_for_header(header: str) -> str:
    key = _norm_header(header)
    for field, aliases in _HEADER_ALIASES.items():
        if key in aliases:
            return field
    for field, aliases in _HEADER_ALIASES.items():
        if any(alias in key for alias in aliases):
            return field
    return ""


def _pick(cells: dict, field: str) -> str:
    for header, value in (cells or {}).items():
        if _field_for_header(header) == field:
            text = (value or "").strip()
            if text:
                return text
    return ""


def _clean(value: str) -> str:
    value = (value or "").strip()
    return "" if value in ("-", "--", "\u2013", "\u2014") else value


def _is_order(notice_type: str, description: str) -> bool:
    """Only a real Order counts. DRC-01B/01C are notices with amounts, not
    orders, even though their form code starts with DRC."""
    text = f"{notice_type} {description}".lower()
    return ("order" in text
            or notice_type.strip().lower() == "order")


def _responded(status: str, actions: list[dict]) -> bool:
    text = (status or "").lower()
    if any(word in text for word in ("repl", "respond", "submitted")):
        return True
    for action in actions or []:
        label = (action.get("text") or "").lower()
        if "reply" in label or "response" in label:
            return True
    return False


def normalise_rows(raw_rows: list[dict]) -> list[dict]:
    """Map extracted table rows to the canonical GST notice fields.

    Each raw row is ``{"cells": {header: text}, "actions": [{"text", "href"}]}``.
    Rows without a reference number and without a notice/order type are
    discarded (pager rows, empty placeholders).
    """
    notices: list[dict] = []
    for raw in raw_rows or []:
        cells = raw.get("cells") or {}
        notice_type = _clean(_pick(cells, "notice_type"))
        ref_id = _clean(_pick(cells, "ref_id"))
        if not notice_type and not ref_id:
            continue
        actions = raw.get("actions") or []
        description = _clean(_pick(cells, "description"))
        status = _clean(_pick(cells, "status"))
        notices.append({
            "notice_type": notice_type,
            "ref_id": ref_id,
            "gstin": _clean(_pick(cells, "gstin")),
            "trade_name": _clean(_pick(cells, "trade_name")),
            "section": _clean(_pick(cells, "section")),
            "description": description,
            "issued_on": _clean(_pick(cells, "issued_on")),
            "due_date": _clean(_pick(cells, "due_date")),
            "status": status,
            "responded": _responded(status, actions),
            "is_order": _is_order(notice_type, description),
            "actions": actions,
            "table_index": raw.get("table_index", 0),
            "row_index": raw.get("row_index", 0),
        })
    for position, notice in enumerate(notices, start=1):
        notice["index"] = position
        if not notice["is_order"] and notice["responded"]:
            notice["is_order"] = False
    return notices


def _case_task_row(item: dict) -> dict:
    """Normalise one litigation-service case task (phase 2) row."""
    descr = str(item.get("taskDesc") or "").strip()
    case_type = str(item.get("caseTypeName") or item.get("caseTpeCd") or "").strip()
    return {
        "ref_id": str(item.get("refId") or item.get("ref_id") or "").strip(),
        "notice_type": case_type or "Case",
        "description": descr,
        "issued_on": str(item.get("assignmentDt") or "").strip(),
        "due_date": "As Applicable*",
        "amount": "",
        "doc_id": "",
        "app_def_id": "",
        "case_id": str(item.get("caseId") or "").strip(),
        "arn": str(item.get("arn") or "").strip(),
        "case_folder_item_id": str(item.get("caseFolderItemId") or "").strip(),
        "case_tpe_cd": str(item.get("caseTpeCd") or "").strip(),
        "source": "case",
        "is_order": "order" in (descr + " " + case_type).lower(),
    }


def _row_signature(row: dict) -> str:
    ref = (row.get("ref_id") or "").strip()
    if ref and ref.upper() != "NA":
        return ref
    return "|".join((
        (row.get("notice_type") or "").strip().lower(),
        (row.get("description") or "").strip().lower(),
        (row.get("issued_on") or "").strip()))


def merge_api_rows(rows: list[dict], api_rows: list[dict],
                   case_rows: list[dict] | None = None) -> list[dict]:
    """Align DOM rows with the portal's two JSON feeds.

    The notices page merges:
      1. ``/services/auth/api/get/notices`` (notices/orders), and
      2. ``/litserv/auth/api/case/task/get`` (appeals / audit / case tasks).

    The API order and fields win; DOM data supplies the click targets. Any
    rendered row not covered by either feed is kept once (de-duplicated by
    reference or type+description+date) so appeals are not lost.
    """
    dom_rows = list(rows or [])
    dom_by_ref: dict[str, dict] = {}
    for row in dom_rows:
        ref = (row.get("ref_id") or "").strip()
        if ref and ref not in dom_by_ref:
            dom_by_ref[ref] = row

    def _dom_for(candidate: dict) -> dict:
        ref = (candidate.get("ref_id") or "").strip()
        if ref and ref in dom_by_ref:
            return dict(dom_by_ref[ref])
        desc = (candidate.get("description") or "").strip().lower()
        if desc:
            for row in dom_rows:
                if desc[:50] in (row.get("description") or "").strip().lower():
                    return dict(row)
        return {}

    out: list[dict] = []
    seen: set[str] = set()

    for api_row in api_rows or []:
        if not isinstance(api_row, dict):
            continue
        ref = str(api_row.get("noticeOrderId") or "").strip()
        base = _dom_for({"ref_id": ref, "description": api_row.get("descr")})
        base.setdefault("actions", [])
        base["ref_id"] = ref or base.get("ref_id", "")
        base["notice_type"] = str(api_row.get("type") or base.get("notice_type", "")).strip()
        base["description"] = str(api_row.get("descr") or base.get("description", "")).strip()
        base["issued_on"] = str(api_row.get("dtOfIssue") or base.get("issued_on", "")).strip()
        base["due_date"] = str(api_row.get("dueDate") or base.get("due_date", "")).strip()
        base["amount"] = str(api_row.get("amount") or "").strip()
        base["doc_id"] = str(api_row.get("docId") or "").strip()
        base["app_def_id"] = str(api_row.get("appDefId") or "").strip()
        base["pdf_download_url"] = str(api_row.get("pdfDownloadURL") or "").strip()
        base["appln_cd"] = str(api_row.get("applnCd") or "").strip()
        base["issued_by"] = str(api_row.get("issuedBy") or "").strip()
        base["is_read"] = str(api_row.get("isRead") or "").strip()
        base["portal_status"] = str(api_row.get("status") or "").strip()
        base["portal_action"] = str(api_row.get("action") or "").strip()
        base["inserted_at"] = str(api_row.get("insertTmstmp") or "").strip()
        base["supp_doc_id"] = str(api_row.get("suppDocId") or "").strip()
        base["addtnl_docs"] = api_row.get("addtnlDocs") or []
        base["source"] = "notice"
        base["is_order"] = str(base["notice_type"]).strip().lower() == "order"
        base["responded"] = bool(base.get("responded")) or bool(re.search(
            r"repl|respond|submitted",
            base["portal_status"] + " " + base["portal_action"], re.I))
        sig = _row_signature(base)
        seen.add(sig)
        out.append(base)

    for item in case_rows or []:
        if not isinstance(item, dict):
            continue
        candidate = _case_task_row(item)
        if not (candidate["ref_id"] or candidate["description"]):
            continue
        base = _dom_for(candidate)
        base.update({k: v for k, v in candidate.items() if v or k not in base})
        base.setdefault("actions", [])
        sig = _row_signature(base)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(base)

    for dom_row in dom_rows:
        sig = _row_signature(dom_row)
        if sig in seen:
            continue
        if not (dom_row.get("ref_id") or dom_row.get("description")
                or dom_row.get("notice_type")):
            continue
        seen.add(sig)
        out.append(dict(dom_row))

    for position, row in enumerate(out, start=1):
        row["index"] = position
    return out


def notice_key(notice: dict) -> str:
    ref = (notice.get("ref_id") or "").strip()
    issued = (notice.get("issued_on") or "").strip()
    if ref:
        return f"{ref}|{issued}"
    gstin = (notice.get("gstin") or "").strip()
    kind = (notice.get("notice_type") or "").strip()
    return f"{gstin}|{kind}|{issued}" if (gstin or kind) else ""


def sanitize_name(raw: str, fallback: str = "document") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", (raw or "").strip())
    return cleaned[:150] if cleaned else fallback


def dedupe_path(save_dir: str, fname: str) -> str:
    base, ext = os.path.splitext(fname)
    candidate = os.path.join(save_dir, fname)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(save_dir, f"{base} ({n}){ext}")
        n += 1
    return candidate


def _files_present(root: str, rel_files) -> bool:
    rels = rel_files or []
    return bool(rels) and all(os.path.exists(os.path.join(root, r)) for r in rels)


def load_meta(root: str) -> dict:
    path = os.path.join(root, "_meta.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _entries_by_key(meta: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entry in (meta.get("notices") or []):
        key = notice_key(entry)
        if key:
            out[key] = entry
    return out


def merge_meta(old_meta: dict, rows: list[dict], files_by_key: dict,
               downloaded_at: str) -> dict:
    """Merge the portal's current rows with the previous run.

    ``files_by_key`` maps ``notice_key`` -> ``{"files", "reply_files",
    "order_files"}``. Already-synced rows keep their old file paths; rows no
    longer shown by the portal are preserved and renumbered.
    """
    old_by_key = _entries_by_key(old_meta)
    entries: list[dict] = []
    used: set[str] = set()

    for position, row in enumerate(rows, start=1):
        key = notice_key(row)
        old = old_by_key.get(key) if key else None
        fresh = (files_by_key or {}).get(key) or {}
        files = list(fresh.get("files") or (old or {}).get("files") or [])
        replies = list(fresh.get("reply_files") or (old or {}).get("reply_files") or [])
        orders = list(fresh.get("order_files") or (old or {}).get("order_files") or [])
        entries.append({
            "index": position,
            "notice_type": row.get("notice_type", ""),
            "ref_id": row.get("ref_id", ""),
            "gstin": row.get("gstin", ""),
            "trade_name": row.get("trade_name", ""),
            "section": row.get("section", ""),
            "description": row.get("description", ""),
            "issued_on": row.get("issued_on", ""),
            "due_date": row.get("due_date", ""),
            "status": row.get("status", ""),
            "portal_status": row.get("portal_status", ""),
            "responded": bool(row.get("responded", False)),
            "is_order": bool(row.get("is_order", False)),
            "amount": row.get("amount", ""),
            "doc_id": row.get("doc_id", ""),
            "app_def_id": row.get("app_def_id", ""),
            "case_id": row.get("app_def_id", "") or row.get("ref_id", ""),
            "order_id": row.get("doc_id", "") if row.get("is_order") else "",
            "reply_id": row.get("supp_doc_id", "") or "",
            "appln_cd": row.get("appln_cd", ""),
            "issued_by": row.get("issued_by", ""),
            "is_read": row.get("is_read", ""),
            "pdf_download_url": row.get("pdf_download_url", ""),
            "supp_doc_id": row.get("supp_doc_id", ""),
            "addtnl_docs": row.get("addtnl_docs") or [],
            "detail_url": row.get("detail_url", ""),
            "files": files,
            "reply_files": replies,
            "order_files": orders,
        })
        if key:
            used.add(key)

    for offset, (key, old) in enumerate(
            (item for item in old_by_key.items() if item[0] not in used), start=1):
        kept = dict(old)
        kept["index"] = len(rows) + offset
        entries.append(kept)

    return {
        "schema": _SCHEMA,
        "module": "gst",
        "downloaded_at": downloaded_at,
        "notices": entries,
    }


def save_meta(root: str, meta: dict) -> None:
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "_meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)


_READ_ROWS_JS = """() => {
    const out = {headers: [], rows: [], source: ''};
    const visible = el => el && el.getBoundingClientRect().width > 0;
    const actionsOf = el => [...el.querySelectorAll('a,button')]
        .filter(visible)
        .map(a => ({text: (a.innerText || a.getAttribute('title') || a.getAttribute('aria-label') || '').trim(),
                    href: a.getAttribute('href') || '',
                    tag: a.tagName.toLowerCase()}))
        .filter(a => a.text || a.href);
    const score = headers => headers.reduce((n, h) =>
        n + (/notice|order|reference|ref\\.?\\s*no|gstin|due|issued|status|description/i.test(h) ? 1 : 0), 0);

    const candidates = [];
    const allTables = [...document.querySelectorAll('table')];
    for (let ti = 0; ti < allTables.length; ti++) {
        const table = allTables[ti];
        if (!visible(table)) continue;
        let headers = [...table.querySelectorAll('thead th, thead td')]
            .map(th => (th.innerText || '').trim());
        const bodyRows = [...table.querySelectorAll('tbody tr')].filter(visible);
        if (!bodyRows.length) continue;
        if (!headers.length) {
            const first = bodyRows[0];
            if (first.querySelector('th')) {
                headers = [...first.querySelectorAll('th,td')].map(c => (c.innerText || '').trim());
            } else {
                headers = [...first.querySelectorAll('td')].map((_, i) => 'Column ' + (i + 1));
            }
        }
        const rows = [];
        for (let ri = 0; ri < bodyRows.length; ri++) {
            const tr = bodyRows[ri];
            const tds = [...tr.querySelectorAll('td,th')];
            if (!tds.length) continue;
            const cells = {};
            tds.forEach((td, i) => {
                const h = headers[i] || ('Column ' + (i + 1));
                cells[h] = (td.innerText || '').trim();
            });
            rows.push({cells, actions: actionsOf(tr), table_index: ti, row_index: ri});
        }
        if (rows.length) candidates.push({headers, rows, source: 'table', score: score(headers)});
    }

    const grid = document.querySelector('.ag-root');
    if (grid && visible(grid)) {
        const headers = [...grid.querySelectorAll('.ag-header-cell')].map(h => ({
            id: h.getAttribute('col-id'),
            text: (h.querySelector('.ag-header-cell-text')?.innerText || '').trim()
        }));
        const rows = [];
        const gridRows = [...grid.querySelectorAll('.ag-row')].filter(visible);
        for (let ri = 0; ri < gridRows.length; ri++) {
            const cells = {};
            for (const cell of gridRows[ri].querySelectorAll('[col-id]')) {
                const id = cell.getAttribute('col-id');
                const header = headers.find(h => h.id === id);
                cells[(header && header.text) ? header.text : id] = (cell.innerText || '').trim();
            }
            if (!Object.keys(cells).length) continue;
            rows.push({cells, actions: actionsOf(gridRows[ri]), table_index: -1, row_index: ri});
        }
        const gridHeaders = headers.map(h => h.text || h.id || '');
        if (rows.length) candidates.push({headers: gridHeaders, rows, source: 'ag-grid', score: score(gridHeaders)});
    }

    if (!candidates.length) return out;
    candidates.sort((a, b) => b.score - a.score);
    const best = candidates[0];
    return {headers: best.headers, rows: best.rows, source: best.source};
}"""

_CLICK_TEXT_JS = """(text) => {
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const wanted = norm(text);
    const vis = e => e && e.getBoundingClientRect().width > 0;
    const els = [...document.querySelectorAll('a,button,span,li,div')].filter(vis);
    const matches = els.filter(e => norm(e.innerText) === wanted);
    const contains = els.filter(e => norm(e.innerText).includes(wanted)
        && norm(e.innerText).length <= wanted.length + 40);
    const target = matches[0] || contains[0];
    if (!target) return false;
    let node = target;
    for (let i = 0; i < 5 && node; i++) {
        const tag = node.tagName.toLowerCase();
        if (tag === 'a' || tag === 'button' || (node.getAttribute && node.getAttribute('role'))) {
            node.click();
            return true;
        }
        node = node.parentElement;
    }
    target.click();
    return true;
}"""


async def _click_text(page: Page, text: str) -> bool:
    try:
        if await page.evaluate(_CLICK_TEXT_JS, text):
            return True
    except Exception:
        pass
    try:
        loc = page.get_by_text(text, exact=False).first
        if await loc.count() and await loc.is_visible(timeout=1500):
            await loc.click(timeout=8000)
            return True
    except Exception:
        pass
    return False


async def _notices_visible(page: Page) -> bool:
    try:
        data = await page.evaluate(_READ_ROWS_JS)
        rows = normalise_rows((data or {}).get("rows") or [])
        return any(row.get("ref_id") or row.get("notice_type") for row in rows)
    except Exception:
        return False


async def _notices_page_anywhere(page: Page):
    if await _notices_visible(page):
        return page
    try:
        for other in page.context.pages:
            if other is page or other.is_closed():
                continue
            if await _notices_visible(other):
                return other
    except Exception:
        pass
    return None


async def _js_click_notices_button(page: Page) -> bool:
    try:
        return bool(await page.evaluate("""() => {
            const vis = e => e && e.getBoundingClientRect().width > 0;
            const btn = [...document.querySelectorAll('button,a')]
                .find(e => vis(e) && /view\\s+notice/i.test(e.innerText || ''));
            if (!btn) return false;
            btn.scrollIntoView({block: 'center'});
            btn.click();
            return true;
        }"""))
    except Exception:
        return False


async def navigate_to_notices(page: Page, log_callback=None) -> Page:
    step = make_step_logger(log_callback, "GST-PROC")
    await update_browser_status(page, "GST: Opening View Notices and Orders...")
    found = await _notices_page_anywhere(page)
    if found is not None:
        step("View Notices and Orders already open")
        return found

    # Confirmed live 2026-11-24: Services → User Services is the menu path.
    # Guessed /services/notices URLs return "Access Denied", so navigation is
    # click-only. The dashboard's own notices button is the reliable fallback.
    step("Navigating: Services → User Services → View Notices and Orders")
    await _click_text(page, "Services")
    await asyncio.sleep(1.5)
    await _click_text(page, "User Services")
    await asyncio.sleep(2.5)
    for label in _OPEN_NOTICES_LABELS:
        if await _click_text(page, label):
            step(f"Clicked '{label}'")
            await asyncio.sleep(4)
            break
    found = await _notices_page_anywhere(page)
    if found is not None:
        step("View Notices and Orders loaded")
        return found

    # Dismiss any open dropdown/overlay, return to the dashboard, then use its
    # single notices button (it needs a second click if a menu swallowed the
    # first one).
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    await asyncio.sleep(1)
    if "fowelcome" not in page.url:
        for label in ("Dashboard", "Home"):
            if await _click_text(page, label):
                await asyncio.sleep(2.5)
                break
    for _ in range(2):
        if not await _js_click_notices_button(page):
            break
        await asyncio.sleep(6)
        found = await _notices_page_anywhere(page)
        if found is not None:
            step("View Notices and Orders loaded (dashboard button)")
            return found

    body = ""
    try:
        body = (await page.inner_text("body"))[:300]
    except Exception:
        pass
    raise RuntimeError(
        "View Notices and Orders did not open"
        + (f" (page text: {body!r})" if body else ""))


async def read_notice_rows(page: Page) -> dict:
    try:
        return await page.evaluate(_READ_ROWS_JS) or {}
    except Exception:
        return {}


async def _resolve_viewer_page(page: Page) -> Page:
    try:
        others = [p for p in page.context.pages if p is not page and not p.is_closed()]
        if others:
            popup = others[-1]
            try:
                await popup.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            return popup
    except Exception:
        pass
    return page


async def _close_extra_pages(page: Page) -> None:
    try:
        for other in page.context.pages:
            if other is not page:
                try:
                    await other.close()
                except Exception:
                    pass
    except Exception:
        pass


async def _return_to_list(page: Page) -> None:
    for label in ("Back", "Close", "Cancel"):
        if await _click_text(page, label):
            await asyncio.sleep(2)
            return


_JS_CLICK_ROW = """(args) => {
    const vis = e => e && e.getBoundingClientRect().width > 0;
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const rows = [...document.querySelectorAll('tbody tr')].filter(vis);
    const ref = args.ref, desc = norm(args.description);
    let tr = ref ? rows.find(r => norm(r.innerText).includes(norm(ref))) : null;
    if (!tr && desc) tr = rows.find(r => norm(r.innerText).includes(desc.slice(0, 60)));
    if (!tr && args.ri < rows.length) tr = rows[args.ri];
    if (!tr) return false;
    const links = [...tr.querySelectorAll('a,button')].filter(vis);
    const action = links.find(a => /view|download|details|reply|click here/i.test(
        (a.innerText || a.getAttribute('title') || ''))) || links[0];
    if (!action) return false;
    tr.scrollIntoView({block: 'center'});
    action.click();
    return true;
}"""


async def _js_click_row(page: Page, ref: str, description: str, ri: int) -> bool:
    try:
        return bool(await page.evaluate(
            _JS_CLICK_ROW,
            {"ref": ref, "description": description, "ri": ri}))
    except Exception:
        return False


async def _open_row(page: Page, row: dict) -> Page:
    """Open a row's View action (visible-row DOM click, then Playwright).

    Case-task rows (the litigation feed) and rows whose index exceeds the
    rendered table have no clickable ``View`` in place; opening them is done
    by :func:`_fetch_notice`. For those, return the row's own page without a
    long locator timeout so one unopenable row never stalls the whole run.
    """
    ref = (row.get("ref_id") or "").strip()
    if ref.upper() == "NA":
        ref = ""
    description = (row.get("description") or "").strip()
    ti = int(row.get("table_index", 0))
    ri = int(row.get("row_index", 0))

    clicked = await _js_click_row(page, ref, description, ri)
    if not clicked:
        # The grid silently resets to 10 rows after a popup is closed.
        if await _set_page_size(page, 100):
            await asyncio.sleep(1.5)
            clicked = await _js_click_row(page, ref, description, ri)
    if clicked:
        await asyncio.sleep(3)
        return await _resolve_viewer_page(page)

    # Bounded Playwright fallback with a short timeout; never block 8s per row.
    try:
        by_ref = page.locator("tbody tr:visible").filter(has_text=ref).first if ref else None
        handle = None
        if by_ref is not None and await by_ref.count():
            handle = by_ref
        elif ti >= 0:
            handle = page.locator("table").nth(ti).locator("tbody tr:visible").nth(ri)
        else:
            handle = page.locator(".ag-row:visible").nth(ri)
        if handle is None or not await handle.count():
            return page
        target = handle.locator("a,button").filter(has_text=_ACTION_RE).first
        if await target.count():
            await target.click(timeout=3000)
        else:
            await handle.click(timeout=3000)
    except Exception as exc:
        raise RuntimeError(f"could not open notice row {ri + 1}: {exc}") from exc

    await asyncio.sleep(3)
    return await _resolve_viewer_page(page)


def _document_rel(doc_id: str, app_id: str) -> str:
    """Relative URL the portal uses for a notice/order PDF."""
    return f"/document/{doc_id}/{app_id}"


def _classify(label: str) -> str:
    text = (label or "").lower()
    if any(word in text for word in ("reply", "response", "submission", "clarification")):
        return "reply"
    if "order" in text:
        return "order"
    return "notice"


_MODAL_DOWNLOAD_JS = """() => {
    const vis = e => e && e.getBoundingClientRect().width > 0;
    const modals = [...document.querySelectorAll('.modal.show, .modal.in, .cdk-overlay-pane, [role=dialog]')]
        .filter(vis);
    const out = [];
    for (const modal of modals) {
        const links = [...modal.querySelectorAll('a,button')].filter(vis).map(e => ({
            text: (e.innerText || e.getAttribute('title') || e.getAttribute('aria-label') || '').replace(/\\s+/g,' ').trim(),
            href: e.getAttribute('href') || '',
            ng: e.getAttribute('data-ng-click') || e.getAttribute('ng-click') || ''
        })).filter(x => x.text || x.href);
        out.push({title: (modal.innerText || '').replace(/\\s+/g,' ').trim().slice(0, 200), links});
    }
    return out;
}"""


async def _capture_modal_documents(page: Page, save_dir: str, step,
                                   row: dict, before_download=None) -> list[dict]:
    """Download every document inside an open portal modal (suppDocPopup /
    suppReg12DocPopup) — used when a row has supporting/additional docs."""
    os.makedirs(save_dir, exist_ok=True)
    saved: list[dict] = []
    candidates = page.locator(
        ".modal.show a[href*='/document/'], .modal.in a[href*='/document/'], "
        ".modal.show a:has-text('.pdf'), .modal.in a:has-text('.pdf'), "
        ".modal.show button:has-text('Download'), .modal.in button:has-text('Download')")
    try:
        count = await candidates.count()
    except Exception:
        count = 0
    for index in range(min(count, 40)):
        element = candidates.nth(index)
        try:
            if not await element.is_visible():
                continue
            href = await element.get_attribute("href") or ""
        except Exception:
            continue
        if before_download:
            await before_download()
        if href and "/document/" in href:
            path = await _fetch_document(page, urljoin(page.url, href), save_dir, step)
            if path:
                saved.append({"path": path, "label": os.path.basename(href),
                              "bucket": "order" if row.get("is_order") else "notice"})
            continue
        try:
            async with page.expect_download(timeout=45000) as dl_info:
                await element.click(timeout=10000)
            download = await dl_info.value
            fname = sanitize_name(download.suggested_filename or f"doc-{index + 1}.pdf")
            path = dedupe_path(save_dir, fname)
            await download.save_as(path)
            bucket = _classify(fname)
            if row.get("is_order") and bucket == "notice":
                bucket = "order"
            saved.append({"path": path, "label": fname, "bucket": bucket})
            step(f"[Victory] Saved GST document: {os.path.basename(path)}")
        except Exception as exc:
            step(f"[Warning] Modal document download failed: {str(exc)[:80]}")
    return saved


async def _fetch_document(page: Page, url: str, save_dir: str, step,
                          fname_hint: str = ""):
    """GET an authenticated /document/... PDF through the browser context.
    Returns the saved path, or '' on failure."""
    os.makedirs(save_dir, exist_ok=True)
    try:
        response = await page.context.request.get(url, timeout=60000)
        body = await response.body()
        ctype = (response.headers or {}).get("content-type", "")
        if response.status != 200 or not (body[:4] == b"%PDF" or "pdf" in ctype.lower()):
            step(f"[Warning] Document fetch not a PDF (status {response.status})")
            return ""
        fname = sanitize_name(fname_hint or os.path.basename(url.split("?")[0]) or "document.pdf")
        if not fname.lower().endswith(".pdf"):
            fname += ".pdf"
        path = dedupe_path(save_dir, fname)
        with open(path, "wb") as handle:
            handle.write(body)
        step(f"[Victory] Saved GST document: {os.path.basename(path)}")
        return path
    except Exception as exc:
        step(f"[Warning] Document fetch failed: {str(exc)[:80]}")
        return ""


async def _download_attachments(page: Page, save_dir: str, step,
                                before_download=None) -> list[dict]:
    """Download every downloadable document on a detail page."""
    os.makedirs(save_dir, exist_ok=True)
    selector = ("button.downloadPdf, button:has-text('Download PDF'), "
                "button:has-text('Download'), a:has-text('Download'), "
                "a:has-text('.pdf'), a[href*='.pdf' i], span.hyperLink, "
                "a[href*='/document/']")
    try:
        candidates = page.locator(selector)
        count = await candidates.count()
    except Exception:
        count = 0
    saved: list[dict] = []
    seen: set[str] = set()
    for index in range(count):
        element = candidates.nth(index)
        try:
            if not await element.is_visible():
                continue
            if await element.evaluate(
                    "e => !!e.closest('header, nav, .navbar, .dropdown-menu')"):
                continue
            label = ((await element.inner_text()).strip()
                     or (await element.get_attribute("aria-label") or "").strip())
            href = await element.get_attribute("href") or ""
        except Exception:
            continue
        key = label or href or f"attachment-{index + 1}"
        if key in seen:
            continue
        seen.add(key)
        if before_download:
            await before_download()
        if href and "/document/" in href:
            path = await _fetch_document(page, urljoin(page.url, href), save_dir, step)
            if path:
                saved.append({"path": path, "label": label, "bucket": _classify(label)})
            continue
        if href and _PDF_RE.search(href):
            try:
                response = await page.context.request.get(
                    urljoin(page.url, href), timeout=45000)
                body = await response.body()
                ctype = (response.headers or {}).get("content-type", "")
                if body[:4] == b"%PDF" or "pdf" in ctype.lower():
                    fname = sanitize_name(
                        os.path.basename(href.split("?")[0]) or f"{key}.pdf")
                    path = dedupe_path(save_dir, fname)
                    with open(path, "wb") as handle:
                        handle.write(body)
                    saved.append({"path": path, "label": key,
                                  "bucket": _classify(key)})
                    step(f"[Victory] Saved GST document: {os.path.basename(path)}")
                    continue
            except Exception as exc:
                step(f"[Warning] Direct GST attachment fetch failed: {str(exc)[:80]}")
        try:
            async with page.expect_download(timeout=45000) as dl_info:
                await element.click(timeout=10000)
            download = await dl_info.value
            fname = sanitize_name(download.suggested_filename or f"{key}.pdf")
            path = dedupe_path(save_dir, fname)
            await download.save_as(path)
            saved.append({"path": path, "label": key, "bucket": _classify(key)})
            step(f"[Victory] Saved GST document: {os.path.basename(path)}")
        except Exception as exc:
            step(f"[Warning] GST attachment '{key}' download failed: {str(exc)[:80]}")
    return saved


async def _close_any_modal(page: Page) -> None:
    """Close a portal modal/overlay so the next row is clickable."""
    try:
        clicked = await page.evaluate("""() => {
            const vis = e => e && e.getBoundingClientRect().width > 0;
            const btns = [...document.querySelectorAll(
                '.modal.show button, .modal.in button, .cdk-overlay-pane button, [role=dialog] button')]
                .filter(vis);
            const close = btns.find(b => /^(close|cancel|ok|x)$/i.test((b.innerText || '').trim())
                || /close/i.test(b.getAttribute('aria-label') || ''));
            if (close) { close.click(); return true; }
            return false;
        }""")
        if clicked:
            await asyncio.sleep(1)
        else:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
    except Exception:
        pass


async def _visible_row_count(page: Page) -> int:
    try:
        return int(await page.evaluate("""() => [...document.querySelectorAll('tbody tr')]
            .filter(e => e && e.getBoundingClientRect().width > 0).length"""))
    except Exception:
        return 0


async def _save_pending(pending: list, notice_dir: str, row: dict, step) -> list[dict]:
    os.makedirs(notice_dir, exist_ok=True)
    got = []
    for download in list(pending):
        try:
            fname = sanitize_name(
                download.suggested_filename
                or f"{row.get('notice_type') or 'notice'}-{index_label(row)}.pdf")
            path = dedupe_path(notice_dir, fname)
            await download.save_as(path)
            bucket = _classify(fname)
            if row.get("is_order") and bucket == "notice":
                bucket = "order"
            got.append({"path": path, "label": fname, "bucket": bucket})
            step(f"[Victory] Saved GST document: {os.path.basename(path)}")
        except Exception as exc:
            step(f"[Warning] GST save failed: {str(exc)[:80]}")
    return got


async def _fetch_notice(page: Page, row: dict, notice_dir: str, step,
                        pending_downloads: list, before_download=None
                        ) -> tuple[list[dict], str]:
    """Download one notice/order's documents, routing by the portal's own
    ``applnCd`` (confirmed live 2026-11-24 from viewnoticeorderctrl.js):

      * DRC01B / DRC01C -> returns-portal summary screen (detail only)
      * APL3A / APLSM and similar -> returns-portal page via getGSTR3A
        (detail only, no PDF)
      * supDcxTxofr / addtnlDocs present -> "View" opens a supporting-doc
        modal (suppDocPopup); download its documents
      * otherwise -> "View" downloads /document/{docId}/{applnId} directly

    Returns ``(saved_documents, detail_url)``.
    """
    os.makedirs(notice_dir, exist_ok=True)
    appln_cd = (row.get("appln_cd") or "").upper()
    got: list[dict] = []

    if appln_cd in ("DRC01B", "DRC01C"):
        pending_downloads.clear()
        viewer = await _open_row(page, row)
        detail_url = "" if viewer is page else (viewer.url or "")
        await asyncio.sleep(3)
        target = viewer if viewer is not page else page
        if pending_downloads:
            for download in list(pending_downloads):
                try:
                    fname = sanitize_name(download.suggested_filename
                                          or f"{appln_cd}-{index_label(row)}.pdf")
                    path = dedupe_path(notice_dir, fname)
                    await download.save_as(path)
                    got.append({"path": path, "label": fname, "bucket": "notice"})
                    step(f"[Victory] Saved GST summary: {os.path.basename(path)}")
                except Exception as exc:
                    step(f"[Warning] DRC summary save failed: {str(exc)[:80]}")
        # The summary can render inline in the same Angular view (not a modal
        # or new page), so scan the whole page and click any download button.
        try:
            clicked = await page.evaluate("""() => {
                const vis = e => e && e.getBoundingClientRect().width > 0;
                const txt = e => (e.innerText || '').replace(/\\s+/g,' ').trim();
                const ng = e => (e.getAttribute('data-ng-click') || e.getAttribute('ng-click') || '');
                const els = [...document.querySelectorAll('button,a,span,li')].filter(vis);
                const drc = els.find(e => /downloadDRC/i.test(ng(e)))
                    || els.find(e => /download|pdf/i.test(txt(e))
                              && !/^downloads$/i.test(txt(e))
                              && !e.closest('header,nav,.dropdown-menu'));
                if (drc) { drc.scrollIntoView({block:'center'}); drc.click(); return true; }
                return false;
            }""")
            if clicked:
                await asyncio.sleep(4)
        except Exception:
            pass
        if pending_downloads:
            for download in list(pending_downloads):
                try:
                    fname = sanitize_name(download.suggested_filename
                                          or f"{appln_cd}-{index_label(row)}.pdf")
                    path = dedupe_path(notice_dir, fname)
                    await download.save_as(path)
                    got.append({"path": path, "label": fname, "bucket": "notice"})
                    step(f"[Victory] Saved GST summary: {os.path.basename(path)}")
                except Exception as exc:
                    step(f"[Warning] DRC summary save failed: {str(exc)[:80]}")
        got.extend(await _download_attachments(
            target, notice_dir, step, before_download=before_download))
        await _close_any_modal(page)
        if viewer is not page:
            await _close_extra_pages(page)
        return got, detail_url

    pending_downloads.clear()
    viewer = await _open_row(page, row)
    detail_url = "" if viewer is page else (viewer.url or "")
    await asyncio.sleep(1.5)

    if (row.get("source") == "case") or row.get("case_id"):
        # Appeal / audit / case-folder task: the portal navigates in-place to
        # the case folder (FormSubmitter), not a new tab.
        got.extend(await _download_attachments(page, notice_dir, step,
                                               before_download=before_download))
        await _close_any_modal(page)
        return got, detail_url

    # Case A: the click started an in-place PDF download.
    if pending_downloads:
        for download in list(pending_downloads):
            try:
                fname = sanitize_name(
                    download.suggested_filename
                    or f"{row.get('notice_type') or 'notice'}-{row.get('ref_id') or 'doc'}.pdf")
                path = dedupe_path(notice_dir, fname)
                await download.save_as(path)
                got.append({"path": path, "label": fname,
                            "bucket": "order" if row.get("is_order") else "notice"})
                step(f"[Victory] Saved GST document: {os.path.basename(path)}")
            except Exception as exc:
                step(f"[Warning] GST download save failed: {str(exc)[:80]}")
        return got, detail_url

    # Case B: a supporting-doc modal opened; download its documents.
    if await page.evaluate(
            "() => !!document.querySelector('.modal.show, .modal.in')"):
        got.extend(await _capture_modal_documents(
            page, notice_dir, step, row, before_download=before_download))
        await _close_any_modal(page)
        if viewer is not page:
            await _close_extra_pages(page)
        return got, detail_url

    # Case C: an authenticated /document/ URL is known from the API.
    doc_id = (row.get("doc_id") or "").strip()
    app_id = (row.get("app_def_id") or "").strip()
    if doc_id and app_id:
        path = await _fetch_document(
            page, urljoin(page.url, _document_rel(doc_id, app_id)), notice_dir,
            step, fname_hint=f"{row.get('notice_type') or 'notice'}-{index_label(row)}.pdf")
        if path:
            got.append({"path": path, "label": os.path.basename(path),
                        "bucket": "order" if row.get("is_order") else "notice"})
        return got, detail_url

    # Case D: an external returns-portal detail page; scrape any PDFs.
    if viewer is not page and not viewer.is_closed():
        got.extend(await _download_attachments(viewer, notice_dir, step,
                                               before_download=before_download))
        await _close_extra_pages(page)
    return got, detail_url


def index_label(row: dict) -> str:
    return f"{int(row.get('index') or 0):02d}"


async def _set_page_size(page: Page, size: int = 100) -> bool:
    """Show as many rows as the portal allows in one page.

    Confirmed live 2026-11-24: the list defaults to 10 rows with 10/25/50/100
    page-size buttons. Using 100 avoids missing DRC/orders that would sit on
    later pages.
    """
    try:
        clicked = await page.evaluate("""(size) => {
            const vis = e => e && e.getBoundingClientRect().width > 0;
            const wanted = String(size);
            const btn = [...document.querySelectorAll('button,a,li,span')]
                .find(e => vis(e) && (e.innerText || '').trim() === wanted);
            if (!btn) return false;
            btn.click();
            return true;
        }""", size)
    except Exception:
        return False
    if clicked:
        await asyncio.sleep(3)
    return bool(clicked)


async def download_gst_notices(page: Page, download_root: str, log_callback,
                               is_running=None, before_download=None,
                               max_rows: int | None = None,
                               only_description: str | None = None,
                               progress_callback=None,
                               ) -> tuple[bool, str, list[dict]]:
    """Sync GST notices/orders for one already-logged-in client.

    Confirmed live 2026-11-24:
      * the dashboard button opens /services/auth/notices;
      * the list is rendered from POST /services/auth/api/get/notices, which
        carries noticeOrderId, appDefId, docId, amount, pdfDownloadURL, etc.;
      * "View" either downloads a supporting PDF in-place (dwnldSuppDoc) or
        opens a returns-portal page (getGSTR3A).

    Returns ``(ok, msg, saved)`` with saved entries shaped like the Income Tax
    downloader: ``{"path", "proceeding", "kind"}``.
    """
    step = make_step_logger(log_callback, "GST-PROC")
    saved: list[dict] = []
    warnings: list[str] = []
    skipped = 0
    os.makedirs(download_root, exist_ok=True)

    def _stopped() -> bool:
        return is_running is not None and not is_running()

    api_payloads: list[list] = []
    case_payloads: list[list] = []
    pending_downloads: list = []

    def _on_response(response):
        try:
            url = response.url
            is_notices = url.endswith("/api/get/notices")
            is_cases = url.endswith("/litserv/auth/api/case/task/get") or \
                "/litserv/auth/api/case/task/get" in url
            if not (is_notices or is_cases):
                return
        except Exception:
            return

        async def _grab():
            try:
                payload = await response.json()
            except Exception:
                return
            if isinstance(payload, list):
                (api_payloads if is_notices else case_payloads).append(payload)
            elif isinstance(payload, dict):
                for key in ("taskResponse", "tasks", "data", "cases"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        case_payloads.append(value)
                        break

        asyncio.create_task(_grab())

    def _on_download(download):
        pending_downloads.append(download)

    page.on("response", _on_response)
    page.on("download", _on_download)

    try:
        await navigate_to_notices(page, log_callback)
        await asyncio.sleep(2.5)
        if await _set_page_size(page, 100):
            step("Set notices page size to 100")
    except Exception as exc:
        step(f"[Error] GST notices navigation failed: {exc}")
        return False, f"Navigation failed: {str(exc)[:120]}", []

    data = await read_notice_rows(page)
    rows = normalise_rows(data.get("rows") or [])
    if api_payloads or case_payloads:
        best_notices = max(api_payloads, key=len) if api_payloads else []
        best_cases = max(case_payloads, key=len) if case_payloads else []
        rows = merge_api_rows(rows, best_notices, best_cases)
        step(f"Portal rows: notices={len(best_notices)}, cases={len(best_cases)}, "
             f"total={len(rows)}")
    step(f"GST notice rows found: {len(rows)}")
    if not rows:
        return False, "No GST notices found", []

    old_meta = load_meta(download_root)
    old_by_key = _entries_by_key(old_meta)
    files_by_key: dict[str, dict] = {}

    async def _save_downloads(items, notice_dir, row) -> list[dict]:
        os.makedirs(notice_dir, exist_ok=True)
        got = []
        for download in items:
            try:
                fname = sanitize_name(
                    download.suggested_filename
                    or f"{row.get('notice_type') or 'notice'}-{row.get('ref_id') or 'doc'}.pdf")
                path = dedupe_path(notice_dir, fname)
                await download.save_as(path)
                bucket = ("order" if row.get("is_order")
                          else "reply" if re.search(r"repl|response", fname, re.I)
                          else "notice")
                got.append({"path": path, "label": fname, "bucket": bucket})
                step(f"[Victory] Saved GST document: {os.path.basename(path)}")
            except Exception as exc:
                step(f"[Warning] GST download save failed: {str(exc)[:80]}")
        return got

    if only_description:
        needle = only_description.lower()
        rows = [r for r in rows
                if needle in (str(r.get("description", "")) + " "
                              + str(r.get("notice_type", ""))).lower()]
    if max_rows:
        rows = rows[:max_rows]
    total_rows = len(rows)
    for position, row in enumerate(rows, start=1):
        if _stopped():
            break
        if progress_callback:
            try:
                progress_callback("progress", position, total_rows, row)
            except Exception:
                pass
        if await _visible_row_count(page) < len(rows):
            await _set_page_size(page, 100)
            await asyncio.sleep(1.5)
        index = int(row.get("index") or 0)
        key = notice_key(row)
        previous = old_by_key.get(key) or {}
        already = (key and _files_present(download_root, previous.get("files"))
                   and (previous.get("responded") or previous.get("is_order")
                        or not previous.get("addtnl_docs")))
        if already:
            step(f"Cached (unchanged): GST notice {index} [{key}]")
            skipped += 1
            files_by_key[key] = {
                "files": previous.get("files") or [],
                "reply_files": previous.get("reply_files") or [],
                "order_files": previous.get("order_files") or [],
            }
            continue

        pending_downloads.clear()
        notice_dir = os.path.join(download_root, f"notice-{index:02d}")
        detail_url = ""
        got: list[dict] = []
        try:
            got, detail_url = await _fetch_notice(
                page, row, notice_dir, step, pending_downloads,
                before_download=before_download)
            if not got and pending_downloads:
                got.extend(await _save_pending(pending_downloads, notice_dir, row, step))
        except Exception as exc:
            step(f"[Warning] Could not open GST notice {index}: {exc}")
            warnings.append(f"{row.get('notice_type') or 'Notice'} {index}: open failed")
            await _close_any_modal(page)
            got, detail_url = [], ""

        files, replies, orders = [], [], []
        for item in got:
            rel = f"notice-{index:02d}/{os.path.basename(item['path'])}"
            files.append(rel)
            if item["bucket"] == "reply":
                replies.append(rel)
            elif item["bucket"] == "order" or row.get("is_order"):
                orders.append(rel)
            saved.append({"path": item["path"],
                          "proceeding": (row.get("notice_type") or row.get("ref_id") or ""),
                          "kind": item["bucket"]})
        if not got:
            warnings.append(f"GST notice {index}: no attachment (portal detail only)")
        files_by_key[key] = {
            "files": files,
            "reply_files": replies,
            "order_files": orders,
        }
        row["detail_url"] = detail_url
        await _close_any_modal(page)
        try:
            await page.bring_to_front()
            await page.evaluate("() => window.scrollTo(0, 0)")
        except Exception:
            pass

        if not await _notices_visible(page):
            try:
                await navigate_to_notices(page, log_callback)
                await asyncio.sleep(1.5)
            except Exception as exc:
                step(f"[Warning] Could not return to GST notices: {exc}")
                warnings.append("navigation lost after a notice")
                break

    try:
        meta = merge_meta(old_meta, rows, files_by_key,
                          datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        save_meta(download_root, meta)
        step(f"Saved GST metadata ({len(saved)} new, {skipped} unchanged)")
    except Exception as exc:
        step(f"[Warning] Could not save GST _meta.json: {exc}")
        warnings.append("metadata save failed")

    log_only = sum(1 for r in rows if r.get("detail_url")
                   and not (r.get("doc_id") and r.get("app_def_id"))
                   and (r.get("appln_cd") or "").upper()
                   in ("APL3A", "APLSM", "DRC01B", "DRC01C"))
    if not saved and skipped:
        return True, f"Up to date ({skipped} unchanged)", []
    if not saved and log_only and not any(
            "open failed" in w for w in warnings):
        # Every row opened but the portal exposes no downloadable document
        # (return-defaulter / mismatch summary notices) — not a failure.
        return True, f"No attachments — {log_only} notice(s) in portal only", []
    if not saved and not any("open failed" in w for w in warnings) and rows:
        return True, "No attachments (portal detail only)", []
    if not saved:
        return False, "; ".join(warnings) or "No GST notice documents found", []
    if warnings:
        return True, "; ".join(warnings), saved
    return True, "", saved
