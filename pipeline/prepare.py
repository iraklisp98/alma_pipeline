"""Read untouched source values and prepare typed working copies."""
from pathlib import Path
import csv

import pandas as pd

COLUMNS = {
    "employees": ["employee_id", "name", "role"],
    "projects": ["project_id", "project_name", "budget"],
    "timesheets": ["employee_id", "project_id", "date", "hours"],
}


def parse_dates(values):
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for pattern, fmt in [(r"\d{2}/\d{2}/\d{4}", "%d/%m/%Y"),
                         (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d")]:
        mask = values.str.fullmatch(pattern, na=False)
        result.loc[mask] = pd.to_datetime(values.loc[mask], format=fmt, errors="coerce")
    months = dict(zip("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
                      [f"{n:02}" for n in range(1, 13)]))
    parts = values.str.extract(r"^(\d{2})-([A-Z][a-z]{2})-(\d{2})$")
    mask = parts[1].isin(months)
    iso = "20" + parts.loc[mask, 2] + "-" + parts.loc[mask, 1].map(months) + "-" + parts.loc[mask, 0]
    result.loc[mask] = pd.to_datetime(iso, format="%Y-%m-%d", errors="coerce")
    return result


def prepare(input_dir):
    raw, prepared = {}, {}
    for table, columns in COLUMNS.items():
        path = Path(input_dir) / f"{table}.csv"
        # pandas can interpret extra fields as an index; reject malformed rows explicitly.
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle, strict=True)
            if next(reader, None) != columns:
                raise ValueError(f"{table}: expected header {columns}")
            for row in reader:
                if row and len(row) != len(columns):
                    raise ValueError(f"{table}: wrong field count near line {reader.line_num}")
        source = pd.read_csv(path, dtype="string",
                             keep_default_na=False, skip_blank_lines=True)
        if source.columns.tolist() != columns:
            raise ValueError(f"{table}: expected columns {columns}, got {source.columns.tolist()}")
        source.insert(0, "source_record", range(1, len(source) + 1))
        raw[table] = source
        frame = source.copy(deep=True)
        for column in columns:
            frame[column] = frame[column].str.strip().replace("", pd.NA)
        prepared[table] = frame
    prepared["projects"]["budget_numeric"] = pd.to_numeric(prepared["projects"]["budget"], errors="coerce")
    prepared["timesheets"]["hours_numeric"] = pd.to_numeric(prepared["timesheets"]["hours"], errors="coerce")
    prepared["timesheets"]["work_date"] = parse_dates(prepared["timesheets"]["date"])
    return raw, prepared
