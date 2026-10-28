import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { Disclosure } from "./Disclosure";
import { useDisclosureStore } from "./disclosureStore";

// The pattern for component tests: render the real component into jsdom, find things the way a user
// or a screen reader does (by role and name), act through user-event, assert on what is visible.
// localStorage is the real jsdom one here, so no stubbing; the store is reset per test.

beforeEach(() => {
  useDisclosureStore.setState({ open: {} });
});

describe("Disclosure in the DOM", () => {
  it("opens and closes its content when the toggle is clicked", async () => {
    const user = userEvent.setup();
    render(
      <Disclosure title="Advanced" openTitle="Hide advanced">
        <p>secret detail</p>
      </Disclosure>
    );

    const toggle = screen.getByRole("button", { name: "Advanced" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("secret detail")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Hide advanced" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("region", { name: "Hide advanced" })).toBeVisible();
    expect(screen.getByText("secret detail")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Hide advanced" }));
    expect(screen.queryByText("secret detail")).not.toBeInTheDocument();
  });

  it("can be operated with the keyboard", async () => {
    const user = userEvent.setup();
    render(
      <Disclosure title="Options">
        <p>option list</p>
      </Disclosure>
    );
    await user.tab();
    expect(screen.getByRole("button", { name: "Options" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("option list")).toBeVisible();
  });

  it("remembers the state per id in the store and in localStorage", async () => {
    const user = userEvent.setup();
    render(
      <Disclosure id="test:remembered" title="Remembered">
        <p>kept open</p>
      </Disclosure>
    );
    await user.click(screen.getByRole("button", { name: "Remembered" }));
    expect(useDisclosureStore.getState().open).toEqual({ "test:remembered": true });
    const persisted = JSON.parse(window.localStorage.getItem("scenegems:disclosure") ?? "{}") as {
      state?: { open?: unknown };
    };
    expect(persisted.state?.open).toEqual({ "test:remembered": true });
  });

  it("does not close while forceOpen is set", async () => {
    const user = userEvent.setup();
    render(
      <Disclosure title="Advanced" forceOpen>
        <p role="alert">needs attention</p>
      </Disclosure>
    );
    await user.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByRole("alert")).toHaveTextContent("needs attention");
  });
});
