import pytest

from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


BOND = {"face_value": 1000, "coupon_rate": 0.05, "years_to_maturity": 5, "frequency": 2}


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_index_lists_endpoints(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "POST /api/cashflows" in res.get_json()["endpoints"]


def test_cashflows_json(client):
    res = client.post("/api/cashflows", json={**BOND, "ytm": 0.05})
    assert res.status_code == 200
    data = res.get_json()
    assert data["summary"]["price"] == pytest.approx(1000, abs=1e-4)
    assert data["summary"]["trading_at"] == "par"
    assert len(data["schedule"]) == 10
    assert data["schedule"][-1]["principal"] == 1000


def test_cashflows_with_dates(client):
    res = client.post("/api/cashflows", json={**BOND, "ytm": 0.05, "start_date": "2026-01-01"})
    assert res.status_code == 200
    assert res.get_json()["schedule"][0]["payment_date"] == "2026-07-01"


def test_cashflows_csv(client):
    res = client.post("/api/cashflows?format=csv", json={**BOND, "ytm": 0.05})
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    lines = res.get_data(as_text=True).strip().splitlines()
    assert lines[0].startswith("period,years,coupon,principal,cash_flow")
    assert len(lines) == 11  # header + 10 periods


def test_price_endpoint(client):
    res = client.post("/api/price", json={**BOND, "ytm": 0.07})
    assert res.status_code == 200
    body = res.get_json()
    assert body["price"] < 1000
    assert "modified_duration" in body
    assert "schedule" not in body


def test_ytm_endpoint(client):
    res = client.post("/api/ytm", json={**BOND, "price": 950})
    assert res.status_code == 200
    assert res.get_json()["ytm"] > 0.05


def test_missing_field_is_400(client):
    res = client.post("/api/price", json={"face_value": 1000, "ytm": 0.05})
    assert res.status_code == 400
    assert "coupon_rate" in res.get_json()["error"]


def test_bad_frequency_is_400(client):
    res = client.post("/api/price", json={**BOND, "frequency": 3, "ytm": 0.05})
    assert res.status_code == 400


def test_non_json_body_is_400(client):
    res = client.post("/api/price", data="not json", content_type="text/plain")
    assert res.status_code == 400


def test_both_ytm_and_price_is_400(client):
    res = client.post("/api/cashflows", json={**BOND, "ytm": 0.05, "price": 1000})
    assert res.status_code == 400


def test_404_is_json(client):
    res = client.get("/nope")
    assert res.status_code == 404
    assert res.get_json()["error"] == "Not Found"
