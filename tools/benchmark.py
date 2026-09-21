"""The parser benchmark: the four metrics, defined once.

These are the numbers `docs/evals/parser_l0.md` records and the S3 gate is read
against. They are AI_camp's, from `retrieval_eval/traceability_groundtruth_eval_2.md`,
where they were applied by hand to 241 rule citations on Tender 1. Nothing here
invents a metric: a new question about the parser gets measured as a new, named
metric alongside these, never by quietly changing what one of these means.

    recall                  a parser node of its own starts at the key node - same
                            page, and its text opens with the key node's first words
    page_correct            that node starts on the key node's first page
    char_correct            that node records a real, non-zero character length
                            (a container, which carries no text of its own, passes)
    exact_location_correct  page and char correct, a bbox is recorded, AND the node's
                            own text starts with its own marker - which is what makes
                            the recorded position the node's actual start rather than
                            a same-page coincidence

Two properties worth keeping in mind when reading a result:

- `page_correct` and `char_correct` have been numerically identical to `recall` on
  all three tenders throughout, because the parser has never produced a node with a
  page but no text. They are three measurements, but so far one number.
- `exact_location_correct` is bounded above by `recall`: a node that was never found
  cannot have a correct location. Raising it means raising recall first.

Deliberately NOT in the benchmark:

- `kind_correctness` - it skips every node whose id implies no kind (rows, tails,
  notes, fields, headings), and those are the nodes that fail. Measured on 79-87% of
  nodes whose recall was 90-98%, while the nodes it skipped had recall of 23-49%, it
  read high for the wrong reason.
- `hierarchy_correctness` - useful as a diagnostic (it is how the POGS 0/21 parenting
  bug was found) but never a gate.

Both are still computed by the evaluator; they are just not the benchmark.
"""
from __future__ import annotations

import re

#: The benchmark, in reporting order. A result quotes all four or says which it omits.
BENCHMARK = ("recall", "page_correct", "char_correct", "exact_location_correct")

#: Kinds that carry no text of their own, so a zero length is correct for them.
CONTAINER_KINDS = ("document", "subdocument", "part", "annex")

# A leading footnote glyph is not part of a node's own marker - the */^/# convention
# AI_camp tolerated, and no more than that. The bracketed capital these tenders put
# before a requirement's number ("(D) 3.6.4.4 It is a desirable feature...") is
# deliberately NOT stripped here: the parser attaches that flag to the item itself
# (`_attach_item_flags`), which is the right place for it. Widening this pattern
# would make the metric more permissive to accommodate the parser - the exact drift
# this module exists to prevent.
_LEADING_GLYPH = re.compile(r"^[*^#\s]+")


def squash(text: str | None) -> str:
    """Whitespace-insensitive, case-insensitive form, for comparing text to a marker."""
    return re.sub(r"\s+", "", text or "").lower()


def own_markers(node: dict) -> list[str]:
    """Every marker a node's own text may legitimately open with.

    `part` is a SCOPE field - which Part a node sits under - so it is only the node's
    own marker for a node that IS a Part or annex, where the document prints it
    ("Part A", "Table A", "第 4 部分"). ALL candidates are returned, not the first that
    happens to be set: a Part node carries both `number` ("A") and `part` ("Part A"),
    and stopping at `number` failed every Part heading.
    """
    candidates = [node.get("label"), node.get("number")]
    if node.get("kind") in ("part", "annex"):
        candidates.append(node.get("part"))
    return [c for c in candidates if c]


def starts_with_own_marker(node: dict) -> bool:
    """Does the node's own text begin with its own marker?

    A node with no marker of its own - a heading, a form field, a table row with no
    key, a tail - passes on having text at all: there is no marker for it to fail to
    start with.
    """
    text = _LEADING_GLYPH.sub("", node.get("text") or "")
    markers = own_markers(node)
    if not markers or not text:
        return bool(text)
    return any(squash(text).startswith(squash(m)) for m in markers)


def score(key_node: dict, node: dict | None) -> dict[str, bool]:
    """The four metrics for one key node and the parser node matched to it (or None).

    `node` is None when the parser produced nothing for this key node, in which case
    every metric is False - including the three that would otherwise be vacuous.
    """
    if node is None:
        return {name: False for name in BENCHMARK}
    page_ok = node.get("page") == key_node["page"][0]
    char_ok = len(node.get("text") or "") > 0 or node.get("kind") in CONTAINER_KINDS
    return {
        "recall": True,
        "page_correct": page_ok,
        "char_correct": char_ok,
        "exact_location_correct": (
            page_ok and char_ok and bool(node.get("bbox")) and starts_with_own_marker(node)
        ),
    }


def rate(rows: list[dict], name: str) -> tuple[int, int]:
    """(correct, scored) for one metric over a list of per-node result rows."""
    scored = [r[name] for r in rows if r.get(name) is not None]
    return sum(scored), len(scored)


def format_result(rows: list[dict], label: str = "") -> str:
    """One line per metric, the shape `docs/evals/parser_l0.md` records."""
    out = [f"{label} ({len(rows)} nodes)" if label else f"{len(rows)} nodes"]
    for name in BENCHMARK:
        ok, total = rate(rows, name)
        pct = 100 * ok / total if total else 0.0
        out.append(f"  {name:<24} {ok:>5}/{total:<5} {pct:5.1f}%")
    return "\n".join(out)
