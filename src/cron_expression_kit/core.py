"""Core cron expression parser and next-fire time calculator.

The implementation deliberately supports only the classic five-field cron
syntax (minute, hour, day-of-month, month, day-of-week). That keeps the parser
small and predictable; the trade-off is that non-standard extensions such as
seconds fields or ``@reboot`` are rejected with :class:`CronError` rather than
silently reinterpreted.

Day-of-week follows the common cron convention where both 0 and 7 mean Sunday.
When both day-of-month and day-of-week are restricted (i.e. neither is ``*``),
the two are OR-ed together, matching Vixie cron behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterator

__all__ = ["CronError", "CronExpression"]


class CronError(ValueError):
    """Raised when a cron expression cannot be parsed or a field is out of range."""


# Inclusive bounds for each of the five fields.
_FIELD_BOUNDS: tuple[tuple[int, int], ...] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 7),   # day of week (0 and 7 both mean Sunday)
)

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DOW_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}


def _parse_token(token: str, lo: int, hi: int, names: dict[str, int] | None) -> int:
    """Translate a single field token into an integer, honouring names."""
    text = token.strip()
    if not text:
        raise CronError("empty field token")
    lowered = text.lower()
    if names is not None and lowered in names:
        return names[lowered]
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise CronError(f"invalid field value: {token!r}") from exc
    if value < lo or value > hi:
        raise CronError(f"value {value} out of range [{lo}, {hi}]")
    return value


def _parse_field(
    field: str,
    lo: int,
    hi: int,
    names: dict[str, int] | None = None,
    *,
    sunday_seven: bool = False,
) -> set[int]:
    """Expand one cron field into the concrete set of values it matches.

    Supports ``*``, comma-separated lists, ranges (``a-b``), steps (``*/n`` and
    ``a-b/n``), and the ``7`` alias for Sunday when ``sunday_seven`` is set.
    """
    field = field.strip()
    if not field:
        raise CronError("empty cron field")

    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"empty list item in field {field!r}")

        step = 1
        body = part
        if "/" in part:
            body, _, step_text = part.partition("/")
            body = body.strip()
            try:
                step = int(step_text.strip(), 10)
            except ValueError as exc:
                raise CronError(f"invalid step in {part!r}") from exc
            if step <= 0:
                raise CronError(f"step must be positive in {part!r}")

        if body == "*":
            start, end = lo, hi
        elif "-" in body:
            left, _, right = body.partition("-")
            start = _parse_token(left, lo, hi, names)
            end = _parse_token(right, lo, hi, names)
            if start > end:
                raise CronError(f"range start greater than end in {part!r}")
        else:
            start = _parse_token(body, lo, hi, names)
            end = start

        if start == end and step != 1:
            # A step on a single value is almost always a typo (``5/2``).
            raise CronError(f"step used with a single value in {part!r}")

        for value in range(start, end + 1, step):
            if sunday_seven and value == 7:
                values.add(0)
            else:
                values.add(value)

    if not values:
        raise CronError(f"field {field!r} matches no values")
    return values


def _next_month_start(moment: datetime) -> datetime:
    """Return midnight on the first day of the month after ``moment``."""
    year = moment.year + (1 if moment.month == 12 else 0)
    month = 1 if moment.month == 12 else moment.month + 1
    return datetime(year, month, 1, 0, 0, 0)


@dataclass(frozen=True)
class CronExpression:
    """A parsed five-field cron expression.

    Instances are immutable and can be reused across threads. Construct one
    with :meth:`parse` or directly with the five keyword fields; the class
    normalises them into sets of matching values.
    """

    minute: frozenset[int]
    hour: frozenset[int]
    day_of_month: frozenset[int]
    month: frozenset[int]
    day_of_week: frozenset[int]
    dom_restricted: bool
    dow_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> "CronExpression":
        """Parse a standard five-field cron expression.

        The fields are, in order: minute, hour, day-of-month, month,
        day-of-week. Names for months and weekdays are accepted
        case-insensitively. Anything else raises :class:`CronError`.
        """
        if not isinstance(expression, str):
            raise CronError("cron expression must be a string")
        parts = expression.split()
        if len(parts) != 5:
            raise CronError(
                f"expected exactly 5 fields, got {len(parts)}: {expression!r}"
            )

        minute = _parse_field(parts[0], *_FIELD_BOUNDS[0])
        hour = _parse_field(parts[1], *_FIELD_BOUNDS[1])
        dom = _parse_field(parts[2], *_FIELD_BOUNDS[2])
        month = _parse_field(parts[3], *_FIELD_BOUNDS[3], _MONTH_NAMES)
        dow = _parse_field(
            parts[4], *_FIELD_BOUNDS[4], _DOW_NAMES, sunday_seven=True
        )

        return cls(
            minute=frozenset(minute),
            hour=frozenset(hour),
            day_of_month=frozenset(dom),
            month=frozenset(month),
            day_of_week=frozenset(dow),
            dom_restricted=parts[2].strip() != "*",
            dow_restricted=parts[4].strip() != "*",
        )

    def matches(self, moment: datetime) -> bool:
        """Return whether ``moment`` (to the minute) satisfies this expression."""
        if moment.month not in self.month:
            return False
        if moment.hour not in self.hour:
            return False
        if moment.minute not in self.minute:
            return False

        dom_ok = moment.day in self.day_of_month
        # Python's weekday() is Monday=0; cron wants Sunday=0.
        dow = (moment.weekday() + 1) % 7
        dow_ok = dow in self.day_of_week

        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok
        if self.dom_restricted:
            return dom_ok
        if self.dow_restricted:
            return dow_ok
        return True

    def next_fire(
        self, after: datetime, *, inclusive: bool = False
    ) -> datetime:
        """Return the first fire time strictly after ``after``.

        With ``inclusive=True`` a matching ``after`` is returned unchanged.
        Seconds and microseconds on the result are always zero.
        """
        candidate = after.replace(second=0, microsecond=0)
        if inclusive:
            if self.matches(candidate):
                return candidate
        candidate += timedelta(minutes=1)

        # The algorithm advances by whole days when the current day cannot
        # match, which keeps the loop short even for sparse expressions.
        while True:
            if candidate.month not in self.month:
                candidate = _next_month_start(candidate)
                continue
            if not self._day_matches(candidate):
                candidate = (candidate + timedelta(days=1)).replace(
                    hour=0, minute=0
                )
                continue
            if candidate.hour not in self.hour:
                next_hour = self._next_value(self.hour, candidate.hour)
                if next_hour is None:
                    candidate = (candidate + timedelta(days=1)).replace(
                        hour=0, minute=0
                    )
                else:
                    candidate = candidate.replace(hour=next_hour, minute=0)
                continue
            if candidate.minute not in self.minute:
                next_minute = self._next_value(self.minute, candidate.minute)
                if next_minute is None:
                    candidate = (candidate + timedelta(hours=1)).replace(
                        minute=0
                    )
                else:
                    candidate = candidate.replace(minute=next_minute)
                continue
            return candidate

    def iter_fire(
        self,
        after: datetime,
        *,
        inclusive: bool = False,
        limit: int | None = None,
    ) -> Iterator[datetime]:
        """Yield successive fire times after ``after``.

        If ``limit`` is given, at most that many times are produced. The
        generator is lazy, so callers can stop early without computing the
        rest.
        """
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        count = 0
        current = after
        first = True
        while limit is None or count < limit:
            nxt = self.next_fire(
                current, inclusive=inclusive if first else False
            )
            yield nxt
            current = nxt
            first = False
            count += 1

    def _day_matches(self, moment: datetime) -> bool:
        dom_ok = moment.day in self.day_of_month
        dow = (moment.weekday() + 1) % 7
        dow_ok = dow in self.day_of_week
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok
        if self.dom_restricted:
            return dom_ok
        if self.dow_restricted:
            return dow_ok
        return True

    @staticmethod
    def _next_value(values: frozenset[int], current: int) -> int | None:
        """Smallest value in ``values`` strictly greater than ``current``."""
        best: int | None = None
        for value in values:
            if value > current and (best is None or value < best):
                best = value
        return best


def _unused_clock_hint() -> Callable[[], datetime]:
    """Placeholder kept out of the public API; see README for clock guidance."""
    return datetime.now
