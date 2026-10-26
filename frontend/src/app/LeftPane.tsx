import type { ReactElement, SVGProps } from "react";
import { useClusterStore } from "../domain/cluster/clusterStore";
import type { AppSection, WorkbenchView } from "./uiStore";

const APP_TITLE = "SceneGEMS";

type IconProps = SVGProps<SVGSVGElement>;

function iconBaseProps(props: IconProps) {
  return {
    className: "left-menu-icon",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    ...props,
  };
}

function DomainConfigIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
      <circle cx="9" cy="6" r="2" />
      <circle cx="15" cy="12" r="2" />
      <circle cx="8" cy="18" r="2" />
    </svg>
  );
}

function SceneGenerationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15l-1.9-4.1L5.5 9l4.6-1.4L12 3z" />
      <path d="M18 14l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2z" />
    </svg>
  );
}

function TrajectoryGenerationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <circle cx="5" cy="19" r="2" />
      <circle cx="19" cy="5" r="2" />
      <path d="M7 19h6a4 4 0 0 0 4-4V7" strokeDasharray="3 3" />
    </svg>
  );
}

function SimulationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <polygon points="9 7 18 12 9 17 9 7" />
      <circle cx="12" cy="12" r="9" />
    </svg>
  );
}

function WarapsIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M9 7V3M15 7V3" />
      <path d="M7 7h10v4a5 5 0 0 1-10 0V7z" />
      <path d="M12 16v5" />
    </svg>
  );
}

function WorkbenchIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <rect x="3" y="4" width="18" height="13" rx="1.5" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  );
}

function ClusterIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <rect x="4" y="3" width="16" height="5" rx="1" />
      <rect x="4" y="10" width="16" height="5" rx="1" />
      <rect x="4" y="17" width="16" height="4" rx="1" />
      <path d="M8 5.5h.01M8 12.5h.01M8 19h.01" />
    </svg>
  );
}

function CampaignsIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M5 21V4" />
      <path d="M5 4h11l-2 4 2 4H5" />
    </svg>
  );
}

function ObserveIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function ResultsIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M4 20h16" />
      <rect x="6" y="11" width="3" height="7" />
      <rect x="11" y="6" width="3" height="12" />
      <rect x="16" y="13" width="3" height="5" />
    </svg>
  );
}

function DocumentationIcon(props: IconProps) {
  return (
    <svg {...iconBaseProps(props)}>
      <path d="M6 4h9l4 4v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
      <path d="M14 4v5h5" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="14" y2="17" />
    </svg>
  );
}

const WORKBENCH_ITEMS: { view: WorkbenchView; label: string; Icon: (props: IconProps) => ReactElement }[] = [
  { view: "domainConfig", label: "Domain Configuration", Icon: DomainConfigIcon },
  { view: "sceneGeneration", label: "Scene Generation", Icon: SceneGenerationIcon },
  { view: "trajectoryGeneration", label: "Trajectory Generation", Icon: TrajectoryGenerationIcon },
  { view: "simulation", label: "Simulation", Icon: SimulationIcon },
  { view: "waraps", label: "Connections", Icon: WarapsIcon },
];

const CLUSTER_SECTIONS: { section: AppSection; label: string; Icon: (props: IconProps) => ReactElement }[] = [
  { section: "cluster", label: "Cluster", Icon: ClusterIcon },
  { section: "campaigns", label: "Campaigns", Icon: CampaignsIcon },
  { section: "observe", label: "Observe", Icon: ObserveIcon },
  { section: "results", label: "Results", Icon: ResultsIcon },
];

function ClusterSelect() {
  const clusters = useClusterStore((s) => s.clusters);
  const selectedClusterId = useClusterStore((s) => s.selectedClusterId);
  const selectCluster = useClusterStore((s) => s.selectCluster);
  return (
    <label className="left-pane-cluster">
      <span className="left-pane-cluster-label">Cluster</span>
      <select
        value={selectedClusterId ?? ""}
        onChange={(e) => selectCluster(e.target.value === "" ? null : e.target.value)}
        aria-label="Selected cluster"
      >
        <option value="">{clusters.length === 0 ? "no clusters" : "none"}</option>
        {clusters.map((cluster) => (
          <option key={cluster.id} value={cluster.id}>
            {cluster.name}
          </option>
        ))}
      </select>
    </label>
  );
}

interface LeftPaneProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  activeSection: AppSection;
  onSectionSelect: (section: AppSection) => void;
  workbenchView: WorkbenchView;
  /** Selecting a workbench view also shows the workbench section. */
  onWorkbenchViewSelect: (view: WorkbenchView) => void;
}

export function LeftPane({
  isCollapsed,
  onToggleCollapse,
  activeSection,
  onSectionSelect,
  workbenchView,
  onWorkbenchViewSelect,
}: LeftPaneProps) {
  const workbenchActive = activeSection === "workbench";
  return (
    <aside className={`left-pane${isCollapsed ? " collapsed" : ""}`}>
      <div className="left-pane-brand">
        {isCollapsed ? (
          <img className="left-pane-logo" src="/favicon.svg" alt={APP_TITLE} />
        ) : (
          <>
            <div className="left-pane-brand-header">
              <img className="left-pane-logo" src="/favicon.svg" alt="" aria-hidden />
              <span className="left-pane-brand-title">{APP_TITLE}</span>
            </div>
            <p className="left-pane-brand-subtitle">
              A Scenario Generation and Execution Framework for Simulation-Based Assurance of
              Maritime Autonomous Surface Vehicles
            </p>
          </>
        )}
      </div>
      <div className="left-pane-header">
        <button
          className="left-menu-toggle"
          aria-label="Toggle menu"
          onClick={onToggleCollapse}
        >
          &#9776;
        </button>
      </div>
      {!isCollapsed && (
        <>
          <details open className="left-menu-group">
            <summary>Menu</summary>
            <button
              className={`left-menu-item left-menu-section${workbenchActive ? " active-section" : ""}`}
              onClick={() => onSectionSelect("workbench")}
              aria-current={workbenchActive ? "page" : undefined}
            >
              <WorkbenchIcon />
              Workbench
            </button>
            <div className="left-menu-subitems" role="group" aria-label="Workbench views">
              {WORKBENCH_ITEMS.map(({ view, label, Icon }) => (
                <button
                  key={view}
                  className={`left-menu-item left-menu-subitem${workbenchActive && workbenchView === view ? " active" : ""}`}
                  onClick={() => onWorkbenchViewSelect(view)}
                >
                  <Icon />
                  {label}
                </button>
              ))}
            </div>
            {CLUSTER_SECTIONS.map(({ section, label, Icon }) => (
              <button
                key={section}
                className={`left-menu-item left-menu-section${activeSection === section ? " active" : ""}`}
                onClick={() => onSectionSelect(section)}
                aria-current={activeSection === section ? "page" : undefined}
              >
                <Icon />
                {label}
              </button>
            ))}
            <a href="/docs/" className="left-menu-item">
              <DocumentationIcon />
              Documentation
            </a>
          </details>
          <ClusterSelect />
        </>
      )}
    </aside>
  );
}
