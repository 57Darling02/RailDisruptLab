<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'

import { chartDownloadToolbox } from '@/chart-options'
import type { TimetableDisturbance, TimetableRowState } from '@/types'

const PLAN_NORMAL_COLOR = '#2563eb'
const PLAN_AFFECTED_COLOR = '#dc2626'
const ADJUSTED_COLOR = '#16a34a'
const STATION_LINE_COLOR = '#e5e7eb'
const DISTURBANCE_COLOR = {
  delay: '#f59e0b',
  speed_limit: '#3b82f6',
  interruption: '#ef4444',
} as const
const DISTURBANCE_LABEL = {
  delay: '晚点',
  speed_limit: '限速',
  interruption: '中断',
} as const
const TRAIN_SERIES_ID_PREFIX = 'train:'
const props = withDefaults(
  defineProps<{
    rows: TimetableRowState[]
    stationOrder: string[]
    disturbances?: TimetableDisturbance[]
    title?: string
    planRows?: TimetableRowState[]
    compareMode?: boolean
  }>(),
  {
    disturbances: () => [],
    title: '运行图',
    planRows: () => [],
    compareMode: false,
  },
)

const chartOption = computed(() =>
  buildTimetableOption({
    adjustedRows: props.rows,
    planRows: props.planRows,
    stationOrder: props.stationOrder,
    disturbances: props.disturbances,
    title: props.title,
    compareMode: props.compareMode,
  }),
)
const hasRows = computed(() => props.rows.length > 0 || props.planRows.length > 0)
const fullscreenVisible = ref(false)
const chartRef = ref<InstanceType<typeof VChart> | null>(null)
const fullscreenChartRef = ref<InstanceType<typeof VChart> | null>(null)
const trainTooltip = ref({
  visible: false,
  x: null as number | null,
  y: null as number | null,
  text: '',
})
const trainTooltipStyle = computed(() => {
  if (trainTooltip.value.x == null || trainTooltip.value.y == null) return {}
  return {
    left: `${trainTooltip.value.x}px`,
    top: `${trainTooltip.value.y}px`,
  }
})

interface BuildInput {
  adjustedRows: TimetableRowState[]
  planRows: TimetableRowState[]
  stationOrder: string[]
  disturbances: TimetableDisturbance[]
  title: string
  compareMode: boolean
}

function buildTimetableOption(input: BuildInput) {
  const sourceRows = input.compareMode ? [...input.planRows, ...input.adjustedRows] : input.adjustedRows
  const stations = visibleStations(sourceRows, input.stationOrder)
  const stationIndex = new Map(stations.map((station, index) => [station, index]))
  const planRows = input.compareMode ? input.planRows : input.adjustedRows
  const affectedTrains = affectedTrainIds(
    planRows,
    input.compareMode ? input.adjustedRows : [],
    input.disturbances,
    stationIndex,
  )
  const trainLineSeries = input.compareMode
    ? [
        ...lineSeriesByTrain({
          rows: planRows,
          stationIndex,
          namePrefix: '原计划',
          colorForTrain: (trainId) =>
            affectedTrains.has(trainId) ? PLAN_AFFECTED_COLOR : PLAN_NORMAL_COLOR,
          lineTypeForTrain: () => 'solid',
          z: 3,
        }),
        ...lineSeriesByTrain({
          rows: input.adjustedRows,
          stationIndex,
          namePrefix: '调整计划',
          trainFilter: (trainId) => affectedTrains.has(trainId),
          colorForTrain: () => ADJUSTED_COLOR,
          lineTypeForTrain: (_trainId, rows) => (rows.some((row) => row.is_canceled) ? 'dashed' : 'solid'),
          z: 4,
        }),
      ]
    : lineSeriesByTrain({
        rows: input.adjustedRows,
        stationIndex,
        namePrefix: '原计划',
        colorForTrain: () => PLAN_NORMAL_COLOR,
        lineTypeForTrain: () => 'solid',
        z: 3,
      })
  const extent = timeExtent(sourceRows, input.disturbances)

  return {
    animationDuration: 260,
    toolbox: chartDownloadToolbox(fileNameFromTitle(input.title)),
    grid: { top: 68, right: 32, bottom: 72, left: 96 },
    legend: {
      top: 30,
      type: 'scroll',
      selectedMode: true,
      data: legendItems(input.compareMode),
    },
    tooltip: {
      trigger: 'item',
      formatter: formatTooltip,
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      { type: 'slider', xAxisIndex: 0, height: 22, bottom: 24 },
    ],
    xAxis: {
      type: 'value',
      name: '时间',
      min: extent.min,
      max: extent.max,
      axisLabel: { formatter: secondsToHm },
      splitLine: { show: true, lineStyle: { color: '#f3f4f6' } },
    },
    yAxis: {
      type: 'category',
      name: '车站',
      data: stations,
      axisTick: { show: false },
      axisLabel: { interval: 0 },
      splitLine: { show: false },
    },
    series: [
      stationLineSeries(stations, extent),
      ...disturbanceSeries(input.disturbances, stationIndex),
      ...trainLineSeries,
    ],
    title: { text: input.title, left: 8, top: 6, textStyle: { fontSize: 13, fontWeight: 600 } },
  }
}

function fileNameFromTitle(title: string) {
  return title.trim().replace(/[^\p{L}\p{N}_-]+/gu, '-').replace(/^-+|-+$/g, '') || 'timetable-chart'
}

interface ChartPoint {
  value: [number, number]
  trainId: string
  detail?: string
}

interface CustomRenderParams {
  coordSys?: {
    x: number
    y: number
    width: number
    height: number
  }
}

interface CustomRenderApi {
  value: (index: number) => number | string
  coord: (value: [number, number]) => [number, number]
  size: (value: [number, number]) => [number, number]
  style: (style?: Record<string, unknown>) => Record<string, unknown>
}

interface DisturbanceRect {
  value: [number, number, number, number, string]
  itemStyle: {
    color: string
    opacity: number
    borderColor: string
    borderWidth: number
    borderType?: 'solid' | 'dashed'
  }
  detail: string
}

function visibleStations(rows: TimetableRowState[], stationOrder: string[]) {
  const rowStations = new Set(rows.map((row) => row.station))
  const ordered = stationOrder.filter((station) => rowStations.has(station))
  return ordered.length ? ordered : [...rowStations]
}

function affectedTrainIds(
  planRows: TimetableRowState[],
  adjustedRows: TimetableRowState[],
  disturbances: TimetableDisturbance[],
  stationIndex: Map<string, number>,
) {
  const result = new Set<string>()
  for (const item of disturbances) {
    if (item.type === 'delay' && item.train_id) {
      result.add(String(item.train_id))
    }
  }
  const sectionDisturbances = disturbances.filter((item) => item.type !== 'delay')
  if (sectionDisturbances.length) {
    for (const [trainId, trainRows] of groupRowsByTrain(planRows, stationIndex)) {
      if (trainRows.some((row, index) => isTrainSectionAffected(row, trainRows[index + 1], sectionDisturbances))) {
        result.add(trainId)
      }
    }
  }
  for (const trainId of adjustedTrainIds(planRows, adjustedRows)) {
    result.add(trainId)
  }
  return result
}

function adjustedTrainIds(planRows: TimetableRowState[], adjustedRows: TimetableRowState[]) {
  const result = new Set<string>()
  const planByKey = new Map(planRows.map((row) => [rowKey(row), row]))
  for (const row of adjustedRows) {
    if (isAdjustedRow(row, planByKey)) result.add(row.train_id)
  }
  return result
}

function isTrainSectionAffected(
  current: TimetableRowState,
  next: TimetableRowState | undefined,
  disturbances: TimetableDisturbance[],
) {
  if (!next) return false
  const dep = parseTime(current.departure_time)
  const arr = parseTime(next.arrival_time)
  if (dep == null || arr == null) return false
  const sectionStart = current.station
  const sectionEnd = next.station
  return disturbances.some((item) => {
    if (!item.start_station || !item.end_station) return false
    const start = item.start_time ?? 0
    const end = Math.max(item.end_time ?? start + 1, start + 1)
    return sameSection(sectionStart, sectionEnd, item.start_station, item.end_station) && overlaps(dep, arr, start, end)
  })
}

function sameSection(leftStart: string, leftEnd: string, rightStart: string, rightEnd: string) {
  return (
    (leftStart === rightStart && leftEnd === rightEnd) ||
    (leftStart === rightEnd && leftEnd === rightStart)
  )
}

function overlaps(leftStart: number, leftEnd: number, rightStart: number, rightEnd: number) {
  return Math.max(leftStart, rightStart) <= Math.min(leftEnd, rightEnd)
}

function legendItems(compareMode: boolean) {
  if (!compareMode) return ['原计划', '晚点', '限速', '中断']
  return ['原计划-未受影响', '原计划-受影响', '调整计划', '晚点', '限速', '中断']
}

function isAdjustedRow(row: TimetableRowState, planByKey: Map<string, TimetableRowState>) {
  const plan = planByKey.get(rowKey(row))
  return (
    !plan ||
    normalizeTime(row.arrival_time) !== normalizeTime(plan.arrival_time) ||
    normalizeTime(row.departure_time) !== normalizeTime(plan.departure_time) ||
    Boolean(row.is_canceled) !== Boolean(plan.is_canceled)
  )
}

function rowKey(row: TimetableRowState) {
  return `${row.train_id}\u0000${row.station}`
}

function normalizeTime(value: string | null) {
  return value || ''
}

function lineSeriesByTrain({
  rows,
  stationIndex,
  namePrefix,
  trainFilter = () => true,
  segmentFilter = () => true,
  colorForTrain,
  lineTypeForTrain,
  z,
}: {
  rows: TimetableRowState[]
  stationIndex: Map<string, number>
  namePrefix: string
  trainFilter?: (trainId: string, rows: TimetableRowState[]) => boolean
  segmentFilter?: (current: TimetableRowState, next: TimetableRowState, trainId: string) => boolean
  colorForTrain: (trainId: string, rows: TimetableRowState[]) => string
  lineTypeForTrain: (trainId: string, rows: TimetableRowState[]) => 'solid' | 'dashed'
  z: number
}) {
  const byTrain = groupRowsByTrain(rows, stationIndex)
  const series: object[] = []
  for (const [trainId, trainRows] of byTrain) {
    if (!trainFilter(trainId, trainRows)) continue
    const color = colorForTrain(trainId, trainRows)
    const lineType = lineTypeForTrain(trainId, trainRows)
    const name = seriesName(namePrefix, color)
    series.push({
      id: trainSeriesId(trainId, name),
      name,
      type: 'line',
      data: trainLineData(trainId, trainRows, stationIndex, segmentFilter),
      connectNulls: false,
      showSymbol: false,
      triggerEvent: 'line',
      lineStyle: { width: 1.15, type: lineType, color },
      emphasis: { focus: 'series' },
      z,
    })
  }
  return series
}

function seriesName(prefix: string, color: string) {
  if (prefix === '原计划') {
    return color === PLAN_AFFECTED_COLOR ? '原计划-受影响' : '原计划-未受影响'
  }
  if (prefix === '调整计划') {
    return '调整计划'
  }
  return prefix
}

function trainSeriesId(trainId: string, scope: string) {
  return `${TRAIN_SERIES_ID_PREFIX}${encodeURIComponent(trainId)}|${encodeURIComponent(scope)}`
}

function trainIdFromSeriesId(seriesId: unknown) {
  if (typeof seriesId !== 'string' || !seriesId.startsWith(TRAIN_SERIES_ID_PREFIX)) return ''
  const [trainId = ''] = seriesId.slice(TRAIN_SERIES_ID_PREFIX.length).split('|')
  return decodeURIComponent(trainId)
}

function groupRowsByTrain(rows: TimetableRowState[], stationIndex: Map<string, number>) {
  const byTrain = new Map<string, TimetableRowState[]>()
  for (const row of rows) {
    if (!stationIndex.has(row.station)) continue
    const trainRows = byTrain.get(row.train_id) ?? []
    trainRows.push(row)
    byTrain.set(row.train_id, trainRows)
  }
  for (const trainRows of byTrain.values()) {
    trainRows.sort((left, right) => left.row_number - right.row_number)
  }
  return byTrain
}

function trainLineData(
  trainId: string,
  trainRows: TimetableRowState[],
  stationIndex: Map<string, number>,
  segmentFilter: (current: TimetableRowState, next: TimetableRowState, trainId: string) => boolean,
): (ChartPoint | null)[] {
  const data: (ChartPoint | null)[] = []
  for (let index = 0; index < trainRows.length; index += 1) {
    const row = trainRows[index]
    const next = trainRows[index + 1]
    if (!row) continue

    const arrivalPoint = timetablePoint(trainId, row, stationIndex, '到达')
    const departurePoint = timetablePoint(trainId, row, stationIndex, '出发')
    if (arrivalPoint && departurePoint) {
      data.push(arrivalPoint, departurePoint)
    }

    if (!next) continue
    const nextArrivalPoint = timetablePoint(trainId, next, stationIndex, '到达')
    const canConnectToNext = Boolean(departurePoint) && Boolean(nextArrivalPoint)
    if (canConnectToNext && segmentFilter(row, next, trainId) && departurePoint && nextArrivalPoint) {
      if (!departurePointIsLast(data, departurePoint)) data.push(departurePoint)
      data.push(nextArrivalPoint)
    } else {
      data.push(null)
    }
  }
  return data
}

function timetablePoint(
  trainId: string,
  row: TimetableRowState,
  stationIndex: Map<string, number>,
  event: '到达' | '出发',
): ChartPoint | null {
  const time = parseTime(event === '到达' ? row.arrival_time : row.departure_time)
  const y = stationIndex.get(row.station)
  if (time == null || y == null) return null
  return {
    value: [time, y],
    trainId,
    detail: `车次：${trainId}`,
  }
}

function departurePointIsLast(data: (ChartPoint | null)[], point: ChartPoint) {
  const last = data.at(-1)
  return Boolean(last && last.value[0] === point.value[0] && last.value[1] === point.value[1])
}

function stationLineSeries(stations: string[], extent: { min: number; max: number }) {
  return {
    name: '站点水平线',
    type: 'custom',
    legendHoverLink: false,
    silent: true,
    encode: { x: [0, 1], y: 2 },
    data: stations.map((station, index) => ({
      value: [extent.min, extent.max, index],
    })),
    renderItem: (_params: CustomRenderParams, api: CustomRenderApi) => {
      const start = api.coord([Number(api.value(0)), Number(api.value(2))])
      const end = api.coord([Number(api.value(1)), Number(api.value(2))])
      return {
        type: 'line',
        shape: { x1: start[0], y1: start[1], x2: end[0], y2: end[1] },
        style: { stroke: STATION_LINE_COLOR, lineWidth: 1 },
      }
    },
    z: 0,
  }
}

function disturbanceSeries(
  disturbances: TimetableDisturbance[],
  stationIndex: Map<string, number>,
) {
  const byType: Record<keyof typeof DISTURBANCE_COLOR, DisturbanceRect[]> = {
    delay: [],
    speed_limit: [],
    interruption: [],
  }
  for (const item of disturbances) {
    const rect = disturbanceRect(item, stationIndex)
    if (rect) byType[item.type].push(rect)
  }
  return (Object.keys(byType) as (keyof typeof DISTURBANCE_COLOR)[])
    .filter((type) => byType[type].length > 0)
    .map((type) => ({
      name: DISTURBANCE_LABEL[type],
      type: 'custom',
      data: byType[type],
      tooltip: { trigger: 'item' },
      renderItem: renderDisturbanceRect,
      z: 1,
    }))
}

function disturbanceRect(
  item: TimetableDisturbance,
  stationIndex: Map<string, number>,
): DisturbanceRect | null {
  if (item.type === 'delay') {
    if (!item.station) return null
    const stationY = stationIndex.get(item.station)
    if (stationY == null) return null
    const start = typeof item.start_time === 'number' ? item.start_time : 0
    const seconds = Math.max(0, Number(item.seconds ?? 0) || 0)
    return makeRect({
      type: item.type,
      start,
      end: start + seconds,
      yCenter: stationY,
      height: 0.16,
      detail: `${DISTURBANCE_LABEL.delay} ${item.train_id ?? ''} ${item.station} ${item.event_type ?? ''} +${item.seconds ?? 0}s`,
    })
  }

  if (!item.start_station || !item.end_station) return null
  const startY = stationIndex.get(item.start_station)
  const endY = stationIndex.get(item.end_station)
  if (startY == null || endY == null) return null
  const lower = Math.min(startY, endY)
  const upper = Math.max(startY, endY)
  const start = item.start_time ?? 0
  const end = Math.max(item.end_time ?? start + 1, start + 1)
  return makeRect({
    type: item.type,
    start,
    end,
    yCenter: (lower + upper) / 2,
    height: Math.max(0.72, upper - lower),
    detail: `${DISTURBANCE_LABEL[item.type]} ${item.start_station}-${item.end_station} ${secondsToHms(start)}-${secondsToHms(end)}`,
  })
}

function makeRect({
  type,
  start,
  end,
  yCenter,
  height,
  detail,
}: {
  type: keyof typeof DISTURBANCE_COLOR
  start: number
  end: number
  yCenter: number
  height: number
  detail: string
}): DisturbanceRect {
  const color = DISTURBANCE_COLOR[type]
  return {
    value: [start, end, yCenter, height, detail],
    itemStyle: {
      color,
      opacity: type === 'delay' ? 0.3 : 0.2,
      borderColor: color,
      borderWidth: 1,
      borderType: type === 'interruption' ? 'dashed' : 'solid',
    },
    detail,
  }
}

function renderDisturbanceRect(params: CustomRenderParams, api: CustomRenderApi) {
  const start = Number(api.value(0))
  const end = Number(api.value(1))
  const yCenter = Number(api.value(2))
  const heightUnits = Number(api.value(3))
  const startCenter = api.coord([start, yCenter])
  const endCenter = api.coord([end, yCenter])
  const bandHeight = Math.abs(api.size([0, Math.max(heightUnits, 0.08)])[1])
  const coordSys = params.coordSys
  if (!coordSys || !startCenter.every(Number.isFinite) || !endCenter.every(Number.isFinite)) return null
  const x = Math.max(Math.min(startCenter[0], endCenter[0]), coordSys.x)
  const y = Math.max(startCenter[1] - bandHeight / 2, coordSys.y)
  const right = Math.min(Math.max(startCenter[0], endCenter[0]), coordSys.x + coordSys.width)
  const bottom = Math.min(startCenter[1] + bandHeight / 2, coordSys.y + coordSys.height)
  if (right <= x || bottom <= y) return null
  return {
    type: 'rect',
    shape: { x, y, width: right - x, height: bottom - y },
    style: api.style(),
  }
}

function timeExtent(rows: TimetableRowState[], disturbances: TimetableDisturbance[]) {
  const values = rows.flatMap((row) => [parseTime(row.arrival_time), parseTime(row.departure_time)])
  for (const item of disturbances) {
    if (typeof item.start_time === 'number') values.push(item.start_time)
    if (typeof item.end_time === 'number') values.push(item.end_time)
    if (item.type === 'delay' && typeof item.start_time === 'number') {
      values.push(item.start_time + Math.max(0, Number(item.seconds ?? 0) || 0))
    }
  }
  const times = values.filter((value): value is number => value != null)
  if (!times.length) return { min: 0, max: 24 * 3600 }
  const min = Math.max(0, Math.floor(Math.min(...times) / 600) * 600)
  const max = Math.min(24 * 3600, Math.ceil(Math.max(...times) / 600) * 600)
  return { min, max: Math.max(max, min + 600) }
}

function parseTime(value: string | null | undefined) {
  if (!value) return null
  const [hour, minute, second] = value.split(':').map(Number)
  if (![hour, minute, second].every((item) => Number.isFinite(item))) return null
  return (hour ?? 0) * 3600 + (minute ?? 0) * 60 + (second ?? 0)
}

function secondsToHm(value: number) {
  const total = Math.max(0, Math.round(value))
  const hour = Math.floor(total / 3600)
  const minute = Math.floor((total % 3600) / 60)
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

function secondsToHms(value: number) {
  const total = Math.max(0, Math.round(value))
  const hour = Math.floor(total / 3600)
  const minute = Math.floor((total % 3600) / 60)
  const second = total % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`
}

function formatTooltip(params: { data?: ChartPoint | DisturbanceRect; name?: string; value?: unknown }) {
  const data = params.data
  if (data && 'detail' in data && data.detail) return data.detail
  if (data && 'trainId' in data) return `车次：${data.trainId}`
  if (Array.isArray(params.value)) {
    const [time, y] = params.value as [number, number]
    return `${Number(y).toFixed(0)}<br/>${secondsToHms(time)}`
  }
  return params.name ?? ''
}

function showTrainTooltip(params: unknown) {
  const payload = objectRecord(params)
  if (payload?.componentType !== 'series') {
    hideTrainTooltip()
    return
  }
  const trainId = trainIdFromPayload(payload)
  const pointer = chartPointer(payload.event)
  if (!trainId) {
    hideTrainTooltip()
    return
  }
  trainTooltip.value = {
    visible: true,
    x: pointer ? pointer.x + 12 : null,
    y: pointer ? pointer.y + 12 : null,
    text: `${trainId}`,
  }
}

function trainIdFromPayload(payload: Record<string, unknown>) {
  const fromId = trainIdFromSeriesId(payload.seriesId)
  if (fromId) return fromId
  const seriesIndex = integerValue(payload.seriesIndex)
  if (seriesIndex == null) return ''
  return trainIdFromSeries(seriesIndex)
}

function trainIdFromSeries(seriesIndex: number) {
  const option = objectRecord(chartOption.value)
  const series = option?.series
  if (!Array.isArray(series)) return ''
  return trainIdFromSeriesId(objectRecord(series[seriesIndex])?.id)
}

function hideTrainTooltip() {
  trainTooltip.value.visible = false
}

function chartPointer(eventPayload: unknown) {
  const event = objectRecord(eventPayload)
  const nativeEvent = objectRecord(event?.event)
  const x = firstNumber(nativeEvent?.clientX, event?.clientX)
  const y = firstNumber(nativeEvent?.clientY, event?.clientY)
  if (x != null && y != null) return { x, y }
  return chartLocalPointer(event, fullscreenVisible.value ? fullscreenChartRef.value : chartRef.value)
}

function chartLocalPointer(event: Record<string, unknown> | null, chart: InstanceType<typeof VChart> | null) {
  const offsetX = firstNumber(event?.zrX, event?.offsetX)
  const offsetY = firstNumber(event?.zrY, event?.offsetY)
  const rect = chart?.root?.getBoundingClientRect()
  if (offsetX == null || offsetY == null || !rect) return null
  return { x: rect.left + offsetX, y: rect.top + offsetY }
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function integerValue(value: unknown): number | null {
  const number = numberValue(value)
  return number == null ? null : Math.trunc(number)
}

function firstNumber(...values: unknown[]) {
  for (const value of values) {
    const number = numberValue(value)
    if (number != null) return number
  }
  return null
}
</script>

<template>
  <div class="timetable-chart-wrap">
    <div v-if="hasRows" class="chart-toolbar">
      <el-button size="small" @click="fullscreenVisible = true">全屏查看</el-button>
    </div>
    <VChart
      v-if="hasRows"
      ref="chartRef"
      :option="chartOption"
      autoresize
      class="timetable-chart"
      @mouseover="showTrainTooltip"
      @mousemove="showTrainTooltip"
      @mouseout="hideTrainTooltip"
      @globalout="hideTrainTooltip"
    />
    <div
      v-if="trainTooltip.visible"
      class="train-tooltip"
      :class="{ 'is-fixed': trainTooltip.x != null && trainTooltip.y != null }"
      :style="trainTooltipStyle"
    >
      {{ trainTooltip.text }}
    </div>
    <el-empty v-else-if="!hasRows" description="暂无可展示的运行图数据" :image-size="72" />
    <el-dialog
      v-model="fullscreenVisible"
      :title="title"
      fullscreen
      append-to-body
      destroy-on-close
    >
      <VChart
        ref="fullscreenChartRef"
        :option="chartOption"
        autoresize
        class="fullscreen-chart"
        @mouseover="showTrainTooltip"
        @mousemove="showTrainTooltip"
        @mouseout="hideTrainTooltip"
        @globalout="hideTrainTooltip"
      />
    </el-dialog>
  </div>
</template>

<style scoped>
.timetable-chart-wrap {
  position: relative;
  width: 100%;
}

.chart-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.timetable-chart {
  display: block;
  width: 100%;
  height: 460px;
}

.fullscreen-chart {
  width: 100%;
  height: calc(100vh - 96px);
}

.train-tooltip {
  position: absolute;
  top: 42px;
  right: 12px;
  z-index: 3000;
  padding: 7px 10px;
  border-radius: 4px;
  color: #fff;
  background: rgb(0 0 0 / 78%);
  font-size: 13px;
  line-height: 1.4;
  pointer-events: none;
  box-shadow: 0 4px 12px rgb(0 0 0 / 18%);
}

.train-tooltip.is-fixed {
  position: fixed;
  inset: auto auto auto auto;
}
</style>
