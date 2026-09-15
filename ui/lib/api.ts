export const API = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8787";

export type Finding = {
  code: string;
  subject_type: string;
  subject_id: number | null;
  subject_name: string | null;
  observation: string;
  evidence: Record<string, unknown>;
};

export type TableRow = {
  table: string;
  review_unit: string | null;
  stage: string | null;
  grouping_enabled: boolean;
  columns: number;
  status_counts: Record<string, number>;
  instructions_version: number | null;
  last_run: { run_id: number; started_at: string } | null;
  staleness: { never_run: number; current: number; direct: number; transitive: number };
  open_failures: number;
  coverage_unticked: number;
  document_set?: string | null;
};

export type Matter = {
  matter: string;
  matter_id: number;
  objective: string | null;
  side: string | null;
  status: string;
  tables: TableRow[];
  table_count: number;
  column_count: number;
  staleness: { never_run: number; current: number; direct: number; transitive: number };
  open_failures: number;
  parameters: { name: string; value: string | null; status: string; consumer_count: number }[];
  memo_outline: { name: string; version: number } | null;
  standard: { firm_version: number; matter_version: number | null; date_pattern: string | null };
  findings: Finding[];
};

export type ActivityEvent = {
  id: number;
  entity_type: string;
  entity_name: string | null;
  action: string;
  source_type: string | null;
  actor: string | null;
  at: string;
  detail: string | null;
};

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const getVersion = () => get<{ data_version: number }>("/api/version");
export const getMatters = () =>
  get<{ matters: { id: number; name: string; objective: string | null }[] }>("/api/matters");
export const getMatter = (m: string) => get<Matter>(`/api/matters/${encodeURIComponent(m)}`);
export type ColumnRow = {
  column_id: number;
  table: string;
  name: string;
  position: number;
  native_type: string;
  status: string;
  role: string | null;
  concept: string | null;
  purpose: string | null;
  version: string | null;
  char_count: number | null;
};

export type TableDetail = {
  matter: string;
  table: string;
  review_unit: string | null;
  grouping_enabled: boolean;
  stage: string | null;
  columns: ColumnRow[];
  column_count: number;
  readiness: { findings: Finding[]; counts: Record<string, number>; total: number; by_cause: Record<string, Finding[]> };
};

export type PromptVersion = {
  version: string;
  text: string;
  char_count: number;
  change_note: string | null;
  failure_class_addressed: string | null;
  created_at: string;
  is_current: boolean;
};

export type ColumnDetail = {
  name: string;
  table: string;
  native_type: string;
  status: string;
  role: string | null;
  concept: string | null;
  purpose: string | null;
  version: string;
  char_count: number;
  prompt_text: string;
  configured_options: string[] | null;
  upstream: { table: string; column: string; kind: string; status: string }[];
  downstream: { table: string; column: string; kind: string; status: string }[];
  consumes_parameters: { name: string; value: string | null; status: string; binding_site: string }[];
  sources_parameters: { name: string; value: string | null; status: string }[];
  staleness: { state: string; reasons: string[] };
  evaluation: { runs: number; documents_tested: number; open_failures: number; open_failure_classes: string[] };
  history: PromptVersion[];
};

export type GraphNode = {
  id: number;
  name: string;
  position: number;
  native_type: string;
  role: string | null;
  status: string;
  level: number;
  degree: number;
  isolated: boolean;
};
export type GraphEdge = { from: number; to: number; kind: string };
export type TableGraph = {
  matter: string;
  table: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  depth: number;
  linked: number;
};

export type ConceptMember = {
  table: string;
  column: string;
  native_type?: string;
  status?: string;
  role?: string | null;
  options?: string[] | null;
  divergent_options?: string[];
};
export type Divergence = {
  name: string;
  observation: string;
  members: ConceptMember[];
  shared_options: string[];
  distinct_option_sets: number;
  native_types: string[];
};
export type Concepts = {
  matter: string;
  divergent: Divergence[];
  name_variants: { observation: string; members: ConceptMember[] }[];
  other: Finding[];
  counts: { divergent: number; name_variants: number; other: number };
};

export const getConcepts = (m: string) =>
  get<Concepts>(`/api/matters/${encodeURIComponent(m)}/concepts`);

export const getGraph = (m: string, t: string) =>
  get<TableGraph>(`/api/matters/${encodeURIComponent(m)}/tables/${encodeURIComponent(t)}/graph`);

export const getTable = (m: string, t: string) =>
  get<TableDetail>(`/api/matters/${encodeURIComponent(m)}/tables/${encodeURIComponent(t)}`);
export const getColumn = (m: string, t: string, c: string) =>
  get<ColumnDetail>(
    `/api/matters/${encodeURIComponent(m)}/tables/${encodeURIComponent(t)}/columns/${encodeURIComponent(c)}`,
  );

export const getActivity = (m: string, limit = 60) =>
  get<{ events: ActivityEvent[]; total: number }>(
    `/api/matters/${encodeURIComponent(m)}/activity?limit=${limit}`,
  );
