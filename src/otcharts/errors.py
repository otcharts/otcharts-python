"""One exception per refusal the API can return.

The API distinguishes its refusals carefully -- a 402 is not a 401, and a 503
from the house being full is not a 429 from your own limit -- and a client that
collapses them all into one HTTPError throws that away. The caller who needs to
know whether to buy a bigger plan, wait thirty seconds, or fix their key cannot
tell from a status code they never see.
"""

__all__ = [
    "OTChartsError", "AuthError", "PlanError", "NotFound",
    "QuotaExceeded", "TooManyStreams", "HouseBusy", "TransportError",
]


class OTChartsError(Exception):
    """Base for everything this package raises."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class AuthError(OTChartsError):
    """401 -- the key is missing, malformed, revoked, or not a key at all.

    Worth knowing: a password reset revokes every key on the account, so a key
    that worked yesterday and 401s today may simply have been revoked by its
    owner resetting their password.
    """


class PlanError(OTChartsError):
    """402 or 403 -- the key is good; the plan does not open what you asked for.

    Four ways to arrive here, and the server's message says which: the account
    holds no data plan (402), it holds one that does not carry this book (403),
    it is on the free tier and the instrument is outside the five that tier
    opens on each book (403, and the message names the five), or it asked to
    page back with `before` from the free tier, which reads the live window
    only (403, and the message links the paid tiers). Said apart from
    AuthError on purpose: hunting for a bad key when the key is fine wastes an
    afternoon.
    """


class NotFound(OTChartsError):
    """404 -- no such venue, or no such symbol on that venue.

    Symbol ids are not portable between books. The same pair is EURUSD_otc on
    Quotex and Pocket Option, EURUSD-OTC on IQ, and EUR/USD-OTC on BinoDex.
    """


class QuotaExceeded(OTChartsError):
    """429 on a request -- the plan's request quota for the window is spent.

    The window is the plan's, not the calendar's: free counts by the WEEK, every
    paid plan by the day. `Usage.per` says which, and `Usage.resets` is when it
    turns over -- sleep until that rather than until midnight.
    """


class TooManyStreams(OTChartsError):
    """429 on a stream -- this ACCOUNT already holds its maximum open streams.

    Your own limit, so closing one of your streams fixes it. Distinct from
    HouseBusy, which is not about you at all.
    """


class HouseBusy(OTChartsError):
    """503 on a stream -- the service as a whole is at its stream ceiling.

    Not your fault and not fixed by upgrading: every customer's streams share
    the same venue sessions, and the total is capped to protect them. Carries
    `retry_after` in seconds.
    """

    def __init__(self, message, status=None, body=None, retry_after=30):
        super().__init__(message, status, body)
        self.retry_after = retry_after


class TransportError(OTChartsError):
    """The request never got an answer -- DNS, TCP, TLS, or a dropped socket."""
