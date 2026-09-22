# Changelog

## 0.5.0

Says something when `candles()` is being used as a live feed.

- **A warning the first time `candles()` is asked for the same instrument
  again before its bar can have changed.** Asking for a 60-second bar twice
  inside 60 seconds cannot return anything new: the newest bar has not closed
  and every older one is already final, so the answer is the previous answer.
  This is the most common mistake made against this API by a wide margin — 57
  candle requests for every stream — and it is what empties a request
  allowance in an afternoon. The server refuses clearly when the allowance is
  gone, and the refusal is read by nobody, because by then the caller is a
  loop. The warning arrives while there is still something to change, and it
  carries the fix as code you can paste.
- Once per client, not once per call: a loop would otherwise bury the message
  it is trying to deliver. Fetching history for five different instruments is
  not polling and says nothing, and neither is re-asking after the bar has
  actually closed.
- Nothing else changed. It is `warnings.warn`, so `-W ignore` silences it and
  no behaviour depends on it.
## 0.4.0

The free tier changed shape on the server, and a client that reports a quota
without its period is worse than one that reports nothing.

- **`Usage.per`** — `"day"` or `"week"`. The free tier now counts by the WEEK
  (1,500) and every paid plan by the day, so `quota` alone is a number over an
  unstated period: 1,500 a week and 1,500 a day are very different products.
  Against a server old enough not to send it, this reads `"day"`, which is what
  everything metered before it was.
- **`Usage.quota_per`** — `"1,500 a week"`, the number and its period together,
  because those are the two things that must never be printed apart.
- `Usage.resets` is unchanged and still the moment the window turns over —
  weekly or daily as the plan dictates. Sleep until it rather than until
  midnight.
- The free tier is now **one book of your choosing**, five instruments on it,
  switchable any time from the account page. It was five books at five
  instruments each.

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
