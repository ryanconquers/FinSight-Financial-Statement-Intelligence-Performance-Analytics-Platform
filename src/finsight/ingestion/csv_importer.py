"""CSV parsing and validation entry point for source-backed observations."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError, ParserError

from finsight.validation.observations import validate_observations
from finsight.validation.report import Finding, ValidationReport


def read_observations(path: str | Path) -> tuple[list[dict[str, object]], ValidationReport]:
    """Parse and validate a contract CSV; malformed files return an actionable report."""
    input_path = Path(path)
    report = ValidationReport(input_filename=str(input_path))
    try:
        frame = pd.read_csv(
            input_path,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
            on_bad_lines="error",
        )
    except EmptyDataError:
        report.add(Finding("error", "empty_file", "CSV has no header row or data."))
        report.import_status = "validation_failed"
        return [], report
    except (ParserError, UnicodeDecodeError) as exc:
        report.add(Finding("error", "malformed_csv", f"Could not parse CSV safely: {exc}"))
        report.import_status = "validation_failed"
        return [], report
    except OSError as exc:
        report.add(Finding("error", "input_unavailable", f"Could not read input file: {exc}"))
        report.import_status = "validation_failed"
        return [], report

    if len(frame.columns) == 0:
        report.add(Finding("error", "empty_file", "CSV has no columns."))
        report.import_status = "validation_failed"
        return [], report
    return validate_observations(frame, str(input_path))
