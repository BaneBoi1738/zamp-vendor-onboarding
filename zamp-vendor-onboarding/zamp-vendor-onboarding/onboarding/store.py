"""Audit log: every run is saved to SQLite (one row per run, full result as JSON)."""
import json, os, sqlite3

DB = os.environ.get("ONBOARDING_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "runs.db"))


def _conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS runs(
        run_id TEXT PRIMARY KEY, submission_id TEXT, vendor TEXT, started_at TEXT, duration_ms INTEGER,
        decision TEXT, blockers INTEGER, fixable INTEGER, review INTEGER, ai_mode TEXT, result TEXT)""")
    return c


def save(r):
    sev = [f["severity"] for f in r["findings"]]
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            r["run_id"], r["submission_id"], r["vendor"], r["started_at"], r["duration_ms"], r["decision"],
            sev.count("blocker"), sev.count("fixable"), sev.count("review"), r["ai_mode"], json.dumps(r, default=str)))


def all_runs():
    with _conn() as c:
        rows = c.execute("SELECT run_id, submission_id, vendor, started_at, duration_ms, decision, blockers, fixable, review, ai_mode FROM runs ORDER BY started_at DESC").fetchall()
    cols = ["run_id", "submission_id", "vendor", "started_at", "duration_ms", "decision", "blockers", "fixable", "review", "ai_mode"]
    return [dict(zip(cols, r)) for r in rows]


def get(run_id):
    with _conn() as c:
        row = c.execute("SELECT result FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def clear():
    with _conn() as c:
        c.execute("DELETE FROM runs")
