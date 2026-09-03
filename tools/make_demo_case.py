"""Generate a fully synthetic tender case (safe to send to cloud APIs).

Default (--bidders 3) — Supply of Industrial Degreaser, unit-price x quantity scheme:
  Tenderer A: complete, compliant, HK$12.50/L
  Tenderer B: complete, compliant, HK$11.80/L but quoted total has an arithmetic error
  Tenderer C: cheapest, but missing the Non-collusive Tendering Certificate (fails
              Stage I) — and its offer is an image-only "scanned" PDF, so the pipeline
              must OCR it through the vision model chain
Expected outcome: C ranked 1 yet non-conforming; B recommended with an error note.

--bidders N (N != 3) generates N deterministic varied bidders for scale testing:
prices spread over ~HK$10-15, every 7th missing the certificate (Stage I fail),
every 11th with a 6-month shelf life (Stage II fail), every 9th with an arithmetic
error in its quoted total, and bidders 2 and 17 as scanned image-only PDFs (OCR path).

--buried generates the evidence-search benchmark: every offer is a 12-page scan-only
PDF whose Price Schedule, Particulars, Non-collusive Certificate and Compliance
Schedule sit on pages 9-12, behind a table of contents on page 1 (with a generic
"Certificates and Declarations" entry, so presence cannot be inferred from the TOC)
and six pages of company-profile filler — with a small MAX_OCR_PAGES the first pass
cannot see them and only an agent that follows the contents page can. Bidder 3
genuinely omits the certificate (a false restore would be caught). Ground truth goes
to ground_truth.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.pdfgen import LINES_PER_PAGE, make_text_pdf  # noqa: E402

TERMS = """\
Tender Ref.: DEMO0022026
Supply of Industrial Degreaser to the Demo Services Department

Terms of Tender - Supplement

5. Tender Submission
A Tenderer must submit the following with its offer:
a. the duly signed Tender Form, Offer to be Bound;
b. the completed Price Schedule Part A;
c. the completed Particulars of Goods Schedule;
d. the completed Non-collusive Tendering Certificate.
Failure to submit any of the above will render the offer incomplete and the
offer will not be considered further under the Stage I completeness check.

19. Tender Evaluation
Partial tender is not permitted. A Tenderer must bid for all 50 000 litres of
industrial degreaser as specified in the Price Schedule.
The tender price will be assessed on the estimated goods price, being the
unit price per litre quoted in the Price Schedule multiplied by the estimated
quantity of 50 000 litres. The lowest estimated goods price will be ranked
number 1. Prices shall be quoted in Hong Kong dollars, free into store.
"""

SPECIAL_CONDITIONS = """\
Tender Ref.: DEMO0022026
Special Conditions of Contract

3. Delivery
It is an essential requirement that the Goods shall be delivered within
45 days from the date of the purchase order.

14. Packing and Labelling
It is an essential requirement that the Goods shall be supplied in sealed
drums of 200 litres, each labelled with the batch number and expiry date.

15. Shelf Life
It is an essential requirement that the Goods shall have a shelf life of at
least 12 months from the date of receipt by the Authority.
"""

OFFER_A = """\
Offer of Tenderer A - Tender Ref. DEMO0022026

Tender Form, Offer to be Bound: duly signed by the authorised signatory of
Tenderer A on 15 June 2026.

Price Schedule Part A: unit price HK$ 12.50 per litre. Estimated quantity
50 000 litres. Estimated goods price HK$ 625,000.00 free into store.

Particulars of Goods Schedule: product DegreaseMax 100. Shelf life 18 months
from the date of receipt. Supplied in sealed drums of 200 litres labelled
with batch number and expiry date.

Non-collusive Tendering Certificate: completed and signed.

Compliance Schedule: delivery within 30 days from the date of the purchase
order is confirmed.
"""

OFFER_B = """\
Offer of Tenderer B - Tender Ref. DEMO0022026

Tender Form, Offer to be Bound: duly signed by the managing director of
Tenderer B on 18 June 2026.

Price Schedule Part A: unit price HK$ 11.80 per litre. Estimated quantity
50 000 litres. Estimated goods price HK$ 590,500.00 free into store.

Particulars of Goods Schedule: product ClearSolv Industrial. Shelf life
24 months from the date of receipt. Supplied in sealed drums of 200 litres
labelled with batch number and expiry date.

Non-collusive Tendering Certificate: completed and signed.

Compliance Schedule: delivery within 40 days from the date of the purchase
order is confirmed.
"""

OFFER_C = """\
Offer of Tenderer C - Tender Ref. DEMO0022026

Tender Form, Offer to be Bound: duly signed by the director of Tenderer C
on 20 June 2026.

Price Schedule Part A: unit price HK$ 10.00 per litre. Estimated quantity
50 000 litres. Estimated goods price HK$ 500,000.00 free into store.

Particulars of Goods Schedule: product EconoClean 55. Shelf life 14 months
from the date of receipt. Supplied in sealed drums of 200 litres labelled
with batch number and expiry date.

Compliance Schedule: delivery within 35 days from the date of the purchase
order is confirmed.
"""


OFFER_TEMPLATE = """\
Offer of {name} - Tender Ref. DEMO0022026

Tender Form, Offer to be Bound: duly signed by the authorised signatory of
{name} on {day} June 2026.

Price Schedule Part A: unit price HK$ {unit:.2f} per litre. Estimated quantity
50 000 litres. Estimated goods price HK$ {total:,.2f} free into store.

Particulars of Goods Schedule: product {product}. Shelf life {shelf} months
from the date of receipt. Supplied in sealed drums of 200 litres labelled
with batch number and expiry date.
{cert}
Compliance Schedule: delivery within {delivery} days from the date of the
purchase order is confirmed.
"""

CERT_LINE = "\nNon-collusive Tendering Certificate: completed and signed.\n"


def synth_offer(i: int) -> tuple[str, str, bool]:
    """Deterministic varied offer for bidder i. Returns (name, text, scanned)."""
    name = f"Tenderer_{i:02d}"
    unit = 10.0 + ((i * 37) % 500) / 100          # HK$10.00 - 14.99, spread
    total = unit * 50_000
    if i % 9 == 4:
        total += 500.0                             # arithmetic error to be flagged
    missing_cert = i % 7 == 3                      # Stage I failure
    shelf = 6 if i % 11 == 5 else 12 + (i % 3) * 6  # 6 fails; 12/18/24 comply
    text = OFFER_TEMPLATE.format(
        name=name, day=10 + (i % 18), unit=unit, total=total,
        product=f"CleanSolv {100 + i}", shelf=shelf,
        cert="" if missing_cert else CERT_LINE, delivery=25 + (i % 15))
    return name, text, i in (2, 17)


def _pad_pages(pages: list[str]) -> list[str]:
    """Lay each text out on its own PDF page (pdfgen paginates by line count)."""
    lines: list[str] = []
    for text in pages:
        chunk = text.splitlines()[:LINES_PER_PAGE]
        lines.extend(chunk + [""] * (LINES_PER_PAGE - len(chunk)))
    return lines


PROFILE_TOPICS = ["history and ownership", "quality management system", "warehouse and "
                  "logistics capacity", "environmental and safety policy", "key personnel",
                  "reference contracts"]


def buried_offer(i: int) -> tuple[str, list[str], dict]:
    """12-page offer with the substantive schedules buried on pages 9-12."""
    name = f"Tenderer_{i:02d}"
    unit = 10.0 + ((i * 37) % 500) / 100
    total = unit * 50_000
    missing_cert = i == 3
    shelf = 12 + (i % 3) * 6
    delivery = 25 + (i % 15)
    contents = [
        "2   Tender Form, Offer to be Bound",
        "3-8 Company Profile",
        "9   Price Schedule Part A",
        "10  Particulars of Goods Schedule",
        "11  Certificates and Declarations",   # generic on purpose: presence needs the page
        "12  Compliance Schedule",
    ]
    pages = [
        f"Offer of {name} - Tender Ref. DEMO0022026\n\nTable of Contents\n" + "\n".join(contents),
        f"Tender Form, Offer to be Bound\n\nDuly signed by the authorised signatory of {name} "
        f"on {10 + (i % 18)} June 2026. {name} offers to be bound by the Terms of Tender.",
    ]
    for k, topic in enumerate(PROFILE_TOPICS, start=1):
        pages.append(f"Company Profile - Section {k}: {topic}\n\n" + "\n".join(
            f"{name} paragraph {k}.{j} about its {topic}, provided for information only."
            for j in range(1, 9)))
    pages.append(f"Price Schedule Part A\n\nUnit price HK$ {unit:.2f} per litre. Estimated "
                 f"quantity 50 000 litres.\nEstimated goods price HK$ {total:,.2f} free into store.")
    pages.append(f"Particulars of Goods Schedule\n\nProduct CleanSolv {100 + i}. Shelf life "
                 f"{shelf} months from the date of receipt.\nSupplied in sealed drums of 200 "
                 "litres labelled with batch number and expiry date.")
    pages.append("Quality Assurance Statement\n\nThe tenderer maintains an ISO 9001 certified "
                 "quality system." if missing_cert else
                 "Non-collusive Tendering Certificate\n\nCompleted and signed by the "
                 f"authorised signatory of {name}.")
    pages.append(f"Compliance Schedule\n\nDelivery within {delivery} days from the date of "
                 "the purchase order is confirmed.")
    truth = {"certificate": not missing_cert, "unit_price": round(unit, 2),
             "quoted_total": round(total, 2), "shelf_life_months": shelf,
             "delivery_days": delivery, "pages": len(pages)}
    return name, _pad_pages(pages), truth


def rasterize(pdf_path: Path) -> None:
    """Replace a text-layer PDF with an image-only version (simulates a scanned offer)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        images = [page.render(scale=2.0).to_pil().convert("RGB") for page in doc]
    finally:
        doc.close()
    images[0].save(pdf_path, "PDF", resolution=144, save_all=True, append_images=images[1:])


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bidders", type=int, default=3,
                        help="number of bidders (3 = the fixed A/B/C demo trio)")
    parser.add_argument("--out", default="demo_case", help="output folder name")
    parser.add_argument("--buried", action="store_true",
                        help="evidence-search benchmark: 12-page scan-only offers with the "
                             "schedules on pages 9-12 (see module docstring)")
    args = parser.parse_args()

    base = ROOT / args.out
    tender = base / "tender"
    tender.mkdir(parents=True, exist_ok=True)
    make_text_pdf(tender / "01_terms_of_tender_supplement.pdf", TERMS)
    make_text_pdf(tender / "02_special_conditions.pdf", SPECIAL_CONDITIONS)

    import json
    truth: dict[str, dict] = {}
    if args.buried:
        offers = []
        for i in range(1, args.bidders + 1):
            name, lines, t = buried_offer(i)
            offers.append((name, lines, True))
            truth[name] = t
        (base / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    elif args.bidders == 3:
        offers = [("Tenderer_A", OFFER_A, False), ("Tenderer_B", OFFER_B, False),
                  ("Tenderer_C", OFFER_C, True)]
    else:
        offers = [synth_offer(i) for i in range(1, args.bidders + 1)]

    scanned = []
    for name, offer, scan in offers:
        d = base / "bids" / name
        d.mkdir(parents=True, exist_ok=True)
        make_text_pdf(d / "offer.pdf", offer)
        if scan:
            rasterize(d / "offer.pdf")
            scanned.append(name)
    print(f"Synthetic case written to {base}: {len(offers)} bidders"
          f" (scanned/image-only: {', '.join(scanned) or 'none'})")


if __name__ == "__main__":
    main()
