"""Paths and headers of the master's cluster API, shared by master and node.

The node reaches the master over HTTPS. Before pairing it trusts nothing: it fetches the
CA certificate, checks its SHA-256 against the value it was given with the pairing token,
and from then on verifies every connection against that CA.
"""

CA_CERTIFICATE_PATH = "/cluster/ca-certificate"  # GET, unauthenticated: the CA certificate as PEM
PAIRING_PATH = "/cluster/pairing"  # POST PairingRequest, answered with PairingResponse or 403
NODE_CONTROL_PATH = "/cluster/node/control"  # WebSocket opened by the node, frames from messages.py
JOBS_PATH = "/cluster/jobs"  # POST JobSubmission; GET lists jobs, GET <JOBS_PATH>/<job id> one job
# GET and PUT <ARTIFACTS_PATH>/<sha256> on the node API (node credential); GET and HEAD on the operator API
ARTIFACTS_PATH = "/cluster/artifacts"
CAMPAIGNS_PATH = "/cluster/campaigns"  # operator API: POST a campaign config; GET lists campaigns, GET <CAMPAIGNS_PATH>/<campaign id> one (campaign_routes.py)

AUTHORIZATION_HEADER = "Authorization"
BEARER_SCHEME = "Bearer"  # the node credential from PairingResponse.node_credential, which names the node


def bearer(credential: str) -> str:
    """The Authorization header value for a node credential."""
    return f"{BEARER_SCHEME} {credential}"


def credential_from_authorization(value: str) -> str:
    """The credential in an Authorization header value, or "" when it is not a bearer value."""
    scheme, _, credential = (value or "").partition(" ")
    return credential.strip() if scheme == BEARER_SCHEME else ""
