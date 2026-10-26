import { useMemo, useState } from "react";
import { ConstraintsTable } from "./ConstraintsTable";
import { buildConstraintsModel, type FieldModel, type GroupModel, type ListModel, type ModelOptions, type ScalarFieldModel } from "./fieldModel";
import { IssueList, ScalarControl, type EditHandler } from "./ScalarControl";
import { applyEdit } from "./yamlEdit";

function pathId(path: ReadonlyArray<string | number>): string {
  return path.join(".");
}

function ScalarFieldRow({ field, onEdit, ariaLabel }: { field: ScalarFieldModel; onEdit: EditHandler; ariaLabel: string }) {
  return (
    <div className="ce-field">
      <div className="ce-label" title={field.comment || undefined}>
        <span className="ce-label-text">{field.label}</span>
        <code className="ce-key">{field.key}</code>
      </div>
      <div className="ce-control">
        <ScalarControl field={field} onEdit={onEdit} ariaLabel={ariaLabel} showUnits />
      </div>
      {field.description || field.hint ? (
        <p className="ce-description">
          {field.description}
          {field.hint ? <span className="ce-hint"> ({field.hint})</span> : null}
        </p>
      ) : null}
      <IssueList issues={field.issues} />
    </div>
  );
}

function FieldView({ field, onEdit, nested }: { field: FieldModel; onEdit: EditHandler; nested: boolean }) {
  switch (field.nodeType) {
    case "scalar":
      return <ScalarFieldRow field={field} onEdit={onEdit} ariaLabel={field.label || field.key} />;
    case "group":
      return nested ? (
        <details className="ce-group" open>
          <summary>
            {field.label} <code className="ce-key">{field.key}</code>
          </summary>
          {field.description ? <p className="ce-description">{field.description}</p> : null}
          <GroupView group={field} onEdit={onEdit} />
        </details>
      ) : (
        <GroupView group={field} onEdit={onEdit} />
      );
    case "table":
      return nested ? (
        <details className="ce-group" open>
          <summary>
            {field.label} <code className="ce-key">{field.key}</code>
          </summary>
          <ConstraintsTable table={field} onEdit={onEdit} />
        </details>
      ) : (
        <ConstraintsTable table={field} onEdit={onEdit} />
      );
    case "list":
      return <ListView list={field} onEdit={onEdit} />;
    case "empty":
      return (
        <p className="ce-empty">
          {field.label ? <strong>{field.label} </strong> : null}
          <code>{field.flow}</code> holds nothing yet. Add entries in the YAML tab.
        </p>
      );
    case "raw":
      return (
        <div className="ce-raw">
          <strong>{field.label || "Value"}</strong> cannot be edited in the form. Edit it in the YAML tab.
          <pre>{field.source}</pre>
        </div>
      );
  }
}

function GroupView({ group, onEdit }: { group: GroupModel; onEdit: EditHandler }) {
  return (
    <div className="ce-sections">
      {group.sections.map((section, sectionIndex) => (
        <section key={sectionIndex} className="ce-section">
          {section.title ? <h5 className="ce-section-title">{section.title}</h5> : null}
          {section.note ? <p className="ce-description">{section.note}</p> : null}
          {section.items.map((item) => (
            <FieldView key={pathId(item.path)} field={item} onEdit={onEdit} nested />
          ))}
        </section>
      ))}
    </div>
  );
}

function ListView({ list, onEdit }: { list: ListModel; onEdit: EditHandler }) {
  return (
    <div className="ce-list">
      {list.label ? <h5 className="ce-section-title">{list.label}</h5> : null}
      {list.description ? <p className="ce-description">{list.description}</p> : null}
      {list.items.map((item, index) => (
        <div key={pathId(item.path)} className="ce-list-item">
          <div className="ce-list-item-body">
            <FieldView field={item} onEdit={onEdit} nested />
          </div>
          <button type="button" onClick={() => onEdit({ kind: "removeItem", path: list.path, index })}>
            Remove
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onEdit({ kind: "addItem", path: list.path })}>
        Add item
      </button>
    </div>
  );
}

export interface ConstraintsFormProps extends ModelOptions {
  text: string;
  onTextChange: (text: string) => void;
  /** Called by the button of the parse error message. */
  onShowYaml?: () => void;
}

/** The form generated from the YAML text. Every edit writes the whole text back through `onTextChange`. */
export function ConstraintsForm({ text, onTextChange, onShowYaml, protectedRows, tableMinRows }: ConstraintsFormProps) {
  const model = useMemo(() => buildConstraintsModel(text, { protectedRows, tableMinRows }), [text, protectedRows, tableMinRows]);
  const [editError, setEditError] = useState<string | null>(null);

  const onEdit: EditHandler = (edit) => {
    const result = applyEdit(text, edit);
    if (result.ok) {
      setEditError(null);
      if (result.text !== text) {
        onTextChange(result.text);
      }
    } else {
      setEditError(result.error);
    }
  };

  if (!model.ok) {
    const { message, line, column } = model.error;
    return (
      <div className="ce-form ce-parse-error" role="alert">
        <p>
          <strong>The YAML does not parse, so the form cannot show it.</strong>
        </p>
        <p>
          {message}
          {line !== null ? ` (line ${line}${column !== null ? `, column ${column}` : ""})` : ""}
        </p>
        {onShowYaml ? (
          <button type="button" onClick={onShowYaml}>
            Fix it in the YAML tab
          </button>
        ) : (
          <p>Fix it in the YAML text.</p>
        )}
      </div>
    );
  }

  if (model.root === null) {
    return (
      <div className="ce-form">
        <p className="ce-empty">The text is empty. Load a preset or a file, or type YAML in the YAML tab.</p>
      </div>
    );
  }

  return (
    <div className="ce-form">
      {model.header ? (
        <details className="ce-header">
          <summary>About this file</summary>
          <pre>{model.header}</pre>
        </details>
      ) : null}
      {model.issueCount > 0 ? (
        <p className="ce-issue ce-issue-warning ce-summary">
          {model.issueCount} {model.issueCount === 1 ? "value needs" : "values need"} a look. Nothing is blocked.
        </p>
      ) : null}
      {editError ? (
        <p className="ce-issue ce-issue-error" role="alert">
          {editError}
        </p>
      ) : null}
      <FieldView field={model.root} onEdit={onEdit} nested={false} />
    </div>
  );
}
