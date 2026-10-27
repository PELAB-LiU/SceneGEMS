import { create } from "zustand";
import { persist } from "zustand/middleware";

interface DisclosureState {
  /** Open or closed per disclosure id. A missing id uses the default of its `Disclosure`. */
  open: Record<string, boolean>;
  setOpen: (id: string, open: boolean) => void;
}

/**
 * The open or closed state of every `Disclosure` that has an id, kept per browser so a section
 * the user opened stays open on the next visit. Ids are stable strings such as `scene-gen:options`.
 */
export const useDisclosureStore = create<DisclosureState>()(
  persist(
    (set) => ({
      open: {},
      setOpen: (id, open) =>
        set((state) => (state.open[id] === open ? state : { open: { ...state.open, [id]: open } })),
    }),
    {
      name: "scenegems:disclosure",
      version: 1,
      partialize: (state) => ({ open: state.open }),
    }
  )
);
