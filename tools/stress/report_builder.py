"""
Written by Aqib-Al-Mohiuddin
Written as part of a Research Assistant project at Swinburne University of Technology, Sarawak.

Turns a run's CSVs into a self-contained HTML report (charts are inline
SVG - no chart library, no internet needed to view it), and optionally
an Excel workbook if pandas is installed.

Input:  the run directory (metrics_*.csv, api_load_*.csv, latency_*.csv,
        system_info.json, summary.json)
Output: report.html (+ report.xlsx when possible)
"""

import csv
import datetime
import json
import os


# ---- tiny SVG line chart, no dependencies ----

def line_chart(series, title, y_label="", w=760, h=220):
    """
    series: {label: [values]} - each becomes one colored line.
    Gaps (None) are skipped. X axis is sample index (seconds).
    """
    palette = ["#1976d2", "#c62828", "#2e7d32", "#ef6c00", "#5e35b1", "#00838f"]
    all_vals = [v for vals in series.values() for v in vals if v is not None]
    if not all_vals:
        return f"<p><i>no data for {title}</i></p>"
    lo, hi = min(all_vals), max(all_vals)
    if hi == lo:
        hi = lo + 1
    pad_l, pad_b, pad_t = 55, 24, 14
    n = max(len(v) for v in series.values())

    def X(i):  return pad_l + (i / max(n - 1, 1)) * (w - pad_l - 10)
    def Y(v):  return pad_t + (1 - (v - lo) / (hi - lo)) * (h - pad_t - pad_b)

    parts = [f'<svg viewBox="0 0 {w} {h}" style="width:100%;background:#fff">',
             f'<text x="{pad_l}" y="12" font-size="13" font-weight="700">{title}</text>']
    for gy in range(5):   # y grid + labels
        v = lo + (hi - lo) * gy / 4
        y = Y(v)
        parts.append(f'<line x1="{pad_l}" y1="{y:.0f}" x2="{w-10}" '
                     f'y2="{y:.0f}" stroke="#eee"/>')
        parts.append(f'<text x="{pad_l-6}" y="{y+4:.0f}" font-size="10" '
                     f'text-anchor="end" fill="#888">{v:.0f}</text>')
    for i, (label, vals) in enumerate(series.items()):
        color = palette[i % len(palette)]
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}"
                       for i, v in enumerate(vals) if v is not None)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                     f'stroke-width="1.8"/>')
        parts.append(f'<text x="{w-10}" y="{pad_t+12+i*13}" font-size="11" '
                     f'text-anchor="end" fill="{color}">{label}</text>')
    parts.append(f'<text x="{pad_l}" y="{h-6}" font-size="10" fill="#888">'
                 f'{y_label} over time (samples = seconds)</text></svg>')
    return "".join(parts)


def read_csv_columns(path):
    """{column: [values]} from a CSV (None for empty cells)."""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    cols = {}
    for key in (rows[0].keys() if rows else []):
        vals = []
        for r in rows:
            try:
                vals.append(float(r[key]) if r[key] != "" else None)
            except (ValueError, KeyError):
                vals.append(None)
        cols[key] = vals
    return cols


def build_report(run_dir):
    info = json.load(open(os.path.join(run_dir, "system_info.json")))
    summaries = json.load(open(os.path.join(run_dir, "summary.json")))

    html = [f"""<html><head><meta charset="utf-8"><title>RiverGuard stress report</title>
<style>body{{font-family:system-ui;margin:24px;color:#1c2b36;max-width:860px}}
h1{{color:#14324f}} table{{border-collapse:collapse;font-size:13px;margin:8px 0 20px}}
td,th{{border:1px solid #dde;padding:4px 10px;text-align:left}} .abort{{color:#c62828;font-weight:700}}
pre{{background:#f6f8fa;padding:10px;font-size:12px}}</style></head><body>
<h1>RiverGuard stress test report</h1>
<p>Run: {os.path.basename(run_dir)} &middot; {datetime.datetime.now().strftime('%d %b %Y %H:%M')}</p>"""]

    if summaries.get("abort_reason"):
        html.append(f'<p class="abort">RUN ABORTED: {summaries["abort_reason"]}</p>')

    # device info table
    html.append("<h2>Test environment</h2><table>")
    for k, v in info.items():
        html.append(f"<tr><th>{k}</th><td>{v}</td></tr>")
    html.append("</table>")

    # per-scenario sections
    for name, s in summaries.get("scenarios", {}).items():
        html.append(f"<h2>Scenario {name}</h2><pre>{json.dumps(s, indent=2)}</pre>")

    # charts from every metrics csv
    html.append("<h2>Resource usage over time</h2>")
    for fname in sorted(os.listdir(run_dir)):
        if fname.startswith("metrics_") and fname.endswith(".csv"):
            cols = read_csv_columns(os.path.join(run_dir, fname))
            rss = {k.replace("_rss_mb", ""): v for k, v in cols.items()
                   if k.endswith("_rss_mb")}
            thr = {k.replace("_threads", ""): v for k, v in cols.items()
                   if k.endswith("_threads")}
            html.append(f"<h3>{fname}</h3>")
            html.append(line_chart(rss, "Memory (MB)"))
            html.append(line_chart(thr, "Threads"))
    html.append("</body></html>")

    out = os.path.join(run_dir, "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write("".join(html))

    # optional Excel
    try:
        import pandas as pd
        xlsx = os.path.join(run_dir, "report.xlsx")
        with pd.ExcelWriter(xlsx, engine="openpyxl") as xl:
            for fname in sorted(os.listdir(run_dir)):
                if fname.endswith(".csv"):
                    pd.read_csv(os.path.join(run_dir, fname)).to_excel(
                        xl, sheet_name=fname[:28].replace(".csv", ""))
        print(f"[report] also wrote {xlsx}")
    except ImportError:
        print("[report] pandas not installed - skipped Excel output")
    return out