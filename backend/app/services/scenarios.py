"""Deterministic mortgage scenario checks (no LLM, no randomness).

1. valuation_ltv            - property valuation vs declared value / purchase price, LTV discrepancies
2. income_tax               - income and tax-return reconciliation over 3-5 financial years
3. terms_conditions         - mortgage terms, required clauses, missing clauses and numeric inconsistencies

Outputs are review aids with evidence; they are not credit decisions.
"""
import re
from app.services.calculations import emi_monthly, estimate_metrics, format_inr

SCENARIOS = ("valuation_ltv", "income_tax", "terms_conditions")
TERMS_CATEGORIES = ("Loan Agreement", "Terms / Disclosure", "Sale / Purchase Agreement")

def _f(code, severity, message, **evidence):
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}

def _pct_diff(a, b):
    """Relative difference of a from b in percent (b is the reference)."""
    return None if not b else (a - b) / b * 100

# ---------------------------------------------------------------- 1. valuation / LTV
def valuation_ltv(declared_property_value=0, requested_loan=0, valuation_amount=None, purchase_price=None, max_ltv_percent=None, tolerance_percent=5.0):
    vals = {k: float(v) for k, v in (("declared", declared_property_value), ("valuation", valuation_amount), ("purchase_price", purchase_price)) if v and float(v) > 0}
    findings, metrics = [], {}
    if requested_loan <= 0: findings.append(_f("NO_LOAN_AMOUNT", "high", "Requested loan amount is missing or zero; LTV cannot be computed."))
    if not vals: findings.append(_f("NO_VALUE_EVIDENCE", "high", "No property value, valuation or purchase price supplied."))
    for k, v in vals.items():
        if requested_loan > 0: metrics[f"ltv_on_{k}_percent"] = round(requested_loan / v * 100, 2)
    names = list(vals)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            hi, lo = (a, b) if vals[a] >= vals[b] else (b, a)
            diff = _pct_diff(vals[hi], vals[lo])
            if diff is not None and diff > tolerance_percent:
                findings.append(_f("VALUE_DISCREPANCY", "high" if diff > 2 * tolerance_percent else "medium",
                    f"{hi.replace('_', ' ')} ({format_inr(vals[hi])}) exceeds {lo.replace('_', ' ')} ({format_inr(vals[lo])}) by {diff:.1f}% (tolerance {tolerance_percent:g}%).",
                    higher=hi, lower=lo, difference_inr=round(vals[hi] - vals[lo], 2), difference_percent=round(diff, 2)))
    basis = None
    if vals:
        basis = min(vals, key=vals.get)  # conservative: the lowest evidenced value
        metrics["lending_value_basis"] = basis
        metrics["lending_value_inr"] = vals[basis]
        if requested_loan > 0:
            ltv = requested_loan / vals[basis] * 100
            metrics["ltv_percent"] = round(ltv, 2)
            if ltv > 100: findings.append(_f("LOAN_EXCEEDS_VALUE", "high", f"Loan {format_inr(requested_loan)} exceeds the lowest evidenced value {format_inr(vals[basis])} (LTV {ltv:.2f}%).", ltv_percent=round(ltv, 2)))
            if max_ltv_percent:
                metrics["max_ltv_percent"] = float(max_ltv_percent)
                if ltv > max_ltv_percent:
                    findings.append(_f("LTV_ABOVE_LIMIT", "high", f"LTV {ltv:.2f}% on {basis.replace('_', ' ')} exceeds the supplied limit {max_ltv_percent:g}%. Maximum loan at this limit: {format_inr(vals[basis] * max_ltv_percent / 100)}.", ltv_percent=round(ltv, 2), limit_percent=float(max_ltv_percent), max_loan_inr=round(vals[basis] * max_ltv_percent / 100, 2)))
            else: findings.append(_f("NO_LTV_LIMIT_SUPPLIED", "info", "No lender LTV limit was supplied, so no pass/fail on LTV was made. Enter the limit from the approved policy."))
    if "valuation" not in vals: findings.append(_f("NO_INDEPENDENT_VALUATION", "medium", "No independent valuation amount supplied; LTV relies on declared/purchase values."))
    return {"scenario": "valuation_ltv", "metrics": metrics, "findings": findings}

# ---------------------------------------------------------------- 2. income / tax
def income_tax(years, declared_annual_income=0, tolerance_percent=10.0, swing_percent=30.0, min_years=3, max_years=5):
    """years: [{year, itr_total_income, salary_income, bank_credits}] (annual INR, any may be missing)."""
    findings, rows = [], []
    for y in years or []:
        rows.append({"year": str(y.get("year", "")).strip(), **{k: (float(y[k]) if y.get(k) not in (None, "") else None) for k in ("itr_total_income", "salary_income", "bank_credits")}})
    rows.sort(key=lambda r: r["year"])
    if len(rows) < min_years: findings.append(_f("INSUFFICIENT_HISTORY", "high", f"{len(rows)} year(s) supplied; at least {min_years} are needed for reconciliation."))
    if len(rows) > max_years: findings.append(_f("EXCESS_HISTORY", "info", f"{len(rows)} years supplied; only the latest {max_years} are analysed.")); rows = rows[-max_years:]
    primary = []
    for r in rows:
        srcs = {k: r[k] for k in ("itr_total_income", "salary_income", "bank_credits") if r[k] is not None}
        if not srcs: findings.append(_f("NO_FIGURES", "medium", f"{r['year']}: no figures supplied.", year=r["year"]));primary.append(None);continue
        primary.append(r["itr_total_income"] if r["itr_total_income"] is not None else r["salary_income"] if r["salary_income"] is not None else r["bank_credits"])
        names = list(srcs)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = srcs[names[i]], srcs[names[j]];hi = max(a, b)
                v = abs(a - b) / hi * 100 if hi else 0
                if v > tolerance_percent: findings.append(_f("SOURCE_MISMATCH", "high" if v > 2 * tolerance_percent else "medium", f"{r['year']}: {names[i]} ({format_inr(a)}) and {names[j]} ({format_inr(b)}) differ by {v:.1f}% (tolerance {tolerance_percent:g}%).", year=r["year"], sources=[names[i], names[j]], variance_percent=round(v, 2)))
        if r["itr_total_income"] is None: findings.append(_f("NO_ITR_FOR_YEAR", "medium", f"{r['year']}: no tax-return income supplied.", year=r["year"]))
    series = [(r["year"], p) for r, p in zip(rows, primary) if p is not None]
    for (y0, p0), (y1, p1) in zip(series, series[1:]):
        ch = _pct_diff(p1, p0)
        if ch is not None and abs(ch) > swing_percent: findings.append(_f("YOY_SWING", "medium", f"Income moved {ch:+.1f}% from {y0} ({format_inr(p0)}) to {y1} ({format_inr(p1)}); exceeds {swing_percent:g}% swing threshold.", from_year=y0, to_year=y1, change_percent=round(ch, 2)))
    metrics = {"years_analyzed": len(rows)}
    if series:
        vals = [p for _, p in series]
        metrics.update({"latest_year": series[-1][0], "latest_income_inr": vals[-1], "average_income_inr": round(sum(vals) / len(vals), 2)})
        if declared_annual_income and declared_annual_income > 0:
            metrics["declared_annual_income_inr"] = float(declared_annual_income)
            over = _pct_diff(declared_annual_income, vals[-1])
            if over is not None and over > tolerance_percent: findings.append(_f("DECLARED_EXCEEDS_EVIDENCE", "high", f"Declared annual income {format_inr(declared_annual_income)} is {over:.1f}% above the latest evidenced income {format_inr(vals[-1])}.", over_percent=round(over, 2)))
            avg = metrics["average_income_inr"];overavg = _pct_diff(declared_annual_income, avg)
            if overavg is not None and overavg > tolerance_percent: findings.append(_f("DECLARED_EXCEEDS_AVERAGE", "medium", f"Declared annual income is {overavg:.1f}% above the {len(vals)}-year average {format_inr(avg)}.", over_percent=round(overavg, 2)))
    return {"scenario": "income_tax", "metrics": metrics, "years": rows, "findings": findings}

# ---------------------------------------------------------------- 3. terms & conditions
REQUIRED_CLAUSES = {
    "loan_amount": r"loan amount|sanctioned amount|principal amount|facility amount|amount of (?:the )?loan",
    "interest_rate": r"interest rate|rate of interest|\bROI\b|per annum|p\.a\.",
    "rate_type_and_reset": r"floating|fixed rate|\brepo\b|\bMCLR\b|\bEBLR\b|benchmark|rate reset|reset",
    "tenure": r"tenure|term of the loan|repayment period|loan term",
    "repayment_emi": r"\bEMI\b|equated monthly|repayment schedule|instal+ment",
    "prepayment_foreclosure": r"pre-?payment|fore-?closure|pre-?closure",
    "penal_default_charges": r"penal|default interest|late payment|overdue|delinquen",
    "fees_and_charges": r"processing fee|administrative (?:fee|charge)|legal (?:fee|charge)|valuation fee|charges",
    "security_collateral": r"security|collateral|mortgage of|equitable mortgage|charge (?:over|on)|hypothecat",
    "insurance": r"insurance",
    "events_of_default_recall": r"events? of default|recall|accelerat",
    "governing_law_jurisdiction": r"governing law|jurisdiction|arbitration|courts? (?:at|of)",
}
_AMT = re.compile(r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?)?", re.I)
_PCT = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*(?:%|percent|per cent)", re.I)
_TEN = re.compile(r"(\d{1,3})\s*(years?|yrs?|months?)", re.I)

def parse_amounts(text):
    out = []
    for m in _AMT.finditer(text or ""):
        v = float(m.group(1).replace(",", ""));u = (m.group(2) or "").lower()
        v *= 10_000_000 if u.startswith("cr") else 100_000 if u.startswith(("lakh", "lac")) else 1
        out.append((v, m.start()))
    return out

def _classified(text, items, groups, window=60, exclude_rate=None):
    """Assign each (value,pos) to the group whose keyword ends closest before it (within `window` chars)."""
    out = {g: [] for g in groups}
    for v, pos in items:
        ctx = text[max(0, pos - window):pos];best, best_end = None, -1
        for g, pat in groups.items():
            for m in re.finditer(pat, ctx, re.I):
                if m.end() > best_end: best, best_end = g, m.end()
        if best and not (exclude_rate and best == "rate" and re.search(exclude_rate, ctx, re.I)): out[best].append(v)
    return {g: sorted(set(vs)) for g, vs in out.items()}

def terms_conditions(text, application=None, tolerance_percent=0.5):
    text = text or "";application = application or {};findings = []
    if not text.strip(): return {"scenario": "terms_conditions", "metrics": {}, "clauses": {}, "findings": [_f("NO_TEXT", "high", "No agreement/terms text available. Upload and extract a Loan Agreement or Terms / Disclosure document.")]}
    clauses = {}
    for name, pat in REQUIRED_CLAUSES.items():
        m = re.search(pat, text, re.I);clauses[name] = {"present": bool(m), "snippet": text[max(0, m.start() - 40):m.end() + 60].replace("\n", " ").strip() if m else None}
        if not m: findings.append(_f("MISSING_CLAUSE", "high" if name in ("interest_rate", "tenure", "loan_amount", "prepayment_foreclosure", "penal_default_charges") else "medium", f"No reference found to: {name.replace('_', ' ')}.", clause=name))
    by_amt = _classified(text, parse_amounts(text), {"loan": r"loan amount|sanctioned|sanction|principal|facility|amount of (?:the )?loan", "emi": r"\bEMI\b|equated monthly|instal+ment"})
    by_pct = _classified(text, [(float(m.group(1)), m.start()) for m in _PCT.finditer(text)], {"rate": r"interest|rate of|\bROI\b|\brate\b"}, exclude_rate=r"penal|processing|\bfees?\b|default|overdue|late|charge|prepay|fore-?clos|margin|spread|repo\s*\+")
    by_ten = _classified(text, [(float(m.group(1)) * (12 if m.group(2).lower().startswith("y") else 1), m.start()) for m in _TEN.finditer(text)], {"tenure": r"tenure|term|period|repay"})
    rates, tenures, loans, emis = by_pct["rate"], by_ten["tenure"], by_amt["loan"], by_amt["emi"]
    metrics = {"interest_rates_found_percent": rates, "tenures_found_months": tenures, "loan_amounts_found_inr": loans, "emi_amounts_found_inr": emis}
    if len(rates) > 1: findings.append(_f("MULTIPLE_RATES", "medium", f"Several interest-rate values near rate wording: {rates}. Confirm which is the contractual rate (some may be penal/benchmark rates).", values=rates))
    if len(tenures) > 1: findings.append(_f("MULTIPLE_TENURES", "medium", f"Several tenure values found (months): {tenures}.", values=tenures))
    if len(loans) > 1: findings.append(_f("MULTIPLE_LOAN_AMOUNTS", "high", f"Different loan amounts stated: {', '.join(format_inr(x) for x in loans)}.", values=loans))
    app_loan, app_rate, app_ten = application.get("requested_loan") or 0, application.get("interest_rate"), application.get("tenure_years")
    if loans and app_loan and not any(abs(x - app_loan) / app_loan * 100 <= tolerance_percent for x in loans): findings.append(_f("LOAN_AMOUNT_MISMATCH", "high", f"Agreement loan amount(s) {', '.join(format_inr(x) for x in loans)} do not match the application request {format_inr(app_loan)}.", agreement=loans, application=app_loan))
    if rates and app_rate is not None and not any(abs(x - app_rate) < 0.01 for x in rates): findings.append(_f("RATE_MISMATCH", "medium", f"Agreement rate(s) {rates}% do not match the application rate {app_rate}%.", agreement=rates, application=app_rate))
    if tenures and app_ten and not any(abs(x - app_ten * 12) < 0.5 for x in tenures): findings.append(_f("TENURE_MISMATCH", "medium", f"Agreement tenure(s) {tenures} months do not match the application tenure {app_ten * 12} months.", agreement=tenures, application=app_ten * 12))
    if len(loans) == 1 and len(rates) == 1 and len(tenures) == 1 and len(emis) == 1:
        calc = emi_monthly(loans[0], rates[0], tenures[0] / 12);metrics["recomputed_emi_inr"] = calc
        if calc and abs(emis[0] - calc) / calc * 100 > 1.0: findings.append(_f("EMI_MISMATCH", "high", f"Stated EMI {format_inr(emis[0])} differs from recomputed EMI {format_inr(calc)} for {format_inr(loans[0])} at {rates[0]}% over {tenures[0] / 12:g} years.", stated=emis[0], recomputed=calc))
    return {"scenario": "terms_conditions", "metrics": metrics, "clauses": clauses, "findings": findings}

# ---------------------------------------------------------------- dispatcher
def run_scenario(name, application, doc_texts, inputs):
    """application: dict of application fields; doc_texts: {category: [text,...]}; inputs: dict of user-entered figures."""
    inputs = inputs or {}
    if name == "valuation_ltv":
        r = valuation_ltv(application.get("property_value") or 0, application.get("requested_loan") or 0, inputs.get("valuation_amount"), inputs.get("purchase_price"), inputs.get("max_ltv_percent"), inputs.get("tolerance_percent") or 5.0)
    elif name == "income_tax":
        r = income_tax(inputs.get("income_years") or [], application.get("annual_income") or 0, inputs.get("tolerance_percent") or 10.0)
    elif name == "terms_conditions":
        text = inputs.get("terms_text") or "\n\n".join(t for c in TERMS_CATEGORIES for t in doc_texts.get(c, []))
        r = terms_conditions(text, application)
    else:
        raise ValueError(f"Unknown scenario '{name}'. Use one of {SCENARIOS}.")
    r["calculations"] = estimate_metrics(application.get("property_value") or 0, application.get("requested_loan") or 0, application.get("annual_income") or 0, application.get("monthly_debt") or 0, application.get("interest_rate") or 0, application.get("tenure_years") or 1)
    r["disclaimer"] = "Deterministic review aid. Not a credit decision; a human reviewer must verify against source documents."
    return r
