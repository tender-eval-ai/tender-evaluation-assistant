import Badge from "./Badge.jsx";

function hkd(value) {
  if (value === null || value === undefined) return "—";
  return `HK$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function num(value, digits = 2) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// "Cannot be calculated" / "not applicable" are the real Price Summary sample's
// own wording (context.md §2/§5) for a conforming tenderer whose index can't be
// derived - kept verbatim here rather than reworded, since a reviewer comparing
// this table against the paper original should see matching text.
function rankCell(row) {
  if (row.status === "RANKED") return row.rank;
  if (row.status === "CANNOT_CALCULATE") return "not applicable";
  return "—";
}

function indexCell(row) {
  if (row.status === "RANKED") return num(row.cost_effectiveness_index);
  if (row.status === "CANNOT_CALCULATE") return "cannot be calculated";
  return "—";
}

export default function PriceSummaryTable({ summary }) {
  if (!summary?.available) {
    return (
      <div className="p-6 text-xs text-ink-3">
        {summary?.reason ?? "No price-summary scoring rule is defined for this tender yet."}
      </div>
    );
  }

  const { rows, formula_text: formulaText, scoring_formula_label: formulaLabel, footnotes } = summary;
  const disqualified = rows.filter((r) => r.status === "DISQUALIFIED");

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="mb-3">
        <p className="font-mono text-xs text-ink-4 uppercase tracking-wider">Summary of Cost-effectiveness</p>
        <p className="text-xs text-ink-3 mt-0.5">
          {formulaLabel} · <span className="font-mono">{formulaText}</span>
        </p>
      </div>

      {disqualified.length > 0 && (
        <div className="mb-3 p-2.5 rounded border border-mandatory bg-mandatory-wash">
          <p className="text-xs font-semibold text-mandatory mb-1">
            {disqualified.length} tenderer{disqualified.length === 1 ? "" : "s"} disqualified — excluded from ranking
          </p>
          <ul className="text-xs text-ink-2 leading-5 list-disc pl-4">
            {disqualified.map((r) => (
              <li key={r.vendor_id}>
                <span className="font-medium">{r.vendor_name}</span>
                {r.notes?.length ? `: ${r.notes.join("; ")}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="bg-bg text-ink-3 font-mono uppercase tracking-wider text-[11px]">
              <th className="p-2 text-left border-b border-border">Rank</th>
              <th className="p-2 text-left border-b border-border">Name of Tenderer</th>
              <th className="p-2 text-right border-b border-border">Estimated Goods Price (HK$)</th>
              <th className="p-2 text-right border-b border-border">Unit Price (M)</th>
              <th className="p-2 text-right border-b border-border">Optimal Dosage (D)</th>
              <th className="p-2 text-right border-b border-border">Cost-effectiveness (D) x (M)</th>
              <th className="p-2 text-left border-b border-border">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.vendor_id}
                className={`border-b border-border-soft ${row.status === "DISQUALIFIED" ? "bg-mandatory-wash" : ""}`}
              >
                <td className="p-2 font-mono">{rankCell(row)}</td>
                <td className="p-2 font-medium text-ink-1">{row.vendor_name}</td>
                <td className="p-2 text-right font-mono">
                  {hkd(row.estimated_goods_price_hkd)}
                  {row.arithmetic_consistent === false && (
                    <span className="ml-1 text-rectifiable" title="Reported total does not match Estimated Quantity x Unit Price">
                      ⚠
                    </span>
                  )}
                </td>
                <td className="p-2 text-right font-mono">
                  {row.one_time_unit_price_hkd ?? "—"}
                  {row.unit_price_currency && row.unit_price_currency !== "HK$" ? ` ${row.unit_price_currency}` : ""}
                </td>
                <td className="p-2 text-right font-mono">
                  {row.optimal_dosage_raw ?? "—"}
                  {row.optimal_dosage_unit ? ` ${row.optimal_dosage_unit}` : ""}
                </td>
                <td className="p-2 text-right font-mono">{indexCell(row)}</td>
                <td className="p-2">
                  <Badge kind={row.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.some((r) => r.notes?.length && r.status !== "DISQUALIFIED") && (
        <div className="mt-3 flex flex-col gap-1.5">
          {rows
            .filter((r) => r.notes?.length && r.status !== "DISQUALIFIED")
            .map((r) => (
              <div key={r.vendor_id} className="text-xs text-ink-3 leading-5">
                <span className="font-medium text-ink-2">{r.vendor_name}</span>: {r.notes.join("; ")}
              </div>
            ))}
        </div>
      )}

      {footnotes?.length > 0 && (
        <div className="mt-4 pt-3 border-t border-border-soft flex flex-col gap-1">
          <p className="font-mono text-xs text-ink-4 uppercase tracking-wider mb-1">Notes</p>
          {footnotes.map((note, i) => (
            <p key={i} className="text-xs text-ink-3 leading-5">
              {note}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
