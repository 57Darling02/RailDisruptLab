import type { EChartsCoreOption } from 'echarts/core'

import { barValueLabel } from '@/chart-options'
import type {
  AdjustmentPlanSolveAnalysis,
  AdjustmentPlanSolveErrorRow,
  AdjustmentPlanSolveMetricSummary,
  AdjustmentPlanSolveState,
  AdjustmentPlanSummary,
  ResourceOption,
  ScenarioSet,
  ScenarioSetVisualization,
} from '@/types'

export const DEFAULT_ABLATION_SCENARIO_LIMIT = 4

const SOLVE_METRIC_ORDER = [
  'objective',
  'mip_gap',
  'num_nodes',
  'duration_sec',
  'constraints',
  'build_duration_sec',
]
const SCENARIO_SERIES = [
  { key: 'total', label: '总数', color: '#303133' },
  { key: 'delay', label: '晚点', color: '#f59e0b' },
  { key: 'speed_limit', label: '限速', color: '#3b82f6' },
  { key: 'interruption', label: '中断', color: '#ef4444' },
] as const

type ScenarioSeriesKey = (typeof SCENARIO_SERIES)[number]['key']

const SCENARIO_VISUAL_STYLES = [
  { lineType: 'solid', lineTypeLabel: '实线', symbol: 'circle', symbolLabel: '圆点' },
  { lineType: 'dashed', lineTypeLabel: '虚线', symbol: 'diamond', symbolLabel: '菱形' },
  { lineType: 'dotted', lineTypeLabel: '点线', symbol: 'triangle', symbolLabel: '三角' },
  { lineType: 'solid', lineTypeLabel: '实线', symbol: 'rect', symbolLabel: '方点' },
] as const

export interface AblationScenarioSelection {
  baselineScenarioSetId: string
  candidateScenarioSetIds: string[]
}

export interface AblationMetricCard {
  key: string
  label: string
  value: string
  detail: string
}

export interface ScenarioStyleLegendRow {
  scenario_set_id: string
  role_label: string
  line_type: string
  line_type_label: string
  symbol: string
  symbol_label: string
}

export interface SolvePlanRow {
  scenario_set_id: string
  plan_id: string
  plan_key: string
  plan_label: string
  role: 'baseline' | 'candidate'
  case_count: number
  solved_count: number
  solved_ratio: number
  config_status: string
  solver_config_text: string
  status_text: string
  metrics: Record<string, number | null>
}

export interface ComparisonSummaryRow {
  key: string
  scenario_set_id: string
  plan_id: string
  plan_key: string
  plan_label: string
  metric: string
  metric_label: string
  case_count: number
  baseline_mean: number | null
  value_mean: number | null
  signed_delta_mean: number | null
  absolute_error_mean: number | null
  relative_error_mean: number | null
}

export interface SolveMetricColumn {
  key: string
  label: string
}

export function scenarioSetOptions(scenarioSets: ScenarioSet[]): ResourceOption[] {
  return scenarioSets.map((scenarioSet) => ({
    value: scenarioSet.scenario_set_id,
    label: `${scenarioSet.scenario_set_id} (${scenarioSet.case_count})`,
  }))
}

export function adjustmentPlanOptions(plans: AdjustmentPlanSummary[]): ResourceOption[] {
  return plans.map((plan) => ({
    value: plan.plan_id,
    label: `${plan.plan_id} (${plan.solved_count}/${plan.case_count})`,
  }))
}

export function mergeSelectedOptions(options: ResourceOption[], selected: ResourceOption[]) {
  const result = [...options]
  for (const item of selected) {
    if (item.value && !result.some((option) => option.value === item.value)) {
      result.unshift(item)
    }
  }
  return result
}

export function scenarioSetLabel(scenarioSets: ScenarioSet[], scenarioSetId: string) {
  const scenarioSet = scenarioSets.find((item) => item.scenario_set_id === scenarioSetId)
  if (!scenarioSet) return scenarioSetId
  return `${scenarioSet.scenario_set_id} (${scenarioSet.case_count})`
}

export function reconcileAblationScenarioSelection(
  scenarioSets: ScenarioSet[],
  current: AblationScenarioSelection,
  limit = DEFAULT_ABLATION_SCENARIO_LIMIT,
  fillDefaultCandidates = true,
): AblationScenarioSelection {
  const scenarioSetIds = scenarioSets.map((scenarioSet) => scenarioSet.scenario_set_id)
  if (!scenarioSetIds.length) return { baselineScenarioSetId: '', candidateScenarioSetIds: [] }

  const baselineScenarioSetId = scenarioSetIds.includes(current.baselineScenarioSetId)
    ? current.baselineScenarioSetId
    : scenarioSetIds[0] ?? ''
  const candidateLimit = Math.max(0, limit - 1)
  const existingCandidates = current.candidateScenarioSetIds.filter(
    (scenarioSetId) => scenarioSetIds.includes(scenarioSetId) && scenarioSetId !== baselineScenarioSetId,
  )
  const candidateScenarioSetIds = existingCandidates.length || !fillDefaultCandidates
    ? existingCandidates.slice(0, candidateLimit)
    : scenarioSetIds.filter((scenarioSetId) => scenarioSetId !== baselineScenarioSetId).slice(0, candidateLimit)

  return { baselineScenarioSetId, candidateScenarioSetIds }
}

export function selectedScenarioSetIds(selection: AblationScenarioSelection): string[] {
  return [
    selection.baselineScenarioSetId,
    ...selection.candidateScenarioSetIds.filter(
      (scenarioSetId) => scenarioSetId !== selection.baselineScenarioSetId,
    ),
  ].filter(Boolean)
}

export function buildScenarioMetricCards(
  items: ScenarioSetVisualization[],
  selectedCount: number,
): AblationMetricCard[] {
  const scenarioCount = items.reduce((total, item) => total + item.summary.scenario_count, 0)
  const disturbanceCount = items.reduce(
    (total, item) => total + item.summary.disturbance_counts.total,
    0,
  )
  return [
    {
      key: 'scenario_sets',
      label: '场景分类',
      value: String(items.length || selectedCount),
      detail: items.length ? '已加载' : '等待分析',
    },
    {
      key: 'scenarios',
      label: '场景样本',
      value: String(scenarioCount),
      detail: items.length ? '总样本数' : '未加载',
    },
    {
      key: 'disturbances',
      label: '扰动总数',
      value: String(disturbanceCount),
      detail: '晚点 / 限速 / 中断',
    },
    {
      key: 'baseline',
      label: '基准分类',
      value: items[0]?.scenario_set_id ?? '无',
      detail: '分布参照',
    },
  ]
}

export function buildScenarioStyleLegendRows(
  items: ScenarioSetVisualization[],
): ScenarioStyleLegendRow[] {
  return items.map((item, index) => {
    const style = scenarioVisualStyle(index)
    return {
      scenario_set_id: item.scenario_set_id,
      role_label: index === 0 ? '基准' : `候选 ${index}`,
      line_type: style.lineType,
      line_type_label: style.lineTypeLabel,
      symbol: style.symbol,
      symbol_label: style.symbolLabel,
    }
  })
}

export function buildAblationMetricCards(
  analysis: AdjustmentPlanSolveAnalysis | null,
  selectedPlanCount: number,
): AblationMetricCard[] {
  if (!analysis) {
    return [
      { key: 'plans', label: '计划数', value: String(selectedPlanCount), detail: '等待分析' },
      { key: 'baseline', label: '基准计划', value: '无', detail: '未选择' },
      { key: 'cases', label: '对照场景', value: '0', detail: '等待求解数据' },
      { key: 'warnings', label: '诊断', value: '0', detail: '暂无诊断' },
    ]
  }
  const caseIds = new Set(analysis.comparison.rows.map((row) => row.case_id).filter(Boolean))
  return [
    {
      key: 'plans',
      label: '计划数',
      value: String(analysis.adjustment_plans.length),
      detail: `${selectedPlanCount} 个已选`,
    },
    {
      key: 'baseline',
      label: '基准计划',
      value: analysis.comparison.baseline_plan_key || analysis.comparison.baseline_plan_id || '无',
      detail: '对照参照',
    },
    {
      key: 'cases',
      label: '对照场景',
      value: String(caseIds.size),
      detail: `${analysis.comparison.rows.length} 条指标差异`,
    },
    {
      key: 'warnings',
      label: '诊断',
      value: String(analysis.warnings.length),
      detail: analysis.warnings.length ? '需要检查' : '数据一致',
    },
  ]
}

export function buildScenarioTypeTimeChartOption(
  items: ScenarioSetVisualization[],
): EChartsCoreOption {
  const timeBins = scenarioTimeBins(items)
  return {
    animationDuration: 300,
    tooltip: {
      trigger: 'axis',
      formatter: formatScenarioTypeTimeTooltip,
    },
    legend: {
      type: 'scroll',
      top: 0,
      data: SCENARIO_SERIES.map((series) => series.label),
    },
    grid: { top: 52, right: 24, bottom: 36, left: 58 },
    xAxis: { type: 'category', data: timeBins },
    yAxis: { type: 'value', name: '扰动数' },
    series: items.flatMap((item, itemIndex) => {
      const style = scenarioVisualStyle(itemIndex)
      return SCENARIO_SERIES.map((series) => ({
        id: `${item.scenario_set_id}-${series.key}`,
        name: series.label,
        type: 'line',
        smooth: true,
        showSymbol: timeBins.length <= 16,
        symbol: style.symbol,
        symbolSize: itemIndex === 0 ? 8 : 7,
        itemStyle: { color: series.color },
        lineStyle: {
          color: series.color,
          opacity: itemIndex === 0 ? 1 : 0.85,
          type: style.lineType,
          width: itemIndex === 0 ? 3 : 2,
        },
        data: scenarioTypeTimeValues(item, series.key, timeBins).map((value) => ({
          value,
          scenario_set_id: item.scenario_set_id,
          type_label: series.label,
        })),
      }))
    }),
  }
}

export function buildScenarioTypeCountChartOption(
  items: ScenarioSetVisualization[],
): EChartsCoreOption {
  return {
    animationDuration: 300,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { type: 'scroll', top: 0 },
    grid: { top: 42, right: 20, bottom: 32, left: 58 },
    xAxis: { type: 'category', data: items.map((item) => item.scenario_set_id) },
    yAxis: { type: 'value', name: '扰动数' },
    series: SCENARIO_SERIES.map((series) => ({
      name: series.label,
      type: 'bar',
      itemStyle: { color: series.color },
      data: items.map((item) => scenarioTypeCount(item, series.key)),
      label: barValueLabel(),
    })),
  }
}

function formatScenarioTypeTimeTooltip(params: unknown) {
  const items = Array.isArray(params) ? params : []
  const first = items[0] as { axisValue?: string } | undefined
  return [
    first?.axisValue ?? '',
    ...items.map((item) => {
      const payload = item as {
        marker?: string
        data?: { value?: number; scenario_set_id?: string; type_label?: string }
      }
      const data = payload.data ?? {}
      return `${payload.marker ?? ''}${data.scenario_set_id ?? '未知'} / ${data.type_label ?? ''}: ${data.value ?? 0}`
    }),
  ].filter(Boolean).join('<br/>')
}

export function buildSolvePlanRows(analysis: AdjustmentPlanSolveAnalysis | null): SolvePlanRow[] {
  if (!analysis) return []
  const baselinePlanKey = analysis.comparison.baseline_plan_key || analysis.comparison.baseline_plan_id
  return analysis.adjustment_plans.map((plan) => {
    const planKey = adjustmentPlanKey(plan)
    const metrics = Object.fromEntries(
      plan.summary_metrics.map((metric) => [metric.key, metric.mean]),
    ) as Record<string, number | null>
    return {
      scenario_set_id: plan.scenario_set_id,
      plan_id: plan.plan_id,
      plan_key: planKey,
      plan_label: adjustmentPlanLabel(plan),
      role: planKey === baselinePlanKey ? 'baseline' : 'candidate',
      case_count: plan.case_count,
      solved_count: plan.solved_count,
      solved_ratio: plan.case_count ? plan.solved_count / plan.case_count : 0,
      config_status: solveConfigStatus(plan),
      solver_config_text: solverConfigText(plan.solver_config),
      status_text: statusCountText(plan.status_counts),
      metrics,
    }
  })
}

export function buildComparisonSummaryRows(
  analysis: AdjustmentPlanSolveAnalysis | null,
): ComparisonSummaryRow[] {
  if (!analysis) return []
  const groups = new Map<string, AdjustmentPlanSolveErrorRow[]>()
  for (const row of analysis.comparison.rows) {
    const key = `${comparisonRowPlanKey(row)}\u0000${row.metric}`
    const rows = groups.get(key) ?? []
    rows.push(row)
    groups.set(key, rows)
  }
  return [...groups.values()]
    .filter(isNonEmptyRows)
    .map((rows) => {
      const [first] = rows
      const planKey = comparisonRowPlanKey(first)
      return {
        key: `${planKey}-${first.metric}`,
        scenario_set_id: first.scenario_set_id,
        plan_id: first.plan_id,
        plan_key: planKey,
        plan_label: comparisonRowPlanLabel(first),
        metric: first.metric,
        metric_label: first.metric_label,
        case_count: rows.length,
        baseline_mean: mean(rows.map((row) => row.baseline_value)),
        value_mean: mean(rows.map((row) => row.value)),
        signed_delta_mean: mean(rows.map((row) => row.signed_delta)),
        absolute_error_mean: mean(rows.map((row) => row.absolute_error)),
        relative_error_mean: mean(rows.map((row) => row.relative_error)),
      }
    })
    .sort((left, right) =>
      left.plan_key === right.plan_key
        ? metricOrder(left.metric) - metricOrder(right.metric)
        : left.plan_label.localeCompare(right.plan_label),
    )
}

export function solveMetricColumns(analysis: AdjustmentPlanSolveAnalysis | null): SolveMetricColumn[] {
  return orderedMetricKeys(analysis).map((metric) => ({
    key: metric,
    label: solveMetricLabel(analysis, metric),
  }))
}

export function buildMetricMeanChartOption(
  analysis: AdjustmentPlanSolveAnalysis | null,
): EChartsCoreOption {
  const plans = analysis?.adjustment_plans ?? []
  const metrics = orderedMetricKeys(analysis)
  const metricLabels = metrics.map((metric) => solveMetricLabel(analysis, metric))
  const metricByLabel = new Map(metrics.map((metric) => [solveMetricLabel(analysis, metric), metric]))
  return {
    animationDuration: 300,
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => formatMetricMeanTooltip(params, metricByLabel),
    },
    legend: {
      type: 'scroll',
      top: 0,
      data: plans.map(adjustmentPlanLabel),
    },
    grid: { top: 42, right: 20, bottom: 44, left: 64 },
    xAxis: { type: 'category', data: metricLabels },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        formatter: (value: number) => formatNumber(value),
      },
    },
    series: plans.map((plan) => ({
      name: adjustmentPlanLabel(plan),
      type: 'bar',
      data: metrics.map((metric) => summaryMetricMean(plan, metric)),
      label: {
        ...barValueLabel(),
        formatter: (params: { value: unknown; dataIndex?: number }) =>
          formatMetricValue(numberValue(params.value), metrics[params.dataIndex ?? -1] ?? ''),
      },
    })),
  }
}

function formatMetricMeanTooltip(params: unknown, metricByLabel: Map<string, string>) {
  const items = Array.isArray(params) ? params : []
  const first = items[0] as { axisValue?: string } | undefined
  const metric = metricByLabel.get(first?.axisValue ?? '') ?? ''
  return [
    first?.axisValue ?? '',
    ...items.map((item) => {
      const payload = item as { marker?: string; seriesName?: string; value?: unknown }
      return `${payload.marker ?? ''}${payload.seriesName ?? ''}: ${formatMetricValue(numberValue(payload.value), metric)}`
    }),
  ].filter(Boolean).join('<br/>')
}

export function buildComparisonDeltaChartOption(
  analysis: AdjustmentPlanSolveAnalysis | null,
): EChartsCoreOption {
  const plans = analysis?.adjustment_plans ?? []
  const metrics = orderedMetricKeys(analysis)
  const metricLabels = metrics.map((metric) => solveMetricLabel(analysis, metric))
  const baseline = baselineSolvePlan(analysis)
  return {
    animationDuration: 300,
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) => formatPercent(numberValue(value)),
    },
    legend: {
      type: 'scroll',
      top: 0,
      data: plans.map(adjustmentPlanLabel),
    },
    grid: { top: 42, right: 20, bottom: 44, left: 64 },
    xAxis: { type: 'category', data: metricLabels },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter: (value: number) => formatPercent(value),
      },
    },
    series: plans.map((plan) => ({
      name: adjustmentPlanLabel(plan),
      type: 'bar',
      data: metrics.map((metric) => relativeMetricError(baseline, plan, metric)),
      label: {
        ...barValueLabel(),
        formatter: ({ value }: { value: unknown }) => formatPercent(numberValue(value)),
      },
    })),
  }
}

function baselineSolvePlan(analysis: AdjustmentPlanSolveAnalysis | null) {
  const baselineKey = analysis?.comparison.baseline_plan_key || analysis?.comparison.baseline_plan_id || ''
  return analysis?.adjustment_plans.find((plan) => adjustmentPlanKey(plan) === baselineKey) ?? null
}

function relativeMetricError(
  baseline: AdjustmentPlanSolveState | null,
  plan: AdjustmentPlanSolveState,
  metric: string,
) {
  if (!baseline) return null
  const baselineValue = summaryMetricMean(baseline, metric)
  const value = summaryMetricMean(plan, metric)
  if (baselineValue === null || value === null || Math.abs(baselineValue) <= 1e-12) return null
  return Math.abs(value - baselineValue) / Math.abs(baselineValue)
}

export function solveMetricLabel(
  analysis: AdjustmentPlanSolveAnalysis | null,
  metric: string,
) {
  return analysis?.metric_labels[metric] ?? metric
}

export function formatMetricValue(value: number | null | undefined, metric = '') {
  if (value === null || value === undefined || !Number.isFinite(value)) return '无'
  if (metric === 'mip_gap') return formatPercent(value)
  if (metric === 'duration_sec' || metric === 'build_duration_sec') return `${formatNumber(value)}s`
  return formatNumber(value)
}

export function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '无'
  return `${(value * 100).toFixed(2)}%`
}

export function formatSignedMetricValue(value: number | null | undefined, metric = '') {
  if (value === null || value === undefined || !Number.isFinite(value)) return '无'
  const prefix = value > 0 ? '+' : ''
  if (metric === 'mip_gap') return `${prefix}${formatPercent(value)}`
  if (metric === 'duration_sec' || metric === 'build_duration_sec') return `${prefix}${formatNumber(value)}s`
  return `${prefix}${formatNumber(value)}`
}

export function roleLabel(role: SolvePlanRow['role']) {
  return role === 'baseline' ? '基准' : '候选'
}

function scenarioTimeBins(items: ScenarioSetVisualization[]) {
  const bins = items.flatMap((item) => item.summary.joint_structure.time_bins)
  return unique(bins.length ? bins : items.flatMap((item) => item.time_distribution?.map((row) => row.label) ?? []))
}

function scenarioTypeTimeValues(item: ScenarioSetVisualization, type: ScenarioSeriesKey, timeBins: string[]) {
  if (type === 'total') {
    const counts = new Map((item.time_distribution ?? []).map((row) => [row.label, row.count]))
    return timeBins.map((timeBin) => counts.get(timeBin) ?? scenarioTypeTimeCount(item, timeBin))
  }
  const counts = new Map(
    item.summary.joint_structure.type_time
      .filter((row) => row.type === type)
      .map((row) => [row.time_bin, row.count]),
  )
  return timeBins.map((timeBin) => counts.get(timeBin) ?? 0)
}

function scenarioTypeTimeCount(item: ScenarioSetVisualization, timeBin: string) {
  return item.summary.joint_structure.type_time
    .filter((row) => row.time_bin === timeBin)
    .reduce((total, row) => total + row.count, 0)
}

function scenarioTypeCount(
  item: ScenarioSetVisualization,
  type: ScenarioSeriesKey,
) {
  if (type === 'total') return item.summary.disturbance_counts.total
  return item.summary.disturbance_counts[type]
}

function scenarioVisualStyle(index: number) {
  return SCENARIO_VISUAL_STYLES[index % SCENARIO_VISUAL_STYLES.length] ?? SCENARIO_VISUAL_STYLES[0]
}

function orderedMetricKeys(analysis: AdjustmentPlanSolveAnalysis | null) {
  const keys = new Set<string>()
  for (const plan of analysis?.adjustment_plans ?? []) {
    for (const metric of plan.summary_metrics) {
      if (metric.count > 0) keys.add(metric.key)
    }
  }
  return [...keys].sort((left, right) => metricOrder(left) - metricOrder(right))
}

function metricOrder(metric: string) {
  const index = SOLVE_METRIC_ORDER.indexOf(metric)
  return index >= 0 ? index : SOLVE_METRIC_ORDER.length
}

function summaryMetricMean(plan: AdjustmentPlanSolveState, metric: string) {
  return plan.summary_metrics.find((item) => item.key === metric)?.mean ?? null
}

function adjustmentPlanKey(plan: Pick<AdjustmentPlanSolveState, 'scenario_set_id' | 'plan_id' | 'plan_key'>) {
  return plan.plan_key || `${plan.scenario_set_id}/${plan.plan_id}`
}

function adjustmentPlanLabel(plan: Pick<AdjustmentPlanSolveState, 'scenario_set_id' | 'plan_id' | 'plan_key'>) {
  return adjustmentPlanKey(plan)
}

function comparisonRowPlanKey(row: Pick<AdjustmentPlanSolveErrorRow, 'scenario_set_id' | 'plan_id' | 'plan_key'>) {
  return row.plan_key || `${row.scenario_set_id}/${row.plan_id}`
}

function comparisonRowPlanLabel(row: Pick<AdjustmentPlanSolveErrorRow, 'scenario_set_id' | 'plan_id' | 'plan_key'>) {
  return comparisonRowPlanKey(row)
}

function solveConfigStatus(plan: AdjustmentPlanSolveState) {
  if (!plan.config_known_count) return '未知'
  return plan.config_consistent ? '一致' : `${plan.solver_config_signatures.length} 组`
}

function solverConfigText(config: Record<string, number>) {
  const entries = Object.entries(config)
  if (!entries.length) return '未知'
  return entries.map(([key, value]) => `${key}=${formatMetricValue(value)}`).join(' / ')
}

function statusCountText(statusCounts: Array<{ label: string; count: number }>) {
  if (!statusCounts.length) return '未知'
  return statusCounts.map((item) => `${item.label} ${item.count}`).join(' / ')
}

function mean(values: Array<number | null | undefined>) {
  const clean = values.filter((value): value is number =>
    value !== null && value !== undefined && Number.isFinite(value),
  )
  if (!clean.length) return null
  return clean.reduce((total, value) => total + value, 0) / clean.length
}

function isNonEmptyRows<T>(rows: T[]): rows is [T, ...T[]] {
  return rows.length > 0
}

function numberValue(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function formatNumber(value: number) {
  const absolute = Math.abs(value)
  if (absolute >= 1000) return value.toFixed(0)
  if (absolute >= 10) return value.toFixed(2)
  if (absolute >= 1) return value.toFixed(3)
  return value.toFixed(4)
}

function unique<T>(items: T[]): T[] {
  return [...new Set(items)]
}
