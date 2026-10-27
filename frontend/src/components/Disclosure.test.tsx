import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../test/memoryStorage";

// zustand's persist takes window.localStorage when the store is created, so the modules load after the stubs.
const storage = new MemoryStorage();
let Disclosure: typeof import("./Disclosure").Disclosure;
let store: typeof import("./disclosureStore");

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage });
  store = await import("./disclosureStore");
  ({ Disclosure } = await import("./Disclosure"));
});

afterAll(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  storage.clear();
  store.useDisclosureStore.setState({ open: {} });
});

describe("Disclosure", () => {
  it("is closed by default: the toggle says so and the content is not rendered", () => {
    const html = renderToStaticMarkup(
      <Disclosure title="Advanced">
        <p>secret detail</p>
      </Disclosure>
    );
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("Advanced");
    expect(html).not.toContain("secret detail");
    expect(html).toContain("hidden");
  });

  it("renders the content when open by default", () => {
    const html = renderToStaticMarkup(
      <Disclosure title="Advanced" defaultOpen>
        <p>visible detail</p>
      </Disclosure>
    );
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain("visible detail");
  });

  it("links the toggle to its region for assistive technology", () => {
    const html = renderToStaticMarkup(<Disclosure title="Options">x</Disclosure>);
    const controls = /aria-controls="([^"]+)"/.exec(html)?.[1];
    const labelledBy = /aria-labelledby="([^"]+)"/.exec(html)?.[1];
    const toggleId = /<button[^>]*id="([^"]+)"/.exec(html)?.[1];
    expect(controls).toBeDefined();
    expect(html).toContain(`id="${controls}"`);
    expect(labelledBy).toBe(toggleId);
    expect(html).toContain('role="region"');
  });

  it("stays open while forceOpen is set, so an error inside it is never hidden", () => {
    const html = renderToStaticMarkup(
      <Disclosure title="Advanced" forceOpen>
        <p role="alert">needs attention</p>
      </Disclosure>
    );
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain("needs attention");
  });

  it("keeps the content mounted but hidden with keepMounted", () => {
    const html = renderToStaticMarkup(
      <Disclosure title="Editor" keepMounted>
        <p>kept</p>
      </Disclosure>
    );
    expect(html).toContain("kept");
    expect(html).toContain('aria-expanded="false"');
  });

  it("shows the hint next to the title and swaps the title while open", () => {
    const closed = renderToStaticMarkup(
      <Disclosure title="Show details" openTitle="Hide details" hint="3 items" variant="link">
        x
      </Disclosure>
    );
    expect(closed).toContain("Show details");
    expect(closed).toContain("3 items");
    const open = renderToStaticMarkup(
      <Disclosure title="Show details" openTitle="Hide details" variant="link" defaultOpen>
        x
      </Disclosure>
    );
    expect(open).toContain("Hide details");
    expect(open).not.toContain("Show details");
  });

  it("wraps the toggle in a heading of the requested level, or none", () => {
    expect(renderToStaticMarkup(<Disclosure title="A" headingLevel={2}>x</Disclosure>)).toContain("<h2");
    expect(renderToStaticMarkup(<Disclosure title="A" headingLevel={null}>x</Disclosure>)).not.toMatch(/<h\d/);
  });

  it("with an id, starts from its default until the user toggles it", () => {
    // Static markup renders the store's initial state, so toggling is covered by the store tests below
    // and by the browser check; this pins the first render.
    const closed = renderToStaticMarkup(
      <Disclosure id="test:first-render" title="Remembered">
        <p>hidden at first</p>
      </Disclosure>
    );
    expect(closed).toContain('aria-expanded="false"');
    expect(closed).not.toContain("hidden at first");
    const open = renderToStaticMarkup(
      <Disclosure id="test:first-render-open" title="Remembered" defaultOpen>
        <p>shown at first</p>
      </Disclosure>
    );
    expect(open).toContain("shown at first");
  });
});

describe("disclosureStore", () => {
  it("stores the state per id and persists it", () => {
    const { setOpen } = store.useDisclosureStore.getState();
    setOpen("a", true);
    setOpen("b", false);
    expect(store.useDisclosureStore.getState().open).toEqual({ a: true, b: false });
    const persisted = JSON.parse(storage.getItem("scenegems:disclosure") ?? "{}") as { state?: { open?: unknown } };
    expect(persisted.state?.open).toEqual({ a: true, b: false });
  });

  it("does not change the state object when the value is the same", () => {
    store.useDisclosureStore.getState().setOpen("a", true);
    const before = store.useDisclosureStore.getState().open;
    store.useDisclosureStore.getState().setOpen("a", true);
    expect(store.useDisclosureStore.getState().open).toBe(before);
  });
});
