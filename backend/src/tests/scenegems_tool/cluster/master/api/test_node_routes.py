import json

from scenegems_tool.cluster.protocol.messages import Welcome
from scenegems_tool.cluster.protocol.pairing import PairingRequest, PairingResponse
from scenegems_tool.cluster.protocol.routes import CA_CERTIFICATE_PATH, PAIRING_PATH
from scenegems_tool.cluster.protocol.version import PROTOCOL_VERSION
from scenegems_tool.cluster.security.certificates.certificate_pinning import certificate_sha256, matches_pinned_sha256
from scenegems_tool.cluster.security.credentials.pairing_tokens import create_pairing_token
from tests.scenegems_tool.cluster.master.fake_node import FakeNode
from tests.scenegems_tool.persistence.stores.builders import make_hello


def test_the_ca_certificate_is_served_unauthenticated(client, security):
    response = client.get(CA_CERTIFICATE_PATH)
    assert response.status_code == 200 and response.headers["content-type"] == "application/x-pem-file"
    assert response.text == security.ca_certificate_pem
    assert matches_pinned_sha256(response.text, certificate_sha256(security.ca_certificate_pem))


def test_pairing_hands_out_a_credential_that_opens_the_control_socket(client, security):
    token = create_pairing_token(security.store).token
    response = client.post(PAIRING_PATH, content=PairingRequest(token=token, node_name="Lab PC 1", labels={"site": "lab"}).model_dump_json())
    assert response.status_code == 200
    paired = PairingResponse.model_validate_json(response.text)
    assert paired.master_id == "lab-master" and paired.node_id.startswith("lab-pc-1-")
    assert paired.broker.topic_scope == f"scenegems/lab-master/{paired.node_id}"
    node = FakeNode(client, paired.node_credential, make_hello(paired.node_id))
    try:
        assert isinstance(node.connect(), Welcome)
    finally:
        node.close()


def test_a_used_or_unknown_token_is_refused(client, security):
    token = create_pairing_token(security.store).token
    body = PairingRequest(token=token, node_name="lab").model_dump_json()
    assert client.post(PAIRING_PATH, content=body).status_code == 200
    again = client.post(PAIRING_PATH, content=body)
    assert again.status_code == 403 and token not in again.text
    assert client.post(PAIRING_PATH, content=PairingRequest(token="x" * 43, node_name="lab").model_dump_json()).status_code == 403


def test_an_invalid_pairing_request(client):
    assert client.post(PAIRING_PATH, content="not json").status_code == 422
    assert client.post(PAIRING_PATH, content=json.dumps({"token": "t", "node_name": "n", "extra": 1})).status_code == 422
    assert client.post(PAIRING_PATH, content="x" * (64 * 1024 + 1)).status_code == 413


def test_a_pairing_request_of_another_protocol_version(client):
    response = client.post(PAIRING_PATH, content=json.dumps({"token": "t", "node_name": "n", "protocol_version": PROTOCOL_VERSION + 1}))
    assert response.status_code == 400 and "same SceneGEMS revision" in response.json()["detail"]
