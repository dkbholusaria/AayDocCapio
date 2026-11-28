"""core/litigation/store.py — F-26 vault-backed litigation store.

Single source of truth for every mutable litigation action:

* case closed / ignored overrides,
* per-document replied / ignored overrides,
* manual personal-hearing dates,
* matters and their fee / billing / reimbursement entries.

Everything is persisted under one vault settings namespace (``"litigation"``)
via ``VaultManager.get_setting`` / ``update_setting`` — the same proven,
migration-safe pattern used by ``get/save_eproc_autofetch_config``. Case
close is additionally mirrored into the legacy ``eproc_case_state`` key so the
existing Income Tax e-Proceedings workspace reflects actions taken here.

Storage shape (schema 1)::

    {
      "schema": 1,
      "cases":   {"<case_uid>": {"closed": bool, "ignored": bool}},
      "docs":    {"<doc_uid>":  {"replied": bool, "ignored": bool}},
      "hearings": {"<case_uid>": ["DD-Mon-YYYY", ...]},
      "matters": [ {Matter...} ],
      "fee":     [ {FeeEntry...} ],
    }
"""

from __future__ import annotations

import uuid

from core.litigation.model import (
    FEE_KINDS,
    FEE_STATUSES,
    FeeEntry,
    Matter,
)

SETTINGS_KEY = "litigation"
_EPROC_CASE_STATE_KEY = "eproc_case_state"
_SCHEMA = 1

MODULE_IT = "it"


def _empty() -> dict:
    return {
        "schema": _SCHEMA,
        "cases": {},
        "docs": {},
        "hearings": {},
        "matters": [],
        "fee": [],
    }


def _normalise(raw) -> dict:
    """Fill defaults and coerce shape so callers never see KeyErrors."""
    data = _empty()
    if not isinstance(raw, dict):
        return data
    data["schema"] = _SCHEMA
    for key in ("cases", "docs", "hearings"):
        val = raw.get(key)
        if isinstance(val, dict):
            data[key] = val
    if isinstance(raw.get("matters"), list):
        data["matters"] = [m for m in raw["matters"] if isinstance(m, dict)]
    if isinstance(raw.get("fee"), list):
        data["fee"] = [f for f in raw["fee"] if isinstance(f, dict)]
    return data


def _native_from_uid(case_uid_value: str) -> str:
    module, _, native = case_uid_value.partition(":")
    return native if module == MODULE_IT else case_uid_value


class LitigationStore:
    """Reads/writes the litigation namespace over a ``VaultManager``."""

    def __init__(self, vault):
        self._vault = vault

    # -- whole-document --------------------------------------------------

    def get(self) -> dict:
        return _normalise(self._vault.get_setting(SETTINGS_KEY, {}))

    def save(self, data: dict) -> dict:
        clean = _normalise(data)
        self._vault.update_setting(SETTINGS_KEY, clean)
        return clean

    # -- case overrides --------------------------------------------------

    def case_closed(self, case_uid_value: str) -> bool:
        entry = self.get()["cases"].get(case_uid_value) or {}
        return bool(entry.get("closed"))

    def case_ignored(self, case_uid_value: str) -> bool:
        entry = self.get()["cases"].get(case_uid_value) or {}
        return bool(entry.get("ignored"))

    def set_case_closed(self, case_uid_value: str, closed: bool) -> None:
        data = self.get()
        entry = data["cases"].setdefault(case_uid_value, {})
        entry["closed"] = bool(closed)
        self.save(data)
        if case_uid_value.startswith(f"{MODULE_IT}:"):
            native = _native_from_uid(case_uid_value)
            state = self._vault.get_setting(_EPROC_CASE_STATE_KEY, {}) or {}
            state.setdefault(native, {})["closed"] = bool(closed)
            self._vault.update_setting(_EPROC_CASE_STATE_KEY, state)

    def set_case_ignored(self, case_uid_value: str, ignored: bool) -> None:
        data = self.get()
        entry = data["cases"].setdefault(case_uid_value, {})
        entry["ignored"] = bool(ignored)
        self.save(data)

    def case_close_overrides(self) -> dict:
        return {
            uid: bool(entry.get("closed"))
            for uid, entry in self.get()["cases"].items()
            if "closed" in entry
        }

    # -- document overrides ---------------------------------------------

    def doc_replied(self, doc_uid: str) -> bool:
        entry = self.get()["docs"].get(doc_uid) or {}
        return bool(entry.get("replied"))

    def set_doc_replied(self, doc_uid: str, replied: bool) -> None:
        data = self.get()
        data["docs"].setdefault(doc_uid, {})["replied"] = bool(replied)
        self.save(data)

    def set_doc_ignored(self, doc_uid: str, ignored: bool) -> None:
        data = self.get()
        data["docs"].setdefault(doc_uid, {})["ignored"] = bool(ignored)
        self.save(data)

    def doc_overrides(self) -> dict:
        return {
            uid: {
                "replied": bool(entry.get("replied")),
                "ignored": bool(entry.get("ignored")),
            }
            for uid, entry in self.get()["docs"].items()
        }

    # -- manual hearing dates -------------------------------------------

    def hearings(self, case_uid_value: str) -> list:
        return list(self.get()["hearings"].get(case_uid_value) or [])

    def add_hearing(self, case_uid_value: str, date_label: str) -> None:
        date_label = (date_label or "").strip()
        if not date_label:
            return
        data = self.get()
        bucket = data["hearings"].setdefault(case_uid_value, [])
        if date_label not in bucket:
            bucket.append(date_label)
        self.save(data)

    def remove_hearing(self, case_uid_value: str, date_label: str) -> None:
        data = self.get()
        bucket = data["hearings"].get(case_uid_value) or []
        data["hearings"][case_uid_value] = [d for d in bucket if d != date_label]
        self.save(data)

    def all_hearings(self) -> dict:
        return dict(self.get()["hearings"])

    # -- matters ---------------------------------------------------------

    def matters(self) -> list:
        return [_matter_from(d) for d in self.get()["matters"]]

    def matter(self, matter_id: str):
        for matter in self.matters():
            if matter.id == matter_id:
                return matter
        return None

    def add_matter(self, client_pan: str, client_name: str, title: str,
                   description: str = "", created: str = "") -> Matter:
        data = self.get()
        matter = Matter(
            id=f"m_{uuid.uuid4().hex[:10]}",
            client_pan=(client_pan or "").strip().upper(),
            client_name=(client_name or "").strip(),
            title=(title or "").strip() or "Untitled matter",
            description=description or "",
            created=created or "",
        )
        data["matters"].append({
            "id": matter.id,
            "client_pan": matter.client_pan,
            "client_name": matter.client_name,
            "title": matter.title,
            "description": matter.description,
            "created": matter.created,
        })
        self.save(data)
        return matter

    def update_matter(self, matter_id: str, **fields) -> bool:
        data = self.get()
        for raw in data["matters"]:
            if raw.get("id") == matter_id:
                for key in ("client_pan", "client_name", "title",
                            "description", "created"):
                    if key in fields:
                        value = fields[key]
                        raw[key] = value.strip().upper() if key == "client_pan" else value
                self.save(data)
                return True
        return False

    def delete_matter(self, matter_id: str) -> None:
        data = self.get()
        data["matters"] = [m for m in data["matters"] if m.get("id") != matter_id]
        data["fee"] = [f for f in data["fee"] if f.get("matter_id") != matter_id]
        for entry in data["cases"].values():
            if entry.get("matter_id") == matter_id:
                entry.pop("matter_id", None)
        self.save(data)

    # -- case <-> matter links ------------------------------------------

    def case_matter_id(self, case_uid_value: str) -> str:
        entry = self.get()["cases"].get(case_uid_value) or {}
        return entry.get("matter_id", "") or ""

    def link_case(self, case_uid_value: str, matter_id: str) -> None:
        data = self.get()
        if matter_id:
            data["cases"].setdefault(case_uid_value, {})["matter_id"] = matter_id
        else:
            entry = data["cases"].get(case_uid_value)
            if entry is not None:
                entry.pop("matter_id", None)
        self.save(data)

    def case_matter_map(self) -> dict:
        return {
            uid: entry.get("matter_id", "")
            for uid, entry in self.get()["cases"].items()
            if entry.get("matter_id")
        }

    # -- fees / billing / reimbursements ---------------------------------

    def fees(self, matter_id: str = "") -> list:
        entries = [_fee_from(d) for d in self.get()["fee"]]
        if matter_id:
            return [e for e in entries if e.matter_id == matter_id]
        return entries

    def add_fee(self, matter_id: str, kind: str, label: str, amount: float,
                status: str, date: str = "", note: str = "") -> FeeEntry:
        kind = kind if kind in FEE_KINDS else "fee"
        status = status if status in FEE_STATUSES else "outstanding"
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0
        data = self.get()
        entry = FeeEntry(
            id=f"f_{uuid.uuid4().hex[:10]}",
            matter_id=matter_id,
            kind=kind,
            label=(label or "").strip() or FEE_KINDS[0],
            amount=amount,
            status=status,
            date=date or "",
            note=note or "",
        )
        data["fee"].append({
            "id": entry.id,
            "matter_id": entry.matter_id,
            "kind": entry.kind,
            "label": entry.label,
            "amount": entry.amount,
            "status": entry.status,
            "date": entry.date,
            "note": entry.note,
        })
        self.save(data)
        return entry

    def update_fee(self, fee_id: str, **fields) -> bool:
        data = self.get()
        for raw in data["fee"]:
            if raw.get("id") == fee_id:
                for key in ("kind", "label", "amount", "status", "date", "note"):
                    if key in fields:
                        raw[key] = fields[key]
                if raw.get("kind") not in FEE_KINDS:
                    raw["kind"] = "fee"
                if raw.get("status") not in FEE_STATUSES:
                    raw["status"] = "outstanding"
                try:
                    raw["amount"] = float(raw.get("amount", 0.0))
                except (TypeError, ValueError):
                    raw["amount"] = 0.0
                self.save(data)
                return True
        return False

    def delete_fee(self, fee_id: str) -> None:
        data = self.get()
        data["fee"] = [f for f in data["fee"] if f.get("id") != fee_id]
        self.save(data)


def _matter_from(raw: dict) -> Matter:
    return Matter(
        id=raw.get("id", ""),
        client_pan=raw.get("client_pan", ""),
        client_name=raw.get("client_name", ""),
        title=raw.get("title", ""),
        description=raw.get("description", ""),
        created=raw.get("created", ""),
    )


def _fee_from(raw: dict) -> FeeEntry:
    try:
        amount = float(raw.get("amount", 0.0))
    except (TypeError, ValueError):
        amount = 0.0
    return FeeEntry(
        id=raw.get("id", ""),
        matter_id=raw.get("matter_id", ""),
        kind=raw.get("kind", "fee"),
        label=raw.get("label", ""),
        amount=amount,
        status=raw.get("status", "outstanding"),
        date=raw.get("date", ""),
        note=raw.get("note", ""),
    )
