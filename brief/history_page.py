"""Turns the 180-day release archive into a separate page (history.html)."""

from html import escape

from .dashboard import CSS as BASE_CSS, _t

EXTRA_CSS = """
.nav{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.nav a{padding:4px 11px;border-radius:5px;font-size:13px;font-weight:600;text-decoration:none;
  border:1px solid var(--line);color:var(--muted);background:var(--panel)}
.nav a:hover{color:var(--text)}
.nav a.active{background:var(--panel-2);color:var(--text);border-color:var(--event)}

.tbl-wrap{overflow-x:auto}
table.hist{width:100%;border-collapse:collapse;font-size:13.5px;min-width:680px}
table.hist th{color:var(--faint);font-weight:500;text-align:right;padding:0 8px 8px;font-size:12px;white-space:nowrap}
table.hist th:first-child,table.hist th.left{text-align:left;padding-left:0}
table.hist td{padding:9px 8px;border-top:1px solid var(--line);text-align:right;vertical-align:top;white-space:nowrap}
table.hist td:first-child,table.hist td.left{text-align:left;padding-left:0}
table.hist td.wrap-txt{white-space:normal;min-width:190px}

.badge{display:inline-block;font-size:11px;font-weight:600;padding:1px 6px;border-radius:4px;
  margin-left:6px;border:1px solid var(--line);color:var(--muted);vertical-align:1px}
.badge.rev{color:var(--event);border-color:color-mix(in srgb,var(--event) 50%,transparent);margin-left:4px}
.badge.disc{color:var(--gold);border-color:color-mix(in srgb,var(--gold) 50%,transparent);margin-left:0;margin-top:3px}
.subline{display:block;color:var(--faint);font-size:12px;margin-top:2px}
.eff{font-weight:600}

.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.pill{background:var(--panel);color:var(--muted);border:1px solid var(--line);border-radius:999px;
  padding:4px 11px;font-size:12.5px;font-family:inherit;cursor:pointer}
.pill.active{background:var(--panel-2);color:var(--text);border-color:var(--event)}
.search{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:5px;
  padding:5px 10px;font-size:13px;font-family:inherit;min-width:190px;margin-left:auto}
.chk{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:12.5px;cursor:pointer}
.summary-bar{background:var(--panel-2);border:1px solid var(--line);border-radius:6px;
  padding:9px 14px;margin-bottom:12px;font-size:13px;color:var(--muted)}
.summary-bar b{color:var(--text)}
tr.hidden-row{display:none}
@media (max-width:720px){.search{margin-left:0;width:100%}}
"""

JS = """
(function(){
  var cat = "all";
  var searchEl = document.getElementById("rel-search");
  var highEl = document.getElementById("rel-high");
  var summaryEl = document.getElementById("rel-summary");
  var emptyEl = document.getElementById("rel-empty-filter");
  var rows = Array.prototype.slice.call(document.querySelectorAll("#rel-tbody tr"));

  function matchCat(title, c){
    if (c === "all") return true;
    var t = title.toLowerCase();
    if (c === "cpi") return t.indexOf("cpi") !== -1;
    if (c === "nfp") return (t.indexOf("non-farm") !== -1 && t.indexOf("adp") === -1) || t.indexOf("unemployment rate") !== -1 || t.indexOf("average hourly earnings") !== -1;
    if (c === "pce") return t.indexOf("pce") !== -1;
    if (c === "fomc") return t.indexOf("fomc") !== -1 || t.indexOf("federal funds") !== -1 || t.indexOf("powell") !== -1;
    if (c === "ppi") return t.indexOf("ppi") !== -1;
    if (c === "gdp") return t.indexOf("gdp") !== -1;
    if (c === "retail") return t.indexOf("retail sales") !== -1;
    if (c === "claims") return t.indexOf("claims") !== -1 || t.indexOf("adp") !== -1 || t.indexOf("jolts") !== -1;
    return true;
  }

  function avgStr(arr){
    if (!arr.length) return "n/a";
    var s = arr.reduce(function(a,b){ return a + b; }, 0) / arr.length;
    return (s >= 0 ? "+" : "") + s.toFixed(2) + "%";
  }

  function applyFilters(){
    var q = (searchEl ? searchEl.value : "").trim().toLowerCase();
    var highOnly = highEl ? highEl.checked : false;
    var shown = 0;
    var hawkG = [], hawkU = [], hawkN = [], doveG = [], doveU = [], doveN = [];

    rows.forEach(function(tr){
      var title = tr.getAttribute("data-title") || "";
      var imp = tr.getAttribute("data-impact") || "";
      var ok = matchCat(title, cat) && (!highOnly || imp === "High") && (!q || title.toLowerCase().indexOf(q) !== -1);
      tr.classList.toggle("hidden-row", !ok);
      if (ok){
        shown += 1;
        var h = parseFloat(tr.getAttribute("data-hawk"));
        var g = parseFloat(tr.getAttribute("data-g"));
        var u = parseFloat(tr.getAttribute("data-u"));
        var n = parseFloat(tr.getAttribute("data-n"));
        if (!isNaN(h) && h >= 0.3){
          if (!isNaN(g)) hawkG.push(g);
          if (!isNaN(u)) hawkU.push(u);
          if (!isNaN(n)) hawkN.push(n);
        } else if (!isNaN(h) && h <= -0.3){
          if (!isNaN(g)) doveG.push(g);
          if (!isNaN(u)) doveU.push(u);
          if (!isNaN(n)) doveN.push(n);
        }
      }
    });

    if (emptyEl) emptyEl.style.display = (rows.length && shown === 0) ? "block" : "none";
    if (summaryEl){
      if (!rows.length){
        summaryEl.style.display = "none";
      } else {
        summaryEl.style.display = "block";
        var parts = ["<b>" + shown + "</b> release" + (shown === 1 ? "" : "s")];
        if (hawkG.length || hawkU.length || hawkN.length){
          parts.push("Hawkish avg: Gold " + avgStr(hawkG) + ", US30 " + avgStr(hawkU) + ", US100 " + avgStr(hawkN));
        }
        if (doveG.length || doveU.length || doveN.length){
          parts.push("Dovish avg: Gold " + avgStr(doveG) + ", US30 " + avgStr(doveU) + ", US100 " + avgStr(doveN));
        }
        summaryEl.innerHTML = parts.join(" &nbsp;·&nbsp; ");
      }
    }
  }

  document.querySelectorAll("[data-cat]").forEach(function(btn){
    btn.addEventListener("click", function(){
      cat = btn.getAttribute("data-cat");
      document.querySelectorAll("[data-cat]").forEach(function(b){ b.classList.toggle("active", b === btn); });
      applyFilters();
    });
  });
  if (searchEl) searchEl.addEventListener("input", applyFilters);
  if (highEl) highEl.addEventListener("change", applyFilters);
  applyFilters();
})();
"""


def _effect_cell(pct_15m: float | None, pct_1h: float | None) -> str:
    if pct_15m is None:
        if pct_1h is None:
            return '<td class="na">—</td>'
        cls = "up" if pct_1h >= 0.15 else "down" if pct_1h <= -0.15 else "na"
        return f'<td><span class="eff {cls}">1h {pct_1h:+.2f}%</span></td>'

    if pct_15m >= 0.15:
        lbl, cls = f"Bullish ▲ {pct_15m:+.2f}%", "up"
    elif pct_15m <= -0.15:
        lbl, cls = f"Bearish ▼ {pct_15m:+.2f}%", "down"
    else:
        lbl, cls = f"Flat {pct_15m:+.2f}%", "na"

    sub = ""
    if pct_1h is not None:
        reversed_move = (pct_15m >= 0.20 and pct_1h < 0) or (pct_15m <= -0.20 and pct_1h > 0)
        rev_badge = '<span class="badge rev">Reversed</span>' if reversed_move else ""
        sub = f'<span class="subline">1h: {pct_1h:+.2f}%{rev_badge}</span>'
    return f'<td><span class="eff {cls}">{lbl}</span>{sub}</td>'


def _releases_section(brief: dict, tz) -> str:
    entries = [r for r in reversed(brief.get("release_log") or []) if not r.get("lead_only")]
    cats = (
        ("all", "All"), ("cpi", "CPI"), ("nfp", "NFP"), ("pce", "PCE"),
        ("fomc", "FOMC"), ("ppi", "PPI"), ("gdp", "GDP"), ("retail", "Retail"), ("claims", "Claims / Jobs"),
    )
    pills = "".join(
        f'<button type="button" class="pill{" active" if k == "all" else ""}" data-cat="{k}">{lbl}</button>'
        for k, lbl in cats
    )

    if not entries:
        table_html = ('<p class="empty">No archived releases yet. Scored US releases will accumulate here '
                      'automatically with forecast, actual, and market effects (retained for 180 days).</p>')
    else:
        rows = []
        for r in entries:
            hawk = r.get("hawk")
            tone = ""
            if hawk is not None:
                tone = "tone-bear" if hawk >= 0.3 else "tone-bull" if hawk <= -0.3 else "tone-flat"
            actual = escape(r.get("actual") or "—")
            forecast = escape(r.get("forecast") or "—")
            previous = escape(r.get("previous") or "—")
            verdict = escape(r.get("verdict") or "—")
            impact = r.get("impact") or "High"
            imp_cls = "imp" if impact == "High" else "imp med"
            disc = f'<span class="badge disc">{escape(r["discrepancy"])}</span>' if r.get("discrepancy") else ""

            g = r.get("gold_pct")
            u = r.get("us30_pct")
            n = r.get("us100_pct")
            attrs = (
                f'data-title="{escape(r.get("headline", ""))}" '
                f'data-impact="{escape(impact)}" '
                f'data-hawk="{"" if hawk is None else f"{hawk:.3f}"}" '
                f'data-g="{"" if g is None else f"{g:.3f}"}" '
                f'data-u="{"" if u is None else f"{u:.3f}"}" '
                f'data-n="{"" if n is None else f"{n:.3f}"}"'
            )
            rows.append(
                f'<tr {attrs}>'
                f'<td class="left">{_t(r["time"], tz, "%b %d")}<span class="subline">{_t(r["time"], tz)}</span></td>'
                f'<td class="left wrap-txt"><span class="rel-title"><span class="{imp_cls}" title="{escape(impact)} impact"></span>'
                f'{escape(r.get("headline", ""))}</span></td>'
                f'<td><b>{actual}</b></td>'
                f'<td>{forecast}</td>'
                f'<td>{previous}</td>'
                f'<td class="left wrap-txt"><span class="{tone}" style="font-weight:600">{verdict}</span>{disc}</td>'
                f'{_effect_cell(g, r.get("gold_1h_pct"))}'
                f'{_effect_cell(u, r.get("us30_1h_pct"))}'
                f'{_effect_cell(n, r.get("us100_1h_pct"))}'
                f'</tr>'
            )
        table_html = f"""<div class="tbl-wrap"><table class="hist" id="rel-table">
<thead><tr>
  <th class="left">Date</th><th class="left">Release</th><th>Actual</th><th>Forecast</th><th>Previous</th>
  <th class="left">Verdict</th><th>Gold</th><th>US30</th><th>US100</th>
</tr></thead>
<tbody id="rel-tbody">{''.join(rows)}</tbody>
</table></div>
<p class="empty" id="rel-empty-filter" style="display:none">No releases match this filter.</p>"""

    return f"""
<section aria-labelledby="rel-h">
  <h2 id="rel-h">Previous US data releases &amp; market effects</h2>
  <p class="sub">Initial 15-minute (30–45m for FOMC) move and 1-hour follow-through across Gold, US30 and US100. Actual numbers come from FRED where available.</p>
  <div class="controls">
    {pills}
    <label class="chk"><input type="checkbox" id="rel-high"> High impact only</label>
    <input type="search" class="search" id="rel-search" placeholder="Filter releases..." aria-label="Filter releases">
  </div>
  <div class="summary-bar" id="rel-summary" style="display:none"></div>
  <div class="panel">{table_html}</div>
</section>"""


def render(brief: dict) -> str:
    tz = brief["tz"]
    now = brief["now"]
    live_href = "index.html" if brief.get("hosted") else "dashboard.html"
    stale = bool(brief.get("problems"))

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>Market brief — Release History</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&display=swap" rel="stylesheet">
<style>{BASE_CSS}{EXTRA_CSS}</style>
</head><body><div class="wrap">

<header class="top">
  <div><span class="brand">Market <span>brief</span></span></div>
  <nav class="nav" aria-label="Views">
    <a href="{live_href}">Live Brief</a>
    <a href="levels.html">Session Levels</a>
    <a class="active" href="history.html">Release History</a>
  </nav>
  <div class="fresh">
    <span><span class="dot{' stale' if stale else ''}"></span>Updated {_t(now, tz)}</span>
    <span>{_t(now, tz, "%a, %b %d")}</span>
  </div>
</header>

{_releases_section(brief, tz)}

<footer>
  <p>Archived releases are retained for 180 days. Forecast &amp; previous values come from the Forex Factory calendar feed; official actuals come from FRED; price reactions are computed from Yahoo Finance 5-minute bars.</p>
</footer>
</div>
<script>{JS}</script>
</body></html>"""
