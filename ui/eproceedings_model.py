"""Pure-Python case-workspace model for downloaded e-Proceedings folders.

This module contains NO Qt imports.  It turns the on-disk tree produced by
``automation/downloader_e_proceedings.py`` into a deterministic, testable
data model that the UI (and any future vault / reporting layer) can consume.

Disk layout
-----------
::

    <root>/<PAN>-<NameSafe>/<AY_*|TY_*>/e-Proceedings/<NN>-<ProcName>/
        _meta.json                     (optional, written by the downloader)
        notice-NN/<file>...
        response-NN/<file>...

``_meta.json`` schema (authoritative when present)::

    {"proceeding": {"name": str, "ay": str, "status": str},
     "downloaded_at": "YYYY-MM-DD HH:MM:SS",
     "notices": [{"index": int, "ref_id": str, "description": str,
                  "issued_on": "DD-Mon-YYYY", "response_due": str,
                  "responded": bool, "section": str,
                  "viewed_by_ao": str, "is_order": bool,
                  "files": ["notice-NN/<file>"],
                  "response_files": ["response-NN/<file>"]}]}

Legacy trees (no ``_meta.json``) are inferred from folder names and file
names.  A trailing ``_DDMMYYYY`` (optionally followed by an extension) is
treated as the issue date; the section is read from a ``u/s <n>`` token in
the file name; ``order`` in the file name marks an order; ``penalty`` /
``remand`` / ``set aside`` / ``appeal`` drive the other kinds.

Design notes
------------
* One :class:`Case` per *proceeding directory*, not per client.  A client
  with five proceedings therefore yields five cases.
* ``Case.id`` is stable across rescans (``PAN:NN:YEAR_FOLDER``) so it can be
  used as a vault key.
* Every document id is deterministic: ``<case>#n<idx>`` (notice),
  ``<case>#r<idx>`` (reply) and ``<case>#o<idx>`` (order-like document:
  order, appeal-order, penalty, remand).  Replies use a running counter so
  a notice with several response attachments still gets unique ids.
* All date maths uses :mod:`datetime` / :mod:`calendar` and is injectable via
  a ``today`` argument (defaults to :func:`_today`) for deterministic tests.
"""

from __future__ import annotations

import calendar
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

__all__ = [
    "Assessee",
    "Doc",
    "AppealStep",
    "Appeal",
    "Limitation",
    "Case",
    "build_cases",
    "derive_status",
    "compute_limitations",
    "kpis",
    "timeline_docs",
    "filter_cases",
    "visible_docs",
    "sort_cases",
    "sections_in",
]


# ---------------------------------------------------------------------------
# Dataclasses (public API)
# ---------------------------------------------------------------------------

@dataclass
class Assessee:
    """Minimal client identity embedded in a case workspace."""

    name: str
    pan: str
    email: str = ""
    phone: str = ""
    ward: str = ""


@dataclass
class Doc:
    """One notice / reply / order-like document in a proceeding.

    ``issued``, ``served`` and ``reply_deadline`` use the portal display
    format ``DD-Mon-YYYY`` (or ``""`` when unknown).  ``status`` is filled by
    :func:`derive_status`; ``responded`` records portal/file evidence that the
    client filed a reply and is used by that derivation.  ``viewed_by_ao`` is
    the portal's "Response viewed by AO on" stamp for that reply (same display
    format, ``""`` when the AO has not opened it).
    """

    id: str
    kind: str
    title: str
    section: str
    issued: str
    served: str
    reply_deadline: str
    urg: str
    triggered_by: str = ""
    remands: str = ""
    parent: str = ""
    note: str = ""
    files: list = field(default_factory=list)
    inferred: dict = field(default_factory=dict)
    status: str = ""
    responded: bool = False
    viewed_by_ao: str = ""


@dataclass
class AppealStep:
    """One row in the appeal-progress tracker."""

    label: str
    date: str = ""
    done: bool = False


@dataclass
class Appeal:
    """A first/second appeal inferred for a case."""

    id: str
    forum: str
    against: str
    filed: str = ""
    status: str = "Window open"
    grounds: str = ""
    steps: list = field(default_factory=list)


@dataclass
class Limitation:
    """One limitation / compliance clock row."""

    key: str
    title: str
    provision: str
    due_date: str
    status: str
    elapsed_pct: int
    source_doc: str = ""


@dataclass
class Case:
    """A single proceeding workspace."""

    id: str
    pan: str
    name: str
    ays: list
    case_open: bool
    remanded: bool
    assessee: Assessee
    docs: list
    appeals: list
    proc_name: str
    year_label: str
    proc_dir: str
    downloaded_at: str = ""
    inferred_links: bool = False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_FILE_EXTS = (".pdf", ".jpg", ".jpeg", ".png")

_DISPLAY_FMT = "%d-%b-%Y"

_DATE_FORMATS = (
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
)

_TRAILING_DATE_RE = re.compile(r"_(\d{2})(\d{2})(\d{4})(?:\.\w+)?$")

_SECTION_FILENAME_RE = re.compile(
    r"u/?s\s*([0-9]{1,4}[A-Z]?(?:\([^)]*\))*)", re.IGNORECASE
)
_SECTION_DESC_RE = re.compile(
    r"u/?s\.?\s*([0-9]{1,4}[A-Z]?(?:\([^)]*\))*)", re.IGNORECASE
)

_DESC_TAIL_RE = re.compile(
    r"\s*of\s+income\s+tax\s+act\s*,?\s*1961\s*\.?\s*$", re.IGNORECASE
)

_YEAR_FOLDER_RE = re.compile(r"^(AY|TY)_(\d{4})_(\d{2,4})$", re.IGNORECASE)

_ORDER_KINDS = ("order", "appeal-order", "remand")


def _today() -> date:
    """Return today's date.

    Kept as a module-level helper so tests can monkey-patch it, and so every
    public function that needs a clock can default to ``_today()``.
    """

    return date.today()


def _parse_date(value) -> date | None:
    """Parse a portal display date or an ISO-ish date.  ``None`` on failure."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _fmt_date(value) -> str:
    """Format a :class:`date` as ``DD-Mon-YYYY``; pass strings through."""

    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime(_DISPLAY_FMT)
    return (value or "").strip()


def _display_date(value) -> str:
    """Normalise a raw date string to display form when parseable."""

    parsed = _parse_date(value)
    if parsed is not None:
        return _fmt_date(parsed)
    return (value or "").strip()


def _add_days(value: date, days: int) -> date:
    return value + timedelta(days=days)


def _add_years(value: date, years: int) -> date:
    """Calendar-year arithmetic that tolerates 29 February."""

    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _add_months(value: date, months: int) -> date:
    """Calendar-month arithmetic clamped to the target month's last day."""

    total = (value.year * 12 + (value.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _end_of_month(value: date) -> date:
    return date(value.year, value.month,
                calendar.monthrange(value.year, value.month)[1])


def _end_of_fy(value: date) -> date:
    """End of the Indian financial year containing ``value`` (31 March)."""

    if value.month >= 4:
        return date(value.year + 1, 3, 31)
    return date(value.year, 3, 31)


def _days_between(later: date, earlier: date) -> int:
    return (later - earlier).days


def _year_label(year_name: str) -> str:
    """``AY_2025_26`` -> ``AY 25-26`` (also handles ``TY_*``)."""

    match = _YEAR_FOLDER_RE.match(year_name or "")
    if not match:
        return (year_name or "").replace("_", " ")
    kind = match.group(1).upper()
    start = match.group(2)
    end = match.group(3)
    if len(end) == 4:
        end = end[-2:]
    return f"{kind} {start[-2:]}-{end}"


def _trailing_date(filename: str) -> date | None:
    """Legacy issue date: trailing ``_DDMMYYYY`` in a file name."""

    match = _TRAILING_DATE_RE.search(filename or "")
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)),
                    int(match.group(1)))
    except ValueError:
        return None


def _folder_number(name: str) -> int:
    digits = ""
    for char in name or "":
        if not char.isdigit():
            break
        digits += char
    return int(digits) if digits else 0


def _subfolder_number(name: str) -> int:
    """Number of a ``notice-NN`` / ``response-NN`` subfolder."""

    match = re.search(r"(\d+)\s*$", name or "")
    return int(match.group(1)) if match else 0


def _strip_proc_prefix(name: str) -> str:
    match = re.match(r"^(\d+)\s*[-_ ]?\s*(.*)$", name or "")
    if match:
        return match.group(2).strip()
    return (name or "").strip()


def _pretty_proc_name(name: str) -> str:
    """Folder-safe proceeding name -> human display name."""

    text = _strip_proc_prefix(name)
    text = re.sub(r"(?i)\bu_s\b", "u/s", text)
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clean_description(description: str) -> str:
    """Strip the repetitive ``of Income Tax Act 1961.`` tail."""

    text = (description or "").strip()
    if not text:
        return ""
    text = _DESC_TAIL_RE.sub("", text).strip()
    return re.sub(r"\s+", " ", text)


def _section_from_filename(filename: str) -> str:
    match = _SECTION_FILENAME_RE.search(filename or "")
    return match.group(1).strip() if match else ""


def _section_from_text(text: str) -> str:
    match = _SECTION_DESC_RE.search(text or "")
    return match.group(1).strip() if match else ""


def _is_penalty_section(section: str) -> bool:
    """Penalty sections: 270/270A, 271 variants, 272, 275.

    s.271(1)(c) is by far the most common; the prefix check also catches
    271A / 271AAC / 271F etc.
    """

    normalized = (section or "").replace(" ", "").upper()
    if not normalized:
        return False
    if normalized in {"271", "271(1)(C)", "272", "275"}:
        return True
    return bool(re.match(r"^(270|271|272|273|274|275)", normalized))


def _is_reply(doc: "Doc", case: "Case") -> bool:
    """True when a notice/penalty has portal or file evidence of a reply."""

    if doc.responded:
        return True
    return any(d.kind == "reply" and d.parent == doc.id for d in case.docs)


def _doc_date(doc: "Doc") -> date | None:
    return _parse_date(doc.served) or _parse_date(doc.issued)


def _appeal_against(case: "Case", doc_id: str) -> bool:
    return any(appeal.against == doc_id for appeal in case.appeals)


# ---------------------------------------------------------------------------
# Classification / naming heuristics
# ---------------------------------------------------------------------------

def _classify_kind(description: str, section: str, is_order: bool,
                   proc_name: str, filename: str = "",
                   reply: bool = False) -> str:
    """Decide a document kind using the ordered heuristics from the PRD.

    Order matters:

    1. response attachment -> ``reply`` (always)
    2. penalty: description/file/proceeding mentions penalty, or the section
       belongs to the penalty family
    3. remand: description/file says remand or set aside
    4. appeal-order: an *order* in an appeal proceeding (proceeding name,
       description or file name mentions "appeal")
    5. order: order flag or "order" in the description/file name
    6. notice: everything else

    Steps 4/5 deliberately require order-ish evidence, so ordinary notices
    inside a "First Appeal Proceedings" folder remain notices.
    """

    if reply:
        return "reply"

    desc = (description or "").lower()
    fname = (filename or "").lower()
    pname = (proc_name or "").lower()

    if ("penalty" in desc or "penalty" in fname or "penalty" in pname
            or _is_penalty_section(section)):
        return "penalty"

    if ("remand" in desc or "set aside" in desc
            or "remand" in fname or "set aside" in fname):
        return "remand"

    orderish = bool(is_order) or "order" in desc or "order" in fname
    if orderish and ("appeal" in desc or "appeal" in fname
                     or "appeal" in pname):
        return "appeal-order"
    if orderish:
        return "order"
    return "notice"


def _doc_title(kind: str, description: str, section: str, proc_name: str,
               legacy: bool, parent_section: str = "") -> str:
    """Human title for a document.

    Preference order: the cleaned portal description, then the proceeding
    name for legacy trees, then a section-based synthetic title.
    """

    cleaned = _clean_description(description)
    if cleaned:
        return cleaned
    if legacy:
        return proc_name or "Proceeding"
    if kind == "reply":
        chosen = parent_section or section
        return f"Reply — {chosen}" if chosen else "Reply"
    if kind == "notice":
        return f"Notice u/s {section}" if section else (proc_name or "Notice")
    label = kind.replace("-", " ").title()
    return f"{label} u/s {section}" if section else (proc_name or label)


def _doc_id(case_id: str, kind: str, index: int) -> str:
    """Deterministic id: notices ``#n``, replies ``#r``, order-like ``#o``."""

    if kind == "notice":
        prefix = "n"
    elif kind == "reply":
        prefix = "r"
    else:
        prefix = "o"
    return f"{case_id}#{prefix}{index}"


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _scan_proc_files(proc_dir: str) -> list[dict]:
    """Return the document files inside one proceeding directory.

    Only PDF/JPEG/PNG files count (mirrors the downloader).  Files under
    ``response-*`` are replies; everything else (``notice-*`` or loose files)
    is a notice candidate.  The first path component supplies the pairing
    number used to attach a reply to its notice.
    """

    found: list[dict] = []
    if not os.path.isdir(proc_dir):
        return found

    for dirpath, dirnames, filenames in os.walk(proc_dir):
        dirnames.sort()
        filenames.sort()
        rel_dir = os.path.relpath(dirpath, proc_dir)
        first = "" if rel_dir == "." else rel_dir.split(os.sep)[0]
        lowered = first.lower()
        if lowered.startswith("response"):
            group = "response"
        else:
            group = "notice"
        for name in filenames:
            if not name.lower().endswith(_FILE_EXTS):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, proc_dir).replace(os.sep, "/")
            found.append({
                "path": full,
                "rel": rel,
                "name": name,
                "group": group,
                "folder_num": _subfolder_number(first),
            })

    found.sort(key=lambda item: (item["folder_num"], item["name"].lower(),
                                 item["rel"].lower()))
    return found


def _load_meta(proc_dir: str) -> dict:
    """Best-effort read of ``<proc_dir>/_meta.json`` (else ``{}``)."""

    path = os.path.join(proc_dir, "_meta.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _iter_eproc_roots(root: str) -> list[tuple[str, str, str]]:
    """Find ``(client_dir_name, year_folder_name, eproc_root)`` triples.

    The normal contract is ``<root>/<PAN>-<Name>/<AY_*|TY_*>/e-Proceedings``.
    For convenience the function also accepts:

    * an ``e-Proceedings`` directory itself (the demo layout), deriving the
      client/year folders from its ancestors;
    * a single client directory containing ``AY_*`` / ``TY_*`` folders.
    """

    root = os.path.abspath(root or "")
    if not os.path.isdir(root):
        return []

    base = os.path.basename(root)
    if base.lower() == "e-proceedings":
        year_dir = os.path.dirname(root)
        client_dir = os.path.dirname(year_dir)
        return [(os.path.basename(client_dir), os.path.basename(year_dir),
                 root)]

    triples: list[tuple[str, str, str]] = []

    def _add_years(client_name: str, client_dir: str) -> None:
        try:
            year_names = sorted(os.listdir(client_dir))
        except OSError:
            return
        for year_name in year_names:
            year_dir = os.path.join(client_dir, year_name)
            if not os.path.isdir(year_dir):
                continue
            if not (year_name.startswith("AY_") or year_name.startswith("TY_")):
                continue
            eproc_root = os.path.join(year_dir, "e-Proceedings")
            if os.path.isdir(eproc_root):
                triples.append((client_name, year_name, eproc_root))

    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return []

    child_dirs = [name for name in entries
                  if os.path.isdir(os.path.join(root, name))]
    looks_like_client = ("-" in base and any(
        name.startswith(("AY_", "TY_")) for name in child_dirs))
    if looks_like_client:
        _add_years(base, root)
        return triples

    for entry in child_dirs:
        if "-" not in entry:
            continue
        _add_years(entry, os.path.join(root, entry))
    return triples


# ---------------------------------------------------------------------------
# Case construction
# ---------------------------------------------------------------------------

def _build_meta_docs(case_id: str, proc_name: str, meta: dict) -> list[Doc]:
    """Documents for a proceeding that has ``_meta.json``.

    Every parsed notice becomes a notice/penalty/remand/order/appeal-order
    doc.  Each ``response_files`` entry becomes a reply doc parented to that
    notice.  Reply dates are not in the meta schema, so a trailing
    ``_DDMMYYYY`` in the attachment name is used when available.
    """

    docs: list[Doc] = []
    reply_counter = 0

    notice_docs_by_index: dict[int, Doc] = {}
    for position, notice in enumerate(meta.get("notices") or [], start=1):
        raw_index = notice.get("index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = position
        if index <= 0:
            index = position

        description = notice.get("description", "") or ""
        section = (notice.get("section", "") or
                   _section_from_text(description))
        is_order = bool(notice.get("is_order")) or "order" in description.lower()
        kind = _classify_kind(description, section, is_order, proc_name)
        issued = _display_date(notice.get("issued_on"))
        responded = (bool(notice.get("responded"))
                     or bool(notice.get("response_files")))
        viewed_by_ao = _display_date(notice.get("viewed_by_ao"))

        doc = Doc(
            id=_doc_id(case_id, kind, index),
            kind=kind,
            title=_doc_title(kind, description, section, proc_name, False),
            section=section,
            issued=issued,
            served=issued,
            reply_deadline=_display_date(notice.get("response_due")),
            urg="",
            files=list(notice.get("files") or []),
            responded=responded,
            viewed_by_ao=viewed_by_ao,
        )
        docs.append(doc)
        notice_docs_by_index[index] = doc

        for rel in notice.get("response_files") or []:
            reply_counter += 1
            filename = os.path.basename(rel)
            reply_issue = _trailing_date(filename)
            reply_issued = _fmt_date(reply_issue) if reply_issue else ""
            reply_section = _section_from_filename(filename) or section
            reply = Doc(
                id=_doc_id(case_id, "reply", reply_counter),
                kind="reply",
                title=_doc_title("reply", "", reply_section, proc_name, False,
                                 parent_section=section),
                section=reply_section,
                issued=reply_issued,
                served=reply_issued,
                reply_deadline="",
                urg="",
                parent=doc.id,
                files=[rel],
                responded=True,
                viewed_by_ao=viewed_by_ao,
            )
            docs.append(reply)
            doc.responded = True

    # Orders recorded against the CARD (e.g. a "Download Closure Order" on a
    # closed appeal). They are separate documents the portal serves outside
    # the notice list, so add them as first-class docs — this is what makes
    # the Orders chip, the appeal link and the closed-case state work.
    for position, order in enumerate(meta.get("orders") or [], start=1):
        title = (order.get("title") or "Order").strip()
        files = list(order.get("files") or [])
        if not files:
            continue
        order_section = _section_from_text(title)
        # Inside an appeal proceeding a closure order IS the appellate order;
        # otherwise it is the assessment order that closes the case.
        kind = "appeal-order" if "appeal" in proc_name.lower() else "order"
        issued = _trailing_date(order.get("filename") or "")
        docs.append(Doc(
            id=_doc_id(case_id, kind, 900 + position),
            kind=kind,
            title=title,
            section=order_section,
            issued=_fmt_date(issued) if issued else "",
            served=_fmt_date(issued) if issued else "",
            reply_deadline="",
            urg="",
            files=files,
            responded=False,
        ))

    return docs


def _build_legacy_docs(case_id: str, proc_name: str, proc_dir: str) -> list[Doc]:
    """Infer documents from a legacy tree with no ``_meta.json``.

    Each file becomes one doc.  Notice files are ordered by folder number and
    file name; replies use their own running counter.  A reply is attached to
    the notice in the same ``NN`` folder when possible, else to the first
    notice.  ``responded`` is set on the parent notice.
    """

    files = _scan_proc_files(proc_dir)
    notice_files = [item for item in files if item["group"] == "notice"]
    response_files = [item for item in files if item["group"] == "response"]

    docs: list[Doc] = []
    folder_to_notice: dict[int, str] = {}
    first_notice_id = ""

    for counter, item in enumerate(notice_files, start=1):
        filename = item["name"]
        section = _section_from_filename(filename)
        issued_date = _trailing_date(filename)
        issued = _fmt_date(issued_date) if issued_date else ""
        is_order = "order" in filename.lower()
        kind = _classify_kind("", section, is_order, proc_name,
                              filename=filename)
        doc = Doc(
            id=_doc_id(case_id, kind, counter),
            kind=kind,
            title=_doc_title(kind, "", section, proc_name, True),
            section=section,
            issued=issued,
            served=issued,
            reply_deadline="",
            urg="",
            files=[item["rel"]],
        )
        if kind not in ("reply",) and not first_notice_id:
            first_notice_id = doc.id
        folder_to_notice.setdefault(item["folder_num"], doc.id)
        docs.append(doc)

    for counter, item in enumerate(response_files, start=1):
        filename = item["name"]
        section = _section_from_filename(filename)
        issued_date = _trailing_date(filename)
        issued = _fmt_date(issued_date) if issued_date else ""
        parent_id = folder_to_notice.get(item["folder_num"]) or first_notice_id
        parent_section = ""
        for doc in docs:
            if doc.id == parent_id:
                parent_section = doc.section
                break
        reply = Doc(
            id=_doc_id(case_id, "reply", counter),
            kind="reply",
            title=_doc_title("reply", "", section, proc_name, True,
                             parent_section=parent_section),
            section=section or parent_section,
            issued=issued,
            served=issued,
            reply_deadline="",
            urg="",
            parent=parent_id,
            files=[item["rel"]],
            responded=True,
        )
        docs.append(reply)
        for doc in docs:
            if doc.id == parent_id:
                doc.responded = True
                break

    return docs


def _link_docs(case: Case) -> None:
    """Cross-link penalty/remand docs to the case's order.

    A penalty is linked when exactly one plain order exists (otherwise the
    target would be ambiguous).  Remand docs link to the first order when one
    exists.  Both links are heuristic, so ``inferred`` records the fact and
    the case exposes ``inferred_links`` for the UI.
    """

    order_docs = [doc for doc in case.docs if doc.kind == "order"]
    for doc in case.docs:
        if doc.kind == "penalty" and len(order_docs) == 1:
            doc.triggered_by = order_docs[0].id
            doc.inferred["triggered_by"] = True
        elif doc.kind == "remand" and order_docs:
            doc.remands = order_docs[0].id
            doc.inferred["remands"] = True
    case.inferred_links = any(doc.inferred for doc in case.docs)


def _build_appeals(case: Case) -> None:
    """Create at most one inferred appeal for the case.

    Trigger: the case has an order anchor (a plain order, or an appeal-order
    when the proceeding itself is an appeal) AND either the proceeding /
    description mentions "appeal" or an appeal-order doc exists.

    An appeal proceeding whose folder already holds a response but no order
    yet still records a live appeal: the reply itself is the filing evidence
    and the appeal stays ``Pending`` until an appeal-order is recorded.

    ``filed`` is the earliest reply date that follows the order.  A reply
    dated before the order cannot be the appeal memo, so it is ignored.  When
    no such reply exists the appeal window is still open.

    Status is ``Resolved`` as soon as the case contains an ``appeal-order``
    document (the appellate / closure order), otherwise ``Pending`` when a
    filing exists, otherwise ``Window open``.
    """

    order_anchor = None
    for doc in case.docs:
        if doc.kind == "order":
            order_anchor = doc
            break
    if order_anchor is None:
        for doc in case.docs:
            if doc.kind == "appeal-order":
                order_anchor = doc
                break

    appeal_only = False
    if order_anchor is None:
        if ("appeal" in (case.proc_name or "").lower()
                and any(doc.kind == "reply" for doc in case.docs)):
            appeal_only = True
        else:
            return

    combined = " ".join(
        [case.proc_name] + [doc.title or "" for doc in case.docs]).lower()
    has_appeal_flavour = (
        appeal_only
        or "appeal" in (case.proc_name or "").lower()
        or "appeal" in combined
        or any(doc.kind == "appeal-order" for doc in case.docs)
    )
    if not has_appeal_flavour:
        return

    reply_dates: list[date] = []
    has_reply_doc = False
    if appeal_only:
        for doc in case.docs:
            if doc.kind != "reply":
                continue
            has_reply_doc = True
            reply_date = _doc_date(doc)
            if reply_date is not None:
                reply_dates.append(reply_date)
    else:
        order_date = _doc_date(order_anchor)
        if order_date is not None:
            for doc in case.docs:
                if doc.kind != "reply":
                    continue
                has_reply_doc = True
                reply_date = _doc_date(doc)
                if reply_date is not None and reply_date >= order_date:
                    reply_dates.append(reply_date)
    filed = _fmt_date(min(reply_dates)) if reply_dates else ""
    # A reply document proves something was filed even when the portal gave it
    # no parseable date — mark the "Appeal filed" step done in that case too,
    # otherwise the stepper showed "filed" as pending while a filing existed.
    filed_done = bool(filed) or has_reply_doc

    appeal_order_doc = next(
        (doc for doc in case.docs if doc.kind == "appeal-order"), None)
    grounds = ""
    if appeal_order_doc is not None and appeal_order_doc.title != case.proc_name:
        grounds = _clean_description(appeal_order_doc.title)

    forum = "ITAT" if "itat" in combined else "CIT(A)"
    if appeal_order_doc is not None:
        status = "Resolved"
    elif filed_done:
        status = "Pending"
    else:
        status = "Window open"
    steps = [
        AppealStep("Appeal filed", filed, filed_done),
        AppealStep("Defects, if any", "", False),
        AppealStep("Paper book", "", False),
        AppealStep("Hearing", "", False),
        AppealStep("Decision", "", False),
    ]
    case.appeals.append(Appeal(
        id=f"{case.id}#a1",
        forum=forum,
        against=order_anchor.id if order_anchor is not None else "",
        filed=filed,
        status=status,
        grounds=grounds,
        steps=steps,
    ))


def _assessee_index(assessees) -> dict[str, dict]:
    if not assessees:
        return {}
    if isinstance(assessees, dict):
        values = list(assessees.values())
    else:
        values = list(assessees)
    index: dict[str, dict] = {}
    for entry in values:
        if not isinstance(entry, dict):
            continue
        pan = (entry.get("pan") or "").strip().upper()
        if pan:
            index[pan] = entry
    return index


def _case_ays(year_name: str, proc_ay: str) -> list[str]:
    """Year-folder label plus a meaningful proceeding AY (deduped)."""

    ays = [_year_label(year_name)]
    ay = (proc_ay or "").strip()
    if ay and ay.lower() not in ("not available", "n/a", "na", "none"):
        if ay.lower() not in {item.lower() for item in ays}:
            ays.append(ay)
    return ays


_CLOSED_PROCEEDING_STATUSES = frozenset({
    "closed",
    "disposed",
    "completed",
    "concluded",
    # The portal closes/provides relief on a proceeding with these status
    # texts; treat both as a finished case (currently reported live).
    "closed by officer",
    "extinguished",
})


def _case_open_from_meta(meta: dict) -> bool:
    """Portal status -> open flag.

    A proceeding whose download recorded order documents (closure order /
    assessment order) is a CLOSED case even when the status text is blank —
    confirmed live: closed appeal cards carry a "Download Closure Order"
    button while showing no explicit status.

    Closed statuses ("Closed", "Closed by officer", "Extinguished", ...) are
    matched case- and whitespace-insensitively so free-form portal text does
    not leave an actually-closed case marked open."""

    if meta.get("closed") is True:
        return False
    if any(o.get("files") for o in (meta.get("orders") or [])):
        return False
    raw = ((meta.get("proceeding") or {}).get("status") or "").strip()
    if not raw:
        return True
    status = " ".join(raw.lower().split())
    return status not in _CLOSED_PROCEEDING_STATUSES


def build_cases(root: str, assessees: list[dict],
                case_state: dict | None = None,
                today: date | None = None) -> list[Case]:
    """Build one :class:`Case` per proceeding directory under ``root``.

    ``assessees`` is the vault list (keys ``pan``, ``name``, ``email``, ``cc``,
    ``group``, ...); matching is by upper-cased PAN.  ``case_state`` maps a
    case id to ``{"closed": bool}`` and overrides the portal-derived open
    flag, which is how a manual "close this case" action survives rescans.

    ``today`` is injected into the initial status/urgency derivation so tests
    remain deterministic; call :func:`derive_status` again after a date
    change if needed.
    """

    current = today or _today()
    by_pan = _assessee_index(assessees)
    state = case_state or {}
    cases: list[Case] = []

    for client_entry, year_name, eproc_root in _iter_eproc_roots(root):
        if "-" in client_entry:
            pan, folder_name = client_entry.split("-", 1)
        else:
            pan, folder_name = client_entry, client_entry
        pan = pan.strip().upper()
        folder_name = folder_name.strip()

        match = by_pan.get(pan) or {}
        assessee_name = (match.get("name") or folder_name or pan).strip()
        assessee = Assessee(
            name=assessee_name,
            pan=pan,
            email=(match.get("email") or "").strip(),
            phone=(match.get("phone") or match.get("mobile") or "").strip(),
            ward=(match.get("group") or "").strip(),
        )

        try:
            proc_names = sorted(os.listdir(eproc_root))
        except OSError:
            continue

        for entry in proc_names:
            proc_dir = os.path.join(eproc_root, entry)
            if not os.path.isdir(proc_dir):
                continue
            proc_num = _folder_number(entry)
            if proc_num == 0:
                proc_num = 10 ** 6
            folder_proc_name = _pretty_proc_name(entry)

            meta = _load_meta(proc_dir)
            meta_proc = meta.get("proceeding") or {}
            proc_name = (meta_proc.get("name") or "").strip() or folder_proc_name
            proc_ay = (meta_proc.get("ay") or "").strip()

            case_id = f"{pan}:{proc_num:02d}:{year_name}"
            override = state.get(case_id)

            notices = meta.get("notices") or []
            if meta and notices:
                docs = _build_meta_docs(case_id, proc_name, meta)
            else:
                docs = _build_legacy_docs(case_id, proc_name, proc_dir)

            case = Case(
                id=case_id,
                pan=pan,
                name=assessee_name,
                ays=_case_ays(year_name, proc_ay),
                case_open=True,
                remanded=False,
                assessee=assessee,
                docs=docs,
                appeals=[],
                proc_name=proc_name,
                year_label=_year_label(year_name),
                proc_dir=proc_dir,
                downloaded_at=(meta.get("downloaded_at") or "").strip(),
            )

            _link_docs(case)
            _build_appeals(case)

            # Derive statuses once with the case treated as open so an
            # unreplied notice is visible while deciding the final open flag.
            case.case_open = True
            for doc in case.docs:
                doc.status = derive_status(doc, case, today=current)

            has_order = any(doc.kind in _ORDER_KINDS for doc in case.docs)
            pending_appeal = any(
                appeal.status in ("Pending", "Window open")
                for appeal in case.appeals)
            open_notices = any(
                doc.kind in ("notice", "penalty")
                and doc.status in ("Open", "Overdue")
                for doc in case.docs)
            portal_closed = (not _case_open_from_meta(meta)) or has_order
            case_open = (not portal_closed) or pending_appeal or open_notices
            # A manual case_state entry is the final word.
            if isinstance(override, dict) and "closed" in override:
                case_open = not bool(override.get("closed"))
            case.case_open = case_open

            for doc in case.docs:
                doc.status = derive_status(doc, case, today=current)
            for doc in case.docs:
                doc.urg = _compute_urgency(doc, current)
            case.remanded = any(doc.kind == "remand" for doc in case.docs)

            cases.append(case)

    cases.sort(key=lambda case: (case.name.lower(), case.id))
    return cases


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------

def _compute_urgency(doc: Doc, today: date) -> str:
    """Urgency from the reply deadline.

    Overdue or due within 7 days -> High; within 30 days -> Medium; otherwise
    Low.  Replies, closed documents and documents without a deadline are Low.
    """

    deadline = _parse_date(doc.reply_deadline)
    if deadline is None:
        return "Low"
    if doc.responded or doc.status in ("Replied", "Closed", "Satisfied"):
        return "Low"
    remaining = _days_between(deadline, today)
    if remaining <= 7:
        return "High"
    if remaining <= 30:
        return "Medium"
    return "Low"


def derive_status(doc: Doc, case: Case, today: date | None = None) -> str:
    """Derive and return a document's workflow status.

    Rules, in evaluation order:

    * the whole case is closed -> ``Closed`` for every doc;
    * remand docs -> ``Remanded`` while the case is open;
    * any order / appeal-order / remand dated later than the doc closes it;
    * replies -> ``Replied`` (``Closed`` when a later order exists);
    * notices / penalties -> ``Replied``, else ``Overdue`` when the reply
      deadline has passed, else ``Open``;
    * orders -> ``Under appeal`` when an appeal exists against the order,
      else ``Appeal window`` for 30 days from issue, else
      ``Limitation expired``;
    * appeal-orders -> ``2nd appeal window`` for 60 days, else
      ``Limitation expired``;
    * anything else (or a dateless order) -> ``Open``.
    """

    current = today or _today()

    if not case.case_open:
        return "Closed"

    if doc.kind == "remand":
        return "Remanded"

    doc_date = _doc_date(doc)
    later_order = False
    if doc_date is not None:
        for other in case.docs:
            if other.id == doc.id or other.kind not in _ORDER_KINDS:
                continue
            other_date = _doc_date(other)
            if other_date is not None and other_date > doc_date:
                later_order = True
                break

    if doc.kind == "reply":
        return "Closed" if later_order else "Replied"

    if doc.kind in ("notice", "penalty"):
        if _is_reply(doc, case):
            return "Closed" if later_order else "Replied"
        if later_order:
            return "Closed"
        deadline = _parse_date(doc.reply_deadline)
        if deadline is not None and deadline < current:
            return "Overdue"
        return "Open"

    if doc.kind == "order":
        if _appeal_against(case, doc.id):
            return "Under appeal"
        if doc_date is None:
            return "Open"
        if _days_between(current, doc_date) <= 30:
            return "Appeal window"
        return "Limitation expired"

    if doc.kind == "appeal-order":
        if doc_date is None:
            return "Open"
        if _days_between(current, doc_date) <= 60:
            return "2nd appeal window"
        return "Limitation expired"

    return "Open"


# ---------------------------------------------------------------------------
# Limitation clocks
# ---------------------------------------------------------------------------

def _limitation_status(due: date, satisfied: bool, today: date) -> str:
    if satisfied:
        return "Satisfied"
    if due < today:
        return "Overdue"
    if _days_between(due, today) <= 7:
        return "Due soon"
    return "Open"


def _elapsed_pct(start: date | None, due: date, today: date) -> int:
    if start is None:
        return 0
    span = _days_between(due, start)
    if span <= 0:
        return 100 if today >= due else 0
    elapsed = _days_between(today, start)
    return int(max(0, min(100, round(elapsed * 100 / span))))


def _make_limitation(case: Case, suffix: str, title: str, provision: str,
                     start: date | None, due: date, source_doc: str,
                     satisfied: bool, today: date) -> Limitation:
    return Limitation(
        key=f"{case.id}:{suffix}",
        title=title,
        provision=provision,
        due_date=_fmt_date(due),
        status=_limitation_status(due, satisfied, today),
        elapsed_pct=_elapsed_pct(start, due, today),
        source_doc=source_doc,
    )


def compute_limitations(case: Case,
                        today: date | None = None) -> list[Limitation]:
    """Build the limitation / compliance clocks for a case.

    Provisions used (one line each):

    * ``Reply due`` - the portal's response due date for an open notice or
      penalty; satisfied when a reply exists.
    * ``s.246A r/w s.249(2)`` - first appeal to CIT(A) within 30 days of
      service of the order; satisfied when an appeal is recorded against it.
    * ``s.253(3)`` - second appeal to ITAT within 60 days of the CIT(A)
      order; satisfied when an appeal is recorded against that order.
    * ``s.260A(2)`` - High Court appeal within 120 days of the CIT(A) order.
    * ``s.154(7)`` - rectification within 4 years from the end of the FY in
      which the order was passed.
    * ``s.264(3)`` - revision within 1 year of the order.
    * ``s.275`` - penalty limitation: 6 months from the end of the month in
      which the order was passed.

    Rows are emitted per source document, so one case can have several first
    appeal / rectification rows when it contains several orders.  The
    ``status`` is ``Satisfied`` when the milestone is met, else ``Overdue``
    once past, ``Due soon`` within 7 days, otherwise ``Open``.
    """

    current = today or _today()
    rows: list[Limitation] = []

    for doc in case.docs:
        if doc.kind not in ("notice", "penalty"):
            continue
        deadline = _parse_date(doc.reply_deadline)
        if deadline is None:
            continue
        if doc.status not in ("", "Open", "Overdue"):
            continue
        replied = _is_reply(doc, case)
        start = _doc_date(doc)
        rows.append(_make_limitation(
            case, f"reply:{doc.id}", "Reply due", "Reply due", start,
            deadline, doc.id, replied, current))

    for doc in case.docs:
        if doc.kind != "order":
            continue
        start = _doc_date(doc)
        if start is None:
            continue
        satisfied = _appeal_against(case, doc.id)
        rows.append(_make_limitation(
            case, f"first-appeal:{doc.id}", "First appeal (CIT(A))",
            "s.246A r/w s.249(2)", start, _add_days(start, 30),
            doc.id, satisfied, current))
        rows.append(_make_limitation(
            case, f"rectification:{doc.id}", "Rectification", "s.154(7)",
            start, _add_years(_end_of_fy(start), 4), doc.id, False, current))
        rows.append(_make_limitation(
            case, f"revision:{doc.id}", "Revision", "s.264(3)",
            start, _add_years(start, 1), doc.id, False, current))
        rows.append(_make_limitation(
            case, f"penalty:{doc.id}", "Penalty (info)", "s.275",
            start, _add_months(_end_of_month(start), 6),
            doc.id, False, current))

    for doc in case.docs:
        if doc.kind != "appeal-order":
            continue
        start = _doc_date(doc)
        if start is None:
            continue
        satisfied = _appeal_against(case, doc.id)
        rows.append(_make_limitation(
            case, f"second-appeal:{doc.id}", "Second appeal (ITAT)",
            "s.253(3)", start, _add_days(start, 60),
            doc.id, satisfied, current))
        rows.append(_make_limitation(
            case, f"high-court:{doc.id}", "High Court", "s.260A(2)",
            start, _add_days(start, 120), doc.id, False, current))

    return rows


# ---------------------------------------------------------------------------
# KPIs, filtering and sorting
# ---------------------------------------------------------------------------

_UNREPLIED_STATUSES = ("Open", "Overdue")

_PENDING_DOC_STATUSES = ("Open", "Window open", "2nd appeal window",
                         "Under appeal")


def _is_unreplied(doc: Doc) -> bool:
    """True when a notice/penalty still needs a reply or has no closing order."""

    return (doc.kind in ("notice", "penalty")
            and doc.status in _UNREPLIED_STATUSES)


def _pending_appeal_against(case: Case, doc_id: str) -> bool:
    """True when a Pending / Window-open appeal is filed against ``doc_id``."""

    return any(appeal.against == doc_id
               and appeal.status in ("Pending", "Window open")
               for appeal in case.appeals)


def _deadline_days(doc: Doc, today: date) -> int | None:
    """Days from ``today`` to the reply deadline; ``None`` when undated."""

    deadline = _parse_date(doc.reply_deadline)
    if deadline is None:
        return None
    return _days_between(deadline, today)


def kpis(cases: list[Case], today: date | None = None) -> dict:
    """Aggregate dashboard counts.

    Keys (exact): ``cases``, ``open_cases``, ``fresh_notices``, ``due7``,
    ``due15``, ``under_appeal``, ``closed_by_order``, ``remanded``,
    ``overdue_limitations``.

    Definitions:

    * ``fresh_notices`` - unreplied notice/penalty docs (status ``Open`` or
      ``Overdue``) with no reply deadline or a deadline more than 15 days
      away.  Overdue documents never count as fresh.
    * ``due7`` / ``due15`` - unreplied notice/penalty docs whose reply
      deadline falls between today and 7 / 15 days from today inclusive.
    * ``under_appeal`` - OPEN cases only, having at least one appeal whose
      status is ``Pending`` (a filing exists and no appeal-order is recorded).
    * ``closed_by_order`` - documents closed by an order with no Pending /
      Window-open appeal against them.  Specifically:

      - notice/penalty docs whose status is ``Closed`` (an order passed
        after them), plus
      - ``appeal-order`` docs that are not the target of a Pending /
        Window-open appeal in the same case (no further appeal filed) and
        whose own status is not a pending state (``Open``,
        ``Window open``, ``2nd appeal window``, ``Under appeal``).

      The resolved appeal that produced an appeal-order does not exclude it;
      only a further pending appeal against it does.
    * ``remanded`` - cases containing a remand document.
    * ``overdue_limitations`` - limitation rows past their due date.

    ``awaiting_reply`` is kept as a legacy alias for the number of cases with
    at least one unreplied notice/penalty doc.
    """

    current = today or _today()
    open_cases = 0
    awaiting_reply = 0
    fresh_notices = 0
    due7 = 0
    due15 = 0
    under_appeal = 0
    closed_by_order = 0
    remanded = 0

    for case in cases:
        if case.case_open:
            open_cases += 1

        has_unreplied = False
        for doc in case.docs:
            if not _is_unreplied(doc):
                continue
            has_unreplied = True
            days = _deadline_days(doc, current)
            if doc.status != "Overdue" and (days is None or days > 15):
                fresh_notices += 1
            if days is not None and 0 <= days <= 7:
                due7 += 1
            if days is not None and 0 <= days <= 15:
                due15 += 1

        if has_unreplied:
            awaiting_reply += 1
        if case.case_open and any(
                appeal.status == "Pending" for appeal in case.appeals):
            under_appeal += 1
        if case.remanded:
            remanded += 1

        for doc in case.docs:
            if doc.kind in ("notice", "penalty") and doc.status == "Closed":
                if not _pending_appeal_against(case, doc.id):
                    closed_by_order += 1
            elif doc.kind == "appeal-order":
                if _pending_appeal_against(case, doc.id):
                    continue
                if doc.status in _PENDING_DOC_STATUSES:
                    continue
                closed_by_order += 1

    overdue = 0
    for case in cases:
        overdue += sum(1 for row in compute_limitations(case, today=current)
                       if row.status == "Overdue")

    return {
        "cases": len(cases),
        "open_cases": open_cases,
        "awaiting_reply": awaiting_reply,
        "fresh_notices": fresh_notices,
        "due7": due7,
        "due15": due15,
        "under_appeal": under_appeal,
        "closed_by_order": closed_by_order,
        "remanded": remanded,
        "overdue_limitations": overdue,
    }


def _doc_index(doc: Doc) -> int:
    """Trailing numeric index in a deterministic document id (0 if none)."""

    match = re.search(r"(\d+)$", doc.id or "")
    return int(match.group(1)) if match else 0


def _timeline_date_key(doc: Doc) -> date:
    return _doc_date(doc) or date.max


def timeline_docs(case: Case) -> list[Doc]:
    """Documents in true narrative order.

    1. notices/penalties in issue order (date, then index); each notice is
       immediately followed by ITS replies (``parent == notice.id``), oldest
       first (undated replies stay with their parent);
    2. orders, chronological;
    3. appeal-orders, chronological (the appeal order always comes last);
    4. remands, then anything unplaced (e.g. orphan replies).
    """

    position = {doc.id: index for index, doc in enumerate(case.docs)}
    placed: set[str] = set()
    out: list[Doc] = []

    replies_by_parent: dict[str, list[Doc]] = {}
    for doc in case.docs:
        if doc.kind == "reply" and doc.parent:
            replies_by_parent.setdefault(doc.parent, []).append(doc)

    notices = [doc for doc in case.docs
               if doc.kind in ("notice", "penalty")]
    notices.sort(key=lambda doc: (_timeline_date_key(doc), _doc_index(doc),
                                  position.get(doc.id, 0)))

    for notice in notices:
        out.append(notice)
        placed.add(notice.id)
        replies = replies_by_parent.get(notice.id, [])
        replies.sort(key=lambda doc: (_doc_date(doc) or date.min,
                                      position.get(doc.id, 0)))
        for reply in replies:
            if reply.id in placed:
                continue
            out.append(reply)
            placed.add(reply.id)

    for kind in ("order", "appeal-order", "remand"):
        group = [doc for doc in case.docs
                 if doc.kind == kind and doc.id not in placed]
        group.sort(key=lambda doc: (_timeline_date_key(doc), _doc_index(doc),
                                    position.get(doc.id, 0)))
        for doc in group:
            out.append(doc)
            placed.add(doc.id)

    for doc in case.docs:
        if doc.id not in placed:
            out.append(doc)
            placed.add(doc.id)

    return out


def filter_cases(cases: list[Case], status: str = "all", tag: str = "all",
                 section: str = "all",
                 urgency: str = "all") -> list[Case]:
    """Case-level filter used by the workspace sidebar.

    ``status``: ``all``, ``open`` or ``closed``.
    ``tag``: ``all``, ``Multi-year`` (len(ays) > 1), ``Remanded`` or
    ``Under appeal`` (a Pending appeal exists).
    ``section``: exact section present on any doc.
    ``urgency``: exact urgency present on any doc (High / Medium / Low).
    """

    status_key = (status or "all").strip().lower()
    tag_key = (tag or "all").strip().lower()
    section_key = (section or "all").strip()
    urgency_key = (urgency or "all").strip().lower()

    out: list[Case] = []
    for case in cases:
        if status_key == "open" and not case.case_open:
            continue
        if status_key == "closed" and case.case_open:
            continue

        if tag_key == "multi-year" and len(case.ays) <= 1:
            continue
        if tag_key == "remanded" and not case.remanded:
            continue
        if tag_key == "under appeal" and not any(
                appeal.status == "Pending" for appeal in case.appeals):
            continue

        if section_key.lower() != "all" and not any(
                (doc.section or "").lower() == section_key.lower()
                for doc in case.docs):
            continue
        if urgency_key != "all" and not any(
                (doc.urg or "").lower() == urgency_key
                for doc in case.docs):
            continue

        out.append(case)
    return out


def visible_docs(case: Case, section: str = "all",
                 urgency: str = "all") -> list[Doc]:
    """Notice-level filter for the document list of one case."""

    section_key = (section or "all").strip()
    urgency_key = (urgency or "all").strip().lower()
    out: list[Doc] = []
    for doc in case.docs:
        if section_key.lower() != "all" \
                and (doc.section or "").lower() != section_key.lower():
            continue
        if urgency_key != "all" and (doc.urg or "").lower() != urgency_key:
            continue
        out.append(doc)
    return out


_URGENCY_RANK = {"High": 0, "Medium": 1, "Low": 2, "": 9}


def _case_deadline_key(case: Case) -> date:
    dates: list[date] = []
    for doc in case.docs:
        if doc.status in ("Replied", "Closed", "Satisfied"):
            continue
        parsed = _parse_date(doc.reply_deadline)
        if parsed is not None:
            dates.append(parsed)
    return min(dates) if dates else date.max


def _case_urgency_key(case: Case) -> tuple[int, date]:
    ranks = [_URGENCY_RANK.get(doc.urg, 9) for doc in case.docs]
    rank = min(ranks) if ranks else 9
    return rank, _case_deadline_key(case)


def sort_cases(cases: list[Case], mode: str = "deadline") -> list[Case]:
    """Return a sorted copy.

    ``deadline`` - nearest open reply deadline first (undated last);
    ``urgency`` - High before Medium before Low, deadline as tie-break;
    ``assessee`` - client name; ``id`` - stable case id.
    """

    mode = (mode or "deadline").strip().lower()
    if mode == "assessee":
        return sorted(cases, key=lambda case: (case.name.lower(), case.id))
    if mode == "id":
        return sorted(cases, key=lambda case: case.id)
    if mode == "urgency":
        return sorted(cases, key=lambda case: (
            _case_urgency_key(case)[0], _case_urgency_key(case)[1],
            case.name.lower(), case.id))
    return sorted(cases, key=lambda case: (
        _case_deadline_key(case), _case_urgency_key(case)[0],
        case.name.lower(), case.id))


def _section_sort_key(section: str) -> tuple:
    match = re.match(r"^(\d+)(.*)$", section)
    if match:
        return (0, int(match.group(1)), match.group(2).lower())
    return (1, 0, section.lower())


def sections_in(cases: list[Case]) -> list[str]:
    """Distinct non-empty sections across all documents, naturally sorted."""

    seen: dict[str, str] = {}
    for case in cases:
        for doc in case.docs:
            section = (doc.section or "").strip()
            if section and section.lower() not in seen:
                seen[section.lower()] = section
    return sorted(seen.values(), key=_section_sort_key)
