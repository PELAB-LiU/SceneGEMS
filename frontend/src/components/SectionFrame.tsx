import type { ReactNode } from "react";
import { useSelectedCluster } from "../domain/cluster/clusterStore";
import { PageHeader } from "./PageHeader";

interface SectionFrameProps {
  title: string;
  /** One plain sentence on what the section is for. */
  subtitle?: string;
  /** The primary action and the status badges of the section, at the right of the header. */
  actions?: ReactNode;
  children: ReactNode;
}

/** The frame of a cluster section (Cluster, Campaigns, Observe, Results): header with the selected cluster, scrolling body. */
export function SectionFrame({ title, subtitle, actions, children }: SectionFrameProps) {
  const cluster = useSelectedCluster();
  return (
    <main className="section-layout">
      <PageHeader
        title={title}
        description={subtitle}
        meta={
          <p className="section-cluster">
            {cluster ? (
              <>
                <span className="section-cluster-name">{cluster.name}</span>
                <span className="section-cluster-url">{cluster.operatorUrl}</span>
              </>
            ) : (
              <span className="section-cluster-none">No cluster selected</span>
            )}
          </p>
        }
        actions={actions}
      />
      <div className="section-body">{children}</div>
    </main>
  );
}
