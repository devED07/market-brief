"""Turns the brief into one self-contained HTML page (dashboard.html)."""

import json
from datetime import datetime, timedelta
from html import escape

from .prices import LABELS

CSS = """
:root{
  --bg:#161D27; --panel:#1C2531; --panel-2:#222D3B; --line:#2E3A4A;
  --text:#E3E7ED; --muted:#8E99AA; --faint:#5F6B7D;
  --gold:#D1A84A; --us30:#86A9CF; --us100:#7FC4B8;
  --bull:#5BB585; --bear:#E26A5E; --flat:#A9B2BF; --event:#B793E6;
  --font:"Archivo", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text)}
body{font-family:var(--font);font-size:15px;line-height:1.5;font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased}
a{color:inherit}
a:focus-visible,button:focus-visible{outline:2px solid var(--event);outline-offset:2px}
.wrap{max-width:1180px;margin:0 auto;padding:20px 24px 48px}

/* top bar */
.top{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap;
  padding-bottom:14px;border-bottom:1px solid var(--line)}
.brand{font-weight:800;font-stretch:75%;font-size:22px;letter-spacing:.01em}
.brand span{color:var(--gold)}
.clock{color:var(--muted);font-size:14px}
.clock b{color:var(--text);font-weight:600}
.fresh{display:flex;gap:18px;color:var(--muted);font-size:13px}
.fresh .dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--bull);margin-right:6px;vertical-align:1px}
.fresh .dot.stale{background:var(--bear)}

/* banners */
.banner{margin:16px 0 0;padding:12px 16px;border-radius:6px;border:1px solid;
  display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
.banner.event{border-color:color-mix(in srgb,var(--event) 55%,transparent);
  background:color-mix(in srgb,var(--event) 12%,var(--bg))}
.banner.closed{border-color:var(--line);background:var(--panel)}
.banner.demo{border-color:color-mix(in srgb,var(--gold) 50%,transparent);background:color-mix(in srgb,var(--gold) 10%,var(--bg))}
.banner strong{font-weight:700}
.banner .count{font-weight:800;font-stretch:80%;font-size:20px;color:var(--event)}

/* bias */
.bias{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:20px}
.inst{background:var(--panel);border-radius:6px;padding:18px 20px 16px;border-top:3px solid var(--c)}
.inst.gold{--c:var(--gold)} .inst.us30{--c:var(--us30)} .inst.us100{--c:var(--us100)}
.inst-head{display:flex;justify-content:space-between;align-items:baseline}
.inst-name{font-weight:700;font-size:16px;color:var(--c)}
.inst-sym{color:var(--faint);font-size:13px}
.verdict{font-weight:800;font-stretch:68%;font-size:clamp(32px,3.5vw,44px);line-height:1;margin:14px 0 6px;letter-spacing:-.005em}
.tone-bull{color:var(--bull)} .tone-bear{color:var(--bear)} .tone-flat{color:var(--flat)}
.scoreline{display:flex;align-items:center;gap:12px;margin:12px 0 4px}
.scorenum{font-weight:700;font-size:15px;min-width:74px}
.scale{position:relative;flex:1;height:10px;background:var(--panel-2);border-radius:5px}
.scale .mid{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--faint)}
.scale .fill{position:absolute;top:0;bottom:0;border-radius:5px}
.scale .pin{position:absolute;top:-4px;width:3px;height:18px;border-radius:2px;background:var(--text);transform:translateX(-1px)}
.scale-ends{display:flex;justify-content:space-between;color:var(--faint);font-size:12px;margin-left:86px}
.agree{color:var(--muted);font-size:13px;margin:8px 0 12px}
.warn{margin:0 0 12px;padding:9px 12px;border-radius:5px;font-size:13px;line-height:1.45;
  border:1px solid color-mix(in srgb,var(--gold) 50%,transparent);background:color-mix(in srgb,var(--gold) 10%,var(--panel))}
.drivers{width:100%;border-collapse:collapse;font-size:14px}
.drivers td{padding:7px 0;border-top:1px solid var(--line);vertical-align:top}
.drivers .dn{font-weight:600;padding-right:10px}
.drivers .dd{display:block;color:var(--muted);font-weight:400;font-size:13px;line-height:1.4;margin-top:1px}
.drivers .db{width:64px;padding-top:12px}
.drivers .dp{width:44px;text-align:right;font-weight:600}
.minibar{position:relative;height:6px;background:var(--panel-2);border-radius:3px}
.minibar i{position:absolute;top:0;bottom:0;border-radius:3px}
.minibar:after{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--faint)}

/* tonight strip */
section{margin-top:28px}
h2{font-size:17px;font-weight:700;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin:0 0 12px}
.strip{background:var(--panel);border-radius:6px;padding:14px 16px 10px}
.lane{display:grid;grid-template-columns:86px 1fr;align-items:center;min-height:26px}
.lane-name{color:var(--muted);font-size:13px}
.track{position:relative;height:26px}
.track .seg{position:absolute;top:6px;height:14px;border-radius:3px;background:var(--panel-2);
  border:1px solid var(--line)}
.track .seg.us30{background:color-mix(in srgb,var(--us30) 35%,var(--panel-2));border-color:color-mix(in srgb,var(--us30) 60%,transparent)}
.track .seg.overlap{background:color-mix(in srgb,var(--gold) 30%,var(--panel-2));border-color:color-mix(in srgb,var(--gold) 55%,transparent)}
.track .rel{position:absolute;top:2px;width:3px;height:22px;border-radius:2px;background:var(--event);transform:translateX(-1px)}
.track .rel.med{opacity:.5}
.track .rel-label{position:absolute;top:4px;font-size:12px;color:var(--event);white-space:nowrap;padding-left:7px}
.axis{position:relative;height:18px;margin-left:86px;color:var(--faint);font-size:12px}
.axis span{position:absolute;transform:translateX(-50%)}
.nowline{position:absolute;top:0;bottom:0;width:2px;background:var(--text);opacity:.85}
.lanes{position:relative}
.lanes .nowwrap{position:absolute;top:0;bottom:0;left:86px;right:0;pointer-events:none}

/* lead-ups */
.leads{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px;align-items:start}
.lead{background:var(--panel);border-radius:6px;padding:16px 18px;border-left:3px solid var(--event)}
.lead-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.lead-name{font-weight:700;font-size:16px}
.lead-when{color:var(--muted);font-size:13px}
.lead-label{font-weight:800;font-stretch:80%;font-size:24px;line-height:1.15;margin:10px 0 2px}
.lead-conf{color:var(--muted);font-size:13px;margin-bottom:10px}
.lead-rows{width:100%;border-collapse:collapse;font-size:14px}
.lead-rows td{padding:6px 0;border-top:1px solid var(--line);vertical-align:baseline}
.lead-rows .ld{color:var(--muted);width:44px}
.lead-rows .lv{text-align:right;white-space:nowrap;padding-left:10px}
.lead-rows tr.pending td{color:var(--faint)}
.lead p{margin:10px 0 0;font-size:13px;color:var(--muted);max-width:70ch}
.lead p.fine{color:var(--faint);font-size:12px;margin-top:6px}
.lead-rows .ln{display:block;color:var(--muted);font-size:12.5px}
.lead-sc{width:100%;border-collapse:collapse;font-size:14px;margin-top:12px}
.lead-sc caption{text-align:left;color:var(--faint);font-size:12px;padding-bottom:4px}
.lead-sc td{padding:6px 8px 6px 0;border-top:1px solid var(--line);white-space:nowrap}
.lead-sc td:first-child{color:var(--muted)}
.lead-sc tr.on td:first-child{color:var(--text);font-weight:600}
.lead-sc .soft{opacity:.7}

/* lower grid */
.grid2{display:grid;grid-template-columns:1.25fr 1fr;gap:20px}
.panel{background:var(--panel);border-radius:6px;padding:14px 18px}
.day{color:var(--muted);font-size:13px;font-weight:600;margin:12px 0 2px}
.day:first-child{margin-top:0}
.rel-row{display:grid;grid-template-columns:72px 1fr auto;gap:10px;padding:8px 0;border-top:1px solid var(--line);align-items:baseline}
.rel-time{color:var(--muted);font-size:14px}
.rel-title{font-weight:600}
.rel-title .imp{display:inline-block;width:8px;height:8px;border-radius:2px;background:var(--event);margin-right:7px;vertical-align:1px}
.rel-title .imp.med{opacity:.45}
.rel-meta{color:var(--muted);font-size:13px;margin-top:1px}
.rel-out{text-align:right;font-size:13px;white-space:nowrap}
.rel-out .v{font-weight:600;display:block}
.rel-out .moves{color:var(--muted)}
.empty{color:var(--muted);padding:8px 0}

table.mk{width:100%;border-collapse:collapse;font-size:14px}
table.mk th{color:var(--faint);font-weight:500;text-align:right;padding:0 0 6px;font-size:12px}
table.mk th:first-child{text-align:left}
table.mk td{padding:8px 0;border-top:1px solid var(--line);text-align:right}
table.mk td:first-child{text-align:left}
.mk .nm{font-weight:600}
.mk .hint{display:block;color:var(--faint);font-size:12px;font-weight:400}
.up{color:var(--bull)} .down{color:var(--bear)} .na{color:var(--faint)}
.note{color:var(--faint);font-size:12px;margin-top:10px}

/* headlines */
.hl{display:grid;grid-template-columns:62px 1fr;gap:12px;padding:9px 0;border-top:1px solid var(--line)}
.hl:first-of-type{border-top:0}
.hl-time{color:var(--muted);font-size:13px}
.hl a{text-decoration:none}
.hl a:hover{text-decoration:underline}
.hl-src{color:var(--faint);font-size:13px;margin-left:6px}
.tag{display:inline-block;font-size:12px;padding:0 7px;border-radius:9px;margin-left:6px;border:1px solid var(--line);color:var(--muted)}
.tag.hawkish{color:var(--bear);border-color:color-mix(in srgb,var(--bear) 45%,transparent)}
.tag.dovish{color:var(--bull);border-color:color-mix(in srgb,var(--bull) 45%,transparent)}
.tag.risk-off{color:var(--event);border-color:color-mix(in srgb,var(--event) 45%,transparent)}
.tag.risk-on{color:var(--us30);border-color:color-mix(in srgb,var(--us30) 45%,transparent)}
.tag.geopolitics{color:var(--gold);border-color:color-mix(in srgb,var(--gold) 45%,transparent)}
.tag.de-escalation{color:var(--flat);border-color:color-mix(in srgb,var(--flat) 45%,transparent)}

footer{margin-top:32px;padding-top:14px;border-top:1px solid var(--line);color:var(--faint);font-size:12px}
footer p{margin:4px 0;max-width:80ch}
.problems{color:var(--bear)}

@media (max-width:1020px){
  .bias{grid-template-columns:1fr}
  .verdict{font-size:clamp(36px,7vw,52px)}
}
@media (max-width:860px){
  .wrap{padding:16px 16px 40px}
  .grid2{grid-template-columns:1fr}
  .lane{grid-template-columns:64px 1fr}
  .axis{margin-left:64px}
  .lanes .nowwrap{left:64px}
  .scale-ends{margin-left:86px}
}
@media (max-width:600px){
  .leads{grid-template-columns:1fr}
  .rel-row{grid-template-columns:70px 1fr}
  .rel-time{white-space:nowrap}
  .rel-out .moves{display:inline-block}
  .rel-out{grid-column:2;text-align:left;white-space:normal}
  .rel-out .v{display:inline;margin-right:8px}
  .axis span:nth-child(even){display:none}
  table.mk{font-size:13px}
  .mk .hint{display:none}
  .fresh{gap:12px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
(function(){
  var cfg = window.BRIEF;
  function fmtLeft(ms){
    if (ms <= 0) return "now";
    var s = Math.floor(ms/1000), d = Math.floor(s/86400), h = Math.floor(s%86400/3600),
        m = Math.floor(s%3600/60), sec = s%60;
    if (d > 0) return "in " + d + "d " + h + "h";
    if (h > 0) return "in " + h + "h " + m + "m";
    return "in " + m + "m " + (sec<10?"0":"") + sec + "s";
  }
  var clockFmt = new Intl.DateTimeFormat("en-US",{timeZone:cfg.tz,weekday:"short",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});
  function nowMs(){ return Date.now() + (cfg.offset || 0); }
  function tick(){
    var now = nowMs();
    var c = document.getElementById("clock"); if (c) c.textContent = clockFmt.format(new Date(now));
    document.querySelectorAll("[data-at]").forEach(function(el){
      el.textContent = fmtLeft(Date.parse(el.getAttribute("data-at")) - now);
    });
    var nl = document.getElementById("nowline");
    if (nl){
      var p = (now - cfg.nightStart) / (cfg.nightEnd - cfg.nightStart) * 100;
      if (p >= 0 && p <= 100){ nl.style.left = p + "%"; nl.style.display = "block"; } else { nl.style.display = "none"; }
    }
  }
  tick(); setInterval(tick, 1000);

  // How old is this page? Flag it if updates have stopped arriving.
  function fmtAgo(ms){
    var m = Math.floor(ms/60000);
    if (m < 60) return m + " min ago";
    var h = Math.floor(m/60);
    if (h < 24) return h + "h " + (m%60) + "m ago";
    return Math.floor(h/24) + "d " + (h%24) + "h ago";
  }
  function freshness(){
    var age = nowMs() - cfg.generated, el = document.getElementById("age"), dot = document.getElementById("dot");
    if (!el) return;
    if (age > cfg.staleAfter){
      el.textContent = " (" + fmtAgo(age) + ", later than expected)";
      if (dot) dot.classList.add("stale");
    } else if (age > 45*60000){
      el.textContent = " (" + fmtAgo(age) + ")";
    } else { el.textContent = ""; }
  }
  freshness(); setInterval(freshness, 30000);

  // Load the new version when it's ready, keeping your scroll position.
  try { var y = sessionStorage.getItem("briefScroll"); if (y) window.scrollTo(0, parseInt(y,10)); } catch(e){}
  function reload(fresh){
    try { sessionStorage.setItem("briefScroll", String(window.scrollY)); } catch(e){}
    if (fresh) location.replace(location.pathname + "?v=" + Date.now()); else location.reload();
  }
  if (/^https?:/.test(location.protocol)){
    // Hosted: check a tiny file every 2 minutes and reload only when it changed.
    setInterval(function(){
      fetch("meta.json?t=" + Date.now(), {cache:"no-store"}).then(function(r){ return r.json(); })
        .then(function(m){ if (m && m.generated > cfg.generated) reload(true); }).catch(function(){});
    }, 120000);
  } else {
    var wait = Math.max(30000, cfg.nextUpdate + 90000 - nowMs());
    setTimeout(function(){ reload(false); }, Math.min(wait, 10*60*1000));
  }
})();
"""


# ------------------------------------------------------------------ helpers

def _t(dt: datetime, tz, fmt: str = "%I:%M %p") -> str:
    s = dt.astimezone(tz).strftime(fmt)
    return s.lstrip("0") if fmt.startswith("%I") else s


def _num(key: str, v: float | None) -> str:
    if v is None:
        return "n/a"
    if key == "gold":
        return f"{v:,.1f}"
    if key in ("us30", "us100"):
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def _chg(v: float | None, invert: bool = False) -> str:
    if v is None:
        return '<span class="na">n/a</span>'
    cls = "up" if v > 0.005 else "down" if v < -0.005 else "na"
    return f'<span class="{cls}">{v:+.2f}%</span>'


def _signed(x: float) -> str:
    if abs(x) < 0.05:
        return "0.0"
    return f"{x:+.1f}".replace("-", "−")


def _bar_html(points: float, span: float) -> str:
    w = min(abs(points) / span, 1.0) * 50
    color = "var(--bull)" if points > 0 else "var(--bear)"
    left = 50 if points >= 0 else 50 - w
    return f'<div class="minibar"><i style="left:{left:.1f}%;width:{w:.1f}%;background:{color}"></i></div>'


# ------------------------------------------------------------------ sections

def _instrument(key: str, name: str, symbol: str, data: dict) -> str:
    score = data["score"]
    pos = (score + 10) / 20 * 100
    left, width = (50, pos - 50) if score >= 0 else (pos, 50 - pos)
    fill_color = {"bull": "var(--bull)", "bear": "var(--bear)", "flat": "var(--flat)"}[data["tone"]]
    rows = []
    for d in data["drivers"]:
        rows.append(
            f'<tr><td class="dn">{escape(d["name"])}<span class="dd">{escape(d["detail"])}</span></td>'
            f'<td class="db">{_bar_html(d["points"], 4)}</td><td class="dp">{_signed(d["points"])}</td></tr>'
        )
    return f"""
<article class="inst {key}" aria-label="{name} bias">
  <div class="inst-head"><span class="inst-name">{name}</span><span class="inst-sym">{escape(symbol)}</span></div>
  <div class="verdict tone-{data['tone']}">{escape(data['label'])}</div>
  <div class="scoreline">
    <span class="scorenum">{_signed(score)} <span style="color:var(--faint);font-weight:400">/ 10</span></span>
    <div class="scale" role="img" aria-label="Score {score:.1f} on a scale from minus 10 to plus 10">
      <span class="fill" style="left:{left:.1f}%;width:{width:.1f}%;background:{fill_color};opacity:.55"></span>
      <span class="mid"></span><span class="pin" style="left:{pos:.1f}%"></span>
    </div>
  </div>
  <div class="scale-ends"><span>Bearish</span><span>Bullish</span></div>
  <div class="agree">{escape(data['agreement'])}</div>
  {f'<p class="warn" role="note">{escape(data["warning"])}</p>' if data.get("warning") else ""}
  <table class="drivers">{''.join(rows)}</table>
</article>"""


def _banners(brief: dict, tz, now: datetime) -> str:
    out = []
    if brief.get("demo"):
        out.append('<div class="banner demo"><strong>Demo data.</strong> '
                   '<span>Everything below is made up to show the layout. Start the app normally for live data.</span></div>')
    mkt = brief["market"]
    if not mkt["open"]:
        when = _t(mkt["reopen"], tz, "%A %I:%M %p").replace(" 0", " ")
        what = "for the weekend" if mkt["reason"] == "weekend" else "for the daily one-hour break"
        out.append(f'<div class="banner closed"><strong>Gold, US30 and US100 futures are closed {what}.</strong>'
                   f'<span>They reopen {when} your time. Changes shown are from the last session.</span></div>')

    for rel in brief["releases"]:
        if rel["impact"] != "High":
            continue
        if rel["status"] == "waiting":
            ready = rel["time"] + timedelta(minutes=rel["window_min"] + 13)
            out.append(f'<div class="banner event"><strong>{escape(rel["headline"])} just came out.</strong>'
                       f'<span>The first 15 to 30 minutes are often noisy and can reverse. '
                       f'The reaction gets scored at about {_t(ready, tz)}.</span></div>')
            break
    nxt = brief.get("next_release")
    if nxt and nxt["impact"] == "High" and (nxt["time"] - now) <= timedelta(minutes=90):
        ev = nxt["events"][0]
        fc = []
        if ev["forecast"]:
            fc.append(f"Forecast {escape(ev['forecast'])}")
        if ev["previous"]:
            fc.append(("previous " if fc else "Previous ") + escape(ev["previous"]))
        fc_txt = (", ".join(fc) + ". ") if fc else ""
        out.append(f'<div class="banner event"><span class="count" data-at="{nxt["time"].isoformat()}"></span>'
                   f'<strong>{escape(nxt["headline"])} at {_t(nxt["time"], tz)}.</strong>'
                   f'<span>{fc_txt}Expect fast spikes. The bias can flip on the number.</span></div>')
    return "".join(out)


def _night(brief: dict, tz) -> str:
    night = brief["night"]
    start, end = night["start"], night["end"]
    span = (end - start).total_seconds()

    def pct(dt):
        return max(0.0, min(100.0, (dt - start).total_seconds() / span * 100))

    lanes = []
    # Releases lane
    marks = []
    for rel in brief["releases"]:
        if start <= rel["time"] < end and not rel.get("all_day") and not rel.get("lead_only"):
            p = pct(rel["time"])
            cls = "rel" if rel["impact"] == "High" else "rel med"
            title = f'{_t(rel["time"], tz)} {rel["headline"]}'
            marks.append(f'<span class="{cls}" style="left:{p:.2f}%" title="{escape(title)}"></span>')
            if rel["impact"] == "High" and p < 80:
                marks.append(f'<span class="rel-label" style="left:{p:.2f}%">{_t(rel["time"], tz)} '
                             f'{escape(_short(rel["headline"]))}</span>')
    lanes.append(f'<div class="lane"><span class="lane-name">US data</span><div class="track">{"".join(marks)}</div></div>')

    sess = {s["name"]: s for s in night["sessions"]}
    overlap = None
    if "London" in sess and "New York" in sess:
        o = max(sess["London"]["open"], sess["New York"]["open"])
        c = min(sess["London"]["close"], sess["New York"]["close"])
        if c > o:
            overlap = (o, c)
    for name in ("Tokyo", "London", "New York", "US30 cash"):
        segs = []
        s = sess.get(name)
        if s:
            l, r = pct(s["open"]), pct(s["close"])
            cls = "seg us30" if name == "US30 cash" else "seg"
            label = f'{name}: {_t(s["open"], tz)} to {_t(s["close"], tz)}'
            segs.append(f'<span class="{cls}" style="left:{l:.2f}%;width:{r - l:.2f}%" title="{escape(label)}"></span>')
            if name == "New York" and overlap:
                ol, orr = pct(overlap[0]), pct(overlap[1])
                segs.append(f'<span class="seg overlap" style="left:{ol:.2f}%;width:{orr - ol:.2f}%" '
                            f'title="London and New York overlap"></span>')
        lanes.append(f'<div class="lane"><span class="lane-name">{name}</span><div class="track">{"".join(segs)}</div></div>')

    ticks = []
    for h in range(0, 25, 3):
        t = start + timedelta(hours=h)
        lab = _t(t, tz, "%I %p").lower().replace(" ", "")
        ticks.append(f'<span style="left:{h / 24 * 100:.2f}%">{lab}</span>')

    sub_bits = []
    if overlap:
        sub_bits.append(f"London and New York overlap {_t(overlap[0], tz)} to {_t(overlap[1], tz)} (shaded gold)")
    if "US30 cash" in sess:
        sub_bits.append(f"US30 cash session opens {_t(sess['US30 cash']['open'], tz)}")
    sub = ". ".join(sub_bits) + "." if sub_bits else "No sessions in this window."

    return f"""
<section aria-labelledby="night-h">
  <h2 id="night-h">{escape(night["title"])}</h2>
  <p class="sub">{sub}</p>
  <div class="strip">
    <div class="lanes">{''.join(lanes)}<div class="nowwrap"><span class="nowline" id="nowline" style="display:none"></span></div></div>
    <div class="axis">{''.join(ticks)}</div>
  </div>
</section>"""


def _leadups(brief: dict, tz, now: datetime) -> str:
    reads = brief.get("leadups") or []
    if not reads:
        body = ('<p class="empty">No NFP, CPI or PCE in this week\'s calendar yet. '
                'A lead-up read appears here once one is scheduled.</p>')
        return f"""
<section aria-labelledby="lead-h">
  <h2 id="lead-h">Lead-up to the big releases</h2>
  <p class="sub">How the smaller releases before NFP, CPI and PCE came in, and what they hint about the big one.</p>
  <div class="panel">{body}</div>
</section>"""

    cards = []
    for read in reads:
        t, rel = read["target"], read["release"]
        ev = rel["events"][0]
        when = _t(rel["time"], tz, "%A") + " " + _t(rel["time"], tz)
        if ev["forecast"]:
            when += f", forecast {escape(ev['forecast'])}"
        if ev["previous"]:
            when += f", previous {escape(ev['previous'])}"
        rows = []
        items = [dict(s, kind="done") for s in read["scored"]] + [dict(p, kind="pending") for p in read["pending"]]
        items.sort(key=lambda x: x["time"])
        for it in items:
            day = _t(it["time"], tz, "%a")
            if it["kind"] == "done":
                h = it["hawk"]
                tone = "tone-bear" if h >= 0.3 else "tone-bull" if h <= -0.3 else "tone-flat"
                hot_cold = "came in hot" if h >= 0.3 else "came in cold" if h <= -0.3 else "in line"
                nums = f'<span class="ln">{escape(it["text"])}</span>' if it.get("text") else ""
                rows.append(f'<tr><td class="ld">{day}</td><td>{escape(it["name"])}{nums}</td>'
                            f'<td class="lv {tone}">{hot_cold}</td></tr>')
            else:
                label = "reading the reaction" if it["status"] == "waiting" else "still to come"
                rows.append(f'<tr class="pending"><td class="ld">{day}</td><td>{escape(it["name"])}</td>'
                            f'<td class="lv">{label}</td></tr>')
        table = f'<table class="lead-rows">{"".join(rows)}</table>' if rows else ""

        meaning = ""
        if read["lean"] is not None and abs(read["lean"]) >= 0.3:
            if read["lean"] > 0:
                meaning = ("Hot data usually lifts yields and the dollar, which weighs on gold, US30 and US100. "
                           f"If {t['name']} confirms it, some of that may already be priced in. "
                           "A surprise the other way would likely move price more.")
            else:
                meaning = ("Soft data usually pulls yields and the dollar down, which helps gold. For US30 and US100 it "
                           "depends on whether the market reads it as rate cuts (good) or a slowdown (bad). "
                           f"If {t['name']} confirms it, some of that may already be priced in. "
                           "A surprise the other way would likely move price more.")
        meaning_html = f"<p>{meaning}</p>" if meaning else ""
        conf = f'<div class="lead-conf">{escape(read["confidence"])}</div>' if read["confidence"] else '<div class="lead-conf"></div>'
        cards.append(f"""
<article class="lead" aria-label="Lead-up to {escape(t['name'])}">
  <div class="lead-head"><span class="lead-name">{escape(t['name'])}</span><span class="lead-when">{when}</span></div>
  <div class="lead-label tone-{read['tone']}">{escape(read['label'])}</div>
  {conf}
  {table}
  {_scenarios(t, read.get("side"))}
  {meaning_html}
  <p class="fine">{escape(t['note'])}</p>
</article>""")

    return f"""
<section aria-labelledby="lead-h">
  <h2 id="lead-h">Lead-up to the big releases</h2>
  <p class="sub">How the smaller releases before it came in (the actual number against forecast where FRED has it, otherwise the market's reaction), what that hints about the big one, and how each market usually reacts.</p>
  <div class="leads">{''.join(cards)}</div>
</section>"""


def _scenarios(target: dict, side: str | None) -> str:
    """How each market usually reacts first to a hot or a cold number. The
    row the lead-up leans toward is marked."""
    def cell(name: str, v: float) -> str:
        if abs(v) < 0.25:
            return f'<td class="tone-flat">{name} mixed</td>'
        soft = " soft" if abs(v) < 0.75 else ""
        return (f'<td class="tone-bull{soft}">{name} ▲</td>' if v > 0
                else f'<td class="tone-bear{soft}">{name} ▼</td>')

    rows = []
    for key, flip, label in (("hot", 1, target["hot"]), ("cold", -1, target["cold"])):
        cells = "".join(cell(name, target["if_hot"][k] * flip)
                        for k, name in (("gold", "Gold"), ("us30", "US30"), ("us100", "US100")))
        mark = " (lead-up leans here)" if side == key else ""
        label = label.split(" ", 1)[1]  # "a hot CPI" -> "hot CPI"
        rows.append(f'<tr class="{"on" if side == key else ""}"><td>If {escape(label)}{mark}</td>{cells}</tr>')
    return (f'<table class="lead-sc"><caption>Usual first reaction. Faded arrow = weaker tendency.</caption>'
            f'{"".join(rows)}</table>')


def _short(title: str) -> str:
    return (title.replace("Non-Farm Employment Change", "NFP").replace(" m/m", "")
            .replace(" y/y", "").replace(" q/q", "").replace("Federal Funds Rate", "Fed decision"))


def _releases(brief: dict, tz, now: datetime) -> str:
    rels = [r for r in brief["releases"] if r["time"] >= now - timedelta(days=7) and not r.get("lead_only")]
    if not rels:
        return '<p class="empty">No US releases in the feed yet. The calendar refreshes every hour.</p>'
    out, last_day = [], None
    for r in rels:
        day = r["time"].astimezone(tz).strftime("%A, %b %d").replace(" 0", " ")
        if day != last_day:
            out.append(f'<div class="day">{day}</div>')
            last_day = day
        ev = r["events"][0]
        meta = []
        if ev.get("actual"):
            meta.append(f"<b>Actual {escape(ev['actual'])}</b>")
        if ev["forecast"]:
            meta.append(f"{'forecast' if meta else 'Forecast'} {escape(ev['forecast'])}")
        if ev["previous"]:
            meta.append(f"previous {escape(ev['previous'])}")
        if r["others"]:
            meta.append(f"with {len(r['others'])} related")
        meta_html = f'<div class="rel-meta">{", ".join(meta)}</div>' if meta else ""

        if r["status"] == "all_day":
            right = '<span class="v">No set time</span><span class="moves">Expect headline-driven moves</span>'
        elif r["status"] == "upcoming":
            right = f'<span class="v" data-at="{r["time"].isoformat()}"></span>'
        elif r["status"] == "waiting":
            right = '<span class="v" style="color:var(--event)">Reading the reaction</span>'
        else:
            tone = ""
            if r["hawk"] is not None:
                tone = "tone-bear" if r["hawk"] >= 0.3 else "tone-bull" if r["hawk"] <= -0.3 else "tone-flat"
            moves = ""
            if r["gold_pct"] is not None or r["us30_pct"] is not None or r.get("us100_pct") is not None:
                g = "n/a" if r["gold_pct"] is None else f'{r["gold_pct"]:+.2f}%'
                u = "n/a" if r["us30_pct"] is None else f'{r["us30_pct"]:+.2f}%'
                n = "n/a" if r.get("us100_pct") is None else f'{r["us100_pct"]:+.2f}%'
                moves = f'<span class="moves">Gold {g}, US30 {u}, US100 {n}</span>'
            right = f'<span class="v {tone}">{escape(r["verdict"])}</span>{moves}'
        imp = "imp" if r["impact"] == "High" else "imp med"
        out.append(
            f'<div class="rel-row"><span class="rel-time">{"All day" if r["status"] == "all_day" else _t(r["time"], tz)}</span>'
            f'<div><div class="rel-title"><span class="{imp}" title="{r["impact"]} impact"></span>{escape(r["headline"])}</div>{meta_html}</div>'
            f'<div class="rel-out">{right}</div></div>'
        )
    return "".join(out)


def _markets(brief: dict, now: datetime) -> str:
    rows = []
    for key in ("gold", "us30", "us100", "dollar", "treasury_10y", "vix"):
        s = brief["snaps"].get(key)
        name = LABELS[key]
        hint = ""
        if key == "treasury_10y":
            hint = '<span class="hint">Falls when yields rise</span>'
        elif key == "gold":
            hint = '<span class="hint">Futures, a few dollars above spot</span>'
        elif key == "us30":
            hint = '<span class="hint">Dow futures</span>'
        elif key == "us100":
            hint = '<span class="hint">Nasdaq 100 futures</span>'
        if not s:
            rows.append(f'<tr><td><span class="nm">{name}</span>{hint}</td><td colspan="4" class="na">No data</td></tr>')
            continue
        rows.append(
            f'<tr><td><span class="nm">{name}</span>{hint}</td><td>{_num(key, s["last"])}</td>'
            f'<td>{_chg(s["chg_30m"])}</td><td>{_chg(s["chg_4h"])}</td><td>{_chg(s["chg_24h"])}</td></tr>'
        )
    return f"""<table class="mk">
<thead><tr><th>Market</th><th>Last</th><th>30m</th><th>4h</th><th>24h</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="note">Yahoo prices lag about 10 minutes. Use your broker chart for entries.</p>"""


def _headlines(brief: dict, tz, now: datetime) -> str:
    hls = brief["headlines"]
    if not hls:
        return '<p class="empty">No headlines came through this time. They retry on the next update.</p>'
    out = []
    for h in hls[:20]:
        mins = int((now - h["time"]).total_seconds() // 60)
        ago = f"{mins}m ago" if mins < 60 else f"{mins // 60}h ago"
        tags = "".join(f'<span class="tag {t}">{t}</span>' for t in h.get("tags", []))
        link = escape(h.get("link") or "#")
        out.append(
            f'<div class="hl"><span class="hl-time">{ago}</span><div>'
            f'<a href="{link}" target="_blank" rel="noopener">{escape(h["title"])}</a>'
            f'<span class="hl-src">{escape(h.get("source", ""))}</span>{tags}</div></div>'
        )
    return "".join(out)


# ------------------------------------------------------------------ page

def render(brief: dict) -> str:
    tz = brief["tz"]
    now = brief["now"]
    syms = brief["symbols"]
    stale = bool(brief["problems"])
    weekend = brief["market"].get("reason") == "weekend"
    if brief.get("hosted"):
        cadence = "Updates every 3 hours until markets reopen" if weekend else "Updates about every 30 min"
        stale_after_min = 240 if weekend else 75
    else:
        cadence = f"Next update {_t(brief['next_update'], tz)}"
        stale_after_min = max(75, int((brief["next_update"] - now).total_seconds() // 60) + 45)

    cfg = {
        "tz": str(tz),
        "nightStart": int(brief["night"]["start"].timestamp() * 1000),
        "nightEnd": int(brief["night"]["end"].timestamp() * 1000),
        "nextUpdate": int(brief["next_update"].timestamp() * 1000),
        "offset": int(brief.get("clock_offset_ms", 0)),
        "generated": int(now.timestamp() * 1000),
        "staleAfter": stale_after_min * 60000,
    }

    problems = ""
    if brief["problems"]:
        items = "; ".join(escape(p) for p in brief["problems"])
        problems = f'<p class="problems">Some sources didn\'t respond this time: {items}. They\'ll be tried again on the next update.</p>'

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>Market brief</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head><body><div class="wrap">

<header class="top">
  <div><span class="brand">Market <span>brief</span></span></div>
  <div class="clock"><b id="clock">{_t(now, tz, "%a, %b %d %I:%M %p")}</b></div>
  <div class="fresh">
    <span><span class="dot{' stale' if stale else ''}" id="dot"></span>Updated {_t(now, tz)}<span id="age"></span></span>
    <span>{cadence}</span>
  </div>
</header>

{_banners(brief, tz, now)}

<div class="bias">
{_instrument("gold", "Gold", syms["gold"], brief["bias"]["gold"])}
{_instrument("us30", "US30", syms["us30"], brief["bias"]["us30"])}
{_instrument("us100", "US100", syms["us100"], brief["bias"]["us100"])}
</div>

{_night(brief, tz)}

{_leadups(brief, tz, now)}

<section class="grid2">
  <div>
    <h2>US releases</h2>
    <p class="sub">High and medium impact, in your time. The verdict is how yields and the dollar reacted. Actual numbers come from FRED when it has them.</p>
    <div class="panel">{_releases(brief, tz, now)}</div>
  </div>
  <div>
    <h2>Markets</h2>
    <p class="sub">Change over the last 30 minutes, 4 hours and 24 hours.</p>
    <div class="panel">{_markets(brief, now)}</div>
  </div>
</section>

<section>
  <h2>Headlines, last 12 hours</h2>
  <p class="sub">Tags come from simple keyword rules and feed the headline driver above.</p>
  <div class="panel">{_headlines(brief, tz, now)}</div>
</section>

<footer>
  {problems}
  <p>Bias combines how big US releases moved yields and the dollar this week, the 24-hour dollar and yield trend, VIX, headline tone, geopolitical tension, and each market's own recent trend. It doesn't read chart patterns or levels, so your setup still decides entries.</p>
  <p>Personal tool, not financial advice. Data: Forex Factory calendar feed, Yahoo Finance, Google News, The GDELT Project for geopolitical tension, and FRED (Federal Reserve Bank of St. Louis) for released numbers. This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.</p>
</footer>
</div>
<script>window.BRIEF={json.dumps(cfg)};</script>
<script>{JS}</script>
</body></html>"""
