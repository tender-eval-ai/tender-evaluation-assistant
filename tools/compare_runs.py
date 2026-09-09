"""Markdown tables from step-2 measurement files: stress results (tools/stress_test.py
--out), buried-benchmark runs (tools/benchmark_buried.py --out dirs) and an OCR
comparison report (tools/ocr_compare.py) — the "agreement, latency, $ per bid" table.

    python tools/compare_runs.py --stress vertex=output/step2/stress_vertex.json \\
        deepseek=output/step2/stress_deepseek.json local=output/step2/stress_local.json \\
        --bench vertex=output/step2/bench_vertex deepseek=output/step2/bench_deepseek \\
        --ocr output/step2/ocr_compare/report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _kv(items: list[str]) -> dict[str, Path]:
    return {k: Path(v) for k, v in (s.split("=", 1) for s in items)}


def stress_table(files: dict[str, Path]) -> str:
    rows = ["| configuration | agreement | wall clock | rubric | extraction | $ total | $ / bid (mean · median) | tokens / bid | model s / bid (median) | failed calls |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for label, path in files.items():
        r = json.loads(path.read_text())
        a, u, s = r["agreement"]["overall"], r.get("usage") or {}, r["seconds"]
        rows.append(f"| {label} | {a['agree']}/{a['of']} ({a['pct']}%) | {s['total']} s | {s['rubric']} s "
                    f"| {s['extract']} s | ${u.get('usd_total', 0)} | ${u.get('usd_per_bid_mean', 0)} · "
                    f"${u.get('usd_per_bid_median', 0)} | {u.get('tokens_per_bid', '—')} "
                    f"| {u.get('model_seconds_per_bid_median', '—')} s | {u.get('failed_calls', '—')} |")
    return "\n".join(rows)


def bench_table(dirs: dict[str, Path]) -> str:
    rows = ["| configuration | run | certificate recall | false restores | price extracted | unclear w/ evidence | agent OCR pages | time | $ |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for label, d in dirs.items():
        res = json.loads((d / "results.json").read_text())
        for mode, r in res.items():
            usage = d / mode / "usage" / "summary.json"
            usd = json.loads(usage.read_text())["usd_total"] if usage.is_file() else 0
            rows.append(f"| {label} | {mode} | {r['cert_recall']} | {r['false_restores']} | {r['price_extracted']} "
                        f"| {r['unclear_with_evidence']} | {r['agent_ocr_pages']} | {r['seconds']} s | ${usd} |")
    return "\n".join(rows)


def ocr_table(path: Path) -> str:
    r = json.loads(path.read_text())
    a, b = r["chains"]["a"], r["chains"]["b"]
    f = r["facts"]
    return "\n".join([
        f"| chain | served | s / page | $ / page | ground-truth facts found | failed calls |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| A `{a['entry'].split('@')[0]}` | {', '.join(a['served'].values())} | {a['seconds_per_page']} | ${a['usd_per_page']} | {f['a_found']}/{f['checked']} | {a['failed_calls']} |",
        f"| B `{b['entry'].split('@')[0]}` | {', '.join(b['served'].values())} | {b['seconds_per_page']} | ${b['usd_per_page']} | {f['b_found']}/{f['checked']} | {b['failed_calls']} |",
        "",
        f"Transcript similarity A vs B over {r['pages']} pages: mean {r['similarity']['mean']}, "
        f"median {r['similarity']['median']}, min {r['similarity']['min']}. "
        f"Missed by A: {f['missed_by_a'] or 'none'}. Missed by B: {f['missed_by_b'] or 'none'}. "
        f"Empty transcripts — A: {r.get('empty_transcripts', {}).get('a') or 'none'}; "
        f"B: {r.get('empty_transcripts', {}).get('b') or 'none'}.",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stress", nargs="*", default=[], help="label=results.json ...")
    ap.add_argument("--bench", nargs="*", default=[], help="label=benchmark_out_dir ...")
    ap.add_argument("--ocr", help="ocr_compare report.json")
    args = ap.parse_args()
    if args.stress:
        print("30-bidder stress case\n\n" + stress_table(_kv(args.stress)) + "\n")
    if args.bench:
        print("Buried-evidence benchmark\n\n" + bench_table(_kv(args.bench)) + "\n")
    if args.ocr:
        print("OCR comparison\n\n" + ocr_table(Path(args.ocr)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
