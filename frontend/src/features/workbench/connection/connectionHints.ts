/**
 * Turn the attempted endpoint into the checks that actually resolve a failed connect.
 * The server already says what went wrong; these say what to do about it.
 */
export function connectionHints(usesMaster: boolean, clientBroker: string, port: number, tlsConnection: boolean): string[] {
  if (usesMaster) {
    return [
      "The master's broker runs as the cluster-broker service of the master's stack: check that it is up with docker ps on the master's machine.",
      "Pick another broker if this master was started without one.",
    ];
  }
  const host = clientBroker.trim().toLowerCase();
  const hints: string[] = [];
  if (host === "localhost" || host === "127.0.0.1") {
    hints.push(`The server resolves localhost to its Docker host, so the broker must be published on port ${port} of the master's machine.`);
  }
  hints.push(`Confirm something listens on ${clientBroker || "the broker host"}:${port} and that the master's machine can reach it.`);
  if (tlsConnection) {
    hints.push("TLS is on: the port must speak MQTT over TLS (8883 for broker.waraps.org) and the credentials must be valid.");
  } else {
    hints.push("TLS is off: the port must speak plain MQTT (usually 1883).");
  }
  return hints;
}
