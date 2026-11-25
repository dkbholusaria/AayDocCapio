"""core/litigation/adapters/gst.py — GST litigation adapter.

Maps GST notice/order records from :mod:`ui.gst_proceedings_model` into the
shared litigation records. Kept separate from the Income Tax adapter so the
core stays module-agnostic and GST can evolve its own fields.
"""

from __future__ import annotations

from core.litigation.model import (
    EVENT_REPLY,
    EVENT_STATE_CLOSED,
    EVENT_STATE_IGNORED,
    EVENT_STATE_OPEN,
    EVENT_STATE_REPLIED,
    MODULE_GST,
    UnifiedCase,
    UnifiedEvent,
    case_uid,
    event_uid,
)


def _model():
    import ui.gst_proceedings_model as model
    return model


class GstAdapter:
    key = MODULE_GST
    label = "GST"

    def __init__(self):
        self._case_cache: dict = {}

    def collect_cases(self, root, assessees, store, today=None):
        model = _model()
        cases = model.build_cases(root, assessees, today)
        self._case_cache = {case.id: case for case in cases}
        matter_map = store.case_matter_map()

        out = []
        for case in cases:
            uid = case_uid(MODULE_GST, case.id)
            out.append(UnifiedCase(
                uid=uid,
                module=MODULE_GST,
                native_id=case.id,
                client_pan=case.client_key,
                client_name=case.client_name,
                title=case.title,
                assessment_year="",
                status=case.status,
                urgency=_case_urgency(case, today),
                case_type="assessment" if case.is_order else "notice",
                matter_id=matter_map.get(uid, ""),
                closed=case.status == "Closed",
                replied=case.responded,
                ignored=store.case_ignored(uid),
            ))
        return out

    def collect_events(self, cases, store, today=None):
        model = _model()
        current = today or model._today()
        out = []
        for uc in cases:
            if uc.module != MODULE_GST:
                continue
            case = self._case_cache.get(uc.native_id)
            if case is None:
                continue
            due = model._parse_date(case.due)
            if due is None:
                continue
            if uc.closed:
                state = EVENT_STATE_CLOSED
            elif uc.replied:
                state = EVENT_STATE_REPLIED
            elif uc.ignored:
                state = EVENT_STATE_IGNORED
            else:
                state = EVENT_STATE_OPEN
            overdue = due < current
            soon = not overdue and 0 <= (due - current).days <= 7
            out.append(UnifiedEvent(
                eid=event_uid(uc.uid, EVENT_REPLY, case.id),
                case_uid=uc.uid,
                module=MODULE_GST,
                kind=EVENT_REPLY,
                title=f"Reply due — {case.title}",
                date=due,
                state=state,
                urgency="High" if (overdue or soon) else "Medium",
                native_doc_id=case.id,
            ))
        return out


def _case_urgency(case, today) -> str:
    model = _model()
    due = model._parse_date(case.due)
    current = today or model._today()
    if due is not None and due < current and case.status != "Closed":
        return "High"
    if due is not None and 0 <= (due - current).days <= 7:
        return "Medium"
    return "Low"


__all__ = ["GstAdapter"]
