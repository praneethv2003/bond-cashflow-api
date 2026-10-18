"""
Core bond math, built on pandas.

Everything here works on a plain-vanilla fixed-coupon bond that pays coupons
`frequency` times a year and returns face value at maturity. Pricing assumes
we're standing on a coupon date (so no accrued interest / dirty price).

The main entry point is `analyze_bond`, which the Flask layer calls. The
smaller functions are exposed too so they can be tested on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

VALID_FREQUENCIES = {1: "annual", 2: "semi-annual", 4: "quarterly", 12: "monthly"}


class BondInputError(ValueError):
    """Raised when bond parameters don't make sense."""


@dataclass(frozen=True)
class Bond:
    face_value: float
    coupon_rate: float          # annual rate as a decimal, 0.05 == 5%
    years_to_maturity: float
    frequency: int = 2          # coupon payments per year
    start_date: Optional[date] = None  # if given, payment dates get filled in

    def __post_init__(self):
        if self.face_value <= 0:
            raise BondInputError("face_value must be positive")
        if self.coupon_rate < 0:
            raise BondInputError("coupon_rate can't be negative")
        if self.years_to_maturity <= 0:
            raise BondInputError("years_to_maturity must be positive")
        if self.frequency not in VALID_FREQUENCIES:
            raise BondInputError(
                f"frequency must be one of {sorted(VALID_FREQUENCIES)} "
                "(annual, semi-annual, quarterly, monthly)"
            )
        periods = self.years_to_maturity * self.frequency
        if abs(periods - round(periods)) > 1e-9:
            raise BondInputError(
                "years_to_maturity * frequency has to be a whole number of "
                f"coupon periods (got {periods:g})"
            )

    @property
    def n_periods(self) -> int:
        return int(round(self.years_to_maturity * self.frequency))

    @property
    def coupon_payment(self) -> float:
        return self.face_value * self.coupon_rate / self.frequency


def build_cashflow_schedule(bond: Bond, ytm: Optional[float] = None) -> pd.DataFrame:
    """
    Return one row per coupon period.

    Always includes: period, years, coupon, principal, cash_flow, cumulative_cash_flow.
    If `ytm` is given, also adds discount_factor and present_value.
    If the bond has a start_date, adds payment_date.
    """
    periods = np.arange(1, bond.n_periods + 1)

    df = pd.DataFrame({"period": periods})
    df["years"] = df["period"] / bond.frequency
    df["coupon"] = bond.coupon_payment
    df["principal"] = 0.0
    df.loc[df.index[-1], "principal"] = float(bond.face_value)
    df["cash_flow"] = df["coupon"] + df["principal"]
    df["cumulative_cash_flow"] = df["cash_flow"].cumsum()

    if bond.start_date is not None:
        months_per_period = 12 // bond.frequency
        start = pd.Timestamp(bond.start_date)
        df["payment_date"] = [
            (start + pd.DateOffset(months=int(p) * months_per_period)).date()
            for p in df["period"]
        ]

    if ytm is not None:
        periodic_rate = ytm / bond.frequency
        df["discount_factor"] = (1 + periodic_rate) ** (-df["period"])
        df["present_value"] = df["cash_flow"] * df["discount_factor"]

    return df


def price_bond(bond: Bond, ytm: float) -> float:
    """Clean price = sum of discounted cash flows at the given annual yield."""
    if ytm <= -1:
        raise BondInputError("ytm must be greater than -100%")
    df = build_cashflow_schedule(bond, ytm)
    return float(df["present_value"].sum())


def solve_ytm(bond: Bond, price: float, tol: float = 1e-10, max_iter: int = 200) -> float:
    """
    Find the annual yield that makes the PV of cash flows equal `price`.

    Price is strictly decreasing in yield, so bisection is safe and always
    converges. Searches between -99% and 1000%, which covers anything sane.
    """
    if price <= 0:
        raise BondInputError("price must be positive")

    lo, hi = -0.99, 10.0
    if price_bond(bond, lo) < price:
        raise BondInputError("price is too high to be matched by any yield above -99%")
    if price_bond(bond, hi) > price:
        raise BondInputError("price is too low to be matched by any yield below 1000%")

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        if price_bond(bond, mid) > price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def risk_metrics(bond: Bond, ytm: float) -> dict:
    """Macaulay duration, modified duration, convexity, DV01, current yield."""
    df = build_cashflow_schedule(bond, ytm)
    price = df["present_value"].sum()
    f = bond.frequency
    periodic_rate = ytm / f

    weights = df["present_value"] / price
    macaulay = float((weights * df["years"]).sum())
    modified = macaulay / (1 + periodic_rate)

    # Standard convexity formula for a bond compounding f times a year
    k = df["period"]
    convexity_sum = (df["cash_flow"] * k * (k + 1) / (1 + periodic_rate) ** (k + 2)).sum()
    convexity = float(convexity_sum / (price * f**2))

    dv01 = modified * price * 0.0001
    current_yield = (bond.face_value * bond.coupon_rate) / price if price else float("nan")

    return {
        "macaulay_duration": macaulay,
        "modified_duration": float(modified),
        "convexity": convexity,
        "dv01": float(dv01),
        "current_yield": float(current_yield),
    }


def analyze_bond(
    bond: Bond,
    ytm: Optional[float] = None,
    price: Optional[float] = None,
) -> dict:
    """
    Full analysis. Give either a yield (we solve for price) or a price
    (we solve for yield). Returns a dict ready to be turned into JSON,
    plus the schedule DataFrame under the "schedule" key.
    """
    if ytm is None and price is None:
        raise BondInputError("provide either ytm or price")
    if ytm is not None and price is not None:
        raise BondInputError("provide ytm or price, not both")

    if ytm is None:
        ytm = solve_ytm(bond, price)
    else:
        if ytm <= -1:
            raise BondInputError("ytm must be greater than -100%")
        price = price_bond(bond, ytm)

    schedule = build_cashflow_schedule(bond, ytm)
    metrics = risk_metrics(bond, ytm)

    if abs(price - bond.face_value) < 1e-6:
        trading_at = "par"
    elif price > bond.face_value:
        trading_at = "premium"
    else:
        trading_at = "discount"

    summary = {
        "face_value": bond.face_value,
        "coupon_rate": bond.coupon_rate,
        "years_to_maturity": bond.years_to_maturity,
        "frequency": bond.frequency,
        "frequency_label": VALID_FREQUENCIES[bond.frequency],
        "n_periods": bond.n_periods,
        "coupon_payment": bond.coupon_payment,
        "ytm": float(ytm),
        "price": float(price),
        "trading_at": trading_at,
        "total_coupons": float(schedule["coupon"].sum()),
        "total_cash_flow": float(schedule["cash_flow"].sum()),
        **metrics,
    }

    return {"summary": summary, "schedule": schedule}
