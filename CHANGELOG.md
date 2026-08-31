# Changelog

## 0.1.0 — unreleased

First release. Reads `/v1/venues`, `/v1/candles` and `/v1/stream` from the OTCharts
data API across five books: Pocket Option, Quotex, IQ Option, BinoDex, and the real
institutional FX feed.

- No dependencies outside the standard library; `pandas` is an optional extra.
- One exception per refusal, including the distinction between `429` from your own
  quota, `429` from your own concurrent-stream limit, and `503` from the service's
  overall ceiling — three different problems that share two status codes.
- Selective stream reconnection: transport failures and `HouseBusy` are retried,
  authentication and plan refusals are not.
