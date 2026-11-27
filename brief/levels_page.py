"""Turns live session key levels and 5-day PDH/PDL into a separate page (levels.html)."""

from html import escape

from .dashboard import CSS as BASE_CSS, _num, _t

EXTRA_CSS = """
.nav{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.nav a{padding:4px 11px;border-radius:5px;font-size:13px;font-weight:600;text-decoration:none;
  border:1px solid var(--line);color:var(--muted);background:var(--panel)}
.nav a:hover{color:var(--text)}
.nav a.active{background:var(--panel-2);color:var(--text);border-color:var(--event)}

.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 14px}
.tab{background:var(--panel);color:var(--muted);border:1px solid var(--line);border-radius:6px;
  padding:7px 14px;font-size:13.5px;font-weight:600;font-family:inherit;cursor:pointer}
.tab span{font-weight:400;font-size:12px;color:var(--faint);margin-left:6px}
.tab.active{background:var(--panel-2);color:var(--text);border-color:var(--c,var(--event))}
.tab.gold{--c:var(--gold)} .tab.us30{--c:var(--us30)} .tab.us100{--c:var(--us100)}
.lvl-pane{display:none}
.lvl-pane.active{display:block}

.lvl-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:22px}
.lvl-panel h3{font-size:15px;font-weight:700;margin:0 0 8px}
table.kv{width:100%;border-collapse:collapse;font-size:13.5px}
table.kv td{padding:7px 0;border-top:1px solid var(--line);vertical-align:baseline}
table.kv td:nth-child(2){text-align:right;font-weight:600;padding-right:12px;white-space:nowrap}
table.kv td:last-child{text-align:right;font-size:12.5px;white-space:nowrap;width:110px}
.stretched{color:var(--gold);font-weight:600}

.tbl-wrap{overflow-x:auto}
table.hist{width:100%;border-collapse:collapse;font-size:13.5px;min-width:700px}
table.hist th{color:var(--faint);font-weight:500;text-align:right;padding:0 8px 8px;font-size:12px;white-space:nowrap}
table.hist th:first-child,table.hist th.left{text-align:left;padding-left:0}
table.hist td{padding:9px 8px;border-top:1px solid var(--line);text-align:right;vertical-align:top;white-space:nowrap}
table.hist td:first-child,table.hist td.left{text-align:left;padding-left:0}
.badge{display:inline-block;font-size:11px;font-weight:600;padding:1px 6px;border-radius:4px;
  margin-left:6px;border:1px solid var(--line);color:var(--muted);vertical-align:1px}
.badge.pdh{color:var(--gold);border-color:color-mix(in srgb,var(--gold) 55%,transparent);
  background:color-mix(in srgb,var(--gold) 10%,var(--panel))}

@media (max-width:860px){.lvl-grid{grid-template-columns:1fr}}
"""

JS = """
(function(){
  document.querySelectorAll("[data-tab]").forEach(function(btn){
    btn.addEventListener("click", function(){
      var key = btn.getAttribute("data-tab");
      document.querySelectorAll("[data-tab]").forEach(function(b){ b.classList.toggle("active", b === btn); });
      document.querySelectorAll(".lvl-pane").forEach(function(p){ p.classList.toggle("active", p.id === "lvl-" + key); });
    });
  });
})();
"""


def _dist(level: float | None, last: float | None) -> str:
    if level is None or last is None or last == 0:
        return '<span class="na">—</span>'
    pct_diff = (level - last) / last * 100.0
    if abs(pct_diff) < 0.01:
        return '<span class="na">at level</span>'
    if pct_diff > 0:
        return f'<span class="up">{pct_diff:.2f}% above</span>'
    return f'<span class="down">{abs(pct_diff):.2f}% below</span>'


def _kv_row(key: str, label: str, val: float | None, last: float | None) -> str:
    val_txt = _num(key, val) if val is not None else '<span class="na">—</span>'
    return f'<tr><td>{escape(label)}</td><td>{val_txt}</td><td>{_dist(val, last)}</td></tr>'


def _kv_pair(key: str, label: str, hi: float | None, lo: float | None) -> str:
    if hi is None or lo is None:
        return f'<tr><td>{escape(label)}</td><td class="na">—</td><td class="na"></td></tr>'
    return f'<tr><td>{escape(label)}</td><td>{_num(key, hi)} / {_num(key, lo)}</td><td class="na">H / L</td></tr>'


def _hl_pair(key: str, hi: float | None, lo: float | None) -> str:
    if hi is None or lo is None:
        return '<span class="na">—</span>'
    return f"{_num(key, hi)} / {_num(key, lo)}"


def _asset_pane(key: str, snap: dict) -> str:
    last = snap.get("last")
    sl = snap.get("session_levels") or {}
    ru = snap.get("range_used")
    if ru is not None:
        stretched = ' <span class="stretched">(stretched)</span>' if ru >= 1.5 else ""
        range_row = f'<tr><td>Daily range used</td><td>{ru:.2f}× 5d avg</td><td>{stretched or "normal"}</td></tr>'
    else:
        range_row = '<tr><td>Daily range used</td><td class="na">—</td><td class="na"></td></tr>'

    cur_rows = "".join([
        _kv_row(key, "Today's Open", sl.get("today_open"), last),
        _kv_row(key, "Today's High", sl.get("today_high"), last),
        _kv_row(key, "Today's Low", sl.get("today_low"), last),
        range_row,
        _kv_row(key, "Asia High (18–03 ET)", sl.get("asia_h"), last),
        _kv_row(key, "Asia Low (18–03 ET)", sl.get("asia_l"), last),
        _kv_row(key, "London High (03–08 ET)", sl.get("london_h"), last),
        _kv_row(key, "London Low (03–08 ET)", sl.get("london_l"), last),
        _kv_row(key, "New York High (08–17 ET)", sl.get("ny_h"), last),
        _kv_row(key, "New York Low (08–17 ET)", sl.get("ny_l"), last),
    ])

    ref_rows = "".join([
        _kv_row(key, "PDH (Previous Day High)", sl.get("pdh"), last),
        _kv_row(key, "PDL (Previous Day Low)", sl.get("pdl"), last),
        _kv_row(key, "PDC (Previous Day Close)", sl.get("pdc"), last),
        _kv_row(key, "5-Day Swing High", sl.get("week_h"), last),
        _kv_row(key, "5-Day Swing Low", sl.get("week_l"), last),
        _kv_pair(key, "Prev Asia (18–03 ET)", sl.get("prev_asia_h"), sl.get("prev_asia_l")),
        _kv_pair(key, "Prev London (03–08 ET)", sl.get("prev_london_h"), sl.get("prev_london_l")),
        _kv_pair(key, "Prev New York (08–17 ET)", sl.get("prev_ny_h"), sl.get("prev_ny_l")),
    ])

    levels = snap.get("levels_5d") or []
    if not levels:
        tbl_html = '<p class="empty">Not enough intraday bars yet to build 5 completed trading days.</p>'
    else:
        rows = []
        for idx, row in enumerate(levels):
            badge = '<span class="badge pdh">PDH / PDL</span>' if idx == 0 else ""
            rng = f'{row["range_pct"]:.2f}%' if row.get("range_pct") is not None else "—"
            if last is None:
                vs_now = '<span class="na">—</span>'
            elif last > row["high"]:
                vs_now = '<span class="up">Above high</span>'
            elif last < row["low"]:
                vs_now = '<span class="down">Below low</span>'
            else:
                vs_now = '<span class="na">Inside</span>'
            rows.append(
                f'<tr>'
                f'<td class="left">{escape(row["label"])}{badge}</td>'
                f'<td>{_num(key, row["high"])}</td>'
                f'<td>{_num(key, row["low"])}</td>'
                f'<td>{_num(key, row["close"])}</td>'
                f'<td>{rng}</td>'
                f'<td>{_hl_pair(key, row.get("asia_h"), row.get("asia_l"))}</td>'
                f'<td>{_hl_pair(key, row.get("london_h"), row.get("london_l"))}</td>'
                f'<td>{_hl_pair(key, row.get("ny_h"), row.get("ny_l"))}</td>'
                f'<td>{vs_now}</td>'
                f'</tr>'
            )
        tbl_html = f"""<div class="tbl-wrap"><table class="hist">
<thead><tr>
  <th class="left">Day</th><th>Daily High</th><th>Daily Low</th><th>Close</th><th>Range</th>
  <th>Asia (18–03 ET)</th><th>London (03–08 ET)</th><th>New York (08–17 ET)</th><th>vs Now</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table></div>"""

    return f"""
<div class="lvl-grid">
  <div class="panel lvl-panel">
    <h3>Current session levels</h3>
    <table class="kv"><tbody>{cur_rows}</tbody></table>
  </div>
  <div class="panel lvl-panel">
    <h3>Reference levels (PDH / PDL &amp; prior sessions)</h3>
    <table class="kv"><tbody>{ref_rows}</tbody></table>
  </div>
</div>
<h2>Last 5 completed trading days</h2>
<p class="sub">Aligned to the New York futures day (18:00–17:00 ET), newest first. Row 1 is yesterday's PDH / PDL.</p>
<div class="panel">{tbl_html}</div>"""


def render(brief: dict) -> str:
    tz = brief["tz"]
    now = brief["now"]
    snaps = brief.get("snaps") or {}
    syms = brief.get("symbols") or {}
    live_href = "index.html" if brief.get("hosted") else "dashboard.html"
    stale = bool(brief.get("problems"))

    assets = (("gold", "Gold"), ("us30", "US30"), ("us100", "US100"))
    tabs = []
    panes = []
    for idx, (key, name) in enumerate(assets):
        snap = snaps.get(key) or {}
        last = snap.get("last")
        last_txt = _num(key, last) if last is not None else "n/a"
        active = " active" if idx == 0 else ""
        tabs.append(
            f'<button type="button" class="tab {key}{active}" data-tab="{key}">'
            f'{escape(name)}<span>{escape(syms.get(key, ""))} · {last_txt}</span></button>'
        )
        panes.append(f'<div class="lvl-pane{active}" id="lvl-{key}">{_asset_pane(key, snap)}</div>')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>Market brief — Session Levels</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&display=swap" rel="stylesheet">
<style>{BASE_CSS}{EXTRA_CSS}</style>
</head><body><div class="wrap">

<header class="top">
  <div><span class="brand">Market <span>brief</span></span></div>
  <nav class="nav" aria-label="Views">
    <a href="{live_href}">Live Brief</a>
    <a class="active" href="levels.html">Session Levels</a>
    <a href="history.html">Release History</a>
  </nav>
  <div class="fresh">
    <span><span class="dot{' stale' if stale else ''}"></span>Updated {_t(now, tz)}</span>
    <span>{_t(now, tz, "%a, %b %d")}</span>
  </div>
</header>

<section aria-labelledby="lvl-main-h">
  <h2 id="lvl-main-h">Session key levels</h2>
  <p class="sub">Asia (18:00–03:00 ET), London (03:00–08:00 ET), New York (08:00–17:00 ET), PDH / PDL / PDC, and 5-day swing levels from Yahoo Finance 5-minute futures bars (~10 min delayed).</p>
  <div class="tabs" role="tablist">{''.join(tabs)}</div>
  {''.join(panes)}
</section>

<footer>
  <p>Session levels use futures bars (GC=F, YM=F, NQ=F) and lag ~10 minutes. Compare exact entry prices against your broker chart.</p>
</footer>
</div>
<script>{JS}</script>
</body></html>"""
