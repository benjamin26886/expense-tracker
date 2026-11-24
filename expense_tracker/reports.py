"""Turning data into something people can read: tables, warnings and CSV.

These functions return strings (instead of printing directly), which keeps
them easy to test - a test can just compare the returned text.
"""

from __future__ import annotations

import csv
from typing import Iterable, List, Mapping, Optional, Sequence

from .models import Expense

# Spending at or above this share of a budget is flagged as "near limit".
NEAR_LIMIT_RATIO = 0.8


def format_money(amount: float) -> str:
    """Format a number as money, e.g. ``1234.5`` -> ``"$1,234.50"``."""
    return f"${amount:,.2f}"


def format_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    right_align: Iterable[int] = (),
    footer: Optional[Sequence[str]] = None,
) -> str:
    """Draw a simple ASCII table.

    Args:
        headers: the column titles.
        rows: the table body; every cell must already be a string.
        right_align: indexes of columns to right-align (useful for numbers).
        footer: an optional extra row (like a total) drawn under a divider.

    Each column is made as wide as its longest cell so everything lines up.
    """
    right = set(right_align)
    all_rows = [list(headers), *[list(r) for r in rows]]
    if footer is not None:
        all_rows.append(list(footer))
    widths = [max(len(row[i]) for row in all_rows) for i in range(len(headers))]

    def render(cells: Sequence[str]) -> str:
        padded = [
            cell.rjust(widths[i]) if i in right else cell.ljust(widths[i])
            for i, cell in enumerate(cells)
        ]
        return "| " + " | ".join(padded) + " |"

    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
    lines = [border, render(headers), border]
    lines.extend(render(row) for row in rows)
    if footer is not None:
        lines.extend([border, render(footer)])
    lines.append(border)
    return "\n".join(lines)


def expenses_table(expenses: Sequence[Expense]) -> str:
    """Render a list of expenses as a table with a total at the bottom."""
    rows = [
        [
            str(expense.id),
            expense.date.isoformat(),
            expense.category,
            format_money(expense.amount),
            expense.description,
        ]
        for expense in expenses
    ]
    total = sum(expense.amount for expense in expenses)
    return format_table(
        ["ID", "Date", "Category", "Amount", "Description"],
        rows,
        right_align=[0, 3],
        footer=["", "", "TOTAL", format_money(total), f"{len(expenses)} expense(s)"],
    )


def budget_status(spent: float, limit: float) -> str:
    """Describe how spending compares with a budget in a few words."""
    if spent > limit:
        return f"OVER by {format_money(spent - limit)}"
    if spent >= limit * NEAR_LIMIT_RATIO:
        return "Near limit"
    return "OK"


def summary_table(totals: Mapping[str, float], budgets: Mapping[str, float]) -> str:
    """Render per-category spending next to each category's budget.

    Categories that have a budget but no spending yet are included too, so
    you can see how much room you have left everywhere.
    """
    # Keep the order from ``totals`` (biggest spending first), then add any
    # budgeted categories that had no spending.
    categories = list(totals) + sorted(c for c in budgets if c not in totals)
    rows: List[List[str]] = []
    for category in categories:
        spent = totals.get(category, 0.0)
        limit = budgets.get(category)
        if limit is None:
            rows.append([category, format_money(spent), "-", "-", "No budget"])
        else:
            rows.append(
                [
                    category,
                    format_money(spent),
                    format_money(limit),
                    format_money(limit - spent),
                    budget_status(spent, limit),
                ]
            )
    total_spent = sum(totals.values())
    return format_table(
        ["Category", "Spent", "Budget", "Remaining", "Status"],
        rows,
        right_align=[1, 2, 3],
        footer=["TOTAL", format_money(total_spent), "", "", ""],
    )


def budget_warnings(
    totals: Mapping[str, float], budgets: Mapping[str, float]
) -> List[str]:
    """Return one warning message for every category that is over budget."""
    warnings: List[str] = []
    for category, limit in budgets.items():
        spent = totals.get(category, 0.0)
        if spent > limit:
            warnings.append(
                f"WARNING: '{category}' is over budget - spent {format_money(spent)} "
                f"of {format_money(limit)} (over by {format_money(spent - limit)})"
            )
    return warnings


def export_to_csv(expenses: Iterable[Expense], path: str) -> int:
    """Write expenses to a CSV file and return how many rows were written.

    CSV files open straight into Excel, Google Sheets or Numbers, which makes
    them a simple way to get data out of the app.
    """
    count = 0
    # newline="" is what the csv module docs recommend - without it you can
    # get blank lines between rows on Windows.
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["id", "date", "category", "amount", "description"])
        for expense in expenses:
            writer.writerow(
                [
                    expense.id,
                    expense.date.isoformat(),
                    expense.category,
                    f"{expense.amount:.2f}",
                    expense.description,
                ]
            )
            count += 1
    return count
