"""
automation/challan_fields.py
==============================
Single source of truth for the per-client input columns used by
GenerateChallansDialog's table, its Excel/CSV import, its export, and its
import template — see automation/doc_types.py's own docstring for why this
matters: the Form 168 emailer bugs happened twice because two files each
kept their own copy of a column list and drifted apart. Financial Year and
Tax Type are NOT here — they're picked once for the whole dialog/batch, not
per client (see automation/challan_generator.py's TAX_TYPES).

Payment Mode and Bank ARE per-client here (unlike Year/Tax Type) — each
client may pay through a different bank/mode, confirmed by the user's own
correction: this isn't a single batch-wide choice like Year is.
"""

CHALLAN_INPUT_COLUMNS = [
    # (field_key, header_label, kind)
    ("pan",           "PAN",             "text"),
    ("payment_mode",  "Payment Mode",    "choice"),   # see automation.challan_generator.PAYMENT_MODES
    ("bank",          "Bank / Sub-Mode", "choice"),   # options depend on payment_mode
    ("drawee_bank",   "Drawn on Bank",   "text"),     # Pay at Bank Counter + Cheque/Demand Draft only —
                                                       # confirmed against a real sample PDF ("Drawn on
                                                       # Bank: Kotak Mahindra Bank"); blank for every
                                                       # other mode/sub-mode combination.
    ("tax",           "Tax",             "amount"),
    ("surcharge",     "Surcharge",       "amount"),
    ("cess",          "Cess",            "amount"),
    ("interest",      "Interest",        "amount"),
    ("penalty",       "Penalty",         "amount"),
    ("others",        "Others",          "amount"),
]

CHALLAN_AMOUNT_FIELDS = [key for key, _, kind in CHALLAN_INPUT_COLUMNS if kind == "amount"]

CHALLAN_SUMMARY_COLUMNS = [
    "PAN", "Name", "Financial Year", "Tax Type", "Portal Year Label",
    "Payment Mode", "Bank", "Drawn on Bank", "Total Amount", "CRN", "Valid Till",
    "Status", "Reason", "Artifact Path",
]

# ── TDS/TCS challan (F-4) ────────────────────────────────────────────────
# A TDS challan is NOT the same row shape as an Income Tax challan: it has
# one or more section codes, each with its own Tax / Surcharge / Cess, plus
# ONE common set of other payments. Kept separate from CHALLAN_INPUT_COLUMNS
# so the Income Tax dialog/import/export cannot drift.
TDS_SECTION_FIELDS = [
    ("section_code", "Section Code", "text"),
    ("tax",          "Tax",          "amount"),
    ("surcharge",    "Surcharge",    "amount"),
    ("cess",         "Education Cess", "amount"),
]

TDS_OTHER_FIELDS = [
    ("interest", "Interest (d)",          "amount"),
    ("fee",      "Late Fee u/s 427 (e)",  "amount"),
    ("penalty",  "Penalty (f)",           "amount"),
    ("others",   "Others (g)",            "amount"),
]

TDS_AMOUNT_FIELDS = [k for k, _, kind in TDS_SECTION_FIELDS if kind == "amount"]
TDS_OTHER_AMOUNT_FIELDS = [k for k, _, kind in TDS_OTHER_FIELDS if kind == "amount"]

TDS_SUMMARY_COLUMNS = [
    "TAN", "Name", "Tax Year", "Deductee Type", "Residence", "Sections",
    "Total Amount", "Payment Mode", "Bank", "Drawn on Bank", "CRN",
    "Valid Till", "Status", "Reason", "Artifact Path",
]
