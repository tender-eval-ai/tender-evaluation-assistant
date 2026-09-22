"""V1: six pages a call, every page answered, unknown labels never leak through."""
from app.checks.pages import as_dicts, render_offer
from app.checks.triage import PageLabel, PageLabels, triage
from test.checks.conftest import CASE, cert_page, fake_llm, page_labels
from test.fakes import FakeLLM, Rule


def _pages(tmp_path, tenderer="Tenderer_B"):
    return as_dicts(render_offer(CASE / "bids" / tenderer, tmp_path))


def test_sixteen_pages_take_three_calls_and_every_page_gets_one_label(tmp_path):
    pages = _pages(tmp_path)
    llm = fake_llm("Tenderer_B")
    progress = []
    labels = triage(pages, "Tenderer_B", llm, lambda step, d, n: progress.append((step, d, n)))
    assert llm.count() == 3 and progress == [("triage", 6, 16), ("triage", 12, 16), ("triage", 16, 16)]
    assert [lab["seq"] for lab in labels] == list(range(1, 17))
    assert labels[cert_page("Tenderer_B") - 1]["label"] == "noncollusive_certificate"
    assert labels[cert_page("Tenderer_B") - 1]["signed"] is True
    assert {lab["label"] for lab in labels} == set(page_labels("Tenderer_B").values()) | {"company_profile"}
    assert sum(lab["label"] == "company_profile" for lab in labels) == 16 - len(page_labels("Tenderer_B"))
    assert all(len(c.images) == 6 or c.images == [] for c in llm.calls[:2]) and len(llm.calls[2].images) == 4


def test_start_at_and_max_batches_let_a_job_checkpoint_per_batch(tmp_path):
    pages = _pages(tmp_path)
    llm = fake_llm("Tenderer_B")
    first = triage(pages, "Tenderer_B", llm, lambda *_: None, start_at=0, max_batches=1)
    rest = triage(pages, "Tenderer_B", llm, lambda *_: None, start_at=6)
    assert [lab["seq"] for lab in first] == [1, 2, 3, 4, 5, 6] and [lab["seq"] for lab in rest] == list(range(7, 17))
    assert llm.count() == 3


def test_missing_and_unknown_labels_become_other(tmp_path):
    pages = _pages(tmp_path, "Tenderer_A")[:6]
    sparse = FakeLLM([Rule(reply=PageLabels(labels=[PageLabel(seq=1, label="cover_or_contents"),
                                                     PageLabel(seq=2, label="marketing_brochure")]), out_model=PageLabels)])
    labels = triage(pages, "Tenderer_A", sparse, lambda *_: None)
    assert [lab["label"] for lab in labels] == ["cover_or_contents", "other", "other", "other", "other", "other"]
