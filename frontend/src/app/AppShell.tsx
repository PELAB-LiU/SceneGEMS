import { useEffect, useState } from "react";
import "./shell.css";
import "../components/components.css";
import { LeftPane } from "./LeftPane";
import { useUiStore } from "./uiStore";
import { WorkbenchSection } from "./WorkbenchSection";
import { usePlaybackStore } from "../domain/playback/playbackStore";
import { ClusterSection } from "../features/cluster/ClusterSection";
import { CampaignsSection } from "../features/campaigns/CampaignsSection";
import { ObserveSection } from "../features/observe/ObserveSection";
import { ResultsSection } from "../features/results/ResultsSection";

const APP_TITLE = "SceneGEMS";

/**
 * The frame of the console: the left pane with its sections and the shown section. The
 * workbench stays mounted while another section is shown, so its gateway socket, generation
 * runs and editor state carry on; the cluster sections mount when shown.
 */
export function AppShell() {
  useEffect(() => {
    document.title = APP_TITLE;
  }, []);

  const section = useUiStore((s) => s.section);
  const setSection = useUiStore((s) => s.setSection);
  const workbenchView = useUiStore((s) => s.workbenchView);
  const setWorkbenchView = useUiStore((s) => s.setWorkbenchView);
  const [isLeftMenuCollapsed, setIsLeftMenuCollapsed] = useState(true);
  const [errorSlot, setErrorSlot] = useState<HTMLDivElement | null>(null);

  return (
    <div className="app-shell">
      <div
        className="app-body"
        style={{ gridTemplateColumns: `${isLeftMenuCollapsed ? 48 : 220}px minmax(0, 1fr)` }}
      >
        <LeftPane
          isCollapsed={isLeftMenuCollapsed}
          onToggleCollapse={() => setIsLeftMenuCollapsed((v) => !v)}
          activeSection={section}
          onSectionSelect={setSection}
          workbenchView={workbenchView}
          onWorkbenchViewSelect={(view) => {
            if (view === "simulation") {
              usePlaybackStore.getState().requestAutoFit();
            }
            setWorkbenchView(view);
            setSection("workbench");
          }}
        />

        <WorkbenchSection active={section === "workbench"} errorSlot={errorSlot} />
        {section === "cluster" && <ClusterSection />}
        {section === "campaigns" && <CampaignsSection />}
        {section === "observe" && <ObserveSection />}
        {section === "results" && <ResultsSection />}
      </div>
      <div ref={setErrorSlot} className="app-error-slot" />
    </div>
  );
}
