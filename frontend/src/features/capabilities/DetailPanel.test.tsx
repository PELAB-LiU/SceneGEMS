import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { sampleStackDocument } from "../../test/fixtures/architectureDocuments";
import { DetailPanel } from "./DetailPanel";
import { MatrixView } from "./MatrixView";

const document = sampleStackDocument();

function panel(view: "concrete" | "metamodel", selection: { kind: "node" | "edge"; id: string } | null) {
  return renderToStaticMarkup(<DetailPanel document={document} view={view} selection={selection} onShow={vi.fn()} />);
}

describe("DetailPanel", () => {
  it("shows the whole document when nothing is selected", () => {
    const html = panel("concrete", null);
    expect(html).toContain("A stack of three layers.");
    expect(html).toContain("6");
    expect(html).toContain("4 of 6");
    expect(html).toContain("A note on the stack.");
    expect(html).not.toContain("Back to the overview");
  });

  it("describes a selected implementation with its values, where they come from and the stacks through it", () => {
    const html = panel("concrete", { kind: "node", id: "bottom/e" });
    expect(html).toContain("Back to the overview");
    expect(html).toContain("Implements bottom layer");
    expect(html).toContain("measured");
    expect(html).toContain("declared");
    expect(html).toContain("How it was measured");
    expect(html).toContain("Available stacks through it (2)");
    expect(html).toContain("a · c · e");
  });

  it("marks a planned implementation and one that no stack uses", () => {
    const html = panel("concrete", { kind: "node", id: "middle/d" });
    expect(html).toContain("planned");
    expect(html).toContain("No stack uses it yet.");
  });

  it("describes an adapter with its ends and says when it is an alternative", () => {
    const html = panel("concrete", { kind: "edge", id: "a_to_c_alt" });
    expect(html).toContain("a to c");
    expect(html).toContain("alternative");
    expect(html).toContain("Implements upper adapter");
  });

  it("gives the reason of a ruled-out connection", () => {
    const html = panel("concrete", { kind: "edge", id: "ruled-out:middle/d>bottom/e" });
    expect(html).toContain("Ruled out");
    expect(html).toContain("d has no adapter to e");
  });

  it("tells what a metamodel node asks of an implementation, how to add one and who implements it", () => {
    const html = panel("metamodel", { kind: "node", id: "stack/layer/middle" });
    expect(html).toContain("An implementation provides");
    expect(html).toContain("middle.run()");
    expect(html).toContain("Add a middle.");
    expect(html).toContain("pkg/middle.py");
    expect(html).toContain("Implemented by");
    expect(html).toContain(">c<");
    expect(html).toContain(">d<");
  });

  it("tells what a generic adapter asks and which adapters implement it", () => {
    const html = panel("metamodel", { kind: "edge", id: "stack/adapter/lower" });
    expect(html).toContain("Generic adapter");
    expect(html).toContain("c to e");
    expect(html).toContain("c to f");
  });
});

describe("MatrixView", () => {
  it("shows every combination, the weakest link of the available ones and why the others are not possible", () => {
    const html = renderToStaticMarkup(<MatrixView document={document} />);
    expect(html).toContain("available");
    expect(html).toContain("not possible");
    expect(html).toContain("planned");
    expect(html).toContain("d has no adapter to e");
    expect(html).toContain("exact");
    expect(html).toContain("wind unsupported");
    expect(html).toContain("waves supported");
    expect((html.match(/<tr>/g) ?? []).length).toBe(1 + 4);
  });

  it("says so when a document has no matrix", () => {
    const html = renderToStaticMarkup(<MatrixView document={{ ...document, combinations: [] }} />);
    expect(html).toContain("no availability matrix");
  });
});
