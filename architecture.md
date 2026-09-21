# Assessment pipeline architecture

Build a small Python/pandas batch pipeline that reads the three supplied CSVs, validates and cleans their contents, and writes analysis-ready outputs. This design targets roughly five hours of total assessment work, including exploration and documentation. It does not require production infrastructure.

`EDA.ipynb` documents the exploration. [diagram.md](diagram.md) shows the proposed pipeline and relational model. The modules below are implemented in `pipeline/`.

## Repository structure

```text
employees.csv                 # Original inputs; never overwritten
projects.csv
timesheets.csv
EDA.ipynb                     # Exploration and observed issues
pipeline/
    __init__.py
    run.py                    # Orchestrate stages and write outputs
    prepare.py                # Read, normalize and parse working copies
    validate.py               # Rules, record classifications and issue report
    transform.py              # Clean tables and hours summaries
outputs/
    employees_clean.csv
    projects_clean.csv
    timesheets_clean.csv
    hours_by_project.csv
    hours_by_employee.csv
    validation_issues.csv
    review_records.csv
    rejected_records.csv
schema.sql                    # Proposed database tables and constraints
diagram.md                   # Pipeline and ER diagrams
architecture.md
README.md                     # Setup, command, assumptions and trade-offs
requirements.txt
tests/
    test_pipeline.py          # A few focused validation and rerun checks
```

Run the implementation from the repository root with `python -m pipeline.run`. Use paths relative to the repository, not machine-specific paths. `run.py` exposes a small `run(input_dir, output_dir)` function so tests can use temporary folders.

## Stages and responsibilities

| Stage | Module | Responsibility |
|---|---|---|
| Raw | `prepare.py` | Read the CSVs as strings, check expected columns, preserve original frames and attach a source record number. |
| Prepared | `prepare.py` | Trim surrounding whitespace, normalize empty values to null, and parse dates and numbers on copies. |
| Validated | `validate.py` | Validate dimensions first, then timesheets. Return clean candidates, review/rejected records and row-level issues. |
| Transformed | `transform.py` | Select clean columns and calculate accepted hours by project and employee. |
| Verification | `validate.py` | After transformation, `verify_outputs()` checks row accounting, clean keys, references and totals. |
| Output | `run.py` | Coordinate the stages and write the verified CSV outputs. |

Pass DataFrames explicitly between functions. Keep validation separate from file writing. A missing file or unexpected CSV schema stops the run with a clear error; a bad business record is reported without stopping other records from being processed.

## Cleaning and validation rules

### Common rules

- Preserve raw values and a one-based source record number for tracing issues. The number identifies a parsed record, not a physical file line or permanent business ID.
- Trim surrounding whitespace and convert empty fields to null. Preserve names, accents and case.
- Require employee IDs in the provisional format `E###` and project IDs in `P###`.
- Remove identical duplicate copies, keeping the first in source order. Report removed copies as rejected with a duplicate reason.
- Do not resolve conflicting records by arbitrarily keeping the last row.

### Employees and projects

- Reject missing or malformed IDs.
- Review all distinct records sharing an ID but containing conflicting attributes. Exclude those unresolved IDs from clean dimensions.
- Flag missing employee names/roles and project names for review. Keep the identifiable record in the clean dimension with a null description.
- Parse budget as a finite, nonnegative number. Flag missing, negative, nonnumeric or range-valued budgets for review and represent the clean budget as null. Do not infer a midpoint for `55000-60000`.
- Do not enforce a role vocabulary or budget currency that was not supplied.

Incomplete descriptive fields or uncertain budgets do not make an otherwise valid timesheet unusable. This is a deliberate simplification from the notebook's strict policy, which held those dependent timesheets for review. It changes the expected output counts; calculate them from the implementation rather than copying the notebook baseline.

### Timesheets

- Parse the observed formats explicitly: `DD/MM/YYYY`, `YYYY-MM-DD`, and English `DD-Mon-YY`. Assume slash dates are day-first and two-digit years mean 2000–2099. Reject missing or invalid dates.
- Trim and lowercase hours for exact matching against a dictionary mapping `one` through `ten` to 1–10. Then require finite numeric hours with `0 < hours <= 24`. Reject missing hours, other text such as `not_a_number` or `seven hours`, and out-of-range values. Preserve raw values; do not guess other text.
- Reject references to IDs absent from the source dimensions. Hold references to conflicting, unresolved dimension IDs for review.
- Provisionally assume one entry per employee/project/day. Remove identical parsed copies; hold conflicting hours at that grain for review. Confirm this assumption in the README.
- Check total hours per employee/day across projects after removing invalid rows and duplicates. If an employee/day has unresolved grain conflicts, hold that day's remaining entries for review rather than calculate a definitive total. Otherwise reject all contributing entries when the total exceeds 24 hours.
- Do not introduce a separate 12-hour cutoff. Long but possible days and weekend work are not automatically errors without a business rule.

## Accepted, review and rejected records

Use one final status per source record, with `rejected` taking precedence over `review`, and `accepted` meaning no unresolved issue.

| Status | Handling |
|---|---|
| Accepted | Include in clean outputs. |
| Review | Preserve for correction. Dimension rows with valid unique IDs and only incomplete descriptions/budgets can also appear in clean dimensions with nulls; unresolved dimension conflicts and timesheet review rows remain excluded. |
| Rejected | Exclude from clean outputs and retain the original record with reasons, including redundant duplicate copies. |

A review status therefore does not always mean exclusion from clean dimensions. Keep an explicit `include_in_clean` flag in the validation result so the rule is visible and testable. This exception never applies to timesheet review rows.

`validation_issues.csv` has one row per issue:

```text
source_table, source_record, column, raw_value, rule, status, reason
```

A source record may have several issues. The review and rejected files contain the original fields, source table, source record number and final status. Combining the three source schemas in these small CSVs produces unused columns for some rows; that is acceptable for this assessment.

Check that every source record receives exactly one status:

```text
input rows = accepted rows + review rows + rejected rows
```

This equation counts dispositions, not clean output rows: some reviewed dimension records remain usable. Print a short summary of status counts and clean counts when the pipeline finishes.

## Transformations and outputs

Produce three clean tables:

- Employees: `employee_id`, `name`, `role`.
- Projects: `project_id`, `project_name`, `budget`.
- Timesheets: `employee_id`, `project_id`, `date`, `hours`.

Produce two small summaries:

- Hours by project: `project_id`, `project_name`, `total_hours`, `timesheet_count`.
- Hours by employee: `employee_id`, `name`, `total_hours`, `timesheet_count`.

Aggregate only accepted timesheets. Group by IDs, then join dimension labels with a many-to-one join check. Include only employees/projects with accepted work in these summaries; document that zero-activity entities remain available in the clean dimensions. Missing names must not cause hours to disappear from grouping.

Export dates as `YYYY-MM-DD`, sort by stable keys, and check that both summaries reconcile to the clean timesheet total. The supplied hours are integers or half-hours, so pandas numeric arithmetic is sufficient here. Use SQL `NUMERIC` for the proposed database schema and discuss precision if future data requires it. Do not calculate costs or budget utilization without rates and currency.

## Proposed relational schema

| Table | Fields and constraints |
|---|---|
| `employees` | `employee_id VARCHAR(4) PRIMARY KEY`, `name TEXT NULL`, `role TEXT NULL`. |
| `projects` | `project_id VARCHAR(4) PRIMARY KEY`, `project_name TEXT NULL`, `budget NUMERIC NULL CHECK (budget >= 0)`. |
| `timesheets` | `employee_id VARCHAR(4) NOT NULL REFERENCES employees(employee_id)`, `project_id VARCHAR(4) NOT NULL REFERENCES projects(project_id)`, `work_date DATE NOT NULL`, `hours NUMERIC NOT NULL CHECK (hours > 0 AND hours <= 24)`. Composite primary key: `(employee_id, project_id, work_date)`. |

Nullable descriptive fields and budget represent known data-quality gaps; the issue report records why they are missing. Require valid ID formats and reject nonfinite numeric values in the pipeline. Use database primary keys, foreign keys, types and range checks as a second line of protection. Avoid cascading deletion of work history.

Parsing, duplicate decisions, review routing and daily totals belong in the pipeline. A row-level database check cannot enforce hours summed across multiple records.

The timesheet composite key depends on the stated grain assumption. If multiple daily entries are legitimate, obtain a source entry ID instead. The delivered `schema.sql` uses SQLite 3: dates are ISO text and `NUMERIC` is affinity rather than exact decimal storage. The tests load clean outputs into this schema. A database with fixed-precision `NUMERIC` would be appropriate for monetary calculations. Delivering the schema and ER diagram is sufficient; a running database or database loader is not necessary for this submission.

## Safe reruns and verification

Read unchanged inputs, rebuild every stage in memory, and overwrite the fixed output files rather than append. Use deterministic sorting and reset issue collections for every run. Validate all results before writing. This provides repeatable successful runs without duplicate accumulation.

The simple writer does not guarantee atomic replacement of the entire output folder if interrupted during export. Document that limitation and rerun after a failure. Run hashes, manifests, historical run directories and concurrency controls are outside this assessment's scope.

Keep verification focused:

- Test exact duplicates versus conflicting IDs/grains, invalid dates/hours and unknown references.
- Test that incomplete dimension attributes do not discard valid work and that review timesheets stay excluded.
- Test employee/day totals across projects.
- Check row accounting, clean uniqueness, foreign keys and aggregate totals.
- Run twice against a small fixture into a temporary output folder and compare outputs.

## README and time budget

The README should explain installation, the run command, stages, output files, rules and assumptions, rerun behavior, and a short future-improvements section. Explicitly call out the date interpretation, timesheet grain, positive-hours assumption, and nullable dimension policy.

With more time, add a correction workflow, atomic output publication, stable source entry IDs and incremental/database loading. Mention these as extensions rather than implementing them for the assessment.
