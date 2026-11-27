"""Turns live session key levels and day-by-day PDH/PDL into a separate page (levels.html)."""

from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

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

.ref-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin-bottom:18px}
.ref-item{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.ref-k{display:block;color:var(--faint);font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.ref-v{display:block;font-size:16px;font-weight:700;margin:2px 0 1px}
.ref-d{display:block;font-size:12px}
.stretched{color:var(--gold);font-weight:600}

.day-cards{display:flex;flex-direction:column;gap:14px}
.day-card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.day-card.today{border-left:3px solid var(--event)}
.day-card.pdh-card{border-left:3px solid var(--gold)}
.day-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;
  padding-bottom:10px;border-bottom:1px solid var(--line)}
.day-title{font-weight:700;font-size:16px}
.day-meta{color:var(--muted);font-size:13px;display:flex;gap:14px;flex-wrap:wrap;align-items:baseline}
.badge{display:inline-block;font-size:11px;font-weight:600;padding:1px 6px;border-radius:4px;
  margin-left:6px;border:1px solid var(--line);color:var(--muted);vertical-align:1px}
.badge.live{color:var(--event);border-color:color-mix(in srgb,var(--event) 55%,transparent);
  background:color-mix(in srgb,var(--event) 12%,var(--panel))}
.badge.pdh{color:var(--gold);border-color:color-mix(in srgb,var(--gold) 55%,transparent);
  background:color-mix(in srgb,var(--gold) 10%,var(--panel))}

.sess-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:12px}
.sbox{background:var(--panel-2);border:1px solid var(--line);border-radius:5px;padding:10px 12px}
.sbox-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
.sbox-name{font-weight:700;font-size:13px}
.sbox-time{color:var(--faint);font-size:11.5px}
.sbox.asia .sbox-name{color:var(--gold)}
.sbox.london .sbox-name{color:var(--us30)}
.sbox.ny .sbox-name{color:var(--event)}
.lvl-row{display:flex;justify-content:space-between;align-items:baseline;gap:8px;padding:4px 0;font-size:13px}
.lvl-row + .lvl-row{border-top:1px solid color-mix(in srgb,var(--line) 70%,transparent)}
.lvl-lbl{color:var(--muted)}
.lvl-val{font-weight:700}
.lvl-sub{display:block;font-size:11.5px;color:var(--faint);text-align:right;font-weight:400}

.rangebar-wrap{margin-top:12px;display:flex;align-items:center;gap:10px;font-size:11.5px;color:var(--faint)}
.rangebar{position:relative;flex:1;height:10px;background:var(--bg);border-radius:5px;border:1px solid var(--line)}
.rseg{position:absolute;top:1px;bottom:1px;border-radius:3px;opacity:.75}
.rseg.asia{background:var(--gold)}
.rseg.london{background:var(--us30)}
.rseg.ny{background:var(--event)}
.rpin{position:absolute;top:-3px;bottom:-3px;width:3px;border-radius:2px;background:var(--text);transform:translateX(-1px)}

@media (max-width:1020px){.sess-grid{grid-template-columns:repeat(2,1fr)}}
@media (max-width:560px){.sess-grid{grid-template-columns:1fr}}
"""

JS = """
(function(){
  function activate(key, updateHash){
    if (!document.getElementById("lvl-" + key)) key = "gold";
    document.querySelectorAll("[data-tab]").forEach(function(b){
      b.classList.toggle("active", b.getAttribute("data-tab") === key);
    });
    document.querySelectorAll(".lvl-pane").forEach(function(p){
      p.classList.toggle("active", p.id === "lvl-" + key);
    });
    if (updateHash && history.replaceState){
      history.replaceState(null, "", "#" + key);
    }
  }
  document.querySelectorAll("[data-tab]").forEach(function(btn){
    btn.addEventListener("click", function(){ activate(btn.getAttribute("data-tab"), true); });
  });
  function fromHash(){
    var h = (location.hash || "").replace("#", "").toLowerCase();
    if (h) activate(h, false);
  }
  window.addEventListener("hashchange", fromHash);
  fromHash();
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


def _fmt_iso(iso: str, tz) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        return _t(dt, tz)
    except Exception:
        return ""


def _level_line(key: str, label: str, val: float | None, time_iso: str, last: float | None, tz) -> str:
    if val is None:
        return (
            f'<div class="lvl-row"><span class="lvl-lbl">{escape(label)}</span>'
            f'<span class="na">—</span></div>'
        )
    when = _fmt_iso(time_iso, tz)
    sub_bits = [b for b in (when, _dist(val, last)) if b]
    sub = f'<span class="lvl-sub">{" · ".join(sub_bits)}</span>' if sub_bits else ""
    return (
        f'<div class="lvl-row">'
        f'<span class="lvl-lbl">{escape(label)}</span>'
        f'<span><span class="lvl-val">{_num(key, val)}</span>{sub}</span>'
        f'</div>'
    )


def _range_bar(key: str, row: dict, last: float | None) -> str:
    hi, lo = row.get("high"), row.get("low")
    if hi is None or lo is None or hi <= lo:
        return ""
    span = hi - lo

    def seg(cls: str, title: str, sh: float | None, sl: float | None) -> str:
        if sh is None or sl is None or sh < sl:
            return ""
        left = max(0.0, min(100.0, (sl - lo) / span * 100.0))
        width = max(2.0, min(100.0 - left, (sh - sl) / span * 100.0))
        return f'<span class="rseg {cls}" style="left:{left:.1f}%;width:{width:.1f}%" title="{escape(title)}"></span>'

    segs = "".join([
        seg("asia", "Asia range", row.get("asia_h"), row.get("asia_l")),
        seg("london", "London range", row.get("london_h"), row.get("london_l")),
        seg("ny", "New York range", row.get("ny_h"), row.get("ny_l")),
    ])
    pin = ""
    if last is not None and lo <= last <= hi:
        pos = (last - lo) / span * 100.0
        pin = f'<span class="rpin" style="left:{pos:.1f}%" title="Last {_num(key, last)}"></span>'
    return (
        f'<div class="rangebar-wrap">'
        f'<span>{_num(key, lo)}</span>'
        f'<div class="rangebar">{segs}{pin}</div>'
        f'<span>{_num(key, hi)}</span>'
        f'</div>'
    )


def _session_window(day_str: str, tzname: str, oh: int, om: int, ch: int, cm: int,
                    local_tz, prev_day_open: bool = False) -> str:
    try:
        d = date.fromisoformat(day_str)
    except Exception:
        return ""
    tz = ZoneInfo(tzname)
    od = (d - timedelta(days=1)) if prev_day_open else d
    o = datetime(od.year, od.month, od.day, oh, om, tzinfo=tz)
    c = datetime(d.year, d.month, d.day, ch, cm, tzinfo=tz)
    return f"{_t(o, local_tz)}–{_t(c, local_tz)}"


def _day_card(key: str, row: dict, last: float | None, tz, is_pdh: bool = False) -> str:
    is_today = bool(row.get("is_today"))
    card_cls = "day-card today" if is_today else ("day-card pdh-card" if is_pdh else "day-card")
    badge = (
        '<span class="badge live">Today (Live)</span>' if is_today
        else '<span class="badge pdh">PDH / PDL</span>' if is_pdh else ""
    )

    chg = row.get("chg_pct")
    chg_cls = "up" if (chg or 0) > 0.005 else "down" if (chg or 0) < -0.005 else "na"
    chg_txt = f'<span class="{chg_cls}">{chg:+.2f}%</span>' if chg is not None else "—"
    rng_txt = f'{row["range_pct"]:.2f}%' if row.get("range_pct") is not None else "—"

    hi, lo = row.get("high"), row.get("low")
    if last is None or hi is None or lo is None:
        vs_now = ""
    elif last > hi:
        vs_now = '<span class="up">Above high</span>'
    elif last < lo:
        vs_now = '<span class="down">Below low</span>'
    else:
        vs_now = '<span class="na">Inside range</span>'

    full_hi_lbl = "PDH" if is_pdh else "Day High"
    full_lo_lbl = "PDL" if is_pdh else "Day Low"
    close_lbl = "Last" if is_today else "Close"
    day_str = row.get("date", "")
    full_win = _session_window(day_str, "America/New_York", 18, 0, 17, 0, tz, prev_day_open=True)
    asia_win = _session_window(day_str, "Asia/Tokyo", 9, 0, 15, 0, tz)
    lon_win = _session_window(day_str, "Europe/London", 8, 0, 16, 30, tz)
    ny_win = _session_window(day_str, "America/New_York", 8, 0, 17, 0, tz)

    boxes = "".join([
        f'<div class="sbox">'
        f'<div class="sbox-head"><span class="sbox-name">Full Day</span><span class="sbox-time">{escape(full_win)}</span></div>'
        f'{_level_line(key, full_hi_lbl, hi, row.get("high_t", ""), last, tz)}'
        f'{_level_line(key, full_lo_lbl, lo, row.get("low_t", ""), last, tz)}'
        f'</div>',
        f'<div class="sbox asia">'
        f'<div class="sbox-head"><span class="sbox-name">Asia (Tokyo)</span><span class="sbox-time">{escape(asia_win)}</span></div>'
        f'{_level_line(key, "High", row.get("asia_h"), row.get("asia_h_t", ""), last, tz)}'
        f'{_level_line(key, "Low", row.get("asia_l"), row.get("asia_l_t", ""), last, tz)}'
        f'</div>',
        f'<div class="sbox london">'
        f'<div class="sbox-head"><span class="sbox-name">London Session</span><span class="sbox-time">{escape(lon_win)}</span></div>'
        f'{_level_line(key, "High", row.get("london_h"), row.get("london_h_t", ""), last, tz)}'
        f'{_level_line(key, "Low", row.get("london_l"), row.get("london_l_t", ""), last, tz)}'
        f'</div>',
        f'<div class="sbox ny">'
        f'<div class="sbox-head"><span class="sbox-name">New York Session</span><span class="sbox-time">{escape(ny_win)}</span></div>'
        f'{_level_line(key, "High", row.get("ny_h"), row.get("ny_h_t", ""), last, tz)}'
        f'{_level_line(key, "Low", row.get("ny_l"), row.get("ny_l_t", ""), last, tz)}'
        f'</div>',
    ])

    title = row.get("full_label") or row.get("label") or row.get("date", "")
    return f"""
<article class="{card_cls}">
  <div class="day-head">
    <div class="day-title">{escape(title)}{badge}</div>
    <div class="day-meta">
      <span>Open <b>{_num(key, row.get("open"))}</b></span>
      <span>{close_lbl} <b>{_num(key, row.get("close"))}</b> ({chg_txt})</span>
      <span>Range <b>{rng_txt}</b></span>
      {vs_now}
    </div>
  </div>
  <div class="sess-grid">{boxes}</div>
  {_range_bar(key, row, last)}
</article>"""


def _ref_card(label: str, val_txt: str, sub_html: str) -> str:
    return (
        f'<div class="ref-item">'
        f'<span class="ref-k">{escape(label)}</span>'
        f'<span class="ref-v">{val_txt}</span>'
        f'<span class="ref-d">{sub_html}</span>'
        f'</div>'
    )


def _asset_pane(key: str, snap: dict, tz) -> str:
    last = snap.get("last")
    sl = snap.get("session_levels") or {}
    ru = snap.get("range_used")
    rng_val = f"{ru:.2f}× 5d avg" if ru is not None else "—"
    rng_sub = '<span class="stretched">Stretched</span>' if (ru is not None and ru >= 1.5) else '<span class="na">vs 5-day avg</span>'

    strip = f"""<div class="ref-strip">
  {_ref_card("Last Price", _num(key, last) if last is not None else "n/a", '<span class="na">~10m delayed</span>')}
  {_ref_card("PDH (Prev High)", _num(key, sl.get("pdh")), _dist(sl.get("pdh"), last))}
  {_ref_card("PDL (Prev Low)", _num(key, sl.get("pdl")), _dist(sl.get("pdl"), last))}
  {_ref_card("PDC (Prev Close)", _num(key, sl.get("pdc")), _dist(sl.get("pdc"), last))}
  {_ref_card("5-Day High", _num(key, sl.get("week_h")), _dist(sl.get("week_h"), last))}
  {_ref_card("5-Day Low", _num(key, sl.get("week_l")), _dist(sl.get("week_l"), last))}
  {_ref_card("Today Range", rng_val, rng_sub)}
</div>"""

    cards = []
    today = snap.get("today_levels")
    if today:
        cards.append(_day_card(key, today, last, tz, is_pdh=False))
    for idx, row in enumerate(snap.get("levels_5d") or []):
        cards.append(_day_card(key, row, last, tz, is_pdh=(idx == 0)))

    if not cards:
        return strip + '<div class="panel"><p class="empty">Not enough intraday bars yet to build session levels.</p></div>'
    return strip + f'<div class="day-cards">{"".join(cards)}</div>'


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
        panes.append(f'<div class="lvl-pane{active}" id="lvl-{key}">{_asset_pane(key, snap, tz)}</div>')

    today_str = now.astimezone(tz).strftime("%Y-%m-%d")
    asia_sub = _session_window(today_str, "Asia/Tokyo", 9, 0, 15, 0, tz)
    lon_sub = _session_window(today_str, "Europe/London", 8, 0, 16, 30, tz)
    ny_sub = _session_window(today_str, "America/New_York", 8, 0, 17, 0, tz)

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
  <h2 id="lvl-main-h">Day-by-day session key levels</h2>
  <p class="sub">Each trading day's Full Day (PDH/PDL), Asia ({escape(asia_sub)}), London ({escape(lon_sub)}), and New York ({escape(ny_sub)}) highs and lows in your time zone, with the exact time each level was set. Bar colors: gold = Asia, blue = London, purple = New York, white pin = current price.</p>
  <div class="tabs" role="tablist">{''.join(tabs)}</div>
  {''.join(panes)}
</section>

<footer>
  <p>Session levels use futures bars (GC=F, YM=F, NQ=F) and lag ~10 minutes. Compare exact entry prices against your broker chart.</p>
</footer>
</div>
<script>{JS}</script>
</body></html>"""
