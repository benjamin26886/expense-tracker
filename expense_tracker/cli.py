"""Command-line interface built with ``argparse``.

Each subcommand (``add``, ``list``, ``edit``, ``delete``, ``summary``,
``budget``, ``export``) has its own small handler function that validates the
user's input, talks to ``ExpenseDatabase`` and prints a friendly result.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import List, Optional, Sequence, Tuple

from .database import ExpenseDatabase
from .models import (
    Expense,
    month_bounds,
    normalize_category,
    parse_amount,
    parse_date,
    parse_month,
)
from .reports import (
    budget_warnings,
    expenses_table,
    export_to_csv,
    format_money,
    format_table,
    summary_table,
)

DEFAULT_DB_PATH = os.environ.get("EXPENSE_TRACKER_DB", "expenses.db")


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level ``argparse`` parser and all subcommands."""
    parser = argparse.ArgumentParser(
        prog="expense_tracker",
        description="Track daily expenses, category budgets and monthly summaries.",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help="Path to the SQLite database file (default: %(default)s).",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # --- add -----------------------------------------------------------------
    add_parser = subparsers.add_parser("add", help="Record a new expense.")
    add_parser.add_argument("amount", help="Amount spent (e.g. 12.50 or $12.50).")
    add_parser.add_argument("category", help="Category name (e.g. food, rent).")
    add_parser.add_argument(
        "-d",
        "--description",
        default="",
        help="Short note about the expense.",
    )
    add_parser.add_argument(
        "--date",
        default=None,
        help="Expense date in YYYY-MM-DD format (default: today).",
    )
    add_parser.set_defaults(handler=_handle_add)

    # --- list ----------------------------------------------------------------
    list_parser = subparsers.add_parser("list", help="List saved expenses.")
    _add_filter_arguments(list_parser)
    list_parser.set_defaults(handler=_handle_list)

    # --- edit ----------------------------------------------------------------
    edit_parser = subparsers.add_parser("edit", help="Update an existing expense.")
    edit_parser.add_argument("id", type=int, help="ID of the expense to edit.")
    edit_parser.add_argument("--amount", help="New amount.")
    edit_parser.add_argument("--category", help="New category.")
    edit_parser.add_argument(
        "-d", "--description", default=None, help="New description."
    )
    edit_parser.add_argument("--date", help="New date in YYYY-MM-DD format.")
    edit_parser.set_defaults(handler=_handle_edit)

    # --- delete --------------------------------------------------------------
    delete_parser = subparsers.add_parser("delete", help="Delete an expense by ID.")
    delete_parser.add_argument("id", type=int, help="ID of the expense to delete.")
    delete_parser.set_defaults(handler=_handle_delete)

    # --- summary -------------------------------------------------------------
    summary_parser = subparsers.add_parser(
        "summary", help="Show spending totals per category alongside budgets."
    )
    summary_parser.add_argument(
        "-m",
        "--month",
        help="Month to summarise in YYYY-MM format (e.g. 2026-11).",
    )
    summary_parser.add_argument(
        "--from", dest="start", help="Start date in YYYY-MM-DD format."
    )
    summary_parser.add_argument(
        "--to", dest="end", help="End date in YYYY-MM-DD format."
    )
    summary_parser.set_defaults(handler=_handle_summary)

    # --- budget --------------------------------------------------------------
    budget_parser = subparsers.add_parser(
        "budget",
        help="Set, list or remove monthly category budgets.",
    )
    budget_parser.add_argument(
        "args",
        nargs="*",
        help=(
            "Use 'set <category> <limit>', 'remove <category>', 'list', "
            "or simply '<category> <limit>'."
        ),
    )
    budget_parser.add_argument(
        "--remove",
        metavar="CATEGORY",
        help="Remove the monthly budget for a category.",
    )
    budget_parser.set_defaults(handler=_handle_budget)

    # --- export --------------------------------------------------------------
    export_parser = subparsers.add_parser(
        "export", help="Export expenses to a CSV file."
    )
    export_parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Destination CSV file path (default: expenses.csv).",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        dest="output_flag",
        default=None,
        help="Destination CSV file path.",
    )
    _add_filter_arguments(export_parser)
    export_parser.set_defaults(handler=_handle_export)

    return parser


def _add_filter_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach the shared date/category filter flags to a subcommand."""
    parser.add_argument(
        "-m",
        "--month",
        help="Filter by month in YYYY-MM format (e.g. 2026-11).",
    )
    parser.add_argument(
        "--from", dest="start", help="Start date in YYYY-MM-DD format."
    )
    parser.add_argument(
        "--to", dest="end", help="End date in YYYY-MM-DD format."
    )
    parser.add_argument(
        "-c", "--category", help="Only include expenses in this category."
    )


def _resolve_date_range(
    args: argparse.Namespace,
) -> Tuple[Optional[dt.date], Optional[dt.date]]:
    """Turn ``--month``, ``--from`` and ``--to`` flags into a ``(start, end)`` pair."""
    if args.month and (args.start or args.end):
        raise ValueError("Use either --month or --from/--to, not both")
    if args.month:
        year, month = parse_month(args.month)
        return month_bounds(year, month)
    start = parse_date(args.start) if args.start else None
    end = parse_date(args.end) if args.end else None
    if start and end and start > end:
        raise ValueError(
            f"Start date ({start.isoformat()}) cannot be after end date ({end.isoformat()})"
        )
    return start, end


# --- subcommand handlers -----------------------------------------------------


def _handle_add(db: ExpenseDatabase, args: argparse.Namespace) -> int:
    amount = parse_amount(args.amount)
    category = normalize_category(args.category)
    date = parse_date(args.date) if args.date else dt.date.today()
    description = args.description.strip()

    expense = Expense(
        amount=amount,
        category=category,
        description=description,
        date=date,
    )
    expense_id = db.add_expense(expense)
    print(
        f"Added expense #{expense_id}: {format_money(amount)} "
        f"for '{category}' on {date.isoformat()}"
    )

    # Check whether this expense pushed the category over its monthly budget.
    totals = dict(db.monthly_summary(date.year, date.month))
    budgets = db.get_budgets()
    if category in budgets:
        for warning in budget_warnings(
            {category: totals.get(category, 0.0)},
            {category: budgets[category]},
        ):
            print(warning)
    return 0


def _handle_list(db: ExpenseDatabase, args: argparse.Namespace) -> int:
    start, end = _resolve_date_range(args)
    category = normalize_category(args.category) if args.category else None
    expenses = db.list_expenses(start=start, end=end, category=category)
    if not expenses:
        print("No expenses found.")
        return 0
    print(expenses_table(expenses))
    return 0


def _handle_edit(db: ExpenseDatabase, args: argparse.Namespace) -> int:
    expense = db.get_expense(args.id)
    if expense is None:
        raise ValueError(f"Expense #{args.id} was not found")

    if (
        args.amount is None
        and args.category is None
        and args.description is None
        and args.date is None
    ):
        raise ValueError(
            "Provide at least one field to update (--amount, --category, --description, --date)"
        )

    if args.amount is not None:
        expense.amount = parse_amount(args.amount)
    if args.category is not None:
        expense.category = normalize_category(args.category)
    if args.description is not None:
        expense.description = args.description.strip()
    if args.date is not None:
        expense.date = parse_date(args.date)

    db.update_expense(expense)
    print(
        f"Updated expense #{expense.id}: {format_money(expense.amount)} "
        f"for '{expense.category}' on {expense.date.isoformat()}"
    )
    return 0


def _handle_delete(db: ExpenseDatabase, args: argparse.Namespace) -> int:
    if not db.delete_expense(args.id):
        raise ValueError(f"Expense #{args.id} was not found")
    print(f"Deleted expense #{args.id}.")
    return 0


def _handle_summary(db: ExpenseDatabase, args: argparse.Namespace) -> int:
    start, end = _resolve_date_range(args)
    totals = dict(db.category_totals(start=start, end=end))
    budgets = db.get_budgets()
    if not totals and not budgets:
        print("No expenses or budgets recorded yet.")
        return 0
    print(summary_table(totals, budgets))
    for warning in budget_warnings(totals, budgets):
        print(warning)
    return 0


def _handle_budget(db: ExpenseDatabase, args: argparse.Namespace) -> int:
    tokens: List[str] = list(args.args)

    if args.remove:
        category = normalize_category(args.remove)
        if not db.delete_budget(category):
            raise ValueError(f"No budget found for category '{category}'")
        print(f"Removed budget for '{category}'.")
        return 0

    if not tokens or (len(tokens) == 1 and tokens[0].lower() == "list"):
        budgets = db.get_budgets()
        if not budgets:
            print("No budgets set.")
            return 0
        rows = [[cat, format_money(limit)] for cat, limit in budgets.items()]
        print(format_table(["Category", "Monthly Budget"], rows, right_align=[1]))
        return 0

    action = tokens[0].lower()
    if action in ("remove", "delete", "rm") and len(tokens) == 2:
        category = normalize_category(tokens[1])
        if not db.delete_budget(category):
            raise ValueError(f"No budget found for category '{category}'")
        print(f"Removed budget for '{category}'.")
        return 0

    if action == "set" and len(tokens) == 3:
        raw_category, raw_limit = tokens[1], tokens[2]
    elif len(tokens) == 2 and action not in ("set", "remove", "delete", "rm", "list"):
        raw_category, raw_limit = tokens[0], tokens[1]
    else:
        raise ValueError(
            "Usage: budget [set] <category> <limit> | budget list | budget remove <category>"
        )

    category = normalize_category(raw_category)
    limit = parse_amount(raw_limit)
    db.set_budget(category, limit)
    print(f"Set monthly budget for '{category}' to {format_money(limit)}.")
    return 0


def _handle_export(db: ExpenseDatabase, args: argparse.Namespace) -> int:
    output_path = args.output_flag or args.output or "expenses.csv"
    start, end = _resolve_date_range(args)
    category = normalize_category(args.category) if args.category else None
    expenses = db.list_expenses(start=start, end=end, category=category)
    count = export_to_csv(expenses, output_path)
    print(f"Exported {count} expense(s) to {output_path}.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse command-line arguments and run the chosen subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        with ExpenseDatabase(args.db) as db:
            return int(args.handler(db, args))
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
