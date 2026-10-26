import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_PAGE_SIZE, DEFAULT_VERDICT_FILTERS } from "./resultsApi";
import { useResultsStore } from "./resultsStore";

describe("results store", () => {
  beforeEach(() => {
    useResultsStore.getState().reset();
  });

  it("starts with no campaign, the default filters and the first page", () => {
    expect(useResultsStore.getState()).toMatchObject({
      campaignId: null,
      caseId: null,
      filters: DEFAULT_VERDICT_FILTERS,
      page: 0,
      pageSize: DEFAULT_PAGE_SIZE,
      direction: "asc",
    });
  });

  it("opens a campaign with clean filters and the table shown", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setFilters({ state: "failed" });
    store.openCase("c1", 5);
    store.openCampaign("c2");
    expect(useResultsStore.getState()).toMatchObject({ campaignId: "c2", caseId: null, filters: DEFAULT_VERDICT_FILTERS, page: 0 });
  });

  it("keeps the filters when the same campaign is opened again from its table", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setFilters({ runIndex: 1 });
    store.openCampaign("c1");
    expect(useResultsStore.getState().filters.runIndex).toBe(1);
  });

  it("returns to the first page when a filter, the page size or the order changes", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setPage(3);
    store.setFilters({ classId: "a" });
    expect(useResultsStore.getState().page).toBe(0);
    store.setPage(2);
    store.setPageSize(100);
    expect(useResultsStore.getState()).toMatchObject({ page: 0, pageSize: 100 });
    store.setPage(2);
    store.setDirection("desc");
    expect(useResultsStore.getState()).toMatchObject({ page: 0, direction: "desc" });
    store.setPage(2);
    store.resetFilters();
    expect(useResultsStore.getState()).toMatchObject({ page: 0, filters: DEFAULT_VERDICT_FILTERS });
  });

  it("merges filter changes", () => {
    const store = useResultsStore.getState();
    store.setFilters({ state: "failed" });
    store.setFilters({ sensitive: "yes" });
    expect(useResultsStore.getState().filters).toEqual({ ...DEFAULT_VERDICT_FILTERS, state: "failed", sensitive: "yes" });
  });

  it("keeps the page inside the known total", () => {
    const store = useResultsStore.getState();
    store.setPage(9, 120);
    expect(useResultsStore.getState().page).toBe(2);
    store.setPage(-4, 120);
    expect(useResultsStore.getState().page).toBe(0);
    store.setPage(4);
    expect(useResultsStore.getState().page).toBe(4);
  });

  it("opens a case of the open campaign and goes back to the table", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setFilters({ state: "failed" });
    store.openCase("c1", 5);
    expect(useResultsStore.getState()).toMatchObject({ campaignId: "c1", caseId: 5 });
    expect(useResultsStore.getState().filters.state).toBe("failed");
    store.closeCase();
    expect(useResultsStore.getState().caseId).toBeNull();
    expect(useResultsStore.getState().filters.state).toBe("failed");
  });

  it("opens a case of another campaign with clean filters", () => {
    const store = useResultsStore.getState();
    store.openCampaign("c1");
    store.setFilters({ state: "failed" });
    store.openCase("c2", 7);
    expect(useResultsStore.getState()).toMatchObject({ campaignId: "c2", caseId: 7, filters: DEFAULT_VERDICT_FILTERS });
  });
});
