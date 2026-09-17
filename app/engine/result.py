from dataclasses import dataclass, field

from app.engine.field_result import FieldResult, overall_status, status_counts


@dataclass
class ItemCheckResult:
    # item_no is deliberately untyped beyond "identifier" - most schedules are
    # itemized (Price Schedule row 1, 2, ...) but some are per-tender, not
    # per-item (Compliance Schedule, Appendix contact details) and pass a fixed
    # label instead of an int. Uniform shape either way for downstream consumers.
    item_no: object
    overall_status: str
    status_counts: dict[str, int]
    fields: list[FieldResult]
    auto_adjustments: list[dict] = field(default_factory=list)


def assemble(item_no, fields: list[FieldResult], auto_adjustments: list[dict]) -> ItemCheckResult:
    return ItemCheckResult(
        item_no=item_no,
        overall_status=overall_status(fields),
        status_counts=status_counts(fields),
        fields=fields,
        auto_adjustments=auto_adjustments,
    )
