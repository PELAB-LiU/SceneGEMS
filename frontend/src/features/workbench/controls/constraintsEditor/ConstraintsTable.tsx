import { useId, useState } from "react";
import type { TableModel, TableRow } from "./fieldModel";
import { IssueList, ScalarControl, type EditHandler } from "./ScalarControl";
import { alternateUnit, unitSymbol } from "./units";
import { suggestRowName, validateRowName } from "./yamlEdit";

type PendingAction = { mode: "duplicate" | "rename" | "remove"; rowKey: string; name: string };

interface Props {
  table: TableModel;
  onEdit: EditHandler;
}

export function ConstraintsTable({ table, onEdit }: Props) {
  const baseId = useId();
  const rowKeys = table.rows.map((row) => row.key);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [templateKey, setTemplateKey] = useState<string>("");
  const [newName, setNewName] = useState("");

  const effectiveTemplate = rowKeys.includes(templateKey) ? templateKey : (rowKeys[0] ?? "");
  const addProblem = newName === "" ? null : validateRowName(newName, rowKeys);
  const pendingProblem =
    pending && pending.mode !== "remove" ? validateRowName(pending.name, rowKeys, pending.mode === "rename" ? pending.rowKey : undefined) : null;

  const startAction = (mode: PendingAction["mode"], row: TableRow) => {
    setPending({ mode, rowKey: row.key, name: mode === "duplicate" ? suggestRowName(row.key, rowKeys) : row.key });
  };

  const confirmPending = () => {
    if (!pending) {
      return;
    }
    const path = table.path;
    if (pending.mode === "remove") {
      onEdit({ kind: "removeRow", path, key: pending.rowKey });
    } else if (pending.mode === "rename") {
      if (pending.name !== pending.rowKey) {
        onEdit({ kind: "renameRow", path, key: pending.rowKey, newKey: pending.name });
      }
    } else {
      onEdit({ kind: "duplicateRow", path, key: pending.rowKey, newKey: pending.name });
    }
    setPending(null);
  };

  return (
    <div className="ce-table-block">
      {table.description ? <p className="ce-description">{table.description}</p> : null}
      <IssueList issues={table.issues} />
      <div className="ce-table-scroll">
        <table className="ce-table">
          <thead>
            <tr>
              <th scope="col" className="ce-table-name-head">
                Name
              </th>
              {table.columns.map((column) => {
                const alternate = column.unit ? alternateUnit(column.unit) : null;
                return (
                  <th key={column.key} scope="col" title={[column.key, column.description].filter(Boolean).join(": ")}>
                    <span className="ce-column-label">{column.label}</span>
                    {column.unit ? (
                      <span className="ce-unit ce-column-unit">
                        {unitSymbol(column.unit)}
                        {alternate ? ` = ${alternate.symbol}` : ""}
                      </span>
                    ) : null}
                    {column.description ? <span className="ce-column-description">{column.description}</span> : null}
                  </th>
                );
              })}
              <th scope="col" className="ce-table-actions-head">
                <span className="ce-visually-hidden">Row actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <TableRowView
                key={row.key}
                row={row}
                table={table}
                pending={pending?.rowKey === row.key ? pending : null}
                pendingProblem={pendingProblem}
                onStart={startAction}
                onPendingName={(name) => setPending((current) => (current ? { ...current, name } : current))}
                onConfirm={confirmPending}
                onCancel={() => setPending(null)}
                onEdit={onEdit}
              />
            ))}
          </tbody>
        </table>
      </div>
      <div className="ce-add-row">
        <label htmlFor={`${baseId}-template`}>Add a type like</label>
        <select id={`${baseId}-template`} value={effectiveTemplate} onChange={(event) => setTemplateKey(event.target.value)}>
          {rowKeys.map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </select>
        <input
          type="text"
          className={`ce-input ce-text${addProblem ? " ce-flagged" : ""}`}
          value={newName}
          placeholder="New name"
          aria-label="Name of the new row"
          onChange={(event) => setNewName(event.target.value)}
        />
        <button
          type="button"
          disabled={newName === "" || addProblem !== null || effectiveTemplate === ""}
          onClick={() => {
            onEdit({ kind: "addRow", path: table.path, templateKey: effectiveTemplate, newKey: newName });
            setNewName("");
          }}
        >
          Add
        </button>
        {addProblem ? <span className="ce-issue ce-issue-error">{addProblem}</span> : null}
      </div>
    </div>
  );
}

interface RowProps {
  row: TableRow;
  table: TableModel;
  pending: PendingAction | null;
  pendingProblem: string | null;
  onStart: (mode: PendingAction["mode"], row: TableRow) => void;
  onPendingName: (name: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  onEdit: EditHandler;
}

function TableRowView({ row, table, pending, pendingProblem, onStart, onPendingName, onConfirm, onCancel, onEdit }: RowProps) {
  return (
    <>
      <tr>
        <th scope="row" className="ce-table-name" title={row.note ?? undefined}>
          <span className="ce-row-name">{row.key}</span>
          {row.protected ? <span className="ce-badge" title="The backend looks this row up by name">required</span> : null}
          {row.note ? <span className="ce-row-note">{row.note}</span> : null}
        </th>
        {table.columns.map((column, index) => {
          const cell = row.cells[index];
          return (
            <td key={column.key}>
              {cell ? (
                <>
                  <ScalarControl field={cell} onEdit={onEdit} ariaLabel={`${row.key} ${column.key}`} showUnits={false} />
                  <IssueList issues={cell.issues} />
                </>
              ) : (
                <span className="ce-missing" title={`${row.key} has no ${column.key}`}>
                  missing
                </span>
              )}
            </td>
          );
        })}
        <td className="ce-row-actions">
          <button type="button" onClick={() => onStart("duplicate", row)} title={`Duplicate ${row.key}`}>
            Duplicate
          </button>
          <button type="button" onClick={() => onStart("rename", row)} disabled={row.protected} title={row.protected ? "The backend looks this row up by name" : `Rename ${row.key}`}>
            Rename
          </button>
          <button type="button" onClick={() => onStart("remove", row)} disabled={row.protected} title={row.protected ? "The backend looks this row up by name" : `Remove ${row.key}`}>
            Remove
          </button>
        </td>
      </tr>
      {pending ? (
        <tr className="ce-pending-row">
          <td colSpan={table.columns.length + 2}>
            {pending.mode === "remove" ? (
              <span className="ce-pending">
                Remove {pending.rowKey} from the YAML?
                <button type="button" onClick={onConfirm}>
                  Remove
                </button>
                <button type="button" onClick={onCancel}>
                  Keep
                </button>
              </span>
            ) : (
              <span className="ce-pending">
                {pending.mode === "duplicate" ? `Name of the copy of ${pending.rowKey}` : `New name of ${pending.rowKey}`}
                <input
                  type="text"
                  className={`ce-input ce-text${pendingProblem ? " ce-flagged" : ""}`}
                  value={pending.name}
                  aria-label="Row name"
                  autoFocus
                  onChange={(event) => onPendingName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !pendingProblem) {
                      onConfirm();
                    } else if (event.key === "Escape") {
                      onCancel();
                    }
                  }}
                />
                <button type="button" onClick={onConfirm} disabled={pendingProblem !== null}>
                  {pending.mode === "duplicate" ? "Duplicate" : "Rename"}
                </button>
                <button type="button" onClick={onCancel}>
                  Cancel
                </button>
                {pendingProblem ? <span className="ce-issue ce-issue-error">{pendingProblem}</span> : null}
              </span>
            )}
          </td>
        </tr>
      ) : null}
    </>
  );
}
