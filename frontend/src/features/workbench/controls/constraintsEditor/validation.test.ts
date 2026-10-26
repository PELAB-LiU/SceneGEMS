import { describe, expect, it } from "vitest";
import { buildConstraintsModel, flattenScalarFields, type ScalarFieldModel, type TableModel } from "./fieldModel";
import { VESSEL_TYPES } from "./domainFiles.fixture";
import { applyEdit } from "./yamlEdit";
import { impliesNonNegative, keyWords } from "./validation";

function fieldsOf(text: string): Record<string, ScalarFieldModel> {
  const model = buildConstraintsModel(text);
  if (!model.ok) {
    throw new Error("parse failure");
  }
  return Object.fromEntries(flattenScalarFields(model.root).map((field) => [field.key, field]));
}

function messages(field: ScalarFieldModel): string[] {
  return field.issues.map((issue) => issue.message);
}

describe("keyWords", () => {
  it("splits snake, upper and camel case", () => {
    expect(keyWords("min_length")).toEqual(["min", "length"]);
    expect(keyWords("MAX_SPEED")).toEqual(["max", "speed"]);
    expect(keyWords("maxAngularSpeed")).toEqual(["max", "angular", "speed"]);
  });
});

describe("non-negative values", () => {
  it("flags a negative value when the unit says it cannot be negative", () => {
    const fields = fieldsOf("TIMEOUT: -5 # Wait (seconds)\n");
    expect(fields.TIMEOUT.issues).toHaveLength(1);
    expect(fields.TIMEOUT.issues[0].severity).toBe("warning");
  });

  it("flags a negative value when the name says so", () => {
    expect(fieldsOf("min_length: -1\n").min_length.issues).toHaveLength(1);
    expect(fieldsOf("max_speed: -0.5\n").max_speed.issues).toHaveLength(1);
  });

  it("flags a negative value when the comment says so", () => {
    expect(fieldsOf("x: -1 # Maximum heading change\n").x.issues).toHaveLength(1);
  });

  it("accepts negative angles and values with no implication", () => {
    expect(fieldsOf("offset: -1.5 # Heading offset (radians)\n").offset.issues).toEqual([]);
    expect(fieldsOf("bias: -3\n").bias.issues).toEqual([]);
  });

  it("accepts zero and positive values", () => {
    expect(fieldsOf("min_length: 0\n").min_length.issues).toEqual([]);
  });

  it("tells whether a field implies non-negative", () => {
    expect(impliesNonNegative({ key: "x", comment: "", unit: "meters" })).toBe(true);
    expect(impliesNonNegative({ key: "x", comment: "", unit: "degrees" })).toBe(false);
    expect(impliesNonNegative({ key: "TIME_STEP", comment: "", unit: null })).toBe(true);
  });
});

describe("min and max pairs", () => {
  it("flags both fields when min is greater than max", () => {
    const fields = fieldsOf("min_length: 50\nmax_length: 10\n");
    expect(messages(fields.min_length)).toEqual(["min_length is greater than max_length."]);
    expect(messages(fields.max_length)).toEqual(["max_length is smaller than min_length."]);
  });

  it("accepts min equal to max, as the vessel types use", () => {
    const fields = fieldsOf("min_length: 30\nmax_length: 30\n");
    expect(fields.min_length.issues).toEqual([]);
    expect(fields.max_length.issues).toEqual([]);
  });

  it("pairs other spellings", () => {
    expect(fieldsOf("length_min: 5\nlength_max: 1\n").length_min.issues).toHaveLength(1);
    expect(fieldsOf("minSpeed: 5\nmaxSpeed: 1\n").minSpeed.issues).toHaveLength(1);
    expect(fieldsOf("MINIMUM_RANGE: 5\nMAXIMUM_RANGE: 1\n").MINIMUM_RANGE.issues).toHaveLength(1);
  });

  it("does not pair unrelated keys", () => {
    const fields = fieldsOf("min_length: 50\nmax_beam: 10\n");
    expect(fields.min_length.issues).toEqual([]);
  });

  it("works across the sections of a group", () => {
    const text = "# A\nmin_x: 9\n\n# B\nmax_x: 1\n";
    expect(fieldsOf(text).min_x.issues).toHaveLength(1);
  });

  it("flags a row of a table and nothing else", () => {
    const broken = applyEdit(VESSEL_TYPES, { kind: "set", path: ["Tanker", "min_length"], value: 900 });
    expect(broken.ok).toBe(true);
    const model = buildConstraintsModel(broken.ok ? broken.text : "");
    const table = (model.ok ? model.root : null) as TableModel;
    const flagged = table.rows.filter((row) => row.cells.some((cell) => cell && cell.issues.length > 0));
    expect(flagged.map((row) => row.key)).toEqual(["Tanker"]);
  });
});

describe("types in a table column", () => {
  it("flags text among numbers", () => {
    const text = "A:\n  x: 1\nB:\n  x: 2\nC:\n  x: three\n";
    const model = buildConstraintsModel(text);
    const table = (model.ok ? model.root : null) as TableModel;
    expect(table.rows[2].cells[0]?.issues[0].severity).toBe("error");
    expect(table.rows[0].cells[0]?.issues).toEqual([]);
  });

  it("does not flag an integer among floats", () => {
    const text = "A:\n  x: 1.5\nB:\n  x: 2\n";
    const model = buildConstraintsModel(text);
    const table = (model.ok ? model.root : null) as TableModel;
    expect(table.rows.every((row) => row.cells[0]?.issues.length === 0)).toBe(true);
  });
});

describe("what the backend reads differently", () => {
  it("warns about numbers PyYAML reads as text", () => {
    const fields = fieldsOf("a: 1e-3\nb: 1.0e3\nc: 1.0e-3\nd: 0.001\n");
    expect(messages(fields.a)[0]).toContain("reads 1e-3 as text");
    expect(messages(fields.b)[0]).toContain("as text");
    expect(fields.c.issues).toEqual([]);
    expect(fields.d.issues).toEqual([]);
  });

  it("warns about octal and boolean words", () => {
    expect(messages(fieldsOf("a: 010\n").a)[0]).toContain("octal");
    expect(messages(fieldsOf("a: yes\n").a)[0]).toContain("boolean");
    expect(fieldsOf("a: true\n").a.issues).toEqual([]);
  });

  it("flags values that are not finite", () => {
    expect(fieldsOf("a: .inf\n").a.issues.some((issue) => issue.severity === "error")).toBe(true);
    expect(fieldsOf("a: .nan\n").a.issues.some((issue) => issue.severity === "error")).toBe(true);
  });
});
