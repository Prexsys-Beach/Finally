# Market Simulator

How FinAlly simulates stock prices when no `MASSIVE_API_KEY` is set: the approach, the code structure, and how it actually behaves.

**Status:** built and working in `backend/app/market/`. Measurements below were taken by running the real `GBMSimulator` on 2026-11-06, unless marked as calculated. The changes under "Required Changes" have been applied.

Related docs: `MARKET_INTERFACE.md` (the interface it implements).

## Goals

- Work with no API key, no network and no setup.
- Look alive: prices tick every 500 ms and flash green and red.
- Look plausible: stocks move together, volatile names move more, and prices never go negative.
- Provide some drama for demos through occasional sudden moves.

It's a demo engine, not a market model. There's no order book, no opening or closing, and no link to real prices.

## Approach

Each tick has three steps:

1. Draw one random number per ticker, correlated across tickers.
2. Move each price with Geometric Brownian Motion (GBM).
3. Occasionally apply a sudden 2–5% shock to a ticker.

### Geometric Brownian Motion

GBM is the standard simple model for stock prices. Returns are random, and the price is multiplied each step, so it can't go negative.

```
S(t+dt) = S(t) * exp((mu - sigma²/2) * dt + sigma * sqrt(dt) * Z)
```

| Symbol | Meaning |
|---|---|
| `S(t)` | Current price |
| `mu` | Annual drift (expected return), e.g. `0.05` for 5% |
| `sigma` | Annual volatility, e.g. `0.22` for 22% |
| `dt` | Time step, as a fraction of a trading year |
| `Z` | Correlated standard normal draw |

A 500 ms tick is a tiny share of a trading year:

```
dt = 0.5 / (252 days * 6.5 hours * 3600 seconds) = 0.5 / 5,896,800 ≈ 8.48e-8
```

Simulated time matches wall-clock time: one real second is one second of trading. The simulator runs nonstop, with no closed periods.

### Correlated Moves

Real stocks move together, so independent draws would look wrong. We build a correlation matrix `C`, take its Cholesky factor `L`, and multiply it by independent normals:

```
L = cholesky(C)
Z_correlated = L @ Z_independent
```

Each pair's correlation comes from sector membership:

| Pair | Correlation | Measured over 200,000 ticks |
|---|---|---|
| Both tech (AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX) | 0.6 | AAPL/MSFT 0.601 |
| Both finance (JPM, V) | 0.5 | JPM/V 0.500 |
| TSLA with anything | 0.3 | TSLA/AAPL 0.301, TSLA/JPM 0.299 |
| Cross-sector or unknown ticker | 0.3 | AAPL/JPM 0.300 |

`L` is rebuilt whenever a ticker is added or removed. The default values worked for 10, 50 and 200 tickers. `np.linalg.cholesky` raises `LinAlgError` if a matrix isn't positive definite, so re-test at a large ticker count if you change these constants.

### Random Events

After the GBM step, each ticker has a 0.1% chance per tick of a shock:

```python
if random.random() < self._event_prob:
    shock_magnitude = random.uniform(0.02, 0.05)
    shock_sign = random.choice([-1, 1])
    self._prices[ticker] *= 1 + shock_magnitude * shock_sign
```

With 10 tickers at 2 ticks a second, that predicts one event every 50 seconds. We measured one every 49 seconds. Events are independent, so one ticker jumps alone.

### Parameters

All of these live in `seed_prices.py`.

| Ticker | Seed price | `sigma` | `mu` | Note |
|---|---|---|---|---|
| AAPL | $190 | 0.22 | 0.05 | |
| GOOGL | $175 | 0.25 | 0.05 | |
| MSFT | $420 | 0.20 | 0.05 | |
| AMZN | $185 | 0.28 | 0.05 | |
| TSLA | $250 | 0.50 | 0.03 | High volatility |
| NVDA | $800 | 0.40 | 0.08 | High volatility, strong drift |
| META | $500 | 0.30 | 0.05 | |
| JPM | $195 | 0.18 | 0.04 | Low volatility |
| V | $280 | 0.17 | 0.04 | Low volatility |
| NFLX | $600 | 0.35 | 0.05 | |
| Any other | Random $50–$300 | 0.25 | 0.05 | `DEFAULT_PARAMS` |

## Code Structure

```
backend/app/market/
├── seed_prices.py    Constants only: seed prices, parameters, correlations
├── simulator.py      GBMSimulator (the maths) + SimulatorDataSource (the async wrapper)
├── interface.py      MarketDataSource, the contract
└── cache.py          PriceCache, where prices are written
```

```
SimulatorDataSource                       owns the async task and the cache
    │  start(): creates GBMSimulator, seeds the cache, starts the loop
    │  every 500 ms:
    ▼
GBMSimulator.step() ──▶ {"AAPL": 190.12, ...} ──▶ PriceCache.update()
```

The split keeps `GBMSimulator` synchronous and free of I/O, so tests can call `step()` in a tight loop with no event loop.

### `GBMSimulator`

| Method | Purpose |
|---|---|
| `step() -> dict[str, float]` | Advances all tickers once. Returns prices rounded to 2 dp |
| `add_ticker(ticker)` / `remove_ticker(ticker)` | Changes the set and rebuilds `L` |
| `get_price(ticker)` | Current unrounded price, or `None` |
| `get_tickers()` | Copy of the tracked list |

Constructor: `GBMSimulator(tickers, dt=DEFAULT_DT, event_probability=0.001)`.

The core of `step()`:

```python
z_independent = np.random.standard_normal(n)
z_correlated = self._cholesky @ z_independent if self._cholesky is not None else z_independent

for i, ticker in enumerate(self._tickers):
    params = self._params[ticker]
    mu, sigma = params["mu"], params["sigma"]

    drift = (mu - 0.5 * sigma**2) * self._dt
    diffusion = sigma * math.sqrt(self._dt) * z_correlated[i]
    self._prices[ticker] *= math.exp(drift + diffusion)

    # ...then the random event shown above
    result[ticker] = round(self._prices[ticker], 2)
```

Internal prices stay unrounded so that rounding errors don't build up. With fewer than two tickers, `_cholesky` is `None` and the draws are used directly.

### `SimulatorDataSource`

Implements `MarketDataSource`. Constructor: `SimulatorDataSource(price_cache, update_interval=0.5, event_probability=0.001)`.

- `start()` builds the simulator and writes seed prices to the cache at once, so SSE has data on its first read.
- `add_ticker()` writes the new ticker's price at once, so it shows up without waiting for a tick.
- `remove_ticker()` also removes the ticker from the cache.
- The loop catches and logs exceptions from `step()`, so one bad tick can't stop the stream.

```python
async def _run_loop(self) -> None:
    while True:
        try:
            if self._sim:
                for ticker, price in self._sim.step().items():
                    self._cache.update(ticker=ticker, price=price)
        except Exception:
            logger.exception("Simulator step failed")
        await asyncio.sleep(self._interval)
```

## Measured Behaviour

### Per-Tick Moves

Over 200,000 ticks with events turned off:

| Ticker | Typical move per tick | Ticks with no visible change |
|---|---|---|
| JPM | $0.010 | 36% |
| AAPL | $0.012 | 31% |
| GOOGL | $0.013 | 30% |
| V | $0.014 | 28% |
| AMZN | $0.015 | 26% |
| MSFT | $0.025 | 16% |
| TSLA | $0.036 | 11% |
| META | $0.044 | 9% |
| NFLX | $0.061 | 6% |
| NVDA | $0.093 | 4% |

Moves are generally a cent or more. A "no change" tick happens when the move rounds away at 2 dp, and that tick gets `direction: "flat"` with no flash. So low-priced, calm tickers flash less often, which looks natural.

### Events Dominate Over Time

Events matter far more than GBM to how far prices travel. For AAPL, using 20,000 paths from a NumPy model of the same formulas and parameters (not the `GBMSimulator` class):

| Run length | GBM only: spread | With events: spread | Median move | Average events |
|---|---|---|---|---|
| 1 hour | 0.54% | **9.75%** | -0.5% | 7.2 |
| 6.5 hours | 1.38% | **24.86%** | -3.1% | 46.7 |

Two consequences:

- **`sigma` barely matters in a long session.** Over an hour, a ticker's spread comes almost entirely from events, so TSLA and V end up looking alike despite their different `sigma`.
- **Prices tend to sink slowly.** A +3% and a -3% event don't cancel: `1.03 × 0.97 = 0.9991`. So the median price falls, even though the mean stays roughly flat.

This suits a demo of a few minutes, where drama is the goal. It's the main thing to adjust if long sessions look too wild. Event rates and their calculated effect, for 10 tickers:

| `event_probability` | An event every | Spread after 1 hour |
|---|---|---|
| 0.001 (current) | 50 s | about 9.7% |
| 0.0003 | 3 min | about 5.3% |
| 0.0001 | 8 min | about 3.1% |

### Performance

`step()` took well under 1 ms even at 200 tickers, and building the simulator took single-digit milliseconds. Rebuilding `L` is O(n³), but the sizes here make that irrelevant. The simulator adds no meaningful load.

## Known Limitations

- **Daily change has no real day.** There's no session boundary, so "daily change" means change since the app started.
- **Prices restart on each launch.** Nothing is saved, so a position bought at a drifted price will show an immediate gain or loss after a restart, because the ticker has returned to its seed price.
- **New tickers get a random price.** An unknown ticker starts between $50 and $300, and the price differs each time it's added.
- **Results aren't reproducible.** The code uses the global `random` and `np.random` state. Tests should assert properties, or set both seeds.
- **Correlation is approximate.** Shocks are independent, so a ticker's correlation with others weakens over a long run with events.
- **Comment drift.** A comment in `_pairwise_correlation` says TSLA is in the tech set, but it isn't. `TSLA_CORR` and `CROSS_GROUP_CORR` are both 0.3, so the TSLA branch changes nothing unless they diverge.

## Required Changes

Both are part of the wider plan in `MARKET_INTERFACE.md`.

**Normalise tickers.** `add_ticker("aapl")` currently adds a second instrument at a random price, alongside `AAPL`. Fix: call `normalize_ticker()` in `start()`, `add_ticker()` and `remove_ticker()`.

**Publish a daily reference price.** The watchlist needs a daily change figure. Seeding the cache with a `previous_close` is enough, because the cache keeps it across later updates, so the loop doesn't change.

```python
    @property
    def mode(self) -> DataMode:
        return "simulated"

    def _seed_cache(self, ticker: str) -> None:
        """Publish a starting price. It is also the reference for daily change."""
        price = self._sim.get_price(ticker)
        if price is not None:
            self._cache.update(ticker=ticker, price=price, previous_close=price)
```

`start()` and `add_ticker()` then call `self._seed_cache(ticker)` instead of writing to the cache themselves.

**Correct the `GBMSimulator` docstring,** which said "sub-cent moves".

## Optional Tuning

Neither of these is needed for the demo, so leave them unless long sessions look wrong.

**Calm the events** by lowering `event_probability` in `SimulatorDataSource`. `0.0003` keeps regular drama, and it restores some difference between calm and volatile tickers.

**Remove the downward pull** by making shocks symmetric in log terms:

```python
self._prices[ticker] *= math.exp(shock_magnitude * shock_sign)
```

## Testing

The tests in `backend/tests/market/test_simulator.py` and `test_simulator_source.py` pass. Keep these properties covered:

- Prices stay positive and `step()` returns every tracked ticker.
- Add and remove rebuild the matrix, including going down to one ticker and to none.
- The Cholesky build succeeds for the full default set plus many unknown tickers.
- `event_probability=0` produces no moves beyond GBM scale.
- Measured correlations match the targets on a large sample.
- Mixed-case tickers don't create duplicates.

For a visual check, run the terminal dashboard:

```bash
cd backend
uv run market_data_demo.py
```
