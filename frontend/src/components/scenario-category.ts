import type {
  RunGraphReference,
  ScenarioVisualizationItem,
  TimetableDisturbance,
  TimetableRowState,
} from '@/types'

export type RunGraphUsage = {
  key: string
  label: string
  runGraph: RunGraphReference
  scenarioCount: number
  disturbanceCount: number
}

export type DisturbanceSeriesKey = 'total' | TimetableDisturbance['type']
export type DisturbanceTimeBucket = Record<DisturbanceSeriesKey, number> & { label: string; seconds: number }
export type DisturbanceSpacePoint = Record<DisturbanceSeriesKey, number> & {
  key: string
  label: string
  tooltipLabel: string
  mileage: number
}

export const DISTURBANCE_SERIES: Array<{ key: DisturbanceSeriesKey; label: string }> = [
  { key: 'total', label: '总数' },
  { key: 'delay', label: '晚点' },
  { key: 'speed_limit', label: '限速' },
  { key: 'interruption', label: '中断' },
]

export const DISTURBANCE_TYPE_OPTIONS: Array<{ label: string; value: DisturbanceSeriesKey }> = [
  { label: '总体', value: 'total' },
  { label: '晚点', value: 'delay' },
  { label: '限速', value: 'speed_limit' },
  { label: '中断', value: 'interruption' },
]

export const DAY_SECONDS = 24 * 60 * 60
export const HOUR_SECONDS = 60 * 60

export function buildRunGraphUsages(scenarios: ScenarioVisualizationItem[]) {
  const usages = new Map<string, RunGraphUsage>()
  for (const scenario of scenarios) {
    const runGraph = scenario.run_graph
    if (!runGraph) continue
    const key = runGraphKey(runGraph)
    const existing = usages.get(key)
    if (existing) {
      existing.scenarioCount += 1
      existing.disturbanceCount += scenario.counts.total
    } else {
      usages.set(key, {
        key,
        label: runGraphLabel(runGraph),
        runGraph,
        scenarioCount: 1,
        disturbanceCount: scenario.counts.total,
      })
    }
  }
  return [...usages.values()].sort((left, right) =>
    right.scenarioCount - left.scenarioCount ||
    right.disturbanceCount - left.disturbanceCount ||
    left.label.localeCompare(right.label),
  )
}

export function runGraphKey(runGraph: RunGraphReference) {
  return `${runGraph.set_id}\u0000${runGraph.graph_id}\u0000${runGraph.context_sha256}`
}

export function runGraphLabel(runGraph: RunGraphReference) {
  return `${runGraph.set_id} / ${runGraph.graph_id}`
}

export function sameRunGraph(
  left: RunGraphReference | null | undefined,
  right: RunGraphReference | null | undefined,
) {
  if (!left || !right) return false
  return (
    left.set_id === right.set_id &&
    left.graph_id === right.graph_id &&
    left.context_sha256 === right.context_sha256
  )
}

export function overviewDisturbancesForRunGraph(
  scenarios: ScenarioVisualizationItem[],
  runGraph: RunGraphReference | null,
  rows: TimetableRowState[],
) {
  if (!runGraph) return []
  return normalizeOverviewDisturbances(
    scenarios
      .filter((scenario) => sameRunGraph(scenario.run_graph, runGraph))
      .flatMap((scenario) =>
        scenario.disturbances.map((item) => ({ ...item, scenario_id: scenario.scenario_id })),
      ),
    rows,
  )
}

export function buildDisturbanceTimeDistribution(items: TimetableDisturbance[]): DisturbanceTimeBucket[] {
  const buckets: DisturbanceTimeBucket[] = Array.from({ length: 24 }, (_, hour) => ({
    label: `${formatDayClockTime(hour * HOUR_SECONDS)} - ${formatDayClockTime((hour + 1) * HOUR_SECONDS)}`,
    seconds: hour * HOUR_SECONDS,
    total: 0,
    delay: 0,
    speed_limit: 0,
    interruption: 0,
  }))
  for (const item of items) {
    if (typeof item.start_time !== 'number' || !Number.isFinite(item.start_time)) continue
    const hour = Math.max(0, Math.min(23, Math.floor(item.start_time / HOUR_SECONDS)))
    const bucket = buckets[hour]
    if (!bucket) continue
    bucket.total += 1
    bucket[item.type] += 1
  }
  return buckets
}

export function buildDisturbanceSpaceDistribution(
  items: TimetableDisturbance[],
  type: DisturbanceSeriesKey,
) {
  const counts = new Map<string, number>()
  for (const item of items) {
    if (type !== 'total' && item.type !== type) continue
    const label = disturbanceSpaceLabel(item)
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label))
}

export function buildRunGraphSpaceSeries(
  items: TimetableDisturbance[],
  stationOrder: string[],
  mileageByStation: Record<string, number>,
) {
  const rows = new Map<string, DisturbanceSpacePoint>()
  for (const station of stationOrder) {
    const mileage = mileageByStation[station]
    if (typeof mileage !== 'number' || !Number.isFinite(mileage)) continue
    rows.set(stationKey(station), emptySpacePoint(stationKey(station), station, mileage))
  }
  for (let index = 0; index < stationOrder.length - 1; index += 1) {
    const start = stationOrder[index]
    const end = stationOrder[index + 1]
    if (!start || !end) continue
    const point = sectionSpacePoint(start, end, mileageByStation)
    if (point) rows.set(point.key, point)
  }

  for (const item of items) {
    const point = disturbanceSpacePoint(item, mileageByStation)
    if (!point) continue
    const row = rows.get(point.key) ?? point
    row.total += 1
    row[item.type] += 1
    rows.set(point.key, row)
  }
  return [...rows.values()].sort((left, right) => left.mileage - right.mileage || left.label.localeCompare(right.label))
}

export function disturbanceSpaceLabel(item: TimetableDisturbance) {
  if (item.type === 'delay') return item.station || '未知'
  const start = item.start_station || ''
  const end = item.end_station || ''
  return start || end ? `${start}-${end}` : '未知'
}

function disturbanceSpacePoint(
  item: TimetableDisturbance,
  mileageByStation: Record<string, number>,
) {
  if (item.type === 'delay') {
    const station = item.station || ''
    const mileage = mileageByStation[station]
    if (typeof mileage !== 'number' || !Number.isFinite(mileage)) return null
    return emptySpacePoint(stationKey(station), station, mileage)
  }
  if (!item.start_station || !item.end_station) return null
  return sectionSpacePoint(item.start_station, item.end_station, mileageByStation)
}

function sectionSpacePoint(
  startStation: string,
  endStation: string,
  mileageByStation: Record<string, number>,
) {
  const startMileage = mileageByStation[startStation]
  const endMileage = mileageByStation[endStation]
  if (
    typeof startMileage !== 'number' ||
    typeof endMileage !== 'number' ||
    !Number.isFinite(startMileage) ||
    !Number.isFinite(endMileage)
  ) {
    return null
  }
  const [leftStation, rightStation] = startMileage <= endMileage
    ? [startStation, endStation]
    : [endStation, startStation]
  const leftMileage = Math.min(startMileage, endMileage)
  const rightMileage = Math.max(startMileage, endMileage)
  const tooltipLabel = `${leftStation}-${rightStation}`
  return emptySpacePoint(sectionKey(leftStation, rightStation), '', (leftMileage + rightMileage) / 2, tooltipLabel)
}

function emptySpacePoint(
  key: string,
  label: string,
  mileage: number,
  tooltipLabel = label,
): DisturbanceSpacePoint {
  return {
    key,
    label,
    tooltipLabel,
    mileage,
    total: 0,
    delay: 0,
    speed_limit: 0,
    interruption: 0,
  }
}

function stationKey(station: string) {
  return `station:${station}`
}

function sectionKey(startStation: string, endStation: string) {
  return `section:${startStation}\u0000${endStation}`
}

function normalizeOverviewDisturbances(
  disturbances: TimetableDisturbance[],
  rows: TimetableRowState[],
) {
  const eventTime = timetableEventTime(rows)
  const stationOrder = timetableStationOrder(rows)
  return disturbances.map((item) => {
    if (item.type !== 'delay') return item
    const key = `${item.train_id ?? ''}\u0000${item.station ?? ''}\u0000${item.event_type ?? ''}`
    return {
      ...item,
      start_time: typeof item.start_time === 'number' ? item.start_time : eventTime.get(key),
      station_order: typeof item.station_order === 'number' ? item.station_order : stationOrder.get(item.station ?? ''),
    }
  })
}

function timetableEventTime(rows: TimetableRowState[]) {
  const result = new Map<string, number>()
  for (const row of rows) {
    const arrival = parseTime(row.arrival_time)
    if (arrival != null) result.set(`${row.train_id}\u0000${row.station}\u0000arr`, arrival)
    const departure = parseTime(row.departure_time)
    if (departure != null) result.set(`${row.train_id}\u0000${row.station}\u0000dep`, departure)
  }
  return result
}

function timetableStationOrder(rows: TimetableRowState[]) {
  const result = new Map<string, number>()
  for (const row of rows) {
    if (!result.has(row.station)) result.set(row.station, result.size)
  }
  return result
}

function parseTime(value: string | null | undefined) {
  if (!value) return null
  const [hour, minute, second] = value.split(':').map(Number)
  if (![hour, minute, second].every((item) => Number.isFinite(item))) return null
  return (hour ?? 0) * 3600 + (minute ?? 0) * 60 + (second ?? 0)
}

function formatClockTime(totalSeconds: number) {
  const sign = totalSeconds < 0 ? '-' : ''
  const absoluteSeconds = Math.abs(Math.round(totalSeconds))
  const hours = Math.floor(absoluteSeconds / 3600)
  const minutes = Math.floor((absoluteSeconds % 3600) / 60)
  const seconds = absoluteSeconds % 60
  const prefix = `${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
  return seconds ? `${prefix}:${String(seconds).padStart(2, '0')}` : prefix
}

export function formatDayClockTime(totalSeconds: number) {
  if (!Number.isFinite(totalSeconds)) return ''
  const seconds = Math.max(0, Math.min(DAY_SECONDS, Math.round(totalSeconds)))
  if (seconds === DAY_SECONDS) return '24:00'
  return formatClockTime(seconds)
}
