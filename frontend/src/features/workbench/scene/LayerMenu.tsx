import type { OverlayVisibility } from "../../../app/uiStore";

const LAYER_LABELS: [keyof OverlayVisibility, string][] = [
  ["dot", "Hulls and heading lines"],
  ["velocity", "Course and speed vectors"],
  ["trajectory", "Tracks and path ahead"],
  ["safetyDomain", "Safety domains"],
  ["staticAvoidanceDomain", "Static avoidance domains"],
  ["maneuveringDomain", "Maneuvering corridors"],
  ["safetyRadius", "Safety radius rings"],
];

/** Drop-down of the canvas layers, laid over the canvas. */
export function LayerMenu({
  layers,
  onChange,
}: {
  layers: OverlayVisibility;
  onChange: (key: keyof OverlayVisibility, value: boolean) => void;
}) {
  return (
    <details className="enc-layer-menu">
      <summary>Layers</summary>
      <div className="enc-layer-menu-body">
        {LAYER_LABELS.map(([key, label]) => (
          <label key={key}>
            <input type="checkbox" checked={layers[key]} onChange={(event) => onChange(key, event.target.checked)} />
            {label}
          </label>
        ))}
      </div>
    </details>
  );
}
