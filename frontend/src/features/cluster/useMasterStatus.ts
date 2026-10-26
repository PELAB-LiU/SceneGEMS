import { useQuery } from "@tanstack/react-query";
import { createOperatorClient, OperatorApiError } from "../../domain/cluster/operatorApi";

export const MASTER_STATUS_POLL_MS = 10_000;

/** The master's status (`GET /cluster/status`), polled while the Cluster section is shown. */
export function useMasterStatus(operatorUrl: string | null) {
  return useQuery({
    queryKey: ["cluster", operatorUrl, "status"],
    queryFn: ({ signal }) => createOperatorClient(operatorUrl as string).getStatus(signal),
    enabled: operatorUrl !== null,
    refetchInterval: MASTER_STATUS_POLL_MS,
    retry: (failureCount, error) => !(error instanceof OperatorApiError && error.unreachable) && failureCount < 2,
  });
}
