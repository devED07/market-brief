# Market Brief

A gold and US30 bias dashboard that updates itself every 30 minutes.

Each update it:
- pulls this week's US economic calendar (CPI, NFP, FOMC, PCE...)
- checks gold, US30, the dollar index, 10Y T-notes and VIX
- reads the last 12 hours of headlines
- scores gold and US30 from −10 (bearish) to +10 (bullish), and lists the reasons underneath

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

**When it updates** (times shown in Manila time):
- Monday 5am to Saturday 8am: every 30 minutes, at :07 and :37.
- Weekends: every 3 hours, then every 30 minutes again from 5am Monday.
- Around big US releases it stays on, so you get the 15-minute warning and the reaction score on time.

GitHub can start scheduled runs a few minutes late when it's busy. If an update is more than about 75 minutes old, the page marks it in the top bar.

**Update by hand:** open the **Actions** tab, choose **Market Brief**, then **Run workflow**.

**If a run fails:** GitHub emails you. Open the failed run in the Actions tab, copy the red error text, and paste it into a chat with Claude.

---

## B. Telegram alerts (optional)

You'll get a message about 60 and 15 minutes before high-impact US releases, when a release gets scored, and when a bias changes.

1. In Telegram, search for **@BotFather**, send `/newbot` and follow the steps. It gives you a token that looks like `123456789:ABCdef...`.
2. Find your new bot by the name you gave it, and send it any message (for example "hi").
3. In your browser, open this address with your token pasted in:
   `https://api.telegram.org/bot<YOUR TOKEN>/getUpdates`
   Find `"chat":{"id":` followed by a number. That number is your chat id.
4. In the GitHub repo, open **Settings → Secrets and variables → Actions → New repository secret** and add two secrets:
   - Name `TELEGRAM_BOT_TOKEN`, with the token as the value
   - Name `TELEGRAM_CHAT_ID`, with the number as the value
5. Run the workflow by hand (see above). You should get a "Market Brief is connected" message.

**Never put the token in `settings.ini` or any other file here.** The repo is public, and anyone with the token can send messages as your bot.

---

## C. Running it on your own PC instead (optional)

You can also run it on your PC as a local app, with the dashboard opening in your browser.

1. Install Python from [python.org](https://www.python.org/downloads/). On the first screen, tick **"Add python.exe to PATH"**.
2. Download this repo (**Code → Download ZIP**) and extract it somewhere permanent.
3. Double-click **Start Market Brief.bat** (on a Mac: `start_mac.command`). Keep the black window open while you trade.

For phone alerts in this mode, fill in the `[telegram]` part of `settings.ini`. That file stays on your PC, so it's safe there.

---

## D. Reading the dashboard

The big word (Bearish, Leaning bullish, No clear lean...) is the bias. Below it are the five drivers and how many points each one adds:

| Driver | What it measures |
|---|---|
| US data this week | How yields and the dollar reacted in the first 15 minutes after each big US release. Yields and dollar up means hawkish, which is bad for gold and US30. Older releases count less (half weight after 3 days). |
| Dollar and yields | The dollar and 10Y yields over the last 24 hours. |
| Risk mood | VIX. Nervous markets hurt US30 and usually help gold. The exception is when gold falls along with stocks: that's traders selling everything, so fear isn't counted for gold. |
| Headlines | Keyword tags on recent news. |
| Price trend | The market's own direction: the last 24 hours, the last 4 hours, and where price sits against its 5-day average. |

When the data and news point one way but price keeps going the other, the card shows a **Price disagrees** note. That's a sign to wait for price to confirm.

"Drivers are mixed" means low conviction, so let your chart lead.

**Lead-up to the big releases.** For each NFP, CPI or Core PCE in the calendar, the dashboard lists the smaller releases that come before it and whether each came in hot or cold, then says what they hint about the big one:

| Big release | Lead-ins it watches |
|---|---|
| NFP | ADP, jobless claims, ISM services and manufacturing, JOLTS, Challenger job cuts, consumer confidence |
| CPI | PPI, ISM prices paid, import prices, wage growth from the last NFP, inflation expectations |
| Core PCE | CPI, PPI, import prices |

Each lead-in is read from how yields and the dollar reacted to it, because the free calendar doesn't include the actual numbers. Some lead-ins predict better than others. ADP is a weak guide to NFP, while CPI and PPI tell you most of what PCE will show. So each read comes with a confidence level. Scored releases are kept for 45 days, so lead-ins from earlier weeks still count. The Telegram heads-up before each big release includes the lead-up read.

The purple bar at the top warns you before high-impact releases (with a countdown) and right after them. The first 15 to 30 minutes after a release are often noisy and can reverse.

Things to know:
- Prices come from Yahoo and lag about 10 minutes. The dashboard is for bias and timing, not entries. Use your broker chart for those.
- Gold is shown as GC futures, which trade a few dollars above spot XAUUSD. The direction is what matters here.
- The free calendar has the forecast but not the actual number, so the app reads the surprise from how the market reacted.
- This is a personal tool, not financial advice.

---

## E. On your TradingView chart

`tradingview/market_brief_live.pine` is an indicator that shows the live-market part of the bias right on your chart, using TradingView's own prices: dollar and yields, risk mood, and the chart's price trend, with the same rules as the dashboard. US data reactions and headlines aren't available inside TradingView, so for the full bias, check the dashboard. Because the indicator has three of the five drivers, its score can differ from the dashboard's.

**Add it (one time):**
1. In this repo, open `tradingview/market_brief_live.pine` and click the copy button.
2. In TradingView, open a gold or US30 chart, then open **Pine Editor** at the bottom.
3. Select everything in the editor, paste over it, click **Save**, then **Add to chart**.

It works on XAUUSD, GOLD, GC, US30 and Dow charts, on any timeframe. Settings let you move the table or force Gold/US30 if your broker's symbol name isn't recognised.

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
- **Personal use of the data.** Yahoo's price data is for personal use, and the calendar and headlines belong to Forex Factory, Google News and the publishers. The page tells search engines not to list it, credits its sources, and links headlines back to the original articles.
- **Keep it non-commercial.** Don't sell access, run ads on it, or offer the bias as a signal service. That would break the data sources' terms and GitHub's rules for Pages and Actions.

This is a practical summary, not legal advice.

---

## G. Changing things

| File | What it controls |
|---|---|
| `settings.ini` | time zone, symbols, local refresh time |
| `.github/workflows/market-brief.yml` | the online schedule |
| `brief/bias.py` | the bias rules and point weights |
| `brief/news.py` | headline searches and keyword lists |
| `brief/dashboard.py` | how the page looks |

To preview layout changes on your PC with made-up data, run `python main.py --demo`.
