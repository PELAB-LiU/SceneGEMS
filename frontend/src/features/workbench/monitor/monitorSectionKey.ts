import type { TrajectoryStream } from "../../../app/uiStore";

export function monitorSectionKey(stream: TrajectoryStream, section: string): string {
  return `monitor:${stream}:${section}`;
}
