/**
 * Edits of a constraints YAML text, text in and text out.
 *
 * A value edit replaces just the characters of that value, so the rest of the file stays byte for byte
 * as it was: comments, their spacing, key order, blank lines, line endings. Structural edits (rows and
 * list items added, duplicated, renamed or removed) go through the `yaml` Document and are written with
 * `toString()`, which keeps comments and order but normalises whitespace: a comment follows its value
 * after one space, runs of blank lines become one. The indent and the line ending of the original are kept.
 */

import { isMap, isNode, isScalar, isSeq, Pair, Scalar, type Document, type YAMLMap, type YAMLSeq } from "yaml";
import { parseConstraintsDocument, type YamlPath } from "./fieldModel";
import { formatYamlScalar, type ScalarValue } from "./yamlValues";

export type YamlEdit =
  /** Sets one scalar. A missing key is created. `asFloat` keeps a whole number written with a dot. */
  | { kind: "set"; path: YamlPath; value: ScalarValue; asFloat?: boolean }
  /** Adds a row to the map at `path`, as a copy of the row `templateKey`. */
  | { kind: "addRow"; path: YamlPath; templateKey: string; newKey: string }
  /** Adds a copy of the row `key` right after it. */
  | { kind: "duplicateRow"; path: YamlPath; key: string; newKey: string }
  | { kind: "renameRow"; path: YamlPath; key: string; newKey: string }
  | { kind: "removeRow"; path: YamlPath; key: string }
  /** Adds a copy of the last item to the list at `path`. */
  | { kind: "addItem"; path: YamlPath }
  | { kind: "removeItem"; path: YamlPath; index: number };

export type EditResult = { ok: true; text: string } | { ok: false; error: string };

const ROW_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** Names that a row can be given: letters, digits and underscores, so YAML reads the key as text. */
export function validateRowName(name: string, existing: readonly string[], ignore?: string): string | null {
  if (!ROW_NAME.test(name)) {
    return "Use letters, digits and underscores, starting with a letter.";
  }
  if (name !== ignore && existing.includes(name)) {
    return `A row named ${name} exists already.`;
  }
  return null;
}

/** A name for a copy of `base` that no row has yet: `CargoShipCopy`, `CargoShipCopy2`, ... */
export function suggestRowName(base: string, existing: readonly string[]): string {
  const stem = base.replace(/Copy\d*$/, "") + "Copy";
  if (!existing.includes(stem)) {
    return stem;
  }
  let counter = 2;
  while (existing.includes(`${stem}${counter}`)) {
    counter += 1;
  }
  return `${stem}${counter}`;
}

function nodeAt(doc: Document.Parsed, path: YamlPath): unknown {
  return path.length === 0 ? doc.contents : doc.getIn(path, true);
}

function mapAt(doc: Document.Parsed, path: YamlPath): YAMLMap | null {
  const node = nodeAt(doc, path);
  return isMap(node) ? node : null;
}

function seqAt(doc: Document.Parsed, path: YamlPath): YAMLSeq | null {
  const node = nodeAt(doc, path);
  return isSeq(node) ? node : null;
}

function findPairIndex(map: YAMLMap, key: string): number {
  return map.items.findIndex((pair) => isScalar(pair.key) && String(pair.key.value) === key);
}

function detectIndent(text: string): number {
  const match = /^( +)\S/m.exec(text);
  return match ? match[1].length : 2;
}

function serialize(doc: Document.Parsed, original: string): string {
  let out = doc.toString({ indent: detectIndent(original), lineWidth: 0 });
  if (!/\n$/.test(original)) {
    out = out.replace(/\r?\n$/, "");
  }
  if (original.includes("\r\n")) {
    out = out.replace(/\r?\n/g, "\r\n");
  }
  return out;
}

function stripComments(node: unknown): void {
  if (!isNode(node)) {
    return;
  }
  node.comment = undefined;
  node.commentBefore = undefined;
  node.spaceBefore = undefined;
  if (isMap(node) || isSeq(node)) {
    for (const item of node.items) {
      if (item instanceof Pair) {
        stripComments(item.key);
        stripComments(item.value);
      } else {
        stripComments(item);
      }
    }
  }
}

/** Whether the rows of this map are separated by blank lines, so that a new row gets one too. */
function rowsAreSpaced(map: YAMLMap): boolean {
  return map.items.slice(1).some((pair) => isNode(pair.key) && pair.key.spaceBefore === true);
}

function insertRow(map: YAMLMap, at: number, newKey: string, source: Pair): void {
  const value = isNode(source.value) ? source.value.clone() : new Scalar(null);
  stripComments(value);
  const key = new Scalar(newKey);
  if (rowsAreSpaced(map)) {
    key.spaceBefore = true;
  }
  map.items.splice(at, 0, new Pair(key, value));
}

function valueNodeText(text: string, node: Scalar): { start: number; end: number } | null {
  const range = node.range;
  if (!range || node.anchor || node.tag) {
    return null;
  }
  if (node.type === "BLOCK_FOLDED" || node.type === "BLOCK_LITERAL") {
    return null;
  }
  const [start, end] = range;
  if (start >= end || end > text.length || text.slice(start, end).includes("\n")) {
    return null;
  }
  return { start, end };
}

function applySet(text: string, doc: Document.Parsed, edit: Extract<YamlEdit, { kind: "set" }>): EditResult {
  const existing = nodeAt(doc, edit.path);
  if (isScalar(existing)) {
    // The same value in another spelling (0.10 and 0.1) is not an edit: the text stays as written.
    if (existing.value === edit.value) {
      return { ok: true, text };
    }
    const span = valueNodeText(text, existing);
    if (span) {
      const replacement = formatYamlScalar(edit.value, edit.asFloat ?? false);
      return { ok: true, text: text.slice(0, span.start) + replacement + text.slice(span.end) };
    }
    existing.value = edit.value;
    existing.source = undefined;
    existing.type = undefined;
    existing.minFractionDigits = edit.asFloat && typeof edit.value === "number" && Number.isInteger(edit.value) ? 1 : undefined;
    return { ok: true, text: serialize(doc, text) };
  }
  if (existing === undefined || existing === null) {
    if (edit.path.length === 0) {
      return { ok: false, error: "The document is empty." };
    }
    const scalar = new Scalar(edit.value);
    if (edit.asFloat && typeof edit.value === "number" && Number.isInteger(edit.value)) {
      scalar.minFractionDigits = 1;
    }
    doc.setIn(edit.path, scalar);
    return { ok: true, text: serialize(doc, text) };
  }
  return { ok: false, error: "That part of the document is not a single value." };
}

export function applyEdit(text: string, edit: YamlEdit): EditResult {
  const doc = parseConstraintsDocument(text);
  if (doc.errors.length > 0) {
    return { ok: false, error: "The YAML does not parse." };
  }

  switch (edit.kind) {
    case "set":
      return applySet(text, doc, edit);

    case "addRow":
    case "duplicateRow": {
      const map = mapAt(doc, edit.path);
      if (!map) {
        return { ok: false, error: "There is no table at that place." };
      }
      const sourceKey = edit.kind === "addRow" ? edit.templateKey : edit.key;
      const index = findPairIndex(map, sourceKey);
      if (index < 0) {
        return { ok: false, error: `There is no row named ${sourceKey}.` };
      }
      const existing = map.items.map((pair) => String(isScalar(pair.key) ? pair.key.value : ""));
      const problem = validateRowName(edit.newKey, existing);
      if (problem) {
        return { ok: false, error: problem };
      }
      insertRow(map, edit.kind === "addRow" ? map.items.length : index + 1, edit.newKey, map.items[index]);
      return { ok: true, text: serialize(doc, text) };
    }

    case "renameRow": {
      const map = mapAt(doc, edit.path);
      const index = map ? findPairIndex(map, edit.key) : -1;
      if (!map || index < 0) {
        return { ok: false, error: `There is no row named ${edit.key}.` };
      }
      const existing = map.items.map((pair) => String(isScalar(pair.key) ? pair.key.value : ""));
      const problem = validateRowName(edit.newKey, existing, edit.key);
      if (problem) {
        return { ok: false, error: problem };
      }
      const key = map.items[index].key;
      if (isScalar(key)) {
        key.value = edit.newKey;
        key.source = undefined;
        key.type = undefined;
      }
      return { ok: true, text: serialize(doc, text) };
    }

    case "removeRow": {
      const map = mapAt(doc, edit.path);
      const index = map ? findPairIndex(map, edit.key) : -1;
      if (!map || index < 0) {
        return { ok: false, error: `There is no row named ${edit.key}.` };
      }
      map.items.splice(index, 1);
      return { ok: true, text: serialize(doc, text) };
    }

    case "addItem": {
      const seq = seqAt(doc, edit.path);
      if (!seq) {
        return { ok: false, error: "There is no list at that place." };
      }
      const last = seq.items[seq.items.length - 1];
      const copy = isNode(last) ? last.clone() : new Scalar(null);
      stripComments(copy);
      seq.items.push(copy);
      return { ok: true, text: serialize(doc, text) };
    }

    case "removeItem": {
      const seq = seqAt(doc, edit.path);
      if (!seq || edit.index < 0 || edit.index >= seq.items.length) {
        return { ok: false, error: "There is no such list item." };
      }
      seq.items.splice(edit.index, 1);
      return { ok: true, text: serialize(doc, text) };
    }
  }
}
