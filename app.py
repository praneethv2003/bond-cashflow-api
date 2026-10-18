"""
Flask REST API for the bond cash-flow calculator.

Run locally:
    flask --app app run --debug
or:
    python app.py
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint, Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from bondcalc import Bond, analyze_bond
from bondcalc.calculator import BondInputError

api = Blueprint("api", __name__, url_prefix="/api")

ROUND_TO = 6


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise BondInputError("request body must be a JSON object")
    return body


def _num(body: dict, key: str, required: bool = True, default=None):
    """Pull a numeric field out of the body with a readable error if it's bad."""
    if key not in body or body[key] is None:
        if required:
            raise BondInputError(f"missing required field: {key}")
        return default
    try:
        return float(body[key])
    except (TypeError, ValueError):
        raise BondInputError(f"{key} must be a number")


def _bond_from_body(body: dict) -> Bond:
    frequency = body.get("frequency", 2)
    try:
        frequency = int(frequency)
    except (TypeError, ValueError):
        raise BondInputError("frequency must be an integer")

    start_date = None
    if body.get("start_date"):
        try:
            start_date = date.fromisoformat(str(body["start_date"]))
        except ValueError:
            raise BondInputError("start_date must be YYYY-MM-DD")

    return Bond(
        face_value=_num(body, "face_value"),
        coupon_rate=_num(body, "coupon_rate"),
        years_to_maturity=_num(body, "years_to_maturity"),
        frequency=frequency,
        start_date=start_date,
    )


def _round_summary(summary: dict) -> dict:
    return {k: (round(v, ROUND_TO) if isinstance(v, float) else v) for k, v in summary.items()}


def _schedule_records(schedule) -> list[dict]:
    df = schedule.copy()
    if "payment_date" in df.columns:
        df["payment_date"] = df["payment_date"].astype(str)
    num_cols = df.select_dtypes("number").columns
    df[num_cols] = df[num_cols].round(ROUND_TO)
    return df.to_dict(orient="records")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@api.post("/cashflows")
def cashflows():
    """
    Full cash-flow schedule plus summary. Pass either `ytm` or `price`.
    Add ?format=csv to download the schedule as a CSV file instead of JSON.
    """
    body = _get_json_body()
    bond = _bond_from_body(body)
    result = analyze_bond(
        bond,
        ytm=_num(body, "ytm", required=False),
        price=_num(body, "price", required=False),
    )

    if request.args.get("format", "json").lower() == "csv":
        csv_text = result["schedule"].to_csv(index=False, float_format=f"%.{ROUND_TO}f")
        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=bond_cashflows.csv"},
        )

    return jsonify(
        summary=_round_summary(result["summary"]),
        schedule=_schedule_records(result["schedule"]),
    )


@api.post("/price")
def price():
    """Price + risk metrics for a bond at a given yield (no schedule)."""
    body = _get_json_body()
    bond = _bond_from_body(body)
    result = analyze_bond(bond, ytm=_num(body, "ytm"))
    return jsonify(_round_summary(result["summary"]))


@api.post("/ytm")
def ytm():
    """Yield to maturity + risk metrics for a bond at a given price (no schedule)."""
    body = _get_json_body()
    bond = _bond_from_body(body)
    result = analyze_bond(bond, price=_num(body, "price"))
    return jsonify(_round_summary(result["summary"]))


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(api)

    @app.get("/")
    def index():
        return jsonify(
            name="bond-cashflow-api",
            endpoints={
                "GET /health": "liveness check",
                "POST /api/cashflows": "schedule + summary (ytm or price); ?format=csv for CSV",
                "POST /api/price": "price and risk metrics from a yield",
                "POST /api/ytm": "yield and risk metrics from a price",
            },
            note="rates are decimals: 0.05 means 5%",
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.errorhandler(BondInputError)
    def bad_input(err):
        return jsonify(error=str(err)), 400

    @app.errorhandler(HTTPException)
    def http_error(err):
        return jsonify(error=err.name, detail=err.description), err.code

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
