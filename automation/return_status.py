"""
automation/return_status.py
=============================
F-67 — check a filed return's current ITD processing status for one client,
one Assessment Year, WITHOUT downloading any documents. Deliberately a
lighter-weight sibling of automation/downloader_filed_returns.py, reusing its
already-confirmed navigation and AY-filter helpers (navigate_to_view_filed_
returns, apply_ay_filter) and several of its private per-card readers
(_read_filing_date, _read_ack_no, _is_discarded, _pager_arrow_enabled,
_goto_page) rather than duplicating that logic — see this app's own repeated
"Form 168 emailer bug" lesson (automation/doc_types.py's docstring) on why
two copies of the same scraping logic drift apart.

Same "most recent filing wins" rule as downloader_filed_returns.py's
filing_scope="latest": one AY can have more than one filing (Original,
Revised, Rectification, ...) — this always reports the status of whichever
one has the latest Filing Date, since that's the one that actually reflects
where things currently stand.
"""

import asyncio
import os
import re

from playwright.async_api import Page

from automation.downloader import make_step_logger
from automation.downloader_filed_returns import (
    navigate_to_view_filed_returns,
    apply_ay_filter,
    _read_filing_date,
    _read_ack_no,
    _is_discarded,
    _is_return_verified,
    _sanitize_filing_type,
    _pager_arrow_enabled,
    _goto_page,
    _INTIMATION_DATE_RE,
)

# UNCONFIRMED: section source on the filed-returns card is best-effort; verify
# against a real export (F-121). Anchored on an explicit "u/s"/"section" lead or
# a "139(1)"-style parenthesised clause so a bare 3-digit number elsewhere on the
# card (dates, ack numbers) is never misread as a section.
_SECTION_RE = re.compile(
    r"(?:u/s\.?\s*|section\s+)(\d{3}\s*\(\s*\d+[a-z]?\s*\)|\d{3}[a-z]?)"
    r"|(\d{3}\s*\(\s*\d+[a-z]?\s*\))",
    re.IGNORECASE,
)


async def _read_latest_status(card, step) -> tuple[str, str]:
    """Confirmed markup (shared with _is_discarded/_is_return_verified in
    downloader_filed_returns.py): one .matStepStatus element per step on the
    filing's status timeline. BUG FIX (2026-09-07): confirmed live (a real
    portal screenshot, client Santosh Kumari Malik, AY 2026-27) — the
    timeline renders NEWEST-first, not chronological: "Processed with no
    demand/refund" (Aug 3) appeared above "Successfully e-Verified" (Jul 29)
    which appeared above "Pending for e-Verification" (also Jul 29, the
    earliest step). The original code took the LAST step assuming
    oldest-to-newest order, which reported "Pending for e-Verification" —
    the very first, most outdated step — as the client's current status,
    even though the return was actually already fully processed. Now reads
    the FIRST step instead, which is the most advanced one actually
    reached.

    Returns (status_text, status_date) — status_date is the date the
    PORTAL itself shows against that step (e.g. "Aug 3, 2026"), read from
    the step's own container text via the same date regex already used for
    Intimation Order dates, since the date isn't inside .matStepStatus
    itself (confirmed live: that element's own text is just the status
    label, e.g. "ITR Filed" with no date). UNCONFIRMED, flagged for live
    testing: the container is assumed to be .matStepStatus's immediate
    parent — if a live check shows the date living somewhere else in the
    step's markup, this is the one thing to fix here."""
    try:
        statuses = card.locator(".matStepStatus")
        count = await statuses.count()
        if count == 0:
            step("No .matStepStatus steps found on this card")
            return "", ""
        latest = statuses.nth(0)
        text = (await latest.inner_text() or "").strip()
        step(f"Latest status step ({count} total): '{text}'")

        status_date = ""
        try:
            container_text = await latest.locator("xpath=..").inner_text()
            m = _INTIMATION_DATE_RE.search(container_text)
            if m:
                status_date = m.group(1)
                step(f"Latest status date: '{status_date}'")
            else:
                step(f"No date found in status step container text: '{container_text}'")
        except Exception as e:
            step(f"Could not read status step date: {e}")

        return text, status_date
    except Exception as e:
        step(f"Could not read status stepper: {e}")
        return "", ""


async def _find_latest_card(filed_returns_page, assessment_year: str, step):
    """Page-walk scan + 'most recent filing wins' resolution, factored out so
    scan_latest_status() and scan_full_status() share the exact same
    card-selection logic rather than keeping two copies that could drift
    apart. Resets the pager to page 0 first, records every non-discarded AY
    card's Filing Date as a cheap candidate, then navigates back to the
    winning card's page.

    Returns (card_locator, winner_dict, current_page) on success — the card
    locator is valid only while that page stays rendered (Playwright
    locators re-query lazily) — or None if no non-discarded filing exists
    for this AY."""
    next_page_btn = filed_returns_page.locator("img[alt='next page']").first
    prev_page_btn = filed_returns_page.locator("img[alt='previous page']").first

    # Reset to the first page before scanning. This function's own paging
    # below always starts counting from page 0 — fine when called right
    # after apply_ay_filter() (which lands on page 0 already), but NOT
    # safe when called after a download pass that may have paged forward
    # to find/download a specific filing and left the pager there. Without
    # this, the scan below could start mid-way through the results and
    # miss earlier cards, or double-count pages already stepped through.
    for _reset_attempt in range(10):
        try:
            if await _pager_arrow_enabled(prev_page_btn, step, "previous"):
                await prev_page_btn.click()
                await asyncio.sleep(1)
            else:
                break
        except Exception as e:
            step(f"Pager reset-to-first-page failed (continuing): {e}")
            break

    candidates: list[dict] = []
    current_page = 0
    for _page_num in range(10):  # same hard cap as downloader_filed_returns.py
        step(f"Scanning page {current_page} for AY {assessment_year} cards")
        all_cards = filed_returns_page.locator("mat-card.contextBox")
        card_count = await all_cards.count()
        for i in range(card_count):
            card = all_cards.nth(i)
            try:
                ay_text = await card.locator(".contentHeadingText").first.inner_text()
            except Exception as e:
                step(f"Card {i}: could not read AY heading ({e})")
                ay_text = ""
            if assessment_year not in ay_text:
                continue
            if await _is_discarded(card, step):
                step(f"Card {i}: discarded — excluded from 'latest' comparison")
                continue
            date_text, date_parsed = await _read_filing_date(card, step)
            candidates.append({
                "page": current_page, "index": i,
                "date_text": date_text, "date_parsed": date_parsed,
            })

        try:
            if await _pager_arrow_enabled(next_page_btn, step, "next"):
                await next_page_btn.click()
                await asyncio.sleep(1)
                current_page += 1
            else:
                break
        except Exception as e:
            step(f"Next-page click failed ({e}) — stopping scan")
            break

    if not candidates:
        step(f"No non-discarded filing found for AY {assessment_year}")
        return None

    dated = [c for c in candidates if c["date_parsed"] is not None]
    winner = max(dated, key=lambda c: c["date_parsed"]) if dated else candidates[0]
    step(f"Latest filing: page={winner['page']}, index={winner['index']}, date={winner['date_text']}")

    current_page = await _goto_page(winner["page"], current_page, next_page_btn, prev_page_btn, step)
    card = filed_returns_page.locator("mat-card.contextBox").nth(winner["index"])
    return card, winner, current_page


async def scan_latest_status(filed_returns_page, assessment_year: str, step) -> dict:
    """The card-scan + 'most recent filing wins' resolution + status/date
    read, factored out of check_return_status() so it can be reused by
    ANY caller that has already navigated to View Filed Returns and
    applied the AY filter for this year — not just check_return_status()
    itself. In particular, automation/downloader_filed_returns.py's
    download flow calls this too (F-67 "kill two birds" follow-up): it
    has already navigated + AY-filtered the page as part of downloading
    that year's documents, so reusing that same page here avoids a
    second, separate navigate+filter (the expensive/fragile part) just
    to also record processing status — only the comparatively cheap
    per-card scan below is repeated.

    Returns {"ok", "reason", "status", "status_date", "filing_date", "ack_no"}
    — see check_return_status()'s docstring for what each field means."""
    empty = {"ok": False, "reason": "", "status": "", "status_date": "", "filing_date": "", "ack_no": ""}

    found = await _find_latest_card(filed_returns_page, assessment_year, step)
    if found is None:
        return {**empty, "reason": f"No filing found for AY {assessment_year}"}

    card, winner, _current_page = found
    ack_no = await _read_ack_no(card, step)
    status_text, status_date = await _read_latest_status(card, step)

    if not status_text:
        return {**empty, "reason": "Found the filing but could not read its status"}

    return {
        "ok": True, "reason": "", "status": status_text, "status_date": status_date,
        "filing_date": winner["date_text"], "ack_no": ack_no,
    }


def _derive_refund_status(timeline_text: str) -> str:
    """Best-effort refund outcome from the status timeline text: a 'refund'
    step that also mentions paid/credited is done ("paid"); any 'adjusted'
    step is "adjusted"; a 'refund' step with neither is still "pending";
    otherwise "" (not a refund case at all)."""
    low = (timeline_text or "").lower()
    if "adjusted" in low:
        return "adjusted"
    if "refund" in low:
        if "paid" in low or "credited" in low:
            return "paid"
        return "pending"
    return ""


_VERIFIED_RE = re.compile(r"e-?\s*verif", re.IGNORECASE)
_PROCESSED_RE = re.compile(r"process", re.IGNORECASE)


def _is_everify_pending(status_text) -> bool:
    """Heuristic on a raw portal status string: True if the filing looks like
    it still awaits e-verification. Never raises on junk input."""
    text = str(status_text or "")
    return bool(re.search(r"pending for e-?\s*verif", text, re.IGNORECASE))


def compute_everify_pending(filed, e_verified, status_text: str = "") -> bool:
    """Whether the latest filing is filed-but-not-yet-e-verified.

    An explicit e_verified flag wins: True => not pending, False => pending.
    When the flag is unknown (None) and the return is filed, fall back to the
    status text: a verified/processed status means not pending, anything else
    (including a bare "ITR Filed") means still pending."""
    if not filed:
        return False
    if e_verified is True:
        return False
    if e_verified is False:
        return True
    text = str(status_text or "")
    if re.search(r"pending for e-?\s*verif", text, re.IGNORECASE):
        return True
    if _VERIFIED_RE.search(text) or _PROCESSED_RE.search(text):
        return False
    return True


def _extract_section(card_text: str) -> str:
    """Best-effort tax-section under which the return was filed, read from the
    filed-returns card text (e.g. "139(1)", "142(1)").

    UNCONFIRMED (F-121): the portal doesn't expose a dedicated section field on
    the card, so this scrapes an explicit "u/s"/"section" lead or a bare
    "NNN(n)" clause. Returns "" — the honest result — when no such clause is
    present rather than guessing from stray numbers (dates, ack numbers)."""
    # verify against a real export (F-121).
    m = _SECTION_RE.search(card_text or "")
    if not m:
        return ""
    token = m.group(1) or m.group(2) or ""
    return re.sub(r"\s+", "", token)


async def scan_full_status(filed_returns_page, assessment_year: str, step) -> dict:
    """Richer sibling of scan_latest_status(): reuses the exact same
    _find_latest_card() 'latest non-discarded filing wins' card selection,
    but reads extra fields off the winning card instead of only
    status/date/ack. Returns the scan_latest_status() dict as a superset,
    plus filing_type, filed, section, revised, revised_section, rectified,
    e_verified, processed, refund_status. Honesty over completeness: fields
    whose source isn't clearly exposed by the portal are left "" / None
    rather than guessed."""
    empty = {
        "ok": False, "reason": "", "status": "", "status_date": "",
        "filing_date": "", "ack_no": "",
        "filing_type": "", "filed": None, "section": "", "revised": None,
        "revised_section": "", "rectified": None, "e_verified": None,
        "processed": None, "refund_status": "", "everify_pending": None,
    }

    found = await _find_latest_card(filed_returns_page, assessment_year, step)
    if found is None:
        return {**empty, "reason": f"No filing found for AY {assessment_year}", "filed": False}

    card, winner, _current_page = found
    ack_no = await _read_ack_no(card, step)
    status_text, status_date = await _read_latest_status(card, step)

    try:
        raw_filing_type = await card.locator(".leftSideVal").first.inner_text()
    except Exception as e:
        step(f"Could not read Filing Type field: {e}")
        raw_filing_type = ""
    filing_type = _sanitize_filing_type(raw_filing_type, step) if (raw_filing_type or "").strip() else ""

    e_verified = await _is_return_verified(card, step)

    timeline_text = ""
    try:
        statuses = card.locator(".matStepStatus")
        count = await statuses.count()
        parts = [(await statuses.nth(i).inner_text() or "").strip() for i in range(count)]
        timeline_text = " | ".join(p for p in parts if p)
    except Exception as e:
        step(f"Could not read full status timeline: {e}")

    try:
        card_text = await card.inner_text()
    except Exception as e:
        step(f"Could not read card text: {e}")
        card_text = ""

    section = _extract_section(card_text)
    refund_status = _derive_refund_status(timeline_text)
    latest_low = (status_text or "").lower()

    revised = filing_type in ("Revised", "Updated", "Modified") if filing_type else None
    rectified = (filing_type == "Rectification") if filing_type else None

    if not status_text:
        return {**empty, "reason": "Found the filing but could not read its status", "filed": True}

    everify = compute_everify_pending(True, e_verified, status_text)
    return {
        "ok": True, "reason": "", "status": status_text, "status_date": status_date,
        "filing_date": winner["date_text"], "ack_no": ack_no,
        "filing_type": filing_type, "filed": True,
        "section": section,
        "revised": revised,
        "revised_section": section if revised else "",
        "rectified": rectified,
        "e_verified": e_verified,
        "processed": ("processed" in latest_low) if status_text else None,
        "refund_status": refund_status,
        "everify_pending": everify,
    }


async def check_return_status(page: Page, assessment_year: str, log_callback,
                               pan: str = "", dob: str = "") -> dict:
    """One already-logged-in client, one Assessment Year. Returns:
    {"ok": bool, "reason": str, "status": str, "status_date": str,
     "filing_date": str, "ack_no": str}
    ok=False covers: AY filter didn't apply, no (non-discarded) filing found
    for this AY, or a navigation/timeout failure — reason has a short
    human-readable explanation in every ok=False case. status is the raw
    text of the latest filing's current stepper step (e.g. "ITR processed",
    "Successfully e-Verified", "Pending for e-Verification") — shown exactly
    as the portal itself shows it, never simplified or remapped. status_date
    is the date the PORTAL shows against that same step (e.g. "Aug 3,
    2026") — distinct from filing_date (when the return was filed) and from
    whatever timestamp the caller records for "when this app last checked.

    Beyond those original keys, the returned dict is scan_full_status()'s
    superset — it also carries filing_type, filed, section, revised,
    revised_section, rectified, e_verified, processed and refund_status (see
    that function's docstring). It reads via scan_full_status() directly
    rather than also calling scan_latest_status() so the portal is only
    scanned once; every original key keeps its exact prior meaning."""
    step = make_step_logger(log_callback, "RETSTATUS")
    empty = {
        "ok": False, "reason": "", "status": "", "status_date": "",
        "filing_date": "", "ack_no": "",
        "filing_type": "", "filed": None, "section": "", "revised": None,
        "revised_section": "", "rectified": None, "e_verified": None,
        "processed": None, "refund_status": "", "everify_pending": None,
    }
    try:
        step(f"Starting return status check — AY={assessment_year}, pan={'set' if pan else 'blank'}")
        filed_returns_page = await navigate_to_view_filed_returns(page, log_callback)

        filtered = await apply_ay_filter(filed_returns_page, assessment_year, step)
        if not filtered:
            # Unlike the full download flow, a status-only check has no
            # reason to fall back to a full page-walk scan — the AY filter
            # is cheap and reliable; if it didn't apply, something on the
            # portal side is off and guessing at a status would be worse
            # than just reporting the failure plainly.
            step("AY filter did not apply — reporting failure rather than guessing")
            return {**empty, "reason": f"Could not filter to Assessment Year {assessment_year} on the portal"}

        return await scan_full_status(filed_returns_page, assessment_year, step)
    except Exception as e:
        err = str(e)
        step(f"[Error] Return status check failed: {err}")
        if "Timeout" in err or "timeout" in err:
            reason = "Timed out waiting for portal response (try again)"
        elif "net::" in err.lower():
            reason = "Network error — check internet connection"
        elif "Target page" in err or "browser has been closed" in err:
            reason = "Browser closed unexpectedly"
        else:
            reason = err[:80] if len(err) <= 80 else err[:77] + "..."
        return {**empty, "reason": reason}


def _year_tokens(ay_value: str) -> list[str]:
    """Year spellings to look for inside a filed-forms tree for a given
    Assessment Year (2024-25 => "2024-25" / "2024_25").

    Audit reports (3CB-3CD / 3CA-3CD) are keyed by Assessment Year on the
    portal, so only AY spellings are returned — deliberately no Financial Year
    variant, which for the same AY would be the *previous* year and would let a
    different year's audit report satisfy this one."""
    raw = (ay_value or "").strip()
    m = re.match(r"(\d{4})\D(\d{2})", raw)
    if not m:
        return [raw.replace("-", "_").lower()] if raw else []
    start = int(m.group(1))
    end = str((start + 1) % 100).zfill(2)
    return sorted([f"{start}-{end}", f"{start}_{end}"])


def _path_has_year(rel: str, tokens: list[str]) -> bool:
    """Whether a filed-form's relative path contains one of the year tokens as
    a whole number run (not embedded in a longer digit sequence), so
    "2024-25" never matches inside "2025-26" and vice versa."""
    low = (rel or "").replace("\\", "/").lower()
    if not tokens:
        return True
    for tok in tokens:
        if re.search(r"(?<!\d)" + re.escape(tok) + r"(?!\d)", low):
            return True
    return False


def has_audit_report(download_root: str, pan: str, ay_value: str) -> bool | None:
    """Whether a tax-audit report (Form 3CB-3CD / 3CA-3CD) was downloaded for
    this client/year — a presence check only, no portal hit.

    Returns True if such an artifact is found under the client's Income-Tax
    Forms tree for the year, False if the client folder / 'Filed IT Forms'
    dir exists but no matching audit file is present, and None if there is
    nothing to inspect yet (no client folder or no 'Filed IT Forms' dir —
    i.e. unknown, not yet downloaded).

    Layout (confirmed by app.py's _out_for_year / handle_filed_forms):
    ``<download_root>/<PAN>-<name...>/Filed IT Forms/<Form>/<AY|FY>/...`` —
    the outer path is not year-scoped (forms carry their own AY/FY), so the
    year is matched inside the recursive file path."""
    pan = (pan or "").strip().upper()
    if not pan or not os.path.isdir(download_root):
        return None
    client_dir = None
    try:
        for name in os.listdir(download_root):
            if name.upper().startswith(pan + "-") or name.upper() == pan:
                candidate = os.path.join(download_root, name)
                if os.path.isdir(candidate):
                    client_dir = candidate
                    break
    except OSError:
        return None
    if not client_dir:
        return None

    forms_root = os.path.join(client_dir, "Filed IT Forms")
    if not os.path.isdir(forms_root):
        return None

    tokens = _year_tokens(ay_value)
    for dirpath, _dirnames, filenames in os.walk(forms_root):
        for fname in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fname), forms_root)
            low = rel.lower()
            if "3cb" not in low and "3cd" not in low:
                continue
            if _path_has_year(rel, tokens):
                return True
    return False


_AUDIT_CATEGORY_RE = re.compile(r"3c[ab]\s*-\s*3cd", re.IGNORECASE)


async def probe_audit_report(page, step) -> bool:
    """Whether the portal lists an audit-report form (Form 3CB-3CD or
    3CA-3CD) under Income Tax Forms for this already-logged-in client.

    ``page`` must already be on the Income Tax Forms category-listing screen
    (navigate_to_filed_forms()). Reads every visible ``.eachMatCardStyle``
    card text and looks for a "3CB-3CD"/"3CA-3CD" form code — the same card
    markup downloader_filed_forms._read_category_cards() uses. Returns True
    if an audit-report category is present, False otherwise. Raises only on
    page-level failure so the caller can fall back to has_audit_report()."""
    cards = await page.evaluate("""() => {
        const visible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };
        return [...document.querySelectorAll('.eachMatCardStyle')]
            .filter(visible)
            .map(el => (el.innerText || '').replace(/\\s+/g, ' ').trim())
            .filter(Boolean);
    }""")
    for text in cards or []:
        if _AUDIT_CATEGORY_RE.search(text):
            step(f"Audit report form present on portal: {text[:80]}")
            return True
    step(f"No audit-report (3CB-3CD/3CA-3CD) category found ({len(cards or [])} cards)")
    return False
