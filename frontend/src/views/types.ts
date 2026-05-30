import type { TaskTagType } from '@/task-status'
import type { ArtifactSummary } from '@/types'

export interface ArtifactGroup {
  case_id: string
  size_bytes: number
  has_lp: boolean
  has_solution: boolean
  has_solution_csv: boolean
  has_timetable_data: boolean
}

export function groupArtifactsByCase(artifacts: ArtifactSummary[]) {
  const groups = new Map<string, ArtifactGroup>()
  for (const artifact of artifacts) {
    const group = groups.get(artifact.case_id) ?? {
      case_id: artifact.case_id,
      size_bytes: 0,
      has_lp: false,
      has_solution: false,
      has_solution_csv: false,
      has_timetable_data: false,
    }
    group.size_bytes += artifact.size_bytes
    group.has_lp = group.has_lp || artifact.name.endsWith('.lp')
    group.has_solution = group.has_solution || artifact.name.endsWith('.sol')
    group.has_solution_csv = group.has_solution_csv || artifact.name.endsWith('.sol.csv')
    group.has_timetable_data = group.has_timetable_data || artifact.name === 'adjusted_timetable.json'
    groups.set(artifact.case_id, group)
  }
  return [...groups.values()]
}

export function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
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
  skipSolved: boolean
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
  relation_weight: number
}

export type ModelCheckpointTagType = TaskTagType
