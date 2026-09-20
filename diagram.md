# Assessment pipeline

Flow of the small Python/pandas implementation. See [architecture.md](architecture.md) for rules and module responsibilities.

```mermaid
flowchart TD
    INPUT["Original CSVs<br/>employees · projects · timesheets"]
    PREP["prepare.py<br/>Read strings and check columns<br/>Preserve raw values and source record numbers<br/>Trim blanks and parse dates/numbers"]
    DIM["validate.py: dimensions<br/>IDs · duplicates · conflicts<br/>Missing descriptions · invalid budgets"]
    DIMCLEAN["Usable employees and projects<br/>Allow flagged null descriptions/budgets"]
    TIME["validate.py: timesheets<br/>Dates · hours · references<br/>Duplicates · grain conflicts · daily totals"]
    VALID["Accepted timesheets"]
    AUDIT["Validation issues<br/>Review records<br/>Rejected records"]
    TRANSFORM["transform.py<br/>Clean tables<br/>Hours by project and employee"]
    CHECK["run.py: verify results<br/>Row accounting · unique keys · valid references<br/>Summary totals match clean hours"]
    OUTPUT["run.py: write outputs<br/>Overwrite fixed CSV files<br/>Print validation summary"]
    ERROR["Stop with a clear error<br/>Fix the problem and rerun"]

    INPUT --> PREP
    PREP -->|"Employee and project frames"| DIM
    PREP -->|"Timesheet frame"| TIME
    PREP -->|"Missing file or invalid CSV schema"| ERROR
    DIM --> DIMCLEAN
    DIM --> AUDIT
    DIMCLEAN -->|"Valid reference IDs"| TIME
    DIM -->|"Known IDs and unresolved conflicts"| TIME
    TIME --> VALID
    TIME --> AUDIT
    DIMCLEAN --> TRANSFORM
    VALID --> TRANSFORM
    TRANSFORM --> CHECK
    AUDIT --> CHECK
    CHECK -->|"Checks pass"| OUTPUT
    CHECK -->|"Checks fail"| ERROR
```

Raw input files stay unchanged. Repeated successful runs rebuild and overwrite the same outputs rather than append data. An interrupted export requires a rerun; atomic publication is outside this assessment's scope.

Review records need a source correction or an explicit business decision. Unique, valid dimension IDs with incomplete descriptive fields or uncertain budgets remain usable with null attributes and reported issues. Conflicting dimensions and all timesheet review records are excluded from clean outputs. Only accepted timesheet hours enter summaries.

# Proposed relational model

```mermaid
erDiagram
    EMPLOYEES ||--o{ TIMESHEETS : records
    PROJECTS ||--o{ TIMESHEETS : receives

    EMPLOYEES {
        varchar employee_id PK
        text name "nullable"
        text role "nullable"
    }

    PROJECTS {
        varchar project_id PK
        text project_name "nullable"
        numeric budget "nullable; nonnegative when present"
    }

    TIMESHEETS {
        varchar employee_id PK, FK
        varchar project_id PK, FK
        date work_date PK
        numeric hours "greater than 0 and at most 24"
    }
```

Each timesheet belongs to exactly one employee and one project; an employee or project can have zero timesheets. The three `PK` fields in `TIMESHEETS` form a single composite key, assuming one entry per employee/project/day. If multiple entries are legitimate, use a stable source entry ID instead.

The ER diagram describes the proposed clean schema. Review/rejected records and validation issues are separate CSV audit outputs. The assessment delivers schema definitions; operating a database is not required.
