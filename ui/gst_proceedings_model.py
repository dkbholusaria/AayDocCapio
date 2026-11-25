"""GST proceedings data model.

GST has its own notice/order shape (one flat list, not Income Tax proceeding
cards), so this model is separate from :mod:`ui.eproceedings_model`. It reads
the GST ``_meta.json`` files written by
:func:`automation.gst.notices.download_gst_notices`.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_CLOSED_WORDS = ("closed", "order passed", "disposed", "completed", "final")


@dataclass
class GstDoc:
    id: str
    kind: str
    title: str
    label: str
    files: list = field(default_factory=list)


@dataclass
class GstCase:
    id: str
    client_key: str
    client_name: str
    gstin: str
    trade_name: str
    notice_type: str
    ref_id: str
    description: str
    section: str
    issued: str
    due: str
    raw_status: str
    status: str
    responded: bool
    is_order: bool
    amount: str = ""
    doc_id: str = ""
    app_def_id: str = ""
    case_id: str = ""
    order_id: str = ""
    reply_id: str = ""
    detail_url: str = ""
    docs: list = field(default_factory=list)
    root: str = ""
    downloaded_at: str = ""

    @property
    def title(self) -> str:
        parts = [self.notice_type or "GST Notice"]
        if self.section:
            parts.append(f"u/s {self.section}")
        return " ".join(parts)

    @property
    def file_count(self) -> int:
        return sum(len(doc.files) for doc in self.docs)


def _parse_date(value: str):
    text = (value or "").strip()
    if not text:
        return None
    text = text.split()[0] if re.match(r"^\d", text) else text
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y",
                "%d %b %Y", "%d-%b-%y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.search(r"(\d{1,2})[-/ ]([A-Za-z]{3,9})[-/ ](\d{2,4})", text)
    if match:
        day, month, year = match.groups()
        month_num = _MONTHS.get(month[:3].lower())
        if month_num:
            year_num = int(year)
            if year_num < 100:
                year_num += 2000
            try:
                return date(year_num, month_num, int(day))
            except ValueError:
                return None
    return None


def _today() -> date:
    return date.today()


def _client_identity(folder_name: str) -> tuple[str, str]:
    if "-" in folder_name:
        key, name = folder_name.split("-", 1)
        return key.strip(), name.strip()
    return folder_name.strip(), folder_name.strip()


def _assessee_for(key: str, assessees: list[dict]) -> dict:
    target = (key or "").upper()
    for assessee in assessees or []:
        if (assessee.get("pan") or "").upper() == target:
            return assessee
        if (assessee.get("gst_username") or "").upper() == target:
            return assessee
    return {}


def _load_meta(root: str) -> dict:
    try:
        with open(os.path.join(root, "_meta.json"), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def iter_gst_roots(root: str) -> list[str]:
    root = os.path.abspath(root or "")
    if not os.path.isdir(root):
        return []
    if os.path.basename(root).lower() in ("gst-proceedings", "gst_proceedings"):
        return [root]
    found = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return []
    for entry in entries:
        candidate = os.path.join(root, entry)
        if not os.path.isdir(candidate):
            continue
        for folder in ("GST-Proceedings", "GST_Proceedings"):
            target = os.path.join(candidate, folder)
            if os.path.isdir(target):
                found.append(target)
                break
    return found


def _status_from(meta_entry: dict, replied: bool, is_order: bool,
                 due: str, today: date) -> str:
    raw = (meta_entry.get("status") or "").strip()
    low = raw.lower()
    if is_order or meta_entry.get("order_files"):
        return "Closed"
    if any(word in low for word in _CLOSED_WORDS):
        return "Closed"
    if replied:
        return "Replied"
    due_date = _parse_date(due)
    if due_date is not None and due_date < today:
        return "Overdue"
    return "Open"


def build_cases(root: str, assessees: list[dict] | None = None,
                today: date | None = None) -> list[GstCase]:
    current = today or _today()
    assessees = assessees or []
    cases: list[GstCase] = []
    for gst_root in iter_gst_roots(root):
        client_folder = os.path.basename(os.path.dirname(gst_root))
        client_key, folder_name = _client_identity(client_folder)
        assessee = _assessee_for(client_key, assessees)
        client_name = (assessee.get("name") or folder_name or client_key).strip()
        meta = _load_meta(gst_root)
        downloaded_at = (meta.get("downloaded_at") or "").strip()

        for position, entry in enumerate(meta.get("notices") or [], start=1):
            try:
                index = int(entry.get("index"))
            except (TypeError, ValueError):
                index = position
            if index <= 0:
                index = position

            files = list(entry.get("files") or [])
            reply_files = list(entry.get("reply_files") or [])
            order_files = list(entry.get("order_files") or [])
            is_order = bool(entry.get("is_order")) or bool(order_files)
            replied = bool(entry.get("responded")) or bool(reply_files)
            notice_type = (entry.get("notice_type") or "").strip()
            ref_id = (entry.get("ref_id") or "").strip()
            due = (entry.get("due_date") or "").strip()
            status = _status_from(entry, replied, is_order, due, current)

            docs: list[GstDoc] = []
            for kind, rels in (
                    ("notice", [f for f in files if f not in reply_files and f not in order_files]),
                    ("reply", reply_files),
                    ("order", order_files)):
                for rel in rels:
                    docs.append(GstDoc(
                        id=f"{client_key}:{index}:{kind}:{rel}",
                        kind=kind,
                        title=os.path.basename(rel),
                        label=f"{notice_type or 'Notice'} — {os.path.basename(rel)}",
                        files=[rel],
                    ))
            if not docs and files:
                for rel in files:
                    docs.append(GstDoc(
                        id=f"{client_key}:{index}:file:{rel}",
                        kind="notice",
                        title=os.path.basename(rel),
                        label=os.path.basename(rel),
                        files=[rel],
                    ))

            cases.append(GstCase(
                id=f"{client_key}:{index:02d}",
                client_key=client_key,
                client_name=client_name,
                gstin=(entry.get("gstin") or "").strip(),
                trade_name=(entry.get("trade_name") or "").strip(),
                notice_type=notice_type,
                ref_id=ref_id,
                description=(entry.get("description") or "").strip(),
                section=(entry.get("section") or "").strip(),
                issued=(entry.get("issued_on") or "").strip(),
                due=due,
                raw_status=(entry.get("status") or "").strip(),
                status=status,
                responded=replied,
                is_order=is_order,
                amount=(entry.get("amount") or "").strip(),
                doc_id=(entry.get("doc_id") or "").strip(),
                app_def_id=(entry.get("app_def_id") or "").strip(),
                case_id=(entry.get("case_id") or "").strip(),
                order_id=(entry.get("order_id") or "").strip(),
                reply_id=(entry.get("reply_id") or "").strip(),
                detail_url=(entry.get("detail_url") or "").strip(),
                docs=docs,
                root=gst_root,
                downloaded_at=downloaded_at,
            ))
    cases.sort(key=lambda c: (_sort_date(c.issued), c.client_name.lower(),
                              c.notice_type.lower()))
    return cases


def _sort_date(value: str) -> date:
    return _parse_date(value) or date.min


def derive_status(case: GstCase, today: date | None = None) -> str:
    return _status_from(
        {"status": case.raw_status, "order_files": case.is_order},
        case.responded, case.is_order, case.due, today or _today())


def kpis(cases: list[GstCase]) -> dict:
    counts = {"total": 0, "open": 0, "replied": 0, "overdue": 0,
              "orders": 0, "files": 0}
    for case in cases or []:
        counts["total"] += 1
        counts["files"] += case.file_count
        if case.is_order:
            counts["orders"] += 1
        key = case.status.lower()
        if key in counts:
            counts[key] += 1
    return counts


def filter_cases(cases: list[GstCase], search: str = "",
                 status: str = "") -> list[GstCase]:
    query = (search or "").strip().lower()
    wanted = (status or "").strip().lower()
    result = []
    for case in cases or []:
        if wanted and wanted != "all" and case.status.lower() != wanted:
            continue
        if query:
            haystack = " ".join((
                case.client_name, case.client_key, case.gstin, case.trade_name,
                case.notice_type, case.ref_id, case.description, case.section,
                case.issued, case.due, case.status)).lower()
            if query not in haystack:
                continue
        result.append(case)
    return result


def case_folder(case: GstCase) -> str:
    return case.root


def amount_value(case: GstCase) -> float:
    """Parse the portal's amount text; 0.0 when it is 'NA'/blank/non-numeric."""
    text = (case.amount or "").replace(",", "").replace("₹", "").strip()
    if not text or text.upper() in ("NA", "N/A", "-"):
        return 0.0
    match = re.search(r"-?\d+(\.\d+)?", text)
    return float(match.group(0)) if match else 0.0
