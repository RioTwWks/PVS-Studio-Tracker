"""Parser for PVS-Studio warning classifier CSV data."""

import csv
from typing import Any


def parse_classifier_csv(csv_path: str) -> list[dict[str, Any]]:
    """Parse the Actual_warnings.csv file and return a list of classifier entries.

    Expected CSV format:
    key;type;priority;Name
    V1001;BUG;MAJOR;Variable is assigned but not used...
    """
    classifiers: list[dict[str, Any]] = []

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            key = row.get("key", "").strip()
            if not key:
                continue

            classifiers.append(
                {
                    "rule_code": key,
                    "type": row.get("type", "").strip(),
                    "priority": row.get("priority", "").strip(),
                    "name": row.get("Name", "").strip(),
                }
            )

    return classifiers
