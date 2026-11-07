from app.services.calculations import emi_monthly, estimate_metrics

def test_zero_rate():
    assert emi_monthly(120000, 0, 10) == 1000

def test_regular_emi_is_positive():
    assert 17000 < emi_monthly(2_000_000, 8.5, 20) < 18000

def test_metrics_are_estimates():
    m = estimate_metrics(5_000_000, 3_000_000, 1_200_000, 10000, 8.5, 20)
    assert m["loan_to_value_percent"] == 60
    assert m["estimated_monthly_emi_inr"] > 0
    assert "not a credit decision" in m["disclaimer"]
