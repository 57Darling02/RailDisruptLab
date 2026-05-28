import type { TaskTagType } from '@/task-status'

export interface ArtifactGroup {
  case_id: string
  size_bytes: number
  has_lp: boolean
  has_solution: boolean
  has_solution_csv: boolean
  has_timetable_data: boolean
}

export interface MetadataEntry {
  key: string
  label: string
  value: string
}

export interface SchemaPoolRow {
  id: string
  size: string
  feature_dim: string
}

export interface SchemaEdgeRow {
  id: string
  source_pool_id: string
  target_pool_id: string
  feature_dim: string
}

export interface SchemaTaskRow {
  id: string
  target_pool_id: string
  max_slots: string
  count_bounds: string
  param_dim: string
}

export interface DatasetRunForm {
  solveLimit: number
  solveTimeLimit: number
  solveMipGap: number
  solveThreads: number
}

export interface DatasetBuildForm {
  objective_delay_weight: number
  objective_mode: string
  cancellation_enabled: boolean
  cancellation_penalty_weight: number
  arr_arr_headway_seconds: number
  dep_dep_headway_seconds: number
  dwell_seconds_at_stops: number
  big_m: number
  tolerance_delay_seconds: number
}

export interface TrainForm {
  model_id: string
  scenario_set_id: string
  max_slots: number
  event_time_window: number
  event_top_k: number
  section_order_window: number
  hidden_dim: number
  latent_dim: number
  message_passing_steps: number
  epochs: number
  batch_size: number
  lr: number
  seed: number
  device: string
  count_weight: number
  anchor_weight: number
  param_weight: number
  kl_weight: number
}

export type ModelCheckpointTagType = TaskTagType
