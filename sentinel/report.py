"""Render an executive-readable HTML report with an inline SVG spend-vs-budget chart (no deps)."""
import html

COLORS = {"ACTIVE": "#1a7f37", "FROZEN": "#d1242f", "TERMINATED": "#6e7781"}


def svg_chart(sb, samples, events, w=860, h=300, pad=48):
    pts = [s for s in samples if s["id"] == sb["id"]]
    if not pts:
        return ""
    tmax = max(p["t"] for p in pts) or 1
    ymax = max(sb["budget"] * 1.15, max(p["spend"] for p in pts) * 1.05)
    X = lambda t: pad + (w - 2 * pad) * t / tmax
    Y = lambda v: h - pad - (h - 2 * pad) * v / ymax
    path = " ".join(f"{X(p['t']):.1f},{Y(p['spend']):.1f}" for p in pts)
    out = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="11">',
           f'<rect width="{w}" height="{h}" fill="#fff"/>',
           f'<line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" stroke="#999"/>',
           f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h-pad}" stroke="#999"/>',
           f'<line x1="{pad}" x2="{w-pad}" y1="{Y(sb["budget"]):.1f}" y2="{Y(sb["budget"]):.1f}" stroke="#d1242f" stroke-dasharray="6 4"/>',
           f'<text x="{w-pad}" y="{Y(sb["budget"])-5:.1f}" text-anchor="end" fill="#d1242f">budget ${sb["budget"]:.0f}</text>',
           f'<polyline fill="none" stroke="#0969da" stroke-width="2.5" points="{path}"/>']
    for n, e in enumerate([e for e in events if e["id"] == sb["id"]]):
        x = X(e["t"])
        y = Y(min((p["spend"] for p in pts if p["t"] >= e["t"]), default=0))
        col = "#d1242f" if e["kind"] in ("FREEZE", "TERMINATE") else "#bf8700"
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{pad}" y2="{h-pad}" stroke="{col}" stroke-opacity=".35"/>')
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{col}"/>')
        out.append(f'<text x="{x+6:.1f}" y="{pad+12+14*(n%5)}" fill="{col}">{html.escape(e["kind"])}</text>')
    out.append(f'<text x="{w/2}" y="{h-10}" text-anchor="middle" fill="#555">hours since sandbox creation</text>')
    out.append(f'<text x="14" y="{h/2}" transform="rotate(-90 14 {h/2})" text-anchor="middle" fill="#555">spend (USD)</text>')
    out.append("</svg>")
    return "".join(out)


def html_report(title, sandboxes, samples, events, audit_ok):
    rows, charts = [], []
    for s in sandboxes:
        d = s.to_dict()
        d["budget"] = d["budget_usd"]
        col = COLORS.get(s.state, "#333")
        rows.append(f"<tr><td>{s.id}</td><td>{html.escape(s.owner)}</td><td>${s.budget_usd:.0f}</td>"
                    f"<td>${s.spend_usd:.2f}</td><td style='color:{col};font-weight:600'>{s.state}</td>"
                    f"<td>{html.escape(s.reason)}</td></tr>")
        charts.append(f"<h3>{s.id} — {html.escape(s.owner)}</h3>{svg_chart(d, samples, events)}")
    return f"""<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:920px;margin:2rem auto;color:#1f2328}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #d0d7de;padding:6px 8px;text-align:left}}
.ok{{color:#1a7f37}}.bad{{color:#d1242f}}</style>
<h1>{html.escape(title)}</h1>
<p>Audit chain integrity: <b class="{'ok' if audit_ok else 'bad'}">{'VERIFIED' if audit_ok else 'TAMPERED'}</b></p>
<table><tr><th>Sandbox</th><th>Owner</th><th>Budget</th><th>Final spend</th><th>State</th><th>Reason</th></tr>{''.join(rows)}</table>
{''.join(charts)}"""
