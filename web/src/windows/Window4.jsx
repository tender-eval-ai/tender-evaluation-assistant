import { useEffect, useState } from "react";
import { getReport } from "../api.js";
import Badge from "../components/Badge.jsx";
import PriceSummaryTable from "../components/PriceSummaryTable.jsx";

const OVERALL_LABEL = {
  PASS: { label: "PASS", cls: "text-ok" },
  PASS_NEEDS_REVIEW: { label: "PASS — needs review", cls: "text-rectifiable" },
  FAIL: { label: "FAIL", cls: "text-mandatory" },
};

function OverallPill({ overall }) {
  const info = OVERALL_LABEL[overall] ?? { label: overall, cls: "text-ink-3" };
  return <span className={`font-mono text-xs font-semibold ${info.cls}`}>{info.label}</span>;
}

function Section({ title, subtitle, children }) {
  return (
    <section className="mb-8 break-inside-avoid">
      <div className="mb-2 pb-1.5 border-b-2 border-navy">
        <p className="text-sm font-semibold text-ink-1">{title}</p>
        {subtitle && <p className="text-xs text-ink-3 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function Stage1Section({ stage1 }) {
  const evaluated = stage1.items.filter((i) => i.status !== "not_evaluated");
  const notEvaluated = stage1.items.filter((i) => i.status === "not_evaluated");
  return (
    <Section
      title="Stage I — Completeness Check"
      subtitle={
        <>
          The vendor&rsquo;s submission was checked against the tender&rsquo;s Completeness Check Schedule. Result:{" "}
          <OverallPill overall={stage1.overall} /> ({stage1.counts.pass} compliant, {stage1.counts.needs_review} need
          review, {stage1.counts.disqualified} disqualifying, {stage1.counts.not_evaluated} not yet evaluated).
        </>
      }
    >
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-bg text-ink-3 font-mono uppercase tracking-wider text-[11px]">
            <th className="p-1.5 text-left border-b border-border w-16">Item</th>
            <th className="p-1.5 text-left border-b border-border">Requirement</th>
            <th className="p-1.5 text-left border-b border-border w-40">Status</th>
          </tr>
        </thead>
        <tbody>
          {evaluated.map((item) => (
            <tr key={item.id} className="border-b border-border-soft">
              <td className="p-1.5 font-mono">{item.id}</td>
              <td className="p-1.5 text-ink-2">{item.name}</td>
              <td className="p-1.5">
                <Badge kind={item.status} compact={false} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {notEvaluated.length > 0 && (
        <p className="text-xs text-ink-4 mt-2">
          Not yet evaluated (no vendor check run yet): {notEvaluated.map((i) => i.id).join(", ")}
        </p>
      )}
    </Section>
  );
}

function Stage2Section({ stage2 }) {
  const evaluated = stage2.letters.filter((l) => l.status !== "not_evaluated");
  const notEvaluated = stage2.letters.filter((l) => l.status === "not_evaluated");
  return (
    <Section
      title="Stage II — Assessment of Compliance with Essential Requirements"
      subtitle={
        <>
          Offers passing Stage I were checked against essential requirements (mandatory technical features,
          currency, arithmetic consistency, etc.). Result: <OverallPill overall={stage2.overall} />.
        </>
      }
    >
      <table className="w-full text-xs border-collapse mb-2">
        <thead>
          <tr className="bg-bg text-ink-3 font-mono uppercase tracking-wider text-[11px]">
            <th className="p-1.5 text-left border-b border-border w-20">Item</th>
            <th className="p-1.5 text-left border-b border-border">Result</th>
          </tr>
        </thead>
        <tbody>
          {evaluated.map((l) => (
            <tr key={l.letter} className="border-b border-border-soft">
              <td className="p-1.5 font-mono">({l.letter})</td>
              <td className="p-1.5">
                <Badge kind={l.status} compact={false} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {stage2.fields.length > 0 && (
        <div className="flex flex-col gap-1 mb-2">
          {stage2.fields
            .filter((f) => f.status !== "pass")
            .map((f) => (
              <p key={`${f.letter}-${f.field_id}`} className="text-xs text-ink-2 leading-5">
                <span className="font-mono text-ink-4">({f.letter})</span> {f.field}: {f.note}
              </p>
            ))}
        </div>
      )}
      {notEvaluated.length > 0 && (
        <p className="text-xs text-ink-4">
          Not yet evaluated (no extraction run yet): {notEvaluated.map((l) => `(${l.letter})`).join(", ")}
        </p>
      )}
    </Section>
  );
}

export default function Window4({ tenderId }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getReport(tenderId)
      .then((data) => {
        setReport(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [tenderId]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-ink-3 p-10 text-center">
        Assembling the report from Stage I, Stage II and the Price Summary…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-mandatory p-10 text-center">
        Failed to load: {error}
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-card">
      <div className="max-w-4xl mx-auto p-6 print:p-0">
        <div className="flex items-start justify-between mb-6 print:hidden">
          <div>
            <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Tender Assessment Report</p>
            <p className="text-lg font-semibold text-ink-1">{tenderId}</p>
            {report.vendor && <p className="text-xs text-ink-3 mt-0.5">Tenderer: {report.vendor.name}</p>}
          </div>
          <button
            type="button"
            onClick={() => window.print()}
            className="px-3 py-1.5 text-xs rounded border border-border text-ink-2 hover:text-accent-strong
              hover:border-accent transition-colors font-mono cursor-pointer"
          >
            ↓ Print / Export PDF
          </button>
        </div>

        <Stage1Section stage1={report.stage1} />
        <Stage2Section stage2={report.stage2} />

        <Section
          title="Stage III/IV — Price Assessment"
          subtitle="Cost-effectiveness ranking of conforming tenderers, per the tender's own Marking Scheme and Tender Evaluation rule."
        >
          <div className="border border-border rounded overflow-hidden">
            <PriceSummaryTable summary={report.price_summary} />
          </div>
        </Section>
      </div>
    </div>
  );
}
