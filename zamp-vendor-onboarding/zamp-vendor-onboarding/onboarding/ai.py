"""The only two places this process uses AI:
  1. Reading documents  - classify what a PDF actually is and pull out the fields.
  2. Writing messages   - draft the email back to the vendor / the internal alert.

Everything else is deterministic rules. If the AI is unavailable (no key, API error,
bad JSON) the process falls back to a rule-based reader/template so a run never dies;
the run log records that the fallback was used.
"""
import base64, json, os, re

import pdfplumber

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
DOC_TYPES = ["gst_certificate", "bank_proof", "pan_card", "other"]


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        try:  # Streamlit Cloud secrets
            import streamlit as st
            key = st.secrets.get("ANTHROPIC_API_KEY")
        except Exception:
            key = None
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


def ai_available() -> bool:
    return _client() is not None


def pdf_text(path: str) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        return ""


# ---------------------------------------------------------------- 1. documents
EXTRACT_PROMPT = """You are checking a vendor onboarding document for an Indian company's procurement team.
The vendor uploaded this file in the slot labelled "{slot}".

1. Decide what the document ACTUALLY is (ignore the slot label): one of gst_certificate, bank_proof (cancelled cheque or bank letter), pan_card, other.
2. Extract every field you can see. Use null when a field is absent. Copy values exactly as printed.

Reply with ONLY a JSON object:
{{"doc_type": "...", "confidence": 0-1,
  "legal_name": null, "trade_name": null, "gstin": null, "pan": null, "state": null, "address": null,
  "account_holder": null, "account_number": null, "ifsc": null, "bank_name": null,
  "red_flag": false,
  "notes": "one short sentence describing the document"}}

Set "red_flag" to true ONLY if you see a concrete problem: signs of editing/tampering, illegible key fields,
an expired or cancelled registration, or the document belonging to a different entity than its own fields suggest.
Routine advice (e.g. "should be verified on the portal") is NOT a red flag."""


def extract_document(path: str, slot: str) -> dict:
    """Returns extracted fields + 'method' ('ai' or 'rules') + optional 'ai_error'."""
    client = _client()
    if client:
        try:
            with open(path, "rb") as f:
                b64 = base64.standard_b64encode(f.read()).decode()
            msg = client.messages.create(
                model=MODEL, max_tokens=3000,
                messages=[{"role": "user", "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                    {"type": "text", "text": EXTRACT_PROMPT.format(slot=slot)},
                ]}],
            )
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            data["method"] = "ai"
            return data
        except Exception as e:  # graceful degradation
            out = _rules_extract(path)
            out["method"] = "rules (AI fallback)"
            out["ai_error"] = str(e)[:200]
            return out
    out = _rules_extract(path)
    out["method"] = "rules (no API key)"
    return out


def _find(pattern, text, group=1):
    m = re.search(pattern, text, re.I | re.M)
    return m.group(group).strip() if m else None


def _rules_extract(path: str) -> dict:
    """Keyword/regex reader used when AI isn't available. Works for text-based PDFs only."""
    t = pdf_text(path)
    up = t.upper()
    if "REG-06" in up or "REGISTRATION CERTIFICATE" in up:
        doc_type = "gst_certificate"
    elif "CANCELLED" in up or "A/C NO" in up or "IFSC" in up:
        doc_type = "bank_proof"
    elif "PERMANENT ACCOUNT NUMBER" in up:
        doc_type = "pan_card"
    else:
        doc_type = "other"
    d = {"doc_type": doc_type, "confidence": 0.7 if t.strip() else 0.0,
         "legal_name": None, "trade_name": None, "gstin": None, "pan": None, "state": None, "address": None,
         "account_holder": None, "account_number": None, "ifsc": None, "bank_name": None, "red_flag": False, "notes": None}
    if not t.strip():
        d["notes"] = "No machine-readable text (scanned image?) - needs AI or manual review"
        return d
    if doc_type == "gst_certificate":
        d["gstin"] = _find(r"GSTIN\)?\s*([0-9A-Z]{15})", t)
        d["legal_name"] = _find(r"Legal Name\s+(.+)", t)
        d["trade_name"] = _find(r"Trade Name, if any\s+(.+)", t)
        d["state"] = _find(r"^\s*State\s+(.+)$", t)
        d["address"] = _find(r"Place of Business\s+(.+)", t)
    elif doc_type == "bank_proof":
        lines = [l for l in t.splitlines() if l.strip()]
        d["bank_name"] = lines[0].strip() if lines else None
        d["ifsc"] = _find(r"IFSC:?\s*([A-Z]{4}0[A-Z0-9]{6})", t)
        d["account_number"] = _find(r"A/c No\.?\s*([0-9]{6,20})", t)
        d["account_holder"] = _find(r"For\s+(.+)", t)
    elif doc_type == "pan_card":
        d["pan"] = _find(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", t)
        d["legal_name"] = _find(r"^Name\s*\n(.+)$", t)
    return d


# ---------------------------------------------------------------- 2. messages
def draft_message(kind: str, vendor: dict, findings: list[dict]) -> dict:
    """kind = 'vendor_request' (pending) | 'vendor_decline' (rejected) | 'internal_alert' | 'vendor_welcome'."""
    client = _client()
    issues = "\n".join(f"- [{f['severity']}] {f['message']}" for f in findings)
    if client:
        try:
            prompt = MESSAGE_PROMPTS[kind].format(name=vendor.get("legal_name"), email=vendor.get("contact_email"), issues=issues or "none")
            msg = client.messages.create(model=MODEL, max_tokens=3000, messages=[{"role": "user", "content": prompt}])
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            data["method"] = "ai"
            return data
        except Exception as e:
            out = _template_message(kind, vendor, findings)
            out["method"] = "template (AI fallback)"; out["ai_error"] = str(e)[:200]
            return out
    out = _template_message(kind, vendor, findings)
    out["method"] = "template (no API key)"
    return out


MESSAGE_PROMPTS = {
    "vendor_request": """Write a short, friendly email from a procurement team to a new vendor, {name}, whose onboarding is ON HOLD.
List exactly what they need to fix or send, in plain language, as a numbered list, using these internal findings (do not mention severity labels or internal rules):
{issues}
Keep it under 150 words. Reply with ONLY JSON: {{"to": "{email}", "subject": "...", "body": "..."}}""",
    "vendor_decline": """Write a short, neutral email to {name} saying their vendor registration cannot be completed at this time and asking them to contact the procurement team.
IMPORTANT: do NOT reveal any fraud checks or specific reasons (the case is under internal review). Under 80 words.
Reply with ONLY JSON: {{"to": "{email}", "subject": "...", "body": "..."}}""",
    "internal_alert": """Write a concise internal alert to the Procurement & Finance Controls team about a REJECTED vendor onboarding for {name}.
Summarise the red flags below, say what was blocked, and recommend next steps (e.g. verify by phone using independently sourced contact details, do not create the vendor).
Red flags:
{issues}
Under 150 words. Reply with ONLY JSON: {{"to": "procurement-controls@company.example", "subject": "...", "body": "..."}}""",
    "vendor_welcome": """Write a 2-3 sentence welcome email to {name} confirming their vendor registration is approved and they can now submit invoices.
Reply with ONLY JSON: {{"to": "{email}", "subject": "...", "body": "..."}}""",
}


def _template_message(kind, vendor, findings):
    name, email = vendor.get("legal_name"), vendor.get("contact_email")
    if kind == "vendor_request":
        items = "\n".join(f"{i}. {f.get('vendor_ask') or f['message']}" for i, f in enumerate(
            [f for f in findings if f["severity"] in ("fixable", "review")], 1))
        return {"to": email, "subject": f"Action needed to complete your vendor registration – {name}",
                "body": f"Hi {name} team,\n\nThanks for registering as a vendor. Before we can approve your account, we need the following:\n\n{items}\n\nPlease reply to this email with the corrected details or documents and we'll re-check them the same day.\n\nRegards,\nProcurement Team"}
    if kind == "vendor_decline":
        return {"to": email, "subject": f"Your vendor registration – {name}",
                "body": f"Hi {name} team,\n\nWe're unable to complete your vendor registration at this time. Please contact our procurement team if you have any questions.\n\nRegards,\nProcurement Team"}
    if kind == "internal_alert":
        flags = "\n".join(f"- {f['message']}" for f in findings if f["severity"] == "blocker")
        return {"to": "procurement-controls@company.example", "subject": f"[BLOCKED] Vendor onboarding rejected – {name}",
                "body": f"Onboarding for {name} was automatically rejected.\n\nRed flags:\n{flags}\n\nThe vendor has NOT been created. Recommended: verify by phone using independently sourced contact details before any further action. The vendor was sent a neutral message without the reasons."}
    return {"to": email, "subject": f"Welcome aboard – {name}",
            "body": f"Hi {name} team,\n\nYour vendor registration is approved. You can now submit invoices against purchase orders.\n\nRegards,\nProcurement Team"}
