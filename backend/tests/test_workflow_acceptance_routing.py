"""nginx retry histories must identify the final Gateway, not each attempt."""

import httpx
import pytest
from test_workflow_gateway_acceptance import final_gateway_port


@pytest.mark.parametrize(
    "history, expected",
    [
        ("192.0.2.1:8001", 8001),
        ("[2001:db8::1]:8001, 192.0.2.1:8001", 8001),
        ("192.0.2.1:8001, [2001:db8::1]:8002, 192.0.2.1:8002", 8002),
        ("[2001:db8::1]:8002", 8002),
    ],
)
def test_final_gateway_port(history, expected):
    response = httpx.Response(200, headers={"X-Acceptance-Upstream": history})
    assert final_gateway_port(response) == expected
