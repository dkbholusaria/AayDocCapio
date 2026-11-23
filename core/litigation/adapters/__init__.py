"""core/litigation/adapters — F-26 module adapter registry."""

from __future__ import annotations

from core.litigation.adapters.income_tax import IncomeTaxAdapter

ADAPTERS = [
    IncomeTaxAdapter(),
]

_BY_KEY = {adapter.key: adapter for adapter in ADAPTERS}


def adapter_for(module: str):
    return _BY_KEY.get(module)


def collect_all(root, assessees, store, today=None):
    """Run every adapter and return ``(cases, events)`` across all modules."""
    all_cases = []
    for adapter in ADAPTERS:
        all_cases.extend(adapter.collect_cases(root, assessees, store, today))

    all_events = []
    for adapter in ADAPTERS:
        all_events.extend(adapter.collect_events(all_cases, store, today))

    from dataclasses import replace
    doc_overrides = store.doc_overrides()
    overridden = []
    for event in all_events:
        ov = doc_overrides.get(event.eid)
        if ov and ov.get("ignored") and event.state != "closed":
            event = replace(event, state="ignored")
        overridden.append(event)
    overridden.sort(key=lambda e: (e.date, e.case_uid, e.kind))
    return all_cases, overridden


__all__ = ["ADAPTERS", "adapter_for", "collect_all"]
