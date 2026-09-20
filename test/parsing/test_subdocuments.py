"""Splitting a combined PDF into its documents from each page's numbering (synthetic page text)."""
from app.parsing.document_index import _zh_number, detect_subdocuments
from app.parsing.loader import Page


def _pages(*texts: str) -> list[Page]:
    return [Page("combined.pdf", number, True, text) for number, text in enumerate(texts, start=1)]


def _starts(pages) -> list[tuple[str, int]]:
    return [(s["name"], s["first_page"]) for s in detect_subdocuments(pages)]


def test_a_footer_with_the_name_before_page_n_of_m_still_splits_as_before():
    pages = _pages(
        "Body text.\nSample Schedule Page 1 of 2",
        "Body text.\nSample Schedule Page 2 of 2",
        "Body text.\nOther Schedule Page 1 of 1",
    )

    assert _starts(pages) == [("Sample Schedule", 1), ("Other Schedule", 3)]


def test_page_numbering_printed_above_the_name_starts_a_document():
    pages = _pages(
        "Page 1 of 2\nF.1 (Rev. 01/25) (English Version)\nBody text.",
        "Page 2 of 2\nF.1 (Rev. 01/25) (English Version)\nBody text.",
        "Body text.\nSample Schedule Page 1 of 1",
    )

    assert _starts(pages) == [("F.1 (Rev. 01/25) (English Version)", 1), ("Sample Schedule", 3)]


def test_chinese_page_numbering_starts_its_own_document():
    pages = _pages(
        "Page 1 of 1\nF.1 (Rev. 01/25) (English Version)\nBody text.",
        "第一頁，共二頁\nF.1 (Rev.01/25) (中文版)\n正文。",
        "第二頁，共二頁\nF.1 (Rev. 01/25) (中文版)\n正文。",
    )

    assert _starts(pages) == [("F.1 (Rev. 01/25) (English Version)", 1), ("F.1 (Rev.01/25) (中文版)", 2)], \
        "a name that differs only in spacing is the same document"


def test_a_reference_number_line_over_page_n_of_m_names_a_document():
    pages = _pages(
        "Body text.\nSample Schedule Page 1 of 1",
        "Ref. No. SAMPLE-TERMS-1 (June 2025)\nPage 1 of 150\nBody text.",
        "Ref. No. SAMPLE-TERMS-1 (June 2025)\nPage 2 of 150\nBody text.",
        "Ref. No. SAMPLE-TERMS-1 (June 2025)\nPage 3 of 150\nBody text.",
        "Ref. No. SAMPLE-TERMS-1 (June 2025)\nPage 4 of 150\nBody text.",
        "Ref. No. SAMPLE-TERMS-1 (June 2025)\nPage 5 of 150\nBody text.",
    )

    segments = detect_subdocuments(pages)

    assert [(s["name"], s["first_page"], s["last_page"]) for s in segments] == [
        ("Sample Schedule", 1, 1), ("Ref. No. SAMPLE-TERMS-1 (June 2025)", 2, 6),
    ]


def test_chinese_numerals():
    assert [_zh_number(t) for t in ("一", "三", "十", "十二", "二十", "一百零三")] == [1, 3, 10, 12, 20, 103]
