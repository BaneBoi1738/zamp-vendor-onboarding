"""Vendor onboarding process: 8 stages, run in order, each producing findings.

Severity ladder (drives the decision):
  blocker  -> identity/fraud problem. Vendor is REJECTED and an internal alert is raised.
  fixable  -> something the vendor can correct (typo, wrong file, missing doc). Vendor is PENDING
              and gets an email listing exactly what to fix.
  review   -> not wrong, but a human should glance at it (e.g. free email domain). PENDING.
  pass     -> check passed (shown in the run view so the reviewer sees what WAS checked).

Decision rule (deterministic, no AI): any blocker -> Rejected; else any fixable/review -> Pending; else Approved.
"""
import csv, json, os, re, time, uuid
from datetime import datetime

from rapidfuzz import fuzz

from . import validators as v
from .ai import extract_document, draft_message, ai_available

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

REQUIRED_FIELDS = ["legal_name", "gstin", "pan", "address", "state", "contact_email",
                   "bank_account_holder", "bank_account", "ifsc"]
REQUIRED_DOCS = {"gst_certificate": "GST registration certificate",
                 "bank_proof": "cancelled cheque or bank letter",
                 "pan_card": "PAN card"}

DOC_LABELS = {"gst_certificate": "GST certificate", "bank_proof": "bank proof / cheque", "pan_card": "PAN card", "other": "unrecognised document"}

NAME_MATCH = 90   # >= this: same entity
NAME_REVIEW = 75  # between REVIEW and MATCH: probably same, ask a human


def F(severity, message, vendor_ask=None, check=None):
    return {"severity": severity, "message": message, "vendor_ask": vendor_ask, "check": check}


def normalise_name(n: str) -> str:
    n = (n or "").upper()
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    for a, b in [(r"\bPRIVATE\b", "PVT"), (r"\bLIMITED\b", "LTD"), (r"\bCOMPANY\b", "CO"),
                 (r"\bAND\b", "&"), (r"\bM S\b", "")]:
        n = re.sub(a, b, n)
    return re.sub(r"\s+", " ", n).strip()


def name_score(a, b) -> int:
    return int(fuzz.token_sort_ratio(normalise_name(a), normalise_name(b)))


def load_master():
    with open(os.path.join(DATA, "vendor_master.csv")) as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ stages
def stage_completeness(sub, ctx):
    out = []
    for k in REQUIRED_FIELDS:
        if not str(sub.get(k) or "").strip():
            out.append(F("fixable", f"Missing field: {k}", f"Please provide your {k.replace('_', ' ')}.", "completeness"))
    docs = sub.get("documents") or {}
    for slot, label in REQUIRED_DOCS.items():
        p = docs.get(slot)
        if not p or not os.path.exists(_doc_path(p)):
            out.append(F("fixable", f"Missing document: {label}", f"Please upload your {label}.", "completeness"))
    if not out:
        out.append(F("pass", f"All {len(REQUIRED_FIELDS)} fields and {len(REQUIRED_DOCS)} documents present", check="completeness"))
    return out


def stage_format(sub, ctx):
    out = []
    checks = [("GSTIN", v.check_gstin, sub.get("gstin")), ("PAN", v.check_pan, sub.get("pan")),
              ("IFSC", v.check_ifsc, sub.get("ifsc"))]
    for label, fn, val in checks:
        if not val:
            continue
        ok, why = fn(val)
        out.append(F("pass", f"{label} {val}: {why}", check="format") if ok else
                   F("fixable", f"{label} {val} is invalid: {why}", f"Please re-check your {label} ({val}) – it doesn't pass validation.", "format"))
    ok, why = v.check_email(sub.get("contact_email") or "")
    if not ok:
        out.append(F("fixable", f"Contact email invalid: {why}", "Please share a valid contact email.", "format"))
    elif "free" in why.lower():
        out.append(F("review", f"Contact email {sub['contact_email']} uses a free email domain, not a company domain", check="format"))
    else:
        out.append(F("pass", f"Contact email: {why}", check="format"))
    acct = re.sub(r"\s", "", sub.get("bank_account") or "")
    if acct and not re.fullmatch(r"\d{9,18}", acct):
        out.append(F("fixable", f"Bank account number '{acct}' should be 9–18 digits", "Please re-check your bank account number.", "format"))
    return out


def stage_read_documents(sub, ctx):
    out, extracted = [], {}
    for slot, label in REQUIRED_DOCS.items():
        p = (sub.get("documents") or {}).get(slot)
        if not p or not os.path.exists(_doc_path(p)):
            continue
        d = extract_document(_doc_path(p), slot)
        extracted[slot] = d
        if d.get("doc_type") != slot:
            actual = DOC_LABELS.get(d.get("doc_type"), "different document")
            out.append(F("fixable", f"The file uploaded as '{label}' is actually a {actual}",
                         f"The file you uploaded as your {label} looks like a {actual}. Please upload the correct {label}.",
                         "doc_type"))
        else:
            out.append(F("pass", f"{label}: read via {d['method']}", check="doc_type"))
        if d.get("method") == "ai" and d.get("red_flag") is True:
            # AI returns a structured yes/no flag; we never keyword-match its free text
            # ("no signs of tampering" would otherwise trip a 'tamper' keyword).
            out.append(F("review", f"AI flagged {label}: {d.get('notes') or 'possible issue'}", check="doc_ai_flag"))
    ctx["extracted"] = extracted
    ctx["ai_methods"] = sorted({d["method"] for d in extracted.values()})
    return out


def stage_cross_check(sub, ctx):
    out, ex = [], ctx.get("extracted", {})
    name = sub.get("legal_name")
    gst = ex.get("gst_certificate") if ex.get("gst_certificate", {}).get("doc_type") == "gst_certificate" else None
    bank = ex.get("bank_proof") if ex.get("bank_proof", {}).get("doc_type") == "bank_proof" else None
    pan = ex.get("pan_card") if ex.get("pan_card", {}).get("doc_type") == "pan_card" else None

    # 1. PAN embedded in GSTIN must equal declared PAN (pure rule, strongest identity signal)
    if sub.get("gstin") and sub.get("pan"):
        if v.pan_from_gstin(sub["gstin"]) == sub["pan"].upper():
            out.append(F("pass", "PAN embedded in GSTIN matches declared PAN", check="pan_in_gstin"))
        else:
            out.append(F("blocker", f"GSTIN {sub['gstin']} belongs to PAN {v.pan_from_gstin(sub['gstin'])}, but declared PAN is {sub['pan']} – the GSTIN and PAN are of different entities", check="pan_in_gstin"))

    # 2. GSTIN state code vs declared state
    st = v.state_from_gstin(sub.get("gstin") or "")
    if st and sub.get("state"):
        if st.lower() == sub["state"].strip().lower():
            out.append(F("pass", f"GSTIN state code ({st}) matches declared state", check="state"))
        else:
            out.append(F("fixable", f"GSTIN is registered in {st} but declared state is {sub['state']}",
                         f"Your GSTIN is registered in {st}, but the form says {sub['state']}. Please confirm the state, or share the GSTIN for your {sub['state']} registration.", "state"))

    # 3. GST certificate vs form
    if gst:
        if gst.get("gstin") and gst["gstin"].upper() != (sub.get("gstin") or "").upper():
            form_ok = v.check_gstin(sub.get("gstin") or "")[0]
            doc_ok = v.check_gstin(gst["gstin"])[0]
            if doc_ok and not form_ok:
                # form value fails checksum, certificate value is valid -> vendor typo, not a different entity
                out.append(F("fixable", f"GSTIN on form ({sub.get('gstin')}) looks like a typo – certificate shows {gst['gstin']}",
                             f"The GSTIN on your form ({sub.get('gstin')}) doesn't match your GST certificate ({gst['gstin']}). Please confirm the correct GSTIN.", "gst_doc"))
            else:
                out.append(F("blocker", f"GSTIN on certificate ({gst['gstin']}) differs from GSTIN on form ({sub.get('gstin')})", check="gst_doc"))
        elif gst.get("gstin"):
            out.append(F("pass", "GSTIN on certificate matches form", check="gst_doc"))
        if gst.get("legal_name"):
            s = name_score(name, gst["legal_name"])
            if s >= NAME_MATCH:
                out.append(F("pass", f"Legal name matches GST certificate ('{gst['legal_name']}', score {s})", check="name_gst"))
            elif s >= NAME_REVIEW:
                out.append(F("review", f"Legal name is close but not exact vs GST certificate ('{gst['legal_name']}', score {s})", check="name_gst"))
            else:
                out.append(F("blocker", f"GST certificate is for a different business: '{gst['legal_name']}' vs declared '{name}' (score {s})", check="name_gst"))

    # 4. PAN card vs form
    if pan:
        if pan.get("pan") and pan["pan"].upper() != (sub.get("pan") or "").upper():
            out.append(F("fixable", f"PAN on card ({pan['pan']}) differs from PAN on form ({sub.get('pan')})",
                         "The PAN on your PAN card doesn't match the PAN on the form. Please correct it.", "pan_doc"))
        elif pan.get("pan"):
            out.append(F("pass", "PAN on card matches form", check="pan_doc"))

    # 5. Bank proof vs form – account must be in the vendor's own name
    if bank:
        acct_doc = re.sub(r"\s", "", bank.get("account_number") or "")
        if acct_doc and acct_doc != re.sub(r"\s", "", sub.get("bank_account") or ""):
            out.append(F("fixable", f"Account number on cheque ({acct_doc}) differs from form ({sub.get('bank_account')})",
                         "The account number on your cancelled cheque doesn't match the form. Please correct it.", "bank_doc"))
        if bank.get("ifsc") and bank["ifsc"].upper() != (sub.get("ifsc") or "").upper():
            out.append(F("fixable", f"IFSC on cheque ({bank['ifsc']}) differs from form ({sub.get('ifsc')})",
                         "The IFSC on your cancelled cheque doesn't match the form. Please correct it.", "bank_doc"))
        if bank.get("account_holder"):
            s = name_score(name, bank["account_holder"])
            if s >= NAME_MATCH:
                out.append(F("pass", f"Bank account holder matches vendor ('{bank['account_holder']}', score {s})", check="name_bank"))
            else:
                out.append(F("fixable", f"Bank account is held by '{bank['account_holder']}', not '{name}' (score {s}) – payments must go to the vendor's own account",
                             f"The cancelled cheque is in the name of {bank['account_holder']}. We can only pay into an account held by {name}. Please share a cancelled cheque or bank letter for an account in the company's name.", "name_bank"))
    return out


def stage_risk(sub, ctx):
    """Compare against existing vendor master: duplicate bank account / GSTIN / PAN."""
    out, master = [], load_master()
    acct, ifsc = re.sub(r"\s", "", sub.get("bank_account") or ""), (sub.get("ifsc") or "").upper()
    gstin, pan = (sub.get("gstin") or "").upper(), (sub.get("pan") or "").upper()
    hit = False
    for m in master:
        same_entity = name_score(m["legal_name"], sub.get("legal_name")) >= NAME_MATCH
        if m["bank_account"] == acct and m["ifsc"].upper() == ifsc and not same_entity:
            out.append(F("blocker", f"Bank account {acct} ({ifsc}) is already registered to existing vendor {m['vendor_id']} – {m['legal_name']} ({m['status']}). Possible payment-diversion fraud.", check="dup_bank")); hit = True
        if m["gstin"].upper() == gstin:
            out.append(F("blocker" if not same_entity else "review",
                         f"GSTIN already exists in vendor master as {m['vendor_id']} – {m['legal_name']}" + ("" if not same_entity else " (likely duplicate registration)"), check="dup_gstin")); hit = True
        elif m["pan"].upper() == pan and not same_entity:
            out.append(F("review", f"PAN already used by {m['vendor_id']} – {m['legal_name']} (could be a group entity)", check="dup_pan")); hit = True
    if not hit:
        out.append(F("pass", f"No duplicate bank account, GSTIN or PAN across {len(master)} existing vendors", check="dup"))
    return out


def decide(findings):
    sev = [f["severity"] for f in findings]
    if "blocker" in sev:
        return "Rejected"
    if "fixable" in sev or "review" in sev:
        return "Pending"
    return "Approved"


def stage_communicate(sub, ctx):
    d, findings = ctx["decision"], ctx["findings"]
    msgs = []
    if d == "Approved":
        msgs.append(draft_message("vendor_welcome", sub, findings))
    elif d == "Pending":
        msgs.append(draft_message("vendor_request", sub, findings))
    else:
        msgs.append(draft_message("internal_alert", sub, findings))
        msgs.append(draft_message("vendor_decline", sub, findings))
    ctx["messages"] = msgs
    return [F("pass", f"Drafted: {m['subject']}  →  {m['to']}  [{m['method']}]", check="message") for m in msgs]


STAGES = [
    ("intake", "1. Intake & completeness", stage_completeness),
    ("format", "2. Format validation (GSTIN / PAN / IFSC / email)", stage_format),
    ("documents", "3. Read documents", stage_read_documents),
    ("cross_check", "4. Cross-check form vs documents", stage_cross_check),
    ("risk", "5. Risk & duplicate check vs vendor master", stage_risk),
    ("decision", "6. Decision", None),
    ("communicate", "7. Draft communication", stage_communicate),
    ("record", "8. Record in audit log", None),
]


def run(sub: dict):
    """Generator: yields ('stage', key, label, findings, ms) per stage, then ('done', result).
    The UI consumes it to render each stage live; the CLI just drains it."""
    from . import store
    run_id = "RUN-" + uuid.uuid4().hex[:8].upper()
    t0 = time.time()
    ctx = {"findings": []}
    stage_log = []
    for key, label, fn in STAGES:
        ts = time.time()
        if key == "decision":
            ctx["decision"] = decide(ctx["findings"])
            fs = [F("pass", f"Decision: {ctx['decision']} "
                    f"({sum(f['severity']=='blocker' for f in ctx['findings'])} blocker, "
                    f"{sum(f['severity']=='fixable' for f in ctx['findings'])} fixable, "
                    f"{sum(f['severity']=='review' for f in ctx['findings'])} review)", check="decision")]
        elif key == "record":
            fs = [F("pass", f"Saved as {run_id}", check="record")]
        else:
            try:
                fs = [f for f in fn(sub, ctx) if f]
            except Exception as e:  # one broken check must not kill the run – escalate to a human
                fs = [F("review", f"Check crashed: {type(e).__name__}: {e} – needs manual review", check=key)]
            if key != "communicate":
                ctx["findings"].extend(fs)
        ms = int((time.time() - ts) * 1000)
        stage_log.append({"key": key, "label": label, "findings": fs, "ms": ms})
        yield ("stage", key, label, fs, ms)

    result = {
        "run_id": run_id, "submission_id": sub.get("submission_id"), "vendor": sub.get("legal_name"),
        "scenario": sub.get("scenario"), "expected": sub.get("expected"),
        "decision": ctx["decision"], "started_at": datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
        "duration_ms": sum(x["ms"] for x in stage_log),  # processing time only (excludes UI demo pauses)
        "ai_mode": "AI" if ai_available() else "Rules only (no API key)",
        "doc_methods": ctx.get("ai_methods", []),
        "findings": ctx["findings"], "stages": stage_log, "messages": ctx.get("messages", []),
        "extracted": ctx.get("extracted", {}), "submission": sub,
    }
    store.save(result)
    yield ("done", result)


def run_all(sub):
    for ev in run(sub):
        if ev[0] == "done":
            return ev[1]


def _doc_path(p):
    return p if os.path.isabs(p) else os.path.join(DATA, p)


def load_samples():
    d = os.path.join(DATA, "submissions")
    return [json.load(open(os.path.join(d, f))) for f in sorted(os.listdir(d)) if f.endswith(".json")]
