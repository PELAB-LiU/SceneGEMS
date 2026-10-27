import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  /** What to do next, in plain words. */
  children?: ReactNode;
  /** The one action that moves on, usually a primary button. */
  action?: ReactNode;
  /** `error` is for a failure the user can act on; the default is a calm "nothing here yet". */
  tone?: "neutral" | "error";
}

/** What a screen or list shows when there is nothing to show yet: what is missing, what to do, one action. */
export function EmptyState({ title, children, action, tone = "neutral" }: EmptyStateProps) {
  return (
    <div className={`empty-state empty-state--${tone}`} role={tone === "error" ? "alert" : undefined}>
      <h3 className="empty-state-title">{title}</h3>
      {children && <div className="empty-state-body">{children}</div>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
