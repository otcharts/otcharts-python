"""Tests against a real HTTP server on loopback, not a mocked urlopen.

Mocking the transport would test that the code calls the function it calls.
These start a stdlib server that answers the way the real API answers, so the
header, the status handling and the SSE parsing are all genuinely exercised --
and no test touches the network.
"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import otcharts
from otcharts import (
    AuthError, Client, HouseBusy, NotFound, PlanError,
    QuotaExceeded, TooManyStreams,
)

ROUTES = {}          # path -> (status, headers, body)
SEEN = {}            # path -> the full request line, query and all


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        SEEN[path] = self.path
        if self.headers.get("Authorization") != "Bearer test-key":
            self._send(401, {}, json.dumps({"error": "key refused"}))
            return
        status, headers, body = ROUTES.get(path, (404, {}, '{"error":"nope"}'))
        self._send(status, headers, body)

    def _send(self, status, headers, body):
        raw = body.encode()
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def client(self, key="test-key"):
        return Client(api_key=key, base_url=f"http://127.0.0.1:{self.port}",
                      timeout=5)


class TestReading(Base):
    def test_candles_parse_in_order(self):
        ROUTES["/v1/candles"] = (200, {}, json.dumps({"candles": [
            {"time": 100, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15},
            {"time": 160, "open": 1.15, "high": 1.3, "low": 1.1, "close": 1.25},
        ]}))
        bars = self.client().candles("quotex", "EURUSD_otc")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].time, 100)
        self.assertEqual(bars[1].close, 1.25)
        self.assertLess(bars[0].time, bars[1].time, "oldest first")

    def test_venues_lists_every_book(self):
        ROUTES["/v1/venues"] = (200, {}, json.dumps({"venues": [
            {"id": "otc", "open": False}, {"id": "quotex", "open": True},
        ]}))
        vs = self.client().venues()
        self.assertEqual([v.id for v in vs], ["otc", "quotex"])
        self.assertFalse(vs[0].open)
        self.assertTrue(vs[1].open)

    def test_limit_is_checked_before_the_request(self):
        for bad in (0, 5001, -1):
            with self.assertRaises(ValueError):
                self.client().candles("quotex", "EURUSD_otc", limit=bad)


class TestRefusals(Base):
    """Each refusal must arrive as the exception that says what to DO."""

    def test_bad_key_is_auth_error(self):
        with self.assertRaises(AuthError):
            self.client(key="wrong").venues()

    def test_no_plan_is_plan_error_not_auth_error(self):
        ROUTES["/v1/candles"] = (402, {}, json.dumps(
            {"error": "this account has no data plan"}))
        with self.assertRaises(PlanError):
            self.client().candles("iq", "EURUSD-OTC")

    def test_unknown_symbol_is_not_found(self):
        ROUTES["/v1/candles"] = (404, {}, json.dumps({"error": "no such symbol"}))
        with self.assertRaises(NotFound):
            self.client().candles("iq", "NOPE")

    def test_429_on_a_request_is_quota(self):
        ROUTES["/v1/candles"] = (429, {}, json.dumps({"error": "daily quota spent"}))
        with self.assertRaises(QuotaExceeded):
            self.client().candles("quotex", "EURUSD_otc")

    def test_429_on_a_stream_is_the_accounts_own_stream_limit(self):
        """Same status as the quota case, entirely different fix.

        Collapsing these two into one exception would tell someone holding ten
        streams that they had run out of daily requests.
        """
        ROUTES["/v1/stream"] = (429, {}, json.dumps({"error": "too many streams"}))
        gen = self.client().stream("quotex", "EURUSD_otc", reconnect=False)
        with self.assertRaises(TooManyStreams):
            next(gen)

    def test_503_is_house_busy_and_carries_retry_after(self):
        ROUTES["/v1/stream"] = (503, {"Retry-After": "45"},
                                json.dumps({"error": "house is full"}))
        gen = self.client().stream("quotex", "EURUSD_otc", reconnect=False)
        with self.assertRaises(HouseBusy) as cm:
            next(gen)
        self.assertEqual(cm.exception.retry_after, 45,
                         "must obey the server's delay, not a guess")

    def test_a_missing_key_fails_before_any_request(self):
        with self.assertRaises(AuthError):
            Client(api_key="", base_url="http://127.0.0.1:1")


class TestStream(Base):
    def test_sse_parsing_skips_keepalives_and_junk(self):
        body = (
            ": keepalive\n"                       # comment, holds the connection
            "\n"                                  # blank separator
            'data: {"time":100,"price":1.234}\n'
            "event: ping\n"                       # a field we do not consume
            'data: {"time":160,"price":1.235}\n'
            "data: not json at all\n"             # must not crash the generator
            'data: {"time":220}\n'                # no price, must be skipped
            'data: {"time":280,"price":1.236}\n'
        )
        ROUTES["/v1/stream"] = (200, {"Content-Type": "text/event-stream"}, body)
        ticks = list(self.client().stream("quotex", "EURUSD_otc", reconnect=False))
        self.assertEqual([t.price for t in ticks], [1.234, 1.235, 1.236])
        self.assertEqual(ticks[0].time, 100)

    def test_reconnect_off_does_not_retry_a_plan_error(self):
        """A 402 will fail identically forever; retrying it is a loop."""
        ROUTES["/v1/stream"] = (402, {}, json.dumps({"error": "no plan"}))
        gen = self.client().stream("quotex", "EURUSD_otc", reconnect=True)
        with self.assertRaises(PlanError):
            next(gen)   # raises even with reconnect ON, rather than spinning


class TestCatalogue(Base):
    """/v1/symbols -- so nobody has to keep their own list of ids."""

    def test_symbols_carry_the_id_and_a_name(self):
        ROUTES["/v1/symbols"] = (200, {}, json.dumps({"venue": "otc", "count": 2, "symbols": [
            {"symbol": "EURUSD_otc", "name": "EUR/USD"},
            {"symbol": "#AAPL_otc", "name": "Apple"},
        ]}))
        got = self.client().symbols("otc")
        self.assertEqual([i.symbol for i in got], ["EURUSD_otc", "#AAPL_otc"])
        self.assertEqual(got[1].name, "Apple")
        self.assertIn("venue=otc", SEEN["/v1/symbols"])

    def test_a_symbol_without_a_name_falls_back_to_its_id(self):
        ROUTES["/v1/symbols"] = (200, {}, json.dumps({"symbols": [{"symbol": "EURUSD"}]}))
        self.assertEqual(self.client().symbols("forex")[0].name, "EURUSD")


class TestUsage(Base):
    """/v1/usage -- the figures a customer otherwise learns by being cut off."""

    BODY = json.dumps({
        "plan": "api_build", "planName": "Build", "expires": 1791138947,
        "books": ["otc"],
        "requests": {"used": 17774, "quota": 25000, "remaining": 7226, "resets": 1788566400},
        "streams": {"open": 1, "limit": 1, "instrumentsPerStream": 10},
        "keys": 2,
    })

    def test_usage_reads_every_figure(self):
        ROUTES["/v1/usage"] = (200, {}, self.BODY)
        u = self.client().usage()
        self.assertEqual((u.plan, u.plan_name), ("api_build", "Build"))
        self.assertEqual((u.used, u.quota, u.remaining), (17774, 25000, 7226))
        self.assertEqual(u.resets, 1788566400)
        self.assertEqual((u.streams_open, u.streams_limit), (1, 1))
        self.assertEqual(u.instruments_per_stream, 10)
        self.assertEqual(u.books, ("otc",))
        self.assertEqual(u.keys, 2)

    def test_desk_reports_no_instrument_ceiling(self):
        """None, not 0 -- Desk carries the whole book on one connection."""
        body = json.loads(self.BODY)
        body["streams"]["instrumentsPerStream"] = None
        ROUTES["/v1/usage"] = (200, {}, json.dumps(body))
        self.assertIsNone(self.client().usage().instruments_per_stream)


class TestMultiSymbolStream(Base):
    """One connection, many instruments -- the difference between following a
    watchlist and exhausting a quota polling it."""

    TWO = ('data: {"time":100,"price":1.1,"symbol":"EURUSD_otc"}\n'
           'data: {"time":101,"price":2.2,"symbol":"GBPUSD_otc"}\n')

    def test_a_list_is_sent_as_one_comma_separated_parameter(self):
        ROUTES["/v1/stream"] = (200, {"Content-Type": "text/event-stream"}, self.TWO)
        list(self.client().stream("otc", ["EURUSD_otc", "GBPUSD_otc"], reconnect=False))
        self.assertIn("symbol=EURUSD_otc%2CGBPUSD_otc", SEEN["/v1/stream"])

    def test_every_tick_carries_its_own_symbol(self):
        ROUTES["/v1/stream"] = (200, {"Content-Type": "text/event-stream"}, self.TWO)
        ticks = list(self.client().stream("otc", ["EURUSD_otc", "GBPUSD_otc"], reconnect=False))
        self.assertEqual([t.symbol for t in ticks], ["EURUSD_otc", "GBPUSD_otc"])

    def test_one_symbol_still_works_as_a_plain_string(self):
        ROUTES["/v1/stream"] = (200, {"Content-Type": "text/event-stream"},
                                'data: {"time":100,"price":1.1}\n')
        ticks = list(self.client().stream("quotex", "EURUSD_otc", reconnect=False))
        self.assertEqual(ticks[0].symbol, "EURUSD_otc",
                         "an unlabelled tick on a single-symbol stream is that symbol")

    def test_an_unlabelled_tick_on_a_multi_stream_is_not_mislabelled(self):
        """Tagging it with the whole comma list would be worse than empty."""
        ROUTES["/v1/stream"] = (200, {"Content-Type": "text/event-stream"},
                                'data: {"time":100,"price":1.1}\n')
        ticks = list(self.client().stream("otc", ["A_otc", "B_otc"], reconnect=False))
        self.assertEqual(ticks[0].symbol, "")

    def test_duplicates_are_dropped_so_they_do_not_spend_a_place(self):
        got = Client._symbol_param(["EURUSD_otc", "EURUSD_otc", "GBPUSD_otc"])
        self.assertEqual(got, "EURUSD_otc,GBPUSD_otc")

    def test_whitespace_and_comma_strings_are_accepted(self):
        self.assertEqual(Client._symbol_param(" EURUSD_otc , GBPUSD_otc "),
                         "EURUSD_otc,GBPUSD_otc")

    def test_nothing_to_subscribe_is_refused_before_the_request(self):
        for empty in ("", "   ", ",", [], [" "]):
            with self.assertRaises(ValueError):
                Client._symbol_param(empty)


class TestPackage(unittest.TestCase):
    def test_version_and_exports(self):
        self.assertRegex(otcharts.__version__, r"^\d+\.\d+\.\d+$")
        for name in ("Client", "Candle", "Tick", "Instrument", "Usage",
                     "AuthError", "HouseBusy"):
            self.assertTrue(hasattr(otcharts, name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
