import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { ArchitectureNode, Fact, Lane, MetamodelNode } from "../../domain/cluster/architectureApi";
import { cardFacts, chipsPerRow, factTone, formatFactValue, measuredCount, words } from "./capabilitiesModel";
import { CONCRETE_WIDTH, META_WIDTH } from "./cardSizes";

export interface ConcreteNodeData extends Record<string, unknown> {
  node: ArchitectureNode;
  height: number;
  selected: boolean;
  dimmed: boolean;
}

export interface MetaNodeData extends Record<string, unknown> {
  node: MetamodelNode;
  height: number;
  implementations: number;
  selected: boolean;
  dimmed: boolean;
}

export interface LaneNodeData extends Record<string, unknown> {
  lane: Lane;
  index: number;
}

export type ConcreteFlowNode = Node<ConcreteNodeData, "concrete">;
export type MetaFlowNode = Node<MetaNodeData, "meta">;
export type LaneFlowNode = Node<LaneNodeData, "lane">;

function Handles() {
  return (
    <>
      <Handle type="target" position={Position.Left} className="cap-handle" isConnectable={false} />
      <Handle type="source" position={Position.Right} className="cap-handle" isConnectable={false} />
    </>
  );
}

/** Short names for the chips, so two fit a card's row. */
const CHIP_LABELS: Record<string, string> = {
  repeatability_tier: "Repeat",
  max_speedup: "Speed",
  wind: "Wind",
  waves: "Waves",
};

const SHORT_SUPPORT: Record<string, string> = { supported: "yes", unsupported: "no", unmeasured: "untested" };

/** The value as a chip prints it, short enough for half a card; the tooltip has the full text. */
function chipValue(fact: Fact): string {
  if (fact.value === null) {
    return "?";
  }
  return (fact.key === "wind" || fact.key === "waves") && typeof fact.value === "string" ? (SHORT_SUPPORT[fact.value] ?? fact.value) : formatFactValue(fact);
}

/** One value of a node or adapter as a chip: green, amber or red by what it promises, with a dot when it was measured. */
export function FactChip({ fact, short = false }: { fact: Fact; short?: boolean }) {
  const label = short ? (CHIP_LABELS[fact.key] ?? fact.label) : fact.label;
  const value = chipValue(fact);
  const title = `${fact.label}: ${formatFactValue(fact)}${fact.measured ? " (measured)" : " (declared)"}${fact.note ? `. ${fact.note}` : ""}`;
  return (
    <span className={`cap-chip cap-chip--${factTone(fact)}`} title={title}>
      <span className="cap-chip-label">{label}</span>
      <span className="cap-chip-value">{value}</span>
      {fact.measured && <span className="cap-chip-measured" aria-label="measured" />}
    </span>
  );
}

export function ConcreteNode({ data }: NodeProps<ConcreteFlowNode>) {
  const { node, height, selected, dimmed } = data;
  const chips = cardFacts(node);
  const measured = measuredCount(node);
  return (
    <div className={`cap-node cap-node--${node.status}${selected ? " is-selected" : ""}${dimmed ? " is-dimmed" : ""}`} style={{ width: CONCRETE_WIDTH, height }} title={node.description}>
      <Handles />
      <div className="cap-node-head">
        <span className="cap-node-title" title={node.id}>
          {words(node.label)}
        </span>
        {node.status === "planned" && <span className="cap-tag cap-tag--planned">planned</span>}
      </div>
      {chips.length === 0 && <p className="cap-node-description">{node.description}</p>}
      {(node.tags.length > 0 || measured > 0) && (
        <div className="cap-node-meta">
          {node.tags.map((tag) => (
            <span key={tag} className="cap-tag">
              {tag}
            </span>
          ))}
          {measured > 0 && <span className="cap-tag cap-tag--measured">{measured} measured</span>}
        </div>
      )}
      {chips.length > 0 && (
        <div className={`cap-node-chips${chipsPerRow(chips) === 1 ? " cap-node-chips--single" : ""}`}>
          {chips.map((fact) => (
            <FactChip key={fact.key} fact={fact} short />
          ))}
        </div>
      )}
    </div>
  );
}

export function MetaNode({ data }: NodeProps<MetaFlowNode>) {
  const { node, height, implementations, selected, dimmed } = data;
  return (
    <div className={`cap-node cap-node--meta cap-node--kind-${node.kind}${selected ? " is-selected" : ""}${dimmed ? " is-dimmed" : ""}`} style={{ width: META_WIDTH, height }}>
      <Handles />
      <div className="cap-node-head">
        <span className="cap-node-title" title={node.id}>
          {node.label}
        </span>
        <span className="cap-tag cap-tag--kind">{node.kind}</span>
      </div>
      <p className="cap-node-description cap-node-description--long">{node.description}</p>
      <div className="cap-node-meta">
        <span className="cap-tag">{node.members.length} to provide</span>
        <span className={`cap-tag ${implementations > 0 ? "cap-tag--measured" : "cap-tag--planned"}`}>{implementations === 0 ? "no implementation" : `${implementations} implemented`}</span>
      </div>
    </div>
  );
}

/** The column of a lane: its name and what it is, behind the cards. */
export function LaneBand({ data }: NodeProps<LaneFlowNode>) {
  const { lane, index } = data;
  return (
    <div className="cap-lane">
      <div className="cap-lane-head">
        <span className="cap-lane-index">{index + 1}</span>
        <div>
          <p className="cap-lane-title">{lane.label}</p>
          <p className="cap-lane-description">{lane.description}</p>
        </div>
      </div>
    </div>
  );
}
