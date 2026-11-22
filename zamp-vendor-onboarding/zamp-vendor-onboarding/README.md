# Vendor Onboarding Agent – Zamp case study (PS-2)

A runnable process that takes a new vendor's registration form + documents (GST certificate, cancelled cheque, PAN card),
checks them the way a procurement analyst would, decides **Approved / Pending / Rejected**, and drafts the right email.

**Live app:** https://zamp-vendor-app-249bpvmgxnnw6n7feiqnqk.streamlit.app/  
**Demo video (5 min):** https://www.loom.com/share/318712848cf74a8788119919fb8210eb

## Run it locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
Optional – turn on AI (document reading + email drafting with Claude):
create `.streamlit/secrets.toml` with `ANTHROPIC_API_KEY = "..."` (never commit it). Without a key the app runs in
rules-only mode: every check still runs, documents are read with text extraction and emails come from templates.

To regenerate the sample data: `python scripts/make_test_data.py`

## The process (8 stages)
| # | Stage | How | Example catch |
|---|---|---|---|
| 1 | Intake & completeness | rules | missing PAN card |
| 2 | Format validation | GSTIN check-digit (mod-36), PAN / IFSC structure, email domain | GSTIN typo, gmail address |
| 3 | Read documents | **AI** reads each PDF, says what it *actually* is and extracts fields · fallback: pdfplumber + regex | PAN card uploaded in the GST slot |
| 4 | Cross-check | PAN inside GSTIN, GSTIN state code vs declared state, fuzzy name match (rapidfuzz) form ↔ certificate ↔ cheque | GSTIN of another company, cheque in a third party's name |
| 5 | Risk check | compare with vendor master | bank account already belongs to another vendor |
| 6 | Decision | severity ladder (below) | — |
| 7 | Communication | **AI** drafts email · fallback: templates | — |
| 8 | Audit log | SQLite, full evidence per run | — |

**Severity → decision:** any `blocker` → **Rejected** (internal alert + neutral note to vendor) · any `fixable`/`review` → **Pending** (vendor gets a list of exactly what to fix) · otherwise **Approved**.

## Test scenarios
| ID | Scenario | Expected | Why |
|---|---|---|---|
| SUB-001 | Clean submission (names written differently: "Pvt Ltd" vs "PRIVATE LIMITED") | Approved | fuzzy match handles formatting |
| SUB-002 | Cheque is in the name of "R K Enterprises" | Pending | must pay the vendor's own account – vendor can fix |
| SUB-003 | GSTIN belongs to a different PAN/company, state mismatch, gmail | Rejected | identity doesn't hold together |
| SUB-004 | PAN card uploaded in the GST certificate slot | Pending | wrong file – vendor can fix |
| SUB-005 | Bank account already registered to existing vendor V-1001 | Rejected + alert | classic payment-diversion pattern |

## Design decisions
1. **AI only where rules can't do it** – reading varied documents and writing human emails. Every approve/reject decision is a deterministic rule: explainable, repeatable, auditable.
2. **Fail safe** – if the AI or any check fails, the run falls back or escalates to human review. It never auto-approves on an error.
3. **Don't tip off fraud** – rejected vendors get a neutral message; the evidence goes to the internal controls team only.
4. **Typo ≠ fraud** – a form GSTIN that fails the checksum while the certificate's GSTIN is valid is treated as a typo (Pending), not a different entity (Rejected).
5. **Everything logged** – each run stores inputs, what was read from each document, every finding and the drafted messages.

## What I'd add in production
Live GSTIN/PAN verification via the GST portal or a KYC API, penny-drop bank account verification, OCR for scanned
images, ERP write-back (SAP/Oracle vendor master) on approval, an email inbox listener for vendor replies that re-runs the
process automatically, and reviewer sign-off for every Rejected case.
