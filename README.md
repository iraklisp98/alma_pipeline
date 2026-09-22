# CSV data preparation assessment

A small pandas pipeline converts the supplied employee, project and timesheet CSVs into clean tables, accepted-hour summaries and a validation report. Source files are never modified.

## Run

Python 3.10+ is required. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pipeline.run
python -m unittest discover -s tests -v
```

The pipeline uses repository-relative paths and writes to `outputs/`. No database, credentials or external service is required. It was verified using Python 3.12 and pandas 3.0.2. The notebook additionally requires a Jupyter-compatible environment; Jupyter is not a runtime dependency of the pipeline.

## Structure

- [EDA.ipynb](EDA.ipynb): initial exploration and evidence behind the rules.
- [architecture.md](architecture.md): stage responsibilities, scope and trade-offs.
- [diagram.md](diagram.md): Mermaid pipeline and ER diagrams.
- `pipeline/prepare.py`: raw ingestion, whitespace/null normalization and explicit parsing.
- `pipeline/validate.py`: dimension and timesheet validation, an issue ledger, and final output integrity checks.
- `pipeline/transform.py`: clean column selection and two aggregations.
- `pipeline/run.py`: stage orchestration and CSV writing; calls `verify_outputs()` before export.
- [schema.sql](schema.sql): executable SQLite schema; database loading is not part of the runner.

The stages pass DataFrames explicitly. Validation has no filesystem side effects. Raw values are kept separately from prepared values; every input record gets a source table and one-based parsed record number for audit purposes.

## Rules and assumptions

| Area | Treatment |
|---|---|
| Text | Trim outer whitespace, convert empty fields to null, preserve names and accents. |
| IDs | Require `E###` / `P###`; reject missing or malformed IDs. |
| Dimension duplicates | Keep the first identical normalized row; reject extra copies. Hold conflicting versions of an ID for review. |
| Missing descriptions | Flag for review, retaining the valid unique ID and null attribute in the clean dimension. |
| Budget | Require a finite nonnegative scalar; flag invalid/missing values and write null. Do not guess the midpoint of a range or a currency. |
| Dates | Accept `DD/MM/YYYY`, `YYYY-MM-DD`, and English `DD-Mon-YY`. Slash dates are day-first; two-digit years mean 2000–2099. Reject other or impossible dates. |
| Hours | Trim and lowercase hours for exact matching of English words `one` through `ten` to 1–10. Require numeric `0 < hours <= 24`; reject other text, missing values, infinity and invalid ranges. Preserve original values. |
| References | Reject unknown employees/projects; hold references to conflicting dimension IDs for review. |
| Timesheet grain | Assume one record per employee/project/day. Remove identical parsed copies; hold conflicting entries and the remaining work on that employee/day for review. |
| Daily totals | After removing invalid rows and duplicates, reject all contributing records if an unambiguous employee/day total exceeds 24 hours across projects. |

Missing employee descriptions and uncertain project budgets do **not** block otherwise valid work. Weekend work and days above 12 but at most 24 hours are not automatically errors. Positive-only hours assume ordinary work entries, not negative corrections. The date interpretation and one-entry-per-day grain require source-owner confirmation; multiple legitimate entries would require a stable source entry ID.

**Difference from the exploratory notebook:** its stricter preview excluded incomplete dimensions and dependent timesheets, and proposed a 12-hour review threshold. The implementation follows the subsequently simplified architecture above. Its counts therefore differ intentionally; the notebook remains the original exploration record.

## Record decisions and audit outputs

Every source record gets exactly one final status: `accepted`, `review`, or `rejected`. Rejection takes precedence when multiple issues apply.

- Accepted records enter clean outputs.
- Reviewed dimension records with only missing descriptions or uncertain budgets can enter clean dimensions with null attributes. `include_in_clean` makes that exception explicit in `review_records.csv`.
- Conflicting dimensions and reviewed timesheets are excluded until corrected.
- Rejected records, including duplicate copies, are excluded and retained in `rejected_records.csv`.

[validation_issues.csv](outputs/validation_issues.csv) contains source table, record number, column, original value, rule, issue status and reason. Several issues may refer to one record, and an issue's status can differ from the record's final status. Join audit files on `(source_table, source_record)`. The review/rejected files combine source schemas, so some columns are intentionally empty for other record types. Original CSVs remain the authoritative raw data.

## Generated results

| Dataset | Input | Accepted | Review | Rejected | Clean output |
|---|---:|---:|---:|---:|---:|
| Employees | 42 | 38 | 2 | 2 | 40 |
| Projects | 39 | 31 | 4 | 4 | 35 |
| Timesheets | 343 | 332 | 0 | 11 | 332 |

Input counts equal accepted + review + rejected. Clean dimension counts also include usable reviewed records; they are not the same as accepted-status counts.

The 332 clean timesheets total **2,390 accepted hours**, including the entry normalized from `seven` to `7`. The 11 rejected timesheet records comprise two duplicate copies, four unknown references, one missing employee ID and four invalid hour values.

The runner writes eight files:

- [employees_clean.csv](outputs/employees_clean.csv), [projects_clean.csv](outputs/projects_clean.csv), [timesheets_clean.csv](outputs/timesheets_clean.csv).
- [hours_by_project.csv](outputs/hours_by_project.csv), [hours_by_employee.csv](outputs/hours_by_employee.csv).
- [validation_issues.csv](outputs/validation_issues.csv), [review_records.csv](outputs/review_records.csv), [rejected_records.csv](outputs/rejected_records.csv).

Summaries group accepted timesheets by ID, then join names with a many-to-one check. Missing names cannot remove hours. Only entities with accepted work appear in summaries; clean dimensions also include entities without work. Both summary totals must equal the clean timesheet total. Dates use ISO format, nulls are empty CSV fields, and output order is deterministic.

## Schema and enforcement

The ER diagram has employees and projects as dimensions and timesheets as their linking fact table. The proposed timesheet primary key is `(employee_id, project_id, work_date)` under the stated grain assumption. Descriptions and budget are nullable; their quality issues are recorded separately.

`schema.sql` uses SQLite 3 and enforces primary keys, foreign keys, ID formats, nonblank populated descriptions, and numeric ranges. Enable foreign keys on every connection. SQLite stores dates as ISO text and uses numeric affinity rather than fixed-precision decimal storage. Python checks calendar validity and aggregate daily limits. A database with exact `NUMERIC` storage would be preferable if monetary calculations were added.

The tests create the schema in memory, load the clean outputs and verify foreign-key and hours constraints. For a manual empty database, if the SQLite CLI is installed:

```bash
sqlite3 assessment.db < schema.sql
```

Then inspect the database from the repository root:

```bash
# List all tables
sqlite3 assessment.db ".tables"

# Show the full schema, including constraints
sqlite3 assessment.db ".schema"

# Show the schema for one table
sqlite3 assessment.db ".schema timesheets"
```

The creation command creates empty tables; it does not import the pipeline's CSV outputs. Run it once for a new database. If the tables already exist, use the inspection commands directly.

## Repeatability and checks

Every run rebuilds working frames and issues from the original inputs and overwrites fixed output files; it never appends. Repeating a successful run on the same inputs produces identical CSV bytes. Checks run before export and cover row accounting, unique clean keys, valid references, positive hours, daily totals and aggregate reconciliation. Run normally, without Python's `-O` flag, which disables the internal assertions.

Eight focused tests cover case-insensitive hour-word mapping, bad dates/hours/references, usable incomplete dimensions, duplicate/conflict handling, daily totals, structural CSV errors, empty clean outputs, repeatable output and the SQL schema.

An interrupted export can leave a partially refreshed output folder. Rerun after correcting the failure. For this assessment there are no concurrent writers, transaction manager, immutable run history or review application. Correct the source records using authoritative information and rerun; do not edit generated outputs.

With more time: add an explicit correction workflow, atomic output publication, stable source entry IDs, and incremental or database loading. The current implementation deliberately remains a local batch script that is easy to inspect.
