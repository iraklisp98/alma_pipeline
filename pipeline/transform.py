"""Select clean columns and summarize accepted work."""

def transform(validated):
    selected = {name: frame.loc[frame["include_in_clean"]].copy() for name, frame in validated.items()}
    employees = selected["employees"][["employee_id", "name", "role"]].sort_values("employee_id").reset_index(drop=True)
    projects = (selected["projects"][["project_id", "project_name", "budget_numeric"]]
                .rename(columns={"budget_numeric": "budget"}).sort_values("project_id").reset_index(drop=True))
    timesheets = (selected["timesheets"][["employee_id", "project_id", "work_date", "hours_numeric"]]
                  .rename(columns={"work_date": "date", "hours_numeric": "hours"})
                  .sort_values(["employee_id", "project_id", "date"]).reset_index(drop=True))
    outputs = {"employees_clean": employees, "projects_clean": projects, "timesheets_clean": timesheets}
    for entity, key, label, dimension in [("project", "project_id", "project_name", projects),
                                         ("employee", "employee_id", "name", employees)]:
        totals = timesheets.groupby(key, as_index=False).agg(total_hours=("hours", "sum"), timesheet_count=("hours", "size"))
        totals = totals.merge(dimension[[key, label]], on=key, validate="many_to_one")
        outputs[f"hours_by_{entity}"] = totals[[key, label, "total_hours", "timesheet_count"]].sort_values(key).reset_index(drop=True)
    return outputs
