import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  COLREGS_CONSTRAINTS_PRESETS,
  OBSTACLE_TYPES_PRESETS,
  VESSEL_TYPES_PRESETS,
} from "./domainConfigPresets";
import { Disclosure } from "../../../components/Disclosure";
import { PageHeader } from "../../../components/PageHeader";
import { ConstraintsEditor } from "./constraintsEditor";

type DomainConfigTab = "colregs" | "vesselObstacleTypes";

// The backend looks these rows up by name (VesselTypeMap and StaticObstacleTypeMap).
const VESSEL_TYPE_PROTECTED_ROWS = ["UnspecifiedVesselType"] as const;
const OBSTACLE_TYPE_PROTECTED_ROWS = ["UnspecifiedObstacleType"] as const;

const DUAL_COLUMN_SPLIT_MIN = 15;
const DUAL_COLUMN_SPLIT_MAX = 85;

function clampDualColumnSplit(value: number): number {
  return Math.min(DUAL_COLUMN_SPLIT_MAX, Math.max(DUAL_COLUMN_SPLIT_MIN, value));
}

interface DomainFileToolsProps {
  /** Which file the tools belong to; names the remembered open state of the file options. */
  scope: string;
  presets: readonly string[];
  hasContent: boolean;
  onLoadFromPreset: (path: string) => void;
  onLoadFromFile: (file: File) => void;
  onExport: () => void;
}

/** Pick a preset (the usual way to change a file) and, behind one toggle, load a file from the computer or export. */
function DomainFileTools({ scope, presets, hasContent, onLoadFromPreset, onLoadFromFile, onExport }: DomainFileToolsProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  return (
    <div className="domain-file-tools">
      <select
        aria-label="Load a preset"
        onChange={(event) => {
          const path = event.target.value;
          if (path) {
            onLoadFromPreset(path);
          }
        }}
        defaultValue=""
      >
        <option value="" disabled>
          Load a preset...
        </option>
        {presets.map((path) => (
          <option key={path} value={path}>
            {path}
          </option>
        ))}
      </select>
      <Disclosure
        id={`domain-config:${scope}:file-options`}
        variant="link"
        headingLevel={null}
        title="Files: load or export"
        openTitle="Hide file options"
        keepMounted
      >
        <div className="toolbar-row">
          <input
            ref={fileInputRef}
            hidden
            type="file"
            accept=".yaml,.yml,text/yaml,text/x-yaml"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                onLoadFromFile(file);
              }
              event.target.value = "";
            }}
          />
          <button type="button" onClick={() => fileInputRef.current?.click()}>
            Load from computer
          </button>
          <button type="button" onClick={onExport} disabled={!hasContent}>
            Export as YAML file
          </button>
        </div>
      </Disclosure>
    </div>
  );
}

interface YamlEditorColumnProps {
  title: string;
  protectedRows: readonly string[];
  presets: readonly string[];
  text: string;
  onTextChange: (value: string) => void;
  onLoadFromPreset: (path: string) => void;
  onLoadFromFile: (file: File) => void;
  onExport: () => void;
  style?: CSSProperties;
}

function YamlEditorColumn({
  title,
  protectedRows,
  presets,
  text,
  onTextChange,
  onLoadFromPreset,
  onLoadFromFile,
  onExport,
  style,
}: YamlEditorColumnProps) {
  const hasContent = useMemo(() => text.trim().length > 0, [text]);

  return (
    <div className="domain-config-column" style={style}>
      <h4>{title}</h4>
      <DomainFileTools
        scope={title.toLowerCase().replace(/\s+/g, "-")}
        presets={presets}
        hasContent={hasContent}
        onLoadFromPreset={onLoadFromPreset}
        onLoadFromFile={onLoadFromFile}
        onExport={onExport}
      />
      <ConstraintsEditor
        text={text}
        onTextChange={onTextChange}
        label={title}
        protectedRows={protectedRows}
        tableMinRows={1}
      />
    </div>
  );
}

interface Props {
  colregsText: string;
  onColregsTextChange: (value: string) => void;
  onLoadColregsFromPreset: (path: string) => void;
  onLoadColregsFromFile: (file: File) => void;
  onExportColregs: () => void;
  vesselTypesText: string;
  onVesselTypesTextChange: (value: string) => void;
  onLoadVesselTypesFromPreset: (path: string) => void;
  onLoadVesselTypesFromFile: (file: File) => void;
  onExportVesselTypes: () => void;
  obstacleTypesText: string;
  onObstacleTypesTextChange: (value: string) => void;
  onLoadObstacleTypesFromPreset: (path: string) => void;
  onLoadObstacleTypesFromFile: (file: File) => void;
  onExportObstacleTypes: () => void;
  /** Moves on to the next step of the workflow (Scene Generation). */
  onContinue?: () => void;
}

export function DomainConfigurationPanel({
  colregsText,
  onColregsTextChange,
  onLoadColregsFromPreset,
  onLoadColregsFromFile,
  onExportColregs,
  vesselTypesText,
  onVesselTypesTextChange,
  onLoadVesselTypesFromPreset,
  onLoadVesselTypesFromFile,
  onExportVesselTypes,
  obstacleTypesText,
  onObstacleTypesTextChange,
  onLoadObstacleTypesFromPreset,
  onLoadObstacleTypesFromFile,
  onExportObstacleTypes,
  onContinue,
}: Props) {
  const [activeTab, setActiveTab] = useState<DomainConfigTab>("colregs");
  const [vesselColumnSplitPercent, setVesselColumnSplitPercent] = useState(50);
  const [isResizingDualColumns, setIsResizingDualColumns] = useState(false);
  const dualColumnsRef = useRef<HTMLDivElement | null>(null);
  const dualColumnSplitDragRef = useRef<{ startX: number; startSplit: number; width: number } | null>(
    null
  );
  const hasColregs = useMemo(() => colregsText.trim().length > 0, [colregsText]);

  const onDualColumnResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const el = dualColumnsRef.current;
      if (!el) {
        return;
      }
      const width = el.getBoundingClientRect().width;
      dualColumnSplitDragRef.current = {
        startX: event.clientX,
        startSplit: vesselColumnSplitPercent,
        width,
      };
      setIsResizingDualColumns(true);

      const onPointerMove = (moveEvent: PointerEvent) => {
        const drag = dualColumnSplitDragRef.current;
        if (!drag) {
          return;
        }
        const deltaPct = ((moveEvent.clientX - drag.startX) / drag.width) * 100;
        setVesselColumnSplitPercent(clampDualColumnSplit(drag.startSplit + deltaPct));
      };

      const onPointerUp = () => {
        dualColumnSplitDragRef.current = null;
        setIsResizingDualColumns(false);
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp, { once: true });
    },
    [vesselColumnSplitPercent]
  );

  return (
    <aside className="right-pane scene-generation-sidebar domain-configuration-panel">
      <PageHeader
        eyebrow="Step 1 of 4"
        title="Domain Configuration"
        description="The rules and vessel types the generators work with. The defaults are already loaded, so you can usually go straight on to the next step."
        actions={
          onContinue ? (
            <button type="button" className="primary-btn accent" onClick={onContinue}>
              Next: Scene Generation
            </button>
          ) : undefined
        }
      />
      <div className="scene-gen-tabs" role="tablist" aria-label="Domain configuration section">
        <button
          className={`scene-gen-tab${activeTab === "colregs" ? " active" : ""}`}
          type="button"
          role="tab"
          aria-selected={activeTab === "colregs"}
          onClick={() => setActiveTab("colregs")}
        >
          Collision rules (COLREGS)
        </button>
        <button
          className={`scene-gen-tab${activeTab === "vesselObstacleTypes" ? " active" : ""}`}
          type="button"
          role="tab"
          aria-selected={activeTab === "vesselObstacleTypes"}
          onClick={() => setActiveTab("vesselObstacleTypes")}
        >
          Vessel and obstacle types
        </button>
      </div>

      {activeTab === "colregs" ? (
        <div className="scene-editor-panel">
          <DomainFileTools
            scope="colregs"
            presets={COLREGS_CONSTRAINTS_PRESETS}
            hasContent={hasColregs}
            onLoadFromPreset={onLoadColregsFromPreset}
            onLoadFromFile={onLoadColregsFromFile}
            onExport={onExportColregs}
          />
          <ConstraintsEditor text={colregsText} onTextChange={onColregsTextChange} label="COLREGS constraints" scope="colregs" />
        </div>
      ) : (
        <div className="scene-editor-panel domain-config-dual-panel">
          <div
            ref={dualColumnsRef}
            className={`domain-config-dual-columns${isResizingDualColumns ? " is-resizing" : ""}`}
          >
            <YamlEditorColumn
              title="Vessel types"
              protectedRows={VESSEL_TYPE_PROTECTED_ROWS}
              presets={VESSEL_TYPES_PRESETS}
              text={vesselTypesText}
              onTextChange={onVesselTypesTextChange}
              onLoadFromPreset={onLoadVesselTypesFromPreset}
              onLoadFromFile={onLoadVesselTypesFromFile}
              onExport={onExportVesselTypes}
              style={{ flex: `0 0 ${vesselColumnSplitPercent}%`, minWidth: 0 }}
            />
            <div
              className="domain-config-column-resizer"
              onPointerDown={onDualColumnResizeStart}
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize vessel types and obstacle types panels"
              aria-valuenow={vesselColumnSplitPercent}
              aria-valuemin={DUAL_COLUMN_SPLIT_MIN}
              aria-valuemax={DUAL_COLUMN_SPLIT_MAX}
            />
            <YamlEditorColumn
              title="Static obstacle types"
              protectedRows={OBSTACLE_TYPE_PROTECTED_ROWS}
              presets={OBSTACLE_TYPES_PRESETS}
              text={obstacleTypesText}
              onTextChange={onObstacleTypesTextChange}
              onLoadFromPreset={onLoadObstacleTypesFromPreset}
              onLoadFromFile={onLoadObstacleTypesFromFile}
              onExport={onExportObstacleTypes}
              style={{ flex: "1 1 0%", minWidth: 0 }}
            />
          </div>
        </div>
      )}
    </aside>
  );
}
