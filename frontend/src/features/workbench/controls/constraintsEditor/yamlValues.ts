/**
 * How scalar values are written to YAML and how the backend reads them back.
 *
 * The browser parses with the `yaml` package (YAML 1.2), the backend with PyYAML `safe_load` (YAML 1.1).
 * They agree on ordinary values, but PyYAML reads `1e-3` and `1.0e3` as text and `010` as octal, so
 * numbers are written in a form both read the same way, and values that differ are flagged.
 */

import { stringify } from "yaml";

export type ScalarValue = number | boolean | string | null;

/** A number as PyYAML reads it: a dot in every float, a signed exponent. */
export function formatYamlNumber(value: number, asFloat: boolean): string {
  if (Number.isNaN(value)) {
    return ".nan";
  }
  if (!Number.isFinite(value)) {
    return value > 0 ? ".inf" : "-.inf";
  }
  const text = String(value);
  if (/e/i.test(text)) {
    const [mantissa, exponent] = text.toLowerCase().split("e");
    const dotted = mantissa.includes(".") ? mantissa : `${mantissa}.0`;
    const signed = /^[-+]/.test(exponent) ? exponent : `+${exponent}`;
    return `${dotted}e${signed}`;
  }
  if (asFloat && !text.includes(".")) {
    return `${text}.0`;
  }
  return text;
}

/** A string as a single YAML line, quoted only when it would otherwise be read as something else. */
export function formatYamlString(value: string): string {
  const flat = value.replace(/\r?\n/g, " ");
  if (flat === "") {
    return '""';
  }
  return stringify(flat, { lineWidth: 0, version: "1.1" }).trimEnd();
}

export function formatYamlScalar(value: ScalarValue, asFloat: boolean): string {
  if (value === null) {
    return "null";
  }
  if (typeof value === "number") {
    return formatYamlNumber(value, asFloat);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return formatYamlString(value);
}

const PYYAML_INT = /^[-+]?(?:0b[01_]+|0[0-7_]+|(?:0|[1-9][0-9_]*)|0x[0-9a-fA-F_]+|[1-9][0-9_]*(?::[0-5]?[0-9])+)$/;
const PYYAML_FLOAT =
  /^(?:[-+]?[0-9][0-9_]*\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9_]+(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$/;

/** True when PyYAML reads the plain text as a number. */
export function pyYamlReadsNumber(source: string): boolean {
  return PYYAML_INT.test(source) || PYYAML_FLOAT.test(source);
}

const PYYAML_OCTAL = /^[-+]?0[0-7_]+$/;

/** True when PyYAML reads an integer-looking text as octal, so its value differs from the browser's. */
export function pyYamlReadsOctal(source: string): boolean {
  return PYYAML_OCTAL.test(source);
}

const PYYAML_WORDS = /^(?:yes|no|on|off)$/i;

/** Plain words that YAML 1.1 reads as booleans although YAML 1.2 keeps them as text. */
export function isYaml11BooleanWord(source: string): boolean {
  return PYYAML_WORDS.test(source);
}

const NUMBER_TEXT = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/;

/** The number a typed text stands for, or null when it is not a number. */
export function parseTypedNumber(text: string): number | null {
  const trimmed = text.trim();
  if (!NUMBER_TEXT.test(trimmed)) {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}
