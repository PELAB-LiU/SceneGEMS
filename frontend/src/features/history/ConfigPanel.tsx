import { useMemo, useState } from "react";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import type { CampaignConfig } from "../../domain/cluster/schemas";
import { shortHash } from "../cluster/clusterFormat";
import { configYaml, formatDateTime } from "../campaigns/campaignFormat";

/** The campaign's config as YAML, read-only, with its versions. */
export function ConfigPanel({ config, error, loading }: { config: CampaignConfig | undefined; error: unknown; loading: boolean }) {
  const [chosen, setChosen] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const version = useMemo(() => {
    if (!config) {
      return undefined;
    }
    return config.versions.find((entry) => entry.version === (chosen ?? config.current_version)) ?? config.versions[config.versions.length - 1];
  }, [config, chosen]);
  const text = useMemo(() => (version ? configYaml(version.config) : ""), [version]);

  const copy = () => {
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => setCopied(false)
    );
  };

  return (
    <details className="panel camp-config">
      <summary>
        <span className="camp-config-title">Config</span>
        <span className="meta">
          {config ? `version ${config.current_version} of ${config.versions.length}, read-only` : loading ? "loading" : "not loaded"}
        </span>
      </summary>
      {error ? <p className="meta warning">The config did not load: {describeOperatorError(error)}</p> : null}
      {config && version && (
        <>
          <div className="camp-config-bar">
            <label className="camp-inline-field">
              Version
              <select value={version.version} onChange={(event) => setChosen(Number(event.target.value))}>
                {[...config.versions].reverse().map((entry) => (
                  <option key={entry.version} value={entry.version}>
                    {entry.version}
                    {entry.version === config.current_version ? " (current)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <span className="meta">
              hash <code title={version.config_hash}>{shortHash(version.config_hash, 12)}</code>, created {formatDateTime(version.created_at)}
            </span>
            <button type="button" onClick={copy}>
              {copied ? "Copied" : "Copy YAML"}
            </button>
          </div>
          <pre className="camp-yaml" tabIndex={0} aria-label={`Config version ${version.version} as YAML`}>
            {text}
          </pre>
        </>
      )}
    </details>
  );
}
