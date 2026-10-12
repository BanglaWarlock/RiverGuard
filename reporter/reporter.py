"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Daily email report: raw CSV of the last reporting window's messages.

Run as a ONE-SHOT container (Task Scheduler -> bat -> docker run --rm):
  1. Read last-reported timestamp from state/ (volume - survives runs)
  2. Query telemetry, route_reports, blacklists since then (default: 24h)
  3. Build CSVs (raw payloads, one row per message, no computation)
  4. Email them as attachments - no local files kept
  5. On ANY failure (DB unreachable etc): email the failure instead

Failure semantics: the email system is the alert channel. If the
database is down, the recipient learns it from an email, not silence.
"""

import csv
import datetime
import io
import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from pymongo import MongoClient

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)

# --- config (env, injected by compose/bat) ---
DB_URI = os.getenv("DB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "RiverGuard")
WINDOW_HOURS = int(os.getenv("WINDOW_HOURS", "24"))

# The last-reported checkpoint: state/last_report.txt next to this file.
# The container mounts reporter/state as /app/state, so local and
# container runs share the SAME state file - deliberate.
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
STATE_FILE = os.path.join(STATE_DIR, "last_report.txt")

RECIPIENTS = os.getenv("RECIPIENTS", "").split(",")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "RiverGuard <noreply@riverguard.local>")

MAX_BACKLOG_DAYS = 7



def build_windows(start, end):
    """Split [start, end) into sequential 24h windows - one email each.
    Capped at MAX_BACKLOG_DAYS so a deleted state file after months of
    data does not flood the recipient."""
    windows = []
    cur = start
    while cur < end and len(windows) < MAX_BACKLOG_DAYS:
        nxt = min(cur + datetime.timedelta(hours=WINDOW_HOURS), end)
        windows.append((cur, nxt))
        cur = nxt
    return windows

def now():
    return datetime.datetime.utcnow()


def read_last_reported():
    """Start of the reporting window: the last reported timestamp, or
    (now - WINDOW_HOURS) on first run. Stored on the state volume."""
    try:
        with open(STATE_FILE) as f:
            return datetime.datetime.fromisoformat(f.read().strip())
    except Exception:
        return now() - datetime.timedelta(hours=WINDOW_HOURS)


def write_last_reported(ts):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        f.write(ts.isoformat())


def collect(db, start, end):
    query = {"timestamp": {"$gte": start, "$lt": end}}
    telemetry = list(db.telemetry.find(query).sort("timestamp", 1))
    routes = list(db.route_reports.find(query).sort("timestamp", 1))
    blacklists = list(db.blacklists.find(query).sort("timestamp", 1))
    return telemetry, routes, blacklists


def to_csv(rows, fields, payload_fields=None):
    """rows -> CSV string. payload_fields: keys to flatten out of the
    payload dict (raw values, no computation)."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(fields + (payload_fields or []))
    for r in rows:
        base = [r.get(f, "") for f in fields]
        if payload_fields:
            p = r.get("payload") or {}
            base += [p.get(k, "") for k in payload_fields]
        ts = r.get("timestamp")
        base[fields.index("timestamp")] = ts.isoformat() if ts else ""
        w.writerow(base)
    return out.getvalue()


def build_csvs(telemetry, routes, blacklists):
    """The three attachments: raw message data, no computation."""
    t_csv = to_csv(telemetry,
        ["node_id", "timestamp"],
        ["node", "uptime_minute", "sequence", "tx_packets", "rx_packets",
         "tx_bytes", "rx_bytes", "sf"])
    r_csv = to_csv(routes,
        ["node_id", "timestamp"],
        ["s", "g"])   # routes are big; the payload JSON is the honest form
    b_csv = to_csv(blacklists,
        ["v", "sequence", "edges", "timestamp"])

    # route payloads contain nested route lists - attach the raw JSON as
    # a column so nothing is lost (raw, as specified)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["node_id", "timestamp", "raw_payload"])
    for r in routes:
        ts = r.get("timestamp")
        w.writerow([r.get("node_id", ""),
                    ts.isoformat() if ts else "",
                    json.dumps(r.get("payload"))])
    return [("telemetry.csv", t_csv),
            ("route_reports.csv", out.getvalue()),
            ("blacklists.csv", b_csv)]


def send(subject, body, csvs=None):
    """Send one email; csvs is [(filename, content), ...]. No-op-ish on
    missing config (failure emails will state it)."""
    if not SMTP_USER or not RECIPIENTS or RECIPIENTS == [""]:
        print("[reporter] email not configured - printing instead")
        print(subject); print(body)
        return

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(body, "plain"))
    for fname, content in csvs or []:
        part = MIMEApplication(content.encode("utf-8"), Name=fname)
        part["Content-Disposition"] = f'attachment; filename="{fname}"'
        msg.attach(part)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, RECIPIENTS, msg.as_string())
        
def connect_or_fail():
    """Connect to the database or send the failure email and exit 1."""
    try:
        db = MongoClient(DB_URI, serverSelectionTimeoutMS=10000)[DB_NAME]
        db.command("ping")
        return db
    except Exception as e:
        send(f"[RiverGuard] Report FAILED - database unreachable",
             f"The daily report could not run.\n\nError: {e}\n"
             f"Time: {now().isoformat()} UTC\n\n"
             f"Check: is the compose stack running? (docker ps)")
        raise SystemExit(1)

def main():
    db = connect_or_fail()

    start = read_last_reported()
    end = now()
    windows = build_windows(start, end)

    try:
        for w_start, w_end in windows:
            telemetry, routes, blacklists = collect(db, w_start, w_end)
            csvs = build_csvs(telemetry, routes, blacklists)
            body = (f"RiverGuard daily report\n"
                    f"Window: {w_start.isoformat()} -> {w_end.isoformat()} UTC\n"
                    f"Messages: {len(telemetry)} telemetry, {len(routes)} route "
                    f"reports, {len(blacklists)} blacklist versions.\n")
            send(f"[RiverGuard] Report {w_start.date()} - "
                 f"{len(telemetry)+len(routes)+len(blacklists)} messages",
                 body, csvs)
            write_last_reported(w_end)   # advance per window - partial progress survives
    except Exception as e:
        # SMTP unreachable (campus internet down, etc.) - the state is
        # NOT advanced, so the next successful run re-reports this window.
        print(f"[reporter] send failed: {e}")
        print("[reporter] state not advanced - will retry next scheduled run.")
        raise SystemExit(2)   # distinct from DB failure's exit 1

    if start + datetime.timedelta(days=MAX_BACKLOG_DAYS) < end:
        send("[RiverGuard] Report backlog truncated",
             f"More than {MAX_BACKLOG_DAYS} days of backlog existed; only the "
             f"most recent were reported. State has been advanced to now.")


if __name__ == "__main__":
    main()