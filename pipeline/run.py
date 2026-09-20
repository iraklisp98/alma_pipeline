"""Run from the repository root with: python -m pipeline.run."""
from pathlib import Path

import pandas as pd

from .prepare import prepare
from .validate import validate, verify_outputs
from .transform import transform


def run(input_dir=None, output_dir=None):
    root = Path(__file__).resolve().parent.parent
    input_dir = Path(input_dir) if input_dir is not None else root
    output_dir = Path(output_dir) if output_dir is not None else root / "outputs"
    raw, prepared = prepare(input_dir)
    validated, issues = validate(raw, prepared)
    outputs = transform(validated)
    verify_outputs(raw, validated, outputs)
    outputs["validation_issues"] = issues
    for status in ["review", "rejected"]:
        records = []
        for table, frame in validated.items():
            selected = raw[table].loc[frame["status"].eq(status)].copy()
            selected.insert(0, "source_table", table)
            selected["status"] = status
            selected["include_in_clean"] = frame.loc[selected.index, "include_in_clean"]
            records.append(selected)
        outputs[f"{status}_records"] = pd.concat(records, ignore_index=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        frame.to_csv(output_dir / f"{name}.csv", index=False, date_format="%Y-%m-%d", lineterminator="\n")
    summary = pd.DataFrame([
        {"table": table, "input": len(frame),
         **{status: int(frame["status"].eq(status).sum()) for status in ["accepted", "review", "rejected"]},
         "clean": int(frame["include_in_clean"].sum())}
        for table, frame in validated.items()
    ])
    print(summary.to_string(index=False))
    print(f"Accepted hours: {outputs['timesheets_clean']['hours'].sum():g}")
    print(f"Outputs: {output_dir}")
    return outputs, summary


if __name__ == "__main__":
    run()
