#!/usr/bin/env python3
"""Generate a stylish index.html for ControlTower report pages.

Per-page card includes:
- short title
- summary
- key metrics (domain-specific when possible)
- last update
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import html
import json
import re

ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def find_meta(html_text: str, name: str) -> str:
    patterns = [
        rf'<meta[^>]*name=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']+)["\'][^>]*>',
        rf'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']{re.escape(name)}["\'][^>]*>',
    ]
    for pattern in patterns:
        m = re.search(pattern, html_text, flags=re.IGNORECASE)
        if m:
            return clean(m.group(1))
    return ""


def first_tag_text(html_text: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return clean(re.sub(r"<[^>]+>", "", m.group(1)))


def parse_metrics(raw: str) -> list[str]:
    if not raw:
        return []
    parts = [clean(p) for p in re.split(r"[,;|]", raw)]
    return [p for p in parts if p][:6]


def short_title(filename: str) -> str:
    stem = Path(filename).stem.replace("-", " ").replace("_", " ").strip()
    return stem.title() if stem else filename


def infer_topic(filename: str) -> str:
    key = filename.lower()
    if "moto" in key:
        return "Moto"
    if "enel" in key:
        return "Enel"
    if "paypal" in key:
        return "PayPal"
    if "skiathos" in key or "sjyathos" in key:
        return "Trip"
    return "Report"


def topic_slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "report"


def eur(amount: float | int | None) -> str:
    if amount is None:
        return "—"
    return f"€{float(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def extract_json_array(html_text: str, var_name: str) -> list[dict]:
    m = re.search(rf"const\s+{re.escape(var_name)}\s*=\s*(\[.*?\]);", html_text, flags=re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def extract_json_object(html_text: str, var_name: str, stop_token: str | None = None) -> dict:
    if stop_token:
        m = re.search(
            rf"const\s+{re.escape(var_name)}\s*=\s*(\{{.*?\}});\s*{re.escape(stop_token)}",
            html_text,
            flags=re.DOTALL,
        )
    else:
        m = re.search(rf"const\s+{re.escape(var_name)}\s*=\s*(\{{.*?\}});", html_text, flags=re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def metrics_for_enel(html_text: str) -> list[str]:
    bills = extract_json_array(html_text, "bills")
    if not bills:
        return ["Latest bill: n/a"]

    def key(b: dict) -> str:
        return str(b.get("date") or "")

    latest = max(bills, key=key)
    amount = latest.get("amount")
    due = latest.get("due_date") or "n/a"
    supply = latest.get("supply_name") or latest.get("bill_type") or "n/a"
    return [
        f"Last bill: {eur(amount)}",
        f"Due: {due}",
        f"Supply: {supply}",
    ]


def metrics_for_moto(html_text: str) -> list[str]:
    tels = re.findall(r'href="tel:([^"]+)"', html_text, flags=re.IGNORECASE)
    cleaned = [t.strip() for t in tels if t.strip()]
    non_emergency = [n for n in cleaned if n not in {"112", "118"}]
    m1 = non_emergency[0] if len(non_emergency) > 0 else (cleaned[0] if cleaned else "n/a")
    m2 = non_emergency[1] if len(non_emergency) > 1 else "112"
    return [
        f"Roadside: {m1}",
        f"Backup: {m2}",
        "Emergency: 112",
    ]


def metrics_for_paypal(html_text: str) -> list[str]:
    data = extract_json_object(html_text, "DATA", stop_token="const rows")
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return ["Last transaction: n/a"]

    def dt(row: dict) -> str:
        return str(row.get("transaction_date") or row.get("email_date") or "")

    latest = max(rows, key=dt)
    amount = latest.get("amount")
    ccy = latest.get("currency") or "EUR"
    cp = str(latest.get("counterparty") or "Unknown").strip()
    kind = str(latest.get("kind") or "txn")
    date = (str(latest.get("transaction_date") or latest.get("email_date") or "")[:10]) or "n/a"
    amount_txt = f"{eur(amount)} {ccy}" if amount is not None else f"n/a {ccy}"
    return [
        f"Last txn: {amount_txt}",
        f"To/From: {cp}",
        f"Date: {date} · {kind}",
    ]


def metrics_for_trip(html_text: str) -> list[str]:
    m = re.search(r"TOTALE STIMATO.*?([0-9][0-9\.,\s]+€|€\s*[0-9][0-9\.,\s]+)", html_text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        total = clean(m.group(1))
        return [f"Estimated total: {total}", "Skiathos + Skopelos", "Family plan"]
    return ["Skiathos + Skopelos", "Family plan ready"]


def domain_metrics(topic: str, html_text: str) -> list[str]:
    if topic == "Enel":
        return metrics_for_enel(html_text)
    if topic == "Moto":
        return metrics_for_moto(html_text)
    if topic == "PayPal":
        return metrics_for_paypal(html_text)
    if topic == "Trip":
        return metrics_for_trip(html_text)
    return []


def card_info(path: Path) -> dict:
    html_text = path.read_text(encoding="utf-8", errors="ignore")

    topic = infer_topic(path.name)
    title = find_meta(html_text, "ct-title") or first_tag_text(html_text, "title") or short_title(path.name)
    summary = find_meta(html_text, "ct-summary") or first_tag_text(html_text, "h1") or "Open full report"

    metrics = parse_metrics(find_meta(html_text, "ct-metrics"))
    if not metrics:
        metrics = domain_metrics(topic, html_text)
    if not metrics:
        metrics = ["Open full report"]

    return {
        "file": path.name,
        "topic": topic,
        "topic_slug": topic_slug(topic),
        "title": clean(title)[:90],
        "summary": clean(summary)[:170],
        "metrics": metrics[:6],
        "updated": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
    }


def build_html(cards: list[dict]) -> str:
    cards_html = []
    for c in cards:
        metrics_html = "".join(f'<span class="metric">{esc(m)}</span>' for m in c["metrics"])
        cards_html.append(
            f"""
      <a class=\"card topic-{esc(c['topic_slug'])}\" href=\"./{esc(c['file'])}\">
        <div class=\"card-top\">
          <span class=\"topic topic-{esc(c['topic_slug'])}\">{esc(c['topic'])}</span>
          <span class=\"updated\">Updated: {esc(c['updated'])}</span>
        </div>
        <h3>{esc(c['title'])}</h3>
        <p>{esc(c['summary'])}</p>
        <div class=\"metrics\">{metrics_html}</div>
        <div class=\"open\">Open full page →</div>
      </a>
            """.rstrip()
        )

    grid = "\n".join(cards_html) if cards_html else "<p class=\"muted\">No report pages yet. Add <code>*.html</code> files in this folder.</p>"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Control Tower — Reports Index</title>
  <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap\" rel=\"stylesheet\"> 
  <style>
    :root {{
      --bg: #090b10;
      --text: #f4f7ff;
      --muted: #a6b0c5;
      --line: rgba(255,255,255,.11);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 26px;
      min-height: 100vh;
      font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background:
        radial-gradient(900px 600px at -10% -10%, rgba(122,141,255,.22), transparent 45%),
        radial-gradient(850px 500px at 110% -20%, rgba(86,211,255,.17), transparent 48%),
        var(--bg);
      color: var(--text);
    }}
    .shell {{ max-width: 1200px; margin: 0 auto; }}
    .hero {{ margin-bottom: 18px; }}
    h1 {{ margin: 0; font-size: clamp(1.5rem, 2.4vw, 2.1rem); letter-spacing: -0.02em; }}
    .sub {{ margin-top: 8px; color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; margin-top: 16px; }}

    .card {{
      --topic: #7a8dff;
      display: block;
      text-decoration: none;
      color: inherit;
      border: 1px solid var(--line);
      border-left: 4px solid var(--topic);
      border-radius: 16px;
      padding: 14px;
      background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.015));
      backdrop-filter: blur(2px);
      transition: transform .14s ease, border-color .14s ease, box-shadow .14s ease;
    }}
    .card:hover {{ transform: translateY(-2px); border-color: color-mix(in srgb, var(--topic) 65%, white 10%); box-shadow: 0 10px 25px rgba(0,0,0,.28); }}

    .topic-enel {{ --topic: #47d16a; }}
    .topic-moto {{ --topic: #5aa8ff; }}
    .topic-paypal {{ --topic: #3d8bff; }}
    .topic-trip {{ --topic: #ffb347; }}
    .topic-report {{ --topic: #b58cff; }}

    .card-top {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; }}
    .topic {{
      display: inline-flex;
      align-items: center;
      padding: 3px 9px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--topic) 22%, transparent);
      border: 1px solid color-mix(in srgb, var(--topic) 56%, white 8%);
      color: #eef2ff;
      font-size: .72rem;
      font-weight: 600;
      letter-spacing: .01em;
    }}
    .updated {{ color: var(--muted); font-size: .74rem; }}
    .card h3 {{ margin: 10px 0 8px; font-size: 1.03rem; line-height: 1.3; letter-spacing: -0.01em; }}
    .card p {{ margin: 0 0 11px; color: #c6d0e6; min-height: 2.7em; font-size: .92rem; }}
    .metrics {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 11px; }}
    .metric {{
      font-size: .76rem;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,.2);
      background: rgba(255,255,255,.04);
      color: #e8ecff;
      white-space: nowrap;
    }}
    .open {{ font-size: .88rem; font-weight: 600; color: #d7ddff; }}
    .muted {{ color: var(--muted); }}
    code {{ background: rgba(255,255,255,.12); padding: 0 .35rem; border-radius: 6px; }}
  </style>
</head>
<body>
  <main class=\"shell\">
    <section class=\"hero\">
      <h1>Control Tower</h1>
      <div class=\"sub\">All generated reports in one place • Updated {generated}</div>
    </section>
    <section class=\"grid\">{grid}
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    pages = sorted([p for p in ROOT.glob("*.html") if p.name.lower() != "index.html"])
    cards = [card_info(p) for p in pages]
    INDEX_FILE.write_text(build_html(cards), encoding="utf-8")
    print(f"index.html regenerated with {len(cards)} page(s).")


if __name__ == "__main__":
    main()
