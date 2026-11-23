"""Data models and input validation helpers.

Validation lives here (instead of inside the CLI) so that every part of the
app - the command line, the database layer and the tests - follows exactly
the same rules.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional, Tuple

DATE_FORMAT = "%Y-%m-%d"  # ISO 8601, e.g. 2026-11-16
MONTH_FORMAT = "%Y-%m"  # e.g. 2026-11


@dataclass
class Expense:
    """A single expense.

    ``id`` is ``None`` until the expense is saved, because SQLite is the one
    that hands out IDs when a row is inserted.
    """

    amount: float
    category: str
    description: str
    date: dt.date
    id: Optional[int] = None


def parse_amount(text: str) -> float:
    """Turn user input such as ``"12.5"`` or ``"$12.50"`` into a money amount.

    The text is parsed with ``Decimal`` first because it reads values like
    ``"0.10"`` exactly, then rounded to whole cents like real money.

    Raises:
        ValueError: if the text is not a number or is not greater than zero.
    """
    cleaned = str(text).strip().lstrip("$").replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"'{text}' is not a valid amount (example: 12.50)") from None

    # "NaN" and "Infinity" are valid Decimals, but not valid prices.
    if not value.is_finite():
        raise ValueError(f"'{text}' is not a valid amount (example: 12.50)")

    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value <= 0:
        raise ValueError("Amount must be greater than zero")
    return float(value)


def to_cents(amount: float) -> int:
    """Convert dollars to whole cents for storage.

    Floats can't represent most decimal fractions exactly (in Python,
    ``0.1 + 0.2 == 0.30000000000000004``). Storing integers avoids rounding
    errors creeping into totals.
    """
    return int(round(amount * 100))


def from_cents(cents: int) -> float:
    """Convert whole cents back into dollars for display."""
    return cents / 100


def parse_date(text: str) -> dt.date:
    """Parse a ``YYYY-MM-DD`` string into a ``date`` object.

    Raises:
        ValueError: with a friendly message if the format is wrong.
    """
    try:
        return dt.datetime.strptime(text.strip(), DATE_FORMAT).date()
    except ValueError:
        raise ValueError(
            f"'{text}' is not a valid date - use YYYY-MM-DD (e.g. 2026-11-16)"
        ) from None


def parse_month(text: str) -> Tuple[int, int]:
    """Parse a ``YYYY-MM`` string into a ``(year, month)`` tuple."""
    try:
        parsed = dt.datetime.strptime(text.strip(), MONTH_FORMAT)
    except ValueError:
        raise ValueError(
            f"'{text}' is not a valid month - use YYYY-MM (e.g. 2026-11)"
        ) from None
    return parsed.year, parsed.month


def month_bounds(year: int, month: int) -> Tuple[dt.date, dt.date]:
    """Return the first and last day of a month.

    ``calendar.monthrange`` knows how many days each month has, including
    February in leap years, so we don't have to.
    """
    last_day = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last_day)


def normalize_category(text: str) -> str:
    """Clean up a category name so ``"Food"`` and ``" food "`` count as one.

    Raises:
        ValueError: if the category is empty.
    """
    category = text.strip().lower()
    if not category:
        raise ValueError("Category cannot be empty")
    return category
