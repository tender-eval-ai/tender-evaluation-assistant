// From the contract's citations to DocumentViewer pages ({url, label,
// pageNumber, box}).
import { listPages, pageImageUrl } from "./api.js";

// What to ask the server to highlight on a cited offer page. PageCitation has
// no box and no quote at S2 (the quote arrives with V4, S4), so the best text
// available is a value the checker read from that very page, e.g. the
// tenderer's name on the certificate. Booleans ("signed: yes") are not text
// on the page, so they are skipped.
export function highlightFor(values, citation) {
  for (const v of Object.values(values ?? {})) {
    if (
      typeof v?.value === "string" &&
      v.value.trim() &&
      !v.redacted &&
      v.page?.doc_id === citation.doc_id &&
      v.page?.page === citation.page
    ) {
      return v.value;
    }
  }
  return null;
}

export function offerPage(citation, highlight) {
  return {
    url: pageImageUrl(citation.image_url, { highlight }),
    label: `${citation.file}, p.${citation.page}`,
    pageNumber: citation.page,
    box: null,
  };
}

// A rule set Citation names its document by path relative to the project
// ("tender/09 Schedules.pdf"); Document has a doc_id and the bare file name.
// Match them, then take the page's signed link from GET .../pages.
export function documentFor(documents, citation) {
  const [top, ...rest] = citation.file.split("/");
  const file = rest.pop();
  return (
    (documents ?? []).find((d) =>
      top === "tender"
        ? d.kind === "tender" && d.file === file
        : top === "bids" && d.kind === "bid" && d.tenderer === rest[0] && d.file === file
    ) ?? null
  );
}

export async function tenderPage(pid, documents, citation) {
  const doc = documentFor(documents, citation);
  if (!doc) throw new Error(`${citation.file} is not among the project's documents`);
  const pages = await listPages(pid, doc.doc_id);
  const page = pages.find((p) => p.page === citation.page);
  if (!page) throw new Error(`${citation.file} has no page ${citation.page}`);
  return {
    url: pageImageUrl(page.image_url, { highlight: citation.quote }),
    label: `${doc.file}, p.${page.page}`,
    pageNumber: page.page,
    box: null,
    file: doc.file,
  };
}
