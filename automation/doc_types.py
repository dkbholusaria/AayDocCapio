"""
automation/doc_types.py
========================
Single source of truth for "what filename pattern maps to which document
type" — consumed by automation/emailer.py (collect_attachments, _doc_list)
and ui/dialogs.py (MailDocsDialog._keep/_doc_label) so the two files can't
drift out of agreement, which is exactly what caused the Form 168 emailer
bugs (fixed in e1c574e, 608debe) twice already.

Order matters: entries are checked in the order listed, first match wins —
this preserves suffix-specific checks (e.g. "-itd.xlsx") needing to be
tested before a more generic fallback (".xlsx") for the same doc family.
"""

DOC_TYPES = [
    {
        "key": "26as_pdf", "template_key": "26as_pdf",
        "label": "Form 26AS — Annual Tax Statement (PDF)", "short_label": "26AS PDF",
        "subfolder": "26AS", "nested": False, "glob_suffix": "-26AS-*.pdf",
        "match": lambda n: "-26AS-" in n and n.endswith(".PDF"),
        "emailable": True,
    },
    {
        "key": "26as_xlsx", "template_key": "26as_xlsx",
        "label": "Form 26AS — Annual Tax Statement (Excel)", "short_label": "26AS Excel",
        "subfolder": "26AS", "nested": False, "glob_suffix": "-26AS-*.xlsx",
        "match": lambda n: "-26AS-" in n and n.endswith(".XLSX"),
        "emailable": True,
    },
    # Form 168 — from TY 2026-27 onward, Form 26AS's replacement under the
    # 2025 Income-tax Act — downloads under its own "168" subfolder (see
    # utils.migrate_168_subfolder_name()), not "26AS".
    {
        "key": "168_itd_xlsx", "template_key": "168_xlsx",
        "label": "Form 168 — ITD Native Excel", "short_label": "168 ITD Excel",
        "subfolder": "168", "nested": False, "glob_suffix": "-168-*.xlsx",
        "match": lambda n: "-168-" in n and n.endswith("-ITD.XLSX"),
        "emailable": True,
    },
    {
        "key": "168_pdf", "template_key": "168_pdf",
        "label": "Form 168 — Annual Tax Statement (PDF)", "short_label": "168 PDF",
        "subfolder": "168", "nested": False, "glob_suffix": "-168-*.pdf",
        "match": lambda n: "-168-" in n and n.endswith(".PDF"),
        "emailable": True,
    },
    {
        "key": "168_xlsx", "template_key": "168_xlsx",
        "label": "Form 168 — Annual Tax Statement (Excel)", "short_label": "168 Excel",
        "subfolder": "168", "nested": False, "glob_suffix": "-168-*.xlsx",
        "match": lambda n: "-168-" in n and n.endswith(".XLSX"),
        "emailable": True,
    },
    {
        "key": "ais_pdf", "template_key": "ais_pdf",
        "label": "AIS — Annual Information Statement (PDF)", "short_label": "AIS PDF",
        "subfolder": "AIS-TIS", "nested": False, "glob_suffix": "-AIS-*.pdf",
        "match": lambda n: "-AIS-" in n and n.endswith(".PDF"),
        "emailable": True,
    },
    {
        "key": "ais_xlsx", "template_key": "ais_xlsx",
        "label": "AIS — Annual Information Statement (Excel)", "short_label": "AIS Excel",
        "subfolder": "AIS-TIS", "nested": False, "glob_suffix": "-AIS-*.xlsx",
        "match": lambda n: "-AIS-" in n and n.endswith(".XLSX"),
        "emailable": True,
    },
    {
        "key": "tis_pdf", "template_key": "tis_pdf",
        "label": "TIS — Taxpayer Information Summary", "short_label": "TIS",
        "subfolder": "AIS-TIS", "nested": False, "glob_suffix": "-TIS-*.pdf",
        "match": lambda n: "-TIS-" in n and n.endswith(".PDF"),
        "emailable": True,
    },
    {
        "key": "itr_form", "template_key": "itr_form",
        "label": "ITR Form", "short_label": "ITR Form",
        "subfolder": "ITR Returns", "nested": True, "glob_suffix": "-ITR-*-Form.pdf",
        "match": lambda n: "-ITR-" in n and n.endswith("-FORM.PDF"),
        "emailable": True,
    },
    {
        "key": "itr_receipt", "template_key": "itr_receipt",
        "label": "ITR Receipt", "short_label": "ITR Receipt",
        "subfolder": "ITR Returns", "nested": True, "glob_suffix": "-ITR-*-Receipt.pdf",
        "match": lambda n: "-ITR-" in n and n.endswith("-RECEIPT.PDF"),
        "emailable": True,
    },
    {
        "key": "itr_v", "template_key": "itr_v",
        "label": "ITR-V (Verification Form — return not yet e-verified)", "short_label": "ITR-V",
        "subfolder": "ITR Returns", "nested": True, "glob_suffix": "-ITR-*-ITR-V.pdf",
        "match": lambda n: "-ITR-" in n and n.endswith("-ITR-V.PDF"),
        "emailable": True,
    },
    {
        "key": "itr_json", "template_key": None,
        "label": "ITR JSON", "short_label": "ITR JSON",
        "subfolder": "ITR Returns", "nested": True, "glob_suffix": "-ITR-*.json",
        "match": lambda n: "-ITR-" in n and n.endswith(".JSON"),
        "emailable": False,  # download-only, never emailed
    },
    {
        "key": "itr_status_xlsx", "template_key": None,
        "label": "ITR Status Summary (Excel)", "short_label": "ITR Status",
        "subfolder": "ITR Returns", "nested": False, "glob_suffix": "-ITR-Status-*.xlsx",
        "match": lambda n: "-ITR-STATUS-" in n and n.endswith(".XLSX"),
        "emailable": False,  # download-only, never emailed
    },
    {
        "key": "intimation", "template_key": "intimation",
        "label": "Intimation Order", "short_label": "Intimation",
        "subfolder": "Intimation Orders", "nested": True, "glob_suffix": "-Intimation-*.pdf",
        "match": lambda n: "-INTIMATION-" in n and n.endswith(".PDF"),
        "emailable": True,
    },
    # Paid vs Payable are deliberately separate keys/checkboxes (per the
    # user: "both serve different purposes" — a Paid challan is a payment
    # receipt, a Payable one is an amount-due notice asking the client to
    # go pay it) even though both come from downloader_challans.py/
    # challan_generator.py's shared "-Challan-" filename convention. They're
    # told apart by content, not folder (match_doc_type() only ever sees a
    # bare filename, no folder context) — challan_generator.py's filenames
    # carry an "AY_"/"TY_"-prefixed year segment (see #76) right after
    # "-Challan-", which downloader_challans.py's downloaded-challan
    # filenames never do (bare "2026_27", no prefix) — so that prefix is
    # what distinguishes a Payable challan's filename from a Paid one's.
    {
        "key": "challan_paid_pdf", "template_key": "challan_paid_pdf",
        "label": "Tax Payment Challan — Paid (PDF)", "short_label": "Challan (Paid)",
        "subfolder": "Tax Challans (Paid)", "nested": False, "glob_suffix": "-Challan-*.pdf",
        "match": lambda n: "-CHALLAN-" in n and n.endswith(".PDF")
                            and "-CHALLAN-AY_" not in n and "-CHALLAN-TY_" not in n,
        "emailable": True,
    },
    {
        "key": "challan_payable_pdf", "template_key": "challan_payable_pdf",
        "label": "Tax Payment Challan — Payable (PDF)", "short_label": "Challan (Payable)",
        "subfolder": "Tax Challans (Payable)", "nested": False, "glob_suffix": "-Challan-*.pdf",
        "match": lambda n: "-CHALLAN-" in n and n.endswith(".PDF")
                            and ("-CHALLAN-AY_" in n or "-CHALLAN-TY_" in n),
        "emailable": True,
    },
    # Net Banking/Debit Card/Payment Gateway modes have no downloadable
    # document — generate_challan() screenshots the confirmation page as a
    # PNG instead (see PAYMENT_MODES' "view_details_screenshot" artifact).
    # Same key/checkbox as the Payable PDF entry above.
    {
        "key": "challan_payable_pdf", "template_key": "challan_payable_pdf",
        "label": "Tax Payment Challan — Payable (PDF)", "short_label": "Challan (Payable)",
        "subfolder": "Tax Challans (Payable)", "nested": False, "glob_suffix": "-Challan-*.png",
        "match": lambda n: "-CHALLAN-" in n and n.endswith(".PNG")
                            and ("-CHALLAN-AY_" in n or "-CHALLAN-TY_" in n),
        "emailable": True,
    },
]


def match_doc_type(basename_upper: str) -> dict | None:
    """Return the first DOC_TYPES entry whose `match` predicate matches this
    (already-uppercased) basename, or None if nothing recognizes it."""
    for entry in DOC_TYPES:
        if entry["match"](basename_upper):
            return entry
    return None
