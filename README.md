# Bond Cash-Flow Calculator API

A small Flask REST API that builds the full cash-flow schedule for a fixed-coupon bond and prices it. All the math runs on pandas DataFrames: discount factors, present values, yield-to-maturity (bisection solver), Macaulay/modified duration, convexity, and DV01.

Give it a yield and it tells you the price. Give it a price and it solves for the yield. Either way you get the period-by-period schedule back as JSON or CSV.

## Stack

- **Python 3.10+**
- **Flask** – REST API, app-factory + blueprint layout, JSON error handling
- **pandas / NumPy** – vectorized cash-flow schedule and pricing math
- **pytest** – 26 tests covering the math (checked against textbook values) and every endpoint

## Quick start

```bash
git clone https://github.com/praneethv2003/bond-cashflow-api.git
cd bond-cashflow-api
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                    # serves on http://127.0.0.1:5000
```

Run the tests:

```bash
pytest
```

## Endpoints

| Method | Path                 | What it does                                                   |
| ------ | -------------------- | -------------------------------------------------------------- |
| GET    | `/health`            | Liveness check                                                 |
| POST   | `/api/cashflows`     | Full schedule + summary. Pass `ytm` **or** `price`. `?format=csv` returns a CSV download |
| POST   | `/api/price`         | Price and risk metrics from a yield (no schedule)              |
| POST   | `/api/ytm`           | Yield to maturity and risk metrics from a price (no schedule)  |

### Request body

| Field               | Type   | Required | Notes                                              |
| ------------------- | ------ | -------- | -------------------------------------------------- |
| `face_value`        | number | yes      | Par value, e.g. `1000`                             |
| `coupon_rate`       | number | yes      | Annual rate as a decimal: `0.05` = 5%              |
| `years_to_maturity` | number | yes      | Must line up with `frequency` to a whole number of periods |
| `frequency`         | int    | no       | Coupons per year: `1`, `2` (default), `4`, or `12` |
| `ytm`               | number | one of   | Annual yield as a decimal                          |
| `price`             | number | one of   | Market price; the API solves for yield             |
| `start_date`        | string | no       | `YYYY-MM-DD`; adds a `payment_date` column         |

### Example

Price an 8% semi-annual 10-year bond at a 10% yield:

```bash
curl -X POST http://127.0.0.1:5000/api/price \
  -H "Content-Type: application/json" \
  -d '{"face_value": 1000, "coupon_rate": 0.08, "years_to_maturity": 10, "frequency": 2, "ytm": 0.10}'
```

```json
{
  "price": 875.377897,
  "ytm": 0.1,
  "trading_at": "discount",
  "macaulay_duration": 6.840368,
  "modified_duration": 6.514637,
  "convexity": 56.485036,
  "dv01": 0.570277,
  "current_yield": 0.091389,
  "coupon_payment": 40.0,
  "n_periods": 20,
  "total_coupons": 800.0,
  "total_cash_flow": 1800.0,
  ...
}
```

Get the schedule with payment dates:

```bash
curl -X POST http://127.0.0.1:5000/api/cashflows \
  -H "Content-Type: application/json" \
  -d '{"face_value": 1000, "coupon_rate": 0.05, "years_to_maturity": 2, "frequency": 2, "ytm": 0.06, "start_date": "2026-01-15"}'
```

```json
{
  "summary": { "price": 981.414508, "ytm": 0.06, "trading_at": "discount", ... },
  "schedule": [
    {"period": 1, "years": 0.5, "payment_date": "2026-07-15", "coupon": 25.0, "principal": 0.0,
     "cash_flow": 25.0, "cumulative_cash_flow": 25.0, "discount_factor": 0.970874, "present_value": 24.271845},
    {"period": 2, "years": 1.0, "payment_date": "2027-01-15", "coupon": 25.0, "principal": 0.0, ...},
    {"period": 3, "years": 1.5, "payment_date": "2027-07-15", "coupon": 25.0, "principal": 0.0, ...},
    {"period": 4, "years": 2.0, "payment_date": "2028-01-15", "coupon": 25.0, "principal": 1000.0,
     "cash_flow": 1025.0, "cumulative_cash_flow": 1100.0, "discount_factor": 0.888487, "present_value": 910.699224}
  ]
}
```

Same thing as a CSV file (handy for dropping into Excel):

```bash
curl -X POST "http://127.0.0.1:5000/api/cashflows?format=csv" \
  -H "Content-Type: application/json" \
  -d '{"face_value": 1000, "coupon_rate": 0.05, "years_to_maturity": 2, "frequency": 2, "ytm": 0.06}' \
  -o bond_cashflows.csv
```

Bad input comes back as a 400 with a plain-English message:

```json
{"error": "years_to_maturity * frequency has to be a whole number of coupon periods (got 2.5)"}
```

## How the math works

For a bond with `n = years × frequency` periods and periodic rate `r = ytm / frequency`:

- **Cash flow** in period *k* is the coupon (`face × coupon_rate / frequency`), plus face value in the last period.
- **Discount factor** `DF_k = (1 + r)^-k`, **present value** `CF_k × DF_k`; **price** is the sum of PVs.
- **YTM** is found by bisection on the price function, which is strictly decreasing in yield so it always converges (tolerance 1e-10).
- **Macaulay duration** is the PV-weighted average time to cash flow; **modified duration** divides by `(1 + r)`.
- **Convexity** `= Σ CF_k · k(k+1) / (1+r)^(k+2) ÷ (price × frequency²)`.
- **DV01** `= modified duration × price × 0.0001`.

The schedule is one pandas DataFrame, so all of the above is a handful of column operations rather than loops. Pricing assumes settlement on a coupon date (clean price, no accrued interest).

## Project layout

```
bond-cashflow-api/
├── app.py                  # Flask app factory, blueprint, routes, error handlers
├── bondcalc/
│   ├── __init__.py
│   └── calculator.py       # Bond dataclass + all pandas math
├── tests/
│   ├── test_calculator.py  # math checked against textbook values
│   └── test_api.py         # Flask test-client tests for every endpoint
├── requirements.txt
├── pytest.ini
└── README.md
```

## Ideas for next steps

- Accrued interest / dirty price for settlement between coupon dates
- Day-count conventions (30/360, ACT/ACT)
- Floating-rate and amortizing bonds
- A small React front end that charts the schedule

## License

MIT
