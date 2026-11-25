import datetime as dt


class Clock:
    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


class FakeClock(Clock):
    """Deterministic clock for tests and the demo."""

    def __init__(self, start=None):
        self._t = start or dt.datetime(2026, 1, 5, 9, 0, tzinfo=dt.timezone.utc)

    def now(self):
        return self._t

    def advance(self, **kw):
        self._t += dt.timedelta(**kw)
