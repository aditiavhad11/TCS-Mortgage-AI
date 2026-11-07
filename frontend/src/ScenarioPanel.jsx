import { useState } from "react";
import { notifyError } from "./ToastProvider";
// Shared by Customer and Reviewer portals. `run(name, body)` must return the scenario JSON from the backend.
const inr = (n) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(Number(n || 0));
const NAMES = {
  valuation_ltv: "Valuation & LTV",
  income_tax: "Income & tax reconciliation",
  terms_conditions: "Terms & conditions",
};
const SEV = {
  high: "#b42318",
  medium: "#b54708",
  low: "#475467",
  info: "#175cd3",
};
const num = (v) => (v === "" || v == null ? null : Number(v));
export default function ScenarioPanel({ run }) {
  const [name, setName] = useState("valuation_ltv");
  const [val, setVal] = useState({
    valuation_amount: "",
    purchase_price: "",
    max_ltv_percent: "",
  });
  const [years, setYears] = useState([
    { year: "", itr_total_income: "", salary_income: "", bank_credits: "" },
    { year: "", itr_total_income: "", salary_income: "", bank_credits: "" },
    { year: "", itr_total_income: "", salary_income: "", bank_credits: "" },
  ]);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const setY = (i, k, v) =>
    setYears((ys) => ys.map((y, j) => (j === i ? { ...y, [k]: v } : y)));
  async function go() {
    setBusy(true);
    setRes(null);
    try {
      let body = {};
      if (name === "valuation_ltv")
        body = {
          valuation_amount: num(val.valuation_amount),
          purchase_price: num(val.purchase_price),
          max_ltv_percent: num(val.max_ltv_percent),
        };
      if (name === "income_tax")
        body = {
          income_years: years
            .filter((y) => y.year.trim())
            .map((y) => ({
              year: y.year.trim(),
              itr_total_income: num(y.itr_total_income),
              salary_income: num(y.salary_income),
              bank_credits: num(y.bank_credits),
            })),
        };
      setRes(await run(name, body));
    } catch {
      notifyError();
    } finally {
      setBusy(false);
    }
  }
  const inp = (v, f, ph, w = 140) => (
    <input
      style={{ width: w, padding: "6px 8px", margin: "2px 4px 2px 0" }}
      value={v}
      placeholder={ph}
      onChange={(e) => f(e.target.value)}
      inputMode="decimal"
    />
  );
  return (
    <section className="panel">
      <div className="section-head">
        <div>
          <h2>Mortgage scenario checks</h2>
          <p>
            Deterministic calculations on the application and the document text.
            Enter figures you verified from the documents. Review aid only — not
            a credit decision.
          </p>
        </div>
      </div>
      <div
        style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}
      >
        {Object.entries(NAMES).map(([k, v]) => (
          <button
            key={k}
            className={name === k ? "primary" : "secondary"}
            onClick={() => {
              setName(k);
              setRes(null);
            }}
          >
            {v}
          </button>
        ))}
      </div>
      {name === "valuation_ltv" && (
        <div>
          {inp(
            val.valuation_amount,
            (v) => setVal({ ...val, valuation_amount: v }),
            "Valuation report (₹)",
          )}
          {inp(
            val.purchase_price,
            (v) => setVal({ ...val, purchase_price: v }),
            "Purchase price (₹)",
          )}
          {inp(
            val.max_ltv_percent,
            (v) => setVal({ ...val, max_ltv_percent: v }),
            "Lender max LTV %",
            130,
          )}
        </div>
      )}
      {name === "income_tax" && (
        <div>
          {years.map((y, i) => (
            <div key={i}>
              {inp(y.year, (v) => setY(i, "year", v), "FY e.g. 2023-24", 120)}
              {inp(
                y.itr_total_income,
                (v) => setY(i, "itr_total_income", v),
                "ITR income (₹)",
              )}
              {inp(
                y.salary_income,
                (v) => setY(i, "salary_income", v),
                "Salary / Form 16 (₹)",
              )}
              {inp(
                y.bank_credits,
                (v) => setY(i, "bank_credits", v),
                "Bank credits (₹)",
              )}
            </div>
          ))}
          <button
            className="secondary small"
            disabled={years.length >= 5}
            onClick={() =>
              setYears([
                ...years,
                {
                  year: "",
                  itr_total_income: "",
                  salary_income: "",
                  bank_credits: "",
                },
              ])
            }
          >
            + Add year (max 5)
          </button>
        </div>
      )}
      {name === "terms_conditions" && (
        <p className="hint">
          Uses the text of uploaded Loan Agreement, Terms / Disclosure and Sale
          / Purchase Agreement documents (your correction if saved, otherwise
          the original OCR text).
        </p>
      )}
      <div className="actions">
        <button className="primary" onClick={go} disabled={busy}>
          {busy ? "Running…" : "Run check"}
        </button>
      </div>
      {res && (
        <div>
          <h3>{NAMES[res.scenario]}</h3>
          {res.metrics && (
            <div className="hint">
              {Object.entries(res.metrics)
                .filter(([k, v]) => !Array.isArray(v))
                .map(([k, v]) => (
                  <span key={k} style={{ marginRight: 14 }}>
                    {k.replaceAll("_", " ")}:{" "}
                    <b>
                      {typeof v === "number" && k.endsWith("_inr")
                        ? inr(v)
                        : String(v)}
                    </b>
                  </span>
                ))}
            </div>
          )}
          {res.calculations && (
            <p className="hint">
              EMI {inr(res.calculations.estimated_monthly_emi_inr)} · LTV{" "}
              {res.calculations.loan_to_value_percent ?? "—"}% · DTI{" "}
              {res.calculations.debt_to_income_percent ?? "—"}% (illustrative)
            </p>
          )}
          {res.findings?.length ? (
            res.findings.map((f, i) => (
              <article key={i} className="doc">
                <div className="doc-head">
                  <b style={{ color: SEV[f.severity] }}>
                    {f.severity.toUpperCase()} · {f.code}
                  </b>
                </div>
                <p>{f.message}</p>
              </article>
            ))
          ) : (
            <p>No findings.</p>
          )}
          {res.policy_retrieval_status && (
            <section className="doc">
              <h4>Retrieved bank policy evidence</h4>
              {Array.isArray(res.policy_evidence) &&
              res.policy_evidence.length > 0 ? (
                <ul>
                  {res.policy_evidence.map((source, i) => (
                    <li key={`${source.policy_id}-${source.chunk_index}-${i}`}>
                      <b>
                        {source.title} · v{source.policy_version}
                      </b>
                      {source.category ? ` · ${source.category}` : ""}
                      <p>{source.excerpt}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="hint">
                  {res.policy_retrieval_status === "NO_RELEVANT_POLICY_EVIDENCE"
                    ? "No relevant active bank policy evidence was found. The scenario findings above remain deterministic document/application checks."
                    : "Bank policy evidence retrieval failed or returned no citations; no policy conclusion is inferred from the scenario findings."}
                </p>
              )}
            </section>
          )}
          <p className="hint">{res.disclaimer}</p>
        </div>
      )}
    </section>
  );
}
