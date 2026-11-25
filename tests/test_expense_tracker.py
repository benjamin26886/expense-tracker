"""Unit tests for models, database, reports and the CLI."""

from __future__ import annotations

import csv
import datetime as dt
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from expense_tracker.cli import main
from expense_tracker.database import ExpenseDatabase
from expense_tracker.models import (
    Expense,
    from_cents,
    month_bounds,
    normalize_category,
    parse_amount,
    parse_date,
    parse_month,
    to_cents,
)
from expense_tracker.reports import (
    budget_status,
    budget_warnings,
    expenses_table,
    export_to_csv,
    format_money,
    summary_table,
)


class ModelsTestCase(unittest.TestCase):
    """Tests for input parsing and money/date helpers."""

    def test_parse_amount_valid_inputs(self) -> None:
        self.assertEqual(parse_amount("12.50"), 12.50)
        self.assertEqual(parse_amount(" $1,234.567 "), 1234.57)
        self.assertEqual(parse_amount("0.01"), 0.01)

    def test_parse_amount_rejects_invalid_or_non_positive(self) -> None:
        for bad in ("", "abc", "0", "-5", "NaN", "Infinity"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_amount(bad)

    def test_cents_round_trip(self) -> None:
        self.assertEqual(to_cents(19.99), 1999)
        self.assertEqual(from_cents(1999), 19.99)

    def test_parse_date_and_month(self) -> None:
        self.assertEqual(parse_date("2026-11-16"), dt.date(2026, 11, 16))
        self.assertEqual(parse_month("2026-11"), (2026, 11))
        with self.assertRaises(ValueError):
            parse_date("16/11/2026")
        with self.assertRaises(ValueError):
            parse_month("2026-13")

    def test_month_bounds_handles_leap_year(self) -> None:
        start, end = month_bounds(2024, 2)
        self.assertEqual(start, dt.date(2024, 2, 1))
        self.assertEqual(end, dt.date(2024, 2, 29))

    def test_normalize_category(self) -> None:
        self.assertEqual(normalize_category("  Food "), "food")
        with self.assertRaises(ValueError):
            normalize_category("   ")


class DatabaseTestCase(unittest.TestCase):
    """Tests for SQLite CRUD, filtering, summaries and budgets."""

    def setUp(self) -> None:
        self.db = ExpenseDatabase(":memory:")

    def tearDown(self) -> None:
        self.db.close()

    def test_add_get_update_delete_expense(self) -> None:
        exp = Expense(15.25, "food", "Lunch", dt.date(2026, 11, 2))
        exp_id = self.db.add_expense(exp)
        self.assertEqual(exp_id, 1)

        loaded = self.db.get_expense(exp_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.amount, 15.25)
        self.assertEqual(loaded.category, "food")

        loaded.amount = 18.00
        loaded.description = "Lunch with coffee"
        self.assertTrue(self.db.update_expense(loaded))
        updated = self.db.get_expense(exp_id)
        assert updated is not None
        self.assertEqual(updated.amount, 18.00)
        self.assertEqual(updated.description, "Lunch with coffee")

        self.assertTrue(self.db.delete_expense(exp_id))
        self.assertIsNone(self.db.get_expense(exp_id))
        self.assertFalse(self.db.delete_expense(exp_id))

    def test_filters_and_monthly_summary(self) -> None:
        self.db.add_expense(Expense(10.0, "food", "Bagel", dt.date(2026, 10, 31)))
        self.db.add_expense(Expense(25.5, "food", "Groceries", dt.date(2026, 11, 5)))
        self.db.add_expense(Expense(40.0, "transport", "Metro pass", dt.date(2026, 11, 6)))

        nov = self.db.list_expenses(
            start=dt.date(2026, 11, 1), end=dt.date(2026, 11, 30)
        )
        self.assertEqual(len(nov), 2)

        only_food = self.db.list_expenses(category="food")
        self.assertEqual(len(only_food), 2)

        summary = self.db.monthly_summary(2026, 11)
        self.assertEqual(summary, [("transport", 40.0), ("food", 25.5)])

    def test_budgets_upsert_and_delete(self) -> None:
        self.db.set_budget("food", 200.0)
        self.db.set_budget("food", 250.0)
        self.assertEqual(self.db.get_budgets(), {"food": 250.0})
        self.assertTrue(self.db.delete_budget("food"))
        self.assertFalse(self.db.delete_budget("food"))


class ReportsTestCase(unittest.TestCase):
    """Tests for ASCII tables, budget warnings and CSV export."""

    def test_expenses_and_summary_tables(self) -> None:
        items = [
            Expense(12.5, "food", "Tacos", dt.date(2026, 11, 1), id=1),
            Expense(85.0, "utilities", "Internet", dt.date(2026, 11, 3), id=2),
        ]
        table = expenses_table(items)
        self.assertIn("Tacos", table)
        self.assertIn("$97.50", table)
        self.assertIn("2 expense(s)", table)

        summary = summary_table({"food": 90.0}, {"food": 100.0, "books": 30.0})
        self.assertIn("Near limit", summary)
        self.assertIn("books", summary)

    def test_budget_status_and_warnings(self) -> None:
        self.assertEqual(budget_status(50.0, 100.0), "OK")
        self.assertEqual(budget_status(80.0, 100.0), "Near limit")
        self.assertEqual(budget_status(115.0, 100.0), "OVER by $15.00")
        warnings = budget_warnings({"food": 120.0}, {"food": 100.0})
        self.assertEqual(len(warnings), 1)
        self.assertIn("over budget", warnings[0])
        self.assertEqual(format_money(1234.5), "$1,234.50")

    def test_export_to_csv(self) -> None:
        items = [Expense(9.99, "coffee", "Latte", dt.date(2026, 11, 4), id=1)]
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "out.csv")
            written = export_to_csv(items, csv_path)
            self.assertEqual(written, 1)
            with open(csv_path, encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(
                rows,
                [
                    ["id", "date", "category", "amount", "description"],
                    ["1", "2026-11-04", "coffee", "9.99", "Latte"],
                ],
            )


class CliTestCase(unittest.TestCase):
    """End-to-end tests for the CLI using a temporary SQLite file."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test.db")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def run_cli(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--db", self.db_path, *args])
        return code, out.getvalue(), err.getvalue()

    def test_full_cli_workflow(self) -> None:
        code, out, _ = self.run_cli("budget", "set", "food", "50")
        self.assertEqual(code, 0)
        self.assertIn("$50.00", out)

        code, out, _ = self.run_cli(
            "add", "30", "Food", "-d", "Groceries", "--date", "2026-11-10"
        )
        self.assertEqual(code, 0)
        self.assertIn("Added expense #1", out)

        code, out, _ = self.run_cli(
            "add", "25", "food", "-d", "Dinner", "--date", "2026-11-12"
        )
        self.assertEqual(code, 0)
        self.assertIn("WARNING: 'food' is over budget", out)

        code, out, _ = self.run_cli("list", "--month", "2026-11")
        self.assertEqual(code, 0)
        self.assertIn("Groceries", out)
        self.assertIn("$55.00", out)

        code, out, _ = self.run_cli("edit", "1", "--amount", "20")
        self.assertEqual(code, 0)
        self.assertIn("Updated expense #1", out)

        code, out, _ = self.run_cli("summary", "--month", "2026-11")
        self.assertEqual(code, 0)
        self.assertIn("$45.00", out)
        self.assertIn("Near limit", out)

        csv_path = os.path.join(self.tmpdir.name, "nov.csv")
        code, out, _ = self.run_cli("export", csv_path, "--month", "2026-11")
        self.assertEqual(code, 0)
        self.assertIn("Exported 2 expense(s)", out)

        code, out, _ = self.run_cli("delete", "2")
        self.assertEqual(code, 0)
        self.assertIn("Deleted expense #2", out)

    def test_cli_friendly_error_on_invalid_input(self) -> None:
        code, _, err = self.run_cli("add", "-10", "food")
        self.assertEqual(code, 1)
        self.assertIn("Error: Amount must be greater than zero", err)

        code, _, err = self.run_cli("delete", "999")
        self.assertEqual(code, 1)
        self.assertIn("Error: Expense #999 was not found", err)


if __name__ == "__main__":
    unittest.main()
