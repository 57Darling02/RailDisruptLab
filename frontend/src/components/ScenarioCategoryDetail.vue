<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api } from '@/api/client'
import { barPercentLabel } from '@/chart-options'
import ChartPanel from '@/components/ChartPanel.vue'
import type { ScenarioCoverageRow, ScenarioSetVisualization, ScenarioVisualizationItem } from '@/types'

const props = defineProps<{
  projectId: string
  scenarioSetId: string
  busy?: boolean
}>()

const emit = defineEmits<{
  createScenario: []
  simulateScenario: []
  deleteScenario: [scenarioId: string]
  viewScenario: [scenarioId: string]
  loaded: []
}>()

const loading = ref(false)
const errorMessage = ref('')
const visualization = ref<ScenarioSetVisualization | null>(null)
let requestSeq = 0

const timeOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { top: 28, right: 18, bottom: 32, left: 48 },
  xAxis: { type: 'category', data: visualization.value?.time_distribution?.map((item) => item.label) ?? [] },
  yAxis: { type: 'value', name: '数量' },
  series: [
    {
      name: '扰动数量',
      type: 'line',
      smooth: true,
      data: visualization.value?.time_distribution?.map((item) => item.count) ?? [],
    },
  ],
}))
const spaceOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
  legend: { bottom: 0, type: 'scroll' },
  series: [
    {
      name: '空间分布',
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '42%'],
      data: visualization.value?.space_distribution?.map((item) => ({ name: item.label, value: item.count })) ?? [],
    },
  ],
}))
const typePieOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
  legend: { bottom: 0, type: 'scroll' },
  series: [
    {
      name: '场景类型',
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '42%'],
      data: visualization.value?.summary.category_ratios.map((item) => ({ name: item.label, value: item.count })) ?? [],
    },
  ],
}))
const coverageBarOption = computed(() => {
  const rows = visualization.value?.summary.coverage.rows ?? []
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => formatCoverageTooltip(params, rows),
    },
    legend: { top: 0 },
    grid: { top: 54, right: 18, bottom: 28, left: 48 },
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
        label: barPercentLabel(),
        data: rows.map((row) => row.time_ratio),
      },
      {
        name: '空间覆盖率',
        type: 'bar',
        label: barPercentLabel(),
        data: rows.map((row) => row.space_ratio),
      },
    ],
  }
})

watch(
  () => [props.projectId, props.scenarioSetId].join('\u0000'),
  () => {
    void loadDetail()
  },
  { immediate: true },
)

async function loadDetail() {
  if (!props.projectId || !props.scenarioSetId) {
    visualization.value = null
    return
  }
  const seq = requestSeq + 1
  requestSeq = seq
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await api.readScenarioSetVisualization(props.projectId, props.scenarioSetId)
    if (seq !== requestSeq) return
    visualization.value = data
    emit('loaded')
  } catch (error) {
    if (seq !== requestSeq) return
    visualization.value = null
    errorMessage.value = error instanceof Error ? error.message : String(error)
    ElMessage.error(errorMessage.value)
  } finally {
    if (seq === requestSeq) loading.value = false
  }
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

function formatCoverageTooltip(params: unknown, rows: ScenarioCoverageRow[]) {
  const items = Array.isArray(params) ? params : []
  const first = items[0] as { dataIndex?: number; axisValue?: string } | undefined
  const row = typeof first?.dataIndex === 'number' ? rows[first.dataIndex] : null
  if (!row) return ''
  return [
    `${first?.axisValue ?? row.label}`,
    `时间覆盖率 ${formatPercent(row.time_ratio)}`,
    `空间覆盖率 ${formatPercent(row.space_ratio)}`,
  ].join('<br/>')
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

defineExpose({ reload: loadDetail })
</script>

<template>
  <div v-loading="loading" class="scenario-category-detail" element-loading-text="正在加载场景分类数据...">
    <el-result v-if="errorMessage" icon="error" title="场景分类加载失败" :sub-title="errorMessage">
      <template #extra>
        <el-button :disabled="busy" @click="loadDetail">重试</el-button>
      </template>
    </el-result>

    <template v-else-if="visualization">
      <el-card class="scenario-section" shadow="never">
        <template #header>场景扰动数量-时间分布</template>
        <ChartPanel :option="timeOption" filename="scenario-time-distribution" height="320px" />
      </el-card>

      <div class="scenario-chart-grid">
        <el-card shadow="never">
          <template #header>场景扰动数量-空间分布</template>
          <ChartPanel :option="spaceOption" filename="scenario-space-distribution" height="260px" />
        </el-card>
        <el-card shadow="never">
          <template #header>场景类型占比</template>
          <ChartPanel :option="typePieOption" filename="scenario-type-ratio" height="260px" />
        </el-card>
        <el-card shadow="never">
          <template #header>扰动时间 / 空间覆盖率</template>
          <ChartPanel :option="coverageBarOption" filename="scenario-coverage" height="260px" />
        </el-card>
      </div>

      <el-card class="scenario-section" shadow="never">
        <template #header>
          <div class="card-header">
            <span>场景资源</span>
            <el-space>
              <el-button type="primary" :disabled="busy" @click="emit('simulateScenario')">模拟场景</el-button>
              <el-button type="primary" :disabled="busy" @click="emit('createScenario')">新增场景</el-button>
            </el-space>
          </div>
        </template>
        <el-table :data="visualization.scenarios" empty-text="暂无场景">
          <el-table-column prop="scenario_id" label="场景 ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="激活" width="90">
            <template #default="{ row }">
              <el-tag :type="row.activated ? 'success' : 'info'" size="small">
                {{ row.activated ? '已激活' : '未激活' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag :type="scenarioTagType(row.category)" size="small">{{ scenarioTypeLabel(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="counts.delay" label="晚点" width="90" />
          <el-table-column prop="counts.speed_limit" label="限速" width="90" />
          <el-table-column prop="counts.interruption" label="中断" width="90" />
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button link type="primary" :disabled="busy" @click="emit('viewScenario', row.scenario_id)">查看</el-button>
              <el-button link type="danger" :disabled="busy" @click="emit('deleteScenario', row.scenario_id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.scenario-category-detail {
  min-height: 260px;
}

.scenario-section {
  margin-top: 16px;
}

.scenario-chart-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

@media (max-width: 1200px) {
  .scenario-chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
