"""Generates the demo dataset: an existing vendor master + 5 new vendor submissions
(1 happy path, 4 edge cases) with realistic-looking PDF documents."""
import csv, json, os, random
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(DATA, "docs")
SUBS = os.path.join(DATA, "submissions")
os.makedirs(DOCS, exist_ok=True); os.makedirs(SUBS, exist_ok=True)

# ---------- PDF builders ----------
def _header(c, title, sub):
    w, h = A4
    c.setFillColor(colors.HexColor("#1f3a5f")); c.rect(0, h - 90, w, 90, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 18); c.drawString(40, h - 50, title)
    c.setFont("Helvetica", 10); c.drawString(40, h - 70, sub)
    c.setFillColor(colors.black)

def gst_certificate(path, legal_name, trade_name, gstin, address, state, reg_date):
    c = canvas.Canvas(path, pagesize=A4); w, h = A4
    _header(c, "Form GST REG-06", "Government of India  |  Registration Certificate")
    y = h - 130; c.setFont("Helvetica", 11)
    rows = [("Registration Number (GSTIN)", gstin), ("1. Legal Name", legal_name), ("2. Trade Name, if any", trade_name),
            ("3. Constitution of Business", "Private Limited Company"), ("4. Address of Principal Place of Business", address),
            ("   State", state), ("5. Date of Liability", reg_date), ("6. Period of Validity", f"From {reg_date}  To  Not Applicable"),
            ("7. Type of Registration", "Regular")]
    for k, v in rows:
        c.setFont("Helvetica-Bold", 10); c.drawString(40, y, k); c.setFont("Helvetica", 10); c.drawString(300, y, v); y -= 26
    c.setFont("Helvetica-Oblique", 9); c.drawString(40, 80, "This is a system generated digitally signed Registration Certificate. (Demo document for case study)")
    c.save()

def cancelled_cheque(path, bank, branch, holder, account, ifsc):
    c = canvas.Canvas(path, pagesize=(A4[0], 300)); w = A4[0]
    c.setStrokeColor(colors.HexColor("#4a6fa5")); c.setLineWidth(2); c.rect(20, 20, w - 40, 260)
    c.setFont("Helvetica-Bold", 16); c.drawString(40, 245, bank)
    c.setFont("Helvetica", 9); c.drawString(40, 230, f"Branch: {branch}")
    c.drawString(40, 216, f"IFSC: {ifsc}")
    c.setFont("Helvetica", 10); c.drawString(40, 180, "Pay ________________________________________________ or Bearer")
    c.drawString(40, 150, "Rupees ______________________________________________")
    c.drawString(40, 110, f"A/c No. {account}")
    c.setFont("Helvetica-Bold", 11); c.drawString(w - 280, 70, f"For {holder}")
    c.setFont("Helvetica", 9); c.drawString(w - 280, 50, "Authorised Signatory")
    c.setStrokeColor(colors.red); c.setLineWidth(4); c.line(60, 40, w - 60, 270); c.line(60, 60, w - 60, 290)
    c.setFillColor(colors.red); c.setFont("Helvetica-Bold", 28); c.drawString(w / 2 - 80, 140, "CANCELLED")
    c.save()

def pan_card(path, name, pan, date):
    c = canvas.Canvas(path, pagesize=(340, 215))
    c.setFillColor(colors.HexColor("#e8f0ff")); c.rect(0, 0, 340, 215, fill=1, stroke=0); c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11); c.drawString(15, 190, "INCOME TAX DEPARTMENT        GOVT. OF INDIA")
    c.setFont("Helvetica", 8); c.drawString(15, 160, "Permanent Account Number Card")
    c.setFont("Helvetica-Bold", 14); c.drawString(15, 140, pan)
    c.setFont("Helvetica", 8); c.drawString(15, 115, "Name"); c.setFont("Helvetica-Bold", 10); c.drawString(15, 102, name)
    c.setFont("Helvetica", 8); c.drawString(15, 80, "Date of Incorporation/Formation"); c.setFont("Helvetica-Bold", 10); c.drawString(15, 67, date)
    c.save()

# ---------- Vendor master (already-onboarded vendors) ----------
random.seed(7)
master = [
    ("V-1001", "Apex Traders Private Limited", "29AABCT3518Q1ZS", "AABCT3518Q", "912010034567890", "UTIB0000456", "Approved"),
    ("V-1002", "Bharat Freight Carriers Pvt Ltd", "07AABCB4521K1Z", "AABCB4521K", "50100223344556", "HDFC0000123", "Approved"),
    ("V-1003", "Coastal Cold Chain LLP", "27AAJFC8812M1Z", "AAJFC8812M", "123405678901", "ICIC0000789", "Approved"),
    ("V-1004", "Delta Print & Pack Pvt Ltd", "06AADCD7741N1Z", "AADCD7741N", "38221104455", "SBIN0001234", "Approved"),
    ("V-1005", "Everest IT Services Pvt Ltd", "29AAECE9910P1Z", "AAECE9910P", "1234002200331", "KKBK0000958", "Approved"),
    ("V-1006", "Fortune Office Supplies", "24AAGFF2231Q1Z", "AAGFF2231Q", "60011223344", "PUNB0123400", "Approved"),
    ("V-1007", "Ganga Industrial Gases Ltd", "09AAACG5521R1Z", "AAACG5521R", "917020045678123", "UTIB0001234", "Approved"),
    ("V-1008", "Horizon Facility Management Pvt Ltd", "36AADCH6612S1Z", "AADCH6612S", "50200087766554", "HDFC0004455", "Approved"),
    ("V-1009", "Indus Packaging Solutions", "33AAHFI7723T1Z", "AAHFI7723T", "777705551234", "ICIC0004321", "Approved"),
    ("V-1010", "Jaipur Handloom Exports Pvt Ltd", "08AADCJ8834U1Z", "AADCJ8834U", "38990011223", "SBIN0007788", "Approved"),
    ("V-1011", "Kaveri Agro Foods Pvt Ltd", "29AAECK9945V1Z", "AAECK9945V", "1234005500667", "KKBK0008001", "Approved"),
    ("V-1012", "Lotus Electricals", "19AAJFL1156W1Z", "AAJFL1156W", "60099887766", "PUNB0456700", "Approved"),
    ("V-1013", "Metro Courier Services Pvt Ltd", "07AADCM2267X1Z", "AADCM2267X", "50100998877665", "HDFC0000999", "Approved"),
    ("V-1014", "Northstar Security Services", "06AAKFN3378Y1Z", "AAKFN3378Y", "123400998877", "ICIC0000555", "Pending"),
    ("V-1015", "Orbit Software Labs Pvt Ltd", "29AAFCO4489Z1Z", "AAFCO4489Z", "1234008800112", "KKBK0000111", "Approved"),
    ("V-1016", "Pioneer Steel Traders", "27AAHFP5590A1Z", "AAHFP5590A", "917020099887766", "UTIB0002222", "Approved"),
    ("V-1017", "Quantum Lab Supplies Pvt Ltd", "36AADCQ6601B1Z", "AADCQ6601B", "50200011223344", "HDFC0007777", "Approved"),
    ("V-1018", "Royal Catering Services", "07AAJFR7712C1Z", "AAJFR7712C", "38991122334", "SBIN0005555", "Approved"),
    ("V-1019", "Sunrise Transport Co", "09AAHFS8823D1Z", "AAHFS8823D", "60022334455", "PUNB0789000", "Inactive"),
    ("V-1020", "Trident Tools & Hardware Pvt Ltd", "24AADCT9934E1Z", "AADCT9934E", "1234009900445", "KKBK0002222", "Approved"),
]
import sys; sys.path.insert(0, ROOT)
from onboarding.validators import gstin_checksum
with open(os.path.join(DATA, "vendor_master.csv"), "w", newline="") as f:
    wr = csv.writer(f); wr.writerow(["vendor_id", "legal_name", "gstin", "pan", "bank_account", "ifsc", "status"])
    for v in master:
        g = v[2] if len(v[2]) == 15 else v[2] + gstin_checksum(v[2])
        wr.writerow([v[0], v[1], g, v[3], v[4], v[5], v[6]])

# ---------- New submissions ----------
def sub(sid, title, expected, form, docs):
    for d in docs.values():
        d["fn"](os.path.join(DOCS, d["file"]), *d["args"])
    form["documents"] = {k: f"docs/{v['file']}" for k, v in docs.items()}
    with open(os.path.join(SUBS, f"{sid}.json"), "w") as f:
        json.dump({"submission_id": sid, "scenario": title, "expected": expected, **form}, f, indent=2)

# S1 — happy path (also shows fuzzy name matching: "Pvt Ltd" vs "PRIVATE LIMITED")
sub("SUB-001", "Happy path – clean submission", "Approved", {
    "legal_name": "Sharma Logistics Pvt Ltd", "gstin": "06AAKCS4821P1ZU", "pan": "AAKCS4821P",
    "address": "Plot 42, Sector 37, Gurugram", "state": "Haryana", "contact_email": "accounts@sharmalogistics.in",
    "bank_account_holder": "Sharma Logistics Pvt Ltd", "bank_account": "50200041872215", "ifsc": "HDFC0001234"},
    {"gst_certificate": {"fn": gst_certificate, "file": "SUB-001_gst.pdf", "args": ["SHARMA LOGISTICS PRIVATE LIMITED", "SHARMA LOGISTICS", "06AAKCS4821P1ZU", "Plot 42, Sector 37, Gurugram, Haryana 122001", "Haryana", "01/04/2019"]},
     "bank_proof": {"fn": cancelled_cheque, "file": "SUB-001_cheque.pdf", "args": ["HDFC BANK", "Sector 37, Gurugram", "SHARMA LOGISTICS PVT. LTD.", "50200041872215", "HDFC0001234"]},
     "pan_card": {"fn": pan_card, "file": "SUB-001_pan.pdf", "args": ["SHARMA LOGISTICS PRIVATE LIMITED", "AAKCS4821P", "12/03/2015"]}})

# S2 — edge: bank account belongs to a different entity than the vendor
sub("SUB-002", "Edge – bank account holder is a different entity", "Pending", {
    "legal_name": "Greenleaf Packaging Pvt Ltd", "gstin": "29AADCG7315K1ZC", "pan": "AADCG7315K",
    "address": "No. 18, Peenya Industrial Area, Bengaluru", "state": "Karnataka", "contact_email": "finance@greenleafpack.com",
    "bank_account_holder": "Greenleaf Packaging Pvt Ltd", "bank_account": "917020078812345", "ifsc": "UTIB0000789"},
    {"gst_certificate": {"fn": gst_certificate, "file": "SUB-002_gst.pdf", "args": ["GREENLEAF PACKAGING PRIVATE LIMITED", "GREENLEAF", "29AADCG7315K1ZC", "No. 18, Peenya Industrial Area, Bengaluru, Karnataka 560058", "Karnataka", "15/07/2020"]},
     "bank_proof": {"fn": cancelled_cheque, "file": "SUB-002_cheque.pdf", "args": ["AXIS BANK", "Peenya, Bengaluru", "R K ENTERPRISES", "917020078812345", "UTIB0000789"]},
     "pan_card": {"fn": pan_card, "file": "SUB-002_pan.pdf", "args": ["GREENLEAF PACKAGING PRIVATE LIMITED", "AADCG7315K", "02/02/2018"]}})

# S3 — edge: GSTIN belongs to a different PAN than declared + state mismatch (borrowed tax identity)
sub("SUB-003", "Edge – GSTIN doesn't belong to the declared PAN", "Rejected", {
    "legal_name": "Nova Industrial Supplies Pvt Ltd", "gstin": "07AAFCN2290R1ZV", "pan": "AAFCN9921R",
    "address": "Unit 9, Udyog Vihar Phase 4, Gurugram", "state": "Haryana", "contact_email": "nova.supplies.ind@gmail.com",
    "bank_account_holder": "Nova Industrial Supplies Pvt Ltd", "bank_account": "38990045671", "ifsc": "SBIN0003344"},
    {"gst_certificate": {"fn": gst_certificate, "file": "SUB-003_gst.pdf", "args": ["NOVA TRADELINK PRIVATE LIMITED", "NOVA TRADELINK", "07AAFCN2290R1ZV", "45 Naraina Industrial Area, New Delhi 110028", "Delhi", "10/10/2017"]},
     "bank_proof": {"fn": cancelled_cheque, "file": "SUB-003_cheque.pdf", "args": ["STATE BANK OF INDIA", "Udyog Vihar, Gurugram", "NOVA INDUSTRIAL SUPPLIES PVT LTD", "38990045671", "SBIN0003344"]},
     "pan_card": {"fn": pan_card, "file": "SUB-003_pan.pdf", "args": ["NOVA INDUSTRIAL SUPPLIES PRIVATE LIMITED", "AAFCN9921R", "20/06/2023"]}})

# S4 — edge: wrong document uploaded in the GST certificate slot (a PAN card)
pan_card(os.path.join(DOCS, "SUB-004_gst_slot_is_pan.pdf"), "MERIDIAN MEDICAL DEVICES PRIVATE LIMITED", "AAICM1180D", "05/09/2016")
sub("SUB-004", "Edge – wrong document uploaded as GST certificate", "Pending", {
    "legal_name": "Meridian Medical Devices Pvt Ltd", "gstin": "09AAICM1180D1ZN", "pan": "AAICM1180D",
    "address": "C-12, Sector 63, Noida", "state": "Uttar Pradesh", "contact_email": "vendor.ops@meridianmed.in",
    "bank_account_holder": "Meridian Medical Devices Pvt Ltd", "bank_account": "1234006677889", "ifsc": "KKBK0004567"},
    {"bank_proof": {"fn": cancelled_cheque, "file": "SUB-004_cheque.pdf", "args": ["KOTAK MAHINDRA BANK", "Sector 18, Noida", "MERIDIAN MEDICAL DEVICES PVT LTD", "1234006677889", "KKBK0004567"]},
     "pan_card": {"fn": pan_card, "file": "SUB-004_pan.pdf", "args": ["MERIDIAN MEDICAL DEVICES PRIVATE LIMITED", "AAICM1180D", "05/09/2016"]}})
s4 = json.load(open(os.path.join(SUBS, "SUB-004.json")))
s4["documents"] = {"gst_certificate": "docs/SUB-004_gst_slot_is_pan.pdf", **s4["documents"]}
json.dump(s4, open(os.path.join(SUBS, "SUB-004.json"), "w"), indent=2)

# S5 — edge: bank account already belongs to an existing approved vendor (classic payment-fraud pattern)
sub("SUB-005", "Edge – bank account already used by another vendor", "Rejected", {
    "legal_name": "Prism Office Solutions Pvt Ltd", "gstin": "24AAECP6634L1Z6", "pan": "AAECP6634L",
    "address": "301, Shivalik Plaza, Ahmedabad", "state": "Gujarat", "contact_email": "billing@prismoffice.co.in",
    "bank_account_holder": "Prism Office Solutions Pvt Ltd", "bank_account": "912010034567890", "ifsc": "UTIB0000456"},
    {"gst_certificate": {"fn": gst_certificate, "file": "SUB-005_gst.pdf", "args": ["PRISM OFFICE SOLUTIONS PRIVATE LIMITED", "PRISM OFFICE", "24AAECP6634L1Z6", "301, Shivalik Plaza, Ahmedabad, Gujarat 380015", "Gujarat", "01/08/2021"]},
     "bank_proof": {"fn": cancelled_cheque, "file": "SUB-005_cheque.pdf", "args": ["AXIS BANK", "Ashram Road, Ahmedabad", "PRISM OFFICE SOLUTIONS PVT LTD", "912010034567890", "UTIB0000456"]},
     "pan_card": {"fn": pan_card, "file": "SUB-005_pan.pdf", "args": ["PRISM OFFICE SOLUTIONS PRIVATE LIMITED", "AAECP6634L", "11/01/2021"]}})
print("done")
