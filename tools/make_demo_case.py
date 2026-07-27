"""Generate a fully synthetic tender case (safe to send to cloud APIs) in demo_case/.

Scenario — Supply of Industrial Degreaser, unit-price x quantity scheme:
  Tenderer A: complete, compliant, HK$12.50/L
  Tenderer B: complete, compliant, HK$11.80/L but quoted total has an arithmetic error
  Tenderer C: cheapest, but missing the Non-collusive Tendering Certificate (fails
              Stage I) — and its offer is an image-only "scanned" PDF, so the pipeline
              must OCR it through the vision model chain
Expected outcome: C ranked 1 yet non-conforming; B recommended with an error note.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.pdfgen import make_text_pdf  # noqa: E402

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
    base = ROOT / "demo_case"
    tender = base / "tender"
    tender.mkdir(parents=True, exist_ok=True)
    make_text_pdf(tender / "01_terms_of_tender_supplement.pdf", TERMS)
    make_text_pdf(tender / "02_special_conditions.pdf", SPECIAL_CONDITIONS)
    for name, offer in [("Tenderer_A", OFFER_A), ("Tenderer_B", OFFER_B), ("Tenderer_C", OFFER_C)]:
        d = base / "bids" / name
        d.mkdir(parents=True, exist_ok=True)
        make_text_pdf(d / "offer.pdf", offer)
    rasterize(base / "bids" / "Tenderer_C" / "offer.pdf")
    print(f"Synthetic case written to {base} (Tenderer_C's offer is scanned/image-only)")


if __name__ == "__main__":
    main()
