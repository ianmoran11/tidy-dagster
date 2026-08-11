export type BenchmarkAsset = {
  name: string;
  xlsx: string;
  recipe: string;
  expected_csv?: string;
  expected_csvs?: Record<string, string>;
  metadata?: string;
  expected_overlay?: string;
  enabled: boolean;
  ci_smoke?: boolean;
  disabled_reason?: string;
  difficulty?: string;
  features?: string[];
  repeat_of?: string;
  repeat_index?: number;
};

export type BenchmarkManifest = {
  version: "0.1";
  assets: BenchmarkAsset[];
};

export type ExpectedOverlay = {
  asset: string;
  sheet: string;
  tables: Array<{
    name: string;
    values?: {
      range?: string;
      addresses?: string[];
    };
    headers?: Array<{
      name: string;
      direction: string;
      addresses: string[];
      fill?: string;
    }>;
  }>;
  non_table_cells?: string[];
};

export type CsvTable = {
  headers: string[];
  rows: string[][];
  records: Record<string, string>[];
};

export type CsvDiff = {
  reference_csv_available: boolean;
  exact_csv_match: boolean;
  normalized_csv_match: boolean;
  non_blank_value_csv_match: boolean;
  row_count_expected: number;
  row_count_actual: number;
  raw_row_count_expected: number;
  raw_row_count_actual: number;
  blank_value_rows_ignored_expected: number;
  blank_value_rows_ignored_actual: number;
  row_count_delta: number;
  column_names_expected: string[];
  column_names_actual: string[];
  column_order_match: boolean;
  cell_exact_match_count: number;
  cell_total_count: number;
  cell_exact_match_rate: number;
  numeric_match_rate: number | null;
  blank_match_rate: number | null;
  extra_rows: string[];
  missing_rows: string[];
  mismatches: CellMismatch[];
  value_address: AddressMetrics;
  header_assignment: HeaderAssignmentMetrics;
  coherence: CoherenceMetrics;
};

export type CellMismatch = {
  row_index: number;
  column: string;
  expected: string;
  actual: string;
};

export type AddressMetrics = {
  expected_value_addresses: string[];
  actual_value_addresses: string[];
  missing_value_addresses: string[];
  extra_value_addresses: string[];
  value_address_precision: number;
  value_address_recall: number;
  value_address_f1: number;
};

export type AnchorCoverage = {
  expected_record_count: number;
  matched_by_address_count: number;
  matched_positionally_count: number;
  unmatched_count: number;
  matched_by_address_share: number;
  matched_positionally_share: number;
  unmatched_share: number;
  anchoring_mode: "address-anchored" | "mixed" | "positional-only" | "unanchored";
};

export type HeaderAssignmentMetrics = {
  anchor_coverage: AnchorCoverage;
  variables: Record<
    string,
    {
      accuracy: number;
      missing_rate: number;
      extra_value_rate: number;
      distinct_value_overlap: number;
      mismatches: CellMismatch[];
    }
  >;
  address_conditioned_cell_match_count: number;
  address_conditioned_cell_total_count: number;
  address_conditioned_cell_match_rate: number;
  full_row_header_match_rate: number;
  full_row_with_value_match_rate: number;
};

export type CoherenceMetrics = {
  value_column: string | null;
  numeric_like_value_count: number;
  non_numeric_value_count: number;
  mixed_value_types: boolean;
  empty_header_label_count: number;
  empty_header_value_count: number;
  duplicate_output_row_count: number;
  duplicate_source_address_count: number;
  non_numeric_value_samples: string[];
};

export type GeometryMetrics = {
  expected_overlay_available: boolean;
  data_cell_precision: number | null;
  data_cell_recall: number | null;
  data_cell_f1: number | null;
  header_cell_precision: number | null;
  header_cell_recall: number | null;
  header_cell_f1: number | null;
  direction_accuracy: number | null;
  table_boundary_iou: number | null;
  multi_table_count_accuracy: number | null;
  header_fill_accuracy: number | null;
  missing_data_cells: string[];
  extra_data_cells: string[];
  missing_header_cells: string[];
  extra_header_cells: string[];
  direction_errors: Array<{
    table: string;
    header: string;
    expected: string;
    actual: string | null;
  }>;
};

export type MatchedColumnPair = {
  /** Matched expected column's cell set (sorted addresses, never a name). */
  expected_cells: string[];
  /** Matched actual column's cell set (sorted addresses, never a name). */
  actual_cells: string[];
  /** `|S_exp ∩ S_act|` — the matching weight / shared type-1 edge count. */
  shared_cell_count: number;
};

/**
 * Jaccard graph-similarity result (see
 * `docs/performance-measures/graph-similarity.md`). Produced by
 * `scripts/benchmark/metrics/graphSimilarity.ts` and wired into asset
 * summaries by `graphSimilarityAsset.ts`.
 */
export type GraphSimilarityMetrics = {
  reference_available: boolean;
  expected_value_sources_available: boolean;
  expected_header_sources_available: boolean;
  /** Jaccard over the combined scored edge set (primary score). */
  graph_similarity: number | null;
  /** Jaccard over type-1 (column/axis) edges only. */
  column_axis_jaccard: number | null;
  /** Jaccard over type-2 (value↔header association) edges only. */
  association_jaccard: number | null;
  matched_column_pairs: MatchedColumnPair[];
  unmatched_expected_column_count: number;
  unmatched_actual_column_count: number;
  expected_edge_count: number;
  actual_edge_count: number;
  shared_edge_count: number;
};

export type NonTableMetrics = {
  expected_non_table_cells: string[];
  actual_non_table_cells: string[];
  missing_non_table_cells: string[];
  extra_non_table_cells: string[];
  non_table_precision: number | null;
  non_table_recall: number | null;
  non_table_f1: number | null;
};

export type MetricStats = {
  mean: number;
  min: number;
  max: number;
  stddev: number;
};

export type RepeatMetricStats = {
  deterministicPassRate: MetricStats;
  exact_csv_match_rate: MetricStats;
  mean_cell_exact_match_rate: MetricStats;
  mean_address_conditioned_cell_match_rate: MetricStats;
  mean_value_address_f1: MetricStats;
  mean_full_row_header_match_rate: MetricStats;
  mean_full_row_with_value_match_rate: MetricStats;
  mean_header_assignment_accuracy: MetricStats;
  /** Graph-similarity stats over assets with `reference_available: true`. */
  mean_graph_similarity: MetricStats;
  mean_column_axis_jaccard: MetricStats;
  mean_association_jaccard: MetricStats;
};

export type BenchmarkUsageCost = {
  model?: string;
  call_count?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  cached_tokens?: number;
  total_tokens?: number;
  estimated_usd?: number;
  actual_usd?: number;
  generation_ms?: number;
  source?: string;
};

export type AssetBenchmarkSummary = {
  asset: string;
  repeat_of?: string;
  repeat_index?: number;
  sheet: string;
  table_count: number;
  table_names: string[];
  deterministic_pass: boolean;
  deterministic_skipped: boolean;
  exact_csv_match: boolean;
  normalized_csv_match: boolean;
  row_count_expected: number;
  row_count_actual: number;
  cell_exact_match_rate: number;
  address_conditioned_cell_match_rate: number;
  value_address_f1: number;
  full_row_header_match_rate: number;
  full_row_with_value_match_rate: number;
  anchor_coverage: AnchorCoverage;
  warnings: Array<{ code: string; message: string }>;
  metadata: Record<string, unknown> | null;
  usage_cost?: BenchmarkUsageCost | null;
  difficulty?: string;
  features: string[];
  artifacts: Record<string, string>;
  metrics: {
    csv: CsvDiff;
    geometry: GeometryMetrics;
    non_table: NonTableMetrics;
    graph: GraphSimilarityMetrics;
  };
};

export type SuiteSummary = {
  run_id: string;
  manifest: string;
  mode: string;
  assets_total: number;
  assets_passed: number;
  assets_failed: number;
  assets_skipped: number;
  execution_errors: Array<{ asset: string; reason: string }>;
  exact_csv_match_rate: number;
  mean_cell_exact_match_rate: number;
  mean_address_conditioned_cell_match_rate: number;
  mean_value_address_f1: number;
  mean_full_row_header_match_rate: number;
  mean_full_row_with_value_match_rate: number;
  /** Compatibility alias for mean_full_row_header_match_rate. */
  mean_header_assignment_accuracy: number;
  /**
   * Graph-similarity rollups. Each mean is computed only over assets whose
   * `metrics.graph.reference_available` is true: assets without expected
   * source addresses are excluded from the denominator (mirroring how
   * null-gated metrics are handled), and the mean is 0 when no asset is
   * scoreable.
   */
  mean_graph_similarity: number;
  mean_column_axis_jaccard: number;
  mean_association_jaccard: number;
  mean_judge_overall_score: number | null;
  anchor_coverage: AnchorCoverage;
  header_dimension_rollups: Record<
    string,
    {
      asset_count: number;
      mean_accuracy: number;
      mean_missing_rate: number;
      mean_extra_value_rate: number;
      mean_distinct_value_overlap: number;
    }
  >;
  assets: Array<{
    asset: string;
    deterministic_pass: boolean;
    deterministic_skipped: boolean;
    exact_csv_match: boolean;
    cell_exact_match_rate: number;
    address_conditioned_cell_match_rate: number;
    value_address_f1: number;
    full_row_header_match_rate: number;
    full_row_with_value_match_rate: number;
    anchor_coverage: AnchorCoverage;
    repeat_of?: string;
    repeat_index?: number;
    flakiness?: boolean;
    repeat_stats?: RepeatMetricStats;
    usage_cost?: BenchmarkUsageCost | null;
    summary_path: string;
  }>;
  usage_cost?: {
    assets_with_usage: number;
    prompt_tokens: number;
    completion_tokens: number;
    cached_tokens: number;
    total_tokens: number;
    estimated_usd: number;
    actual_usd: number;
    generation_ms: number;
  } | null;
  repeat_stats: RepeatMetricStats;
  repeat_rollups: Record<
    string,
    {
      repeat_count: number;
      flakiness: boolean;
      stats: RepeatMetricStats;
    }
  >;
  feature_rollups: Record<
    string,
    {
      asset_count: number;
      exact_csv_match_rate: number;
      mean_cell_exact_match_rate: number;
      mean_address_conditioned_cell_match_rate: number;
      mean_value_address_f1: number;
      mean_full_row_header_match_rate: number;
      mean_full_row_with_value_match_rate: number;
      anchor_coverage: AnchorCoverage;
    }
  >;
  critical_failures: Array<{ asset: string; reason: string }>;
};

export type RunAssetOptions = {
  repoRoot?: string;
  outputDir: string;
  renderPng?: boolean;
  numericTolerance?: number;
};
