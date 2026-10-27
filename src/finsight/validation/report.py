"""Structured, reproducible validation and import reports."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warning", "manual_review", "info"]


@dataclass(frozen=True)
class Finding:
    """One validation outcome, optionally associated with a CSV row and field."""

    severity: Severity
    code: str
    message: str
    row_number: int | None = None
    field: str | None = None


@dataclass
class ValidationReport:
    """Machine-readable summary for one input file and its import attempt."""

    input_filename: str
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    import_status: str = "not_run"
    database_rows_written: int = 0
    database_summary: str = "No database writes attempted."
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    @property
    def manual_review(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "manual_review"]

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def to_dict(self) -> dict[str, object]:
        """Return stable, JSON-serializable report data."""
        return {
            "input_filename": self.input_filename,
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "import_status": self.import_status,
            "database_rows_written": self.database_rows_written,
            "database_summary": self.database_summary,
            "errors": [asdict(item) for item in self.errors],
            "warnings": [asdict(item) for item in self.warnings],
            "manual_review": [asdict(item) for item in self.manual_review],
            "findings": [asdict(item) for item in self.findings],
        }

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def write_csv(self, path: str | Path) -> None:
        """Write one row per finding; emit a summary row when there are no findings."""
        fields = [
            "input_filename", "total_rows", "valid_rows", "invalid_rows",
            "import_status", "database_rows_written", "database_summary",
            "severity", "code", "row_number", "field", "message",
        ]
        rows = self.findings or [Finding("info", "no_findings", "No validation findings.")]
        with Path(path).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for finding in rows:
                writer.writerow({
                    **{key: value for key, value in self.to_dict().items() if key not in {"errors", "warnings", "manual_review", "findings"}},
                    **asdict(finding),
                })
