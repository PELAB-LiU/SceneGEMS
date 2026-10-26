/** Entry of the dev-only `/encounter-harness.html` (see `EncounterHarness`). */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../../index.css";
import { EncounterHarness } from "./EncounterHarness";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <EncounterHarness />
  </StrictMode>
);
