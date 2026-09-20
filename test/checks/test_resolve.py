"""V2: the labels answer when they can; the model is asked only when they cannot."""
from app.checks.resolve import ItemPages, resolve
from test.checks.conftest import fake_llm
from test.fakes import FakeLLM, Rule


def _labels(cert_seq: int | None, n: int = 16) -> list[dict]:
    return [{"seq": i, "doc": "offer.pdf", "page": i, "path": "", "has_text": False,
             "label": "noncollusive_certificate" if i == cert_seq else "company_profile",
             "title": "Non-collusive Tendering Certificate" if i == cert_seq else f"Company Profile - Section {i}",
             "summary": "", "signed": i == cert_seq, "has_table": False} for i in range(1, n + 1)]


def test_a_labelled_page_is_found_without_a_call():
    llm = fake_llm("Tenderer_B")
    out = resolve(_labels(13), "l", "Tenderer_B", llm)
    assert out.pages == [13] and out.confidence == 0.9 and llm.count() == 0


def test_without_a_label_the_model_is_asked_once_with_the_index():
    llm = fake_llm("Tenderer_C")
    out = resolve(_labels(None), "l", "Tenderer_C", llm)
    assert out.pages == [] and llm.count() == 1 and "p13 company_profile" in llm.calls[0].user


def test_the_model_cannot_name_a_page_that_does_not_exist():
    llm = FakeLLM([Rule(reply=ItemPages(pages=[3, 99], confidence=0.8), out_model=ItemPages)])
    assert resolve(_labels(None, 5), "l", "t", llm).pages == [3]
