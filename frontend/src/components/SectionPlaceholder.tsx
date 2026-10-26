import { SectionFrame } from "./SectionFrame";

interface SectionPlaceholderProps {
  title: string;
  /** What the section will show, in one line. */
  purpose: string;
}

/** A section that is not built yet. */
export function SectionPlaceholder({ title, purpose }: SectionPlaceholderProps) {
  return (
    <SectionFrame title={title}>
      <div className="section-empty" role="status">
        <h3>{title} is not built yet</h3>
        <p className="meta">{purpose}</p>
      </div>
    </SectionFrame>
  );
}
