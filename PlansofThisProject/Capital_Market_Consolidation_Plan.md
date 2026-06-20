# Implementation Plan: Restructuring consolidated "⭐ Capital Market (All)" Sheet

This plan outlines the implementation of the revised blueprint for the **⭐ Capital Market (All)** sheet. 
The new layout expands the columns to 30, shifts the data columns left by removing instructional margin offsets, links raw data cells back to individual source sheets, computes capital gains, and applies defined names.

---

## 1. Column Specifications & Mapping Matrix

The consolidated sheet will contain exactly 30 columns (shifted left to start at Column A). 
Below is the mapping showing how each column is populated or computed, including the exact individual sheet source column.

*Let $R_{ind}$ be the 1-based row number in the source sheet (data starts at row 3).*

| Col Letter | Col Name | Source Type | SFT-17 Depository Source | SFT-18 RTA Source | SFT-17-LES(OC) Source |
|---|---|---|---|---|---|
| **A** | `SFT Code` | Static Value | Static string (e.g. `"SFT-17-LES(M)"`) | Static string | `"SFT-17-LES(OC)"` |
| **B** | `Sr.` | Computed | Sequential counter (1, 2, 3...) | Sequential counter | Sequential counter |
| **C** | `Source` | Link | `='{WS}'!B{R_ind}` | `='{WS}'!B{R_ind}` | `='{WS}'!B{R_ind}` |
| **D** | `TransID` | Link | `='{WS}'!C{R_ind}` (`TSN`) | `='{WS}'!C{R_ind}` (`TSN`) | `='{WS}'!C{R_ind}` (`TSN`) |
| **E** | `AMC Name (Code)` | Link | `""` (Empty) | `='{WS}'!D{R_ind}` | `""` (Empty) |
| **F** | `Debit Type` | Link | `='{WS}'!H{R_ind}` (`Debit Type`) | `='{WS}'!I{R_ind}` (`Debit Type`) | `='{WS}'!F{R_ind}` (`Nature`) |
| **G** | `Credit Type` | Link | `='{WS}'!I{R_ind}` (`Credit Type`) | `='{WS}'!J{R_ind}` (`Credit Type`) | `""` (Empty) |
| **H** | `Date of Sale/Transfer` | Link | `='{WS}'!D{R_ind}` | `='{WS}'!E{R_ind}` | `='{WS}'!E{R_ind}` (`Date of Transfer`) |
| **I** | `ISIN` | Link | `='{WS}'!E{R_ind}` | `='{WS}'!G{R_ind}` | `='{WS}'!G{R_ind}` |
| **J** | `Security Name` | Link | `='{WS}'!F{R_ind}` | `='{WS}'!H{R_ind}` | `='{WS}'!H{R_ind}` |
| **K** | `Security Class` | Link | `='{WS}'!G{R_ind}` | `='{WS}'!F{R_ind}` | `='{WS}'!I{R_ind}` |
| **L** | `Asset Type` | Link | `='{WS}'!J{R_ind}` | `='{WS}'!K{R_ind}` | `""` (Empty) |
| **M** | `Quantity` | Link | `='{WS}'!K{R_ind}` | `='{WS}'!L{R_ind}` | `='{WS}'!J{R_ind}` (`Quantity Transfd`) |
| **N** | `Sale Price (Per unit)` | Link | `='{WS}'!L{R_ind}` | `='{WS}'!M{R_ind}` | `='{WS}'!K{R_ind}` (`EOD Price`) |
| **O** | `Sale Consideration (net)` | Link | `='{WS}'!M{R_ind}` (`Sales Consideration`) | `='{WS}'!N{R_ind}` (`Sales Consideration`) | `='{WS}'!M{R_ind}` (`Consideration`) |
| **P** | `STT` | Link | `0` | `='{WS}'!O{R_ind}` | `0` |
| **Q** | `Gross Cost of Acquisition (w/o index)` | Link | `='{WS}'!N{R_ind}` (`Cost of Acquisition`) | `='{WS}'!P{R_ind}` (`Cost of Acquisition`) | `0` (Empty) |
| **R** | `Indexed Cost of Acquisition` | Link | `='{WS}'!Q{R_ind}` | `='{WS}'!S{R_ind}` | `0` (Empty) |
| **S** | `FMV 31-Jan-2018 (per unit)` | Link | `='{WS}'!O{R_ind}` (`Unit FMV`) | `='{WS}'!Q{R_ind}` (`Unit FMV`) | `0` (Empty) |
| **T** | `FMV 31-Jan-2018 (Total)` | Link | `='{WS}'!P{R_ind}` (`Fair Market Value`) | `='{WS}'!R{R_ind}` (`Fair Market Value`) | `0` (Empty) |
| **U** | `Assets Eligible for GrandFathering` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **V** | `Effetive FMV 31-03-2028 for long term assets` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **W** | `Adj. FMV (lower of Sale & FMV)` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **X** | `Adj. Cost of Acquisition (no indexation)` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **Y** | `Capital Gain (w/o Indexation)` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **Z** | `Capital Gain (w/ Indexation)` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **AA** | `STCG (Rs.)` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **AB** | `LTCG w/o Indexation (Rs.)` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **AC** | `LTCG with Indexation (Rs.)` | Formula | See Section 2 below | See Section 2 below | See Section 2 below |
| **AD** | `Status` | Link | `='{WS}'!R{R_ind}` | `='{WS}'!T{R_ind}` | `='{WS}'!N{R_ind}` |

---

## 2. Formula Logic Specifications

For each data row at 1-based Excel row index $xr$, the formulas are:

1.  **Assets Eligible for GrandFathering (Column U)**:
    Determines if the asset qualifies for Section 55(2)(ac) grandfathering.
    ```excel
    =IF(AND(ISNUMBER(SEARCH("Long", L{xr})), OR(K{xr}="Listed Equity Share", K{xr}="Unit of Equity Oriented Mutual Fund", K{xr}="Unit of Business Trust", AND(K{xr}="Other Units", S{xr}>0))), "Yes - Eligible", IF(ISNUMBER(SEARCH("Short", L{xr})), "No - Short term Asset", "No - Ineligible Asset"))
    ```

2.  **Effetive FMV 31-03-2028 for long term assets (Column V)**:
    Pulls the total FMV as of Jan 31, 2018 if eligible, otherwise 0.
    ```excel
    =IF(U{xr}="Yes - Eligible", T{xr}, 0)
    ```

3.  **Adj. FMV (lower of Sale & FMV) (Column W)**:
    Caps FMV at the actual sale consideration.
    ```excel
    =MIN(O{xr}, V{xr})
    ```

4.  **Adj. Cost of Acquisition (no indexation) (higher of Adj. FMV or Actual CoA) (Column X)**:
    Computes grandfathered cost base.
    ```excel
    =MAX(Q{xr}, W{xr})
    ```

5.  **Capital Gain (w/o Indexation) (Column Y)**:
    ```excel
    =O{xr}-X{xr}
    ```

6.  **Capital Gain (w/ Indexation) (Column Z)**:
    ```excel
    =O{xr}-R{xr}
    ```

7.  **STCG (Rs.) (Column AA)**:
    Applies Capital Gain (w/o Indexation) if the asset is short term.
    ```excel
    =IF(ISNUMBER(SEARCH("Short", L{xr})), Y{xr}, 0)
    ```

8.  **LTCG w/o Indexation (Rs.) (Column AB)**:
    Applies Capital Gain (w/o Indexation) if long term.
    ```excel
    =IF(ISNUMBER(SEARCH("Long", L{xr})), Y{xr}, 0)
    ```

9.  **LTCG with Indexation (Rs.) (Column AC)**:
    Applies Capital Gain (w/ Indexation) if long term.
    ```excel
    =IF(ISNUMBER(SEARCH("Long", L{xr})), Z{xr}, 0)
    ```

---

## 3. Defined Names (Workbook Scope)

The following workbook-scoped defined names will be registered for the consolidated sheet columns to match the blueprint's specification:

*   `CostWoIndex` $\rightarrow$ `='⭐ Capital Market (All)'!$Q:$Q`
*   `CostWIndex` $\rightarrow$ `='⭐ Capital Market (All)'!$R:$R`
*   `EligibleAssetForGF` $\rightarrow$ `='⭐ Capital Market (All)'!$U:$U`
*   `AdjustedFMV` $\rightarrow$ `='⭐ Capital Market (All)'!$W:$W`
*   `AdjustedCostWoIndex` $\rightarrow$ `='⭐ Capital Market (All)'!$X:$X`
*   `CapitalGainWoIndex` $\rightarrow$ `='⭐ Capital Market (All)'!$Y:$Y`
*   `CapitalGainWIndex` $\rightarrow$ `='⭐ Capital Market (All)'!$Z:$Z`
*   `STCG` $\rightarrow$ `='⭐ Capital Market (All)'!$AA:$AA`
*   `LTCGWoIndex` $\rightarrow$ `='⭐ Capital Market (All)'!$AB:$AB`
*   `LTCGWIndex` $\rightarrow$ `='⭐ Capital Market (All)'!$AC:$AC`

---

## 4. Subtotaling & Layout Enhancements

1.  **Category Subtotals**:
    Keep the SFT group subtotals by merging columns A to L (index 0 to 11) for the subtotal label (e.g. `"Subtotal — SFT-17-LES(M)"`) and using `=SUM()` formulas for numeric columns.
2.  **Grand Totals**:
    Merge columns A to L for the grand total label (`"GRAND TOTAL — ⭐ Capital Market (All)"`) and use `=SUM()` formulas to sum up the subtotal rows to prevent double-counting.
3.  **Gain-Tinting & Visual Grouping**:
    *   **LTCG rows**: Tint background light blue (`#f0f4ff`) with slightly darker formulas tint (`#e6f2ff`).
    *   **STCG rows**: Keep default white/alternating background.
    *   **Frozen Panes**: Freeze row headers (top 2 rows) and the first 11 columns (up to Security Class, i.e. Column K) to preserve readability while scrolling wide data.

---

## 5. Additional Explanation Sheet: "ReadMe - Capital Gains"

A new worksheet titled `"ReadMe - Capital Gains"` will be added to the output workbook to explain the calculations in plain English.

### Layout & Formatting
*   **Theme**: General Info theme (tab color: grey `#808080`).
*   **Header**: Merged cells A1:D1 with the title `"Capital Gains Computation Guide (u/s 55(2)(ac))"` in bold white text on a dark slate background (`#366092`).
*   **Columns**:
    *   Column A: **Column** (e.g. `Col U`, `Col V`...) - Width: 10
    *   Column B: **Field Name** (e.g. `Assets Eligible for GrandFathering`) - Width: 30
    *   Column C: **Plain English Explanation** - Width: 80 (Wrap Text enabled)
    *   Column D: **Income Tax Act Reference** - Width: 25

### Explanation Data Table
The following content will be written starting at row 3:

| Column | Field Name | Plain English Explanation | Tax Reference |
|---|---|---|---|
| **Col U** | `Assets Eligible for GrandFathering` | Checks if the asset was purchased before 31-Jan-2018. Only Long Term Equity Shares, Equity Mutual Funds, and Business Trusts are eligible. Short-term assets are excluded. | Section 55(2)(ac) |
| **Col V** | `Effective FMV` | Holds the Fair Market Value (FMV) as of Jan 31, 2018 if the asset is eligible for grandfathering, otherwise zero. | Section 55(2)(ac) |
| **Col W** | `Adj. FMV` | Under tax rules, the grandfathered value cannot exceed what the asset actually sold for. This takes the lower of the actual sale value or the Jan 31, 2018 FMV. | Section 55(2)(ac) |
| **Col X** | `Adj. Cost of Acquisition` | The adjusted cost base used for long-term capital gain calculation. It is the higher of the actual purchase cost or the Adjusted FMV. | Section 55(2)(ac) |
| **Col Y** | `Capital Gain (w/o Indexation)` | The capital gain computed without adjusting for inflation. Calculated as: `Sale Consideration - Adjusted Cost of Acquisition`. | Section 112A / 111A |
| **Col Z** | `Capital Gain (w/ Indexation)` | The capital gain computed by adjusting the purchase cost for inflation using government Cost Inflation Indices. Calculated as: `Sale Consideration - Indexed Cost of Acquisition`. NOTE: Indexation benefits are abolished for transfers on or after 23-Jul-2024. | Section 112 |
| **Col AA**| `STCG (Rs.)` | Short-Term Capital Gains. Applies if the asset was held for a short period (typically <= 12 months for equity, <= 24/36 months for others). Grandfathering and inflation adjustments do not apply. | Section 111A / Section 112 |
| **Col AB**| `LTCG w/o Indexation (Rs.)` | Long-Term Capital Gains taxed at 10% (under Section 112A) without inflation indexation, utilizing the grandfathered cost base u/s 55(2)(ac). NOTE: For sales on or after 23-Jul-2024, the tax rate is 12.5% u/s 112A. | Section 112A |
| **Col AC**| `LTCG with Indexation (Rs.)` | Long-Term Capital Gains computed with inflation indexation. NOTE: Under the Finance Act 2024, indexation benefits are completely abolished for transfers executed on or after 23-Jul-2024. For such transactions, this value is not applicable. | Section 112 |

### Legal Disclaimer Block
To protect the tool and outline its informational nature, a prominent disclaimer will be placed below the explanation table (leaving a 2-row margin). It will be styled with a soft red/coral background fill (`#F2DCDB`) and dark red text:

> **Disclaimer**: The computations, tax references, and plain-English explanations provided in this workbook are generated on a **best-efforts basis for informational and illustrative purposes only**. They do not constitute formal professional advice, legal opinion, or tax consulting. While every care has been taken to align the calculations with the provisions of the Income Tax Act, 1961 (including Section 55(2)(ac) and Section 112A/112), tax laws are subject to frequent legislative amendments, administrative updates, and varying judicial interpretations. The user is strongly advised to seek independent guidance from a qualified Chartered Accountant (CA) or tax professional and refer to the official statutory provisions/law before filing any tax returns or making investment decisions. The developers of this application assume no liability for any errors, omissions, or financial consequences arising from the use of this worksheet.

---


## 6. Verification Plan

1.  **Static Dry Run**: Verify sheet compilation using the `test_convert.py` script.
2.  **Formula Verification**: Programmatically open the generated `.xlsx` file and assert that:
    *   The formula in Column U, V, W, X, Y, Z, AA, AB, AC references the correct relative cells.
    *   Raw data cells are written as formulas linking back to individual SFT sheets.
    *   The Defined Names exist in the workbook and point to the correct column ranges.
    *   The `"ReadMe - Capital Gains"` worksheet is correctly populated with plain-English definitions and styling.

