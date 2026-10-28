import { Fragment, type ReactNode } from "react";
import { formatScalar, humanizeKey, sortKeys } from "./frameDataFormat";
import { renderRelationId } from "./renderRelationId";

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

interface DynamicValueProps {
  value: unknown;
  depth: number;
}

export function DynamicValue({ value, depth }: DynamicValueProps): ReactNode {
  if (value === null || value === undefined) {
    return <span className="frame-dyn-empty">:</span>;
  }
  if (typeof value === "string" && value.includes("->")) {
    return <span className="frame-dyn-scalar">{renderRelationId(value)}</span>;
  }
  if (typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    return <span className="frame-dyn-scalar">{formatScalar(value)}</span>;
  }
  if (typeof value === "bigint") {
    return <span className="frame-dyn-scalar">{value.toString()}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="frame-dyn-empty">[]</span>;
    }
    if (depth >= 2 || value.length > 12) {
      return <span className="frame-dyn-folded">[{value.length} items]</span>;
    }
    const allScalar = value.every(
      (item) =>
        item === null ||
        typeof item === "boolean" ||
        typeof item === "number" ||
        typeof item === "string"
    );
    if (allScalar) {
      return (
        <span className="frame-dyn-scalar frame-dyn-inline-list">
          {value.map((item) => formatScalar(item)).join(", ")}
        </span>
      );
    }
    return (
      <ul className="frame-dyn-nested-list">
        {value.slice(0, 8).map((item, i) => (
          <li key={i}>
            <DynamicValue value={item} depth={depth + 1} />
          </li>
        ))}
        {value.length > 8 ? (
          <li className="meta">+{value.length - 8} more…</li>
        ) : null}
      </ul>
    );
  }
  if (isPlainObject(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      return <span className="frame-dyn-empty">{"{}"}</span>;
    }
    if (depth >= 2) {
      return <span className="frame-dyn-folded">{`{${entries.length} fields}`}</span>;
    }
    return (
      <DynamicFieldGrid
        data={value}
        depth={depth + 1}
        className="frame-kv-grid frame-kv-grid--nested"
      />
    );
  }
  return <span className="frame-dyn-scalar">{String(value)}</span>;
}

interface DynamicFieldGridProps {
  data: Record<string, unknown>;
  /** Nesting depth for folding large structures. */
  depth?: number;
  omitKeys?: Set<string>;
  priorityKeys?: readonly string[];
  className?: string;
}

export function DynamicFieldGrid({
  data,
  depth = 0,
  omitKeys = new Set(),
  priorityKeys = [],
  className = "frame-kv-grid",
}: DynamicFieldGridProps) {
  const keys = Object.keys(data).filter((k) => !omitKeys.has(k) && data[k] !== undefined);
  if (keys.length === 0) {
    return <p className="meta frame-dyn-empty">No fields</p>;
  }
  const sorted = priorityKeys.length > 0 ? sortKeys(keys, priorityKeys) : sortKeys(keys, []);

  return (
    <dl className={className}>
      {sorted.map((key) => (
        <Fragment key={key}>
          <dt className="frame-kv-label">
            {key.includes("->") ? renderRelationId(key) : humanizeKey(key)}
          </dt>
          <dd className="frame-kv-value">
            {key === "relationId" && typeof data[key] === "string" ? (
              <span className="frame-dyn-scalar">{renderRelationId(data[key] as string)}</span>
            ) : (
              <DynamicValue value={data[key]} depth={depth} />
            )}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}
