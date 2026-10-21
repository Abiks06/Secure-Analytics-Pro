export type Severity = "critical" | "warning" | "notable" | "positive" | "info";
export type PrivacyMode = "none" | "mask" | "hash" | "redact";

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface DatasetSummary {
  id: string;
  name: string;
  status: "queued" | "processing" | "ready" | "failed";
  stage: string;
  progress: number;
  error: string | null;
  source_format: string;
  size_bytes: number;
  stored_bytes: number;
  sha256: string;
  row_count: number;
  column_count: number;
  quality_score: number | null;
  processing_ms: number | null;
  insight_count: number;
  pii_count: number;
  top_insights: { title: string; kind: string; severity: Severity }[];
  privacy_policy: Record<string, PrivacyMode>;
  created_at: string;
  updated_at: string;
}

export interface ScatterChart {
  type: "scatter";
  x: string;
  y: string;
  points: [number, number][];
  fit: { slope: number; intercept: number };
}
export interface BarChart {
  type: "bar";
  x: string;
  y?: string;
  categories: (string | number | boolean | null)[];
  values: (number | null)[];
  counts?: number[];
  baseline?: number;
}
export interface LineChart {
  type: "line";
  t: string[];
  y: (number | null)[];
  series: string;
  forecast: Forecast | null;
  anomalies: Anomaly[];
}
export interface BoxChart {
  type: "box";
  column: string;
  q1: number;
  median: number;
  q3: number;
  whisker_low: number;
  whisker_high: number;
  samples: number[];
  extreme: number;
  log_scale: boolean;
}
export interface HistogramChart {
  type: "histogram";
  column: string;
  bins: number[];
  counts: number[];
}
export interface ParetoChart {
  type: "pareto";
  column: string;
  x: number[];
  y: number[];
}
export type ChartSpec = ScatterChart | BarChart | LineChart | BoxChart | HistogramChart | ParetoChart;

export interface Insight {
  id: string;
  kind: string;
  severity: Severity;
  title: string;
  body: string;
  score: number;
  columns: string[];
  chart: ChartSpec | null;
  metric: { label: string; value: number } | null;
}

export interface Forecast {
  alpha: number;
  beta: number;
  t: string[];
  y: number[];
  lower: number[];
  upper: number[];
}
export interface Anomaly {
  t: string;
  value: number;
  expected: number;
  z: number;
}

export interface ColumnProfile {
  name: string;
  original_name: string;
  kind: "numeric" | "datetime" | "boolean" | "categorical" | "text" | "identifier";
  dtype: string;
  unit: string | null;
  count: number;
  nulls: number;
  null_pct: number;
  distinct: number;
  distinct_pct: number;
  invalid: number;
  stats?: Record<string, number | string | null>;
  histogram?: { bins: number[]; counts: number[] };
  timeline?: { t: string[]; n: number[] };
  top?: { value: string | number | boolean; count: number }[];
  other_count?: number;
  entropy?: number;
  length?: { min: number; mean: number; max: number };
  health: { completeness: number; validity: number };
}

export interface PiiFinding {
  column: string;
  type: string;
  label: string;
  risk: "critical" | "high" | "medium" | "low";
  confidence: number;
  match_ratio: number | null;
  evidence: string;
  recommended: PrivacyMode;
}

export interface TimeSeries {
  time_column: string;
  granularity: string;
  partial_last: boolean;
  t: string[];
  start: string;
  end: string;
  series: {
    name: string;
    method: string;
    unit: string | null;
    y: (number | null)[];
    trend: {
      slope: number;
      mk_z: number;
      p_value: number;
      direction: "up" | "down" | "flat";
      significant: boolean;
      change_pct: number | null;
      from: number;
      to: number;
    };
    seasonality: { lag: number | null; acf: number | null; detected: boolean };
    anomalies: Anomaly[];
    forecast: Forecast | null;
    peak: { t: string; value: number } | null;
  }[];
}

export interface Report {
  ingest: { format: string; encoding: string | null; delimiter: string | null; compressed: boolean; notes: string[] };
  cleaning: {
    actions: { column: string | null; action: string; count: number; detail: string }[];
    columns: Record<string, { original_name: string; inferred: string; invalid: number; unit: string | null; formats: string[] }>;
  };
  overview: {
    rows: number;
    rows_raw: number;
    columns: number;
    missing_cells: number;
    missing_pct: number;
    duplicates_removed: number;
    memory_bytes: number;
    kinds: Record<string, number>;
  };
  quality: { score: number; completeness: number; validity: number; uniqueness: number; consistency: number };
  columns: ColumnProfile[];
  privacy: { findings: PiiFinding[] };
  insights: Insight[];
  correlations: {
    columns: string[];
    pearson: (number | null)[][];
    spearman: (number | null)[][];
    top_pairs: { a: string; b: string; pearson: number | null; spearman: number | null; n: number }[];
  } | null;
  outliers: {
    univariate: BoxChart[];
    multivariate: {
      columns: string[];
      threshold: number;
      flagged: number;
      rows: { row: number; distance: number; values: Record<string, number>; drivers: string[] }[];
    } | null;
  };
  segments: { group: string; target: string; eta2: number; n: number }[];
  timeseries: TimeSeries | null;
  timings_ms: Record<string, number>;
  narrative?: string;
}

export interface QueryResult {
  columns: { name: string; type: string }[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
}

export interface AskResult {
  question: string;
  sql: string | null;
  rationale?: string;
  chart?: { type: "bar" | "line" | "scatter" | "table" | "metric"; x: string | null; y: string | null } | null;
  answer: string | null;
  result: QueryResult | null;
  error: string | null;
}

export interface RowsPage {
  columns: { name: string; type: string }[];
  index: number[];
  rows: unknown[][];
  total: number;
  offset: number;
}

export interface AuditEvent {
  seq: number;
  action: string;
  target: string | null;
  ip: string;
  detail: Record<string, unknown>;
  created_at: string;
  hash: string;
  prev_hash: string;
}

export interface SystemInfo {
  ai_enabled: boolean;
  ai_model: string | null;
  max_upload_mb: number;
  query_row_limit: number;
  query_timeout_s: number;
  database: string;
  encryption: string;
  auth: string;
  storage: string;
  cache: { entries: number; bytes: number; hits: number; misses: number };
  usage: { datasets: number; rows: number; stored_bytes: number; avg_quality: number | null };
}

export interface SessionInfo {
  id: string;
  user_agent: string;
  ip: string;
  created_at: string | null;
  last_used_at: string | null;
  aal: string;
  current: boolean;
}

export interface ProgressEvent {
  status: DatasetSummary["status"];
  stage: string;
  progress: number;
  message: string | null;
}
