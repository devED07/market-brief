"""Market Brief: gold and US30 bias dashboard.

Start it with "Start Market Brief.bat" (Windows) or start_mac.command (Mac).
Leave the window open while you trade. Close it or press Ctrl+C to stop.

Options:
  --once         run one update and stop
  --demo         build the dashboard from made-up data (for a quick look)
  --no-browser   don't open the dashboard in your browser
  --hosted       GitHub mode: publish to GitHub Pages instead of a local file
                 (the workflow in .github/workflows uses this)
"""

import argparse
import sys
import time
import traceback
import webbrowser
from datetime import datetime, timedelta, timezone

from brief import bias as B
from brief import calendar_feed as C
from brief import dashboard as D
from brief import news as N
from brief import prices as P
from brief import telegram as T
from brief.config import DASHBOARD_FILE, DATA_DIR, load_settings

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def next_run_time(now: datetime, settings, releases: list[dict]) -> datetime:
    """Regular slots on the clock (xx:02 and xx:32 for a 30-min refresh), plus
    extra runs before big releases and right after their reaction is readable."""
    step = settings.refresh_minutes
    minutes_today = now.hour * 60 + now.minute
    slot = (minutes_today // step + 1) * step + 2
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = [base + timedelta(minutes=slot)]
    if candidates[0] <= now:
        candidates[0] += timedelta(minutes=step)

    for r in releases:
        if r["impact"] != "High":
            continue
        for t in (r["time"] - timedelta(minutes=61),
                  r["time"] - timedelta(minutes=16),
                  r["time"] + timedelta(minutes=r["window_min"] + B.YAHOO_DELAY_MIN + 1)):
            if t > now + timedelta(seconds=30):
                candidates.append(t)
    return min(candidates)


# Hosted mode: stay on around big releases so the 15-minute heads-up and the
# reaction score don't depend on GitHub's schedule, which can run late.
STAY_BEFORE_MIN = 45
MAX_JOB_MIN = 170


def run_cycle(settings, demo: bool, memory: dict, hosted: bool = False) -> tuple[dict, str]:
    tz = settings.tz
    symbols = {"gold": settings.gold, "us30": settings.us30, "dollar": settings.dollar,
               "treasury_10y": settings.treasury_10y, "vix": settings.vix}
    problems: list[str] = []
    clock_offset_ms = 0

    if demo:
        from brief import demo as DM
        now, rows, series, headlines = DM.build()
        for h in headlines:
            h["tags"] = N._tag(h["title"])
        snaps = {k: P.snapshot(s, now) for k, s in series.items()}
        clock_offset_ms = int((now - datetime.now(timezone.utc)).total_seconds() * 1000)
    else:
        now = datetime.now(timezone.utc)
        rows, _fresh, note = C.load_raw()
        if note:
            problems.append(note)

        series, snaps, price_problems = P.fetch_all(symbols, now)
        for key in symbols:
            if key not in series and key in memory.get("series", {}):
                series[key] = memory["series"][key]
                snaps[key] = memory["snaps"][key]
        problems.extend(price_problems)
        memory.setdefault("series", {}).update(series)
        memory.setdefault("snaps", {}).update(snaps)

        headlines, news_problems = N.fetch_headlines(now)
        if not headlines and memory.get("headlines"):
            headlines = memory["headlines"]
        if headlines:
            memory["headlines"] = headlines
        if news_problems and len(news_problems) == len(N.QUERIES):
            problems.append("Google News didn't respond")

    releases = [B.score_release(r, series, now) for r in C.group_releases(C.usd_events(rows))]
    upcoming_high = [r for r in releases if r["status"] == "upcoming" and r["impact"] == "High"]
    market = B.market_status(now, tz)
    if demo:
        market = {"open": True, "reason": "", "reopen": None}

    brief = {
        "now": now,
        "tz": tz,
        "symbols": symbols,
        "releases": releases,
        "next_release": upcoming_high[0] if upcoming_high else None,
        "snaps": snaps,
        "headlines": headlines,
        "bias": B.build(releases, snaps, N.tone(headlines), now),
        "market": market,
        "night": B.sessions_for_night(now, tz, market),
        "problems": problems,
        "next_update": next_run_time(now, settings, releases),
        "demo": demo,
        "hosted": hosted,
        "clock_offset_ms": clock_offset_ms,
    }
    html = D.render(brief)
    if not hosted:
        DASHBOARD_FILE.write_text(html, encoding="utf-8")

    if not demo:
        err = T.process(settings, brief, now)
        if err:
            print(f"  ! {err}")
    return brief, html


def _hm(dt: datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%I:%M %p").lstrip("0")


def print_summary(brief: dict, tz) -> None:
    g, u = brief["bias"]["gold"], brief["bias"]["us30"]
    print(f"[{_hm(brief['now'], tz)}] Gold: {g['label']} ({g['score']:+.1f})   "
          f"US30: {u['label']} ({u['score']:+.1f})")
    nxt = brief["next_release"]
    if nxt:
        print(f"           Next big release: {nxt['headline']} at "
              f"{nxt['time'].astimezone(tz).strftime('%a')} {_hm(nxt['time'], tz)}")
    for p in brief["problems"]:
        print(f"  ! {p}")


def _stay_until(releases: list[dict], now: datetime) -> datetime | None:
    """If a high-impact release is close or still being read, returns the
    time its reaction will have been scored."""
    ends = []
    for r in releases:
        if r["impact"] != "High" or r["status"] == "done":
            continue
        if r["time"] - now <= timedelta(minutes=STAY_BEFORE_MIN):
            ends.append(r["time"] + timedelta(minutes=r["window_min"] + B.YAHOO_DELAY_MIN + 2))
    return max(ends) if ends else None


def run_hosted(settings) -> None:
    from brief import publish as PUB

    tz = settings.tz
    print("Market Brief, GitHub mode")
    print(PUB.restore_state())
    if settings.telegram_enabled:
        print("Telegram alerts are on.")
    memory: dict = {}
    started = datetime.now(timezone.utc)
    while True:
        brief, html = run_cycle(settings, False, memory, hosted=True)
        print_summary(brief, tz)
        PUB.publish(html, int(brief["now"].timestamp() * 1000),
                    f"Update {brief['now']:%Y-%m-%d %H:%M} UTC")
        print("           Published to GitHub Pages.")

        now = datetime.now(timezone.utc)
        until = _stay_until(brief["releases"], now)
        nxt = next_run_time(now, settings, brief["releases"])
        if until is None or nxt > until or nxt > started + timedelta(minutes=MAX_JOB_MIN):
            break
        print(f"           Big release nearby, staying on. Next update at {_hm(nxt, tz)}\n")
        while datetime.now(timezone.utc) < nxt:
            time.sleep(min(30, max(1, (nxt - datetime.now(timezone.utc)).total_seconds())))


def main() -> None:
    ap = argparse.ArgumentParser(description="Gold and US30 market brief")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--hosted", action="store_true")
    args = ap.parse_args()

    settings = load_settings()
    tz = settings.tz
    if args.hosted:
        run_hosted(settings)
        return
    print("Market Brief is running.")
    print(f"Dashboard: {DASHBOARD_FILE}")
    print("Leave this window open while you trade. Close it or press Ctrl+C to stop.\n")

    memory: dict = {}
    first = True
    while True:
        try:
            brief, _html = run_cycle(settings, args.demo, memory)
            print_summary(brief, tz)
            nxt = brief["next_update"]
        except Exception as exc:
            print(f"  ! Update failed: {exc}. Trying again in 5 minutes. Details in data/error.log")
            with open(DATA_DIR / "error.log", "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.now()} ---\n{traceback.format_exc()}")
            nxt = datetime.now(timezone.utc) + timedelta(minutes=5)

        if first and settings.open_browser and not args.no_browser and DASHBOARD_FILE.exists():
            webbrowser.open(DASHBOARD_FILE.as_uri())
        first = False

        if args.once or args.demo:
            break

        print(f"           Next update at {_hm(nxt, tz)}\n")
        try:
            while datetime.now(timezone.utc) < nxt:
                time.sleep(min(30, max(1, (nxt - datetime.now(timezone.utc)).total_seconds())))
        except KeyboardInterrupt:
            print("\nStopped. See you next session.")
            return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
