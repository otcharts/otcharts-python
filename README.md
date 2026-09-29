# otcharts

Market data from the OTC books of four binary options brokers — **Pocket Option,
Quotex, IQ Option, BinoDex** — and the real institutional FX market, as JSON.
One dependency-free Python package for trading research, backtesting and live
signal work.

**Free to try, with no card.** Every confirmed account reads one book of its
choosing, five instruments on it, 1,500 requests a week, and one live stream
carrying one instrument.
The example below runs on that.

```bash
pip install otcharts
```

```python
from otcharts import Client

otc = Client()                                      # reads OTCHARTS_API_KEY

for i in otc.symbols("otc"):                        # never guess an id
    print(i.symbol, i.name)

bars = otc.candles("iq", "EURUSD-OTC", tf=60, limit=300)
print(bars[-1].close)

# Live prices. The free tier's stream carries one instrument; from Lite up a
# Pocket Option stream carries a whole watchlist on one connection.
for tick in otc.stream("otc", "EURUSD_otc"):
    print(tick.symbol, tick.price)
```

## Read this before you install

**This reads prices. It does not place trades.** No orders, no positions, no account
balance. If you came here looking for a way to automate trading on one of these
platforms, this is the wrong package and you should stop here rather than pay for it.

**You never give anyone your broker password.** Unlike the community wrappers, this
does not log in as you, drive a browser, or hold your broker session. It talks to an
HTTP API with a key that is yours, and the connection to the venue is held on the
server side.

**Not affiliated** with Pocket Option, Quotex, IQ Option, or BinoDex. Their names
appear here to say which price feed the data comes from, nothing more.

## Why this exists

None of these platforms publishes an official API. What exists is a handful of
community wrappers that log in with your credentials, drive Selenium past a CAPTCHA,
and break quietly when the platform changes its socket format. They are often good
work, and if you need to place orders they are the only route there is.

But if all you wanted was the prices, that is a lot of moving parts — and a lot of
risk to an account — to read a number. This package reads the number.

## Install

```bash
pip install otcharts              # no dependencies
pip install 'otcharts[pandas]'    # adds .dataframe()
```

Requires Python 3.8+. The package imports nothing outside the standard library, so it
cannot conflict with whatever you already have pinned.

## Getting a key

1. Make an account at [otcharts.com](https://otcharts.com/) and confirm the address
2. Create a key on your [account page](https://otcharts.com/account) — it is shown
   once, and only a hash is stored, so nobody can recover it afterwards, including us
3. `export OTCHARTS_API_KEY=otc_live_...`

That key works immediately on the **free tier**. No card, no trial clock, nothing
expires:

| | free tier |
|---|---|
| books | one, whichever you pick — switchable any time |
| instruments on it | five, the same five the free chart opens |
| requests | **1,500 a week** |
| live streams | one, carrying one instrument |
| payout percentages | `null` — the data plans carry them |
| keys | five, each named and revocable |
| older history | the live window only — `before=` and `history()` are Build and up |

The free tier counts by the **week**; every paid plan counts by the day.
`usage().per` tells you which and `usage().resets` is when the window turns
over, so nothing has to assume a midnight that may not be the right boundary:

```python
u = otc.usage()
print(u.quota_per)        # "1,500 a week"  — the number and its period together
print(u.remaining, "left until", u.resets)
```

`symbols(venue)` lists exactly what your key can read, so on the free tier it
returns those five rather than a catalogue of refusals. Asking for a sixth
raises `PlanError`, and the message names the five that are open.

A [paid plan](https://otcharts.com/pricing#api) opens the whole of a book and
raises the quotas. It is the same key and the same code either way.

## The books, and their symbol formats

Ids are **not** portable between books. This catches everyone once:

| venue | book | a symbol looks like |
|---|---|---|
| `otc` | Pocket Option | `EURUSD_otc`, `#AAPL_otc` (equities take a `#`); times are the broker's clock, UTC+2 |
| `quotex` | Quotex | `EURUSD_otc` |
| `iq` | IQ Option | `EURUSD-OTC` (hyphen, uppercase) |
| `binodex` | BinoDex | `EUR/USD-OTC` (slash), `TRX-OTC` |
| `forex` | Real market, institutional feed | `EURUSD` |

```python
otc.venues()            # every book, and whether your plan opens it
otc.symbols("otc")      # every instrument in one, with the exact id to send
```

Do not keep your own list. A book drops instruments it stops quoting, and a
hand-written list goes stale silently — the first thing you notice is an empty
response for a pair delisted weeks ago. `symbols()` is the live catalogue;
[the cross-reference](https://otcharts.com/symbols) is the same thing for
a human, all five books side by side.

## Errors that tell you what to do

The API distinguishes its refusals, and so does this package. In particular
**`429` means two different things**, and they have different fixes:

```python
from otcharts import QuotaExceeded, TooManyStreams, HouseBusy, PlanError

try:
    ...
except QuotaExceeded:      # 429 on a request — the window's quota is spent
    ...
except TooManyStreams:     # 429 on a stream — YOUR account's concurrent limit
    ...                    #   close one of your streams
except HouseBusy as e:     # 503 — the service as a whole is at its ceiling.
    time.sleep(e.retry_after)   # not your fault, not fixed by upgrading
except PlanError:          # 402/403 — key is fine; the plan does not open this
    ...                    #   book, this instrument, or paging back with before=
```

`AuthError` (401) is worth one note: a password reset revokes every API key on the
account, so a key that worked yesterday may simply have been revoked.

## Knowing where you stand

```python
u = otc.usage()
print(u.used, "of", u.quota, "-", u.remaining, "left")
print("resets at", u.resets)                  # unix seconds, next midnight UTC
print(u.instruments_per_stream, "per stream") # None on Desk: the whole book
```

**This call is free** — it does not count against the quota it reports, so a
loop may check it as often as it likes. Every figure is the *account's*, shared
across all of its keys: a second key does not buy a second allowance.

```python
if u.remaining < 500:
    time.sleep(u.resets - time.time())        # rather than find out by refusal
```

## Streaming

One connection, and on Pocket Option's book it can carry **many instruments**
(from Lite up; the free tier's stream carries one):

```python
for tick in otc.stream("otc", ["EURUSD_otc", "GBPUSD_otc", "XAUUSD_otc"]):
    print(tick.symbol, tick.price)        # every tick names its own instrument
```

This is the difference between following a watchlist and exhausting a quota
polling it. Fifty pairs asked for once a minute is **72,000 requests a day**;
fifty pairs on one stream is **one**, and holding it costs nothing further.

How many one stream may carry is a property of your plan —
`usage().instruments_per_stream`, or `None` for no limit. Ask for more and the
refusal names the number. Several instruments on one connection is a Pocket
Option (`otc`) feature today; the other books take one symbol per stream,
because there a second instrument really is a second connection.

A single symbol still works exactly as before:

```python
for tick in otc.stream("quotex", "EURUSD_otc"):
    ...
```

The book subscribes you only to what is quoting right now, so a weekend list of
forty may come back as twenty-seven. Nothing has failed; an instrument that is
not trading is dropped rather than held open.

Reconnection is on by default and is deliberately selective. Dropped sockets and
`HouseBusy` are retried — `HouseBusy` after the delay the server asks for. A revoked
key or a plan that does not open the book is **not** retried, because it will fail
identically forever and a client hammering a 402 in a loop is a client that gets
limited. Pass `reconnect=False` to handle it yourself.

## Older history

`candles()` reads the live window: the newest bars the book holds right now.
Behind it sits each venue's archive — about two years of 1-minute bars on the
real market, a year on Pocket Option — and `before=` pages back through it:

```python
older = otc.candles("forex", "EURUSD", tf=60, limit=450, before=bars[0].time)
```

`before` is a unix time in seconds and the reply is the newest `limit` bars
**strictly older** than it, so chaining `bars[0].time` walks back. `history()`
does the chaining for you, reads the reply's `exhausted` flag, and stops at
`since`:

```python
bars = list(otc.history("forex", "EURUSD", tf=60, since=1_756_684_800))
bars.reverse()                    # it walks backward, so it yields backward
```

Three things worth knowing before a long walk:

- **Every page is one request.** A year of 1-minute bars is about 525,600 of
  them, so roughly 1,170 pages of 450. The venues answer at most 1,500 bars a
  page (Quotex 500) and trim anything larger, so a bigger `page` costs the
  same number of requests.
- **The clock is the venue's.** Pocket Option stamps its bars two hours ahead
  of UTC; the other books are true UTC. `since` and `before` are read on that
  clock, which is why anchoring on a `time` the server gave you is safer than
  one you computed — `history()` only ever does the former.
- **It is a paid feature, Build and up.** The free tier reads the live window
  only: `history()` yields it, then raises `PlanError` with the pricing link.
  BinoDex keeps no archive yet and refuses `before=` with a 400.

A walk that was interrupted resumes from the oldest `time` it reached:
`history(..., before=oldest)`. Nothing is retried for you.

## pandas

```python
df = otc.dataframe("quotex", "EURUSD_otc", tf=60, limit=1000)
```

Optional on purpose — most callers want JSON, and a 60MB install to read five prices
is rude.

## One thing about this data

An instrument named after gold or EUR/USD on an OTC book is **the venue's own price**,
not the underlying market, and it can drift from it. That is how these books work. If
you are modelling this data, treat each series as its own thing rather than as a proxy
for the market it is named after — and note that `venue="forex"` carries the real
institutional feed, so the two can be compared directly.

## Development

```bash
git clone https://github.com/otcharts/otcharts-python
cd otcharts-python
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests run against a real HTTP server on loopback rather than a mocked transport,
so the headers, the status handling and the SSE parsing are genuinely exercised. No
test touches the network.

## Links

- [API reference](https://otcharts.com/api) — one page, the whole contract
- [Pocket Option API](https://otcharts.com/pocket-option-api) ·
  [Quotex API](https://otcharts.com/quotex-api) ·
  [IQ Option API](https://otcharts.com/iq-option-api) ·
  [BinoDex API](https://otcharts.com/binodex-api)

## Licence

MIT. Nothing here is financial advice and no result is promised.
