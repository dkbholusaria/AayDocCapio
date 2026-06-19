# AIS JSON Structure Reference

> **Version:** AIS JSON schema version 11.0.0 (AIS Utility, FY 2024-25 downloads)  
> **Last updated:** 2026-06-17  
> Verified against 7 real decrypted AIS files. 

---

## 1. File Format (Encryption)

The AIS JSON file downloaded from the ITD portal or AIS Utility is **AES-256-CBC encrypted**. The file is a flat binary blob with the following layout:

```
Bytes 0–31   : 32 ASCII hex characters = AES IV (16 bytes when decoded)
Bytes 32–63  : 32 ASCII hex characters = PBKDF2 salt (16 bytes when decoded)
Bytes 64–end : Base64-encoded AES-256-CBC ciphertext (PKCS7 padded)
```

**IMPORTANT:** IV comes first, salt second. This is the opposite of what some third-party documentation suggests.

### Password formula

```
password = pan.lower() + "GQ39%*g" + dob_ddmmyyyy
```

| Component | Example |
|---|---|
| PAN (lowercase) | `<pan_lower>` |
| Fixed pepper | `GQ39%*g` |
| DOB in DDMMYYYY | `<dob_ddmmyyyy>` |
| **Full password** | **`<pan_lower>GQ39%*g<dob_ddmmyyyy>`** |

DOB stored in vault as `DD-MM-YYYY` — strip the hyphens to get `DDMMYYYY`.

### Key derivation

| Parameter | Value |
|---|---|
| Algorithm | PBKDF2-HMAC-SHA256 |
| Iterations | 1000 |
| Key length | 32 bytes (256-bit) |
| Salt | 16 bytes from bytes 32–63 of the file |

### Decryption (Python)

```python
import base64, hashlib, json
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding

def decrypt_ais_json(json_path: str, pan: str, dob: str) -> dict:
    """
    Decrypt an ITD AIS JSON file.
    pan: any case (lowercased automatically)
    dob: vault format DD-MM-YYYY (hyphens stripped automatically)
    Raises ValueError on wrong PAN/DOB (bad PKCS7 padding).
    """
    with open(json_path, "rb") as f:
        raw = f.read()

    iv_bytes   = bytes.fromhex(raw[0:32].decode())
    salt_bytes = bytes.fromhex(raw[32:64].decode())
    ct         = base64.b64decode(raw[64:])

    pw  = (pan.lower() + "GQ39%*g" + dob.replace("-", "")).encode("utf-8")
    key = hashlib.pbkdf2_hmac("sha256", pw, salt_bytes, 1000, dklen=32)

    cipher  = Cipher(algorithms.AES(key), modes.CBC(iv_bytes), backend=default_backend())
    dec     = cipher.decryptor()
    padded  = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    data    = unpadder.update(padded) + unpadder.finalize()
    return json.loads(data)
```

A `ValueError` (bad padding) means wrong PAN or DOB. The `cryptography` library is already a project dependency via `vault.py`.

---

## 2. Top-Level JSON Structure

```json
{
  "metadata":          { ... },
  "header":            { "columnLabel": [...], "columnData": [...] },
  "partA":             null,
  "partB":             { "sections": [ ... ] },
  "rejectedFeedbacks": null,
  "footer":            { "columnLabel": [...], "columnData": [...] },
  "fileSize":          null
}
```

---

## 3. `metadata`

```json
{
  "loggedInPan":    "<PAN>",
  "jsonVersion":    "11.0.0",
  "downloadDate":   "23-Jul-2025",
  "utilityVersion": "..."
}
```

Used to derive the output filename: `{PAN}-AIS-{FY}.xlsx`. FY is derived from `downloadDate` — a July 2025 download is for FY 2024-25.

---

## 4. `header` — Part A (General Information)

```json
{
  "columnLabel": [
    "PAN", "Aadhaar Number", "Name of Assessee",
    "Date of Birth", "Mobile Number", "E-mail Address", "Address"
  ],
  "columnData": [
    "<PAN>", "<MASKED_AADHAAR>", "<ASSESSEE_NAME>",
    "<DOB_DD/MM/YYYY>", "<MOBILE>", "<EMAIL>", "<ADDRESS>"
  ]
}
```

Seven fields, always present. Rendered as key-value pairs in the General Info sheet.

---

## 5. `footer`

```json
{
  "columnLabel": ["Download ID", "IP Address", "Generation Date"],
  "columnData":  ["ABC123456", "XX.XX.XX.XX", "23-Jul-2025 10:35:42"]
}
```

---

## 6. `partB` — The Main Data

`partB.sections` is a list of section objects. Up to 7 sections may appear; B5 and B6 are **absent entirely** (not present as empty sections) when there are no proceedings.

### Section object

```json
{
  "sectionKey": "tdsTcs",
  "title": "Part B1-Information relating to tax deducted or collected at source",
  "heading": "TDS/TCS Information",
  "elements": [ ... ]
}
```

### Section map

| DIT Label | `sectionKey` | Element schema | Notes |
|---|---|---|---|
| B1 — TDS/TCS | `tdsTcs` | l1/l2 | Always present |
| B2 — SFT | `sft` | l1/l2 | Always present |
| B3 — Payment of Taxes | `paymentOfTaxes` | **direct** | Always present; different schema |
| B4 — Demand & Refund | `demandAndRefund` | **subSections (direct)** | Present but may have 0 subSections/elements |
| B5 — Pending Proceedings | *(key unknown)* | l1/l2 | **Absent from JSON entirely** when no proceedings |
| B6 — Completed Proceedings | *(key unknown)* | l1/l2 | **Absent from JSON entirely** when no proceedings |
| B7 — Other Info | `other-info` | l1/l2 | Present; may have elements with `l1: null` |

---

## 7. Two Element Schemas

### Schema A — l1/l2 (used by `tdsTcs`, `sft`, and `other-info`)

```json
{
  "title":  "TDS on Salary",
  "l1Src":  "AIS_TDS_TCS",
  "l1": {
    "columnLabel": [
      { "field": "tsn",     "name": "TSN",                   "type": "String",  "seq": 1, "sumRequired": false },
      { "field": "quarter", "name": "Quarter",                "type": "String",  "seq": 2, "sumRequired": false },
      { "field": "amount",  "name": "Amount Paid/Credited",   "type": "decimal", "seq": 3, "sumRequired": true  }
    ],
    "columnData": [
      ["TSN001", "Q1", "500000.00", "HIDDEN_EXTRA_FIELD"],
      ["TSN002", "Q2", "500000.00"]
    ]
  },
  "l2": {
    "columnLabel": [
      "Information Category", "Information Code", "Information Description",
      "Information Source", "Count", "Amount",
      "Information Category Code", "Derived Amount", "Qualifies For"
    ],
    "columnData": [
      ["TDS", "AIS_TDS_SAL", "Tax deducted on salary", "EMPLOYER XYZ", "2", "1000000.00", "TDS", "0", ""]
    ]
  }
}
```

**Key rules for l1:**
- `columnLabel` is a list of dicts with `field`, `name`, `type`, `seq`, `sumRequired`.
- `columnData` rows may have **more values than columnLabel entries** — the extra values are hidden internal fields. Always use only `len(columnLabel)` values per row.
- `l1` can be `null` when the element definition exists but has no detail data (seen in B7 with no salary data).

**l2 is always 9 columns** (fixed across all sections):
1. Information Category
2. Information Code
3. Information Description
4. Information Source
5. Count
6. Amount
7. Information Category Code
8. Derived Amount
9. Qualifies For

l2 has exactly one summary row per element. The Summary sheet is built entirely from l2 rows.

### Schema B — Direct (used only by `paymentOfTaxes`)

```json
{
  "title": "Advance Tax",
  "columnLabel": ["Assessment Year", "Major Head", "Minor Head", "Tax (A)", "..."],
  "columnData": [
    ["2025-26", "0021", "300", "200000.00", "..."]
  ],
  "columnDataType": ["String", "String", "String", "decimal", "..."]
}
```

- `columnLabel` is a plain list of strings (not dicts).
- No `l1`/`l2` nesting.
- No `l1Src` field.

The converter detects the schema by checking whether `element.get("l1")` or `element.get("l2")` exists.

---

## 8. Section-Specific Details (TDS/TCS, SFT, Taxes, etc.)

For full details on the columns, data types, and schemas for each specific section (B1 through B7), refer to the interactive documentation in:
👉 **[AIS_JSON_Tree.html](AIS_JSON_Tree.html)**

This HTML file provides:
- Complete field listings and data types for all TDS/TCS, SFT, Taxes, Refunds, and Other Info sections (Part B1 to B7)
- An interactive, collapsible **Part B Section & Info Code Quick Reference** index tree
- Centralized reference tables for **short-code enum mappings** and **data format validation rules** (such as PAN, ISIN, and decimal amounts format regexes)
- Real-world warnings highlighting data length quirks and schema types (Schema A vs. Schema B)

---

## 14. Known Quirks and Gotchas

| Quirk | Detail |
|---|---|
| Extra l1 row values | `columnData` rows often have more values than `columnLabel` entries. The extra values are hidden internal fields (e.g. feedback codes). Always use only `len(columnLabel)` values. |
| Multiple elements per Info Code | The same Info Code (e.g. `SFT-015`, `SFT-18(Pur)`) appears multiple times — once per reporting entity. All rows belong to the same logical group. |
| B5/B6 absent vs empty | Not having B5/B6 sections is different from having them with 0 elements. The converter must check for section key existence, not just empty element lists. |
| `l1: null` in B7 | When no salary data, B7 element still exists with `l1: null`. Skip detail row rendering silently. |
| Amount formatting | l2 amounts are strings with commas: `"3,10,000.00"`. Strip commas before numeric operations. |
| `downloadDate` format | `"23-Jul-2025"` — parse as `%d-%b-%Y` to derive FY. A download in Apr–Dec of year Y is FY (Y-1)–Y; Jan–Mar of year Y is FY (Y-1)–Y as well (ITD financial year ends 31 March). |
| 2023-24 files | AIS JSON files downloaded in 2024 (before the current AIS Utility version) used a different encryption scheme that is not compatible with the current decryption code. Only 2024-25 and newer downloads are supported. |

---

## 15. Excel Output Mapping

| Sheet | Source | Condition |
|---|---|---|
| General Info | `header.columnData` + `footer.columnData` | Always |
| Summary | All l2 rows from all sections | Always |
| Part B1 - TDS TCS | `tdsTcs` elements excluding TDS-194IA(P) | If non-empty |
| Part B1 - TDS on Property | `tdsTcs` elements with info_code=TDS-194IA(P) | If present |
| B2 - SFT-005 Time Deposit | `sft` info_code=SFT-005 | If present |
| B2 - SFT-006 Credit Card | `sft` info_code=SFT-006 | If present |
| B2 - SFT-008 Purchase of Shares | `sft` info_code=SFT-008 | If present |
| B2 - SFT-010 MF Purchase | `sft` info_code=SFT-010 | If present |
| B2 - SFT-012 Immovable Property | `sft` info_code=SFT-012 | If present |
| B2 - SFT-015 Dividend | `sft` info_code=SFT-015 | If present |
| B2 - SFT-016 Interest Savings | `sft` info_code=SFT-016(SB) | If present |
| B2 - SFT-016 Interest Term Dep | `sft` info_code=SFT-016(TD) | If present |
| B2 - SFT-016 Interest Rec Dep | `sft` info_code=SFT-016(RD) | If present |
| B2 - SFT-17 Sec Purchase Dep | `sft` info_code=SFT-17(Pur) | If present |
| B2 - SFT-18 MF Purchase RTA | `sft` info_code=SFT-18(Pur) | If present |
| B2 - SFT-18 MF Dividend RTA | `sft` info_code=SFT-18(Div) | If present |
| B2 - SFT-17 Equity Sale Dep | `sft` info_code=SFT-17-LES(M) | If present |
| B2 - SFT-17 Debenture Sale Dep | `sft` info_code=SFT-17-LDB(M) | If present |
| B2 - SFT-17 Eq MF Sale Dep | `sft` info_code=SFT-17-EMF(M) | If present |
| B2 - SFT-17 Bus Trust Sale Dep | `sft` info_code=SFT-17-UBT(M) | If present |
| B2 - SFT-17 Othr Units Sale Dep | `sft` info_code=SFT-17-OTU(M) | If present |
| B2 - SFT-17 Equity Off-Market | `sft` info_code=SFT-17-LES(OC) | If present |
| B2 - SFT-18 Eq MF Sale RTA | `sft` info_code=SFT-18-EMF(M) | If present |
| B2 - SFT-18 Othr Units Sale RTA | `sft` info_code=SFT-18-OTU(M) | If present |
| Payment of Taxes | `paymentOfTaxes` direct schema | If non-empty |
| B7 - Salary | `other-info` info_code=TDS-Ann.II-SAL | If present |
| Demand & Refund | `demandAndRefund` section | If non-empty |
| Pending Proceedings | B5 section (unknown key) | If section present |
| Completed Proceedings | B6 section (unknown key) | If section present |

**Sheet naming rule:** All SFT sheets use prefix `B2 - ` and are truncated to 31 chars (Excel limit). Unknown info codes fall back to dynamic superset and sheet name `B2 - {code}`.

All sheets use the **flat-table** pattern: one header row, Sr. + Source repeated on every detail row, `=SUM()` subtotals after each source group, grand total summing subtotal cells only. No staircase/nested headers.
