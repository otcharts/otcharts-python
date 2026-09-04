# Changelog

## 0.2.0

Catches the client up with three API features that shipped after 0.1.0 — the
three a real customer hit walls on, in the order he hit them.

- **`symbols(venue)`** — every instrument a book lists right now, each with the
  exact id `candles()` and `stream()` want. Keeping your own list is how you end
  up asking for something delisted weeks ago and reading an empty response.
- **`usage()`** — plan, books, requests used against the daily quota, when it
  resets, streams open, instruments per stream, keys. **Does not count against
  the quota it reports**, so a loop may check it freely. Without it the only way
  to discover the limit is to be refused at it.
- **`stream()` takes many instruments.** `stream("otc", ["EURUSD_otc",
  "GBPUSD_otc"])` carries them on ONE connection, for one request and one stream
  slot. Fifty pairs polled once a minute is 72,000 requests a day; fifty on one
  stream is one. Every `Tick` carries its own `symbol`. A plain string still
  works unchanged.
- Pocket Option's equities (`#AAPL_otc` and 21 others) are reachable now — the
  server's symbol filter had been rejecting the `#`, so the README documented
  ids the API refused.
- New types `Instrument` and `Usage`, both exported.

Nothing removed, nothing renamed: 0.1.0 code runs unchanged.

## 0.1.0

First release. Reads `/v1/venues`, `/v1/candles` and `/v1/stream` from the OTCharts
data API across five books: Pocket Option, Quotex, IQ Option, BinoDex, and the real
institutional FX feed.

- No dependencies outside the standard library; `pandas` is an optional extra.
- One exception per refusal, including the distinction between `429` from your own
  quota, `429` from your own concurrent-stream limit, and `503` from the service's
  overall ceiling — three different problems that share two status codes.
- Selective stream reconnection: transport failures and `HouseBusy` are retried,
  authentication and plan refusals are not.
