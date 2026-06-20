<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api, formatApiError, isApiConflict } from '@/api/client'
import ChartPanel from '@/components/ChartPanel.vue'
import FieldLabelTip from '@/components/FieldLabelTip.vue'
import type {
  ScenarioSetVisualization,
  ScenarioVisualizationItem,
  TimetableDisturbance,
} from '@/types'

const props = defineProps<{
  projectId: string
  scenarioSetId: string
  section?: 'overview' | 'resources' | 'all'
  busy?: boolean
}>()

const emit = defineEmits<{
  createScenario: []
  simulateScenario: []
  deleteScenario: [scenarioId: string]
  viewScenario: [scenarioId: string]
  loadingChange: [loading: boolean]
}>()

const loading = ref(false)
const errorMessage = ref('')
const conflictMessage = ref('')
const analysis = ref<ScenarioSetVisualization | null>(null)
const selectedSpaceType = ref<SpaceTypeKey>('total')
let requestSeq = 0

type SpaceTypeKey = 'total' | TimetableDisturbance['type']

const SPACE_TYPE_OPTIONS: Array<{ label: string; value: SpaceTypeKey }> = [
  { label: '总体', value: 'total' },
  { label: '晚点', value: 'delay' },
  { label: '限速', value: 'speed_limit' },
  { label: '中断', value: 'interruption' },
]

const visibleSection = computed(() => props.section ?? 'all')
const showOverview = computed(() => visibleSection.value === 'all' || visibleSection.value === 'overview')
const showResources = computed(() => visibleSection.value === 'all' || visibleSection.value === 'resources')

watch(loading, (value) => {
  emit('loadingChange', value)
}, { immediate: true })

onBeforeUnmount(() => {
  emit('loadingChange', false)
})

const spaceOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
  legend: { bottom: 0, type: 'scroll' },
  series: [
    {
      name: spaceTypeLabel(selectedSpaceType.value),
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '42%'],
      data: spaceDistributionRows.value.map((item) => ({ name: item.label, value: item.count })),
    },
  ],
}))
const spaceDistributionRows = computed(() => {
  const counts = new Map<string, number>()
  for (const item of analysis.value?.summary.disturbances ?? []) {
    if (selectedSpaceType.value !== 'total' && item.type !== selectedSpaceType.value) continue
    const label = disturbanceSpaceLabel(item)
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label))
})
const typePieOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
  legend: { bottom: 0, type: 'scroll' },
  series: [
    {
      name: '纯扰动与混合',
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '42%'],
      data: scenarioCompositionRows.value.map((item) => ({ name: item.label, value: item.count })),
    },
  ],
}))
const scenarioCompositionRows = computed(() => {
  const counts = new Map(
    (analysis.value?.summary.category_ratios ?? []).map((item) => [item.key, item.count]),
  )
  return [
    { key: 'interruption', label: '纯中断', count: counts.get('interruption') ?? 0 },
    { key: 'speed_limit', label: '纯限速', count: counts.get('speed_limit') ?? 0 },
    { key: 'delay', label: '纯晚点', count: counts.get('delay') ?? 0 },
    { key: 'mixed', label: '混合', count: counts.get('mixed') ?? 0 },
  ].filter((item) => item.count > 0)
})
const disturbanceRatioOption = computed(() => {
  const counts = analysis.value?.summary.disturbance_counts
  const rows = [
    { label: '晚点', count: counts?.delay ?? 0 },
    { label: '限速', count: counts?.speed_limit ?? 0 },
    { label: '中断', count: counts?.interruption ?? 0 },
  ].filter((item) => item.count > 0)
  return {
    tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 个 ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [
      {
        name: '扰动占比',
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '42%'],
        data: rows.map((item) => ({ name: item.label, value: item.count })),
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
    analysis.value = null
    loading.value = false
    return
  }
  const seq = requestSeq + 1
  requestSeq = seq
  loading.value = true
  errorMessage.value = ''
  conflictMessage.value = ''
  try {
    const data = await api.readScenarioSetVisualization(props.projectId, props.scenarioSetId)
    if (seq !== requestSeq) return
    analysis.value = data
  } catch (error) {
    if (seq !== requestSeq) return
    analysis.value = null
    if (isApiConflict(error)) {
      conflictMessage.value = formatApiError(error)
      ElMessage.warning(conflictMessage.value)
    } else {
      errorMessage.value = formatApiError(error)
      ElMessage.error(errorMessage.value)
    }
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
  if (item.yaml_status === 'invalid') return '文件错误'
  const labels: Record<string, string> = {
    empty: '空场景',
    delay: '纯晚点',
    speed_limit: '纯限速',
    interruption: '纯中断',
    mixed: '混合',
  }
  return labels[item.category] ?? item.category
}

function disturbanceSpaceLabel(item: TimetableDisturbance) {
  if (item.type === 'delay') return item.station || '未知'
  const start = item.start_station || ''
  const end = item.end_station || ''
  return start || end ? `${start}-${end}` : '未知'
}

function spaceTypeLabel(value: SpaceTypeKey) {
  return SPACE_TYPE_OPTIONS.find((item) => item.value === value)?.label ?? value
}

defineExpose({ reload: loadDetail })
</script>

<template>
  <div
    v-loading="loading"
    class="scenario-category-detail"
    :class="{ 'is-resource-list': visibleSection === 'resources' }"
    element-loading-text="正在加载场景分类数据..."
  >
    <el-result
      v-if="conflictMessage"
      icon="warning"
      title="场景分类正在更新"
      :sub-title="conflictMessage"
    >
      <template #extra>
        <el-button :disabled="busy" @click="loadDetail">稍后重试</el-button>
      </template>
    </el-result>

    <el-result v-else-if="errorMessage" icon="error" title="场景分类加载失败" :sub-title="errorMessage">
      <template #extra>
        <el-button :disabled="busy" @click="loadDetail">重试</el-button>
      </template>
    </el-result>

    <template v-else-if="analysis">
      <div v-if="showOverview" class="scenario-chart-grid">
        <el-card shadow="never">
          <template #header>
            <FieldLabelTip
              label="场景类型占比"
              tip="场景类型包括纯中断 / 纯限速 / 纯晚点 / 混合"
            />
          </template>
          <ChartPanel :option="typePieOption" filename="scenario-type-ratio" height="260px" />
        </el-card>
        <el-card shadow="never">
          <template #header>场景扰动数量-空间分布</template>
          <div class="chart-control-row">
            <el-radio-group v-model="selectedSpaceType" size="small">
              <el-radio-button
                v-for="item in SPACE_TYPE_OPTIONS"
                :key="item.value"
                :label="item.value"
              >
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
          </div>
          <ChartPanel :option="spaceOption" filename="scenario-space-distribution" height="260px" />
        </el-card>
        <el-card shadow="never">
          <template #header>
            <FieldLabelTip
              label="扰动数量占比"
              tip="不论场景划分，统计全部扰动数量中晚点 / 限速 / 中断的占比"
            />
          </template>
          <ChartPanel :option="disturbanceRatioOption" filename="scenario-disturbance-ratio" height="260px" />
        </el-card>
      </div>

      <el-card v-if="showResources" class="scenario-section scenario-resource-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span>场景资源</span>
            <el-space>
              <el-button type="primary" :disabled="busy" @click="emit('createScenario')">新增场景</el-button>
              <el-button type="primary" :disabled="busy" @click="emit('simulateScenario')">模拟场景</el-button>
            </el-space>
          </div>
        </template>
        <el-table class="scenario-resource-table" :data="analysis.scenarios" height="100%" empty-text="暂无场景">
          <el-table-column prop="scenario_id" label="场景 ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="场景文件" width="110">
            <template #default="{ row }">
              <el-button link type="primary" :disabled="busy" @click="emit('viewScenario', row.scenario_id)">
                查看详情
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag :type="scenarioTagType(row.category)" size="small">{{ scenarioTypeLabel(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="晚点" width="90">
            <template #default="{ row }">{{ row.counts.delay }}</template>
          </el-table-column>
          <el-table-column label="限速" width="90">
            <template #default="{ row }">{{ row.counts.speed_limit }}</template>
          </el-table-column>
          <el-table-column label="中断" width="90">
            <template #default="{ row }">{{ row.counts.interruption }}</template>
          </el-table-column>
          <el-table-column label="原因" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.yaml_reason || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
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

.chart-control-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  margin-bottom: 8px;
}

@media (min-width: 1101px) {
  .scenario-category-detail.is-resource-list {
    display: flex;
    min-height: 0;
    flex: 1 1 auto;
    flex-direction: column;
  }

  .scenario-category-detail.is-resource-list .scenario-resource-card {
    display: flex;
    min-height: 0;
    flex: 1 1 auto;
    flex-direction: column;
    margin-top: 0;
  }

  .scenario-category-detail.is-resource-list .scenario-resource-card :deep(.el-card__body) {
    min-height: 0;
    flex: 1 1 auto;
    overflow: hidden;
  }

  .scenario-category-detail.is-resource-list .scenario-resource-table {
    height: 100%;
  }
}

@media (max-width: 1200px) {
  .scenario-chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
