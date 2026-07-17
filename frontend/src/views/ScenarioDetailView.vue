<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api, formatApiError, isApiConflict } from '@/api/client'
import ChartPanel from '@/components/ChartPanel.vue'
import RunGraphSpaceDistributionChart from '@/components/RunGraphSpaceDistributionChart.vue'
import RunGraphSelector from '@/components/RunGraphSelector.vue'
import ScenarioDialog from '@/components/ScenarioDialog.vue'
import type { ScenarioPayload } from '@/components/ScenarioDialog.vue'
import TimetableChart from '@/components/TimetableChart.vue'
import {
  DAY_SECONDS,
  DISTURBANCE_SERIES,
  buildDisturbanceTimeDistribution,
  formatDayClockTime,
} from '@/components/scenario-category'
import type {
  PlanTimetableState,
  RunGraphReference,
  ScenarioDetail,
  TimetableDisturbance,
} from '@/types'

const props = defineProps<{
  projectId: string
  scenarioSetId: string
  scenarioId: string
  busy?: boolean
}>()

const emit = defineEmits<{
  back: []
  validated: []
}>()

const detail = ref<ScenarioDetail | null>(null)
const timetable = ref<PlanTimetableState | null>(null)
const loading = ref(false)
const timetableLoading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const conflictMessage = ref('')
const timetableErrorMessage = ref('')
const disturbanceDialogVisible = ref(false)
const selectedRunGraph = ref<RunGraphReference | null>(null)
const autoTimetableLoadQueued = ref(false)
let requestSeq = 0
let timetableRequestSeq = 0

const scenarioPayload = computed(() => detail.value?.scenario ?? null)
const contextStats = computed(() => detail.value?.context_stats)
const runGraphDetail = computed(() => detail.value?.run_graph_detail ?? null)
const isScenarioFileValid = computed(() => detail.value?.yaml_status === 'valid')
const validationStatus = computed(() => detail.value?.validation_state?.status ?? 'invalid')
const isScenarioValidated = computed(() => isScenarioFileValid.value && validationStatus.value === 'valid')
const canUseScenario = computed(() => Boolean(detail.value?.run_graph) && isScenarioValidated.value)
const hasPendingRunGraph = computed(() => Boolean(selectedRunGraph.value) && !sameRunGraph(selectedRunGraph.value, detail.value?.run_graph))
const canValidateRunGraph = computed(() => Boolean(selectedRunGraph.value) && isScenarioFileValid.value)
const validateButtonLabel = computed(() => {
  if (hasPendingRunGraph.value) return '校验并应用'
  if (validationStatus.value === 'pending') return '校验'
  return '重新校验'
})
const disturbances = computed(() => timetable.value?.disturbances ?? [])
const disturbanceCountItems = computed(() => [
  { key: 'delay', label: '晚点', value: detail.value?.counts.delay ?? 0 },
  { key: 'speed_limit', label: '限速', value: detail.value?.counts.speed_limit ?? 0 },
  { key: 'interruption', label: '中断', value: detail.value?.counts.interruption ?? 0 },
])
const contextMetricItems = computed(() => [
  { key: 'station_count', label: '站点', value: contextStats.value?.station_count ?? '-' },
  { key: 'train_count', label: '车次', value: contextStats.value?.train_count ?? '-' },
  { key: 'section_node_count', label: '区间', value: contextStats.value?.section_node_count ?? '-' },
])
const disturbanceTimeDistribution = computed(() => buildDisturbanceTimeDistribution(disturbances.value))
const disturbanceTimeOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    formatter: (params: unknown) => timeLineTooltip(params),
  },
  legend: {
    top: 0,
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
    data: disturbanceTimeDistribution.value.map((item) => [item.seconds, item[series.key], item.label]),
  })),
}))
watch(
  () => [props.projectId, props.scenarioSetId, props.scenarioId].join('\u0000'),
  () => {
    void loadDetail()
  },
  { immediate: true },
)

async function loadDetail() {
  if (!props.projectId || !props.scenarioSetId || !props.scenarioId) return
  const seq = requestSeq + 1
  requestSeq = seq
  timetableRequestSeq += 1
  autoTimetableLoadQueued.value = false
  loading.value = true
  timetableLoading.value = false
  timetable.value = null
  errorMessage.value = ''
  conflictMessage.value = ''
  timetableErrorMessage.value = ''
  try {
    const data = await api.readScenario(props.projectId, props.scenarioSetId, props.scenarioId)
    if (seq !== requestSeq) return
    detail.value = data
    selectedRunGraph.value = cloneRunGraph(data.run_graph)
    queueTimetableLoad()
  } catch (error) {
    if (seq !== requestSeq) return
    detail.value = null
    selectedRunGraph.value = null
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

async function loadTimetable() {
  if (!props.projectId || !props.scenarioSetId || !props.scenarioId) return
  const seq = timetableRequestSeq + 1
  timetableRequestSeq = seq
  timetableLoading.value = true
  timetableErrorMessage.value = ''
  try {
    const data = await api.readScenarioTimetable(props.projectId, props.scenarioSetId, props.scenarioId)
    if (seq === timetableRequestSeq) timetable.value = data
  } catch (error) {
    if (seq === timetableRequestSeq) {
      timetable.value = null
      timetableErrorMessage.value = formatApiError(error)
    }
  } finally {
    if (seq === timetableRequestSeq) timetableLoading.value = false
  }
}

function queueTimetableLoad() {
  autoTimetableLoadQueued.value = true
  window.setTimeout(() => {
    if (!autoTimetableLoadQueued.value || !canUseScenario.value) return
    autoTimetableLoadQueued.value = false
    void loadTimetable()
  }, 0)
}

async function validateRunGraph() {
  if (saving.value || !selectedRunGraph.value) return
  const applying = hasPendingRunGraph.value
  saving.value = true
  try {
    detail.value = await api.validateScenario(
      props.projectId,
      props.scenarioSetId,
      props.scenarioId,
      selectedRunGraph.value,
    )
    selectedRunGraph.value = cloneRunGraph(detail.value.run_graph)
    ElMessage.success(applying ? '运行图已应用，扰动校验通过' : '扰动与运行图匹配，校验通过')
    queueTimetableLoad()
    emit('validated')
  } catch (error) {
    ElMessage.error(formatApiError(error))
  } finally {
    saving.value = false
  }
}

function openDisturbanceDialog() {
  if (!detail.value?.run_graph) {
    ElMessage.warning('请先选择运行图。')
    return
  }
  disturbanceDialogVisible.value = true
}

async function saveDisturbances(payload: { scenarioId: string; data: ScenarioPayload }) {
  if (saving.value) return
  const runGraph = detail.value?.run_graph
  if (!runGraph) {
    ElMessage.warning('请先选择运行图。')
    return
  }
  saving.value = true
  try {
    detail.value = await api.updateScenarioDisturbances(
      props.projectId,
      props.scenarioSetId,
      props.scenarioId,
      payload.data,
      runGraph,
    )
    selectedRunGraph.value = cloneRunGraph(detail.value.run_graph)
    disturbanceDialogVisible.value = false
    ElMessage.success('扰动事件已保存')
    timetable.value = null
    emit('validated')
  } catch (error) {
    ElMessage.error(formatApiError(error))
  } finally {
    saving.value = false
  }
}

function disturbanceTypeTag(item: TimetableDisturbance) {
  if (item.type === 'interruption') return 'danger'
  if (item.type === 'speed_limit') return 'warning'
  return 'success'
}

function disturbanceTypeLabel(item: TimetableDisturbance) {
  if (item.type === 'delay') return '晚点'
  if (item.type === 'speed_limit') return '限速'
  return '中断'
}

function disturbanceLocation(item: TimetableDisturbance) {
  if (item.type === 'delay') return [item.train_id, item.station, item.event_type].filter(Boolean).join(' / ')
  return [item.start_station, item.end_station].filter(Boolean).join(' -> ')
}

function disturbanceTime(item: TimetableDisturbance) {
  if (item.type === 'delay') return secondsToHms(item.start_time)
  const start = secondsToHms(item.start_time)
  const end = secondsToHms(item.end_time)
  return end ? `${start} - ${end}` : start
}

function disturbanceValue(item: TimetableDisturbance) {
  if (item.type === 'delay') return `${item.seconds ?? 0}s`
  if (item.type === 'interruption') return `${item.duration ?? 0}s`
  return `${item.limit_speed ?? 0} km/h`
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

function statusTagType() {
  if (hasPendingRunGraph.value) return 'info'
  if (!isScenarioFileValid.value || validationStatus.value === 'invalid') return 'danger'
  if (validationStatus.value === 'valid') return 'success'
  return 'info'
}

function statusLabel() {
  if (hasPendingRunGraph.value) return '未校验，待校验后应用'
  if (!isScenarioFileValid.value) return '场景文件错误'
  if (validationStatus.value === 'valid') return '校验通过'
  if (validationStatus.value === 'pending') return '未校验'
  if (validationStatus.value === 'stale') return '需重新校验'
  return '校验失败'
}

function validationReason() {
  if (hasPendingRunGraph.value) return '应用后会校验当前扰动是否匹配所选运行图，通过后写入场景文件。'
  return detail.value?.validation_state?.reason ?? ''
}

function cloneRunGraph(runGraph: RunGraphReference | null | undefined) {
  return runGraph ? { ...runGraph } : null
}

function sameRunGraph(left: RunGraphReference | null | undefined, right: RunGraphReference | null | undefined) {
  if (!left && !right) return true
  if (!left || !right) return false
  return left.set_id === right.set_id && left.graph_id === right.graph_id
}

function secondsToHms(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  const total = Math.max(0, Math.round(value))
  const hour = Math.floor(total / 3600)
  const minute = Math.floor((total % 3600) / 60)
  const second = total % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`
}

</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-breadcrumb>
        <el-breadcrumb-item><a @click.prevent="emit('back')">扰动场景</a></el-breadcrumb-item>
        <el-breadcrumb-item>{{ scenarioSetId }}</el-breadcrumb-item>
        <el-breadcrumb-item>{{ scenarioId }}</el-breadcrumb-item>
      </el-breadcrumb>

      <div v-loading="loading" element-loading-text="正在加载场景数据...">
        <el-result v-if="conflictMessage" icon="warning" title="场景正在更新" :sub-title="conflictMessage">
          <template #extra>
            <el-button @click="loadDetail">稍后重试</el-button>
          </template>
        </el-result>

        <el-result v-else-if="errorMessage" icon="error" title="场景加载失败" :sub-title="errorMessage">
          <template #extra>
            <el-button @click="loadDetail">重试</el-button>
          </template>
        </el-result>

        <template v-else-if="detail">
          <div class="scenario-overview-grid">
            <el-card class="scenario-state-card" shadow="never">
              <div class="state-card-heading">
                <div class="state-title-group">
                  <span class="overview-title">运行图</span>
                  <el-tag :type="statusTagType()" size="small">{{ statusLabel() }}</el-tag>
                </div>
                <el-tooltip :content="validationReason()">
                  <span class="tooltip-button">
                    <el-button
                      type="primary"
                      :loading="saving"
                      :disabled="busy || saving || !canValidateRunGraph"
                      @click="validateRunGraph"
                    >
                      {{ validateButtonLabel }}
                    </el-button>
                  </span>
                </el-tooltip>
              </div>
              <RunGraphSelector
                v-model="selectedRunGraph"
                :project-id="projectId"
                :disabled="busy || saving"
              />
              <el-alert
                v-if="detail.yaml_reason"
                class="scenario-alert"
                type="error"
                :title="detail.yaml_reason"
                show-icon
                :closable="false"
              />
              <el-descriptions v-if="runGraphDetail" :column="2" size="small" border>
                <el-descriptions-item label="分类">{{ runGraphDetail.run_graph_set_id }}</el-descriptions-item>
                <el-descriptions-item label="运行图">{{ runGraphDetail.run_graph_id }}</el-descriptions-item>
                <el-descriptions-item label="Context SHA" :span="2">
                  <el-text truncated>{{ runGraphDetail.context_sha256 }}</el-text>
                </el-descriptions-item>
              </el-descriptions>
            </el-card>

            <el-card class="compact-overview-card" shadow="never">
              <div class="overview-title-row">
                <span class="overview-title">扰动数量</span>
                <span class="overview-title-extra">总数 {{ detail.counts.total }}</span>
              </div>
              <div class="compact-metric-row">
                <div v-for="item in disturbanceCountItems" :key="item.key" class="compact-metric">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </el-card>

            <el-card class="compact-overview-card" shadow="never">
              <div class="overview-title-row">
                <span class="overview-title">运行图规模</span>
              </div>
              <div class="compact-metric-row">
                <div v-for="item in contextMetricItems" :key="item.key" class="compact-metric">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </el-card>
          </div>

          <div class="scenario-main-stack">
            <el-card class="scenario-section" shadow="never">
              <template #header>
                <div class="card-header">
                  <span>扰动事件</span>
                  <el-space>
                    <el-button
                      :loading="timetableLoading"
                      :disabled="busy || saving || timetableLoading || !canUseScenario"
                      @click="loadTimetable"
                    >
                      加载运行图
                    </el-button>
                    <el-button type="primary" :disabled="busy || saving || !detail.run_graph" @click="openDisturbanceDialog">
                      新增 / 编辑
                    </el-button>
                  </el-space>
                </div>
              </template>
              <el-alert
                v-if="timetableErrorMessage"
                class="scenario-alert"
                type="error"
                :title="timetableErrorMessage"
                show-icon
                :closable="false"
              />
              <el-table :data="disturbances" empty-text="暂无扰动事件">
                <el-table-column label="类型" width="90">
                  <template #default="{ row }">
                    <el-tag :type="disturbanceTypeTag(row)" size="small">{{ disturbanceTypeLabel(row) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="位置" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">{{ disturbanceLocation(row) || '-' }}</template>
                </el-table-column>
                <el-table-column label="时间" min-width="180">
                  <template #default="{ row }">{{ disturbanceTime(row) || '-' }}</template>
                </el-table-column>
                <el-table-column label="参数" width="130">
                  <template #default="{ row }">{{ disturbanceValue(row) }}</template>
                </el-table-column>
              </el-table>
            </el-card>

            <el-card v-if="timetable" class="scenario-section" shadow="never">
              <template #header>场景扰动运行图</template>
              <TimetableChart
                :rows="timetable.plan.rows"
                :station-order="timetable.station_order"
                :disturbances="timetable.disturbances"
                :title="`${scenarioId} 场景扰动运行图`"
              />
            </el-card>

            <el-card class="scenario-section" shadow="never">
              <template #header>场景扰动数量-时间分布</template>
              <ChartPanel
                v-if="timetable"
                v-loading="timetableLoading"
                :option="disturbanceTimeOption"
                filename="scenario-detail-time-distribution"
                height="260px"
              />
              <el-empty v-else v-loading="timetableLoading" description="加载运行图后显示时间分布" />
            </el-card>

            <el-card class="scenario-section" shadow="never">
              <template #header>场景扰动数量-空间分布</template>
              <RunGraphSpaceDistributionChart
                v-if="timetable"
                v-loading="timetableLoading"
                :disturbances="disturbances"
                :station-order="timetable.station_order"
                :mileage-by-station="timetable.mileage_by_station"
                filename="scenario-detail-space-distribution"
                height="300px"
              />
              <el-empty v-else v-loading="timetableLoading" description="加载运行图后显示空间分布" />
            </el-card>
          </div>
        </template>
      </div>
    </div>

    <ScenarioDialog
      v-model="disturbanceDialogVisible"
      title="编辑扰动事件"
      :project-id="projectId"
      :scenario-set-id="scenarioSetId"
      :initial-scenario-id="scenarioId"
      :options-scenario-id="scenarioId"
      :existing-scenario="scenarioPayload"
      :busy="busy || saving"
      :submitting="saving"
      @submit="saveDisturbances"
    />
  </section>
</template>

<style scoped>
.scenario-overview-grid {
  display: grid;
  grid-template-columns: minmax(360px, 1.35fr) minmax(320px, 0.9fr);
  align-items: stretch;
  gap: 12px;
  margin-top: 16px;
}

.scenario-overview-grid > :deep(.el-card) {
  min-width: 0;
}

.scenario-state-card {
  grid-row: span 2;
}

.scenario-state-card :deep(.el-card__body) {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
}

.compact-overview-card :deep(.el-card__body) {
  display: flex;
  min-width: 0;
  height: 100%;
  flex-direction: column;
  gap: 12px;
  padding-block: 14px;
}

.state-card-heading,
.overview-title-row {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.state-title-group {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.overview-title {
  color: var(--el-text-color-primary);
  font-weight: 600;
}

.overview-title-extra {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.compact-metric-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  flex: 1 1 auto;
  gap: 8px;
}

.compact-metric {
  display: flex;
  min-width: 0;
  min-height: 74px;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  padding: 12px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-extra-light);
}

.compact-metric span {
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compact-metric strong {
  overflow: hidden;
  color: var(--el-text-color-primary);
  font-size: 24px;
  font-weight: 700;
  line-height: 1.05;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scenario-section {
  margin-top: 16px;
}

.scenario-main-stack {
  min-width: 0;
}

.scenario-alert {
  margin-bottom: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.tooltip-button {
  display: inline-flex;
}

@media (max-width: 900px) {
  .scenario-overview-grid {
    grid-template-columns: 1fr;
  }

  .scenario-state-card {
    grid-row: auto;
  }

  .compact-overview-card :deep(.el-card__body) {
    height: auto;
  }

  .compact-metric {
    min-height: 68px;
  }
}
</style>
