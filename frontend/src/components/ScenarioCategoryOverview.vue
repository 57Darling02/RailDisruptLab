<script setup lang="ts">
import { computed, ref } from 'vue'

import ChartPanel from '@/components/ChartPanel.vue'
import FieldLabelTip from '@/components/FieldLabelTip.vue'
import RunGraphSpaceDistributionChart from '@/components/RunGraphSpaceDistributionChart.vue'
import TimetableChart from '@/components/TimetableChart.vue'
import type {
  RunGraphReference,
  RunGraphTimetableState,
  ScenarioSetVisualization,
  TimetableDisturbance,
} from '@/types'
import {
  DAY_SECONDS,
  DISTURBANCE_SERIES,
  DISTURBANCE_TYPE_OPTIONS,
  buildDisturbanceSpaceDistribution,
  buildDisturbanceTimeDistribution,
  disturbanceSpaceLabel,
  formatDayClockTime,
  overviewDisturbancesForRunGraph,
  sameRunGraph,
  type DisturbanceSeriesKey,
  type RunGraphUsage,
} from '@/components/scenario-category'

const props = defineProps<{
  analysis: ScenarioSetVisualization
  runGraphUsages: RunGraphUsage[]
  selectedRunGraph: RunGraphReference | null
  runGraphTimetable: RunGraphTimetableState | null
  runGraphLoading?: boolean
  runGraphErrorMessage?: string
}>()

const emit = defineEmits<{
  selectRunGraph: [runGraph: RunGraphReference | null]
}>()

const selectedSpaceType = ref<DisturbanceSeriesKey>('total')
const DISTURBANCE_TYPES: Array<{ key: TimetableDisturbance['type']; label: string; color: string }> = [
  { key: 'delay', label: '晚点', color: '#f59e0b' },
  { key: 'speed_limit', label: '限速', color: '#3b82f6' },
  { key: 'interruption', label: '中断', color: '#ef4444' },
]

const selectedRunGraphUsage = computed(() =>
  props.runGraphUsages.find((item) => sameRunGraph(item.runGraph, props.selectedRunGraph)) ?? null,
)
const selectedRunGraphDisturbances = computed(() =>
  overviewDisturbancesForRunGraph(
    props.analysis.scenarios,
    props.selectedRunGraph,
    props.runGraphTimetable?.plan.rows ?? [],
  ),
)
const selectedRunGraphTimeDistribution = computed(() =>
  buildDisturbanceTimeDistribution(selectedRunGraphDisturbances.value),
)
const selectedRunGraphTimeOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    formatter: (params: unknown) => timeLineTooltip(params),
  },
  legend: {
    top: 0,
    data: DISTURBANCE_SERIES.map((item) => item.label),
    selected: {
      总数: true,
      晚点: false,
      限速: false,
      中断: false,
    },
  },
  grid: { top: 48, right: 18, bottom: 72, left: 48 },
  xAxis: {
    type: 'value',
    min: 0,
    max: DAY_SECONDS,
    interval: 60 * 60,
    axisLabel: { formatter: (value: number) => formatDayClockTime(value) },
  },
  yAxis: { type: 'value', name: '数量' },
  dataZoom: [
    { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
    { type: 'slider', xAxisIndex: 0, height: 22, bottom: 18, filterMode: 'none' },
  ],
  series: DISTURBANCE_SERIES.map((series) => ({
    name: series.label,
    type: 'line',
    smooth: true,
    showSymbol: false,
    areaStyle: { opacity: 0.12 },
    emphasis: { focus: 'series' },
    data: selectedRunGraphTimeDistribution.value.map((item) => [item.seconds, item[series.key], item.label]),
  })),
}))
const spaceOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
  legend: rightLegend(120),
  series: [
    rightLegendPieSeries(
      spaceTypeLabel(selectedSpaceType.value),
      buildDisturbanceSpaceDistribution(props.analysis.summary.disturbances ?? [], selectedSpaceType.value)
        .map((item) => ({ name: item.label, value: item.count })),
      120,
    ),
  ],
}))
const typePieOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
  legend: rightLegend(76),
  series: [
    rightLegendPieSeries(
      '纯扰动与混合',
      scenarioCompositionRows.value.map((item) => ({ name: item.label, value: item.count })),
      76,
    ),
  ],
}))
const scenarioCompositionRows = computed(() => {
  const counts = new Map((props.analysis.summary.category_ratios ?? []).map((item) => [item.key, item.count]))
  return [
    { key: 'interruption', label: '纯中断', count: counts.get('interruption') ?? 0 },
    { key: 'speed_limit', label: '纯限速', count: counts.get('speed_limit') ?? 0 },
    { key: 'delay', label: '纯晚点', count: counts.get('delay') ?? 0 },
    { key: 'mixed', label: '混合', count: counts.get('mixed') ?? 0 },
  ].filter((item) => item.count > 0)
})
const disturbanceRatioOption = computed(() => {
  const counts = props.analysis.summary.disturbance_counts
  const rows = [
    { label: '晚点', count: counts?.delay ?? 0 },
    { label: '限速', count: counts?.speed_limit ?? 0 },
    { label: '中断', count: counts?.interruption ?? 0 },
  ].filter((item) => item.count > 0)
  return {
    tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
    legend: rightLegend(64),
    series: [
      rightLegendPieSeries(
        '扰动占比',
        rows.map((item) => ({ name: item.label, value: item.count })),
        64,
      ),
    ],
  }
})
const disturbanceDurationRows = computed(() => {
  const rows = DISTURBANCE_TYPES.map((item) => ({ key: item.key, label: item.label, seconds: 0 }))
  const byType = new Map(rows.map((item) => [item.key, item]))
  for (const item of props.analysis.summary.disturbances ?? []) {
    const row = byType.get(item.type)
    if (!row) continue
    row.seconds += disturbanceDurationSeconds(item)
  }
  return rows.filter((item) => item.seconds > 0)
})
const disturbanceDurationRatioOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 分钟 ({d}%)' },
  legend: rightLegend(64),
  series: [
    rightLegendPieSeries(
      '扰动时长占比',
      disturbanceDurationRows.value.map((item) => ({ name: item.label, value: roundMinutes(item.seconds) })),
      64,
    ),
  ],
}))
const disturbanceSeverityPoints = computed(() =>
  (props.analysis.summary.disturbances ?? [])
    .map((item, index) => ({
      item,
      index: index + 1,
      minutes: roundMinutes(disturbanceDurationSeconds(item)),
    }))
    .filter((item) => item.minutes > 0),
)
const disturbanceSeverityScatterOption = computed(() => ({
  tooltip: {
    trigger: 'item',
    formatter: (params: unknown) => severityTooltip(params),
  },
  legend: { top: 0, right: 12 },
  grid: { top: 42, right: 18, bottom: 36, left: 56 },
  xAxis: {
    type: 'value',
    name: '事件序号',
    min: 0,
    axisLabel: { hideOverlap: true },
  },
  yAxis: { type: 'value', name: '分钟' },
  series: DISTURBANCE_TYPES.map((type) => ({
    name: type.label,
    type: 'scatter',
    symbolSize: 8,
    itemStyle: { color: type.color },
    data: disturbanceSeverityPoints.value
      .filter((point) => point.item.type === type.key)
      .map((point) => ({
        value: [point.index, point.minutes],
        disturbance: point.item,
      })),
  })),
}))

function selectRunGraphByKey(value: unknown) {
  const key = typeof value === 'string' ? value : ''
  const usage = props.runGraphUsages.find((item) => item.key === key)
  emit('selectRunGraph', usage?.runGraph ?? null)
}

function rightLegend(width = 120) {
  return {
    top: 'middle',
    right: 8,
    type: 'plain',
    orient: 'vertical',
    tooltip: { show: true },
    itemWidth: 10,
    itemHeight: 8,
    itemGap: 7,
    textStyle: {
      fontSize: 11,
      overflow: 'truncate',
      width,
    },
  }
}

function rightLegendPieSeries(
  name: string,
  data: Array<{ name: string; value: number }>,
  labelWidth = 96,
) {
  return {
    name,
    type: 'pie',
    radius: ['36%', '62%'],
    center: ['38%', '50%'],
    label: {
      overflow: 'truncate',
      width: labelWidth,
    },
    data,
  }
}

function spaceTypeLabel(value: DisturbanceSeriesKey) {
  return DISTURBANCE_TYPE_OPTIONS.find((item) => item.value === value)?.label ?? value
}

function disturbanceDurationSeconds(item: TimetableDisturbance) {
  const value = item.type === 'delay' ? item.seconds : item.duration
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 0
}

function roundMinutes(seconds: number) {
  return Math.round((seconds / 60) * 10) / 10
}

function severityTooltip(params: unknown) {
  if (!params || typeof params !== 'object') return ''
  const data = (params as { data?: { value?: unknown[]; disturbance?: TimetableDisturbance } }).data
  const item = data?.disturbance
  if (!item) return ''
  const value = Array.isArray(data.value) ? Number(data.value[1] ?? 0) : roundMinutes(disturbanceDurationSeconds(item))
  const index = Array.isArray(data.value) ? Number(data.value[0] ?? 0) : 0
  return [
    `${disturbanceTypeLabel(item.type)} #${index}`,
    `程度：${value} 分钟`,
    `位置：${disturbanceSpaceLabel(item)}`,
  ].join('<br/>')
}

function disturbanceTypeLabel(type: TimetableDisturbance['type']) {
  return DISTURBANCE_TYPES.find((item) => item.key === type)?.label ?? type
}

function timeLineTooltip(params: unknown) {
  if (!Array.isArray(params)) return ''
  const first = params[0] as { data?: unknown[] } | undefined
  const label = Array.isArray(first?.data) && typeof first.data[2] === 'string' ? first.data[2] : '未知时间'
  const lines = [
    label,
    ...params.map((item) => {
      const payload = item as { marker?: string; seriesName?: string; data?: unknown[] }
      const value = Array.isArray(payload.data) ? payload.data[1] : 0
      return `${payload.marker ?? ''}${payload.seriesName ?? ''}: ${value}`
    }),
  ]
  return lines.join('<br/>')
}
</script>

<template>
  <el-row class="scenario-chart-row" :gutter="16">
    <el-col :xs="24">
      <el-card shadow="never">
        <template #header>
          <div class="chart-card-header">
            <span>场景运行图总览</span>
            <el-select
              :model-value="selectedRunGraphUsage?.key ?? ''"
              placeholder="选择运行图"
              size="small"
              class="overview-run-graph-select"
              :disabled="runGraphLoading || !runGraphUsages.length"
              @update:model-value="selectRunGraphByKey"
            >
              <template #empty>暂无数据</template>
              <el-option
                v-for="item in runGraphUsages"
                :key="item.key"
                :label="item.label"
                :value="item.key"
              >
                <div class="run-graph-option">
                  <span>{{ item.label }}</span>
                  <el-text type="info" size="small">
                    {{ item.scenarioCount }} 场景 · {{ item.disturbanceCount }} 扰动
                  </el-text>
                </div>
              </el-option>
            </el-select>
          </div>
        </template>
        <el-alert
          v-if="runGraphErrorMessage"
          class="overview-run-graph-alert"
          type="error"
          :closable="false"
          :title="runGraphErrorMessage"
        />
        <div class="overview-run-graph-chart" v-loading="runGraphLoading" element-loading-text="正在加载运行图...">
          <TimetableChart
            v-if="runGraphTimetable"
            :rows="runGraphTimetable.plan.rows"
            :station-order="runGraphTimetable.station_order"
            :disturbances="selectedRunGraphDisturbances"
            :title="`${selectedRunGraphUsage?.label ?? '运行图'} · ${selectedRunGraphDisturbances.length} 个扰动`"
          />
          <el-empty v-else description="暂无可展示的运行图" :image-size="72" />
        </div>
      </el-card>
    </el-col>

    <el-col :xs="24" :lg="14">
      <el-card shadow="never">
        <template #header>
          <div class="chart-card-header">
            <span>场景扰动数量-空间分布</span>
            <el-radio-group v-model="selectedSpaceType" size="small">
              <el-radio-button
                v-for="item in DISTURBANCE_TYPE_OPTIONS"
                :key="item.value"
                :label="item.value"
              >
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <ChartPanel :option="spaceOption" filename="scenario-space-distribution" height="340px" />
      </el-card>
    </el-col>
    <el-col :xs="24" :lg="10">
      <el-card shadow="never">
        <template #header>
          <FieldLabelTip
            label="扰动程度(时长)"
            tip="每个点代表一个扰动事件，纵轴为该事件持续时长；晚点使用延误秒数，限速 / 中断使用持续时间"
          />
        </template>
        <ChartPanel :option="disturbanceSeverityScatterOption" filename="scenario-disturbance-severity" height="340px" />
      </el-card>
    </el-col>
    <el-col :xs="24" :lg="8">
      <el-card shadow="never">
        <template #header>
          <FieldLabelTip
            label="场景类型占比"
            tip="场景类型包括纯中断 / 纯限速 / 纯晚点 / 混合"
          />
        </template>
        <ChartPanel :option="typePieOption" filename="scenario-type-ratio" height="260px" />
      </el-card>
    </el-col>
    <el-col :xs="24" :lg="8">
      <el-card shadow="never">
        <template #header>
          <FieldLabelTip
            label="扰动数量占比"
            tip="不论场景划分，统计全部扰动数量中晚点 / 限速 / 中断的占比"
          />
        </template>
        <ChartPanel :option="disturbanceRatioOption" filename="scenario-disturbance-ratio" height="260px" />
      </el-card>
    </el-col>
    <el-col :xs="24" :lg="8">
      <el-card shadow="never">
        <template #header>
          <FieldLabelTip
            label="扰动时长占比"
            tip="按扰动类型统计总时长占比；晚点使用延误秒数，限速 / 中断使用持续时间"
          />
        </template>
        <ChartPanel :option="disturbanceDurationRatioOption" filename="scenario-disturbance-duration-ratio" height="260px" />
      </el-card>
    </el-col>
    <el-col :xs="24">
      <el-card shadow="never">
        <template #header>当前运行图扰动数量-时间分布</template>
        <ChartPanel
          :option="selectedRunGraphTimeOption"
          filename="scenario-run-graph-time-distribution"
          height="260px"
        />
      </el-card>
    </el-col>
    <el-col :xs="24">
      <el-card shadow="never">
        <template #header>当前运行图扰动数量-空间分布</template>
        <RunGraphSpaceDistributionChart
          :disturbances="selectedRunGraphDisturbances"
          :station-order="runGraphTimetable?.station_order ?? []"
          :mileage-by-station="runGraphTimetable?.mileage_by_station ?? {}"
          filename="scenario-run-graph-space-distribution"
          height="300px"
        />
      </el-card>
    </el-col>
  </el-row>
</template>

<style scoped>
.scenario-chart-row {
  margin-top: 16px;
}

.scenario-chart-row :deep(.el-col) {
  margin-bottom: 16px;
}

.chart-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.chart-card-header :deep(.el-radio-group) {
  flex-shrink: 0;
}

.overview-run-graph-select {
  width: min(420px, 100%);
}

.overview-run-graph-chart {
  position: relative;
}

.run-graph-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.overview-run-graph-alert {
  margin-bottom: 12px;
}

@media (max-width: 720px) {
  .chart-card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .overview-run-graph-select {
    width: 100%;
  }

  .run-graph-option {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }
}
</style>
