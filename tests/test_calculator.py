from datetime import date

import pytest

from bondcalc import Bond, analyze_bond, build_cashflow_schedule, price_bond, risk_metrics, solve_ytm
from bondcalc.calculator import BondInputError


def test_par_bond_prices_at_face():
    # coupon == yield -> price == face value, for any frequency
    for freq in (1, 2, 4, 12):
        bond = Bond(face_value=1000, coupon_rate=0.05, years_to_maturity=10, frequency=freq)
        assert price_bond(bond, 0.05) == pytest.approx(1000, abs=1e-6)


def test_textbook_discount_bond():
    # 8% semi-annual coupon, 10 years, 10% yield -> classic $875.38 answer
    bond = Bond(face_value=1000, coupon_rate=0.08, years_to_maturity=10, frequency=2)
    assert price_bond(bond, 0.10) == pytest.approx(875.38, abs=0.01)


def test_zero_coupon_bond():
    bond = Bond(face_value=1000, coupon_rate=0.0, years_to_maturity=10, frequency=1)
    assert price_bond(bond, 0.05) == pytest.approx(1000 / 1.05**10)
    # a zero's Macaulay duration is just its maturity
    assert risk_metrics(bond, 0.05)["macaulay_duration"] == pytest.approx(10.0)


def test_schedule_shape_and_totals():
    bond = Bond(face_value=1000, coupon_rate=0.06, years_to_maturity=3, frequency=2)
    df = build_cashflow_schedule(bond)
    assert len(df) == 6
    assert list(df["period"]) == [1, 2, 3, 4, 5, 6]
    assert (df["coupon"] == 30.0).all()
    assert df["principal"].iloc[:-1].eq(0).all()
    assert df["principal"].iloc[-1] == 1000
    assert df["cash_flow"].sum() == pytest.approx(6 * 30 + 1000)
    assert df["cumulative_cash_flow"].iloc[-1] == pytest.approx(1180)


def test_schedule_payment_dates():
    bond = Bond(1000, 0.05, 1, frequency=4, start_date=date(2026, 1, 15))
    df = build_cashflow_schedule(bond)
    assert list(df["payment_date"]) == [
        date(2026, 4, 15),
        date(2026, 7, 15),
        date(2026, 10, 15),
        date(2027, 1, 15),
    ]


def test_ytm_round_trips_through_price():
    bond = Bond(face_value=1000, coupon_rate=0.045, years_to_maturity=7, frequency=2)
    for y in (0.01, 0.045, 0.09):
        assert solve_ytm(bond, price_bond(bond, y)) == pytest.approx(y, abs=1e-8)


def test_premium_discount_labels():
    bond = Bond(1000, 0.05, 5, frequency=2)
    assert analyze_bond(bond, ytm=0.03)["summary"]["trading_at"] == "premium"
    assert analyze_bond(bond, ytm=0.05)["summary"]["trading_at"] == "par"
    assert analyze_bond(bond, ytm=0.07)["summary"]["trading_at"] == "discount"


def test_modified_duration_matches_price_sensitivity():
    # modified duration should approximate -(dP/P) / dy for a small yield bump
    bond = Bond(1000, 0.05, 10, frequency=2)
    y, dy = 0.05, 1e-5
    p0 = price_bond(bond, y)
    numeric = -(price_bond(bond, y + dy) - price_bond(bond, y - dy)) / (2 * dy) / p0
    assert risk_metrics(bond, y)["modified_duration"] == pytest.approx(numeric, rel=1e-5)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(face_value=0, coupon_rate=0.05, years_to_maturity=5),
        dict(face_value=1000, coupon_rate=-0.01, years_to_maturity=5),
        dict(face_value=1000, coupon_rate=0.05, years_to_maturity=0),
        dict(face_value=1000, coupon_rate=0.05, years_to_maturity=5, frequency=3),
        dict(face_value=1000, coupon_rate=0.05, years_to_maturity=2.3, frequency=2),
    ],
)
def test_bad_inputs_raise(kwargs):
    with pytest.raises(BondInputError):
        Bond(**kwargs)


def test_analyze_requires_exactly_one_of_ytm_or_price():
    bond = Bond(1000, 0.05, 5)
    with pytest.raises(BondInputError):
        analyze_bond(bond)
    with pytest.raises(BondInputError):
        analyze_bond(bond, ytm=0.05, price=1000)
