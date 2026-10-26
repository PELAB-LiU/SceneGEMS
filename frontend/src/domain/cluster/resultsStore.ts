import { create } from "zustand";
import {
  clampPage,
  DEFAULT_PAGE_SIZE,
  DEFAULT_VERDICT_FILTERS,
  type SortDirection,
  type VerdictFilterState,
} from "./resultsApi";

/**
 * What the Results section shows: the campaign, the verdict table's filters and page, and the
 * case page that is open. Kept in memory (not persisted): a reload starts at the newest campaign.
 * Other sections open a campaign's results with `openCampaign` (or `openCase`) and then show
 * the section (`features/results/showResults.ts`).
 */
export interface ResultsState {
  campaignId: string | null;
  /** The case page that is open, or null for the verdict table. */
  caseId: number | null;
  filters: VerdictFilterState;
  /** Zero based. */
  page: number;
  pageSize: number;
  direction: SortDirection;
  /** Shows a campaign's verdict table with no filters. */
  openCampaign: (campaignId: string) => void;
  /** Shows one case of a campaign (its page). */
  openCase: (campaignId: string, caseId: number) => void;
  /** Back from the case page to the table. */
  closeCase: () => void;
  /** A filter change returns to the first page. */
  setFilters: (changes: Partial<VerdictFilterState>) => void;
  resetFilters: () => void;
  setPage: (page: number, total?: number | null) => void;
  setPageSize: (pageSize: number) => void;
  setDirection: (direction: SortDirection) => void;
  /** Forgets the campaign (the selected cluster changed). */
  reset: () => void;
}

const INITIAL = {
  campaignId: null,
  caseId: null,
  filters: DEFAULT_VERDICT_FILTERS,
  page: 0,
  pageSize: DEFAULT_PAGE_SIZE,
  direction: "asc" as SortDirection,
};

export const useResultsStore = create<ResultsState>()((set, get) => ({
  ...INITIAL,
  openCampaign: (campaignId) => {
    if (get().campaignId === campaignId && get().caseId === null) {
      return;
    }
    set({ campaignId, caseId: null, filters: DEFAULT_VERDICT_FILTERS, page: 0 });
  },
  openCase: (campaignId, caseId) => {
    if (get().campaignId === campaignId) {
      set({ caseId });
    } else {
      set({ campaignId, caseId, filters: DEFAULT_VERDICT_FILTERS, page: 0 });
    }
  },
  closeCase: () => set({ caseId: null }),
  setFilters: (changes) => set((state) => ({ filters: { ...state.filters, ...changes }, page: 0 })),
  resetFilters: () => set({ filters: DEFAULT_VERDICT_FILTERS, page: 0 }),
  setPage: (page, total) =>
    set((state) => ({ page: total === undefined || total === null ? Math.max(0, page) : clampPage(page, total, state.pageSize) })),
  setPageSize: (pageSize) => set({ pageSize, page: 0 }),
  setDirection: (direction) => set({ direction, page: 0 }),
  reset: () => set({ ...INITIAL }),
}));
