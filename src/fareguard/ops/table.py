"""Which DynamoDB table holds the ledger, read from the outputs of infra/main.

The name and the region come from Terraform, so no script holds the name of a
table or the id of an account.
"""

from collections.abc import Mapping
from dataclasses import dataclass

TABLE_NAME_OUTPUT = "ledger_table_name"
TABLE_ARN_OUTPUT = "ledger_table_arn"
_REGION_FIELD = 3


class LedgerTableError(Exception):
    """An output that names the ledger table is missing or does not hold what it should."""

    def __init__(self, output: str, expected: str) -> None:
        """Name the output and what it must hold, without repeating its value."""
        super().__init__(
            f"the Terraform output {output} must be {expected}; apply infra/main first"
        )


@dataclass(frozen=True)
class LedgerTable:
    """The ledger table and the region it is in."""

    name: str
    region: str


def ledger_table(outputs: Mapping[str, object]) -> LedgerTable:
    """Return the ledger table named in `outputs`, with the region taken from its ARN.

    Raises:
        LedgerTableError: if the name or the ARN is missing, or the ARN names no region.
    """
    name = outputs.get(TABLE_NAME_OUTPUT)
    if not isinstance(name, str) or not name:
        raise LedgerTableError(TABLE_NAME_OUTPUT, "the name of the ledger table")
    arn = outputs.get(TABLE_ARN_OUTPUT)
    fields = arn.split(":") if isinstance(arn, str) else []
    if len(fields) <= _REGION_FIELD or not fields[_REGION_FIELD]:
        raise LedgerTableError(TABLE_ARN_OUTPUT, "an ARN that names a region")
    return LedgerTable(name, fields[_REGION_FIELD])
