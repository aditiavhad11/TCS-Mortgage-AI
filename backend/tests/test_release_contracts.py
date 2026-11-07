from app.services.calculations import emi_monthly, estimate_metrics

def test_emi_zero_rate_is_principal_over_months():
    assert emi_monthly(120000, 0, 10) == 1000.00

def test_ltv_is_percent():
    result = estimate_metrics(1000000, 500000, 600000, 0, 8.5, 20)
    assert result["loan_to_value_percent"] == 50.00

def test_dti_includes_existing_debt_and_emi():
    result = estimate_metrics(1000000, 500000, 600000, 5000, 0, 10)
    # EMI at 0% over 120 months = 500000/120 = 4166.67; (5000 + 4166.67) / 50000 monthly income = 18.33%
    assert result["debt_to_income_percent"] == 18.33
