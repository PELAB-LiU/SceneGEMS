/**
 * Checks on the values of the field model. They flag problems (an issue on the field) and never block an
 * edit: the YAML always keeps what the user wrote.
 */

import type { ScalarFieldModel, TableColumn } from "./fieldModel";
import { isMagnitudeUnit } from "./units";
import { isYaml11BooleanWord, pyYamlReadsNumber, pyYamlReadsOctal } from "./yamlValues";

export interface FieldIssue {
  severity: "error" | "warning";
  message: string;
}

/** The lower-case words of a key: `min_length`, `MIN_LENGTH` and `minLength` all give `min`, `length`. */
export function keyWords(key: string): string[] {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .split(/[\s_\-.]+/)
    .map((word) => word.toLowerCase())
    .filter((word) => word.length > 0);
}

const NON_NEGATIVE_KEY_WORDS = new Set([
  "min",
  "max",
  "minimum",
  "maximum",
  "time",
  "duration",
  "length",
  "beam",
  "speed",
  "radius",
  "distance",
  "acceleration",
  "persistence",
  "period",
  "size",
  "mass",
  "width",
  "height",
  "depth",
  "draft",
  "count",
  "interval",
  "timeout",
  "delay",
]);

const NON_NEGATIVE_COMMENT_WORDS = /\b(minimum|maximum|duration|distance|length|radius|size|persist)\b/i;

/** True where the name, the comment or the unit says the value is a size, a time, a rate or a limit. */
export function impliesNonNegative(field: Pick<ScalarFieldModel, "key" | "comment" | "unit">): boolean {
  if (field.unit !== null && isMagnitudeUnit(field.unit)) {
    return true;
  }
  if (keyWords(field.key).some((word) => NON_NEGATIVE_KEY_WORDS.has(word))) {
    return true;
  }
  return NON_NEGATIVE_COMMENT_WORDS.test(field.comment);
}

/** Issues of one value on its own. */
export function validateFieldValue(field: ScalarFieldModel): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (field.kind === "number" || field.kind === "integer") {
    const value = field.value as number;
    if (!Number.isFinite(value)) {
      issues.push({ severity: "error", message: "The value is not a finite number." });
    } else if (value < 0 && impliesNonNegative(field)) {
      issues.push({ severity: "warning", message: "The name, comment or unit says this cannot be negative." });
    }
    if (!pyYamlReadsNumber(field.source) && Number.isFinite(value)) {
      issues.push({
        severity: "warning",
        message: `The backend reads ${field.source} as text, not as a number. Write it with a dot and a signed exponent, for example 1.0e-3.`,
      });
    } else if (pyYamlReadsOctal(field.source)) {
      issues.push({
        severity: "warning",
        message: `The backend reads ${field.source} as an octal number. Remove the leading zero.`,
      });
    }
  } else if (field.kind === "string" && isYaml11BooleanWord(String(field.value))) {
    issues.push({ severity: "warning", message: `The backend reads ${field.value} as a boolean, not as text.` });
  }
  return issues;
}

type MinMaxRole = "min" | "max";

function minMaxRole(key: string): { role: MinMaxRole; stem: string } | null {
  const words = keyWords(key);
  if (words.length < 2) {
    return null;
  }
  const roleOf = (word: string): MinMaxRole | null => {
    if (word === "min" || word === "minimum") {
      return "min";
    }
    if (word === "max" || word === "maximum") {
      return "max";
    }
    return null;
  };
  const leading = roleOf(words[0]);
  if (leading) {
    return { role: leading, stem: words.slice(1).join("_") };
  }
  const trailing = roleOf(words[words.length - 1]);
  if (trailing) {
    return { role: trailing, stem: words.slice(0, -1).join("_") };
  }
  return null;
}

/** Flags a `min_x` that is greater than its `max_x` among sibling fields, on both of them. */
export function validateMinMaxPairs(fields: ScalarFieldModel[]): void {
  const lows = new Map<string, ScalarFieldModel>();
  const highs = new Map<string, ScalarFieldModel>();
  for (const field of fields) {
    const role = minMaxRole(field.key);
    if (!role) {
      continue;
    }
    (role.role === "min" ? lows : highs).set(role.stem, field);
  }
  for (const [stem, low] of lows) {
    const high = highs.get(stem);
    if (!high || typeof low.value !== "number" || typeof high.value !== "number") {
      continue;
    }
    if (low.value > high.value) {
      low.issues.push({ severity: "warning", message: `${low.key} is greater than ${high.key}.` });
      high.issues.push({ severity: "warning", message: `${high.key} is smaller than ${low.key}.` });
    }
  }
}

function category(kind: TableColumn["kind"]): string {
  return kind === "integer" ? "number" : kind;
}

/** Flags cells whose kind differs from the rest of their column, such as text among numbers. */
export function validateTableColumn(column: TableColumn, cells: (ScalarFieldModel | null)[]): void {
  const expected = category(column.kind);
  for (const cell of cells) {
    if (cell && category(cell.kind) !== expected && cell.kind !== "null") {
      cell.issues.push({
        severity: "error",
        message: `The other rows hold ${expected === "number" ? "numbers" : expected} in ${column.key}; this one holds ${category(cell.kind)}.`,
      });
    }
  }
}
