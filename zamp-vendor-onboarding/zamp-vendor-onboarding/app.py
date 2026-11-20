"""Vendor Onboarding Agent – Streamlit front end.
Run:  streamlit run app.py
"""
import json, os, time, uuid
from collections import Counter

import pandas as pd
import streamlit as st

from onboarding import pipeline, store
from onboarding.ai import ai_available, MODEL

st.set_page_config(page_title="Vendor Onboarding Agent", page_icon="🧾", layout="wide")

ICON = {"pass": "✅", "fixable": "🟠", "review": "🔵", "blocker": "⛔"}
DECISION_STYLE = {"Approved": ("success", "✅ APPROVED – vendor can be created in the ERP"),
                  "Pending": ("warning", "🟠 PENDING – email drafted to the vendor with what to fix"),
                  "Rejected": ("error", "⛔ REJECTED – vendor blocked, internal alert raised")}
UPLOADS = os.path.join(pipeline.DATA, "uploads")
CHECK_LABELS = {
    "completeness": "Missing field or document", "format": "Format issue (GSTIN / PAN / IFSC / email)",
    "doc_type": "Wrong document uploaded", "doc_ai_flag": "AI flagged a document",
    "pan_in_gstin": "GSTIN belongs to a different PAN", "state": "GSTIN state \u2260 declared state",
    "gst_doc": "GSTIN on certificate \u2260 form", "name_gst": "Name \u2260 GST certificate",
    "pan_doc": "PAN card \u2260 form", "bank_doc": "Cheque details \u2260 form",
    "name_bank": "Bank account in another name", "dup_bank": "Bank account used by another vendor",
    "dup_gstin": "GSTIN already registered", "dup_pan": "PAN already registered",
}

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("🧾 Vendor Onboarding")
    if ai_available():
        st.success(f"AI on · `{MODEL}`\n\nReads documents + drafts emails")
    else:
        st.warning("Rules-only mode (no API key)\n\nDocuments read with text extraction; emails from templates. Every check still runs.")
    demo_pace = st.toggle("Demo pace (pause between stages)", value=True,
                          help="Adds a short pause so each stage is visible in a live demo. Turn off for real speed.")
    st.caption("Severity ladder")
    st.markdown("⛔ **blocker** → Rejected + alert  \n🟠 **fixable** → Pending, vendor emailed  \n🔵 **review** → Pending, human glance  \n✅ **pass** → check passed")

tab_run, tab_dash, tab_how = st.tabs(["▶️ Run onboarding", "📊 Dashboard", "ℹ️ How it works"])


# ------------------------------------------------------------------ helpers
def _fmt_ms(ms):
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms/1000:.1f} s"


def show_findings(findings):
    for f in findings:
        st.markdown(f"{ICON.get(f['severity'], '•')} {f['message']}")


def show_result(r):
    kind, text = DECISION_STYLE[r["decision"]]
    getattr(st, kind)(f"**{text}**  ·  {r['run_id']}  ·  {_fmt_ms(r['duration_ms'])}")
    sev = Counter(f["severity"] for f in r["findings"])
    c = st.columns(4)
    c[0].metric("Checks passed", sev["pass"]); c[1].metric("Blockers", sev["blocker"])
    c[2].metric("Fixable", sev["fixable"]); c[3].metric("Needs review", sev["review"])
    st.subheader("Drafted communication")
    for m in r["messages"]:
        with st.expander(f"✉️ {m['subject']}  →  {m['to']}   ·  {m.get('method')}", expanded=True):
            st.text(m["body"])
    with st.expander("What was read from each document"):
        st.json({k: {kk: vv for kk, vv in d.items() if vv not in (None, "")} for k, d in r["extracted"].items()})


def run_live(sub):
    final = None
    for ev in pipeline.run(sub):
        if ev[0] == "stage":
            _, key, label, findings, ms = ev
            worst = "blocker" if any(f["severity"] == "blocker" for f in findings) else \
                    "fixable" if any(f["severity"] == "fixable" for f in findings) else \
                    "review" if any(f["severity"] == "review" for f in findings) else "pass"
            state = "error" if worst == "blocker" else "complete"
            with st.status(f"{ICON[worst]} {label}  ·  {ms} ms", state=state, expanded=worst != "pass"):
                show_findings(findings)
            if demo_pace:
                time.sleep(0.6)
        else:
            final = ev[1]
    return final


# ------------------------------------------------------------------ RUN TAB
with tab_run:
    samples = pipeline.load_samples()
    mode = st.radio("Submission", ["Sample submissions", "New submission (upload your own)"], horizontal=True)

    if mode == "Sample submissions":
        opts = {f"{s['submission_id']} · {s['legal_name']} — {s['scenario']}": s for s in samples}
        sub = opts[st.selectbox("Pick a vendor submission", list(opts))]
        left, right = st.columns([3, 2])
        with left:
            st.markdown("**Form data submitted by the vendor**")
            st.dataframe(pd.DataFrame([(k, sub[k]) for k in pipeline.REQUIRED_FIELDS], columns=["field", "value"]),
                         hide_index=True, use_container_width=True)
        with right:
            st.markdown("**Documents uploaded**")
            for slot, path in sub["documents"].items():
                full = pipeline._doc_path(path)
                with open(full, "rb") as fh:
                    st.download_button(f"📄 {pipeline.REQUIRED_DOCS[slot]}  ({os.path.basename(path)})", fh.read(),
                                       file_name=os.path.basename(path), key=f"dl-{sub['submission_id']}-{slot}")
            st.caption(f"Expected outcome (for testing): **{sub['expected']}**")
    else:
        with st.form("new"):
            c1, c2 = st.columns(2)
            vals = {}
            for i, k in enumerate(pipeline.REQUIRED_FIELDS):
                vals[k] = (c1 if i % 2 == 0 else c2).text_input(k.replace("_", " ").title())
            files = {slot: st.file_uploader(label.capitalize(), type=["pdf"], key=f"up-{slot}")
                     for slot, label in pipeline.REQUIRED_DOCS.items()}
            submitted = st.form_submit_button("Save submission")
        sub = st.session_state.get("custom_sub")
        if submitted:
            sid = "SUB-" + uuid.uuid4().hex[:6].upper()
            os.makedirs(os.path.join(UPLOADS, sid), exist_ok=True)
            docs = {}
            for slot, f in files.items():
                if f is not None:
                    p = os.path.join(UPLOADS, sid, f"{slot}.pdf")
                    open(p, "wb").write(f.getbuffer()); docs[slot] = p
            sub = {"submission_id": sid, "scenario": "Manual submission", "expected": None, **vals, "documents": docs}
            st.session_state["custom_sub"] = sub
            st.success(f"Saved as {sid}. Now run it.")

    if sub and st.button("▶️ Run onboarding", type="primary", use_container_width=True):
        st.divider()
        st.subheader(f"Live run · {sub['legal_name'] or sub['submission_id']}")
        r = run_live(sub)
        st.session_state["last"] = r
        st.divider()
        show_result(r)
    elif st.session_state.get("last") and sub and st.session_state["last"]["submission_id"] == sub["submission_id"]:
        st.divider(); st.caption("Last run of this submission")
        show_result(st.session_state["last"])


# ------------------------------------------------------------------ DASHBOARD TAB
with tab_dash:
    top = st.columns([1, 1, 4])
    if top[0].button("Run all 5 samples"):
        with st.spinner("Running…"):
            for s in pipeline.load_samples():
                pipeline.run_all(s)
    if top[1].button("Clear log"):
        store.clear()

    runs = store.all_runs()
    if not runs:
        st.info("No runs yet. Run a submission, or click **Run all 5 samples**.")
    else:
        df = pd.DataFrame(runs)
        n = len(df); dc = df["decision"].value_counts()
        m = st.columns(6)
        m[0].metric("Submissions processed", n)
        m[1].metric("Auto-approved", int(dc.get("Approved", 0)), f"{dc.get('Approved', 0)/n:.0%} straight-through")
        m[2].metric("Pending vendor", int(dc.get("Pending", 0)))
        m[3].metric("Rejected", int(dc.get("Rejected", 0)))
        m[4].metric("Fraud / identity blocks", int((df["blockers"] > 0).sum()))
        m[5].metric("Avg processing time", _fmt_ms(df["duration_ms"].mean()))

        full = [store.get(rid) for rid in df["run_id"]]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Decisions**")
            st.bar_chart(dc.reindex(["Approved", "Pending", "Rejected"]).fillna(0))
        with c2:
            st.markdown("**Most common issues (which checks catch problems)**")
            iss = Counter((CHECK_LABELS.get(f["check"], f["check"]), f["severity"]) for r in full for f in r["findings"] if f["severity"] != "pass")
            if iss:
                st.dataframe(pd.DataFrame([{"Issue caught": k[0], "Severity": f"{ICON[k[1]]} {k[1]}", "Times": v} for k, v in iss.most_common(10)]),
                             hide_index=True, use_container_width=True)
            else:
                st.caption("No issues found yet.")

        st.markdown("**Run history** – every run is logged for audit")
        st.dataframe(df[["run_id", "started_at", "submission_id", "vendor", "decision", "blockers", "fixable", "review", "duration_ms", "ai_mode"]],
                     hide_index=True, use_container_width=True)

        pick = st.selectbox("Open a run", df["run_id"] + " · " + df["vendor"].fillna(""))
        r = store.get(pick.split(" · ")[0])
        if r:
            for s in r["stages"]:
                with st.expander(f"{s['label']}  ·  {s['ms']} ms"):
                    show_findings(s["findings"])
            show_result(r)


# ------------------------------------------------------------------ HOW TAB
with tab_how:
    st.markdown("""
### What this does
A vendor fills a registration form and uploads 3 documents (GST certificate, cancelled cheque, PAN card).
This process checks everything a procurement analyst would check by hand, decides **Approved / Pending / Rejected**,
and drafts the right email – in seconds instead of days of back-and-forth.

### The 8 stages
| # | Stage | How | Catches |
|---|---|---|---|
| 1 | Intake & completeness | rules | missing fields / documents |
| 2 | Format validation | rules – GSTIN checksum, PAN, IFSC, email domain | typos, fake numbers |
| 3 | Read documents | **AI** (Claude reads the PDF) · fallback: text extraction | wrong file in the wrong slot |
| 4 | Cross-check | rules + fuzzy name match | GSTIN of another company, cheque in someone else's name, state mismatch |
| 5 | Risk check vs vendor master | rules | bank account already used by another vendor (payment diversion) |
| 6 | Decision | rules – severity ladder | — |
| 7 | Communication | **AI** drafts emails · fallback: templates | — |
| 8 | Audit log | SQLite | every run kept with full evidence |

### Design choices
- **AI only where rules can't do the job** – reading messy documents and writing human emails. Every pass/fail decision is a deterministic rule, so it's explainable and repeatable.
- **Fail safe, not fail silent** – if the AI is down or a check crashes, the run falls back or escalates to *review*; it never auto-approves on an error.
- **Rejected vendors are not told why** – the vendor gets a neutral note; the controls team gets the evidence. Telling a fraudster which check caught them teaches them to beat it.
- **Fixable ≠ fraud** – a GSTIN typo (fails checksum, certificate is valid) is *Pending*, not *Rejected*.
""")
