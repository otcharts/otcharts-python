"""OTCharts — market data from OTC broker books, as JSON.

    pip install otcharts

    from otcharts import Client
    otc = Client()                                   # reads OTCHARTS_API_KEY
    bars = otc.candles("iq", "EURUSD-OTC", tf=60, limit=300)

    for i in otc.symbols("otc"):                     # never guess an id
        print(i.symbol, i.name)
    for tick in otc.stream("otc", ["EURUSD_otc", "GBPUSD_otc"]):
        print(tick.symbol, tick.price)                # many pairs, one stream

Reads prices. Does not place trades, and never asks for broker credentials.
Not affiliated with any broker named in this package.
"""
from .client import Candle, Client, Instrument, Tick, Usage, Venue
from .errors import (
    AuthError, HouseBusy, NotFound, OTChartsError, PlanError,
    QuotaExceeded, TooManyStreams, TransportError,
)

__version__ = "0.2.0"
__all__ = [
    "Client", "Candle", "Tick", "Venue", "Instrument", "Usage",
    "OTChartsError", "AuthError", "PlanError", "NotFound",
    "QuotaExceeded", "TooManyStreams", "HouseBusy", "TransportError",
    "__version__",
]
