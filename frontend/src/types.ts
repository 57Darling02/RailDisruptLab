export type JsonObject = Record<string, unknown>

export interface Task {
  id: number
  group?: string
  label?: string
  action?: string
  params?: JsonObject
  display_name?: string
  command?: string
  original_command?: string
  path?: string
  status: string
  status_detail?: unknown
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
  dependencies?: unknown[]
  priority?: number
}

export interface TaskResponse {
  task: Task
}

export interface ProjectSummary {
  project_id: string
  root: string
}

export interface ResourceOption {
  label: string
  value: string
}

export interface FileState {
  name: string
  path: string
  exists?: boolean
  size_bytes: number
}

export interface ScenarioSet {
  scenario_set_id: string
  root: string
  case_count: number
}

export interface ScenarioSummary {
  scenario_set_id?: string
  scenario_id: string
  name: string
  root?: string
  activated?: boolean
  has_timetable?: boolean
  has_mileage?: boolean
  counts?: {
    delay: number
    speed_limit: number
    interruption: number
    total: number
  }
  delay_count: number
  speed_limit_count: number
  interruption_count: number
}

export interface ScenarioContextStats {
  station_count: number
  train_count: number
  total_mileage: number
  event_node_count: number
  section_node_count: number
}

export interface ScenarioDetail {
  scenario_set_id: string
  scenario_id: string
  name: string
  root: string
  activated: boolean
  has_timetable: boolean
  has_mileage: boolean
  counts: {
    delay: number
    speed_limit: number
    interruption: number
    total: number
  }
  delay_count: number
  speed_limit_count: number
  interruption_count: number
  source_files: FileState[]
  context_stats: ScenarioContextStats | null
  scenario: JsonObject | null
  timetable: PlanTimetableState | null
}

export interface ScenarioEventAnchorOption {
  anchor_id: string
  train_id: string
  station: string
  event_type: string
  planned_time: number
  planned_time_text: string
}

export interface ScenarioSectionAnchorOption {
  anchor_id: string
  start_station: string
  end_station: string
  direction: string
  section_order: number
  mileage: number
  min_runtime: number
}

export interface ScenarioOptions {
  project_id: string
  event_anchors: ScenarioEventAnchorOption[]
  section_anchors: ScenarioSectionAnchorOption[]
}

export interface DatasetSummary {
  dataset_id: string
  root: string
  case_count: number
  built_count: number
  solved_count: number
  timetable_count: number
  is_fully_built: boolean
  is_fully_solved: boolean
  is_timetable_ready: boolean
}

export interface DatasetDetail {
  dataset_id: string
  root: string
  case_count: number
  built_count: number
  solved_count: number
  timetable_count: number
  build_config_known_count: number
  build_config_consistent: boolean
  build_config: Record<string, unknown>
  build_config_signatures: Array<{ signature: string; count: number }>
  source_scenario_sets: Array<{ scenario_set_id: string; count: number }>
}

export interface DatasetSolveMetricSummary {
  key: string
  label: string
  count: number
  mean: number | null
  min: number | null
  max: number | null
}

export interface DatasetSolveCase {
  case_id: string
  status: string
  is_solved: boolean
  solver_config: Record<string, number>
  metrics: Record<string, number | null>
  artifacts: Record<string, string>
}

export interface DatasetSolveState {
  dataset_id: string
  root: string
  case_count: number
  solved_count: number
  config_known_count: number
  config_consistent: boolean
  solver_config: Record<string, number>
  solver_config_signatures: Array<{ signature: string; count: number }>
  status_counts: Array<{ label: string; count: number }>
  summary_metrics: DatasetSolveMetricSummary[]
  cases: DatasetSolveCase[]
}

export interface DatasetSolveErrorRow {
  dataset_id: string
  case_id: string
  metric: string
  metric_label: string
  baseline_value: number
  value: number
  absolute_error: number
  relative_error: number | null
  signed_delta: number
}

export interface DatasetSolveAnalysisWarning {
  type: string
  dataset_id: string
  message: string
}

export interface DatasetSolveAnalysis {
  project_id: string
  datasets: DatasetSolveState[]
  metric_labels: Record<string, string>
  comparison: {
    baseline_dataset_id: string
    rows: DatasetSolveErrorRow[]
  }
  warnings: DatasetSolveAnalysisWarning[]
}

export interface ArtifactSummary {
  case_id: string
  name: string
  path: string
  size_bytes: number
}

export interface TimetableRowState {
  train_id: string
  station: string
  arrival_time: string | null
  departure_time: string | null
  is_canceled: boolean
  row_number: number
}

export interface TimetableDisturbance {
  id: string
  type: 'delay' | 'speed_limit' | 'interruption'
  event_anchor_id?: string
  section_anchor_id?: string
  train_id?: string
  station?: string
  event_type?: string
  seconds?: number
  start_station?: string
  end_station?: string
  start_time?: number
  end_time?: number
  duration?: number
  limit_speed?: number
  station_order?: number
  section_order?: number
  mileage?: number
}

export interface ScenarioVisualizationItem {
  scenario_id: string
  name: string
  path: string
  disturbances: TimetableDisturbance[]
  counts: {
    delay: number
    speed_limit: number
    interruption: number
    total: number
  }
  category: string
}

export interface ScenarioCategoryRatio {
  key: string
  label: string
  count: number
  ratio: number
}

export interface ScenarioCoverageRow {
  type: 'all' | 'delay' | 'speed_limit' | 'interruption'
  label: string
  time_seconds: number
  time_ratio: number
  space_units: number
  space_ratio: number
}

export interface ScenarioMetricCard {
  key: string
  label: string
  value: number
  value_type?: 'number' | 'percent'
}

export interface ScenarioAnchorCoverage {
  key: string
  label: string
  used: number
  total: number
  ratio: number
}

export interface ScenarioParameterStat {
  key: string
  label: string
  unit: string
  count: number
  min: number | null
  max: number | null
  mean: number | null
}

export interface ScenarioCountRow {
  key?: string
  label: string
  count: number
}

export interface ScenarioJointTypeTimeRow {
  type: 'delay' | 'speed_limit' | 'interruption'
  type_label: string
  time_bin: string
  count: number
}

export interface ScenarioJointLocationTimeRow extends ScenarioJointTypeTimeRow {
  location: string
}

export interface ScenarioSetResourceSummary {
  scenario_count: number
  disturbance_counts: {
    delay: number
    speed_limit: number
    interruption: number
    total: number
  }
  category_ratios: ScenarioCategoryRatio[]
}

export interface ScenarioSetVisualization {
  project_id: string
  scenario_set_id: string
  station_order: string[]
  mileage_by_station: Record<string, number>
  train_routes: Record<string, string[]>
  plan: {
    rows: TimetableRowState[]
  }
  scenarios: ScenarioVisualizationItem[]
  summary: ScenarioSetResourceSummary & {
    coverage: {
      time_span_seconds: number
      space_span_units: number
      rows: ScenarioCoverageRow[]
    }
    disturbances: TimetableDisturbance[]
    math_graph_metrics: {
      cards: ScenarioMetricCard[]
      anchor_coverage: ScenarioAnchorCoverage[]
      parameter_stats: ScenarioParameterStat[]
      relation_counts: ScenarioCountRow[]
    }
    combination_complexity: {
      cards: ScenarioMetricCard[]
      count_distribution: ScenarioCountRow[]
      type_pair_counts: ScenarioCountRow[]
      relation_counts: ScenarioCountRow[]
    }
    joint_structure: {
      time_bins: string[]
      type_time: ScenarioJointTypeTimeRow[]
      location_time: ScenarioJointLocationTimeRow[]
    }
  }
  time_distribution?: ScenarioCountRow[]
  space_distribution?: ScenarioCountRow[]
}

export interface PlanTimetableState {
  project_id: string
  station_order: string[]
  mileage_by_station: Record<string, number>
  train_routes: Record<string, string[]>
  plan: {
    rows: TimetableRowState[]
  }
  disturbances: TimetableDisturbance[]
}

export interface CaseTimetableState {
  project_id: string
  dataset_id: string
  case_id: string
  station_order: string[]
  mileage_by_station: Record<string, number>
  train_routes: Record<string, string[]>
  plan: {
    rows: TimetableRowState[]
  }
  adjusted: {
    case_id: string
    station_order: string[]
    rows: TimetableRowState[]
  }
  disturbances: TimetableDisturbance[]
}

export interface ModelCheckpoint {
  name: string
  relative_path: string
  path: string
  role: string
  size_bytes: number
}

export interface ModelHistoryState {
  count: number
  latest: JsonObject
  best: JsonObject
}

export interface ModelLossPoint {
  step: number
  epoch: number
  epoch_step: number
  total_steps: number
  loss: number
  count_loss?: number
  anchor_loss?: number
  param_loss?: number
  kl?: number
  elapsed?: number
}

export interface ModelGraphProgress {
  global_graph?: {
    status?: string
  }
  sample_graphs?: {
    status?: string
    total?: number
    completed?: number
  }
  updated_at?: string
}

export interface ModelDetail {
  model_id: string
  root: string
  summary: JsonObject
  config: JsonObject
  schema: JsonObject
  graph_progress: ModelGraphProgress
  history: ModelHistoryState
  loss_points: ModelLossPoint[]
  training_log_tail: string
  checkpoints: ModelCheckpoint[]
}

export interface ModelSummary {
  model_id: string
  root: string
  is_ready: boolean
  has_context_graph: boolean
  sample_count: number
  has_dataset_profile: boolean
  has_best_model: boolean
  has_last_model: boolean
  has_training_summary: boolean
}

export interface ProjectState {
  project_id: string
  root: string
  exists: boolean
  scenario_sets: ScenarioSet[]
  datasets: DatasetSummary[]
  models: ModelSummary[]
}
