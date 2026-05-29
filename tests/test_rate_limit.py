"""Rate-limiting tests.

Each TestClient uses a unique source IP (see conftest), so this test's bucket is
isolated. The heavy limit is configured to 10/minute; the 11th request within the
window must be rejected with HTTP 429.
"""

from __future__ import annotations


def test_heavy_endpoint_rate_limited(client):
    statuses = [client.get("/api/v1/technical/BBCA").status_code for _ in range(11)]
    assert statuses[:10] == [200] * 10
    assert statuses[-1] == 429


def test_rate_limited_response_shape(client):
    last = None
    for _ in range(12):
        last = client.get("/api/v1/signal/BBCA")
    assert last is not None
    assert last.status_code == 429
    assert last.json()["error"]["code"] == "rate_limited"
