"""core/litigation/adapters/income_tax.py — F-26 Income Tax adapter.

Maps the Income Tax e-Proceedings model (``ui.eproceedings_model``) into the
shared litigation records. This is the only place the litigation core touches
Income-Tax-specific code, keeping the core module-agnostic.
"""

from __future__ import annotations

from core.litigation.model import (
    EVENT_HEARING,
    EVENT_LIMITATION,
    EVENT_REPLY,
    EVENT_STATE_CLOSED,
    EVENT_STATE_IGNORED,
    EVENT_STATE_OPEN,
    EVENT_STATE_REPLIED,
    EVENT_STATE_SATISFIED,
    MODULE_IT,
    UnifiedCase,
    UnifiedEvent,
    case_uid,
    event_uid,
)

_EPROC_CASE_STATE_KEY = "eproc_case_state"


def _model():
    """Import the Income Tax model lazily (kept out of the core import graph)."""
    import ui.eproceedings_model as model
    return model


def _case_type(case) -> str:
    docs = getattr(case, "docs", []) or []
    if any(d.kind == "appeal-order" for d in docs):
        return "appeal"
    if any(d.kind == "order" for d in docs):
        return "assessment"
    return "notice"


def _case_status(case) -> str:
    if not case.case_open:
        return "Closed"
    docs = getattr(case, "docs", []) or []
    statuses = {d.status for d in docs}
    if "Overdue" in statuses:
        return "Overdue"
    if "Under appeal" in statuses or "Appeal window" in statuses:
        return "Under appeal"
    if "Remanded" in statuses:
        return "Remanded"
    if "Open" in statuses:
        return "Open"
    if "Replied" in statuses:
        return "Replied"
    if "Closed" in statuses and statuses <= {"Closed", ""}:
        return "Closed"
    return next((d.status for d in docs if d.status), "Open")


def _case_urgency(case) -> str:
    if not case.case_open:
        return "Low"
    rank = {"High": 3, "Medium": 2, "Low": 1, "": 0}
    best = "Low"
    for doc in case.docs or []:
        if rank.get(doc.urg, 0) > rank.get(best, 0):
            best = doc.urg or best
    return best


def _case_replied(case) -> bool:
    docs = case.docs or []
    if not docs:
        return False
    return all(d.kind == "reply" or getattr(d, "responded", False) for d in docs)


def _doc_state(doc, override, case_closed) -> str:
    if case_closed:
        return EVENT_STATE_CLOSED
    if override and override.get("ignored"):
        return EVENT_STATE_IGNORED
    if override and override.get("replied"):
        return EVENT_STATE_REPLIED
    status = getattr(doc, "status", "")
    if status == "Closed":
        return EVENT_STATE_CLOSED
    if status == "Replied":
        return EVENT_STATE_REPLIED
    if status == "Ignored":
        return EVENT_STATE_IGNORED
    return EVENT_STATE_OPEN


class IncomeTaxAdapter:
    key = MODULE_IT
    label = "Income Tax"

    def __init__(self):
        # native case id -> model Case, primed on load so collect_events does
        # not rescan the disk.
        self._case_cache: dict = {}

    # -- cases -----------------------------------------------------------

    def collect_cases(self, root, assessees, store, today=None):
        model = _model()
        # Merge litigation case-close overrides with the IT workspace's own
        # legacy close state, litigation taking precedence.
        case_state = {}
        legacy = store._vault.get_setting(_EPROC_CASE_STATE_KEY, {}) or {}
        for native, entry in legacy.items():
            case_state[native] = dict(entry) if isinstance(entry, dict) else {}
        for uid, closed in store.case_close_overrides().items():
            if uid.startswith(f"{MODULE_IT}:"):
                native = uid.split(":", 1)[1]
                case_state.setdefault(native, {})["closed"] = closed

        cases = model.build_cases(root, assessees, case_state, today,
                                  doc_overrides=store.doc_overrides())
        self._case_cache = {c.id: c for c in cases}

        matter_map = store.case_matter_map()
        out = []
        for case in cases:
            uid = case_uid(MODULE_IT, case.id)
            out.append(UnifiedCase(
                uid=uid,
                module=MODULE_IT,
                native_id=case.id,
                client_pan=case.pan,
                client_name=case.name,
                title=case.proc_name or case.id,
                assessment_year=", ".join(case.ays) if case.ays else "",
                status=_case_status(case),
                urgency=_case_urgency(case),
                case_type=_case_type(case),
                matter_id=matter_map.get(uid, ""),
                closed=not case.case_open,
                replied=_case_replied(case),
                ignored=store.case_ignored(uid),
            ))
        return out

    # -- events ----------------------------------------------------------

    def collect_events(self, cases, store, today=None):
        model = _model()
        current = today or model._today()
        doc_overrides = store.doc_overrides()
        hearings_map = store.all_hearings()

        events = []
        for uc in cases:
            if uc.module != MODULE_IT:
                continue
            model_case = self._case_cache.get(uc.native_id)
            if model_case is None:
                continue
            events.extend(self._case_events(
                uc, model_case, doc_overrides, current,
                hearings_map.get(uc.uid, [])))
        return events

    def _case_events(self, uc, case, doc_overrides, current, manual_hearings):
        model = _model()
        closed = uc.closed
        events = []

        for doc in case.docs:
            if doc.kind not in ("notice", "penalty"):
                continue
            due = model._parse_date(doc.reply_deadline)
            if due is None:
                continue
            uid = (doc.inferred or {}).get("override_uid") or f"it:{doc.id}"
            state = _doc_state(doc, doc_overrides.get(uid), closed)
            events.append(UnifiedEvent(
                eid=event_uid(uc.uid, EVENT_REPLY, doc.id),
                case_uid=uc.uid,
                module=MODULE_IT,
                kind=EVENT_REPLY,
                title=f"Reply due — {doc.title or doc.section or 'Notice'}",
                date=due,
                state=state,
                urgency=getattr(doc, "urg", "") or "Low",
                native_doc_id=doc.id,
            ))

        hearing_pairs = []
        for appeal in case.appeals:
            for step in appeal.steps:
                if step.label.lower().startswith("hearing") and step.date:
                    parsed = model._parse_date(step.date)
                    if parsed is not None:
                        hearing_pairs.append((parsed, appeal.id))
        for label in manual_hearings:
            parsed = model._parse_date(label)
            if parsed is not None:
                hearing_pairs.append((parsed, "manual"))
        for parsed, key in hearing_pairs:
            open_soon = not closed and 0 <= (parsed - current).days <= 7
            events.append(UnifiedEvent(
                eid=event_uid(uc.uid, EVENT_HEARING,
                              f"{key}:{parsed.isoformat()}"),
                case_uid=uc.uid,
                module=MODULE_IT,
                kind=EVENT_HEARING,
                title="Personal hearing",
                date=parsed,
                state=EVENT_STATE_CLOSED if closed else EVENT_STATE_OPEN,
                urgency="High" if open_soon else "Medium",
            ))

        for lim in model.compute_limitations(case, current):
            due = model._parse_date(lim.due_date)
            if due is None:
                continue
            if lim.status == "Satisfied":
                state = EVENT_STATE_SATISFIED
            elif closed:
                state = EVENT_STATE_CLOSED
            else:
                state = EVENT_STATE_OPEN
            events.append(UnifiedEvent(
                eid=event_uid(uc.uid, EVENT_LIMITATION, lim.key),
                case_uid=uc.uid,
                module=MODULE_IT,
                kind=EVENT_LIMITATION,
                title=lim.title,
                date=due,
                state=state,
                urgency="High" if lim.status == "Overdue" else "Medium",
                native_doc_id=lim.source_doc,
            ))
        return events


__all__ = ["IncomeTaxAdapter"]
