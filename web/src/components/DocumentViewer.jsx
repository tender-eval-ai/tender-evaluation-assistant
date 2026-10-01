import { useEffect, useRef, useState } from "react";
import { ChevronIcon } from "./Icons.jsx";

// Scrolls the viewer's own page stack, never the window: scrollIntoView also scrolls every
// scrollable ancestor, so opening a window or picking an item pushed the top bar out of view.
function scrollWithin(container, node, block) {
  if (!container || !node) return;
  const offset = node.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
  const top = Math.max(0, block === "center" ? offset - (container.clientHeight - node.offsetHeight) / 2 : offset);
  if (container.scrollTo) container.scrollTo({ top, behavior: "smooth" });
  else container.scrollTop = top;
}

export default function DocumentViewer({ pages, emptyLabel, focusPage }) {
  const pageRefs = useRef({});
  const containerRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(focusPage ?? null);

  useEffect(() => {
    if (focusPage == null) return;
    const node = pageRefs.current[focusPage];
    // A cited page with a box scrolls to the marked text; without one, to the
    // top of the page.
    const mark = node?.querySelector(".page-highlight");
    if (mark) scrollWithin(containerRef.current, mark, "center");
    else if (node) scrollWithin(containerRef.current, node, "start");
    setCurrentPage(focusPage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusPage, pages]);

  // Track which page is most visible while the reviewer scrolls freely, so
  // the toolbar stays in sync even after the initial jump-to-reference.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !pages || pages.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible.length > 0) {
          const pageNumber = Number(visible[0].target.dataset.pageNumber);
          if (!Number.isNaN(pageNumber)) setCurrentPage(pageNumber);
        }
      },
      { root: container, threshold: [0.5] }
    );
    Object.values(pageRefs.current).forEach((node) => node && observer.observe(node));
    return () => observer.disconnect();
  }, [pages]);

  function goToPage(pageNumber) {
    const node = pageRefs.current[pageNumber];
    scrollWithin(containerRef.current, node, "start");
    setCurrentPage(pageNumber);
  }

  if (!pages || pages.length === 0) {
    return (
      <div className="doc-viewer doc-viewer-empty">
        <p>{emptyLabel ?? "Select an item to view its source pages."}</p>
      </div>
    );
  }

  const pageNumbers = pages.map((p) => p.pageNumber).filter((n) => n != null);
  const minPage = Math.min(...pageNumbers);
  const maxPage = Math.max(...pageNumbers);
  const atFirst = currentPage == null || currentPage <= minPage;
  const atLast = currentPage == null || currentPage >= maxPage;

  return (
    <div className="doc-viewer">
      <div className="doc-viewer-toolbar">
        <button type="button" className="doc-viewer-nav-btn" disabled={atFirst} onClick={() => goToPage((currentPage ?? minPage) - 1)}>
          <ChevronIcon direction="up" />
        </button>
        <span className="doc-viewer-page-indicator">
          Page {currentPage ?? minPage} of {maxPage}
        </span>
        <button type="button" className="doc-viewer-nav-btn" disabled={atLast} onClick={() => goToPage((currentPage ?? minPage) + 1)}>
          <ChevronIcon direction="down" />
        </button>
      </div>
      <div className="page-stack" ref={containerRef}>
        {pages.map((page) => (
          <figure
            className={`page-stack-item${page.pageNumber === focusPage ? " page-stack-item-focus" : ""}`}
            key={page.url}
            data-page-number={page.pageNumber}
            ref={(node) => {
              if (page.pageNumber != null) pageRefs.current[page.pageNumber] = node;
            }}
          >
            <div className="page-stack-image-wrap">
              {/* A signed link (PageCitation.image_url): no cookie or key goes with it.
                  With a signed `highlight` the server marks the cited text on the
                  page itself; `box` (percent of the page, from PageCitation.box and
                  page_size) is drawn over it here. No box: the page, unmarked. */}
              <img src={page.url} alt={page.label} loading="lazy" />
              {page.box && (
                <div
                  className="page-highlight"
                  data-testid="page-highlight-box"
                  title={page.quote ?? undefined}
                  style={{
                    left: `${page.box.left}%`,
                    top: `${page.box.top}%`,
                    width: `${page.box.width}%`,
                    height: `${page.box.height}%`,
                  }}
                />
              )}
            </div>
            <figcaption>{page.label}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}
