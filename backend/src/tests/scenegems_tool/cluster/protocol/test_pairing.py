import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.pairing import BrokerAccess, PairingRequest, PairingResponse


def test_pairing_response_round_trips():
    response = PairingResponse(
        master_id="m1",
        node_id="n1",
        node_credential="secret",
        ca_certificate_pem="-----BEGIN CERTIFICATE-----",
        broker=BrokerAccess(host="10.0.0.1", port=8883, username="node-n1", password="pw", topic_scope="scenegems/m1/n1"),
    )
    assert PairingResponse.model_validate_json(response.model_dump_json()) == response
    assert response.broker.tls


def test_pairing_request_round_trips():
    request = PairingRequest(token="one-time", node_name="lab-1", labels={"gpu": "no"})
    assert PairingRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("port", [0, 70000])
def test_broker_port_range(port):
    with pytest.raises(ValidationError):
        BrokerAccess(host="h", port=port, username="u", password="p", topic_scope="s")
