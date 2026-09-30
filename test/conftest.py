import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.pdfgen import make_text_pdf  # noqa: E402, F401  (re-exported for tests)
