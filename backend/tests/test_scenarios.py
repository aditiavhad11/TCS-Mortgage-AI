from app.services.calculations import format_inr, emi_monthly, estimate_metrics
from app.services.scenarios import valuation_ltv, income_tax, terms_conditions, run_scenario, parse_amounts

def codes(r): return {f["code"] for f in r["findings"]}

def test_format_inr_indian_grouping():
    assert format_inr(1234567) == "₹12,34,567"
    assert format_inr(999) == "₹999"
    assert format_inr(100000) == "₹1,00,000"
    assert format_inr(12345678.5, 2) == "₹1,23,45,678.50"
    assert format_inr(-250000) == "-₹2,50,000"
    assert format_inr(None) == "—"

def test_emi_known_value():
    # 50,00,000 at 8.5% for 20 years -> 43,391.16 (standard EMI formula)
    assert abs(emi_monthly(5_000_000, 8.5, 20) - 43391.16) < 0.5

def test_dti_ltv_values():
    m = estimate_metrics(5_000_000, 4_000_000, 1_200_000, 10_000, 0, 10)
    assert m["loan_to_value_percent"] == 80.0
    assert m["debt_to_income_percent"] == round((10_000 + 4_000_000 / 120) / 100_000 * 100, 2)

def test_valuation_discrepancy_and_ltv_limit():
    r = valuation_ltv(declared_property_value=5_000_000, requested_loan=4_200_000, valuation_amount=4_300_000, purchase_price=4_800_000, max_ltv_percent=80)
    assert r["metrics"]["lending_value_basis"] == "valuation"
    assert r["metrics"]["ltv_percent"] == round(4_200_000 / 4_300_000 * 100, 2)
    assert {"VALUE_DISCREPANCY", "LTV_ABOVE_LIMIT"} <= codes(r)

def test_valuation_clean_case_and_no_limit_note():
    r = valuation_ltv(5_000_000, 3_000_000, 5_000_000, 5_000_000, None)
    assert "VALUE_DISCREPANCY" not in codes(r) and "NO_LTV_LIMIT_SUPPLIED" in codes(r) and r["metrics"]["ltv_percent"] == 60.0

def test_valuation_loan_exceeds_value():
    assert "LOAN_EXCEEDS_VALUE" in codes(valuation_ltv(1_000_000, 1_200_000, 1_000_000, None, 80))

def test_income_reconciliation_multi_year():
    years = [{"year": "FY2021-22", "itr_total_income": 1_000_000, "bank_credits": 980_000},
             {"year": "FY2022-23", "itr_total_income": 1_100_000, "salary_income": 1_090_000},
             {"year": "FY2023-24", "itr_total_income": 1_800_000, "salary_income": 1_150_000}]
    r = income_tax(years, declared_annual_income=2_000_000)
    c = codes(r)
    assert {"SOURCE_MISMATCH", "YOY_SWING", "DECLARED_EXCEEDS_EVIDENCE"} <= c
    assert r["metrics"]["years_analyzed"] == 3 and r["metrics"]["latest_income_inr"] == 1_800_000
    assert r["metrics"]["average_income_inr"] == round((1_000_000 + 1_100_000 + 1_800_000) / 3, 2)

def test_income_needs_three_years():
    assert "INSUFFICIENT_HISTORY" in codes(income_tax([{"year": "FY2023-24", "itr_total_income": 900000}], 900000))

def test_income_limits_to_five_years():
    ys = [{"year": f"FY{2015+i}", "itr_total_income": 1_000_000} for i in range(7)]
    r = income_tax(ys, 1_000_000)
    assert r["metrics"]["years_analyzed"] == 5 and "EXCESS_HISTORY" in codes(r)

AGREEMENT = """LOAN AGREEMENT. Loan amount: Rs. 40,00,000 sanctioned to the borrower. Interest rate 9.0% per annum, floating, linked to repo.
Tenure: 20 years. EMI: Rs. 35,989. Prepayment and foreclosure permitted. Penal interest of 2% on overdue amounts.
Processing fee 0.5%. Security: equitable mortgage of the property. Insurance is mandatory. Events of default: non-payment.
Governing law: Indian law, courts at Mumbai."""

def test_terms_complete_agreement_has_no_missing_clauses():
    r = terms_conditions(AGREEMENT, {"requested_loan": 4_000_000, "interest_rate": 9.0, "tenure_years": 20})
    assert "MISSING_CLAUSE" not in codes(r)
    assert r["metrics"]["loan_amounts_found_inr"] == [4_000_000.0]

def test_terms_stated_emi_matches_recomputation():
    r = terms_conditions(AGREEMENT, {"requested_loan": 4_000_000, "interest_rate": 9.0, "tenure_years": 20})
    assert "EMI_MISMATCH" not in codes(r) and abs(r["metrics"]["recomputed_emi_inr"] - 35989) < 2

def test_terms_detects_missing_and_mismatched():
    text = "Loan amount Rs. 50,00,000. Interest rate 10.5% per annum. Tenure 15 years. EMI Rs. 40,000."
    r = terms_conditions(text, {"requested_loan": 4_000_000, "interest_rate": 9.0, "tenure_years": 20})
    c = codes(r)
    assert {"MISSING_CLAUSE", "LOAN_AMOUNT_MISMATCH", "RATE_MISMATCH", "TENURE_MISMATCH", "EMI_MISMATCH"} <= c
    missing = {f["evidence"]["clause"] for f in r["findings"] if f["code"] == "MISSING_CLAUSE"}
    assert {"prepayment_foreclosure", "penal_default_charges", "governing_law_jurisdiction"} <= missing

def test_terms_no_text():
    assert "NO_TEXT" in codes(terms_conditions("", {}))

def test_parse_amounts_lakh_crore():
    assert [a for a, _ in parse_amounts("Rs 45 lakh and INR 1.2 crore and ₹ 4,500,000")] == [4_500_000.0, 12_000_000.0, 4_500_000.0]

def test_run_scenario_dispatch_and_unknown():
    app = {"property_value": 5_000_000, "requested_loan": 4_000_000, "annual_income": 1_200_000, "monthly_debt": 0, "interest_rate": 9.0, "tenure_years": 20}
    r = run_scenario("terms_conditions", app, {"Loan Agreement": [AGREEMENT]}, {})
    assert r["scenario"] == "terms_conditions" and r["calculations"]["loan_to_value_percent"] == 80.0
    import pytest
    with pytest.raises(ValueError): run_scenario("nope", app, {}, {})
