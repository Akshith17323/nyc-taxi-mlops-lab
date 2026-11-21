"""S1: the schema_contract check on trip_files.

Compare the landed file's Parquet footer with contracts/trips.schema.yaml before
raw_trips copies anything. contracts/platform.yaml says this check is blocking.
"""

import dagster as dg

from ..contracts import trips_schema
from ..partitions import trip_months
from ..resources import DataBucket
from .trip_files import trip_files


@dg.asset_check(
    asset=trip_files,
    partitions_def=trip_months,
    blocking=True,
    description="Parquet schema matches contracts/trips.schema.yaml in column names and types.",
)
def schema_contract(
    context: dg.AssetCheckExecutionContext, data_bucket: DataBucket
) -> dg.AssetCheckResult:
    month = context.partition_key
    footer = data_bucket.footer(month)
    expected = trips_schema()

    if len(footer.columns) != len(expected):
        return dg.AssetCheckResult(
            passed=False,
            severity=dg.AssetCheckSeverity.ERROR,
            description=f"Column count mismatch: expected {len(expected)}, got {len(footer.columns)}",
            metadata={
                "expected_columns": dg.MetadataValue.int(len(expected)),
                "actual_columns": dg.MetadataValue.int(len(footer.columns)),
            },
        )

    mismatches = []
    for i, (act, exp) in enumerate(zip(footer.columns, expected, strict=True)):
        if act.name.lower() != exp.name.lower() or act.type != exp.type:
            mismatches.append(f"col {i}: expected {exp.name}:{exp.type}, got {act.name}:{act.type}")

    if mismatches:
        return dg.AssetCheckResult(
            passed=False,
            severity=dg.AssetCheckSeverity.ERROR,
            description=f"Schema mismatches: {'; '.join(mismatches[:3])}",
            metadata={"mismatches": dg.MetadataValue.json(mismatches)},
        )

    return dg.AssetCheckResult(
        passed=True,
        severity=dg.AssetCheckSeverity.ERROR,
        description="Parquet footer matches contracts/trips.schema.yaml",
        metadata={
            "num_columns": dg.MetadataValue.int(len(footer.columns)),
            "num_rows": dg.MetadataValue.int(footer.num_rows),
        },
    )
