<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api } from '@/api/client'
import { barPercentLabel, barValueLabel } from '@/chart-options'
import ChartPanel from '@/components/ChartPanel.vue'
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
  ResourceOption,
} from '@/types'

type ScenarioAnalysisMode = 'absolute' | 'relative'

const props = defineProps<{
  page: 'ablation-scenarios' | 'ablation-datasets'
  selectedProjectId: string
  scenarioSets: ScenarioSet[]
  datasets: DatasetSummary[]
  busy?: boolean
}>()

const baselineScenarioSetId = ref('')
const candidateScenarioSetIds = ref<string[]>([])
const scenarioSetVisualizations = ref<ScenarioSetVisualization[]>([])
const scenarioCompareLoading = ref(false)
const scenarioAnalysisMode = ref<ScenarioAnalysisMode>('relative')
const baselineDatasetId = ref('')
const candidateDatasetIds = ref<string[]>([])
const datasetSolveAnalysis = ref<DatasetSolveAnalysis | null>(null)
const datasetCompareLoading = ref(false)
const datasetAnalysisMode = ref<ScenarioAnalysisMode>('relative')
const scenarioSetOptions = ref<ResourceOption[]>([])
const scenarioSetOptionsLoading = ref(false)
const datasetOptions = ref<ResourceOption[]>([])
const datasetOptionsLoading = ref(false)
let scenarioSetOptionRequestSeq = 0
let datasetOptionRequestSeq = 0
const scenarioBusy = computed(() => Boolean(props.busy || scenarioCompareLoading.value))
const datasetBusy = computed(() => Boolean(props.busy || datasetCompareLoading.value))

const comparedDatasets = computed(() => {
  const selected = new Set([baselineDatasetId.value, ...candidateDatasetIds.value])
  return props.datasets.filter((item) => selected.has(item.dataset_id))
})
const scenarioItems = computed(() => scenarioSetVisualizations.value)
const baselineVisualization = computed(() =>
  scenarioItems.value.find((item) => item.scenario_set_id === baselineScenarioSetId.value) ??
  scenarioItems.value[0] ??
  null,
)
const scenarioSetSelectOptions = computed(() =>
  mergeSelectedOptions(scenarioSetOptions.value, [
    { value: baselineScenarioSetId.value, label: baselineScenarioSetId.value },
    ...candidateScenarioSetIds.value.map((value) => ({ value, label: value })),
  ]),
)
const candidateScenarioSetOptions = computed(() =>
  scenarioSetSelectOptions.value.filter((item) => item.value !== baselineScenarioSetId.value),
)
const scenarioCategoryOption = computed(() =>
  buildScenarioCategoryOption(scenarioItems.value, scenarioAnalysisMode.value),
)
const scenarioCoverageOption = computed(() =>
  buildScenarioCoverageOption(scenarioItems.value, scenarioAnalysisMode.value),
)
const mathMetricOption = computed(() =>
  buildMetricByMetricOption(scenarioItems.value, 'math_graph_metrics', scenarioAnalysisMode.value),
)
const anchorCoverageOption = computed(() =>
  buildAnchorCoverageOption(scenarioItems.value, scenarioAnalysisMode.value),
)
const combinationMetricOption = computed(() =>
  buildMetricByMetricOption(scenarioItems.value, 'combination_complexity', scenarioAnalysisMode.value),
)
const disturbanceCountOption = computed(() =>
  buildDisturbanceCountOption(scenarioItems.value, scenarioAnalysisMode.value),
)
const typeTimeSetFilter = ref<string[]>([])
const typeTimeTypeFilter = ref<string[]>([])
const ALL_TYPE_FILTER = '__all__'
const ALL_TYPE_LABEL = '全部'
const LEGEND_NAME_LIMIT = 16
const AXIS_LABEL_LIMIT = 12
const typeTimeSetOptions = computed(() => scenarioItems.value.map((item) => scenarioSetLabel(item)))
const typeTimeTypeOptions = computed(() =>
  [
    ALL_TYPE_LABEL,
    ...unique(scenarioItems.value.flatMap((item) => item.summary.joint_structure.type_time.map((row) => row.type_label))),
  ],
)
const typeTimeOption = computed(() =>
  buildTypeTimeOption(
    scenarioItems.value,
    typeTimeSetFilter.value,
    typeTimeTypeFilter.value,
    scenarioAnalysisMode.value,
  ),
)
const typeLocationOption = computed(() =>
  buildTypeLocationOption(
    scenarioItems.value,
    typeTimeSetFilter.value,
    typeTimeTypeFilter.value,
    scenarioAnalysisMode.value,
  ),
)
const relationRows = computed(() => scenarioItems.value.flatMap((item) => relationTableRows(item)))
const parameterRows = computed(() => scenarioItems.value.flatMap((item) => parameterTableRows(item)))
const incompleteDatasetMessages = computed(() =>
  comparedDatasets.value.flatMap((item) => datasetQualityMessages(item)),
)
const datasetSelectOptions = computed(() =>
  mergeSelectedOptions(datasetOptions.value, [
    { value: baselineDatasetId.value, label: baselineDatasetId.value },
    ...candidateDatasetIds.value.map((value) => ({ value, label: value })),
  ]),
)
const candidateDatasetOptions = computed(() =>
  datasetSelectOptions.value.filter((item) => item.value !== baselineDatasetId.value),
)
const datasetAnalysisItems = computed(() => datasetSolveAnalysis.value?.datasets ?? [])
const datasetSummaryRows = computed(() => datasetAnalysisItems.value.flatMap(datasetMetricTableRows))
const datasetErrorRows = computed(() => datasetSolveAnalysis.value?.comparison.rows ?? [])
const datasetErrorSummaryRows = computed(() => summarizeDatasetErrors(datasetErrorRows.value))
const datasetConfigRows = computed(() => datasetAnalysisItems.value.map(datasetConfigTableRow))
const datasetSolveChartOption = computed(() =>
  datasetAnalysisMode.value === 'absolute'
    ? buildDatasetSolveMetricOption(datasetAnalysisItems.value)
    : buildDatasetSolveErrorOption(datasetErrorSummaryRows.value),
)
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

async function loadScenarioSetOptions(query = '') {
  if (!props.selectedProjectId) {
    scenarioSetOptions.value = []
    return
  }
  const requestSeq = scenarioSetOptionRequestSeq + 1
  scenarioSetOptionRequestSeq = requestSeq
  scenarioSetOptionsLoading.value = true
  try {
    const options = await api.listResourceOptions(props.selectedProjectId, 'scenario_sets', query)
    if (requestSeq === scenarioSetOptionRequestSeq) scenarioSetOptions.value = options
  } catch (error) {
    if (requestSeq === scenarioSetOptionRequestSeq) {
      scenarioSetOptions.value = []
      ElMessage.error(error instanceof Error ? error.message : String(error))
    }
  } finally {
    if (requestSeq === scenarioSetOptionRequestSeq) scenarioSetOptionsLoading.value = false
  }
}

async function loadDatasetOptions(query = '') {
  if (!props.selectedProjectId) {
    datasetOptions.value = []
    return
  }
  const requestSeq = datasetOptionRequestSeq + 1
  datasetOptionRequestSeq = requestSeq
  datasetOptionsLoading.value = true
  try {
    const options = await api.listResourceOptions(props.selectedProjectId, 'datasets', query)
    if (requestSeq === datasetOptionRequestSeq) datasetOptions.value = options
  } catch (error) {
    if (requestSeq === datasetOptionRequestSeq) {
      datasetOptions.value = []
      ElMessage.error(error instanceof Error ? error.message : String(error))
    }
  } finally {
    if (requestSeq === datasetOptionRequestSeq) datasetOptionsLoading.value = false
  }
}

function reloadScenarioSetOptionsOnOpen(visible: boolean) {
  if (visible) void loadScenarioSetOptions('')
}

function reloadDatasetOptionsOnOpen(visible: boolean) {
  if (visible) void loadDatasetOptions('')
}

function mergeSelectedOptions(options: ResourceOption[], selected: ResourceOption[]) {
  const result = [...options]
  for (const item of selected) {
    if (item.value && !result.some((option) => option.value === item.value)) {
      result.unshift(item)
    }
  }
  return result
}

async function compareScenarioSets() {
  if (scenarioBusy.value) return
  if (!props.selectedProjectId || !baselineScenarioSetId.value) {
    ElMessage.warning('请选择基准场景分类。')
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
    resetTypeTimeFilters()
  } catch (error) {
    scenarioSetVisualizations.value = []
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    scenarioCompareLoading.value = false
  }
}

function resetTypeTimeFilters() {
  typeTimeSetFilter.value = typeTimeSetOptions.value
  typeTimeTypeFilter.value = [ALL_TYPE_LABEL]
}

async function compareDatasets() {
  if (datasetBusy.value) return
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

function buildScenarioCategoryOption(items: ScenarioSetVisualization[], mode: ScenarioAnalysisMode) {
  const categories = unique(items.flatMap((item) => item.summary.category_ratios.map((row) => row.label)))
  const baseline = baselineScenarioItem(items)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: valueFormatterForMode(mode),
    },
    legend: legendConfig({ top: 0, type: 'scroll' }),
    grid: { top: 62, right: 18, bottom: 54, left: 48 },
    xAxis: categoryAxis(categories, { rotate: categories.length > 4 ? 24 : 0 }),
    yAxis: valueAxis('场景数', mode),
    series: items.map((item) => ({
      name: scenarioSetLabel(item),
      type: 'bar',
      label: barValueLabel(),
      data: categories.map((category) =>
        modeValue(
          categoryCount(item, category),
          baseline ? categoryCount(baseline, category) : 0,
          mode,
        ),
      ),
    })),
  }
}

function buildScenarioCoverageOption(items: ScenarioSetVisualization[], mode: ScenarioAnalysisMode) {
  const metrics = [
    { label: '时间覆盖率', key: 'time_ratio' as const },
    { label: '空间覆盖率', key: 'space_ratio' as const },
  ]
  const baseline = baselineScenarioItem(items)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: percentFormatterForMode(mode),
    },
    legend: legendConfig({ top: 0 }),
    grid: { top: 62, right: 18, bottom: 54, left: 48 },
    xAxis: categoryAxis(metrics.map((item) => item.label)),
    yAxis: mode === 'absolute' ? percentAxis('覆盖率') : valueAxis('相对基准', mode),
    series: items.map((item) => ({
      name: scenarioSetLabel(item),
      type: 'bar',
      label: mode === 'absolute' ? barPercentLabel() : barValueLabel(),
      data: metrics.map((metric) =>
        modeValue(
          coverageValue(item, metric.key),
          baseline ? coverageValue(baseline, metric.key) : 0,
          mode,
        ),
      ),
    })),
  }
}

function buildMetricByMetricOption(
  items: ScenarioSetVisualization[],
  group: 'math_graph_metrics' | 'combination_complexity',
  mode: ScenarioAnalysisMode,
) {
  const metrics = unique(items.flatMap((item) => item.summary[group].cards.map((card) => card.label)))
  const baseline = baselineScenarioItem(items)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: valueFormatterForMode(mode),
    },
    legend: legendConfig({ top: 0, type: 'scroll' }),
    grid: { top: 62, right: 18, bottom: 72, left: 56 },
    xAxis: categoryAxis(metrics, { rotate: metrics.length > 4 ? 24 : 0 }),
    yAxis: valueAxis('', mode),
    series: items.map((item) => ({
      name: scenarioSetLabel(item),
      type: 'bar',
      label: barValueLabel(),
      data: metrics.map((metric) =>
        modeValue(
          metricValue(item.summary[group].cards, metric),
          baseline ? metricValue(baseline.summary[group].cards, metric) : 0,
          mode,
        ),
      ),
    })),
  }
}

function buildAnchorCoverageOption(items: ScenarioSetVisualization[], mode: ScenarioAnalysisMode) {
  const labels = items.map(scenarioSetLabel)
  const anchorLabels = unique(
    items.flatMap((item) => item.summary.math_graph_metrics.anchor_coverage.map((row) => row.label)),
  )
  const baseline = baselineScenarioItem(items)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: percentFormatterForMode(mode),
    },
    legend: legendConfig({ top: 0 }),
    grid: { top: 62, right: 18, bottom: 54, left: 56 },
    xAxis: categoryAxis(labels, { rotate: labels.length > 3 ? 24 : 0 }),
    yAxis: mode === 'absolute' ? percentAxis('覆盖率') : valueAxis('相对基准', mode),
    series: anchorLabels.map((label) => ({
      name: label,
      type: 'bar',
      label: mode === 'absolute' ? barPercentLabel() : barValueLabel(),
      data: items.map((item) => {
        const value = item.summary.math_graph_metrics.anchor_coverage.find((row) => row.label === label)?.ratio ?? 0
        const baselineValue =
          baseline?.summary.math_graph_metrics.anchor_coverage.find((row) => row.label === label)?.ratio ?? 0
        return modeValue(value, baselineValue, mode)
      }),
    })),
  }
}

function buildDisturbanceCountOption(items: ScenarioSetVisualization[], mode: ScenarioAnalysisMode) {
  const labels = unique(
    items.flatMap((item) => item.summary.combination_complexity.count_distribution.map((row) => row.label)),
  )
  const baseline = baselineScenarioItem(items)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: valueFormatterForMode(mode),
    },
    legend: legendConfig({ top: 0, type: 'scroll' }),
    grid: { top: 62, right: 18, bottom: 46, left: 48 },
    xAxis: categoryAxis(labels, { name: '单场景扰动数' }),
    yAxis: valueAxis('场景数', mode),
    series: items.map((item) => ({
      name: scenarioSetLabel(item),
      type: 'bar',
      label: barValueLabel(),
      data: labels.map((label) => {
        const value = disturbanceCountValue(item, label)
        return modeValue(value, baseline ? disturbanceCountValue(baseline, label) : 0, mode)
      }),
    })),
  }
}

function buildTypeTimeOption(
  items: ScenarioSetVisualization[],
  selectedSets: string[],
  selectedTypes: string[],
  mode: ScenarioAnalysisMode,
) {
  const bins = unique(items.flatMap((item) => item.summary.joint_structure.time_bins))
  const setFilter = selectedSets.length ? new Set(selectedSets) : new Set(items.map((item) => scenarioSetLabel(item)))
  const aggregateTypes = selectedTypes.includes(ALL_TYPE_LABEL)
  const typeFilter = !aggregateTypes && selectedTypes.length
    ? new Set(selectedTypes)
    : new Set(items.flatMap((item) => item.summary.joint_structure.type_time.map((row) => row.type_label)))
  const baseline = baselineScenarioItem(items)
  const seriesKeys = aggregateTypes
    ? items.filter((item) => setFilter.has(scenarioSetLabel(item))).map(scenarioSetLabel)
    : unique(
        items.flatMap((item) =>
          item.summary.joint_structure.type_time
            .filter((row) => setFilter.has(scenarioSetLabel(item)) && typeFilter.has(row.type_label))
            .map((row) => `${scenarioSetLabel(item)} · ${row.type_label}`),
        ),
      )
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: valueFormatterForMode(mode),
    },
    legend: legendConfig({ top: 0, selectedMode: false }),
    grid: { top: 92, right: 18, bottom: 46, left: 48 },
    xAxis: categoryAxis(bins),
    yAxis: valueAxis('扰动数', mode),
    series: seriesKeys.map((key) => {
      const { label, typeLabel } = parseTypeSeriesKey(key, aggregateTypes)
      const item = items.find((candidate) => scenarioSetLabel(candidate) === label)
      return {
        name: key,
        type: 'line',
        smooth: true,
        data: bins.map((bin) => {
          const value = typeTimeCount(item, bin, typeLabel)
          const baselineValue = typeTimeCount(baseline, bin, typeLabel)
          return modeValue(value, baselineValue, mode)
        }),
      }
    }),
  }
}

function buildTypeLocationOption(
  items: ScenarioSetVisualization[],
  selectedSets: string[],
  selectedTypes: string[],
  mode: ScenarioAnalysisMode,
) {
  const setFilter = selectedSets.length ? new Set(selectedSets) : new Set(items.map((item) => scenarioSetLabel(item)))
  const aggregateTypes = selectedTypes.includes(ALL_TYPE_LABEL)
  const typeFilter = !aggregateTypes && selectedTypes.length
    ? new Set(selectedTypes)
    : new Set(items.flatMap((item) => item.summary.joint_structure.type_time.map((row) => row.type_label)))
  const visibleLocationRows = items.flatMap((item) =>
    item.summary.joint_structure.location_time.filter(
      (row) => setFilter.has(scenarioSetLabel(item)) && typeFilter.has(row.type_label),
    ),
  )
  const locations = orderedSpatialLocations(items, visibleLocationRows.map((row) => row.location))
  const locationAlias = spatialLocationAlias(items, locations)
  const baseline = baselineScenarioItem(items)
  const seriesKeys = aggregateTypes
    ? items.filter((item) => setFilter.has(scenarioSetLabel(item))).map(scenarioSetLabel)
    : unique(
        items.flatMap((item) =>
          item.summary.joint_structure.location_time
            .filter((row) => setFilter.has(scenarioSetLabel(item)) && typeFilter.has(row.type_label))
            .map((row) => `${scenarioSetLabel(item)} · ${row.type_label}`),
        ),
      )
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: valueFormatterForMode(mode),
    },
    legend: legendConfig({ top: 0, selectedMode: false }),
    grid: { top: 92, right: 18, bottom: 96, left: 48 },
    xAxis: categoryAxis(locations, { rotate: locations.length > 8 ? 35 : 0 }),
    yAxis: valueAxis('扰动数', mode),
    series: seriesKeys.map((key) => {
      const { label, typeLabel } = parseTypeSeriesKey(key, aggregateTypes)
      const item = items.find((candidate) => scenarioSetLabel(candidate) === label)
      return {
        name: key,
        type: 'line',
        smooth: true,
        emphasis: { focus: 'series' },
        data: locations.map((location) => {
          const value = typeLocationCount(item, location, typeLabel, locationAlias)
          const baselineValue = typeLocationCount(baseline, location, typeLabel, locationAlias)
          return modeValue(value, baselineValue, mode)
        }),
      }
    }),
  }
}

function orderedSpatialLocations(items: ScenarioSetVisualization[], rawLocations: string[]) {
  const existing = new Set(rawLocations)
  const stationOrder = items.find((item) => item.station_order.length)?.station_order ?? []
  const ordered = stationOrder.flatMap((station, index) => {
    const next = stationOrder[index + 1]
    return next ? [station, `${station}-${next}`] : [station]
  })
  const known = ordered.filter((location) => existing.has(location) || existing.has(reverseSection(location)))
  const knownSet = new Set(known)
  const rest = [...existing]
    .filter((location) => !knownSet.has(location) && !knownSet.has(reverseSection(location)))
    .sort()
  return [...known, ...rest]
}

function reverseSection(location: string) {
  const [left, right, ...rest] = location.split('-')
  return left && right && rest.length === 0 ? `${right}-${left}` : ''
}

function spatialLocationAlias(items: ScenarioSetVisualization[], locations: string[]) {
  const aliases = new Map<string, string>()
  const knownLocations = new Set(locations)
  for (const item of items) {
    for (let index = 0; index < item.station_order.length - 1; index += 1) {
      const left = item.station_order[index]
      const right = item.station_order[index + 1]
      const forward = `${left}-${right}`
      const reverse = `${right}-${left}`
      const target = knownLocations.has(forward) ? forward : knownLocations.has(reverse) ? reverse : forward
      aliases.set(forward, target)
      aliases.set(reverse, target)
    }
  }
  return aliases
}

function parseTypeSeriesKey(key: string, aggregateTypes: boolean) {
  if (aggregateTypes) return { label: key, typeLabel: ALL_TYPE_FILTER }
  const separator = ' · '
  const index = key.lastIndexOf(separator)
  if (index < 0) return { label: key, typeLabel: '' }
  return {
    label: key.slice(0, index),
    typeLabel: key.slice(index + separator.length),
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
    legend: legendConfig({ top: 0, type: 'scroll' }),
    grid: { top: 68, right: 18, bottom: 58, left: 56 },
    xAxis: categoryAxis(labels, { rotate: labels.length > 3 ? 24 : 0 }),
    yAxis: { type: 'value', name: '均值' },
    series: metrics.map((metric) => ({
      name: metric,
      type: 'bar',
      label: barValueLabel(),
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
    legend: legendConfig({ top: 0, type: 'scroll' }),
    grid: { top: 68, right: 18, bottom: 58, left: 56 },
    xAxis: categoryAxis(labels, { rotate: labels.length > 3 ? 24 : 0 }),
    yAxis: { type: 'value', name: '平均相对误差' },
    series: metrics.map((metric) => ({
      name: metric,
      type: 'bar',
      label: barValueLabel(),
      data: labels.map((datasetId) => {
        return rows.find((row) => row.dataset_id === datasetId && row.metric_label === metric)?.mean_relative_error ?? 0
      }),
    })),
  }
}

function categoryCount(item: ScenarioSetVisualization, label: string) {
  return item.summary.category_ratios.find((row) => row.label === label)?.count ?? 0
}

function baselineScenarioItem(items: ScenarioSetVisualization[]) {
  return (
    items.find((item) => item.scenario_set_id === baselineScenarioSetId.value) ??
    items[0] ??
    null
  )
}

function disturbanceCountValue(item: ScenarioSetVisualization, label: string) {
  return item.summary.combination_complexity.count_distribution.find((row) => row.label === label)?.count ?? 0
}

function typeTimeCount(item: ScenarioSetVisualization | null | undefined, timeBin: string, typeLabel: string) {
  const rows =
    item?.summary.joint_structure.type_time.filter(
      (row) =>
        row.time_bin === timeBin &&
        (typeLabel === ALL_TYPE_FILTER || row.type_label === typeLabel),
    ) ?? []
  return sumCounts(rows)
}

function typeLocationCount(
  item: ScenarioSetVisualization | null | undefined,
  location: string,
  typeLabel: string,
  locationAlias: Map<string, string>,
) {
  const rows =
    item?.summary.joint_structure.location_time.filter(
      (row) =>
        (locationAlias.get(row.location) ?? row.location) === location &&
        (typeLabel === ALL_TYPE_FILTER || row.type_label === typeLabel),
    ) ?? []
  return sumCounts(rows)
}

function modeValue(value: number, baselineValue: number, mode: ScenarioAnalysisMode) {
  if (mode === 'absolute') return value
  return baselineValue === 0 ? null : value / baselineValue
}

function valueAxis(name: string, mode: ScenarioAnalysisMode) {
  return mode === 'absolute'
    ? { type: 'value', name }
    : {
        type: 'value',
        name: '相对基准',
        axisLabel: { formatter: (value: number) => formatChartNumber(Number(value)) },
      }
}

function percentAxis(name: string) {
  return {
    type: 'value',
    name,
    max: 1,
    axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%` },
  }
}

function valueFormatterForMode(mode: ScenarioAnalysisMode) {
  return (value: number) => formatChartNumber(Number(value))
}

function percentFormatterForMode(mode: ScenarioAnalysisMode) {
  return mode === 'absolute'
    ? (value: number) => `${(Number(value) * 100).toFixed(1)}%`
    : valueFormatterForMode(mode)
}

function legendConfig(options: Record<string, unknown> = {}) {
  return {
    ...options,
    formatter: truncateLegendName,
    tooltip: { show: true },
  }
}

function truncateLegendName(name: string) {
  return name.length > LEGEND_NAME_LIMIT ? `${name.slice(0, LEGEND_NAME_LIMIT)}...` : name
}

function categoryAxis(data: string[], options: { name?: string; rotate?: number } = {}) {
  return {
    type: 'category',
    name: options.name,
    data,
    axisLabel: {
      interval: 0,
      rotate: options.rotate ?? 0,
      formatter: truncateAxisLabel,
    },
  }
}

function truncateAxisLabel(value: string) {
  return value.length > AXIS_LABEL_LIMIT ? `${value.slice(0, AXIS_LABEL_LIMIT)}...` : value
}

function coverageValue(item: ScenarioSetVisualization, key: 'time_ratio' | 'space_ratio') {
  return item.summary.coverage.rows.find((row) => row.type === 'all')?.[key] ?? 0
}

function unique(values: string[]) {
  return [...new Set(values)]
}

function sumCounts(rows: { count: number }[]) {
  return rows.reduce((total, row) => total + row.count, 0)
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
      <template v-if="page === 'ablation-scenarios'">
        <el-card shadow="never">
          <el-row class="analysis-toolbar" :gutter="12" align="middle">
            <el-col :span="8">
              <div class="inline-control">
                <span>基准场景分类：</span>
                <el-select
                  v-model="baselineScenarioSetId"
                  filterable
                  remote
                  reserve-keyword
                  class="analysis-select full-width"
                  placeholder="选择基准"
                  :disabled="scenarioBusy"
                  :loading="scenarioSetOptionsLoading"
                  :remote-method="loadScenarioSetOptions"
                  @visible-change="reloadScenarioSetOptionsOnOpen"
                >
                  <el-option
                    v-for="item in scenarioSetSelectOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="inline-control">
                <span>对比场景分类：</span>
                <el-select
                  v-model="candidateScenarioSetIds"
                  multiple
                  filterable
                  remote
                  reserve-keyword
                  collapse-tags
                  collapse-tags-tooltip
                  class="analysis-select full-width"
                  placeholder="选择对比集"
                  :disabled="scenarioBusy"
                  :loading="scenarioSetOptionsLoading"
                  :remote-method="loadScenarioSetOptions"
                  @visible-change="reloadScenarioSetOptionsOnOpen"
                >
                  <el-option
                    v-for="item in candidateScenarioSetOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
              </div>
            </el-col>
            <el-col :span="4">
              <el-radio-group v-model="scenarioAnalysisMode" class="mode-radio" :disabled="scenarioBusy">
                <el-radio-button value="absolute">数值</el-radio-button>
                <el-radio-button value="relative">误差</el-radio-button>
              </el-radio-group>
            </el-col>
            <el-col :span="4">
              <el-button
                class="full-width"
                type="primary"
                :loading="scenarioCompareLoading"
                :disabled="scenarioBusy"
                @click="compareScenarioSets"
              >
                开始分析
              </el-button>
            </el-col>
          </el-row>
        </el-card>

          <el-row class="analysis-section" :gutter="16">
            <el-col :span="8">
              <el-card shadow="never">
                <el-statistic title="基准场景分类" :value="baselineScenarioSetId || '-'" />
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="never">
                <el-statistic title="对比场景分类" :value="candidateScenarioSetIds.length" />
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
                <ChartPanel
                  :option="scenarioCategoryOption"
                  filename="scenario-type-composition"
                  chart-class="analysis-chart"
                  height="320px"
                />
              </el-card>
              <el-card shadow="never">
                <template #header>扰动覆盖率</template>
                <ChartPanel
                  :option="scenarioCoverageOption"
                  filename="scenario-coverage"
                  chart-class="analysis-chart"
                  height="320px"
                />
              </el-card>
            </div>

            <el-card shadow="never">
              <template #header>组合复杂度摘要</template>
              <ChartPanel
                :option="combinationMetricOption"
                filename="combination-complexity-metrics"
                chart-class="analysis-chart"
                height="320px"
              />
            </el-card>

            <el-card shadow="never">
              <template #header>单场景扰动数分布</template>
              <ChartPanel
                :option="disturbanceCountOption"
                filename="disturbance-count"
                chart-class="analysis-chart"
                height="320px"
              />
            </el-card>

            <el-card class="analysis-section" shadow="never">
              <template #header>时空联合结构</template>
              <div class="type-time-controls">
                <label class="type-time-filter">
                  <span>集合维度</span>
                  <el-select
                    v-model="typeTimeSetFilter"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    class="type-time-select"
                    placeholder="全部场景分类"
                    :disabled="scenarioBusy"
                  >
                    <el-option
                      v-for="label in typeTimeSetOptions"
                      :key="label"
                      :label="label"
                      :value="label"
                    />
                  </el-select>
                </label>
                <label class="type-time-filter">
                  <span>类型维度</span>
                  <el-select
                    v-model="typeTimeTypeFilter"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    class="type-time-select"
                    placeholder="全部场景类型"
                    :disabled="scenarioBusy"
                  >
                    <el-option
                      v-for="label in typeTimeTypeOptions"
                      :key="label"
                      :label="label"
                      :value="label"
                    />
                  </el-select>
                </label>
              </div>
              <el-row :gutter="16">
                <el-col :span="24">
                  <el-card shadow="never">
                    <template #header>时间-数量</template>
                    <ChartPanel
                      :option="typeTimeOption"
                      filename="type-time-structure"
                      chart-class="analysis-chart wide-chart"
                      height="380px"
                    />
                  </el-card>
                </el-col>
                <el-col :span="24">
                  <el-card shadow="never" class="joint-chart-card">
                    <template #header>空间-数量</template>
                    <ChartPanel
                      :option="typeLocationOption"
                      filename="type-location-structure"
                      chart-class="analysis-chart wide-chart"
                      height="380px"
                    />
                  </el-card>
                </el-col>
              </el-row>
            </el-card>

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
                  <ChartPanel
                    :option="mathMetricOption"
                    filename="math-graph-metrics"
                    chart-class="analysis-chart"
                    height="320px"
                  />
                </el-card>
                <el-card shadow="never">
                  <template #header>锚点覆盖</template>
                  <ChartPanel
                    :option="anchorCoverageOption"
                    filename="anchor-coverage"
                    chart-class="analysis-chart"
                    height="320px"
                  />
                </el-card>
              </div>
              <div class="analysis-grid compact-grid">
                <el-card shadow="never">
                  <template #header>扰动参数统计</template>
                  <el-table :data="parameterRows" height="320" empty-text="暂无参数统计">
                    <el-table-column prop="scenario_set_id" label="场景分类" min-width="150" show-overflow-tooltip />
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
                    <el-table-column prop="scenario_set_id" label="场景分类" min-width="150" show-overflow-tooltip />
                    <el-table-column prop="relation" label="关系类型" min-width="120" />
                    <el-table-column prop="count" label="数量" width="100" />
                  </el-table>
                </el-card>
              </div>
            </el-card>
          </template>
          <el-empty v-else class="analysis-section" description="请选择基准和对比场景分类并开始对比" />
      </template>

      <template v-else>
        <el-card shadow="never">
          <el-row class="analysis-toolbar" :gutter="12" align="middle">
            <el-col :span="8">
              <div class="inline-control">
                <span>基准数据集：</span>
                <el-select
                  v-model="baselineDatasetId"
                  filterable
                  remote
                  reserve-keyword
                  class="analysis-select full-width"
                  placeholder="选择基准"
                  :disabled="datasetBusy"
                  :loading="datasetOptionsLoading"
                  :remote-method="loadDatasetOptions"
                  @visible-change="reloadDatasetOptionsOnOpen"
                >
                  <el-option
                    v-for="item in datasetSelectOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="inline-control">
                <span>对比数据集：</span>
                <el-select
                  v-model="candidateDatasetIds"
                  multiple
                  filterable
                  remote
                  reserve-keyword
                  collapse-tags
                  collapse-tags-tooltip
                  class="analysis-select full-width"
                  placeholder="选择对比集"
                  :disabled="datasetBusy"
                  :loading="datasetOptionsLoading"
                  :remote-method="loadDatasetOptions"
                  @visible-change="reloadDatasetOptionsOnOpen"
                >
                  <el-option
                    v-for="item in candidateDatasetOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
              </div>
            </el-col>
            <el-col :span="4">
              <el-radio-group v-model="datasetAnalysisMode" class="mode-radio" :disabled="datasetBusy">
                <el-radio-button value="absolute">数值</el-radio-button>
                <el-radio-button value="relative">误差</el-radio-button>
              </el-radio-group>
            </el-col>
            <el-col :span="4">
              <el-button
                class="full-width"
                type="primary"
                :loading="datasetCompareLoading"
                :disabled="datasetBusy"
                @click="compareDatasets"
              >
                开始分析
              </el-button>
            </el-col>
          </el-row>
        </el-card>

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
            >
              <ul class="analysis-warning-list">
                <li v-for="message in datasetAnalysisWarnings" :key="message">
                  {{ message }}
                </li>
              </ul>
            </el-alert>

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

            <el-card shadow="never">
              <template #header>
                {{ datasetAnalysisMode === 'absolute' ? '求解行为数值对比' : '相对基准误差对比' }}
              </template>
              <ChartPanel
                :option="datasetSolveChartOption"
                :filename="datasetAnalysisMode === 'absolute' ? 'dataset-solve-metrics' : 'dataset-solve-errors'"
                chart-class="analysis-chart"
                height="320px"
              />
            </el-card>

            <el-card shadow="never">
              <template #header>{{ datasetAnalysisMode === 'absolute' ? '直接数值表' : '误差汇总表' }}</template>
              <el-table
                v-if="datasetAnalysisMode === 'absolute'"
                :data="datasetSummaryRows"
                height="360"
                empty-text="暂无求解行为数据"
              >
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
              <el-table
                v-else
                :data="datasetErrorSummaryRows"
                height="360"
                empty-text="暂无可对齐的误差数据"
              >
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
          </template>
          <el-empty v-else class="analysis-section" description="请选择基准和对比数据集并开始对比" />
      </template>
    </div>
  </section>
</template>

<style scoped>
.analysis-select {
  width: 420px;
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

.joint-chart-card {
  margin-top: 12px;
}

.type-time-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}

.type-time-filter {
  display: flex;
  min-width: min(360px, 100%);
  flex: 1;
  flex-direction: column;
  gap: 6px;
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 700;
}

.type-time-select {
  width: 100%;
}

.mode-radio {
  width: 100%;
}

.mode-radio :deep(.el-radio-button) {
  flex: 1;
}

.mode-radio :deep(.el-radio-button__inner) {
  width: 100%;
}

.analysis-warning-list {
  margin: 4px 0 0;
  padding-left: 18px;
}

.analysis-warning-list li + li {
  margin-top: 4px;
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
