# cron_expression_kit

Parses standard five-field cron expressions into a set of next-fire times, using only the Python standard library.

```python
from datetime import datetime
from cron_expression_kit import CronExpression

expr = CronExpression.parse("*/15 9-17 * * 1-5")
print(expr.next_fire(datetime(2024, 1, 1, 9, 0)))
# 2024-01-01 09:15:00

for moment in expr.iter_fire(datetime(2024, 1, 1, 9, 0), limit=3):
    print(moment)
# 2024-01-01 09:15:00
# 2024-01-01 09:30:00
# 2024-01-01 09:45:00
```

## Why this exists

Most cron helpers pull in a date library or a full scheduling framework. That is a heavy dependency for the common case of answering a single question: *when does this expression fire next?* This package parses the classic five fields and walks a `datetime` forward using nothing but `datetime` itself.

The trade-off is deliberate scope. Only the five-field form is supported — no seconds field, no `@reboot` or other macros. Anything outside that shape raises `CronError` instead of being guessed at. If you need those extensions, this is the wrong library.

## The awkward edge

Day-of-month and day-of-week are OR-ed when both are restricted, which is the Vixie cron rule but surprises people who expect AND. `CronExpression.parse("0 0 1 * 1")` fires on the 1st of the month *and* on every Monday, not only on Mondays that fall on the 1st. If you want AND semantics, use a day-of-month field of `*` and put the weekday restriction in the day-of-week field.

## API

- `CronExpression.parse(expression: str) -> CronExpression` — parse a five-field expression. Raises `CronError` on malformed input.
- `CronExpression.matches(moment: datetime) -> bool` — whether a minute-precision `datetime` satisfies the expression.
- `CronExpression.next_fire(after: datetime, *, inclusive: bool = False) -> datetime` — first fire time strictly after `after`, or at `after` when `inclusive=True` and it matches. Seconds and microseconds are truncated to zero.
- `CronExpression.iter_fire(after: datetime, *, inclusive: bool = False, limit: int | None = None) -> Iterator[datetime]` — lazy sequence of fire times. `limit` caps how many are produced; a negative limit raises `ValueError`.
- `CronError` — subclass of `ValueError` raised for parse and range errors.

Fields are minute, hour, day-of-month, month, day-of-week. Each accepts `*`, lists, ranges, and steps (`*/n`, `a-b/n`). Month and weekday names are accepted case-insensitively; `7` is an alias for Sunday in the day-of-week field.

## Testing

```
PYTHONPATH=src python -m unittest discover -s tests
```

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

