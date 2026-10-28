import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { StepsStep } from "./StepsStep";
import { StepHarness } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";
import type { WizardDraft } from "./wizardState";

function setup(change: (draft: WizardDraft) => void = () => undefined) {
  const seen: WizardDraft[] = [];
  render(<StepHarness Page={StepsStep} extra={{}} initial={draftOf(change)} onDraft={(draft) => seen.push(draft)} />);
  return { latest: () => seen[seen.length - 1], user: userEvent.setup() };
}

describe("the Steps page", () => {
  it("starts with the whole chain and a monitor choice for both generation steps", () => {
    setup();
    expect(screen.getByRole("radio", { name: /Scene generation\s*Generates scenes/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Simulation\s*Produces simulated runs/ })).toBeChecked();
    expect(screen.getByText("scene generation, then trajectory generation, then simulation")).toBeVisible();
    expect(screen.getByRole("group", { name: "Monitor after scene generation" })).toBeVisible();
    expect(screen.getByRole("group", { name: "Monitor after trajectory generation" })).toBeVisible();
    expect(screen.getByText(/Simulated runs are monitored per run/)).toBeVisible();
  });

  it("takes the name and the description", async () => {
    const { latest, user } = setup();
    await user.type(screen.getByRole("textbox", { name: "Name" }), "planned");
    expect(latest().name).toBe("planned");
    await user.type(screen.getByRole("textbox", { name: "Description" }), "two steps");
    expect(latest().description).toBe("two steps");
  });

  it("chooses a consecutive part: starting later keeps the last step, stopping early keeps the first", async () => {
    const { latest, user } = setup();
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Plans the trajectories/ }));
    expect(latest().steps).toEqual(["trajectory_generation", "simulation"]);
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Produces trajectories/ }));
    expect(latest().steps).toEqual(["trajectory_generation"]);
    await user.click(screen.getByRole("radio", { name: /Simulation\s*Simulates trajectories/ }));
    expect(latest().steps).toEqual(["simulation"]);
  });

  it("does not offer a last step before the first", async () => {
    setup((draft) => void (draft.steps = ["trajectory_generation", "simulation"]));
    expect(screen.getByRole("radio", { name: /Scene generation\s*Comes before the first step/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Simulation\s*Produces simulated runs/ })).toBeChecked();
  });

  it("shows the monitor of a generation step only while the campaign runs it", () => {
    setup((draft) => void (draft.steps = ["simulation"]));
    expect(screen.queryByRole("group", { name: /Monitor after/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Its input comes from earlier results or files/)).toBeVisible();
  });

  it("sets the monitor after scene generation and trajectory generation", async () => {
    const { latest, user } = setup();
    const scenes = screen.getByRole("group", { name: "Monitor after scene generation" });
    await user.click(within(scenes).getByRole("radio", { name: /Post hoc monitor/ }));
    expect(latest().sceneMonitor).toBe("post_hoc");
    expect(latest().trajectoryMonitor).toBe("empty");
    const trajectories = screen.getByRole("group", { name: "Monitor after trajectory generation" });
    await user.click(within(trajectories).getByRole("radio", { name: /Post hoc monitor/ }));
    expect(latest().trajectoryMonitor).toBe("post_hoc");
  });

  it("leaves items out that do not fit the new first step", async () => {
    const { latest, user } = setup((draft) => {
      draft.steps = ["trajectory_generation", "simulation"];
      draft.input.items = [
        { id: "a", name: "scene", ref: { sha256: "a".repeat(64), size_bytes: 1, kind: "scene" }, source: { file: "s.json" }, uploadedAt: null },
      ];
    });
    await user.click(screen.getByRole("radio", { name: /Simulation\s*Simulates trajectories/ }));
    expect(latest().steps).toEqual(["simulation"]);
    expect(latest().input.items).toEqual([]);
  });
});
