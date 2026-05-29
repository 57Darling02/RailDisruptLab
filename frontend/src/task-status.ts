import type { Task } from '@/types'

export type TaskTagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'
export type TaskOutcome = 'running' | 'success' | 'failed' | 'unknown'

const RUNNING_STATUSES = new Set(['Queued', 'Running', 'Paused', 'Stashed', 'Locked'])
const CANCELLABLE_STATUSES = new Set(['Queued', 'Running', 'Paused', 'Stashed'])
const FAILED_STATUSES = new Set(['Failed', 'Killed'])

export function taskOutcome(task: Task): TaskOutcome {
  if (RUNNING_STATUSES.has(task.status)) return 'running'
  if (FAILED_STATUSES.has(task.status)) return 'failed'
  if (task.status === 'Done') {
    return detailIndicatesFailure(task.status_detail) ? 'failed' : 'success'
  }
  return 'unknown'
}

export function isTaskTerminal(task: Task) {
  return taskOutcome(task) !== 'running' && task.status !== 'Queued'
}

export function isTaskSuccessful(task: Task) {
  return taskOutcome(task) === 'success'
}

export function isTaskFailed(task: Task) {
  return taskOutcome(task) === 'failed'
}

export function isTaskCancellable(task: Task) {
  return CANCELLABLE_STATUSES.has(task.status)
}

export function taskDisplayStatus(task: Task) {
  const outcome = taskOutcome(task)
  if (outcome === 'failed') return '失败'
  if (outcome === 'success') return '完成'
  if (task.status === 'Running') return '运行中'
  if (task.status === 'Queued') return '排队中'
  if (task.status === 'Paused') return '已暂停'
  if (task.status === 'Stashed') return '已暂存'
  if (task.status === 'Locked') return '已锁定'
  return task.status || '未知'
}

export function taskDisplayLabel(task: Task | string | null | undefined) {
  if (typeof task !== 'string' && task?.display_name) return task.display_name
  const label = typeof task === 'string' ? task : task?.label
  if (!label) return '任务'
  return (
    {
      normal_generate: '批量生成场景',
      scenario_set_create: '创建场景集合',
      scenario_add: '新增场景',
      scenario_delete: '删除场景',
      prepare: '激活原计划运行图',
      build: '构建 MILP',
      solve: '求解',
      analyze: '导出时刻表',
      export_timetable: '导出时刻表',
      train: '训练模型',
      generation: '生成场景',
    }[label] ?? label
  )
}

export function taskTagType(task: Task): TaskTagType {
  const outcome = taskOutcome(task)
  if (outcome === 'success') return 'success'
  if (outcome === 'failed') return 'danger'
  if (task.status === 'Running') return 'primary'
  if (outcome === 'running') return 'warning'
  return 'info'
}

function detailIndicatesFailure(detail: unknown): boolean {
  if (detail == null) return false
  if (typeof detail === 'string') return failureText(detail)
  if (typeof detail === 'number' || typeof detail === 'boolean') return false
  if (Array.isArray(detail)) return detail.some((item) => detailIndicatesFailure(item))
  if (typeof detail === 'object') {
    return Object.entries(detail).some(([key, value]) => {
      if (failureText(key)) return true
      if (typeof value === 'number' && value !== 0 && /exit|code|status/i.test(key)) return true
      return detailIndicatesFailure(value)
    })
  }
  return false
}

function failureText(text: string) {
  return /fail|error|killed|signal|non[-_ ]?zero|exit(?:ed)?[_ -]?code\s*[(=:]\s*[1-9]/i.test(text)
}
