# Massive API Reference (formerly Polygon.io)

How to get real-time and end-of-day US stock prices for multiple tickers from Massive, written for FinAlly.

**Researched:** 2026-11-06, against the official docs and the source of the `massive` Python package (2.2.0, pinned in `backend/uv.lock`, and 2.9.1, the latest release).

**How far this has been tested:** every Python call below was run through the real `massive` client with the HTTP layer faked, using payloads shaped like the official samples. Two unauthenticated requests went to the live API, and on 2026-11-06 a key without snapshot access was tested live. That run confirmed the 403 on snapshots, the end-of-day flow and aggregate timestamps. **Successful snapshot responses have not been observed**, so the snapshot sample, the nanosecond units and `lastTrade` availability still come from the docs.

## What to Know First

1. **The free plan cannot use the snapshot endpoint.** Basic keys get end-of-day data only. `planning/PLAN.md` §6 says "Free tier: poll every 15 seconds", which won't work on Basic. A key without snapshot access gets a 403 (confirmed live).
2. **Pass `market_type` as the string `"stocks"`, not the Enum.** `SnapshotMarketType.STOCKS` builds a broken URL and the live API returns 404.
3. **`LastTrade` has no `timestamp` attribute.** Use `sip_timestamp`, which is in **nanoseconds**.
4. **`day` has no `previous_close` or `change_percent`.** Use `prev_day.close` and `todays_change_percent` on the snapshot itself.
5. **`last_trade` is plan-dependent.** It's only returned if the plan includes trades, so code needs a fallback price.

Items 2 and 3 are live bugs in `backend/app/market/massive_client.py`. See `MARKET_INTERFACE.md`.

## Basics

| Item | Value |
|---|---|
| Base URL | `https://api.massive.com` |
| Auth | `Authorization: Bearer <API_KEY>` header (set automatically by the client) |
| Python package | `massive` on PyPI, repo `massive-com/client-python`. Not the unrelated `massive-api-client` async wrapper |
| Python version | 3.10+ for 2.9.1 |
| Dependencies | `urllib3`, `certifi`, `websockets` |
| Client style | Synchronous. Call it through `asyncio.to_thread()` from async code |

```python
from massive import RESTClient

client = RESTClient()                     # Reads MASSIVE_API_KEY from the environment
client = RESTClient(api_key="your_key")   # Or pass it explicitly
```

Constructor defaults: `connect_timeout=10.0`, `read_timeout=10.0`, `retries=3`, `num_pools=10`. An empty key raises `AuthError`.

```bash
curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT"
```

## Plans and Limits

From the "plan access" sections of the official endpoint pages:

| Stocks plan | Snapshots | Aggregates and previous day | Aggregate history |
|---|---|---|---|
| Basic (free) | **Not included** | End-of-day | 2 years |
| Starter | 15-minute delayed | 15-minute delayed | 5 years |
| Developer | 15-minute delayed | 15-minute delayed | 10 years |
| Advanced | Real-time | Real-time | All (back to 2003-09-10) |
| Business | Real-time | Real-time | All (back to 2003-09-10) |

- **Rate limits are per asset class:** 5 requests a minute for any asset class you haven't subscribed to, and no limit on those you have.
- **Advanced** is listed at $199/month. Other plan prices did not render when the pricing page was read, so check [massive.com/pricing](https://massive.com/pricing).
- **Which plans include trades** (and so `lastTrade`) isn't stated on the pages read. Assume it may be missing below Advanced.

So "real-time" on Massive needs Advanced or Business. Starter and Developer still work with the same code, but prices lag by 15 minutes.

## Which Endpoint for Which Job

| Need | Endpoint | Client method | API calls | Plans |
|---|---|---|---|---|
| **Live prices, many tickers** | Full Market Snapshot | `get_snapshot_all` | 1 | Starter and up |
| Live detail, one ticker | Single Ticker Snapshot | `get_snapshot_ticker` | 1 per ticker | Starter and up |
| Live prices, mixed asset types | Unified Snapshot | `list_universal_snapshots` | 1+ (paged) | Starter and up |
| **End-of-day, many tickers** | Daily Market Summary | `get_grouped_daily_aggs` | 1 per date | All |
| Previous session, one ticker | Previous Day Bar | `get_previous_close_agg` | 1 per ticker | All |
| One date including pre/after-market | Daily Ticker Summary | `get_daily_open_close_agg` | 1 per ticker | All |
| History for charts | Custom Bars | `list_aggs` | 1+ (paged) | All |

The two bold rows are the ones FinAlly needs: each covers every ticker in one call.

## Real-Time Prices: Full Market Snapshot

`GET /v2/snapshot/locale/us/markets/stocks/tickers`

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `tickers` | comma-separated string | all tickers | **Case-sensitive.** No maximum is documented. Omitting it returns 10,000+ tickers |
| `include_otc` | boolean | `false` | Include OTC securities |

```python
from massive import RESTClient

client = RESTClient()
snapshots = client.get_snapshot_all("stocks", ["AAPL", "MSFT", "NVDA"])  # One API call

for snap in snapshots:
    price = snap.last_trade.price if snap.last_trade else None
    previous_close = snap.prev_day.close if snap.prev_day else None
    print(snap.ticker, price, previous_close, snap.todays_change_percent)
```

The docs don't say what happens to an unknown ticker here. Expect it to be missing from the list rather than an error, but confirm that with a real key. The client returns `[]` for an empty `tickers` array without raising.

### Response

```json
{
  "status": "OK",
  "count": 1,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": 2.25,
      "todaysChangePerc": 1.1968,
      "updated": 1762440000123456789,
      "day":       {"o": 189.0, "h": 191.0, "l": 188.0, "c": 190.2, "v": 1000, "vw": 189.9},
      "min":       {"av": 1000, "o": 190.1, "h": 190.3, "l": 190.1, "c": 190.2, "v": 50, "vw": 190.2,
                    "n": 5, "t": 1762439940000},
      "prevDay":   {"o": 188.0, "h": 189.0, "l": 187.0, "c": 188.0, "v": 900, "vw": 188.1},
      "lastTrade": {"p": 190.25, "s": 100, "t": 1762440000123456789, "x": 4, "i": "1", "c": [14]},
      "lastQuote": {"P": 190.3, "S": 2, "p": 190.2, "s": 3, "t": 1762440000123456789}
    }
  ]
}
```

Values are illustrative. The field names are from the official docs.

### JSON to Python Mapping

The client turns the short JSON keys into these attributes:

| JSON | Python | Meaning |
|---|---|---|
| `lastTrade.p` | `snap.last_trade.price` | Latest trade price |
| `lastTrade.s` | `snap.last_trade.size` | Trade size |
| `lastTrade.t` | `snap.last_trade.sip_timestamp` | Trade time, **nanoseconds** |
| `lastQuote.p` / `lastQuote.P` | `snap.last_quote.bid_price` / `.ask_price` | Bid / ask (lowercase `p` is the bid) |
| `min.c` | `snap.min.close` | Latest minute bar close |
| `min.t` | `snap.min.timestamp` | Minute bar time, milliseconds |
| `day.c` | `snap.day.close` | Today's close so far |
| `prevDay.c` | `snap.prev_day.close` | Previous session close |
| `todaysChange` | `snap.todays_change` | Dollar change on the day |
| `todaysChangePerc` | `snap.todays_change_percent` | Percent change on the day |
| `updated` | `snap.updated` | Last update, 19-digit, treated as nanoseconds |

Every field on these models is `Optional`, so expect `None`. The docs also don't say that a populated field is non-zero, so treat `0` as missing.

### Choosing a Price Robustly

```python
def snapshot_price(snap) -> float | None:
    """Freshest usable price. lastTrade depends on the plan; others can be empty."""
    candidates = (
        snap.last_trade.price if snap.last_trade else None,
        snap.min.close if snap.min else None,
        snap.day.close if snap.day else None,
        snap.prev_day.close if snap.prev_day else None,
    )
    return next((p for p in candidates if p is not None and p > 0), None)
```

### Daily Reset

- Snapshot data is **cleared at 3:30 AM EST** and fills again as exchanges report, as early as 4:00 AM EST (official docs). The client's docstring says 12 AM, which disagrees with the docs, so don't rely on it.
- Sessions: pre-market 4:00–9:30, regular 9:30–16:00, after-hours 16:00–20:00 ET.
- During the reset window, `day` and `min` may be empty. `prev_day` is the last field in the fallback chain for this reason.

### Other Snapshot Endpoints

**Single ticker:** `GET /v2/snapshot/locale/us/markets/stocks/tickers/{stocksTicker}`

```python
snap = client.get_snapshot_ticker("stocks", "AAPL")
print(snap.last_quote.bid_price, snap.last_quote.ask_price)
```

**Unified:** `GET /v3/snapshot` takes `ticker.any_of` with up to 250 tickers, and `limit` (default 10, max 250). It's the only snapshot with a documented ticker cap, and it reports `session.previous_close` directly. FinAlly doesn't need it, since it's stocks only.

## End-of-Day Prices: Daily Market Summary

`GET /v2/aggs/grouped/locale/us/market/stocks/{date}`

Returns one OHLCV bar for **every** US stock on a date, so filter locally.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `date` | path, `YYYY-MM-DD` | required | The trading date |
| `adjusted` | boolean | `true` | Split-adjusted prices |
| `include_otc` | boolean | `false` | Include OTC securities |

```python
wanted = {"AAPL", "MSFT", "NVDA"}
bars = client.get_grouped_daily_aggs("2026-11-05", adjusted=True)   # One API call
closes = {bar.ticker: bar.close for bar in bars if bar.ticker in wanted}
```

```json
{
  "status": "OK",
  "adjusted": true,
  "queryCount": 1,
  "resultsCount": 1,
  "results": [
    {"T": "AAPL", "o": 188.0, "h": 189.0, "l": 187.0, "c": 188.0,
     "v": 900, "vw": 188.1, "n": 5, "t": 1762376400000}
  ]
}
```

Attributes: `ticker`, `open`, `high`, `low`, `close`, `volume`, `vwap`, `transactions`, `timestamp` (milliseconds).

**Finding the latest session.** A weekend or holiday has no bars, and a date newer than the plan allows returns 403. In the live test, requesting 2026-11-06 at about 23:16 ET the same day still returned 403 (`Attempted to request today's data before end of day`), so the latest close isn't available right after 16:00 ET on this plan. The previous day returned 12,720 bars. Walk back one weekday at a time until a date returns bars. Each attempt counts against a Basic key's 5 requests a minute, so space them about 12 seconds apart. `MARKET_INTERFACE.md` has a tested implementation.

### Single-Ticker Daily Endpoints

Use these for a handful of tickers only. On Basic, one call per ticker soon exceeds the limit.

**Previous day bar:** `GET /v2/aggs/ticker/{stocksTicker}/prev`. The client returns a one-item **list**, despite its type hint.

```python
bars = client.get_previous_close_agg("AAPL")
print(bars[0].close, bars[0].timestamp)   # timestamp is milliseconds
```

**Open/close for a date:** `GET /v1/open-close/{stocksTicker}/{date}`. The only one with pre-market and after-hours prices.

```python
day = client.get_daily_open_close_agg("AAPL", "2026-11-05")
print(day.open, day.close, day.pre_market, day.after_hours)
```

**Custom bars:** `GET /v2/aggs/ticker/{stocksTicker}/range/{multiplier}/{timespan}/{from}/{to}`. Useful later for seeding the main chart with history. `limit` defaults to 5,000 and caps at 50,000. The client handles paging.

```python
for bar in client.list_aggs("AAPL", 1, "day", "2026-10-01", "2026-10-31", limit=50000):
    print(bar.timestamp, bar.close)
```

## Timestamp Units

Units differ by field, and the Stocks overview page's "seconds since epoch" doesn't match the endpoint pages. Convert everything to seconds at the boundary.

| Field | Unit | To Unix seconds |
|---|---|---|
| `last_trade.sip_timestamp`, `last_quote.sip_timestamp` | Nanoseconds (from 19-digit samples) | `value / 1e9` |
| `snap.updated` | Nanoseconds (from 19-digit samples) | `value / 1e9` |
| `min.timestamp` | Milliseconds | `value / 1e3` |
| Aggregate `timestamp` | Milliseconds | `value / 1e3` |

Aggregate timestamps mark the **end** of the window on the daily market summary and the **start** on previous day and custom bars. A live daily bar's `t` was 21:00 UTC, which is 16:00 ET. For display, use the requested date rather than converting this value.

## Errors

The client has no typed HTTP errors. A non-200 response raises `massive.exceptions.BadResponse`, whose message is the raw response body, so the status code isn't available as an attribute.

| Status | Body | Meaning | What to do |
|---|---|---|---|
| 401 | `{"status":"ERROR","error":"API Key was not provided"}` (seen live) | Missing or invalid key | Log it. Retrying won't help |
| 403 | `{"status":"NOT_AUTHORIZED","message":"You are not entitled to this data..."}` (seen live) | Plan doesn't cover the endpoint, or the data is too recent | Match `"NOT_AUTHORIZED"` in `str(error)` and change approach |
| 404 | `404 page not found` (seen live) | Wrong path | Fix the code |
| 429 | `{"status":"ERROR","error":"You've exceeded the maximum requests per minute..."}` | Rate limited | Wait for the next poll |

**429s and 5xx responses don't raise `BadResponse` once retries run out.** The client retries 413, 429, 499, 500, 502, 503 and 504 through urllib3, and then raises `urllib3.exceptions.MaxRetryError`. With the default `retries=3`, one 429 costs **4 requests** (measured), which is costly at 5 a minute. Pollers should use `RESTClient(retries=0)` and let the next cycle be the retry. Network failures also surface as urllib3 exceptions, so catch `Exception` around a poll.

**Proxies:** `massive` 2.2.0 ignores `HTTPS_PROXY`, which caused a name resolution failure in a proxied environment. 2.9.1 adds a `proxy` argument to `RESTClient`.

## Polling Guidance

| Plan | Mode | Interval |
|---|---|---|
| Basic | End-of-day | About hourly; closes change once a day |
| Starter, Developer | Snapshot, 15 min delayed | 15 s by default. Faster adds little, given the delay |
| Advanced, Business | Snapshot, real-time | 2–5 s |

Keep polling on a timer even outside market hours. It's one cheap request, and it means the app needs no market calendar.

Massive also offers WebSockets, which `PLAN.md` rules out in favour of REST polling.

## Sources

- [Stocks overview](https://massive.com/docs/rest/stocks/overview)
- [Full market snapshot](https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot)
- [Single ticker snapshot](https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot)
- [Unified snapshot](https://massive.com/docs/rest/stocks/snapshots/unified-snapshot)
- [Daily market summary](https://massive.com/docs/rest/stocks/aggregates/daily-market-summary)
- [Daily ticker summary](https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary)
- [Previous day bar](https://massive.com/docs/rest/stocks/aggregates/previous-day-bar)
- [Custom bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars)
- [Request limits](https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis)
- [Pricing](https://massive.com/pricing)
- [Python client source](https://github.com/massive-com/client-python)
