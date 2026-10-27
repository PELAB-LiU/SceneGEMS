import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  /** One plain sentence on what this screen is for. */
  description?: string;
  /** Small line above the title, such as "Step 2 of 4". */
  eyebrow?: string;
  /** Status badges or context (the selected cluster) under the title. */
  meta?: ReactNode;
  /** The primary action of the screen and its companions, at the right. */
  actions?: ReactNode;
}

/** The header of a screen: title, what it is for, and the primary action. One per screen. */
export function PageHeader({ title, description, eyebrow, meta, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        {eyebrow && <p className="page-header-eyebrow">{eyebrow}</p>}
        <h2 className="page-header-title">{title}</h2>
        {description && <p className="page-header-description">{description}</p>}
        {meta}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
}
