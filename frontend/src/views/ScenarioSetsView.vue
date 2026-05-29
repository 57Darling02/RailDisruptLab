<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import VChart from 'vue-echarts'

import { chartDownloadToolbox } from '@/chart-options'
import EntityToolbar, { type EntityOption } from '@/components/EntityToolbar.vue'
import TimetableChart from '@/components/TimetableChart.vue'
import type {
  ScenarioCoverageRow,
  ScenarioSet,
  ScenarioSetVisualization,
  ScenarioSummary,
  ScenarioVisualizationItem,
} from '@/types'

const props = defineProps<{
  selectedScenarioSetId: string
  scenarioSets: ScenarioSet[]
  scenarios: ScenarioSummary[]
  visualization: ScenarioSetVisualization | null
  loading: boolean
}>()

defineEmits<{
  'update:selectedScenarioSetId': [value: string]
  reloadScenarioSets: [visible: boolean]
  createScenarioSet: []
  deleteScenarioSet: [scenarioSetId: string]
  normalGenerate: []
  createScenario: []
  deleteScenario: [scenarioId: string]
}>()

const selectedScenarioId = ref('')
const ALL_SCENARIOS = '__all__'
const selectedScenario = computed(
  () =>
    props.visualization?.scenarios.find((item) => item.scenario_id === selectedScenarioId.value) ??
    props.visualization?.scenarios[0] ??
    null,
)
const chartDisturbances = computed(() => {
  if (!props.visualization) return []
  return selectedScenarioId.value === ALL_SCENARIOS
    ? props.visualization.summary.disturbances
    : selectedScenario.value?.disturbances ?? []
})
const chartTitle = computed(() => {
  if (!props.selectedScenarioSetId) return '场景扰动分布'
  if (selectedScenarioId.value === ALL_SCENARIOS) return `${props.selectedScenarioSetId} 全部扰动分布`
  return `${selectedScenario.value?.scenario_id ?? props.selectedScenarioSetId} 扰动分布`
})
const typePieOption = computed(() => buildTypePieOption(props.visualization))
const coverageBarOption = computed(() => buildCoverageBarOption(props.visualization))
const counts = computed(() => props.visualization?.summary.disturbance_counts)
const scenarioById = computed(
  () => new Map(props.visualization?.scenarios.map((item) => [item.scenario_id, item]) ?? []),
)
const scenarioSetOptions = computed<EntityOption[]>(() =>
  props.scenarioSets.map((item) => ({
    label: `${item.scenario_set_id} (${item.case_count})`,
    value: item.scenario_set_id,
  })),
)

watch(
  () => props.visualization?.scenario_set_id,
  () => {
    selectedScenarioId.value = ALL_SCENARIOS
  },
  { immediate: true },
)

watch(
  () => props.visualization?.scenarios.map((item) => item.scenario_id).join('\u0000') ?? '',
  () => {
    if (selectedScenarioId.value === ALL_SCENARIOS) return
    if (!props.visualization?.scenarios.some((item) => item.scenario_id === selectedScenarioId.value)) {
      selectedScenarioId.value = ALL_SCENARIOS
    }
  },
)

function buildTypePieOption(visualization: ScenarioSetVisualization | null) {
  const data =
    visualization?.summary.category_ratios.map((item) => ({
      name: item.label,
      value: item.count,
    })) ?? []
  return {
    toolbox: chartDownloadToolbox('scenario-set-type-ratio'),
    tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        name: '场景类型',
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '42%'],
        data,
      },
    ],
  }
}

function buildCoverageBarOption(visualization: ScenarioSetVisualization | null) {
  const rows = visualization?.summary.coverage.rows ?? []
  return {
    toolbox: chartDownloadToolbox('scenario-set-coverage'),
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => formatCoverageTooltip(params, rows),
    },
    legend: { top: 0 },
    grid: { top: 42, right: 18, bottom: 28, left: 48 },
    xAxis: { type: 'category', data: rows.map((row) => row.label) },
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
        data: rows.map((row) => row.time_ratio),
      },
      {
        name: '空间覆盖率',
        type: 'bar',
        data: rows.map((row) => row.space_ratio),
      },
    ],
  }
}

function formatCoverageTooltip(params: unknown, rows: ScenarioCoverageRow[]) {
  const items = Array.isArray(params) ? params : []
  const first = items[0] as { dataIndex?: number; axisValue?: string } | undefined
  const row = typeof first?.dataIndex === 'number' ? rows[first.dataIndex] : null
  if (!row) return ''
  return [
    `${first?.axisValue ?? row.label}`,
    `时间覆盖率 ${formatPercent(row.time_ratio)} (${formatDuration(row.time_seconds)})`,
    `空间覆盖率 ${formatPercent(row.space_ratio)} (${row.space_units} 单位)`,
  ].join('<br/>')
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

function formatDuration(seconds: number) {
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

function scenarioTagType(category: string) {
  if (category === 'empty') return 'info'
  if (category === 'mixed') return 'warning'
  return 'success'
}

function scenarioTypeLabel(item: ScenarioVisualizationItem) {
  const labels: Record<string, string> = {
    empty: '空场景',
    delay: '纯晚点',
    speed_limit: '纯限速',
    interruption: '纯中断',
    mixed: '混合',
  }
  return labels[item.category] ?? item.category
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <EntityToolbar
        label="扰动场景集"
        :model-value="selectedScenarioSetId"
        :options="scenarioSetOptions"
        placeholder="选择扰动场景集"
        delete-label="删除扰动场景集"
        @update:model-value="$emit('update:selectedScenarioSetId', $event)"
        @visible-change="$emit('reloadScenarioSets', $event)"
        @add="$emit('createScenarioSet')"
        @delete="$emit('deleteScenarioSet', $event)"
      />

      <div v-if="!scenarioSets.length" class="primary-empty-panel">
        <el-empty :image-size="120">
          <template #description>
            <div class="primary-empty-title">请先新建扰动场景集</div>
          </template>
          <el-button type="primary" size="large" @click="$emit('createScenarioSet')">
            新建扰动场景集
          </el-button>
        </el-empty>
      </div>

      <div
        v-else
        v-loading="loading"
        class="page-stack"
        element-loading-text="正在加载扰动场景集数据..."
      >
        <el-row class="scenario-stat-row" :gutter="16">
          <el-col :span="6">
            <el-card shadow="never">
              <el-statistic title="场景数" :value="visualization?.summary.scenario_count ?? scenarios.length" />
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="never">
              <el-statistic title="晚点扰动" :value="counts?.delay ?? 0" />
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="never">
              <el-statistic title="限速扰动" :value="counts?.speed_limit ?? 0" />
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="never">
              <el-statistic title="中断扰动" :value="counts?.interruption ?? 0" />
            </el-card>
          </el-col>
        </el-row>

        <div v-if="visualization" class="scenario-visual-grid">
          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>场景扰动运行图</span>
                <el-space>
                  <el-select
                    v-model="selectedScenarioId"
                    class="scenario-select"
                    placeholder="选择场景"
                  >
                    <el-option label="All" :value="ALL_SCENARIOS" />
                    <el-option
                      v-for="item in visualization.scenarios"
                      :key="item.scenario_id"
                      :label="item.scenario_id"
                      :value="item.scenario_id"
                    />
                  </el-select>
                </el-space>
              </div>
            </template>
            <TimetableChart
              :rows="visualization.plan.rows"
              :station-order="visualization.station_order"
              :disturbances="chartDisturbances"
              :title="chartTitle"
            />
          </el-card>

          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>统计图</span>
              </div>
            </template>
            <div class="scenario-chart-stack">
              <div class="scenario-chart-card">
                <div class="scenario-chart-title">场景类型占比</div>
                <VChart :option="typePieOption" autoresize class="scenario-small-chart" />
              </div>
              <div class="scenario-chart-card">
                <div class="scenario-chart-title">扰动时间 / 空间覆盖率</div>
                <VChart :option="coverageBarOption" autoresize class="scenario-small-chart" />
              </div>
            </div>
          </el-card>
        </div>
        <el-alert
          v-else-if="selectedScenarioSetId"
          class="scenario-stat-row"
          title="原计划运行图未激活，暂不能展示扰动分布图。"
          type="warning"
          show-icon
          :closable="false"
        />

        <el-card class="scenario-list-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div>
                <span>当前扰动场景集内的场景</span>
                <span v-if="selectedScenarioSetId" class="scenario-set-context">
                  {{ selectedScenarioSetId }}
                </span>
              </div>
              <div class="scenario-actions">
                <el-button
                  type="primary"
                  :disabled="!selectedScenarioSetId"
                  @click="$emit('normalGenerate')"
                >
                  批量新增场景
                </el-button>
                <el-button
                  type="primary"
                  :disabled="!selectedScenarioSetId"
                  @click="$emit('createScenario')"
                >
                  新增场景
                </el-button>
              </div>
            </div>
          </template>
          <el-scrollbar class="table-scroll" max-height="520px">
            <el-table :data="scenarios" empty-text="暂无场景">
              <el-table-column prop="scenario_id" label="场景 ID" />
              <el-table-column label="类型" width="110">
                <template #default="{ row }">
                  <template v-if="visualization">
                    <el-tag
                      v-if="scenarioById.get(row.scenario_id)"
                      :type="scenarioTagType(scenarioById.get(row.scenario_id)?.category ?? '')"
                      size="small"
                    >
                      {{ scenarioTypeLabel(scenarioById.get(row.scenario_id)!) }}
                    </el-tag>
                  </template>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column prop="delay_count" label="延误数" width="120" />
              <el-table-column prop="speed_limit_count" label="限速数" width="120" />
              <el-table-column prop="path" label="路径" show-overflow-tooltip />
              <el-table-column label="操作" width="100">
                <template #default="{ row }">
                  <el-button
                    link
                    type="danger"
                    @click="$emit('deleteScenario', row.scenario_id)"
                  >
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-scrollbar>
        </el-card>
      </div>
    </div>
  </section>
</template>

<style scoped>
.scenario-stat-row {
  margin-bottom: 16px;
}

.scenario-visual-grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(360px, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.scenario-select {
  width: 220px;
}

.scenario-chart-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.scenario-chart-card {
  min-width: 0;
}

.scenario-chart-title {
  margin-bottom: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  font-weight: 600;
}

.scenario-small-chart {
  display: block;
  width: 100%;
  height: 230px;
}

.scenario-list-card {
  margin-top: 16px;
}

.scenario-set-context {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

@media (max-width: 1200px) {
  .scenario-visual-grid {
    grid-template-columns: 1fr;
  }
}
</style>
