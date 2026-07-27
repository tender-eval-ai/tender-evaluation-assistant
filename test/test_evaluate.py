"""Stage I / Stage II aggregation and the English conclusions."""
from app.evaluate import evaluate, run_stage1, run_stage2


def test_stage1_flags_missing_required_documents(synthetic_case):
    rubric, bids = synthetic_case
    results = {r.tenderer: r for r in run_stage1(rubric, bids)}
    assert results["Bidder A"].passed and results["Bidder B"].passed
    assert not results["Bidder C"].passed
    assert results["Bidder C"].missing == ["S1-04"]


def test_stage2_only_runs_for_stage1_passers(synthetic_case):
    rubric, bids = synthetic_case
    s1 = run_stage1(rubric, bids)
    s2 = {r.tenderer: r for r in run_stage2(rubric, bids, s1)}
    assert "Bidder C" not in s2  # failed Stage I
    assert s2["Bidder A"].passed and s2["Bidder B"].passed
    assert not s2["Bidder D"].passed
    assert s2["Bidder D"].non_compliant == ["S2-02"]
    assert s2["Bidder D"].unclear == ["S2-03"]  # unclear -> clarification, not disqualification


def test_full_evaluation_recommends_best_conforming_offer(synthetic_case):
    rubric, bids = synthetic_case
    result = evaluate(rubric, bids)
    # C ranks 1 on cost-effectiveness but failed Stage I; B is the best conforming offer.
    assert result.recommended == "Bidder B"
    rows = {r.tenderer: r for r in result.price_rows}
    assert rows["Bidder C"].ranking == 1 and not rows["Bidder C"].conforming
    assert rows["Bidder B"].ranking == 2 and rows["Bidder B"].conforming
    assert rows["Bidder D"].remark.startswith("cannot be calculated")


def test_conclusions_read_like_a_tap_report(synthetic_case):
    rubric, bids = synthetic_case
    result = evaluate(rubric, bids)
    assert "completeness" in result.stage1_conclusion
    assert "Bidder C" in result.stage1_conclusion            # named with its missing item
    assert "Non-collusive" in result.stage1_conclusion
    assert "essential requirements" in result.stage2_conclusion
    assert "Bidder D" in result.stage2_conclusion            # named as non-compliant
    assert "Clarification is recommended" in result.stage2_conclusion
