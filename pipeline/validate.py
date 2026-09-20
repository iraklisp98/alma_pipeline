"""Explicit rules and a row-level issue ledger; no filesystem writes."""
import math

import pandas as pd

from .prepare import COLUMNS

ISSUE_COLUMNS = ["source_table", "source_record", "column", "raw_value", "rule", "status", "reason"]


def validate(raw, prepared):
    frames = {name: df.copy(deep=True) for name, df in prepared.items()}
    issues = []
    for frame in frames.values():
        frame["status"] = "accepted"
        frame["include_in_clean"] = True

    def flag(table, mask, column, rule, status, reason, exclude=True):
        frame = frames[table]
        mask = mask.reindex(frame.index, fill_value=False).fillna(False)
        for index in frame.index[mask]:
            issues.append({"source_table": table, "source_record": int(frame.at[index, "source_record"]),
                           "column": column, "raw_value": raw[table].at[index, column],
                           "rule": rule, "status": status, "reason": reason})
        if status == "rejected":
            frame.loc[mask, "status"] = status
        else:
            frame.loc[mask & frame["status"].ne("rejected"), "status"] = status
        if exclude:
            frame.loc[mask, "include_in_clean"] = False

    for table, frame in frames.items():
        for column in [c for c in COLUMNS[table] if c.endswith("_id")]:
            prefix = "E" if column == "employee_id" else "P"
            flag(table, ~frame[column].str.fullmatch(prefix + r"\d{3}", na=False), column,
                 "invalid_id", "rejected", "Missing identifier or invalid format; expected prefix plus three digits.")

    for table, key, descriptions in [("employees", "employee_id", ["name", "role"]),
                                     ("projects", "project_id", ["project_name"])]:
        frame = frames[table]
        duplicates = frame.duplicated(COLUMNS[table], keep="first")
        flag(table, duplicates, key, "duplicate_record", "rejected", "Identical normalized record; retain first source record.")
        distinct = frame.loc[~duplicates]
        conflicts = distinct.loc[distinct[key].notna() & distinct.duplicated(key, keep=False), key]
        flag(table, frame[key].isin(conflicts), key, "conflicting_id", "review", "Different records share this identifier.")
        for column in descriptions:
            flag(table, frame[column].isna(), column, "missing_description", "review",
                 "Keep identifiable record with a null attribute; request correction.", exclude=False)

    projects = frames["projects"]
    budget = projects["budget_numeric"]
    invalid_budget = budget.isna() | budget.lt(0) | budget.isin([float("inf"), -float("inf")])
    flag("projects", invalid_budget, "budget", "invalid_budget", "review",
         "Budget must be a finite nonnegative scalar; use null until corrected.", exclude=False)
    projects.loc[invalid_budget, "budget_numeric"] = pd.NA

    times = frames["timesheets"]
    hours = times["hours_numeric"]
    flag("timesheets", hours.isna() | ~hours.between(0, 24, inclusive="right"), "hours",
         "invalid_hours", "rejected", "Require finite numeric hours with 0 < hours <= 24.")
    flag("timesheets", times["work_date"].isna(), "date", "invalid_date", "rejected",
         "Missing, unsupported or impossible date.")
    for column, parent in [("employee_id", "employees"), ("project_id", "projects")]:
        known = frames[parent][column].dropna()
        usable = frames[parent].loc[frames[parent]["include_in_clean"], column]
        flag("timesheets", times[column].notna() & ~times[column].isin(known), column,
             "unknown_reference", "rejected", "Identifier is absent from the source dimension.")
        flag("timesheets", times[column].isin(known) & ~times[column].isin(usable), column,
             "unresolved_reference", "review", "Referenced dimension has no usable, unambiguous record.")

    grain = ["employee_id", "project_id", "work_date"]
    comparable = times.loc[times[grain + ["hours_numeric"]].notna().all(axis=1)]
    duplicate_indices = comparable.index[comparable.duplicated(grain + ["hours_numeric"], keep="first")]
    flag("timesheets", pd.Series(times.index.isin(duplicate_indices), index=times.index), "hours",
         "duplicate_record", "rejected", "Identical parsed entry; retain first source record.")
    # Only plausible, nonduplicate work can create ambiguous daily totals.
    candidates = times.loc[times["status"].ne("rejected")]
    conflicts = candidates.loc[candidates.duplicated(grain, keep=False)]
    day_key = ["employee_id", "work_date"]
    ambiguous_days = pd.MultiIndex.from_frame(conflicts[day_key])
    ambiguous = pd.Series(pd.MultiIndex.from_frame(times[day_key]).isin(ambiguous_days), index=times.index)
    flag("timesheets", ambiguous & times["status"].ne("rejected"), "hours",
         "ambiguous_work_day", "review", "Conflicting entries exist for this employee/day; resolve before totaling.")
    candidates = times.loc[times["status"].ne("rejected") & ~ambiguous]
    totals = candidates.groupby(day_key)["hours_numeric"].transform("sum")
    flag("timesheets", totals.gt(24), "hours", "daily_hours_over_24", "rejected",
         "Employee/day total exceeds 24 hours across projects; reject all contributing entries.")

    ledger = pd.DataFrame(issues, columns=ISSUE_COLUMNS).sort_values(
        ["source_table", "source_record", "rule"], kind="stable").reset_index(drop=True)
    return frames, ledger


def verify_outputs(raw, validated, outputs):
    """Check transformed output integrity before any files are written."""
    for table, frame in validated.items():
        assert len(frame) == len(raw[table]), f"Lost records: {table}"
        assert frame["source_record"].is_unique
        assert frame["status"].isin(["accepted", "review", "rejected"]).all()
        assert not (frame["status"].eq("rejected") & frame["include_in_clean"]).any()
    employees, projects, times = [outputs[f"{name}_clean"] for name in ["employees", "projects", "timesheets"]]
    assert employees["employee_id"].is_unique
    assert projects["project_id"].is_unique
    assert not times.duplicated(["employee_id", "project_id", "date"]).any()
    assert times["employee_id"].isin(employees["employee_id"]).all()
    assert times["project_id"].isin(projects["project_id"]).all()
    assert times["date"].notna().all()
    assert times["hours"].between(0, 24, inclusive="right").all()
    assert times.groupby(["employee_id", "date"])["hours"].sum().le(24).all()
    assert projects["budget"].dropna().ge(0).all()
    source_times = validated["timesheets"]
    assert source_times.loc[source_times["include_in_clean"], "status"].eq("accepted").all()
    for name in ["hours_by_project", "hours_by_employee"]:
        assert math.isclose(outputs[name]["total_hours"].sum(), times["hours"].sum(), abs_tol=1e-9)
        assert outputs[name]["timesheet_count"].sum() == len(times)
