<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { ElMessage } from 'element-plus'

import { api } from '@/api/client'
import type {
  DatasetSolveAnalysis,
  DatasetSolveErrorRow,
  DatasetSolveMetricSummary,
  DatasetSolveState,
  DatasetSummary,
  ScenarioCountRow,
  ScenarioMetricCard,
  ScenarioSet,
  ScenarioSetVisualization,
} from '@/types'

const props = defineProps<{
  page: 'ablation-scenarios' | 'ablation-datasets'
  selectedProjectId: string
  scenarioSets: ScenarioSet[]
  datasets: DatasetSummary[]
}>()

const baselineScenarioSetId = ref('')
const candidateScenarioSetIds = ref<string[]>([])
const scenarioSetVisualizations = ref<ScenarioSetVisualization[]>([])
const scenarioCompareLoading = ref(false)
const baselineDatasetId = ref('')
const candidateDatasetIds = ref<string[]>([])
const datasetSolveAnalysis = ref<DatasetSolveAnalysis | null>(null)
const datasetCompareLoading = ref(false)

const comparedDatasets = computed(() => {
  const selected = new Set([baselineDatasetId.value, ...candidateDatasetIds.value])
  return props.datasets.filter((item) => selected.has(item.dataset_id))
})
const pageTitle = computed(() =>
  props.page === 'ablation-scenarios' ? '场景集消融实验台' : '数据集消融实验台',
)
const scenarioItems = computed(() => scenarioSetVisualizations.value)
const baselineVisualization = computed(() =>
  scenarioItems.value.find((item) => item.scenario_set_id === baselineScenarioSetId.value) ??
  scenarioItems.value[0] ??
  null,
)
const candidateScenarioSets = computed(() =>
  props.scenarioSets.filter((item) => item.scenario_set_id !== baselineScenarioSetId.value),
)
const scenarioCategoryOption = computed(() => buildScenarioCategoryOption(scenarioItems.value))
const scenarioCoverageOption = computed(() => buildScenarioCoverageOption(scenarioItems.value))
const mathMetricOption = computed(() => buildMetricOption(scenarioItems.value, 'math_graph_metrics'))
const anchorCoverageOption = computed(() => buildAnchorCoverageOption(scenarioItems.value))
const combinationMetricOption = computed(() => buildMetricOption(scenarioItems.value, 'combination_complexity'))
const disturbanceCountOption = computed(() => buildDisturbanceCountOption(scenarioItems.value))
const typeTimeOption = computed(() => buildTypeTimeOption(scenarioItems.value))
const relationRows = computed(() => scenarioItems.value.flatMap((item) => relationTableRows(item)))
const parameterRows = computed(() => scenarioItems.value.flatMap((item) => parameterTableRows(item)))
const incompleteDatasetMessages = computed(() =>
  comparedDatasets.value.flatMap((item) => datasetQualityMessages(item)),
)
const candidateDatasets = computed(() =>
  props.datasets.filter((item) => item.dataset_id !== baselineDatasetId.value),
)
const datasetAnalysisItems = computed(() => datasetSolveAnalysis.value?.datasets ?? [])
const datasetSummaryRows = computed(() => datasetAnalysisItems.value.flatMap(datasetMetricTableRows))
const datasetErrorRows = computed(() => datasetSolveAnalysis.value?.comparison.rows ?? [])
const datasetErrorSummaryRows = computed(() => summarizeDatasetErrors(datasetErrorRows.value))
const datasetConfigRows = computed(() => datasetAnalysisItems.value.map(datasetConfigTableRow))
const datasetSolveMetricOption = computed(() => buildDatasetSolveMetricOption(datasetAnalysisItems.value))
const datasetSolveErrorOption = computed(() => buildDatasetSolveErrorOption(datasetErrorSummaryRows.value))
const datasetAnalysisWarnings = computed(() => [
  ...incompleteDatasetMessages.value,
  ...(datasetSolveAnalysis.value?.warnings.map((item) => item.message) ?? []),
])

watch(
  () => props.scenarioSets.map((item) => item.scenario_set_id).join('\u0000'),
  () => {
    const firstScenarioSetId = props.scenarioSets[0]?.scenario_set_id ?? ''
    if (!baselineScenarioSetId.value && firstScenarioSetId) {
      baselineScenarioSetId.value = firstScenarioSetId
    }
    if (!props.scenarioSets.some((item) => item.scenario_set_id === baselineScenarioSetId.value)) {
      baselineScenarioSetId.value = firstScenarioSetId
    }
    candidateScenarioSetIds.value = candidateScenarioSetIds.value.filter((scenarioSetId) =>
      props.scenarioSets.some((item) => item.scenario_set_id === scenarioSetId),
    )
  },
  { immediate: true },
)

watch(baselineScenarioSetId, () => {
  candidateScenarioSetIds.value = candidateScenarioSetIds.value.filter(
    (scenarioSetId) => scenarioSetId !== baselineScenarioSetId.value,
  )
})

watch(
  () => props.datasets.map((item) => item.dataset_id).join('\u0000'),
  () => {
    const firstDatasetId = props.datasets[0]?.dataset_id ?? ''
    if (!baselineDatasetId.value && firstDatasetId) {
      baselineDatasetId.value = firstDatasetId
    }
    if (!props.datasets.some((item) => item.dataset_id === baselineDatasetId.value)) {
      baselineDatasetId.value = firstDatasetId
    }
    candidateDatasetIds.value = candidateDatasetIds.value.filter((datasetId) =>
      props.datasets.some((item) => item.dataset_id === datasetId),
    )
  },
  { immediate: true },
)

watch(baselineDatasetId, () => {
  candidateDatasetIds.value = candidateDatasetIds.value.filter(
    (datasetId) => datasetId !== baselineDatasetId.value,
  )
})

async function compareScenarioSets() {
  if (!props.selectedProjectId || !baselineScenarioSetId.value) {
    ElMessage.warning('请选择基准场景集。')
    return
  }
  const scenarioSetIds = unique([baselineScenarioSetId.value, ...candidateScenarioSetIds.value])
  scenarioCompareLoading.value = true
  try {
    scenarioSetVisualizations.value = await Promise.all(
      scenarioSetIds.map((scenarioSetId) =>
        api.readScenarioSetVisualization(props.selectedProjectId, scenarioSetId),
      ),
    )
  } catch (error) {
    scenarioSetVisualizations.value = []
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    scenarioCompareLoading.value = false
  }
}

async function compareDatasets() {
  if (!props.selectedProjectId || !baselineDatasetId.value) {
    ElMessage.warning('请选择基准数据集。')
    return
  }
  const datasetIds = unique([baselineDatasetId.value, ...candidateDatasetIds.value])
  datasetCompareLoading.value = true
  try {
    datasetSolveAnalysis.value = await api.readDatasetSolveAnalysis(props.selectedProjectId, datasetIds)
  } catch (error) {
    datasetSolveAnalysis.value = null
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    datasetCompareLoading.value = false
  }
}

function buildScenarioCategoryOption(items: ScenarioSetVisualization[]) {
  const categories = unique(items.flatMap((item) => item.summary.category_ratios.map((row) => row.label)))
  const labels = items.map(scenarioSetLabel)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, type: 'scroll' },
    grid: { top: 48, right: 18, bottom: 54, left: 48 },
    xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 3 ? 24 : 0 } },
    yAxis: { type: 'value', name: '场景数' },
    series: categories.map((category) => ({
      name: category,
      type: 'bar',
      stack: 'category',
      data: items.map((item) => categoryCount(item, category)),
    })),
  }
}

function buildScenarioCoverageOption(items: ScenarioSetVisualization[]) {
  const labels = items.map(scenarioSetLabel)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => `${(Number(value) * 100).toFixed(1)}%`,
    },
    legend: { top: 0 },
    grid: { top: 48, right: 18, bottom: 54, left: 48 },
    xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 3 ? 24 : 0 } },
    yAxis: {
      type: 'value',
      name: '覆盖率',
      max: 1,
      axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%` },
    },
    series: [
      {
        name: '时间覆盖率',
        type: 'bar',
        data: items.map((item) => coverageValue(item, 'time_ratio')),
      },
      {
        name: '空间覆盖率',
        type: 'bar',
        data: items.map((item) => coverageValue(item, 'space_ratio')),
      },
    ],
  }
}

function buildMetricOption(
  items: ScenarioSetVisualization[],
  group: 'math_graph_metrics' | 'combination_complexity',
) {
  const cards = unique(items.flatMap((item) => item.summary[group].cards.map((card) => card.label)))
  const labels = items.map(scenarioSetLabel)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => formatChartNumber(Number(value)),
    },
    legend: { top: 0, type: 'scroll' },
    grid: { top: 48, right: 18, bottom: 58, left: 56 },
    xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 3 ? 24 : 0 } },
    yAxis: { type: 'value' },
    series: cards.map((label) => ({
      name: label,
      type: 'bar',
      data: items.map((item) => metricValue(item.summary[group].cards, label)),
    })),
  }
}

function buildAnchorCoverageOption(items: ScenarioSetVisualization[]) {
  const labels = items.map(scenarioSetLabel)
  const anchorLabels = unique(
    items.flatMap((item) => item.summary.math_graph_metrics.anchor_coverage.map((row) => row.label)),
  )
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => `${(Number(value) * 100).toFixed(1)}%`,
    },
    legend: { top: 0 },
    grid: { top: 48, right: 18, bottom: 54, left: 56 },
    xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 3 ? 24 : 0 } },
    yAxis: {
      type: 'value',
      name: '覆盖率',
      max: 1,
      axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%` },
    },
    series: anchorLabels.map((label) => ({
      name: label,
      type: 'bar',
      data: items.map((item) => {
        return item.summary.math_graph_metrics.anchor_coverage.find((row) => row.label === label)?.ratio ?? 0
      }),
    })),
  }
}

function buildDisturbanceCountOption(items: ScenarioSetVisualization[]) {
  const labels = unique(
    items.flatMap((item) => item.summary.combination_complexity.count_distribution.map((row) => row.label)),
  )
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, type: 'scroll' },
    grid: { top: 48, right: 18, bottom: 46, left: 48 },
    xAxis: { type: 'category', name: '单场景扰动数', data: labels },
    yAxis: { type: 'value', name: '场景数' },
    series: items.map((item) => ({
      name: scenarioSetLabel(item),
      type: 'bar',
      data: labels.map((label) => {
        return item.summary.combination_complexity.count_distribution.find((row) => row.label === label)?.count ?? 0
      }),
    })),
  }
}

function buildTypeTimeOption(items: ScenarioSetVisualization[]) {
  const bins = unique(items.flatMap((item) => item.summary.joint_structure.time_bins))
  const seriesKeys = unique(
    items.flatMap((item) =>
      item.summary.joint_structure.type_time.map((row) => `${scenarioSetLabel(item)} · ${row.type_label}`),
    ),
  )
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, type: 'scroll' },
    grid: { top: 72, right: 18, bottom: 46, left: 48 },
    xAxis: { type: 'category', data: bins },
    yAxis: { type: 'value', name: '扰动数' },
    series: seriesKeys.map((key) => {
      const [label, typeLabel] = key.split(' · ')
      const item = items.find((candidate) => scenarioSetLabel(candidate) === label)
      return {
        name: key,
        type: 'line',
        smooth: true,
        data: bins.map((bin) => {
          return (
            item?.summary.joint_structure.type_time.find(
              (row) => row.type_label === typeLabel && row.time_bin === bin,
            )?.count ?? 0
          )
        }),
      }
    }),
  }
}

function buildDatasetSolveMetricOption(items: DatasetSolveState[]) {
  const labels = items.map(datasetLabel)
  const metrics = unique(items.flatMap((item) => item.summary_metrics.map((row) => row.label)))
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => formatChartNumber(Number(value)),
    },
    legend: { top: 0, type: 'scroll' },
    grid: { top: 54, right: 18, bottom: 58, left: 56 },
    xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 3 ? 24 : 0 } },
    yAxis: { type: 'value', name: '均值' },
    series: metrics.map((metric) => ({
      name: metric,
      type: 'bar',
      data: items.map((item) => metricSummaryValue(item.summary_metrics, metric, 'mean')),
    })),
  }
}

function buildDatasetSolveErrorOption(rows: ReturnType<typeof summarizeDatasetErrors>) {
  const labels = unique(rows.map((row) => row.dataset_id))
  const metrics = unique(rows.map((row) => row.metric_label))
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => formatChartNumber(Number(value)),
    },
    legend: { top: 0, type: 'scroll' },
    grid: { top: 54, right: 18, bottom: 58, left: 56 },
    xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 3 ? 24 : 0 } },
    yAxis: { type: 'value', name: '平均相对误差' },
    series: metrics.map((metric) => ({
      name: metric,
      type: 'bar',
      data: labels.map((datasetId) => {
        return rows.find((row) => row.dataset_id === datasetId && row.metric_label === metric)?.mean_relative_error ?? 0
      }),
    })),
  }
}

function categoryCount(item: ScenarioSetVisualization, label: string) {
  return item.summary.category_ratios.find((row) => row.label === label)?.count ?? 0
}

function coverageValue(item: ScenarioSetVisualization, key: 'time_ratio' | 'space_ratio') {
  return item.summary.coverage.rows.find((row) => row.type === 'all')?.[key] ?? 0
}

function unique(values: string[]) {
  return [...new Set(values)]
}

function scenarioSetLabel(item: ScenarioSetVisualization) {
  return item.scenario_set_id === baselineScenarioSetId.value
    ? `基准: ${item.scenario_set_id}`
    : item.scenario_set_id
}

function datasetLabel(item: DatasetSolveState) {
  return item.dataset_id === baselineDatasetId.value ? `基准: ${item.dataset_id}` : item.dataset_id
}

function metricValue(cards: ScenarioMetricCard[], label: string) {
  return cards.find((card) => card.label === label)?.value ?? 0
}

function relationTableRows(item: ScenarioSetVisualization) {
  return item.summary.math_graph_metrics.relation_counts.map((row) => ({
    scenario_set_id: scenarioSetLabel(item),
    relation: row.label,
    count: row.count,
  }))
}

function parameterTableRows(item: ScenarioSetVisualization) {
  return item.summary.math_graph_metrics.parameter_stats.map((row) => ({
    scenario_set_id: scenarioSetLabel(item),
    metric: row.label,
    count: row.count,
    mean: row.mean,
    min: row.min,
    max: row.max,
    unit: row.unit,
  }))
}

function datasetMetricTableRows(item: DatasetSolveState) {
  return item.summary_metrics.map((row) => ({
    dataset_id: datasetLabel(item),
    metric: row.label,
    count: row.count,
    mean: row.mean,
    min: row.min,
    max: row.max,
  }))
}

function datasetConfigTableRow(item: DatasetSolveState) {
  return {
    dataset_id: datasetLabel(item),
    case_count: item.case_count,
    solved_count: item.solved_count,
    config_known_count: item.config_known_count,
    config_consistent: item.config_consistent,
    time_limit: item.solver_config.time_limit,
    mip_gap: item.solver_config.mip_gap,
    threads: item.solver_config.threads,
  }
}

function summarizeDatasetErrors(rows: DatasetSolveErrorRow[]) {
  const groups = new Map<string, DatasetSolveErrorRow[]>()
  for (const row of rows) {
    const key = `${row.dataset_id}\u0000${row.metric}`
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  return [...groups.values()].map((items) => {
    const first = items[0]!
    const relativeValues = items
      .map((item) => item.relative_error)
      .filter((value): value is number => value !== null && Number.isFinite(value))
    return {
      dataset_id: first.dataset_id,
      metric: first.metric,
      metric_label: first.metric_label,
      count: items.length,
      mean_absolute_error: meanNumber(items.map((item) => item.absolute_error)),
      mean_relative_error: meanNumber(relativeValues),
    }
  })
}

function metricSummaryValue(
  rows: DatasetSolveMetricSummary[],
  label: string,
  key: 'mean' | 'min' | 'max',
) {
  return rows.find((row) => row.label === label)?.[key] ?? 0
}

function formatMetric(card: ScenarioMetricCard) {
  if (card.value_type === 'percent') return `${(Number(card.value) * 100).toFixed(1)}%`
  return formatChartNumber(Number(card.value))
}

function formatChartNumber(value: number) {
  if (!Number.isFinite(value)) return '-'
  if (Math.abs(value) >= 100) return value.toFixed(0)
  if (Math.abs(value) >= 10) return value.toFixed(1)
  return value.toFixed(2)
}

function formatOptionalNumber(value: number | null) {
  return value === null ? '-' : formatChartNumber(value)
}

function formatOptionalPercent(value: number | null) {
  return value === null ? '-' : `${(value * 100).toFixed(2)}%`
}

function meanNumber(values: number[]) {
  const items = values.filter((value) => Number.isFinite(value))
  return items.length ? items.reduce((total, value) => total + value, 0) / items.length : 0
}

function datasetQualityMessages(item: DatasetSummary) {
  if (item.case_count <= 0) return [`${item.dataset_id} 尚未构建实例。`]
  const messages: string[] = []
  if (!item.is_fully_built) {
    messages.push(`${item.dataset_id} 构建不完整：${item.built_count}/${item.case_count}。`)
  }
  if (!item.is_fully_solved) {
    messages.push(`${item.dataset_id} 求解不完整：${item.solved_count}/${item.case_count}。`)
  }
  if (!item.is_timetable_ready) {
    messages.push(`${item.dataset_id} 时刻表导出不完整：${item.timetable_count}/${item.case_count}。`)
  }
  return messages
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>{{ pageTitle }}</span>
          </div>
        </template>

        <template v-if="page === 'ablation-scenarios'">
          <div class="toolbar-row analysis-toolbar">
            <div class="inline-control">
              <span>基准场景集：</span>
              <el-select
                v-model="baselineScenarioSetId"
                filterable
                class="analysis-select"
                placeholder="选择基准"
              >
                <el-option
                  v-for="item in scenarioSets"
                  :key="item.scenario_set_id"
                  :label="item.scenario_set_id"
                  :value="item.scenario_set_id"
                />
              </el-select>
            </div>
            <div class="inline-control">
              <span>对比场景集：</span>
              <el-select
                v-model="candidateScenarioSetIds"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                class="analysis-select"
                placeholder="选择对比集"
              >
                <el-option
                  v-for="item in candidateScenarioSets"
                  :key="item.scenario_set_id"
                  :label="item.scenario_set_id"
                  :value="item.scenario_set_id"
                />
              </el-select>
            </div>
            <el-button type="primary" :loading="scenarioCompareLoading" @click="compareScenarioSets">
              开始对比
            </el-button>
          </div>

          <el-row class="analysis-section" :gutter="16">
            <el-col :span="8">
              <el-card shadow="never">
                <el-statistic title="基准场景集" :value="baselineScenarioSetId || '-'" />
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="never">
                <el-statistic title="对比场景集" :value="candidateScenarioSetIds.length" />
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="never">
                <el-statistic
                  title="已加载场景总数"
                  :value="
                    scenarioItems.reduce(
                      (total, item) => total + item.summary.scenario_count,
                      0,
                    )
                  "
                />
              </el-card>
            </el-col>
          </el-row>

          <template v-if="scenarioItems.length">
            <div class="analysis-grid">
              <el-card shadow="never">
                <template #header>场景类型组成</template>
                <VChart :option="scenarioCategoryOption" autoresize class="analysis-chart" />
              </el-card>
              <el-card shadow="never">
                <template #header>扰动覆盖率</template>
                <VChart :option="scenarioCoverageOption" autoresize class="analysis-chart" />
              </el-card>
            </div>

            <el-card class="analysis-section" shadow="never">
              <template #header>
                <div class="card-header">
                  <span>数学图指标</span>
                  <el-tag v-if="baselineVisualization" type="info" effect="plain">
                    基准：{{ baselineVisualization.scenario_set_id }}
                  </el-tag>
                </div>
              </template>
              <div class="metric-card-grid">
                <el-card
                  v-for="card in baselineVisualization?.summary.math_graph_metrics.cards ?? []"
                  :key="card.key"
                  shadow="never"
                  class="metric-card"
                >
                  <div class="metric-label">{{ card.label }}</div>
                  <div class="metric-value">{{ formatMetric(card) }}</div>
                </el-card>
              </div>
              <div class="analysis-grid compact-grid">
                <el-card shadow="never">
                  <template #header>图规模 / 关系指标对比</template>
                  <VChart :option="mathMetricOption" autoresize class="analysis-chart" />
                </el-card>
                <el-card shadow="never">
                  <template #header>锚点覆盖</template>
                  <VChart :option="anchorCoverageOption" autoresize class="analysis-chart" />
                </el-card>
              </div>
              <div class="analysis-grid compact-grid">
                <el-card shadow="never">
                  <template #header>扰动参数统计</template>
                  <el-table :data="parameterRows" height="320" empty-text="暂无参数统计">
                    <el-table-column prop="scenario_set_id" label="场景集" min-width="150" show-overflow-tooltip />
                    <el-table-column prop="metric" label="指标" min-width="130" />
                    <el-table-column prop="count" label="样本数" width="90" />
                    <el-table-column label="均值" width="100">
                      <template #default="{ row }">{{ formatOptionalNumber(row.mean) }}</template>
                    </el-table-column>
                    <el-table-column label="最小" width="100">
                      <template #default="{ row }">{{ formatOptionalNumber(row.min) }}</template>
                    </el-table-column>
                    <el-table-column label="最大" width="100">
                      <template #default="{ row }">{{ formatOptionalNumber(row.max) }}</template>
                    </el-table-column>
                    <el-table-column prop="unit" label="单位" width="80" />
                  </el-table>
                </el-card>
                <el-card shadow="never">
                  <template #header>辅助关系类型</template>
                  <el-table :data="relationRows" height="320" empty-text="暂无关系统计">
                    <el-table-column prop="scenario_set_id" label="场景集" min-width="150" show-overflow-tooltip />
                    <el-table-column prop="relation" label="关系类型" min-width="120" />
                    <el-table-column prop="count" label="数量" width="100" />
                  </el-table>
                </el-card>
              </div>
            </el-card>

            <el-card class="analysis-section" shadow="never">
              <template #header>组合复杂度指标</template>
              <div class="analysis-grid compact-grid">
                <el-card shadow="never">
                  <template #header>复杂度摘要</template>
                  <VChart :option="combinationMetricOption" autoresize class="analysis-chart" />
                </el-card>
                <el-card shadow="never">
                  <template #header>单场景扰动数分布</template>
                  <VChart :option="disturbanceCountOption" autoresize class="analysis-chart" />
                </el-card>
              </div>
            </el-card>

            <el-card class="analysis-section" shadow="never">
              <template #header>时空联合结构</template>
              <VChart :option="typeTimeOption" autoresize class="analysis-chart wide-chart" />
            </el-card>
          </template>
          <el-empty v-else class="analysis-section" description="请选择基准和对比场景集并开始对比" />
        </template>

        <template v-else>
          <div class="toolbar-row analysis-toolbar">
            <div class="inline-control">
              <span>基准数据集：</span>
              <el-select
                v-model="baselineDatasetId"
                filterable
                class="analysis-select"
                placeholder="选择基准"
              >
                <el-option
                  v-for="item in datasets"
                  :key="item.dataset_id"
                  :label="item.dataset_id"
                  :value="item.dataset_id"
                />
              </el-select>
            </div>
            <div class="inline-control">
              <span>对比数据集：</span>
              <el-select
                v-model="candidateDatasetIds"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                class="analysis-select"
                placeholder="选择对比集"
              >
                <el-option
                  v-for="item in candidateDatasets"
                  :key="item.dataset_id"
                  :label="item.dataset_id"
                  :value="item.dataset_id"
                />
              </el-select>
            </div>
            <el-button type="primary" :loading="datasetCompareLoading" @click="compareDatasets">
              开始对比
            </el-button>
          </div>

          <el-row class="analysis-section" :gutter="16">
            <el-col :span="8">
              <el-card shadow="never">
                <el-statistic title="基准数据集" :value="baselineDatasetId || '-'" />
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="never">
                <el-statistic title="对比数据集" :value="candidateDatasetIds.length" />
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="never">
                <el-statistic
                  title="已加载实例数"
                  :value="datasetAnalysisItems.reduce((total, item) => total + item.case_count, 0)"
                />
              </el-card>
            </el-col>
          </el-row>

          <template v-if="datasetSolveAnalysis">
            <el-alert
              v-if="datasetAnalysisWarnings.length"
              class="analysis-section"
              title="检测到数据不完整或求解器配置不一致，数据分析可能不准确"
              type="warning"
              show-icon
              :closable="false"
              :description="datasetAnalysisWarnings.join(' ')"
            />

            <el-card class="analysis-section" shadow="never">
              <template #header>求解器配置</template>
              <el-table :data="datasetConfigRows" empty-text="暂无配置数据">
                <el-table-column prop="dataset_id" label="数据集" min-width="160" show-overflow-tooltip />
                <el-table-column prop="case_count" label="实例数" width="90" />
                <el-table-column prop="solved_count" label="已求解" width="90" />
                <el-table-column prop="config_known_count" label="配置记录" width="100" />
                <el-table-column label="配置一致" width="100">
                  <template #default="{ row }">
                    <el-tag :type="row.config_consistent ? 'success' : 'warning'" size="small">
                      {{ row.config_consistent ? '一致' : '不一致' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="Time Limit" width="110">
                  <template #default="{ row }">{{ formatOptionalNumber(row.time_limit ?? null) }}</template>
                </el-table-column>
                <el-table-column label="MIP Gap" width="110">
                  <template #default="{ row }">{{ formatOptionalNumber(row.mip_gap ?? null) }}</template>
                </el-table-column>
                <el-table-column label="Threads" width="100">
                  <template #default="{ row }">{{ row.threads ?? '-' }}</template>
                </el-table-column>
              </el-table>
            </el-card>

            <div class="analysis-grid">
              <el-card shadow="never">
                <template #header>求解行为数值对比</template>
                <VChart :option="datasetSolveMetricOption" autoresize class="analysis-chart" />
              </el-card>
              <el-card shadow="never">
                <template #header>相对基准误差对比</template>
                <VChart :option="datasetSolveErrorOption" autoresize class="analysis-chart" />
              </el-card>
            </div>

            <div class="analysis-grid">
              <el-card shadow="never">
                <template #header>直接数值表</template>
                <el-table :data="datasetSummaryRows" height="360" empty-text="暂无求解行为数据">
                  <el-table-column prop="dataset_id" label="数据集" min-width="160" show-overflow-tooltip />
                  <el-table-column prop="metric" label="指标" min-width="120" />
                  <el-table-column prop="count" label="样本数" width="90" />
                  <el-table-column label="均值" width="110">
                    <template #default="{ row }">{{ formatOptionalNumber(row.mean) }}</template>
                  </el-table-column>
                  <el-table-column label="最小" width="110">
                    <template #default="{ row }">{{ formatOptionalNumber(row.min) }}</template>
                  </el-table-column>
                  <el-table-column label="最大" width="110">
                    <template #default="{ row }">{{ formatOptionalNumber(row.max) }}</template>
                  </el-table-column>
                </el-table>
              </el-card>
              <el-card shadow="never">
                <template #header>误差汇总表</template>
                <el-table :data="datasetErrorSummaryRows" height="360" empty-text="暂无可对齐的误差数据">
                  <el-table-column prop="dataset_id" label="对比数据集" min-width="160" show-overflow-tooltip />
                  <el-table-column prop="metric_label" label="指标" min-width="120" />
                  <el-table-column prop="count" label="对齐实例" width="100" />
                  <el-table-column label="平均绝对误差" width="140">
                    <template #default="{ row }">{{ formatOptionalNumber(row.mean_absolute_error) }}</template>
                  </el-table-column>
                  <el-table-column label="平均相对误差" width="140">
                    <template #default="{ row }">{{ formatOptionalPercent(row.mean_relative_error) }}</template>
                  </el-table-column>
                </el-table>
              </el-card>
            </div>
          </template>
          <el-empty v-else class="analysis-section" description="请选择基准和对比数据集并开始对比" />
        </template>
      </el-card>
    </div>
  </section>
</template>

<style scoped>
.analysis-select {
  width: 420px;
}

.analysis-toolbar {
  flex-wrap: wrap;
  gap: 12px;
}

.analysis-section {
  margin-top: 16px;
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.analysis-wide {
  grid-column: 1 / -1;
}

.compact-grid {
  margin-top: 12px;
}

.analysis-chart {
  display: block;
  width: 100%;
  height: 320px;
}

.wide-chart {
  height: 380px;
}

.metric-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.metric-card {
  background: var(--el-fill-color-lighter);
}

.metric-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.metric-value {
  margin-top: 8px;
  color: var(--el-text-color-primary);
  font-size: 24px;
  font-weight: 700;
}

@media (max-width: 1100px) {
  .analysis-grid {
    grid-template-columns: 1fr;
  }

  .analysis-select {
    width: 100%;
  }
}
</style>
