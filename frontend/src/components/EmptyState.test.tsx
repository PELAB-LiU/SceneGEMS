import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("shows the title, the guidance and the one action", () => {
    const html = renderToStaticMarkup(
      <EmptyState title="No campaigns yet" action={<button type="button">New campaign</button>}>
        <p>A campaign runs many simulations.</p>
      </EmptyState>
    );
    expect(html).toContain("No campaigns yet");
    expect(html).toContain("A campaign runs many simulations.");
    expect(html).toContain("New campaign");
    expect(html).not.toContain('role="alert"');
  });

  it("announces an error state", () => {
    const html = renderToStaticMarkup(<EmptyState title="Cannot reach the cluster" tone="error" />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("empty-state--error");
  });
});
