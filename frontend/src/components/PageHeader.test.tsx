import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("renders the title once as the heading, with description and actions", () => {
    const html = renderToStaticMarkup(
      <PageHeader title="Scene Generation" description="Turn a specification into a scene." eyebrow="Step 2 of 4" actions={<button type="button">Generate</button>} />
    );
    expect(html.match(/<h2/g)).toHaveLength(1);
    expect(html).toContain("Scene Generation");
    expect(html).toContain("Turn a specification into a scene.");
    expect(html).toContain("Step 2 of 4");
    expect(html).toContain("Generate");
  });

  it("omits the optional parts", () => {
    const html = renderToStaticMarkup(<PageHeader title="Results" />);
    expect(html).not.toContain("page-header-eyebrow");
    expect(html).not.toContain("page-header-actions");
  });
});
