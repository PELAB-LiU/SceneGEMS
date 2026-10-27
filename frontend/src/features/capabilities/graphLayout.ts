export interface LayoutNode {
  id: string;
  lane: string;
  width: number;
  height: number;
}

export interface LayoutEdge {
  id: string;
  source: string;
  target: string;
}

export interface LaneBand {
  lane: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface GraphLayout {
  positions: Map<string, { x: number; y: number }>;
  bands: LaneBand[];
}

/** Room for the lane's name and description above its first card, and around the cards. */
export const LANE_HEADER_HEIGHT = 76;
export const LANE_PADDING = 24;
/** Between two lanes, room for the arrows and their labels. */
const LANE_GAP = 170;
/** Between two columns of one lane (a card that another card of the lane points at), where there are fewer labels. */
const COLUMN_GAP = 110;
const NODE_GAP = 20;
const SWEEPS = 6;

interface Column {
  lane: string;
  nodes: LayoutNode[];
}

/**
 * Positions for a left-to-right graph whose lanes are columns. A lane is one column, or several when
 * its cards point at each other (a card goes one column right of the card that points at it). The order
 * of the cards inside a column comes from a few barycenter sweeps over the arrows, which keeps the
 * crossings low for graphs of this size, and the columns are centered on each other.
 */
export function layoutGraph(lanes: readonly string[], nodes: readonly LayoutNode[], edges: readonly LayoutEdge[]): GraphLayout {
  const usedLanes = lanes.filter((lane) => nodes.some((node) => node.lane === lane));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const links = edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target) && edge.source !== edge.target);
  const columns = buildColumns(usedLanes, nodes, links);
  const centers = orderColumns(columns, links);

  const positions = new Map<string, { x: number; y: number }>();
  const top = Math.min(...columns.flatMap((column) => column.nodes.map((node) => (centers.get(node.id) as number) - node.height / 2)));
  let x = 0;
  columns.forEach((column, index) => {
    if (index > 0) {
      x += columns[index - 1].lane === column.lane ? COLUMN_GAP : LANE_GAP;
    }
    for (const node of column.nodes) {
      positions.set(node.id, { x, y: (centers.get(node.id) as number) - node.height / 2 - top });
    }
    x += Math.max(...column.nodes.map((node) => node.width));
  });
  return withBands(usedLanes, nodes, positions);
}

/** One column per lane and depth: the depth of a card is the longest chain of arrows from another card of its lane that ends at it. */
function buildColumns(lanes: readonly string[], nodes: readonly LayoutNode[], links: readonly LayoutEdge[]): Column[] {
  const lane = new Map(nodes.map((node) => [node.id, node.lane]));
  const inLane = links.filter((link) => lane.get(link.source) === lane.get(link.target));
  const depth = new Map<string, number>(nodes.map((node) => [node.id, 0]));
  // Longest path by relaxation; the limit keeps a cycle from running away
  for (let round = 0; round < nodes.length; round++) {
    let changed = false;
    for (const link of inLane) {
      const next = (depth.get(link.source) as number) + 1;
      if (next > (depth.get(link.target) as number) && next < nodes.length) {
        depth.set(link.target, next);
        changed = true;
      }
    }
    if (!changed) {
      break;
    }
  }
  const columns: Column[] = [];
  for (const name of lanes) {
    const members = nodes.filter((node) => node.lane === name);
    const deepest = Math.max(...members.map((node) => depth.get(node.id) as number));
    for (let level = 0; level <= deepest; level++) {
      const inColumn = members.filter((node) => depth.get(node.id) === level);
      if (inColumn.length > 0) {
        columns.push({ lane: name, nodes: inColumn });
      }
    }
  }
  return columns;
}

/** Orders every column by the mean height of the cards its arrows reach, sweeping left to right and back; returns each card's center. */
function orderColumns(columns: Column[], links: readonly LayoutEdge[]): Map<string, number> {
  const neighbors = new Map<string, string[]>();
  for (const link of links) {
    neighbors.set(link.source, [...(neighbors.get(link.source) ?? []), link.target]);
    neighbors.set(link.target, [...(neighbors.get(link.target) ?? []), link.source]);
  }
  const centers = new Map<string, number>();
  const stack = (column: Column) => {
    const total = column.nodes.reduce((sum, node) => sum + node.height, 0) + NODE_GAP * (column.nodes.length - 1);
    let y = -total / 2;
    for (const node of column.nodes) {
      centers.set(node.id, y + node.height / 2);
      y += node.height + NODE_GAP;
    }
  };
  columns.forEach(stack);
  const columnOf = new Map<string, number>();
  columns.forEach((column, index) => column.nodes.forEach((node) => columnOf.set(node.id, index)));

  const sweep = (index: number, towards: number) => {
    const column = columns[index];
    const keyed = column.nodes.map((node, position) => {
      const reached = (neighbors.get(node.id) ?? []).filter((id) => (towards < index ? (columnOf.get(id) as number) < index : (columnOf.get(id) as number) > index));
      const mean = reached.length === 0 ? (centers.get(node.id) as number) : reached.reduce((sum, id) => sum + (centers.get(id) as number), 0) / reached.length;
      return { node, mean, position };
    });
    keyed.sort((a, b) => a.mean - b.mean || a.position - b.position);
    column.nodes = keyed.map((item) => item.node);
    stack(column);
  };
  for (let round = 0; round < SWEEPS; round++) {
    for (let index = 1; index < columns.length; index++) {
      sweep(index, index - 1);
    }
    for (let index = columns.length - 2; index >= 0; index--) {
      sweep(index, index + 1);
    }
  }
  return centers;
}

/** One column per lane, the cards stacked in the order given. */
export function stackedLayout(lanes: readonly string[], nodes: readonly LayoutNode[]): GraphLayout {
  const positions = new Map<string, { x: number; y: number }>();
  let x = 0;
  for (const lane of lanes) {
    let y = 0;
    let width = 0;
    for (const node of nodes.filter((item) => item.lane === lane)) {
      positions.set(node.id, { x, y });
      y += node.height + NODE_GAP;
      width = Math.max(width, node.width);
    }
    x += width + LANE_GAP;
  }
  return withBands(lanes, nodes, positions);
}

/** The column of each lane around its cards, all as tall as the whole graph. */
function withBands(lanes: readonly string[], nodes: readonly LayoutNode[], positions: Map<string, { x: number; y: number }>): GraphLayout {
  const boxes = nodes.map((node) => ({ node, ...(positions.get(node.id) as { x: number; y: number }) }));
  const top = Math.min(...boxes.map((box) => box.y));
  const bottom = Math.max(...boxes.map((box) => box.y + box.node.height));
  const bands: LaneBand[] = lanes.map((lane) => {
    const members = boxes.filter((box) => box.node.lane === lane);
    const left = Math.min(...members.map((box) => box.x));
    const right = Math.max(...members.map((box) => box.x + box.node.width));
    return { lane, x: left - LANE_PADDING, y: top - LANE_HEADER_HEIGHT - LANE_PADDING, width: right - left + 2 * LANE_PADDING, height: bottom - top + LANE_HEADER_HEIGHT + 2 * LANE_PADDING };
  });
  return { positions, bands };
}
