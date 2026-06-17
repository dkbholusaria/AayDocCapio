# AIS JSON Structure Reference

> **Version:** AIS JSON schema version 11.0.0 (AIS Utility, FY 2024-25 downloads)  
> **Last updated:** 2026-06-17  
> Verified against 5 real decrypted AIS files: Vikas Banga, Pankaj Poddar, Rakesh Kumar, Deepak Bholusaria, Shivasis Das, Suraj Prasad (all FY 2024-25).

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
| PAN (lowercase) | `afcpb9287r` |
| Fixed pepper | `GQ39%*g` |
| DOB in DDMMYYYY | `09071979` |
| **Full password** | **`afcpb9287rGQ39%*g09071979`** |

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
  "loggedInPan":    "AFCPB9287R",
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
    "AFCPB9287R", "XXXX-XXXX-1234", "VIKAS BANGA",
    "09/07/1979", "9XXXXXXXXX", "v***@gmail.com", "..."
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
| B4 — Demand & Refund | `demandAndRefund` | l1/l2 | Present but may have 0 elements |
| B5 — Pending Proceedings | *(key unknown)* | l1/l2 | **Absent from JSON entirely** when no proceedings |
| B6 — Completed Proceedings | *(key unknown)* | l1/l2 | **Absent from JSON entirely** when no proceedings |
| B7 — Other Info | `other-info` | l1/l2 | Present; may have elements with `l1: null` |

---

## 7. Two Element Schemas

### Schema A — l1/l2 (used by all sections except `paymentOfTaxes`)

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

## 8. B1 — TDS / TCS Detail

`sectionKey: "tdsTcs"` — typically 6-20 elements, one per deductor/collector.

**l1 columns (8, uniform across all TDS elements):**

| # | Name | Type |
|---|---|---|
| 1 | TSN | String |
| 2 | Quarter | String |
| 3 | Date of Payment/Credit | String |
| 4 | Amount Paid/Credited | decimal |
| 5 | TDS Deducted | decimal |
| 6 | TDS Deposited | decimal |
| 7 | Status | String |
| 8 | Feedback | String |

l2 Info Code examples: `AIS_TDS_SAL` (salary), `AIS_TDS_INT` (interest), `AIS_TCS_GOODS` (TCS on goods), etc.

---

## 9. B2 — SFT (Specified Financial Transactions)

`sectionKey: "sft"` — up to 30+ elements. SFT codes may appear multiple times (once per reporting entity).

### All 18 SFT Codes

| Code | Description | Threshold | Reporter |
|---|---|---|---|
| SFT-001 | Purchase of bank drafts/pay orders in cash | ₹10L | Banks |
| SFT-002 | Purchase of pre-paid instruments in cash | ₹10L | Banks |
| SFT-003 | Cash deposits — current accounts | ₹50L | Banks |
| SFT-004 | Cash deposits — non-current accounts | ₹10L | Banks, Post Office |
| SFT-005 | Time deposit purchases | ₹10L | Banks, NBFCs, Post Office |
| SFT-006 | Credit card payments | ₹1L cash / ₹10L other mode | Banks |
| SFT-007 | Purchase of bonds/debentures | ₹10L | Issuers |
| SFT-008 | Purchase of shares | ₹10L | Companies (including buyback) |
| SFT-009 | Share buybacks | ₹10L | Listed companies |
| SFT-010 | Purchase of mutual fund units | ₹10L | AMCs / RTAs |
| SFT-011 | Foreign currency purchases | ₹10L | Authorised dealers |
| SFT-012 | Immovable property transactions | ₹30L | Sub-Registrars |
| SFT-013 | Cash payments for goods/services | ₹2L per transaction | Persons under tax audit |
| SFT-014 | Cash deposits Nov–Dec 2016 (demonetization) | ₹2.5L | Banks, Post Office |
| SFT-015 | Dividend distributions | All dividends | Companies |
| SFT-016 | Interest payments | All interest | Banks, NBFCs, Post Office |
| SFT-017 | Securities sale/transfer (Depository) | All transactions | CDSL, NSDL |
| SFT-018 | MF unit sale/purchase (RTA) | All transactions | KFintech (CAMS) |

### SFT Column Structures (confirmed from real files)

#### SFT-005 — Time deposit purchases (6 cols)
| # | Name |
|---|---|
| 1 | TSN |
| 2 | Reported On |
| 3 | Gross amount received from the person |
| 4 | Gross amount paid to the person |
| 5 | Status |
| 6 | Feedback |

#### SFT-012 — Sale of immovable property (12 cols)
| # | Name |
|---|---|
| 1 | TSN |
| 2 | Reported On |
| 3 | Property Address |
| 4 | Property type |
| 5 | Transaction Type |
| 6 | Transaction Date |
| 7 | Transaction amount |
| 8 | Value for Stamp Duty |
| 9 | Party Count |
| 10 | Transaction amount assigned |
| 11 | Status |
| 12 | Feedback |

#### SFT-015 — Dividend from companies (5 cols)
| # | Name |
|---|---|
| 1 | TSN |
| 2 | Reported On |
| 3 | Dividend Amount |
| 4 | Status |
| 5 | Feedback |

Each dividend-paying company generates a separate element with Info Code `SFT-015`. A single AIS may have 10+ SFT-015 elements.

#### SFT-016 — Bank interest (7 cols; same structure for all 3 sub-codes)

Sub-codes: `SFT-016(SB)` savings bank, `SFT-016(TD)` term deposit, `SFT-016(RD)` recurring deposit.

| # | Name |
|---|---|
| 1 | TSN |
| 2 | Reported On |
| 3 | Account Number |
| 4 | Account Type |
| 5 | Interest amount |
| 6 | Status |
| 7 | Feedback |

#### SFT-017 — Capital market sales via Depository (16 cols)

`l1Src: "AIS_SEC_DEP_MF"` — applies to: `SFT-17-LES(M)` listed equity, `SFT-17-LDB(M)` listed debenture, `SFT-17-EMF(M)` equity MF, `SFT-17-OTU(M)` other units, `SFT-17-UBT(M)` REIT/InvIT.

| # | Name |
|---|---|
| 1 | TSN |
| 2 | Date of Sale/Transfer |
| 3 | Security Name (Security Code) |
| 4 | Security Class |
| 5 | Debit Type |
| 6 | Credit Type |
| 7 | Asset Type |
| 8 | Quantity |
| 9 | Sale Price Per unit |
| 10 | Sales Consideration |
| 11 | Cost of Acquisition |
| 12 | Unit FMV |
| 13 | Fair Market Value |
| 14 | Indexed Cost of Acquisition |
| 15 | Status |
| 16 | Feedback |

#### SFT-018 — Capital market sales via RTA (18 cols)

`l1Src: "AIS_SEC_DEP_MF"` — applies to: `SFT-18-EMF(M)` equity MF, `SFT-18-OTU(M)` other units.

Same as SFT-017 but with `AMC Name (Code)` inserted as column 2 (after TSN) and `STT` inserted as column 12 (after Sales Consideration). Total: 18 cols.

| # | Name |
|---|---|
| 1 | TSN |
| **2** | **AMC Name (Code)** |
| 3 | Date of Sale/Transfer |
| 4 | Security Class |
| 5 | Security Name (Security Code) |
| 6 | Debit Type |
| 7 | Credit Type |
| 8 | Asset Type |
| 9 | Quantity |
| 10 | Sale Price Per unit |
| 11 | Sales Consideration |
| **12** | **STT** |
| 13 | Cost of Acquisition |
| 14 | Unit FMV |
| 15 | Fair Market Value |
| 16 | Indexed Cost of Acquisition |
| 17 | Status |
| 18 | Feedback |

#### SFT-17(Pur) — Depository purchase aggregate (8 cols)

`l1Src: "AIS_SEC_DEP_MF_HLD_PUR_DIV"` — Info Code `SFT-17(Pur)`.

| # | Name |
|---|---|
| 1 | TSN |
| 2 | Quarter |
| 3 | Client ID |
| 4 | Holder Flag |
| 5 | Market Purchase |
| 6 | Market Sales |
| 7 | Status |
| 8 | Feedback |

#### SFT-18(Pur) — RTA purchase aggregate (9 cols)

`l1Src: "AIS_SEC_DEP_MF_HLD_PUR_DIV"` — Info Code `SFT-18(Pur)`.

Same as SFT-17(Pur) but with `AMC Name (Code)` inserted as column 4 (between Client ID and Holder Flag).

| # | Name |
|---|---|
| 1 | TSN |
| 2 | Quarter |
| 3 | Client ID |
| **4** | **AMC Name (Code)** |
| 5 | Holder Flag |
| 6 | Total Purchase Amount |
| 7 | Total Sales Value |
| 8 | Status |
| 9 | Feedback |

Multiple `SFT-18(Pur)` elements appear — one per RTA (e.g. KFintech, CAMS).

#### SFT-18(Div) — MF dividend via RTA (9 cols)

`l1Src: "AIS_SEC_DEP_MF_HLD_PUR_DIV"` — Info Code `SFT-18(Div)`.

| # | Name |
|---|---|
| 1 | TSN |
| 2 | Quarter |
| 3 | Client ID |
| 4 | AMC Name (Code) |
| 5 | No. of Holders |
| 6 | Holder Flag |
| 7 | Dividend Amount |
| 8 | Status |
| 9 | Feedback |

---

## 10. B3 — Payment of Taxes (Direct Schema)

`sectionKey: "paymentOfTaxes"` — uses **Schema B** (direct, no l1/l2 nesting).

**12 columns:**

| # | Name | Notes |
|---|---|---|
| 1 | Assessment Year | e.g. `2025-26` |
| 2 | Major Head | e.g. `0021` (Income Tax) |
| 3 | Minor Head | e.g. `300` (Advance Tax) |
| 4 | Tax (A) | decimal |
| 5 | Surcharge (B) | decimal |
| 6 | Education Cess (C) | decimal |
| 7 | Others (D) | decimal |
| 8 | Total (A+B+C+D) | decimal |
| 9 | BSR Code | bank branch code |
| 10 | Date Of Deposit | e.g. `05-Dec-2024` |
| 11 | Challan Serial Number | |
| 12 | Challan Identification Number | |

Example: Vikas Banga has 3 Advance Tax challans totalling ₹3,10,000.

---

## 11. B4 — Demand and Refund

`sectionKey: "demandAndRefund"` — uses Schema A (l1/l2). Present but may have 0 elements. Skip sheet if empty.

---

## 12. B5 / B6 — Pending / Completed Proceedings

**Absent from the JSON entirely** when there are no proceedings — not just empty sections. The converter must use `section.get("sectionKey") == "pendingProceedings"` (key unknown) and skip gracefully if not found.

---

## 13. B7 — Other Information

`sectionKey: "other-info"` — uses Schema A (l1/l2). May contain:

- `AIS_TDS_ANNEX2` — Salary Annexure II (for salaried employees)

#### AIS_TDS_ANNEX2 — Salary Annexure II (9 cols)

| # | Name |
|---|---|
| 1 | TSN |
| 2 | Employment Start Date |
| 3 | Employment End Date |
| 4 | Gross Salary u/s 17(1) |
| 5 | Perquisites u/s 17(2) |
| 6 | Profits in lieu of salary u/s 17(3) |
| 7 | Gross Salary |
| 8 | Status |
| 9 | Feedback |

**B7 edge case:** The B7 section may be present with elements where `l1` is `null` and `l2.columnData` is absent. This means the section header exists but there is no actual data. The converter must guard against `l1 is None` and skip the B7 sheet if all elements are empty.

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
| TDS / TCS | `tdsTcs` section l1 rows | If non-empty |
| Capital Market Sales | `sft` elements with `l1Src=AIS_SEC_DEP_MF` | If non-empty |
| Capital Market Purchases | `sft` elements with `l1Src=AIS_SEC_DEP_MF_HLD_PUR_DIV` | If non-empty |
| SFT — Other | All other `sft` elements | If non-empty |
| Payment of Taxes | `paymentOfTaxes` direct schema | If non-empty |
| B7 / Other Info | `other-info` section l1 rows | If non-empty |
| Demand & Refund | `demandAndRefund` section | If non-empty |
| Pending Proceedings | B5 section (unknown key) | If section present |
| Completed Proceedings | B6 section (unknown key) | If section present |

All sheets use the **flat-table** pattern: one header row, parent fields repeated on every detail row, subtotals after each group, grand total at end. No staircase/nested headers.
