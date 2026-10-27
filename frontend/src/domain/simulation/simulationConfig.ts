const DEFAULT_WS = "ws://127.0.0.1:5174/ws/scenegems_backend_service";
export const GATEWAY_PATH = "/ws/scenegems_backend_service";

/** The gateway of `VITE_WS_URL`, or the default local master's. */
export function getSimulationWsUrl(): string {
  const fromEnv = import.meta.env.VITE_WS_URL;
  return typeof fromEnv === "string" && fromEnv.length > 0 ? fromEnv : DEFAULT_WS;
}

/**
 * The workbench gateway's WebSocket URL: the active cluster's master serves it on its operator
 * listener, next to the job API, so the workbench follows the cluster selected in the left
 * pane. Without a selected cluster it falls back to `VITE_WS_URL`.
 */
export function gatewayWsUrl(operatorUrl: string | null): string {
  if (!operatorUrl) {
    return getSimulationWsUrl();
  }
  return operatorUrl.replace(/\/+$/, "").replace(/^http(s?):\/\//i, (_match, secure: string) => `ws${secure}://`) + GATEWAY_PATH;
}
