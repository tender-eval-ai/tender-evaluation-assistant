import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "test" / "data" / "synthetic_case"


@pytest.fixture
def synthetic_case():
    from app.rubric import load_rubric
    from app.schemas import BidExtraction

    rubric = load_rubric(FIXTURES / "rubric.json")
    bids = [BidExtraction.model_validate_json(p.read_text())
            for p in sorted((FIXTURES / "bids").glob("*.json"))]
    return rubric, bids


from tools.pdfgen import make_text_pdf  # noqa: E402, F401  (re-exported for tests)
