import { create } from "zustand";

interface EncounterSelectionState {
  /** Vessel pair selected in the workbench's simulation view (canvas, cards and timeline). */
  selectedRelationId: string | null;
  setSelectedRelationId: (relationId: string | null) => void;
}

/** The workbench's pair selection, shared by its canvas, pair cards and rule timeline. */
export const useEncounterSelectionStore = create<EncounterSelectionState>((set) => ({
  selectedRelationId: null,
  setSelectedRelationId: (selectedRelationId) => set({ selectedRelationId }),
}));
