import { useCallback, useEffect, useState } from "react";
import { getPriceSummary } from "../api.js";

// Two decimal places for money, but the unit price is quoted to more and the
// client's Price Summary prints it as given, so it is not rounded here.
const money = (n) => (n == null ? "—" : n.toLocaleString("en-HK", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const plain = (n) => (n == null ? "—" : String(n));

// The Scoring window: the Price Summary for one rule-set version. Every computable
// offer is ranked; the recommendation is the best-ranked CONFORMING one, which is why
// a cheaper non-conforming offer can rank above it and still not be recommended -
// the table shows both so a reviewer can see why.
//
// Nothing here recomputes a price. The API returns the rows already ranked, with the
// reviewer's corrections applied and a US$ quotation converted at the scheme's rate;
// this window only says what it was told, and where it came from.
export default function ScoringWindow({ projectId, version }) {
  const [summary, setSummary] = useState(undefined); // undefined while loading
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setSummary(await getPriceSummary(projectId, { version }));
    } catch (err) {
      setSummary(null);
      setError(err);
    }
  }, [projectId, version]);

  useEffect(() => { load(); }, [load]);

  if (summary === undefined) return <section className="window scoring"><p>Loading the price summary…</p></section>;

  if (error) {
    // 409 unconfirmed_ruleset is the expected state before a rule set is confirmed,
    // not a failure: say what is missing rather than showing an empty table.
    const message = error.code === "unconfirmed_ruleset"
      ? "No confirmed rule set yet. Confirm one in the Rules window to score the offers."
      : error.message;
    return (
      <section className="window scoring">
        <h2>Scoring</h2>
        <p className="notice" role="status">{message}</p>
      </section>
    );
  }

  const { scheme, rows, recommended, missing = [], ruleset_version: rulesetVersion } = summary;
  const effectiveness = scheme.type === "cost_effectiveness";

  return (
    <section className="window scoring">
      <h2>Scoring — Price Summary</h2>
      <p className="meta">
        Rule set v{rulesetVersion} · {effectiveness ? "ranked on cost-effectiveness" : "ranked on unit price × quantity"}
        {scheme.quantity != null && <> · quantity {scheme.quantity.toLocaleString("en-HK")} {scheme.unit}</>}
        {scheme.source && <> (<cite>{scheme.source}</cite>)</>}
        {" · "}US$ at {scheme.usd_hkd}
      </p>

      {missing.length > 0 && (
        <p className="notice" role="status">
          Checked against another rule-set version, so not ranked here: {missing.join(", ")}.
        </p>
      )}

      <table>
        <caption className="sr-only">Price summary by tenderer</caption>
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Tenderer</th>
            <th scope="col">Unit price</th>
            <th scope="col">{scheme.currency} equivalent</th>
            <th scope="col">Estimated goods price</th>
            {effectiveness && <th scope="col">Dosage</th>}
            {effectiveness && <th scope="col">Cost-effectiveness</th>}
            <th scope="col">Stage I</th>
            <th scope="col">Stage II</th>
            <th scope="col">Remark</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.tenderer}
                className={[row.conforming ? "conforming" : "non-conforming",
                            row.tenderer === recommended ? "recommended" : ""].filter(Boolean).join(" ")}>
              <td>{plain(row.ranking)}</td>
              <th scope="row">
                {row.tenderer}
                {row.tenderer === recommended && <span className="badge" title="best-ranked conforming offer">recommended</span>}
                {row.corrected.length > 0 && (
                  <span className="badge corrected" title={`corrected by a reviewer: ${row.corrected.join(", ")}`}>
                    corrected
                  </span>
                )}
              </th>
              <td>{money(row.unit_price)} {row.currency}</td>
              <td>{money(row.unit_price_hkd)}</td>
              <td>{money(row.estimated_goods_price)}</td>
              {effectiveness && <td>{plain(row.dosage_rounded ?? row.dosage)}</td>}
              {effectiveness && <td>{money(row.cost_effectiveness)}</td>}
              <td>{row.stage1 ?? "—"}</td>
              <td>{row.stage2 ?? "—"}</td>
              <td>
                {row.arithmetic_ok === false && <strong>arithmetic does not check out. </strong>}
                {row.remark}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {rows.length === 0 && <p className="notice">No tenderer has been checked against this rule set yet.</p>}
    </section>
  );
}
