"""The Word deliverables (S4-4), modelled on the client's samples and rendered from the
S4 shapes: the Price Summary, the Summary List (Stage I and II conclusions and the
recommendation) and the Evaluation Record (every item of every tenderer). Each states the
rule-set version and who confirmed it, the models, who confirmed each review and when it
was generated, and marks every reviewer's correction and every edited rule. The table
helpers are the legacy renderer's (`app.report`), unchanged."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

from docx import Document as Docx

from app.checks.corrections import item_verdicts
from app.checks.pricing import Offer
from app.rulesets.schema import RuleSet


# ---------------------------------------------------------------- cells (from the prototype's app/report.py)
def _money(v: float | None) -> str:
    return f"{v:,.2f}" if v is not None else "—"


def _num(v: float | None) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".") if v is not None else "—"


def _unit_price(v: float | None) -> str:
    """At least 2 decimals, up to 4 when quoted more precisely (e.g. 1.278)."""
    if v is None:
        return "—"
    s = f"{v:,.4f}".rstrip("0")
    if len(s.partition(".")[2]) < 2:
        return f"{v:,.2f}"
    return s


def _set_cell(cell, value: str, bold: bool) -> None:
    cell.text = value
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = bold


def _header_row(table, labels: list[str]) -> None:
    for cell, label in zip(table.rows[0].cells, labels):
        _set_cell(cell, label, bold=True)


def _fill_row(table, values: list[str], bold: bool = False) -> None:
    row = table.add_row()
    for cell, value in zip(row.cells, values):
        _set_cell(cell, value, bold)

NAMES = ("price_summary.docx", "summary_list.docx", "evaluation_record.docx")


@dataclass
class Bundle:
    """Everything a report states."""

    project: str
    ruleset: RuleSet
    offers: list[Offer]
    evaluation: dict                       # app.checks.pricing.evaluation()
    models: dict = field(default_factory=dict)     # {"text": ..., "vision": ...}
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def summary(self) -> dict:
        return self.evaluation["price"]

    @property
    def approvers(self) -> list[str]:
        return sorted({o.reviewed_by for o in self.offers if o.reviewed_by})


def _stamp(when: datetime | None) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if when else "-"


def _header(doc: Docx, b: Bundle, heading: str) -> None:
    rs = b.ruleset
    doc.add_paragraph(f"Tender: {b.project}")
    doc.add_paragraph(f"Rule set version {rs.version}, confirmed by {rs.confirmed_by or '-'} on {_stamp(rs.confirmed_at)}"
                      + (f"; drafted by {rs.model}" if rs.model else ""))
    if b.models:
        doc.add_paragraph("Models: " + ", ".join(f"{k} {v}" for k, v in b.models.items() if v))
    doc.add_paragraph("Reviews confirmed by: " + (", ".join(b.approvers) if b.approvers else "none yet"))
    doc.add_paragraph(f"Generated {_stamp(b.generated_at)}")
    doc.add_heading(heading, level=1)


def _corrections(doc: Docx, b: Bundle, only_price: bool = False) -> None:
    lines = []
    for o in b.offers:
        for key, c in sorted(o.corrections.items()):
            if only_price and not key.startswith("price_schedule."):
                continue
            lines.append(f"{o.tenderer}: {key} corrected by {c.get('by', '-')} to {c.get('value')!r} "
                         f"(the model read {c.get('model_value')!r}): {c.get('reason', '')}")
    if lines:
        doc.add_paragraph("Corrections by the reviewers:").runs[0].bold = True
        for line in lines:
            doc.add_paragraph(line, style="List Bullet")


def _edited_rules(doc: Docx, b: Bundle) -> None:
    edited = [i for i in b.ruleset.items if i.edit is not None or i.status == "edited"]
    if not edited:
        return
    doc.add_paragraph("Rule-set items edited by a person:").runs[0].bold = True
    for i in edited:
        who = f"{i.edit.by}: {i.edit.reason}" if i.edit is not None else "edited"
        doc.add_paragraph(f"item ({i.letter}) {i.title}: {who}", style="List Bullet")


def _save(doc: Docx) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- price summary
def price_summary_docx(b: Bundle) -> bytes:
    doc = Docx()
    scheme, rows, recommended = b.summary["scheme"], b.summary["rows"], b.summary["recommended"]
    ce = scheme["type"] == "cost_effectiveness"
    _header(doc, b, "Summary of Cost-effectiveness" if ce else "Price Summary")
    quantity = scheme["quantity"]
    qty = f"{quantity:,.0f} {scheme['unit']}" if quantity is not None else "the estimated quantity"
    cur = scheme.get("currency") or ""
    in_cur = f" ({cur})" if cur else ""
    if ce:
        table = doc.add_table(rows=1, cols=6, style="Table Grid")
        _header_row(table, ["Name of Tenderer", f"Estimated Goods Price{in_cur}\n(M) x {qty}", "Optimal Dosage (\"D\")",
                            f"One-time Unit Price (\"M\")\n({cur + '/' if cur else 'per '}{scheme['unit']})", "Cost-effectiveness of Tender\n(D) x (M)",
                            "Ranking of Tender\n(in terms of cost-effectiveness)"])
        for r in rows:
            _fill_row(table, [r["tenderer"], _money(r["estimated_goods_price"]),
                              _num(r["dosage_rounded"] if r["dosage_rounded"] is not None else r["dosage"]), _money(r["unit_price_base"]),
                              _money(r["cost_effectiveness"]) if r["cost_effectiveness"] is not None else "cannot be calculated",
                              str(r["ranking"]) if r["ranking"] is not None else "not applicable"], bold=r["tenderer"] == recommended)
    else:
        table = doc.add_table(rows=1, cols=3, style="Table Grid")
        _header_row(table, ["Name of Tenderers", f"Unit Price per {scheme['unit']}{in_cur}", f"Estimated Goods Price{in_cur}"])
        for r in rows:
            price = _money(r["estimated_goods_price"]) + (f"  [{r['ranking']}]" if r["ranking"] is not None else "")
            _fill_row(table, [r["tenderer"], _unit_price(r["unit_price_base"]), price], bold=r["tenderer"] == recommended)
    doc.add_paragraph()
    doc.add_paragraph("Notes:").runs[0].bold = True
    notes = ["The recommended offer is in bold type.",
             f"The estimated goods price means the one-time unit price multiplied by the estimated quantity specified in the Price Schedule (i.e. {qty}).",
             "A lower figure for the cost-effectiveness of a tender denotes a more cost-effective offer." if ce
             else "The figures in the brackets [ ] denote the ranking of tenders in terms of price, with ranking number 1 being the lowest priced offer."]
    for r in rows:
        if r.get("remark"):
            notes.append(f"{r['tenderer']}: {r['remark']}.")
    for i, note in enumerate(notes, 1):
        doc.add_paragraph(f"({i}) {note}")
    _corrections(doc, b, only_price=True)
    return _save(doc)


# ---------------------------------------------------------------- summary list
def summary_list_docx(b: Bundle) -> bytes:
    doc = Docx()
    _header(doc, b, "Summary of Tender Evaluation")
    doc.add_heading("Stage I - Completeness Check", level=2)
    doc.add_paragraph(b.evaluation["stage1_conclusion"])
    doc.add_heading("Stage II - Assessment of Compliance with Essential Requirements", level=2)
    doc.add_paragraph(b.evaluation["stage2_conclusion"])
    doc.add_heading("Recommendation", level=2)
    recommended = b.evaluation["recommended"]
    if recommended:
        row = next(r for r in b.summary["rows"] if r["tenderer"] == recommended)
        cur = b.summary["scheme"].get("currency") or ""
        amount = (_money(row["cost_effectiveness"]) if row["cost_effectiveness"] is not None else _money(row["estimated_goods_price"]))
        amount = f"{cur}{amount}" if cur.endswith("$") or cur in ("€", "£") else f"{cur} {amount}".strip()
        metric = (f"a cost-effectiveness of {amount}" if row["cost_effectiveness"] is not None
                  else f"a total estimated amount of {amount}")
        doc.add_paragraph(f"Based on the above evaluation results, the TAP found that {recommended}'s offer complied with all the "
                          f"procedural and essential requirements as checked, and recommended acceptance of {recommended}'s offer with {metric}.")
    else:
        doc.add_paragraph(b.evaluation["recommendation"])
    _corrections(doc, b)
    _edited_rules(doc, b)
    return _save(doc)


# ---------------------------------------------------------------- evaluation record
def evaluation_record_docx(b: Bundle) -> bytes:
    doc = Docx()
    _header(doc, b, "Detailed Evaluation Record")
    titles = {i.letter: i for i in b.ruleset.items}
    for o in b.offers:
        doc.add_heading(f"{o.tenderer}: Stage I {o.stage('stage1') or '-'}, Stage II {o.stage('stage2') or '-'}"
                        + (f", review confirmed by {o.reviewed_by}" if o.reviewed_by else ", review not confirmed"), level=2)
        table = doc.add_table(rows=1, cols=5, style="Table Grid")
        _header_row(table, ["Item", "Part", "Outcome", "Reasons", "Corrections"])
        for letter, v in item_verdicts(o.verdict).items():
            item = titles.get(letter)
            corrected = [k for k in o.corrections if any(f["field_id"] == k or f["field_id"] + "_page" == k for f in v.get("fields", []))]
            _fill_row(table, [f"({letter}) {item.title if item else ''}", v.get("part", "-"), v.get("outcome", "-"),
                              "; ".join(v.get("reasons", [])) or "-",
                              "; ".join(f"{k.rsplit('.', 1)[-1]} by {o.corrections[k].get('by', '-')}" for k in corrected) or "-"])
        doc.add_paragraph()
    _corrections(doc, b)
    _edited_rules(doc, b)
    return _save(doc)


RENDERERS = {"price_summary.docx": price_summary_docx, "summary_list.docx": summary_list_docx,
             "evaluation_record.docx": evaluation_record_docx}


def render(name: str, b: Bundle) -> bytes:
    return RENDERERS[name](b)


def text_of(data: bytes) -> str:
    """Every paragraph and table cell of a document, one per line: what the golden files hold."""
    doc = Docx(io.BytesIO(data))
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.replace("\n", " ") for cell in row.cells))
    return "\n".join(line for line in lines if line.strip())
