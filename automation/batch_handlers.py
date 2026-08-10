"""
automation/batch_handlers.py
=============================
Per-document-type batch handlers, extracted from app.py's _execute_batch
dispatch chain. Each handler downloads exactly one document type for one
already-logged-in client and reports progress via the passed-in callbacks —
no dependency on the App class, so adding a new document type here doesn't
grow app.py further.

Every handler shares the same signature (even though each only uses a
subset of the parameters) so the dispatch loop in app.py can call any of
them uniformly via the HANDLERS table.
"""
import asyncio

from automation.downloader_ais_tis import run_request_ais, run_download_ais_tis
from automation.downloader_filed_returns import download_filed_returns
from forms import form_spec, DEFAULT_FORM

DOC_TYPE_LABELS = {
    "26as": "26AS/Form 168",
    "request_ais": "AIS Request",
    "ais_tis": "AIS/TIS",
    "filed_returns": "Filed Returns",
}


# Confirmed live via log: the dashboard's own e-File > "Income Tax Returns"
# flow lands here after login ("[Auth] Dashboard ready: .../#/dashboard/
# fileIncomeTaxReturn"). Used to force the SPA's client-side router back to
# the base dashboard view between handlers.
_DASHBOARD_HASH = "#/dashboard/fileIncomeTaxReturn"


async def ensure_dashboard(page, log_callback=None):
    """Reset the shared tab back to the base dashboard route before the next
    e-File-based handler starts its own navigation.

    Root cause, confirmed live: a handler like Filed Returns navigates the
    shared tab into its own sub-view ("View Filed Returns" — a genuine
    client-side route change, not a reload) and never returns to the base
    dashboard route when done. The next handler's e-File hover then runs
    from inside that sub-view — "e-File" itself is still hoverable (it's a
    persistent top-nav element), but the "Income Tax Returns" flyout item
    underneath it does not reliably render from a non-dashboard route,
    causing the hover timeout — reproduced identically both directions
    (26AS-then-FiledReturns and FiledReturns-then-26AS).

    Two earlier fix attempts failed for unrelated reasons and are NOT what
    this does: (1) a full page.reload() logs the session out entirely
    (confirmed live — even a manual browser refresh does), and (2) opening
    a fresh tab also fails because the ITD portal keeps its session token in
    sessionStorage, which isn't shared across tabs (also confirmed live).
    Neither problem applies here: setting window.location.hash on an
    Angular hash-routed SPA is a client-side route change only — no HTTP
    request, no reload, no session loss — so it should get back to the
    dashboard route without the failure modes above.
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)
    try:
        await page.evaluate(f"window.location.hash = '{_DASHBOARD_HASH}'")
        await asyncio.sleep(1)
        try:
            await page.locator(".customLoaderBackdrop").wait_for(state="hidden", timeout=15000)
        except Exception:
            pass
        await page.keyboard.press("Escape")
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)
        _log(f"[NAV-RESET] Routed back to dashboard hash before handler navigation (url: {page.url})")
    except Exception as e:
        _log(f"[NAV-RESET] Reset attempt failed (continuing): {e}")


async def handle_26as(page, pan, dob, ay, fy, out, log_callback, set_status,
                       form_type=DEFAULT_FORM, filing_scope="all", is_running=None) -> dict:
    # Previously unnecessary (26AS always ran alone), but now that several
    # doc types can run back-to-back on the same tab in one multi-select
    # batch, 26AS also needs a clean slate if something else ran first.
    await ensure_dashboard(page, log_callback)
    _spec = form_spec(form_type or DEFAULT_FORM)
    _form = _spec["label"]
    set_status(pan, f"⏳ Downloading {_form}...")
    ok, err_msg, txt_path = await _spec["download"](
        page, ay, out, log_callback, pan=pan, dob=dob
    )
    if not ok:
        set_status(pan, f"❌ {_form} Failed — {err_msg}")
        return {"txt_path": None}

    if err_msg:
        # PDF saved but TXT failed (bad password / extraction error)
        set_status(pan, f"⚠ Partially Completed — {err_msg}")
    else:
        set_status(pan, f"✅ {_form} Downloaded")

    if txt_path:
        # Convert immediately while next client logs in
        set_status(pan, "⏳ Converting to Excel...")
        try:
            from automation.as26_converter import convert_26as_txt
            log_callback(f"[Convert] Converting {_form} → Excel/HTML for {pan}…")
            convert_26as_txt(txt_path, log_callback=log_callback)
            set_status(pan, f"✅ {_form} + Excel + HTML")
        except Exception as _conv_exc:
            log_callback(f"[Convert] Warning: conversion failed for {pan}: {_conv_exc}")
            set_status(pan, "⚠ Excel convert failed")

    return {"txt_path": txt_path, "form_label": _form}


async def handle_request_ais(page, pan, dob, ay, fy, out, log_callback, set_status,
                              form_type=DEFAULT_FORM, filing_scope="all", is_running=None) -> dict:
    await ensure_dashboard(page, log_callback)
    set_status(pan, "⏳ Opening AIS portal...")
    result = await run_request_ais(
        page, fy, out, log_callback, pan=pan, dob=dob,
        status_callback=lambda t, _p=pan: set_status(_p, t))
    ais_status = result.get("status")
    ref = result.get("ref_id", "")
    if ais_status == "requested" and ref:
        log_callback(f"[AIS] Generation queued — Ref ID: {ref}")
    # combined_status_label already set via status_callback at end of run_request_ais
    return {"ais_status": ais_status, "ref_id": ref}


async def handle_ais_tis(page, pan, dob, ay, fy, out, log_callback, set_status,
                          form_type=DEFAULT_FORM, filing_scope="all", is_running=None) -> dict:
    # "Download Previously Requested AIS" — fetch ONLY the AIS PDF from
    # Activity History. TIS is not re-downloaded here (it was already
    # grabbed during the Request step).
    await ensure_dashboard(page, log_callback)
    set_status(pan, "⏳ Downloading AIS from Activity History...")
    await run_download_ais_tis(
        page, fy, out, log_callback, pan=pan, dob=dob,
        dl_ais=True, dl_tis=False,
        should_continue=(is_running if is_running else (lambda: True)),
        status_callback=lambda t, _p=pan: set_status(_p, t))
    # combined_status_label already set via status_callback at end of run_download_ais_tis
    return {}


async def handle_filed_returns(page, pan, dob, ay, fy, out, log_callback, set_status,
                                form_type=DEFAULT_FORM, filing_scope="all", is_running=None) -> dict:
    await ensure_dashboard(page, log_callback)
    set_status(pan, "⏳ Downloading Filed Returns...")
    fr_ok, fr_msg, fr_saved = await download_filed_returns(
        page, ay, out, log_callback, pan=pan, dob=dob, filing_scope=filing_scope
    )
    if fr_ok:
        if fr_msg:
            set_status(pan, f"⚠ Partially Completed — {fr_msg}")
        else:
            set_status(pan, f"✅ Filed Returns Downloaded ({len(fr_saved)} file(s))")
    else:
        set_status(pan, f"❌ Filed Returns Failed — {fr_msg}")
    return {"saved": fr_saved}


HANDLERS = {
    "26as": handle_26as,
    "request_ais": handle_request_ais,
    "ais_tis": handle_ais_tis,
    "filed_returns": handle_filed_returns,
}

# Filed Returns has only ever been tested (and confirmed working) running
# FIRST, alone. It reliably fails when it runs after 26AS's e-File hover
# has already been used on the same tab; the reverse combination (Filed
# Returns first, then 26AS) has never been tried. Reload/new-tab resets are
# both ruled out (they log the session out entirely — confirmed live), so
# as a cheap, low-risk experiment, always dispatch Filed Returns before the
# other e-File-based handler (26AS); AIS handlers don't use the e-File menu
# at all, so their position doesn't matter for this bug.
HANDLER_ORDER = ["filed_returns", "26as", "request_ais", "ais_tis"]


def ordered_doc_types(selected_docs):
    """selected_docs is a set with unpredictable iteration order; return it
    as a list following HANDLER_ORDER so dispatch order is deterministic."""
    return [d for d in HANDLER_ORDER if d in selected_docs] + \
           [d for d in selected_docs if d not in HANDLER_ORDER]
