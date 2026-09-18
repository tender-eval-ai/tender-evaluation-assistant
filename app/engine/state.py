_NA_TOKENS = {"n/a", "na"}


def classify_presence(item: dict, field_id: str) -> str:
    # Shared across every checker that uses the engine - generalized from
    # particulars_of_goods_schedule_checker.py's own _status(), which every rules
    # file's blank/filled/redacted/not_applicable tier vocabulary was modelled on.
    # `redacted` is visual (a black bar) and can't be inferred from the value
    # alone, so the extraction step reports it directly and it wins regardless of
    # what (if anything) the value itself holds.
    if item.get(f"{field_id}_redacted", False):
        return "redacted"

    value = item.get(field_id)
    if value is None:
        return "blank"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "blank"
        if stripped.lower() in _NA_TOKENS:
            return "not_applicable"
    return "filled"
