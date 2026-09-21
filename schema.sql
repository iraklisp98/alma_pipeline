-- SQLite 3 dialect. Schema illustration; the pipeline exports CSVs, not a database.
-- Enable foreign keys on every SQLite connection.
PRAGMA foreign_keys = ON;

CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY NOT NULL CHECK (employee_id GLOB 'E[0-9][0-9][0-9]'),
    name TEXT CHECK (name IS NULL OR length(trim(name)) > 0),
    role TEXT CHECK (role IS NULL OR length(trim(role)) > 0)
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY NOT NULL CHECK (project_id GLOB 'P[0-9][0-9][0-9]'),
    project_name TEXT CHECK (project_name IS NULL OR length(trim(project_name)) > 0),
    budget NUMERIC CHECK (
        budget IS NULL OR (typeof(budget) IN ('integer', 'real') AND budget >= 0 AND budget < 1e999)
    )
);

CREATE TABLE timesheets (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
    work_date TEXT NOT NULL CHECK (
        work_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    ),
    hours NUMERIC NOT NULL CHECK (typeof(hours) IN ('integer', 'real') AND hours > 0 AND hours <= 24),
    PRIMARY KEY (employee_id, project_id, work_date)
);
-- Calendar validity and cross-row daily totals are checked in Python.
-- SQLite NUMERIC is affinity, not fixed-precision decimal storage; choose a
-- fixed-precision NUMERIC database if monetary calculations are added later.
