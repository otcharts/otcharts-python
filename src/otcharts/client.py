"""A small client for the OTCharts data API.

Deliberately depends on nothing outside the standard library. The other clients
in this corner of the ecosystem pull in Selenium, a websocket stack and a
validation library before they read their first price, because they have to log
in as you and drive a real browser past a CAPTCHA. This one talks to an HTTP API
with a bearer token, which needs none of that -- so `pip install otcharts`
installs one package and cannot conflict with anything you already have.

    from otcharts import Client

    otc = Client()                                  # reads OTCHARTS_API_KEY
    bars = otc.candles("quotex", "EURUSD_otc", tf=60, limit=300)
    for tick in otc.stream("quotex", "EURUSD_otc"):
        print(tick.time, tick.price)

This reads market data. It does not place orders, hold positions, or touch a
broker account, and it never asks for broker credentials -- see the README.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from dataclasses import dataclass

from .errors import (
    AuthError, HouseBusy, NotFound, OTChartsError, PlanError,
    QuotaExceeded, TooManyStreams, TransportError,
)

__all__ = ["Client", "Candle", "Instrument", "Tick", "Usage", "Venue"]

DEFAULT_BASE = "https://otcharts.com"
USER_AGENT = "otcharts-python/0.5.0 (+https://github.com/otcharts/otcharts-python)"


@dataclass(frozen=True)
class Candle:
    """One recorded bar. `time` is the bar's OPEN, in whole seconds UTC."""
    time: int
    open: float
    high: float
    low: float
    close: float

    @classmethod
    def _from(cls, d):
        return cls(int(d["time"]), float(d["open"]), float(d["high"]),
                   float(d["low"]), float(d["close"]))


@dataclass(frozen=True)
class Tick:
    """One live price. `time` is whole seconds UTC."""
    time: int
    price: float
    symbol: str = ""


@dataclass(frozen=True)
class Venue:
    """A book, and whether your plan opens it."""
    id: str
    open: bool


@dataclass(frozen=True)
class Instrument:
    """One tradable thing in a book.

    `symbol` is the exact string candles() and stream() want for THIS book --
    the same pair is EURUSD_otc on Pocket Option, EURUSD-OTC on IQ and
    EUR/USD-OTC on BinoDex, and they are not interchangeable.
    """
    symbol: str
    name: str


@dataclass(frozen=True)
class Usage:
    """What your plan allows, and what the current window has spent.

    Every number is the ACCOUNT's, shared across all of its keys: a second key
    does not buy a second allowance.

    `per` IS THE ONE TO READ BEFORE THE OTHERS. The free tier counts by the
    WEEK and every paid plan counts by the day, so `quota` on its own is a
    number over an unstated period -- 1,500 a week and 1,500 a day are very
    different products. It is `"week"` or `"day"`, and defaults to `"day"`
    against a server old enough not to send it.

    `resets` is unix seconds at the moment the window turns over, whichever
    window that is, so you can sleep until it rather than compute a midnight
    that may not be the right boundary. `instruments_per_stream` is None on
    Desk, which carries the whole book on one connection.
    """
    plan: str
    plan_name: str
    books: tuple
    used: int
    quota: int
    remaining: int
    resets: int
    per: str
    streams_open: int
    streams_limit: int
    instruments_per_stream: object
    keys: int

    @property
    def quota_per(self):
        """"1,500 a week" — the number and its period, which must not be split."""
        return "{:,} a {}".format(self.quota, self.per)

    @classmethod
    def _from(cls, d):
        req, st = d.get("requests", {}), d.get("streams", {})
        return cls(
            plan=str(d.get("plan", "")),
            plan_name=str(d.get("planName", "")),
            books=tuple(d.get("books", [])),
            used=int(req.get("used", 0)),
            quota=int(req.get("quota", 0)),
            remaining=int(req.get("remaining", 0)),
            resets=int(req.get("resets", 0)),
            # A server from before the weekly free tier sends no `per`, and
            # everything it metered was daily, so that is the honest default.
            per=str(req.get("per") or "day"),
            streams_open=int(st.get("open", 0)),
            streams_limit=int(st.get("limit", 0)),
            instruments_per_stream=st.get("instrumentsPerStream"),
            keys=int(d.get("keys", 0)),
        )


class Client:
    """Talks to the OTCharts data API.

    The key is read from OTCHARTS_API_KEY when not passed, so it never has to
    appear in the source of whatever you are building.
    """

    def __init__(self, api_key=None, base_url=DEFAULT_BASE, timeout=30):
        key = api_key or os.environ.get("OTCHARTS_API_KEY", "")
        if not key:
            raise AuthError(
                "no API key: pass api_key= or set OTCHARTS_API_KEY. "
                "Make one at https://otcharts.com/account.html")
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # When each (venue, symbol, tf) was last asked for, so candles() can
        # notice it is being polled. Bounded by the number of instruments a
        # caller actually uses, which a plan caps anyway.
        self._last_candles = {}
        self._warned_polling = False

    # ── plumbing ───────────────────────────────────────────────────────────
    def _request(self, path, params=None, stream=False):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + self.api_key,
            "User-Agent": USER_AGENT,
            "Accept": "text/event-stream" if stream else "application/json",
        })
        try:
            return urllib.request.urlopen(req, timeout=None if stream else self.timeout)
        except urllib.error.HTTPError as e:
            raise self._refusal(e, stream) from None
        except (urllib.error.URLError, OSError) as e:
            raise TransportError(f"could not reach {self.base_url}: {e}") from None

    @staticmethod
    def _refusal(e, stream):
        """Turn an HTTP status into the exception that says what to DO."""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        try:
            msg = json.loads(body).get("error") or body
        except Exception:
            msg = body
        s = e.code
        if s == 401:
            return AuthError(msg or "key refused", s, body)
        if s in (402, 403):
            # Both mean the same thing to a caller and want the same handler:
            # the key is fine, the plan does not open what was asked for. 402
            # is "no data plan at all"; 403 is a book your plan does not carry,
            # or -- on the free tier -- an instrument outside its five. Left
            # unmapped, 403 arrived as a bare OTChartsError and slipped past
            # the `except PlanError` the README tells people to write, which is
            # the refusal a free-tier key meets first.
            return PlanError(msg or "your plan does not open this", s, body)
        if s == 404:
            return NotFound(msg or "no such venue or symbol", s, body)
        if s == 429:
            # Same status, two different problems. On a stream it means the
            # account is at its own concurrent-stream limit; elsewhere it means
            # the request quota for the window is spent. Telling them apart is the whole
            # reason this function exists.
            cls = TooManyStreams if stream else QuotaExceeded
            return cls(msg or "limit reached", s, body)
        if s == 503:
            try:
                wait = int(e.headers.get("Retry-After") or 30)
            except (TypeError, ValueError):
                wait = 30
            return HouseBusy(msg or "the service is at its stream ceiling",
                             s, body, retry_after=wait)
        return OTChartsError(msg or f"HTTP {s}", s, body)

    # ── endpoints ──────────────────────────────────────────────────────────
    def venues(self):
        """Every book, and whether your plan opens it.

        All five are always listed whatever you hold -- a short list could not
        tell a plan limit from a missing feature.
        """
        with self._request("/v1/venues") as r:
            data = json.loads(r.read().decode())
        return [Venue(v["id"], bool(v.get("open"))) for v in data.get("venues", [])]

    def symbols(self, venue):
        """Every instrument a book lists right now.

        Use this instead of keeping your own list. A book drops instruments it
        stops quoting, and a hand-written list goes stale silently -- the first
        thing you notice is an empty response for a pair that was delisted
        weeks ago. Costs one request, like any other call.
        """
        with self._request("/v1/symbols", {"venue": venue}) as r:
            data = json.loads(r.read().decode())
        return [Instrument(str(i["symbol"]), str(i.get("name", i["symbol"])))
                for i in data.get("symbols", [])]

    def usage(self):
        """Your plan, and what today has spent against it.

        FREE: this call does not count against the quota it reports, so a loop
        may check it as often as it likes. Charging for the question would make
        the answer wrong as it was given.

            u = otc.usage()
            if u.remaining < 500:
                time.sleep(u.resets - time.time())
        """
        with self._request("/v1/usage") as r:
            return Usage._from(json.loads(r.read().decode()))

    def candles(self, venue, symbol, tf=60, limit=300):
        """Recorded bars from the venue's own history, oldest first.

        tf is in seconds; limit is 1-5000.
        """
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        self._note_candles(venue, symbol, tf)
        with self._request("/v1/candles", {
            "venue": venue, "symbol": symbol, "tf": tf, "limit": limit,
        }) as r:
            data = json.loads(r.read().decode())
        return [Candle._from(c) for c in data.get("candles", [])]

    def _note_candles(self, venue, symbol, tf):
        """Say something the first time candles() is used as a live feed.

        WHY THIS IS IN THE LIBRARY. Asking for the same bars on a timer is the
        most common mistake made against this API by a wide margin -- 57 candle
        requests for every stream -- and it is what empties a free allowance in
        an afternoon. The server already refuses clearly when the allowance is
        gone, and the refusal goes unread, because by then the caller is a loop
        and nobody is watching. A warning in the caller's own console arrives
        while there is still something to change.

        The test is not a guess: asking for a tf-second bar again before tf
        seconds have passed cannot return anything new. The newest bar has not
        closed and every older one is already final, so the answer is the
        previous answer.

        Once per client, not once per call -- a loop would otherwise bury the
        message it is trying to deliver.
        """
        if self._warned_polling:
            return
        try:
            tf = int(tf)
        except (TypeError, ValueError):
            return
        if tf <= 0:
            return
        now = time.monotonic()
        key = (venue, str(symbol), tf)
        last = self._last_candles.get(key)
        self._last_candles[key] = now
        if last is None or now - last >= tf:
            return
        self._warned_polling = True
        warnings.warn(
            "otcharts: candles(%r, %r, tf=%d) was called again after %.1fs. "
            "A %d-second bar only changes every %d seconds, so this answer is "
            "the last one. Polling like this is what exhausts a request "
            "allowance: five instruments once a minute is 7,200 requests a day, "
            "while the same five on ONE stream is one request. Use "
            "candles() once for history, then stream() for what follows:\n"
            "    for tick in otc.stream(%r, [%r]):\n"
            "        print(tick.symbol, tick.price)\n"
            "See https://otcharts.com/api#stream"
            % (venue, symbol, tf, now - last, tf, tf, venue, symbol),
            stacklevel=3,
        )

    @staticmethod
    def _symbol_param(symbol):
        """One symbol, or several, as the API wants them.

        Accepts a string or any sequence, so both of these work:

            otc.stream("otc", "EURUSD_otc")
            otc.stream("otc", ["EURUSD_otc", "GBPUSD_otc", "XAUUSD_otc"])

        Duplicates are dropped in the order given -- asking for the same pair
        twice would otherwise spend two places against the plan's cap.
        """
        if isinstance(symbol, str):
            parts = symbol.split(",")
        else:
            parts = list(symbol)
        out = []
        for part in parts:
            part = str(part).strip()
            if part and part not in out:
                out.append(part)
        if not out:
            raise ValueError("give at least one symbol")
        return ",".join(out)

    def stream(self, venue, symbol, reconnect=True, max_backoff=60):
        """Live prices, as a generator that yields Tick.

        `symbol` may be ONE instrument or a list of them:

            for tick in otc.stream("otc", ["EURUSD_otc", "GBPUSD_otc"]):
                print(tick.symbol, tick.price)

        One connection carrying ten instruments costs one request and one
        stream slot -- the same as carrying one. That is the difference between
        following a watchlist and exhausting a request quota polling it: fifty
        pairs asked for once a minute is 72,000 requests a day, while fifty
        pairs on one stream is one. Every Tick carries its own `symbol`, so a
        single loop can sort them.

        How many instruments one stream may carry is a property of your plan --
        `usage().instruments_per_stream`, or None for no limit. Asking for more
        than that is refused with a message naming the number. Only the Pocket
        Option book (`otc`) carries several on one connection today; the others
        take one symbol per stream, because there a second instrument really is
        a second connection.

        Read the `connected` event's symbol list if you need to know what the
        book actually subscribed you to: an instrument that is not quoting right
        now is dropped rather than held open, so a weekend list of forty may
        come back as twenty-seven. Nothing has failed.

        Reconnection is ON by default and deliberately does NOT retry
        everything. A dropped socket is worth retrying; a revoked key, or a
        book or instrument the plan does not open, will fail identically
        forever, and a client that hammers a 402 or 403 in a loop is a client
        that gets its account limited.
        So only transport failures and HouseBusy are retried -- and HouseBusy is
        retried after the delay the server asked for, not sooner.
        """
        wanted = self._symbol_param(symbol)
        backoff = 1.0
        while True:
            try:
                yield from self._stream_once(venue, wanted)
                if not reconnect:
                    return
                # A clean end of stream still means the feed stopped; pause
                # briefly rather than spin reopening it.
                time.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2, max_backoff)
            except HouseBusy as e:
                if not reconnect:
                    raise
                time.sleep(e.retry_after)
            except TransportError:
                if not reconnect:
                    raise
                time.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2, max_backoff)

    def _stream_once(self, venue, wanted):
        r = self._request("/v1/stream", {"venue": venue, "symbol": wanted},
                          stream=True)
        # With several instruments on one connection the caller's parameter is
        # no longer a sensible fallback for an unlabelled tick -- it would tag
        # every price with the whole comma list. A tick without a symbol is
        # only ever a single-symbol stream, so fall back to that and to "" when
        # there is more than one.
        default = wanted if "," not in wanted else ""
        try:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                # Keepalive comments hold the connection open through proxies
                # that kill idle streams; they carry no data.
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    d = json.loads(payload)
                except ValueError:
                    continue
                price = d.get("price", d.get("close"))
                if price is None:
                    continue
                yield Tick(int(d.get("time", 0)), float(price),
                           str(d.get("symbol", default)))
        finally:
            r.close()

    # ── convenience ────────────────────────────────────────────────────────
    def dataframe(self, venue, symbol, tf=60, limit=300):
        """The same bars as a pandas DataFrame, indexed by UTC timestamp.

        pandas is an optional extra rather than a dependency: most callers want
        JSON, and forcing a 60MB install on them to read five prices is rude.
        """
        try:
            import pandas as pd
        except ImportError:
            raise OTChartsError(
                "dataframe() needs pandas: pip install 'otcharts[pandas]'") from None
        rows = self.candles(venue, symbol, tf=tf, limit=limit)
        df = pd.DataFrame([vars(c) for c in rows])
        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.set_index("time")
        return df
