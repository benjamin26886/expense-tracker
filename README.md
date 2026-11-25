# Expense Tracker CLI

A lightweight, zero-dependency command-line expense tracker written in Python and backed by SQLite. It lets you log daily expenses, filter by date or category, set monthly category budgets with automatic over-budget alerts, view ASCII summary tables, and export records to CSV.

## Features

- **Add, edit, list, and delete expenses** from the terminal using `argparse` subcommands.
- **Exact money arithmetic**: parses input with `Decimal` and stores amounts as integer cents in SQLite to avoid floating-point rounding errors.
- **Flexible filtering**: filter expenses and exports by `--month YYYY-MM`, `--from YYYY-MM-DD`, `--to YYYY-MM-DD`, or `--category`.
- **Monthly category budgets**: set per-category spending limits and get immediate warnings when an expense pushes a category over budget.
- **Clean ASCII tables & CSV export**: readable terminal tables with right-aligned currency columns and one-command CSV export for spreadsheets.

## Example Terminal Usage

```text
$ python3 -m expense_tracker budget set food 200
Set monthly budget for 'food' to $200.00.

$ python3 -m expense_tracker add 42.50 food -d "Weekly groceries" --date 2026-11-10
Added expense #1: $42.50 for 'food' on 2026-11-10

$ python3 -m expense_tracker add 165.00 food -d "Dinner party" --date 2026-11-14
Added expense #2: $165.00 for 'food' on 2026-11-14
WARNING: 'food' is over budget - spent $207.50 of $200.00 (over by $7.50)

$ python3 -m expense_tracker list --month 2026-11
+----+------------+----------+---------+------------------+
| ID | Date       | Category |  Amount | Description      |
+----+------------+----------+---------+------------------+
|  1 | 2026-11-10 | food     |  $42.50 | Weekly groceries |
|  2 | 2026-11-14 | food     | $165.00 | Dinner party     |
+----+------------+----------+---------+------------------+
|    |            | TOTAL    | $207.50 | 2 expense(s)     |
+----+------------+----------+---------+------------------+

$ python3 -m expense_tracker summary --month 2026-11
+----------+---------+---------+-----------+---------------+
| Category |   Spent |  Budget | Remaining | Status        |
+----------+---------+---------+-----------+---------------+
| food     | $207.50 | $200.00 |    -$7.50 | OVER by $7.50 |
+----------+---------+---------+-----------+---------------+
| TOTAL    | $207.50 |         |           |               |
+----------+---------+---------+-----------+---------------+
WARNING: 'food' is over budget - spent $207.50 of $200.00 (over by $7.50)

$ python3 -m expense_tracker export november.csv --month 2026-11
Exported 2 expense(s) to november.csv.
```

## Setup

Requires **Python 3.9+**. Everything runs on the Python standard library (`sqlite3`, `argparse`, `csv`, `decimal`, `datetime`, `unittest`), so no third-party runtime packages are needed.

```bash
git clone <repo-url>
cd expense-tracker
python3 -m expense_tracker --help
```

By default, data is saved to `expenses.db` in the current directory. Pass `--db path/to/file.db` (or set `EXPENSE_TRACKER_DB`) to use a different database location.

## Project Structure

```text
expense-tracker/
├── expense_tracker/
│   ├── __init__.py      # Package metadata
│   ├── __main__.py      # `python3 -m expense_tracker` entry point
│   ├── cli.py           # argparse subcommands and error handling
│   ├── database.py      # SQLite schema, parameterized CRUD, and aggregations
│   ├── models.py        # Expense dataclass and input parsing/validation
│   └── reports.py       # ASCII table formatter, budget warnings, CSV export
├── tests/
│   ├── __init__.py
│   └── test_expense_tracker.py
├── .gitignore
├── LICENSE
├── README.md
└── requirements-dev.txt
```

## Running Tests

Run the unit test suite with Python's built-in `unittest` runner:

```bash
python3 -m unittest discover -s tests -t . -v
```

## What I Learned

- **Storing currency as integer cents**: floating-point numbers cannot represent `0.10` or `0.20` exactamente in binary, so parsing user input with `decimal.Decimal` and storing integer cents in SQLite prevents subtle rounding bugs.
- **Parameterized SQL queries**: passing user values via `?` placeholders rather than string formatting protects the database from SQL injection and handles quoting automatically.
- **Separating formatting from I/O**: keeping table and report builders as pure functions that return strings (`reports.py`) made unit testing straightforward without needing to mock the database.

## Future Improvements

- Recurring expenses (e.g. monthly rent and subscriptions).
- Multi-currency support with configurable exchange rates.
- Interactive terminal charts for month-over-month spending trends.
- CSV import to bulk-load bank statements.
