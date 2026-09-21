"""Focused behavior tests; no external services or additional test packages."""
import contextlib
import csv
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pandas as pd

from pipeline.prepare import COLUMNS, prepare
from pipeline.run import run
from pipeline.validate import validate

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def fixture(self, directory, timesheets, employees=None, projects=None):
        rows = {
            "employees": employees if employees is not None else [["E001", "Alice", "Engineer"]],
            "projects": projects if projects is not None else [["P001", "Project", "100"], ["P002", "Other", "200"]],
            "timesheets": timesheets,
        }
        for table, data in rows.items():
            with (Path(directory) / f"{table}.csv").open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(COLUMNS[table])
                writer.writerows(data)
        return validate(*prepare(directory))

    def test_dates_hours_and_references(self):
        with tempfile.TemporaryDirectory() as directory:
            frames, issues = self.fixture(directory, [
                ["E001", "P001", "07/01/2024", "8"],
                ["E001", "P001", "2024-01-08", "7.5"],
                ["E001", "P001", "10-Jan-24", "6"],
                ["E001", "P001", "31/02/2024", "8"],
                ["E001", "P001", "11/01/2024", "not_a_number"],
                ["E099", "P001", "12/01/2024", "8"],
                ["E001", "P999", "13/01/2024", "8"],
                ["", "P001", "14/01/2024", "8"],
                *[["E001", "P001", "15/01/2024", value] for value in ["", "0", "-1", "25", "inf"]],
            ])
            self.assertEqual(frames["timesheets"]["include_in_clean"].sum(), 3)
            self.assertEqual(frames["timesheets"].iloc[0]["work_date"], pd.Timestamp("2024-01-07"))
            self.assertTrue({"invalid_date", "invalid_hours", "unknown_reference", "invalid_id"}.issubset(set(issues["rule"])))

    def test_hour_words_are_case_insensitive_exact_matches(self):
        words = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
        values = [f" {word.upper()} " for word in words] + ["SeVeN", "eleven", "seven hours", "not_a_number"]
        with tempfile.TemporaryDirectory() as directory:
            frames, _ = self.fixture(directory, [
                ["E001", "P001", f"{day:02}/01/2024", value]
                for day, value in enumerate(values, 1)
            ])
            times = frames["timesheets"]
            self.assertEqual(times["hours_numeric"].iloc[:11].tolist(), list(range(1, 11)) + [7])
            self.assertEqual(times["status"].tolist(), ["accepted"] * 11 + ["rejected"] * 3)
            raw, _ = prepare(directory)
            self.assertEqual(raw["timesheets"].iloc[0]["hours"], " ONE ")

    def test_nullable_dimensions_keep_valid_work(self):
        with tempfile.TemporaryDirectory() as directory:
            frames, _ = self.fixture(directory, [["E001", "P001", "01/01/2024", "8"]],
                employees=[[" E001 ", " ", "Engineer"]], projects=[["P001", "", "55000-60000"]])
            self.assertEqual(frames["employees"].iloc[0]["status"], "review")
            self.assertTrue(frames["employees"].iloc[0]["include_in_clean"])
            self.assertTrue(pd.isna(frames["projects"].iloc[0]["budget_numeric"]))
            self.assertEqual(frames["timesheets"].iloc[0]["status"], "accepted")

    def test_dimension_duplicates_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            frames, issues = self.fixture(directory, [["E001", "P001", "01/01/2024", "8"]],
                employees=[["E001", "Alice", "Engineer"], ["E001", "Alice", "Engineer"], ["E001", "Bob", "Engineer"]])
            self.assertEqual(frames["employees"]["status"].tolist(), ["review", "rejected", "review"])
            self.assertFalse(frames["employees"]["include_in_clean"].any())
            self.assertEqual(frames["timesheets"].iloc[0]["status"], "review")
            self.assertIn("unresolved_reference", set(issues["rule"]))

    def test_semantic_duplicates_conflicts_and_daily_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            frames, issues = self.fixture(directory, [
                ["E001", "P001", "01/01/2024", "8"],
                ["E001", "P001", "2024-01-01", "8.0"],
                ["E001", "P001", "02/01/2024", "13"],
                ["E001", "P002", "02/01/2024", "12"],
                ["E001", "P001", "03/01/2024", "7"],
                ["E001", "P001", "03/01/2024", "8"],
                ["E001", "P002", "03/01/2024", "10"],
                ["E001", "P001", "04/01/2024", "24"],
            ])
            self.assertEqual(frames["timesheets"]["status"].tolist(),
                             ["accepted", "rejected", "rejected", "rejected", "review", "review", "review", "accepted"])
            self.assertEqual((issues["rule"] == "daily_hours_over_24").sum(), 2)

    def test_schema_errors_stop_ingestion(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fixture(directory, [])
            path = Path(directory) / "employees.csv"
            for text in ["wrong,name,role\n", "employee_id,name,role\nE001,A,B,extra\n"]:
                path.write_text(text)
                with self.assertRaises(ValueError):
                    prepare(directory)

    def test_empty_clean_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fixture(directory, [["E001", "P001", "invalid", "seven"]])
            with contextlib.redirect_stdout(io.StringIO()):
                outputs, _ = run(directory, Path(directory) / "out")
            self.assertTrue(outputs["timesheets_clean"].empty)
            self.assertTrue(outputs["hours_by_project"].empty)

    def test_supplied_data_reruns_and_sql_constraints(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            outputs, summary = run(ROOT, directory)
            first = {p.name: p.read_bytes() for p in Path(directory).glob("*.csv")}
            run(ROOT, directory)
            self.assertEqual(first, {p.name: p.read_bytes() for p in Path(directory).glob("*.csv")})
            self.assertEqual(summary["clean"].tolist(), [40, 35, 332])
            self.assertEqual(outputs["timesheets_clean"]["hours"].sum(), 2390)
            connection = sqlite3.connect(":memory:")
            self.addCleanup(connection.close)
            connection.executescript((ROOT / "schema.sql").read_text())
            for name, table in [("employees_clean", "employees"), ("projects_clean", "projects"), ("timesheets_clean", "timesheets")]:
                frame = outputs[name].copy()
                if "date" in frame:
                    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
                rows = frame.astype(object).where(frame.notna(), None).itertuples(index=False, name=None)
                marks = ",".join("?" for _ in frame.columns)
                connection.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)
            for values in [("E999", "P001", "2024-06-01", 8), ("E001", "P001", "2024-06-01", 25)]:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO timesheets VALUES (?, ?, ?, ?)", values)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM timesheets").fetchone()[0], 332)


if __name__ == "__main__":
    unittest.main()
