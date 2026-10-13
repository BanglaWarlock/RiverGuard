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

Window semantics: ONLY complete WINDOW_HOURS windows are reported -
the trailing partial window (less than WINDOW_HOURS since the last
report) is intentionally left for the next run, so every email is a
full day of data. Empty windows send no email (state still advances
they will never contain data); a run covering complete windows with
ZERO data sends one "no data received" email - in a monitoring
system, total silence from the nodes is itself a finding. If no
complete window has elapsed yet (Task Scheduler firing early), the
run exits 0 having done nothing.
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
    """Complete WINDOW_HOURS windows in [start, end), oldest first.
    The trailing PARTIAL window is excluded on purpose: state is only
    advanced over full windows, so the remainder is picked up by the
    next scheduled run. Capped at MAX_BACKLOG_DAYS so a deleted state
    file after months of data does not flood the recipient."""
    windows = []
    cur = start
    full = datetime.timedelta(hours=WINDOW_HOURS)
    while cur + full <= end and len(windows) < MAX_BACKLOG_DAYS:
        windows.append((cur, cur + full))
        cur += full
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
    window = {"timestamp": {"$gte": start, "$lt": end}}
    # NODE telemetry only: the contract's verbatim-payload rows. The
    # telemetry collection may also hold the seeder's dense edge-quality
    # stream (param/value rows, ~100k/day) - that is analysis data,
    # not node messages; including it would flood the CSVs.
    telemetry = list(db.telemetry.find(
        {**window, "payload": {"$exists": True}}).sort("timestamp", 1))
    routes = list(db.route_reports.find(window).sort("timestamp", 1))
    blacklists = list(db.blacklists.find(window).sort("timestamp", 1))
    return telemetry, routes, blacklists


def _cell(value):
    """CSV cell: lists/dicts become JSON (readable, parseable);
    everything else as-is."""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


def to_csv(rows, fields, payload_fields=None):
    """rows -> CSV string. payload_fields: keys to flatten out of the
    payload dict (raw values, no computation)."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(fields + (payload_fields or []))
    for r in rows:
        base = [_cell(r.get(f, "")) for f in fields]
        if payload_fields:
            p = r.get("payload") or {}
            base += [_cell(p.get(k, "")) for k in payload_fields]
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
    b_csv = to_csv(blacklists,
        ["v", "sequence", "edges", "timestamp"])

    # route payloads contain nested route lists - the raw JSON column is
    # the honest form (flattening would lie about the structure)
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
    """Send one email; csvs is [(filename, content), ...]. If email is
    not configured, prints instead (the failure emails state it)."""
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
    """Connect to the database or report the failure and exit 1."""
    try:
        db = MongoClient(DB_URI, serverSelectionTimeoutMS=10000)[DB_NAME]
        db.command("ping")
        return db
    except Exception as e:
        # the alert email must never MASK the original error: if SMTP
        # is also down (same network outage), print and exit anyway
        try:
            send(f"[RiverGuard] Report FAILED - database unreachable",
                 f"The daily report could not run.\n\nError: {e}\n"
                 f"Time: {now().isoformat()} UTC\n\n"
                 f"Check: is the compose stack running? (docker ps)")
        except Exception as mail_err:
            print(f"[reporter] database down AND alert email failed: {mail_err}")
        raise SystemExit(1)

def main():
    db = connect_or_fail()

    start = read_last_reported()
    end = now()
    windows = build_windows(start, end)

    if not windows:
        # Less than a full window since the last report (Task Scheduler
        # fired early, or first run). Nothing to do - deliberately
        # silent, this is normal operation, not a failure.
        print(f"[reporter] no complete {WINDOW_HOURS}h window yet "
              f"(last report: {start.isoformat()} UTC) - nothing to do.")
        return

    truncated = (start + datetime.timedelta(days=MAX_BACKLOG_DAYS) < end
                 and len(windows) == MAX_BACKLOG_DAYS)

    sent_any = False
    try:
        for w_start, w_end in windows:
            telemetry, routes, blacklists = collect(db, w_start, w_end)
            total = len(telemetry) + len(routes) + len(blacklists)

            if total == 0:
                print(f"[reporter] window {w_start.date()}: 0 messages - no email")
                write_last_reported(w_end)
                continue

            csvs = build_csvs(telemetry, routes, blacklists)
            body = (f"RiverGuard daily report\n"
                    f"Window: {w_start.isoformat()} -> {w_end.isoformat()} UTC\n"
                    f"Messages: {len(telemetry)} telemetry, {len(routes)} route "
                    f"reports, {len(blacklists)} blacklist versions.\n")
            send(f"[RiverGuard] Report {w_start.date()} - {total} messages",
                 body, csvs)
            sent_any = True
            write_last_reported(w_end)   # advance per window - partial progress survives

        if not sent_any:
            # Heartbeat: DB up, reporter alive, complete windows existed,
            # but ZERO data in all of them. Deliberate email - nodes
            # being fully silent is a finding, not "all quiet".
            send(f"[RiverGuard] No data received "
                 f"({start.isoformat()} -> {windows[-1][1].isoformat()} UTC)",
                 f"The reporter ran normally, but no telemetry, route "
                 f"reports, or blacklist updates arrived in the window(s).\n"
                 f"Window: {start.isoformat()} -> {windows[-1][1].isoformat()} UTC\n\n"
                 f"Check: are the nodes powered and in range of the "
                 f"gateway? Is the parser receiving? (docker ps)")

        if truncated:
            send("[RiverGuard] Report backlog truncated",
                 f"More than {MAX_BACKLOG_DAYS} days of backlog existed. "
                 f"The oldest {MAX_BACKLOG_DAYS} days were reported now; "
                 f"the remainder follows over the next scheduled runs "
                 f"(state advanced to {windows[-1][1].isoformat()} UTC).")

    except SystemExit:
        raise
    except Exception as e:
        print(f"[reporter] send failed: {e}")
        print("[reporter] state not advanced past last success - "
              f"will retry next scheduled run.")
        raise SystemExit(2)   # internet/SMTP failure - distinct from DB failure's exit 1


if __name__ == "__main__":
    main()