"""OTCharts — market data from OTC broker books, as JSON.

    pip install otcharts

    from otcharts import Client
    otc = Client()                                   # reads OTCHARTS_API_KEY
    bars = otc.candles("iq", "EURUSD-OTC", tf=60, limit=300)

Reads prices. Does not place trades, and never asks for broker credentials.
Not affiliated with any broker named in this package.
"""
from .client import Candle, Client, Tick, Venue
from .errors import (
    AuthError, HouseBusy, NotFound, OTChartsError, PlanError,
    QuotaExceeded, TooManyStreams, TransportError,
)

__version__ = "0.1.0"
__all__ = [
    "Client", "Candle", "Tick", "Venue",
    "OTChartsError", "AuthError", "PlanError", "NotFound",
    "QuotaExceeded", "TooManyStreams", "HouseBusy", "TransportError",
    "__version__",
]
