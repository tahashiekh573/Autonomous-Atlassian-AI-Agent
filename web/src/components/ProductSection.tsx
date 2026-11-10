import { api } from "../api";
import { useLoad } from "../hooks";
import type { CatalogEntry, Connection, Overview } from "../types";
import { RiskBadge } from "./Badges";

export type Product = "jira" | "jsm" | "confluence" | "integration";

const META: Record<Product, { title: string; blurb: string; examples: string[] }> = {
  jira: {
    title: "Jira Software",
    blurb: "Projects, issue types, fields, workflows, boards, sprints, timelines, dashboards and automation.",
    examples: [
      "Create a Scrum project 'Mobile App' (key MOB) with Epic, Story, Bug, Task and Sub-task issue types",
      "Create an epic 'Payments' with three stories due next month and make the second story block the third",
      "Create an automation that assigns high-priority bugs in MOB to the project lead and comments on the issue",
      "Generate a workload report for MOB",
    ],
  },
  jsm: {
    title: "Jira Service Management",
    blurb: "Service projects, request types, organizations, customers, SLA and request reporting.",
    examples: [
      "Create a Bank IT Service Desk (key BITSD) using the ITSM template with request types for password reset and VPN access",
      "Create an organization 'Branch Offices' and add it to BITSD",
      "Show the SLA report for BITSD incidents",
      "Create an automation that assigns high-priority incidents in BITSD to the IT support lead",
    ],
  },
  confluence: {
    title: "Confluence",
    blurb: "Spaces, KB articles, policies, SOPs, troubleshooting guides, hierarchies and labels.",
    examples: [
      "Create a space 'IT Knowledge Base' (key ITKB) with an index page, an IT acceptable-use policy and a password reset guide",
      "Add a VPN troubleshooting article under 'Troubleshooting' in ITKB labelled vpn",
    ],
  },
  integration: {
    title: "Cross-platform integration",
    blurb: "Keeps Jira, JSM and Confluence connected: issue ↔ page links, incident ↔ bug traceability, live issue macros.",
    examples: [
      "Create a development project, connect its Jira issues with Confluence documentation and link related JSM incidents",
      "Create a bug in MOB from incident BITSD-12 and link them",
      "Create a complete ITSM environment with Jira, JSM and Confluence, including all necessary integrations",
    ],
  },
};

interface Props {
  product: Product;
  connection: Connection | null;
  catalog: CatalogEntry[];
  onUse: (text: string) => void;
}

export function ProductSection({ product, connection, catalog, onUse }: Props) {
  const meta = META[product];
  const ops = catalog.filter((c) => c.agent === product);
  const available = product === "integration" || connection?.capabilities?.products?.[product];
  const { data: overview, error } = useLoad<Overview | null>(
    () => (connection ? api.overview(connection.id) : Promise.resolve(null)),
    [connection?.id],
  );

  return (
    <div className="stack">
      <div className="page-head">
        <div><h1>{meta.title}</h1><p>{meta.blurb}</p></div>
        {connection && <span className={`badge ${available ? "ok" : "err"}`}>{available ? "Available on site" : "Not available on site"}</span>}
      </div>

      <div className="grid-2">
        <div className="card stack">
          <h2>Quick commands</h2>
          <div className="chips">
            {meta.examples.map((e) => <button key={e} className="chip" onClick={() => onUse(e)}>{e}</button>)}
          </div>
          <Resources product={product} overview={overview} error={error} />
        </div>

        <div className="card">
          <h2>What the agent can do</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Operation</th><th>Risk</th><th>Support</th></tr></thead>
              <tbody>
                {ops.map((op) => (
                  <tr key={op.name}>
                    <td>{op.description}<div className="small muted"><code>{op.name}</code></div>
                      {!op.supported && <div className="small">Manual: {op.alternative}</div>}</td>
                    <td><RiskBadge risk={op.risk} /></td>
                    <td>{op.supported
                      ? <span className="badge ok">API{op.needs_jira_admin ? " · admin" : ""}</span>
                      : <span className="badge warn" title={op.limitation ?? ""}>UI only</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function Resources({ product, overview, error }: { product: Product; overview: Overview | null; error: string | null }) {
  if (error) return <div className="alert err">{error}</div>;
  if (!overview) return null;
  const rows: { key: string; name: string }[] =
    product === "jira" ? (overview.jira_projects ?? []).map((p) => ({ key: p.key, name: p.name }))
    : product === "jsm" ? (overview.service_desks ?? []).map((d) => ({ key: d.project_key, name: d.project_name }))
    : product === "confluence" ? (overview.spaces ?? []).map((s) => ({ key: s.key, name: s.name }))
    : [];
  if (product === "integration") return null;
  return (
    <div>
      <h3>Existing on {new URL(overview.site_url).host}</h3>
      {rows.length === 0 ? <div className="muted small">None visible to the connected account.</div> : (
        <div className="table-wrap" style={{ maxHeight: 260, overflowY: "auto" }}>
          <table><tbody>{rows.map((r) => <tr key={r.key}><td><code>{r.key}</code></td><td>{r.name}</td></tr>)}</tbody></table>
        </div>
      )}
    </div>
  );
}
