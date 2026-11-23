"""core/litigation/model.py — F-26 unified litigation data model.

Module-agnostic records shared by every tax module's litigation adapter and
by the Litigation hub UI. Nothing here imports PyQt or any module-specific
code, so the core stays a pure, testable domain layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MODULE_IT = "it"
MODULE_GST = "gst"
MODULE_TDS = "tds"
MODULE_MCA = "mca"

MODULE_LABELS = {
    MODULE_IT: "Income Tax",
    MODULE_GST: "GST",
    MODULE_TDS: "TDS",
    MODULE_MCA: "MCA",
}

CASE_TYPES = ("notice", "assessment", "appeal")

EVENT_REPLY = "reply_due"
EVENT_HEARING = "hearing"
EVENT_LIMITATION = "limitation"

EVENT_KIND_LABELS = {
    EVENT_REPLY: "Reply due",
    EVENT_HEARING: "Hearing",
    EVENT_LIMITATION: "Limitation",
}

EVENT_STATE_OPEN = "open"
EVENT_STATE_REPLIED = "replied"
EVENT_STATE_IGNORED = "ignored"
EVENT_STATE_CLOSED = "closed"
EVENT_STATE_SATISFIED = "satisfied"

_HIDDEN_EVENT_STATES = frozenset({
    EVENT_STATE_REPLIED,
    EVENT_STATE_IGNORED,
    EVENT_STATE_CLOSED,
    EVENT_STATE_SATISFIED,
})

FEE_KINDS = ("fee", "billing", "reimbursement")
FEE_KIND_LABELS = {
    "fee": "Fee",
    "billing": "Billing",
    "reimbursement": "Reimbursement",
}

FEE_STATUSES = ("agreed", "billed", "received", "outstanding", "reimbursed")
FEE_STATUS_LABELS = {
    "agreed": "Agreed",
    "billed": "Billed",
    "received": "Received",
    "outstanding": "Outstanding",
    "reimbursed": "Reimbursed",
}


@dataclass(frozen=True)
class UnifiedCase:
    """One case/proceeding, normalized from any module."""

    uid: str
    module: str
    native_id: str
    client_pan: str
    client_name: str
    title: str
    assessment_year: str
    status: str
    urgency: str
    case_type: str
    matter_id: str = ""
    closed: bool = False
    replied: bool = False
    ignored: bool = False

    @property
    def module_label(self) -> str:
        return MODULE_LABELS.get(self.module, self.module.upper())

    @property
    def is_open(self) -> bool:
        return not self.closed and self.status not in ("Closed",)


@dataclass(frozen=True)
class UnifiedEvent:
    """A dated milestone on a case (reply due / hearing / limitation)."""

    eid: str
    case_uid: str
    module: str
    kind: str
    title: str
    date: object
    state: str
    urgency: str
    native_doc_id: str = ""

    @property
    def kind_label(self) -> str:
        return EVENT_KIND_LABELS.get(self.kind, self.kind)

    @property
    def visible(self) -> bool:
        return self.state not in _HIDDEN_EVENT_STATES


@dataclass
class FeeEntry:
    """One fee / billing / reimbursement line on a matter."""

    id: str
    matter_id: str
    kind: str
    label: str
    amount: float
    status: str
    date: str = ""
    note: str = ""


@dataclass
class Matter:
    """A client matter that notices/assessments/appeals can be linked to."""

    id: str
    client_pan: str
    client_name: str
    title: str
    description: str = ""
    created: str = ""
    fees: list = field(default_factory=list)


def case_uid(module: str, native_id: str) -> str:
    """Stable uid for a case across modules."""
    return f"{module}:{native_id}"


def event_uid(case_uid_value: str, kind: str, native_key: str) -> str:
    """Stable uid for an event (so ignore state survives rescans)."""
    return f"{case_uid_value}|{kind}|{native_key}"


def matter_totals(fees) -> dict:
    """Aggregate fee entries into per-kind and per-status totals."""
    totals = {
        "fee": 0.0, "billing": 0.0, "reimbursement": 0.0,
        "agreed": 0.0, "billed": 0.0, "received": 0.0,
        "outstanding": 0.0, "reimbursed": 0.0,
    }
    for entry in fees:
        try:
            amount = float(entry.amount)
        except (TypeError, ValueError):
            continue
        if entry.kind in totals:
            totals[entry.kind] += amount
        if entry.status in totals:
            totals[entry.status] += amount
    return totals
