"""Stage I / Stage II evaluation matrices and English conclusions.

Logic is deterministic: the LLM's per-bid findings (with citations) are inputs; pass/
fail aggregation and the narrative text are code, phrased after the client's Summary
List sample so the output reads like a TAP report.
"""
from __future__ import annotations

from .pricing import compute_price_rows
from .schemas import (BidExtraction, ComplianceFinding, DocumentPresence,
                      EvaluationResult, Rubric, Stage1Result, Stage2Result)


def run_stage1(rubric: Rubric, bids: list[BidExtraction]) -> list[Stage1Result]:
    results = []
    for bid in bids:
        found = {d.checklist_id: d for d in bid.documents}
        presence: dict[str, DocumentPresence] = {}
        missing: list[str] = []
        for item in rubric.stage1_checklist:
            finding = found.get(item.id, DocumentPresence(
                checklist_id=item.id, present=False, note="not addressed in extraction"))
            presence[item.id] = finding
            if item.required and not finding.present:
                missing.append(item.id)
        results.append(Stage1Result(
            tenderer=bid.tenderer, presence=presence, missing=missing, passed=not missing))
    return results


def run_stage2(rubric: Rubric, bids: list[BidExtraction],
               stage1: list[Stage1Result]) -> list[Stage2Result]:
    passed_s1 = {r.tenderer for r in stage1 if r.passed}
    results = []
    for bid in bids:
        if bid.tenderer not in passed_s1:
            continue
        found = {c.requirement_id: c for c in bid.compliance}
        findings: dict[str, ComplianceFinding] = {}
        non_compliant: list[str] = []
        unclear: list[str] = []
        for req in rubric.stage2_requirements:
            finding = found.get(req.id, ComplianceFinding(
                requirement_id=req.id, complies="unclear", evidence="not addressed in extraction"))
            findings[req.id] = finding
            if finding.complies == "no":
                non_compliant.append(req.id)
            elif finding.complies == "unclear":
                unclear.append(req.id)
        # "unclear" does not disqualify — it goes on the clarification list, as a TAP would.
        results.append(Stage2Result(
            tenderer=bid.tenderer, findings=findings, non_compliant=non_compliant,
            unclear=unclear, passed=not non_compliant))
    return results


def _names(items: list[str]) -> str:
    return ", ".join(items) if items else ""


def stage1_conclusion(rubric: Rubric, stage1: list[Stage1Result]) -> str:
    total = len(stage1)
    failed = [r for r in stage1 if not r.passed]
    text = (
        "The offers received were checked for their completeness and compliance with the "
        "procedural requirements (including the duly signed tender form and the essential "
        "information in the schedules) as detailed in the tender documents. "
    )
    if not failed:
        text += (f"The TAP found that all {total} offers passed the completeness check under "
                 "Stage I assessment and proceeded to Stage II assessment.")
    else:
        items = {i.id: i.item for i in rubric.stage1_checklist}
        details = "; ".join(
            f"{r.tenderer} (missing: {', '.join(items.get(m, m) for m in r.missing)})" for r in failed)
        text += (f"The TAP found that {total - len(failed)} of the {total} offers passed the "
                 f"completeness check under Stage I assessment and proceeded to Stage II "
                 f"assessment. The following offer(s) failed the completeness check and were "
                 f"not considered further: {details}.")
    return text


def stage2_conclusion(rubric: Rubric, stage2: list[Stage2Result]) -> str:
    total = len(stage2)
    failed = [r for r in stage2 if not r.passed]
    unclear = [r for r in stage2 if r.unclear]
    text = (
        "All offers passing Stage I assessment were checked for their compliance with the "
        "essential requirements (including the requirements on delivery and warranty, and "
        "the mandatory features of the technical specifications) as detailed in the tender "
        "documents. "
    )
    if not failed:
        text += (f"The TAP found that all {total} offers complied fully with the essential "
                 "requirements.")
    else:
        reqs = {r.id: r.requirement for r in rubric.stage2_requirements}
        details = "; ".join(
            f"{r.tenderer} (non-compliant: {', '.join(reqs.get(n, n) for n in r.non_compliant)})"
            for r in failed)
        text += (f"The TAP found that {total - len(failed)} of the {total} offers complied "
                 f"fully with the essential requirements. The following offer(s) did not "
                 f"comply and were not considered further: {details}.")
    if unclear:
        text += (" Clarification is recommended for: "
                 + "; ".join(f"{r.tenderer} ({_names(r.unclear)})" for r in unclear) + ".")
    return text


def evaluate(rubric: Rubric, bids: list[BidExtraction]) -> EvaluationResult:
    s1 = run_stage1(rubric, bids)
    s2 = run_stage2(rubric, bids, s1)
    passed_both = {r.tenderer for r in s2 if r.passed}
    price_rows, recommended = compute_price_rows(rubric.price_scheme, bids, passed_both)
    return EvaluationResult(
        rubric=rubric, stage1=s1, stage2=s2, price_rows=price_rows,
        recommended=recommended,
        stage1_conclusion=stage1_conclusion(rubric, s1),
        stage2_conclusion=stage2_conclusion(rubric, s2),
    )
