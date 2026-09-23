"""
RiverGuard reporter service - periodic email reports (Milestone 2b).

A standalone service, same pattern as parser/api. Every interval it:
  1. Queries MongoDB for everything that happened in the report window
  2. Renders an HTML report (email-safe: inline CSS, no images/scripts)
  3. ALWAYS saves it to reporter/reports/  -> demoable without any email
     setup, and an archive of what was sent (audit trail)
  4. Emails it to RECIPIENTS if SMTP is configured

Scheduling (the "flexible timestamp intervals"):
  INTERVAL_HOURS = 1    -> hourly reports
  INTERVAL_HOURS = 24   -> daily reports
  INTERVAL_HOURS = 0.05 -> every 3 minutes (quick demo - set back after!)
  DAILY_AT = "08:00"    -> daily at a fixed local time (overrides interval)

The report WINDOW is independent of the schedule: WINDOW_HOURS = how
much history each report covers.

Usage:
  python reporter.py --test            tiny SMTP sanity-check email
  python reporter.py --now --no-email  one report now, saved locally only
  python reporter.py --now             one report now, emailed too
  python reporter.py                   start the schedule loop

Windows Task Scheduler alternative to the loop (survives reboots,
nothing resident): point a Daily task at
  python reporter.py --now
with "Start in" set to this folder, and add arguments
  1>> task.log 2>&1
to keep a log of unattended runs. Do NOT run the loop and the Task
Scheduler task at the same time (double emails).
"""

import os
import sys
import signal
import threading
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pymongo import MongoClient

# ---------------------------------------------------------------------------
# CONFIG - everything you change lives in this block, nothing below it
# ---------------------------------------------------------------------------

# --- database -------------------------------------------------------------
DB_URI = "mongodb+srv://test:test@banglacluster.ntnbhcq.mongodb.net/?appName=BanglaCluster"
DB_NAME = "RiverGuard"

# --- where reports are saved ----------------------------------------------
# Always relative to this file, so it works no matter where you run from.
# (task.log from Task Scheduler lands here too.)
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")

# --- schedule & window ----------------------------------------------------
WINDOW_HOURS = 24        # how much history each report covers
INTERVAL_HOURS = 24      # schedule: every N hours (when DAILY_AT is None)
DAILY_AT = None          # e.g. "08:00" local time - overrides the schedule

# --- recipients (add as many as you like) ----------------------------------
RECIPIENTS = ["aqib.mohiuddin08@gmail.com", "102782478@students.swinburne.edu.my"]     # <-- YOUR TWO EMAILS

# --- sending account -------------------------------------------------------
# The SENDER is one of your emails. The app password is NOT your normal
# Gmail password:
#   Google Account -> Security -> 2-Step Verification (must be on) ->
#   App passwords -> create "RiverGuard" -> 16 characters, no spaces.
# If SMTP_USER is empty, emailing is disabled: reports still generate
# and save locally (that's what --no-email does internally).
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465          # SSL
SMTP_USER = "aqib.mohiuddin08@gmail.com"       # <-- sender account
SMTP_PASS = "zuhrlxowyscwrhfn"     # <-- 16-char app password, no spaces
EMAIL_FROM = "RiverGuard <aqib.mohiuddin08@gmail.com>"

# ---------------------------------------------------------------------------
# Nothing below needs changing for normal use
# ---------------------------------------------------------------------------

stop_event = threading.Event()

def signal_handler(signum, frame):
    stop_event.set()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ---------------------------------------------------------------------------
# Collect: query the database for the report window
# ---------------------------------------------------------------------------

def collect(hours):
    """Gather everything needed for one report into a plain dict."""
    db = MongoClient(DB_URI)[DB_NAME]

    now = datetime.datetime.utcnow()
    start = now - datetime.timedelta(hours=hours)
    window = {"timestamp": {"$gte": start, "$lt": now}}

    # what HAPPENED in the window
    alerts = list(db.alerts.find(window).sort("timestamp", 1))
    events = list(db.events.find(window).sort("timestamp", 1))
    telemetry_total = db.telemetry.count_documents(window)

    # what the state is RIGHT NOW (not windowed)
    villages = list(db.villages.find().sort("_id", 1))
    nodes = list(db.river_nodes.find())
    stats = db.global_stats.find_one({"_id": "global"}) or {}

    nodes_by_village = {}
    for n in nodes:
        nodes_by_village.setdefault(n.get("village_id"), []).append(n)

    # one row per village for the summary table
    village_rows = []
    for v in villages:
        vn = nodes_by_village.get(v["_id"], [])
        bats = [n.get("bat") for n in vn if n.get("bat") is not None]
        village_rows.append({
            "name": v["_id"],
            "online": bool(v.get("is_online")),
            "master": v.get("master_id") or "?",
            "nodes_total": len(vn),
            "nodes_online": sum(1 for n in vn if n.get("status") == "online"),
            "max_water": max([n.get("water_level") or 0 for n in vn], default=0),
            "min_bat": min(bats) if bats else None,
        })

    def tally(docs, key):
        out = {}
        for d in docs:
            k = d.get(key, "unknown")
            out[k] = out.get(k, 0) + 1
        return out

    return {
        "generated_at": now,
        "window_start": start,
        "window_hours": hours,
        "village_rows": village_rows,
        "alerts": alerts,
        "alert_counts": tally(alerts, "type"),
        "event_counts": tally(events, "event_type"),
        "telemetry_total": telemetry_total,
        "stats": stats,
    }

# ---------------------------------------------------------------------------
# Render: HTML (email) + plain text (fallback)
# ---------------------------------------------------------------------------

LEVEL_COLORS = {0: "#2e7d32", 1: "#f9a825", 2: "#ef6c00", 3: "#c62828"}

def render_html(d):
    """Email-safe HTML: everything inline, no external assets."""
    w = d["window_start"].strftime("%d %b %Y %H:%M") + " UTC"
    g = d["generated_at"].strftime("%d %b %Y %H:%M") + " UTC"

    # --- per-village current state table ---
  # --- per-village current state table ---
    vrows = ""
    for v in d["village_rows"]:
        bat = f"{v['min_bat']:.1f} V" if v["min_bat"] is not None else "—"
        color = LEVEL_COLORS.get(v["max_water"], "#999")

        # Built BEFORE the f-string: Pythons before 3.12 forbid backslashes
        # (and same-quote tricks) inside the {expression} part of an
        # f-string. A plain variable sidesteps that and keeps the table
        # template below easy to read.
        if v["online"]:
            status = "online"
        else:
            status = '<b style="color:#c62828">OFFLINE</b>'

        vrows += (
            f"<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #ddd'><b>{v['name']}</b></td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #ddd'>{status}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #ddd'>{v['nodes_online']}/{v['nodes_total']}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #ddd'>"
            f"<span style='color:#fff;background:{color};padding:1px 8px;border-radius:8px'>{v['max_water']} ft</span></td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #ddd'>{bat}</td>"
            f"</tr>"
        )

    # --- flood alerts in window, newest last, max 20 rows ---
    arows = ""
    flood_alerts = [a for a in d["alerts"] if a.get("type") == "flood"]
    for a in flood_alerts[-20:]:
        t = a["timestamp"].strftime("%d %b %H:%M")
        arows += (
            f"<tr><td style='padding:4px 10px'>{t}</td>"
            f"<td style='padding:4px 10px'><b>{a.get('node_id')}</b> ({a.get('village_id')})</td>"
            f"<td style='padding:4px 10px;color:#c62828'>water at {a.get('value')} ft</td></tr>"
        )
    if not arows:
        arows = "<tr><td colspan=3 style='padding:4px 10px;color:#777'>No flood alerts in this window.</td></tr>"

    ac = d["alert_counts"]
    ac_line = ", ".join(f"{k}: {v}" for k, v in sorted(ac.items())) or "none"
    ec = d["event_counts"]
    ec_line = ", ".join(f"{k}: {v}" for k, v in sorted(ec.items())) or "none"
    s = d["stats"]

    return f"""
    <div style="font-family:Arial,sans-serif;color:#222;max-width:640px">
      <div style="background:#14324f;color:#fff;padding:14px 18px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">RiverGuard Flood Monitoring Report</h2>
        <div style="opacity:.8;font-size:12px">Window: {w} &rarr; {g}</div>
      </div>

      <h3 style="margin:18px 0 6px">Village status (current)</h3>
      <table style="border-collapse:collapse;font-size:14px;width:100%">
        <tr style="color:#5b6b7b;font-size:12px;text-align:left">
          <th style="padding:6px 10px">Village</th><th style="padding:6px 10px">Master</th>
          <th style="padding:6px 10px">Nodes up</th><th style="padding:6px 10px">Max water</th>
          <th style="padding:6px 10px">Min batt.</th></tr>
        {vrows}
      </table>

      <h3 style="margin:18px 0 6px">Flood alerts in window</h3>
      <table style="border-collapse:collapse;font-size:14px;width:100%">{arows}</table>

      <h3 style="margin:18px 0 6px">Summary</h3>
      <ul style="font-size:13px;line-height:1.7">
        <li>Alerts: {ac_line}</li>
        <li>Node/master events: {ec_line}</li>
        <li>Telemetry updates stored: {d['telemetry_total']}</li>
        <li>System now: {s.get('masters_online', 0)} master(s) online,
            {s.get('river_nodes_online', 0)}/{s.get('river_nodes_online', 0) + s.get('river_nodes_offline', 0)} nodes online</li>
      </ul>

      <div style="margin-top:18px;padding-top:10px;border-top:1px solid #ddd;
                  font-size:11px;color:#888">Automated report from the RiverGuard IoT system.</div>
    </div>"""

def render_text(d):
    """Plain-text alternative (some clients/users prefer it)."""
    lines = ["RiverGuard Flood Monitoring Report",
             f"Window: {d['window_start']} -> {d['generated_at']} UTC", ""]
    for v in d["village_rows"]:
        lines.append(f"{v['name']}: {'online' if v['online'] else 'OFFLINE'}, "
                     f"{v['nodes_online']}/{v['nodes_total']} nodes, "
                     f"max water {v['max_water']} ft")
    lines.append("")
    lines.append(f"Alerts: {d['alert_counts'] or 'none'}")
    lines.append(f"Events: {d['event_counts'] or 'none'}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Save + send
# ---------------------------------------------------------------------------

def send_email(subject, html, text):
    """Send one email to all RECIPIENTS. Silently skips if not configured."""
    if not SMTP_USER:
        print("[email] SMTP not configured - report saved locally only")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, RECIPIENTS, msg.as_string())
        print(f"[email] sent to {len(RECIPIENTS)} recipient(s): {subject}")
    except Exception as e:
        print(f"[email] FAILED (report still saved locally): {e}")

def send_test_email():
    """Tiny email to verify SMTP settings before running a real report.
    If this arrives but a report doesn't, the problem is the report.
    If neither arrives, the problem is SMTP settings or the network
    (campus/work networks sometimes block port 465 - try home Wi-Fi)."""
    if not SMTP_USER:
        print("[email] set SMTP_USER/SMTP_PASS first")
        return
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, RECIPIENTS,
                "Subject: RiverGuard SMTP test\n\n"
                "If you can read this in both inboxes, email sending works.")
        print(f"[email] test sent to {len(RECIPIENTS)} recipient(s)")
    except Exception as e:
        print(f"[email] test FAILED: {e}")

def run_report(hours, email=True):
    """One report: collect -> render -> save to disk -> (optionally) email."""
    d = collect(hours)
    html, text = render_html(d), render_text(d)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    fname = os.path.join(REPORTS_DIR,
        f"report_{d['generated_at'].strftime('%Y%m%d_%H%M%S')}.html")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[report] saved {fname}")

    if email:
        floods = d["alert_counts"].get("flood", 0)
        marker = f" [FLOOD x{floods}]" if floods else ""
        subject = (f"RiverGuard report "
                   f"{d['generated_at'].strftime('%d %b %H:%M')} UTC{marker} "
                   f"({len(d['alerts'])} alerts)")
        send_email(subject, html, text)

# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def next_run_time():
    """When the next scheduled report happens (local clock)."""
    if DAILY_AT:
        hh, mm = map(int, DAILY_AT.split(":"))
        now = datetime.datetime.now()
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now:
            candidate += datetime.timedelta(days=1)
        return candidate
    return datetime.datetime.now() + datetime.timedelta(hours=INTERVAL_HOURS)

def main():
    if "--test" in sys.argv:
        send_test_email()
        return
    if "--now" in sys.argv:
        run_report(WINDOW_HOURS, email="--no-email" not in sys.argv)
        return

    print(f"[reporter] schedule: every {INTERVAL_HOURS}h"
          + (f" / daily at {DAILY_AT}" if DAILY_AT else "")
          + f", window {WINDOW_HOURS}h, reports -> {REPORTS_DIR}")
    while not stop_event.is_set():
        target = next_run_time()
        print(f"[reporter] next report at {target}")
        while not stop_event.is_set() and datetime.datetime.now() < target:
            stop_event.wait(1.0)
        if stop_event.is_set():
            break
        try:
            run_report(WINDOW_HOURS, email=True)
        except Exception as e:
            print(f"[reporter] report run failed (will retry next schedule): {e}")

    print("[reporter] shut down")

if __name__ == "__main__":
    main()