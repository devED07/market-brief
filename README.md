# Market Brief

A gold, US30 and US100 bias dashboard that updates itself every 30 minutes.

Each update it:
- pulls this week's US economic calendar (CPI, NFP, FOMC, PCE...)
- checks gold, US30, US100, the dollar index, 10Y T-notes and VIX
- reads the actual release numbers from FRED (optional free key, part H)
- reads the last 12 hours of headlines
- scores gold, US30 and US100 from −10 (bearish) to +10 (bullish), and lists the reasons underneath
- before NFP, CPI and Core PCE, reads the data that came out ahead of them and shows which way each market usually goes if the big number follows

It runs for free on GitHub, so your computer doesn't need to be on.

**Dashboard:** `https://<your-username>.github.io/market-brief/`

---

## A. Running online on GitHub

GitHub Actions runs the app on a schedule (the file `.github/workflows/market-brief.yml`), and GitHub Pages hosts the page.

**Turn on the website (one time only).** Once the first run has finished:
1. In the repo, open **Settings → Pages**.
2. Under *Build and deployment*, set Source to **Deploy from a branch**.
3. Choose branch **gh-pages** and folder **/ (root)**, then click **Save**.
4. Wait a minute. The dashboard address appears at the top of that page.

**When it updates** (once the timer below is set):
- While gold and Dow futures trade (Monday morning to Saturday morning, Manila time): every 15 or 30 minutes, whichever timer you set.
- Weekends: every 3 hours.
- Around big US releases it stays on, so you get the 15-minute warning and the reaction score on time.

If an update is more than about 75 minutes old, the page marks it in the top bar.

**Update by hand:** open the **Actions** tab, choose **Market Brief**, then **Run workflow**.

**Turn on regular updates (one time).** On the free plan, GitHub often skips scheduled runs, so each update lines up the next one itself. The next run waits in an "environment" with a wait timer, which costs nothing:
1. In the repo, open **Settings → Environments**. If `timer` is already listed, click it. If not, click **New environment**, name it `timer`, and click **Configure environment**.
2. Under *Deployment protection rules*, tick **Wait timer**, enter `15` (or `30` for fewer updates), and click **Save protection rules**. You can change it any time.
3. Start the chain once: **Actions → Market Brief → Run workflow**.

From then on, every update lines up the next one. GitHub's own schedule stays on as a backup and restarts the chain if it ever stops. Until a wait timer of at least 10 minutes is set, the app won't chain, so it can never run updates back to back. With a 15-minute timer, headlines are refreshed every other update, so Google News isn't asked too often.

---

## B. Telegram bot (optional)

You get:
- **Release warnings** about 60 and 15 minutes before high-impact US releases, with the lead-up read for NFP, CPI and PCE.
- **Reaction scores** for each big release, about 30 minutes after it comes out.
- **Bias changes** for gold or US30, and a heads-up when geopolitical tension turns high.
- **A session brief** each weekday at 8:30 PM: both biases and what's driving them, the releases coming up, and a link to the dashboard. Change the time with `brief_time` in `settings.ini`.

Setup:
1. In Telegram, search for **@BotFather**, send `/newbot`, and pick a name and a username (the username must end in `bot`). BotFather replies with a token that looks like `123456789:ABCdef...`.
2. In this repo, open **Settings → Secrets and variables → Actions → New repository secret**. Name it `TELEGRAM_BOT_TOKEN`, paste the token, and click **Add secret**.
3. Open your new bot in Telegram (BotFather sends a link) and press **Start**.

Within 30 minutes you'll get "Market Brief is connected." To get it sooner, run the workflow by hand from the Actions tab. The bot locks onto your chat the first time, so other people who find it can't get your alerts.

**Never put the token in `settings.ini` or any other file here.** The repo is public, and anyone with the token can control your bot.

---

## C. Running it on your own PC instead (optional)

You can also run it on your PC as a local app, with the dashboard opening in your browser.

1. Install Python from [python.org](https://www.python.org/downloads/). On the first screen, tick **"Add python.exe to PATH"**.
2. Download this repo (**Code → Download ZIP**) and extract it somewhere permanent.
3. Double-click **Start Market Brief.bat** (on a Mac: `start_mac.command`). Keep the black window open while you trade.

For phone alerts in this mode, fill in the `[telegram]` part of `settings.ini`. That file stays on your PC, so it's safe there.

---

## D. Reading the dashboard

The big word (Bearish, Leaning bullish, No clear lean...) is the bias. Below it are the six drivers and how many points each one adds:

| Driver | What it measures |
|---|---|
| US data this week | How yields and the dollar reacted in the first 15 minutes after each big US release. Yields and dollar up means hawkish, which is bad for gold, US30 and US100. Older releases count less (half weight after 3 days). |
| Dollar and yields | The dollar and 10Y yields over the last 24 hours. |
| Risk mood | VIX. Nervous markets hurt US30 and US100 and usually help gold. The exception is when gold falls along with stocks: that's traders selling everything, so fear isn't counted for gold. |
| Headlines | Keyword tags on recent news (rates talk and market risk mood). |
| Geopolitics | Of the news about events between two countries in the last 24 hours, how much is about conflict (threats, military moves, coercion, attacks, fighting), compared with the normal level over the past 30 days. It comes from the live event feed of [The GDELT Project](https://www.gdeltproject.org/), a free, open database that codes world news every 15 minutes. More conflict news than usual supports gold as a safe haven and weighs on US30 and US100. If it turns **high**, Telegram sends you a message. |
| Price trend | The market's own direction: the last 24 hours, the last 4 hours, and where price sits against its 5-day average. |

When the data and news point one way but price keeps going the other, the card shows a **Price disagrees** note. That's a sign to wait for price to confirm.

"Drivers are mixed" means low conviction, so let your chart lead.

**Lead-up to the big releases.** For each NFP, CPI or Core PCE in the calendar, the dashboard lists the smaller releases that come before it and whether each came in hot or cold, then says what they hint about the big one:

| Big release | Lead-ins it watches |
|---|---|
| NFP | ADP, jobless claims, ISM services and manufacturing, JOLTS, Challenger job cuts, consumer confidence |
| CPI | PPI, ISM prices paid, import prices, wage growth from the last NFP, inflation expectations |
| Core PCE | CPI, PPI, import prices |

With the FRED key set (part H), each lead-in is read from its actual number against the forecast, for example "ADP 58K vs 42K forecast", and gasoline prices are added as a lead-in for CPI. Lead-ins FRED doesn't carry (the ISM surveys, Challenger, consumer confidence), and everything when no key is set, are read from how yields and the dollar reacted instead.

Under the lead-ins, each card shows the usual first reaction of gold, US30 and US100 to a hot and to a cold number, and marks the side the lead-up leans toward. That is the pre-release outlook. It does not change the bias score until the number is out.

Some lead-ins predict better than others. ADP is a weak guide to NFP, while CPI and PPI tell you most of what PCE will show. So each read comes with a confidence level. Scored releases are kept for 45 days, so lead-ins from earlier weeks still count. The Telegram heads-up before each big release includes the lead-up read.

The purple bar at the top warns you before high-impact releases (with a countdown) and right after them. The first 15 to 30 minutes after a release are often noisy and can reverse.

Things to know:
- Prices come from Yahoo and lag about 10 minutes. The dashboard is for bias and timing, not entries. Use your broker chart for those.
- Gold is shown as GC futures, which trade a few dollars above spot XAUUSD. The direction is what matters here.
- The free calendar has the forecast but not the actual number. The bias score reads the surprise from how the market reacted. The actual numbers shown come from FRED, usually within an hour of the release.
- US100 is NQ futures (Nasdaq 100).
- This is a personal tool, not financial advice.

---

## E. On your TradingView chart

`tradingview/market_brief_live.pine` is an indicator that shows the live-market part of the bias right on your chart, using TradingView's own prices: dollar and yields, risk mood, and the chart's price trend, with the same rules as the dashboard. US data reactions and headlines aren't available inside TradingView, so for the full bias, check the dashboard. Because the indicator has three of the five drivers, its score can differ from the dashboard's.

**Add it (one time):**
1. In this repo, open `tradingview/market_brief_live.pine` and click the copy button.
2. In TradingView, open a gold or US30 chart, then open **Pine Editor** at the bottom.
3. Select everything in the editor, paste over it, click **Save**, then **Add to chart**.

It works on XAUUSD, GOLD, GC, US30 and Dow charts, on any timeframe. US100 isn't in the indicator yet. Settings let you move the table or force Gold/US30 if your broker's symbol name isn't recognised.

**Alert when the bias changes:** click **Alert**, set Condition to **Market Brief (live drivers)** and **Any alert() function call**, then pick how you want to be notified (TradingView app, email, or webhook).

**Send TradingView alerts to Telegram.** This needs two-factor login on TradingView and a plan that includes webhooks.
1. Set up the Telegram bot first (part B), and keep the token and chat id handy.
2. In the indicator's settings, put your chat id in **Telegram chat id**.
3. In the alert's Notifications, tick **Webhook URL** and enter
   `https://api.telegram.org/bot<YOUR TOKEN>/sendMessage`

Your own price alerts can go to Telegram the same way. Use the same webhook URL, with this as the alert message:
```
{"chat_id": "<YOUR CHAT ID>", "text": "{{ticker}} hit {{close}}"}
```

---

## F. Staying within the rules

This setup is meant to stay free and within each service's terms, as long as it stays a personal tool:

- **No charges.** GitHub Actions and Pages are free for public repos. The only paid extra is Actions cache storage above 10 GB, and this app uses about 50 MB. Without a payment method on your account, GitHub blocks extra usage rather than billing you.
- **Light on GitHub.** A normal run takes about a minute. Around a big release a run stays on for at most 90 minutes, and it's idle most of that time.
- **Personal use of the data.** Yahoo's price data is for personal use, and the calendar and headlines belong to Forex Factory, Google News and the publishers. GDELT is open data and only asks for credit, which the page gives. The page tells search engines not to list it, credits its sources, and links headlines back to the original articles.
- **Keep it non-commercial.** Don't sell access, run ads on it, or offer the bias as a signal service. That would break the data sources' terms and GitHub's rules for Pages and Actions.

This is a practical summary, not legal advice.

---

## G. Changing things

| File | What it controls |
|---|---|
| `settings.ini` | time zone, symbols, local refresh time |
| `.github/workflows/market-brief.yml` | the online schedule |
| `brief/bias.py` | the bias rules and point weights |
| `brief/leadup.py` | which releases lead into NFP, CPI and PCE, and the usual market reaction |
| `brief/fred.py` | which releases get their actual number from FRED |
| `brief/news.py` | headline searches and keyword lists |
| `brief/dashboard.py` | how the page looks |

To preview layout changes on your PC with made-up data, run `python main.py --demo`.

---

## H. Real release numbers (free FRED key)

FRED is the free data service of the Federal Reserve Bank of St. Louis. With a key, the app shows the actual number for CPI, PCE, PPI, NFP, ADP, jobless claims, JOLTS, retail sales and GDP, and uses those numbers in the lead-up reads. Without a key the app still works and reads everything from the market's reaction.

1. Make a free account at https://fredaccount.stlouisfed.org/apikeys and request an API key.
2. In this repo, open **Settings → Secrets and variables → Actions → New repository secret**. Name it `FRED_API_KEY`, paste the key, and click **Add secret**.

The next update picks it up. If you run the app on your PC instead, put the key under `[fred]` in `settings.ini`. **Never put the key in a file in this repo.**

FRED usually has a number within an hour of the release, so right after a release the actual may still be blank.
