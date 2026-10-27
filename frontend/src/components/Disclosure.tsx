import { useId, useState, type ReactNode } from "react";
import { useDisclosureStore } from "./disclosureStore";

export interface DisclosureProps {
  /** Stable id: when given, the open state is remembered per browser. Without it the state is local. */
  id?: string;
  title: ReactNode;
  /** Text of the toggle while open, for "Show details" / "Hide details" style toggles. */
  openTitle?: ReactNode;
  /** A short summary at the right of the toggle, such as a count or a status. Shown whether open or closed. */
  hint?: ReactNode;
  defaultOpen?: boolean;
  /**
   * `card` is a bordered section, `plain` a section header without a frame, `link` an inline
   * "Show details" style toggle.
   */
  variant?: "card" | "plain" | "link";
  /** The heading level wrapped around the toggle; `null` for none. */
  headingLevel?: 2 | 3 | 4 | null;
  /** Keep the content mounted while closed (hidden), for content that holds state of its own. */
  keepMounted?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * Progressive disclosure: a toggle that shows or hides secondary content. The toggle is a
 * button with `aria-expanded` and `aria-controls`, reachable and operable by keyboard, at least
 * 40px tall. Use it for everything that is detail rather than the main task of a screen.
 */
export function Disclosure({
  id,
  title,
  openTitle,
  hint,
  defaultOpen = false,
  variant = "card",
  headingLevel = 3,
  keepMounted = false,
  className,
  children,
}: DisclosureProps) {
  const storedOpen = useDisclosureStore((s) => (id === undefined ? undefined : s.open[id]));
  const setStoredOpen = useDisclosureStore((s) => s.setOpen);
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const open = id === undefined ? localOpen : (storedOpen ?? defaultOpen);
  const baseId = useId();
  const buttonId = `${baseId}-toggle`;
  const panelId = `${baseId}-panel`;

  const toggle = () => {
    if (id === undefined) {
      setLocalOpen(!open);
    } else {
      setStoredOpen(id, !open);
    }
  };

  const button = (
    <button
      type="button"
      id={buttonId}
      className="disclosure-toggle"
      aria-expanded={open}
      aria-controls={panelId}
      onClick={toggle}
    >
      <span className="disclosure-chevron" aria-hidden />
      <span className="disclosure-title">{open && openTitle !== undefined ? openTitle : title}</span>
      {hint !== undefined && hint !== null && <span className="disclosure-hint">{hint}</span>}
    </button>
  );

  const Heading = headingLevel === null ? null : (`h${headingLevel}` as const);

  return (
    <section
      className={`disclosure disclosure--${variant}${open ? " is-open" : ""}${className ? ` ${className}` : ""}`}
    >
      {Heading === null ? button : <Heading className="disclosure-heading">{button}</Heading>}
      <div
        id={panelId}
        className="disclosure-panel"
        role="region"
        aria-labelledby={buttonId}
        hidden={!open}
      >
        {open || keepMounted ? children : null}
      </div>
    </section>
  );
}
