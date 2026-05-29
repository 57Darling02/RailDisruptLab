import type { Task } from '@/types'

export function taskSortTime(task: Task) {
  return parseTaskTime(task.finished_at) || parseTaskTime(task.started_at) || parseTaskTime(task.created_at)
}

export function formatTaskTime(value: string | null | undefined) {
  const time = parseTaskTime(value)
  if (!time) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(time))
}

export function formatTaskDuration(task: Task, now = Date.now()) {
  const startedAt = parseTaskTime(task.started_at) || parseTaskTime(task.created_at)
  const finishedAt = parseTaskTime(task.finished_at) || now
  if (!startedAt || !finishedAt || finishedAt < startedAt) return '-'

  const totalSeconds = Math.round((finishedAt - startedAt) / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours) return `${hours}h ${minutes}m ${seconds}s`
  if (minutes) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function parseTaskTime(value: string | null | undefined) {
  if (!value) return 0
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : 0
}
