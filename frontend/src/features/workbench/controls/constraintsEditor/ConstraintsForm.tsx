import { useMemo, useState } from "react";
import { Disclosure } from "../../../../components/Disclosure";
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

function FieldView({ field, onEdit, nested, scope }: { field: FieldModel; onEdit: EditHandler; nested: boolean; scope: string }) {
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
          <GroupView group={field} onEdit={onEdit} scope={scope} />
        </details>
      ) : (
        <GroupView group={field} onEdit={onEdit} scope={scope} collapsible />
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
      return <ListView list={field} onEdit={onEdit} scope={scope} />;
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

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

/**
 * The sections of a group. At the top of a file with several titled sections, each section is a
 * disclosure (the first open, the others closed until asked for) so a long file is a short list of topics.
 */
function GroupView({ group, onEdit, scope, collapsible = false }: { group: GroupModel; onEdit: EditHandler; scope: string; collapsible?: boolean }) {
  const titled = group.sections.filter((section) => section.title).length;
  return (
    <div className="ce-sections">
      {group.sections.map((section, sectionIndex) => {
        const content = (
          <>
            {section.note ? <p className="ce-description">{section.note}</p> : null}
            {section.items.map((item) => (
              <FieldView key={pathId(item.path)} field={item} onEdit={onEdit} nested scope={scope} />
            ))}
          </>
        );
        if (collapsible && titled >= 2 && section.title) {
          const count = section.items.length;
          return (
            <Disclosure
              key={sectionIndex}
              id={`ce:${scope}:${slug(section.title)}`}
              title={section.title}
              hint={`${count} ${count === 1 ? "setting" : "settings"}`}
              defaultOpen={sectionIndex === 0}
              variant="card"
              headingLevel={4}
              keepMounted
              className="ce-section-disclosure"
            >
              <div className="ce-section">{content}</div>
            </Disclosure>
          );
        }
        return (
          <section key={sectionIndex} className="ce-section">
            {section.title ? <h5 className="ce-section-title">{section.title}</h5> : null}
            {content}
          </section>
        );
      })}
    </div>
  );
}

function ListView({ list, onEdit, scope }: { list: ListModel; onEdit: EditHandler; scope: string }) {
  return (
    <div className="ce-list">
      {list.label ? <h5 className="ce-section-title">{list.label}</h5> : null}
      {list.description ? <p className="ce-description">{list.description}</p> : null}
      {list.items.map((item, index) => (
        <div key={pathId(item.path)} className="ce-list-item">
          <div className="ce-list-item-body">
            <FieldView field={item} onEdit={onEdit} nested scope={scope} />
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
  /** Names the file in the remembered open or closed state of its sections, for example "colregs". */
  scope?: string;
  text: string;
  onTextChange: (text: string) => void;
  /** Called by the button of the parse error message. */
  onShowYaml?: () => void;
}

/** The form generated from the YAML text. Every edit writes the whole text back through `onTextChange`. */
export function ConstraintsForm({ scope = "constraints", text, onTextChange, onShowYaml, protectedRows, tableMinRows }: ConstraintsFormProps) {
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
      <FieldView field={model.root} onEdit={onEdit} nested={false} scope={scope} />
    </div>
  );
}
