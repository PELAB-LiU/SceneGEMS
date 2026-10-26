import type { ReactNode } from "react";
import { useSelectedCluster } from "../domain/cluster/clusterStore";

interface SectionFrameProps {
  title: string;
  subtitle?: string;
  /** Badges or controls at the right of the header. */
  actions?: ReactNode;
  children: ReactNode;
}

/** The frame of a cluster section (Cluster, Campaigns, Observe, Results): header with the selected cluster, scrolling body. */
export function SectionFrame({ title, subtitle, actions, children }: SectionFrameProps) {
  const cluster = useSelectedCluster();
  return (
    <main className="section-layout">
      <header className="section-header">
        <div className="section-header-text">
          <h2 className="section-title">{title}</h2>
          <p className="section-cluster">
            {cluster ? (
              <>
                <span className="section-cluster-name">{cluster.name}</span>
                <span className="section-cluster-url">{cluster.operatorUrl}</span>
              </>
            ) : (
              <span className="section-cluster-none">no cluster selected</span>
            )}
          </p>
          {subtitle && <p className="meta section-subtitle">{subtitle}</p>}
        </div>
        {actions}
      </header>
      <div className="section-body">{children}</div>
    </main>
  );
}
