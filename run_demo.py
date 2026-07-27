#!/usr/bin/env python3
"""Tender Evaluation Assistant — demo CLI.

  offline-demo   run the synthetic case end-to-end with no network calls
  run            full pipeline over real folders via GitHub Models (cloud!)

Examples:
  python run_demo.py offline-demo
  python run_demo.py run --tender-dir docs/tender --bids-dir docs/bids \
      --out output/case1 --acknowledge-cloud
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.config import Config, load_dotenv  # noqa: E402
from app.pipeline import run_offline, run_pipeline, summarize  # noqa: E402

CLOUD_WARNING = """\
*** CONFIDENTIALITY CHECK ***
'run' sends document content to GitHub Models (cloud). The client's data is under a
strict NDA and must stay local — use this mode ONLY with synthetic or sanitized
documents. Re-run with --acknowledge-cloud to confirm your inputs are safe to upload.
"""


def cmd_offline(args: argparse.Namespace) -> int:
    fixtures = ROOT / "test" / "data" / "synthetic_case"
    out = Path(args.out)
    result = run_offline(fixtures, out)
    print()
    print(summarize(result))
    print(f"\nEditable Word reports: {out / 'reports'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.acknowledge_cloud:
        print(CLOUD_WARNING)
        return 2
    load_dotenv(ROOT / ".env")
    cfg = Config()
    if args.max_ocr_pages:
        cfg.max_ocr_pages = args.max_ocr_pages
    cfg.cache_dir = Path(args.out) / "cache"
    from app.llm import LLM  # import here so offline mode never needs the openai package
    llm = LLM(cfg)
    print(f"Backend: {cfg.base_url}  text={cfg.text_model}  vision={cfg.vision_model}")
    result = run_pipeline(Path(args.tender_dir), Path(args.bids_dir), Path(args.out), cfg, llm)
    print()
    print(summarize(result))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_off = sub.add_parser("offline-demo", help="synthetic case, no network")
    p_off.add_argument("--out", default="output/offline_demo")
    p_off.set_defaults(func=cmd_offline)

    p_run = sub.add_parser("run", help="full pipeline via GitHub Models (cloud)")
    p_run.add_argument("--tender-dir", required=True, help="folder of tender document PDFs")
    p_run.add_argument("--bids-dir", required=True,
                       help="folder with one subfolder (or one PDF) per tenderer")
    p_run.add_argument("--out", required=True, help="output/checkpoint directory")
    p_run.add_argument("--max-ocr-pages", type=int, default=None,
                       help="cap OCR pages per scanned document (default 8; free-tier limits)")
    p_run.add_argument("--acknowledge-cloud", action="store_true",
                       help="confirm the input documents are safe to send to a cloud API")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
