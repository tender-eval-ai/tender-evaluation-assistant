from app.engine.state import classify_presence


def test_none_is_blank():
    assert classify_presence({"x": None}, "x") == "blank"


def test_missing_key_is_blank():
    assert classify_presence({}, "x") == "blank"


def test_empty_string_is_blank():
    assert classify_presence({"x": ""}, "x") == "blank"


def test_whitespace_only_string_is_blank():
    assert classify_presence({"x": "   "}, "x") == "blank"


def test_redacted_flag_wins_even_when_value_present():
    assert classify_presence({"x": "Acme Ltd", "x_redacted": True}, "x") == "redacted"


def test_redacted_flag_wins_even_when_value_blank():
    # A redacted field can't be told apart from a genuinely blank one by value
    # alone - the extraction step reports redaction directly (field_result.py's
    # own rationale for the `redacted` bool), so the flag must win regardless of
    # what (if anything) sits in the value itself.
    assert classify_presence({"x": None, "x_redacted": True}, "x") == "redacted"


def test_na_token_is_not_applicable():
    assert classify_presence({"x": "N/A"}, "x") == "not_applicable"


def test_na_token_is_case_insensitive():
    assert classify_presence({"x": "na"}, "x") == "not_applicable"


def test_na_token_tolerates_surrounding_whitespace():
    assert classify_presence({"x": " n/a "}, "x") == "not_applicable"


def test_nil_is_filled_not_not_applicable():
    # "Nil" is real, meaningful content ("no discount offered" -
    # price_schedule_parts_c_d_rules.json) - distinct from "N/A" ("doesn't apply
    # to me"). Conflating them would misclassify a valid, complete answer.
    assert classify_presence({"x": "Nil"}, "x") == "filled"


def test_zero_is_filled_not_blank():
    # A falsy-but-present numeric value (e.g. a genuine 0% discount) must not be
    # mistaken for an absent one.
    assert classify_presence({"x": 0}, "x") == "filled"


def test_ordinary_string_is_filled():
    assert classify_presence({"x": "Acme Chemicals GmbH"}, "x") == "filled"


def test_ordinary_number_is_filled():
    assert classify_presence({"x": 1102000}, "x") == "filled"


def test_missing_redacted_key_defaults_to_not_redacted():
    assert classify_presence({"x": "filled value"}, "x") == "filled"
