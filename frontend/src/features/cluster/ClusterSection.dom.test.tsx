import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetLiveChannels } from "../../domain/cluster/liveChannels";
import { useNodesStore } from "../../domain/cluster/nodesStore";
import { sampleJob, sampleMasterStatus, sampleNode } from "../../test/fixtures/clusterViews";
import { MockWebSocket } from "../../test/mockWebSocket";
import { ClusterSection } from "./ClusterSection";

// The node cards open the node's instances (pools and leased jobs) with their viewers.

function json(body: unknown, total?: number): Response {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (total !== undefined) {
    headers["X-Total-Count"] = String(total);
  }
  return new Response(JSON.stringify(body), { status: 200, headers });
}

async function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(String(input));
  if (url.pathname === "/cluster/status") {
    return json(sampleMasterStatus);
  }
  if (url.pathname === "/cluster/nodes") {
    return json([sampleNode(), sampleNode({ node_id: "node-b2", name: "worker-b", leases: [] })], 2);
  }
  if (url.pathname === "/cluster/jobs") {
    return json(url.searchParams.get("lease_owner") === "node-a1" || !url.searchParams.has("lease_owner") ? [sampleJob()] : [], 1);
  }
  return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
}

beforeEach(() => {
  MockWebSocket.reset();
  resetLiveChannels({ createSocket: MockWebSocket.factory });
  useNodesStore.setState({ operatorUrl: null, nodes: [], loaded: false, source: null, error: null, unreachable: false, updatedAt: null });
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
});

afterEach(() => {
  resetLiveChannels();
  vi.unstubAllGlobals();
});

describe("Cluster node instances in the DOM", () => {
  it("opens a node's pools and leased jobs, views one, and closes", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ClusterSection />
      </QueryClientProvider>
    );
    const toggle = await screen.findByRole("button", { name: "Instances (1 job)" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Hide the instances" })).toHaveAttribute("aria-expanded", "true");

    const panel = screen.getByRole("region", { name: "Instances of worker-a" });
    const pools = within(panel).getByRole("navigation", { name: "Instances" });
    expect(within(pools).getAllByRole("button", { name: /Scene generation \d/ })).toHaveLength(4);
    expect(await within(pools).findByRole("button", { name: /scene_generation job-1, attempt 1/ })).toBeInTheDocument();

    await user.click(within(pools).getByRole("button", { name: /Scene generation 0/ }));
    expect(within(panel).getByRole("button", { name: "Close the view" })).toBeInTheDocument();
    // The viewer subscribes to the instance topic while it is shown
    await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));

    await user.click(within(panel).getByRole("button", { name: "Close the instances" }));
    expect(screen.queryByRole("region", { name: "Instances of worker-a" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Instances (1 job)" })).toHaveAttribute("aria-expanded", "false");
  });
});
