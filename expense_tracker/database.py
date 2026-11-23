"""SQLite storage for expenses and budgets.

All SQL lives in this module so the rest of the app never has to think about
tables or queries - it just works with ``Expense`` objects.

Security note: every value coming from the user is passed to SQLite through
``?`` placeholders (parameterized queries) and never pasted into the SQL
string. This prevents SQL injection.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from types import TracebackType
from typing import Dict, List, Optional, Tuple, Type

from .models import Expense, from_cents, month_bounds, to_cents

# "IF NOT EXISTS" makes it safe to run this every time the app starts.
SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    date         TEXT    NOT NULL  -- stored as 'YYYY-MM-DD'
);

-- Most queries filter by date, so an index keeps them fast as data grows.
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (date);

CREATE TABLE IF NOT EXISTS budgets (
    category    TEXT    PRIMARY KEY,
    limit_cents INTEGER NOT NULL CHECK (limit_cents > 0)
);
"""


class ExpenseDatabase:
    """A small wrapper around a SQLite connection.

    Use it as a context manager so the connection is always closed::

        with ExpenseDatabase("expenses.db") as db:
            db.add_expense(expense)

    Pass ``":memory:"`` as the path to get a throwaway database (handy in tests).
    """

    def __init__(self, path: str = ":memory:") -> None:
        self.connection = sqlite3.connect(path)
        # Row objects let us read columns by name (row["category"]) instead of
        # by position (row[2]), which is much easier to read.
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    # --- context manager support -------------------------------------------

    def __enter__(self) -> "ExpenseDatabase":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying connection."""
        self.connection.close()

    # --- expenses ------------------------------------------------------------

    def add_expense(self, expense: Expense) -> int:
        """Save a new expense and return the ID SQLite gave it."""
        # "with self.connection" wraps the statement in a transaction: it
        # commits on success and rolls back automatically if anything fails.
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO expenses (amount_cents, category, description, date) "
                "VALUES (?, ?, ?, ?)",
                (
                    to_cents(expense.amount),
                    expense.category,
                    expense.description,
                    expense.date.isoformat(),
                ),
            )
        expense_id = int(cursor.lastrowid)
        expense.id = expense_id
        return expense_id

    def get_expense(self, expense_id: int) -> Optional[Expense]:
        """Return the expense with this ID, or ``None`` if it doesn't exist."""
        row = self.connection.execute(
            "SELECT id, amount_cents, category, description, date "
            "FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        return _row_to_expense(row) if row else None

    def list_expenses(
        self,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        category: Optional[str] = None,
    ) -> List[Expense]:
        """Return expenses (oldest first), optionally filtered.

        Args:
            start: only include expenses on or after this date.
            end: only include expenses on or before this date.
            category: only include expenses in this category.
        """
        where_sql, params = _build_filters(start, end, category)
        rows = self.connection.execute(
            "SELECT id, amount_cents, category, description, date FROM expenses"
            f"{where_sql} ORDER BY date, id",
            params,
        ).fetchall()
        return [_row_to_expense(row) for row in rows]

    def update_expense(self, expense: Expense) -> bool:
        """Overwrite a saved expense. Returns ``False`` if the ID wasn't found."""
        if expense.id is None:
            raise ValueError("Cannot update an expense that has not been saved")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE expenses "
                "SET amount_cents = ?, category = ?, description = ?, date = ? "
                "WHERE id = ?",
                (
                    to_cents(expense.amount),
                    expense.category,
                    expense.description,
                    expense.date.isoformat(),
                    expense.id,
                ),
            )
        # rowcount tells us how many rows were changed: 0 means "no such ID".
        return cursor.rowcount > 0

    def delete_expense(self, expense_id: int) -> bool:
        """Delete an expense. Returns ``False`` if the ID wasn't found."""
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM expenses WHERE id = ?", (expense_id,)
            )
        return cursor.rowcount > 0

    # --- reports -------------------------------------------------------------

    def category_totals(
        self,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
    ) -> List[Tuple[str, float]]:
        """Return ``(category, total)`` pairs, biggest spending first.

        The adding-up is done by SQLite with ``GROUP BY`` rather than in a
        Python loop - databases are built for exactly this kind of work.
        """
        where_sql, params = _build_filters(start, end, None)
        rows = self.connection.execute(
            "SELECT category, SUM(amount_cents) AS total_cents FROM expenses"
            f"{where_sql} GROUP BY category ORDER BY total_cents DESC, category",
            params,
        ).fetchall()
        return [(row["category"], from_cents(row["total_cents"])) for row in rows]

    def monthly_summary(self, year: int, month: int) -> List[Tuple[str, float]]:
        """Return per-category totals for a single calendar month."""
        start, end = month_bounds(year, month)
        return self.category_totals(start, end)

    # --- budgets -------------------------------------------------------------

    def set_budget(self, category: str, limit: float) -> None:
        """Create or replace the monthly budget for a category."""
        with self.connection:
            # "ON CONFLICT ... DO UPDATE" (an "upsert") updates the existing
            # row instead of failing when the category already has a budget.
            self.connection.execute(
                "INSERT INTO budgets (category, limit_cents) VALUES (?, ?) "
                "ON CONFLICT (category) DO UPDATE SET limit_cents = excluded.limit_cents",
                (category, to_cents(limit)),
            )

    def get_budgets(self) -> Dict[str, float]:
        """Return all budgets as a ``{category: monthly_limit}`` dictionary."""
        rows = self.connection.execute(
            "SELECT category, limit_cents FROM budgets ORDER BY category"
        ).fetchall()
        return {row["category"]: from_cents(row["limit_cents"]) for row in rows}

    def delete_budget(self, category: str) -> bool:
        """Remove a category's budget. Returns ``False`` if there wasn't one."""
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM budgets WHERE category = ?", (category,)
            )
        return cursor.rowcount > 0


def _build_filters(
    start: Optional[dt.date],
    end: Optional[dt.date],
    category: Optional[str],
) -> Tuple[str, List[object]]:
    """Build a WHERE clause and its parameter list from optional filters.

    Only fixed snippets like ``"date >= ?"`` are joined into the SQL text;
    the actual user values go into ``params`` so SQLite escapes them safely.
    Dates are stored as ISO strings ('YYYY-MM-DD'), which sort in the same
    order as real dates, so ``>=`` and ``<=`` work as expected.
    """
    clauses: List[str] = []
    params: List[object] = []
    if start is not None:
        clauses.append("date >= ?")
        params.append(start.isoformat())
    if end is not None:
        clauses.append("date <= ?")
        params.append(end.isoformat())
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where_sql, params


def _row_to_expense(row: sqlite3.Row) -> Expense:
    """Convert a database row into an ``Expense`` object."""
    return Expense(
        id=row["id"],
        amount=from_cents(row["amount_cents"]),
        category=row["category"],
        description=row["description"],
        date=dt.date.fromisoformat(row["date"]),
    )
