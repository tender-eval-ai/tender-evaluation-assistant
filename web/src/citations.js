// From the contract's citations to DocumentViewer pages ({url, label,
// pageNumber, box}).
import { listPages, pageImageUrl } from "./api.js";

// PageCitation.box ([x0, y0, x1, y1], PDF points, origin top-left) over
// PageCitation.page_size ([width, height]) as percentages of the page image,
// the form DocumentViewer draws. Null when either is missing (a scanned page,
// or a value not found on the text layer): the page still opens, unmarked.
export function boxOnPage(box, pageSize) {
  if (!Array.isArray(box) || box.length !== 4 || !Array.isArray(pageSize) || pageSize.length !== 2) return null;
  const [x0, y0, x1, y1] = box;
  const [w, h] = pageSize;
  if (!(w > 0 && h > 0 && x1 > x0 && y1 > y0)) return null;
  const pct = (v, of) => Math.min(100, Math.max(0, (v / of) * 100));
  return { left: pct(x0, w), top: pct(y0, h), width: pct(x1 - x0, w), height: pct(y1 - y0, h) };
}

// A cited offer page. `image_url` is used as given: when the citation has a
// quote, the server signed `highlight` into it and draws the highlight itself
// (adding or changing a query parameter breaks the signature).
export function offerPage(citation) {
  return {
    url: pageImageUrl(citation.image_url),
    label: `${citation.file}, p.${citation.page}`,
    pageNumber: citation.page,
    quote: citation.quote ?? null,
    box: boxOnPage(citation.box, citation.page_size),
  };
}

// A rule set Citation names its document by its path relative to the
// project ("tender/09 Schedules.pdf"), which is Document.path.
export function documentFor(documents, citation) {
  return (documents ?? []).find((d) => d.path === citation.file) ?? null;
}

export async function tenderPage(pid, documents, citation) {
  const doc = documentFor(documents, citation);
  if (!doc) throw new Error(`${citation.file} is not among the project's documents`);
  const pages = await listPages(pid, doc.doc_id);
  const page = pages.find((p) => p.page === citation.page);
  if (!page) throw new Error(`${citation.file} has no page ${citation.page}`);
  // Page.image_url is signed for the page only; the rule set quote is added
  // as an unsigned highlight, which the API still accepts on a page-only link
  // (docs/api_contract.md, until tender citations carry a signed one at S3).
  return {
    url: pageImageUrl(page.image_url, { highlight: citation.quote }),
    label: `${doc.file}, p.${page.page}`,
    pageNumber: page.page,
    box: null,
    file: doc.file,
  };
}
