<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { UploadFile, UploadUserFile } from 'element-plus'
import { ElMessage } from 'element-plus'

import { api, formatApiError, isApiConflict } from '@/api/client'
import ChartPanel from '@/components/ChartPanel.vue'
import ScenarioDialog from '@/components/ScenarioDialog.vue'
import type { ScenarioPayload } from '@/components/ScenarioDialog.vue'
import TimetableChart from '@/components/TimetableChart.vue'
import type { JsonObject, PlanTimetableState, ScenarioDetail, TimetableDisturbance } from '@/types'

const props = defineProps<{
  projectId: string
  scenarioSetId: string
  scenarioId: string
  busy?: boolean
}>()

const emit = defineEmits<{
  back: []
  activated: []
}>()

const detail = ref<ScenarioDetail | null>(null)
const timetable = ref<PlanTimetableState | null>(null)
const loading = ref(false)
const timetableLoading = ref(false)
const activating = ref(false)
const errorMessage = ref('')
const conflictMessage = ref('')
const timetableErrorMessage = ref('')
const activateDialogVisible = ref(false)
const disturbanceDialogVisible = ref(false)
const savingDisturbances = ref(false)
const timetableFiles = ref<UploadUserFile[]>([])
const mileageFiles = ref<UploadUserFile[]>([])
const timetableFile = ref<File | null>(null)
const mileageFile = ref<File | null>(null)
let requestSeq = 0
let timetableRequestSeq = 0

type DisturbanceTimeKey = 'total' | TimetableDisturbance['type']

type DisturbanceTimeBucket = Record<DisturbanceTimeKey, number> & {
  label: string
}

const DISTURBANCE_TIME_SERIES: { key: DisturbanceTimeKey; label: string }[] = [
  { key: 'total', label: '总数' },
  { key: 'delay', label: '晚点' },
  { key: 'speed_limit', label: '限速' },
  { key: 'interruption', label: '中断' },
]

const contextStats = computed(() => detail.value?.context_stats)
const disturbances = computed(() => timetable.value?.disturbances ?? [])
const disturbanceTimeDistribution = computed(() => buildDisturbanceTimeDistribution(disturbances.value))
const disturbanceTimeOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: {
    top: 0,
    selected: {
      总数: true,
      晚点: false,
      限速: false,
      中断: false,
    },
  },
  grid: { top: 48, right: 18, bottom: 32, left: 48 },
  xAxis: { type: 'category', data: disturbanceTimeDistribution.value.map((item) => item.label) },
  yAxis: { type: 'value', name: '数量' },
  series: DISTURBANCE_TIME_SERIES.map((series) => ({
    name: series.label,
    type: 'line',
    smooth: true,
    symbolSize: 6,
    emphasis: { focus: 'series' },
    data: disturbanceTimeDistribution.value.map((item) => item[series.key]),
  })),
}))
const scenarioPayload = computed(() => detail.value?.scenario ?? null)
const sourceFiles = computed(() => detail.value?.source_files ?? [])
const hasMissingSourceFile = computed(() => sourceFiles.value.some((file) => !file.exists))
const disturbanceCountItems = computed(() => [
  { key: 'delay', label: '晚点', value: detail.value?.counts.delay ?? 0 },
  { key: 'speed_limit', label: '限速', value: detail.value?.counts.speed_limit ?? 0 },
  { key: 'interruption', label: '中断', value: detail.value?.counts.interruption ?? 0 },
])
const contextMetricItems = computed(() => [
  { key: 'station_count', label: '站点', value: contextStats.value?.station_count ?? '-' },
  { key: 'train_count', label: '车次', value: contextStats.value?.train_count ?? '-' },
  { key: 'event_node_count', label: '事件节点', value: contextStats.value?.event_node_count ?? '-' },
])
const activationStatus = computed(() => detail.value?.activation_status ?? 'inactive')
const canEditDisturbances = computed(() => activationStatus.value === 'active')
const hasSelectedSourceFile = computed(() => Boolean(timetableFile.value || mileageFile.value))
const canActivate = computed(() => {
  if (!detail.value || activationStatus.value === 'invalid') return false
  const hasSource = detail.value.has_timetable && detail.value.has_mileage
  return hasSource || Boolean(timetableFile.value && mileageFile.value)
})

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
  loading.value = true
  timetableLoading.value = false
  timetable.value = null
  errorMessage.value = ''
  conflictMessage.value = ''
  timetableErrorMessage.value = ''
  try {
    const data = await api.readScenario(props.projectId, props.scenarioSetId, props.scenarioId)
    if (seq === requestSeq) {
      detail.value = data
      if (data.activation_status === 'active') void loadTimetable()
    }
  } catch (error) {
    if (seq === requestSeq) {
      detail.value = null
      if (isApiConflict(error)) {
        conflictMessage.value = formatApiError(error)
        ElMessage.warning(conflictMessage.value)
      } else {
        errorMessage.value = formatApiError(error)
        ElMessage.error(errorMessage.value)
      }
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

function openActivateDialog() {
  if (activationStatus.value === 'invalid') {
    ElMessage.warning('请先修正 scenario.yml，再校验场景。')
    return
  }
  resetUploadFiles()
  activateDialogVisible.value = true
}

function setTimetableFile(file: UploadFile) {
  if (file.raw) timetableFile.value = file.raw
}

function setMileageFile(file: UploadFile) {
  if (file.raw) mileageFile.value = file.raw
}

function warnSingleFile() {
  ElMessage.warning('每项只需要一个文件，请先移除后重新选择。')
}

async function activateScenario() {
  if (activating.value) return
  activating.value = true
  try {
    detail.value = await api.activateScenarioCase(
      props.projectId,
      props.scenarioSetId,
      props.scenarioId,
      timetableFile.value,
      mileageFile.value,
    )
    ElMessage.success('场景校验通过')
    resetUploadFiles()
    activateDialogVisible.value = false
    void loadTimetable()
    emit('activated')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    activating.value = false
  }
}

async function saveSourceFiles() {
  if (activating.value || !hasSelectedSourceFile.value) return
  activating.value = true
  try {
    detail.value = await api.updateScenarioCaseSources(
      props.projectId,
      props.scenarioSetId,
      props.scenarioId,
      timetableFile.value,
      mileageFile.value,
    )
    ElMessage.success('源文件已保存，场景需要重新校验')
    resetUploadFiles()
    timetable.value = null
    timetableErrorMessage.value = ''
    emit('activated')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    activating.value = false
  }
}

function resetUploadFiles() {
  timetableFiles.value = []
  mileageFiles.value = []
  timetableFile.value = null
  mileageFile.value = null
}

function openDisturbanceDialog() {
  if (!canEditDisturbances.value) {
    ElMessage.warning('请先完成场景校验，再编辑扰动事件。')
    return
  }
  disturbanceDialogVisible.value = true
}

async function saveDisturbances(payload: { scenarioId: string; data: ScenarioPayload }) {
  if (savingDisturbances.value) return
  savingDisturbances.value = true
  try {
    detail.value = await api.updateScenarioDisturbances(
      props.projectId,
      props.scenarioSetId,
      props.scenarioId,
      payload.data,
    )
    disturbanceDialogVisible.value = false
    ElMessage.success('扰动事件已保存')
    void loadTimetable()
    emit('activated')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    savingDisturbances.value = false
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

function buildDisturbanceTimeDistribution(items: TimetableDisturbance[]): DisturbanceTimeBucket[] {
  const buckets: DisturbanceTimeBucket[] = Array.from({ length: 24 }, (_, hour) => ({
    label: `${String(hour).padStart(2, '0')}:00`,
    total: 0,
    delay: 0,
    speed_limit: 0,
    interruption: 0,
  }))
  for (const item of items) {
    if (typeof item.start_time !== 'number' || !Number.isFinite(item.start_time)) continue
    const hour = Math.max(0, Math.min(23, Math.floor(item.start_time / 3600)))
    const bucket = buckets[hour]
    if (!bucket) continue
    bucket.total += 1
    bucket[item.type] += 1
  }
  return buckets
}

function secondsToHms(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  const total = Math.max(0, Math.round(value))
  const hour = Math.floor(total / 3600)
  const minute = Math.floor((total % 3600) / 60)
  const second = total % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`
}

function activationTagType() {
  if (activationStatus.value === 'active') return 'success'
  if (activationStatus.value === 'invalid') return 'danger'
  return 'warning'
}

function activationActionLabel() {
  return activationStatus.value === 'active' ? '更新资源' : '校验场景'
}

function activationTitle() {
  const labels: Record<string, string> = {
    active: '校验通过',
    inactive: '待校验',
    invalid: '校验失败',
  }
  return labels[activationStatus.value] ?? activationStatus.value
}

function activationSubtitle() {
  if (!detail.value) return ''
  if (detail.value.activation_reason) return detail.value.activation_reason
  if (activationStatus.value === 'active') return '已通过校验，可用于 MILP 和模型训练'
  if (activationStatus.value === 'invalid') return '请修正 scenario.yml 后刷新'
  return '校验源文件并构建场景运行图'
}

function sourceFileLabel(name: string) {
  const labels: Record<string, string> = {
    'timetable.xlsx': '时刻表',
    'mileage.xlsx': '里程表',
  }
  return labels[name] ?? name
}

function downloadUrl(filename: string) {
  return `/api/projects/${encodeURIComponent(props.projectId)}/scenario-sets/${encodeURIComponent(
    props.scenarioSetId,
  )}/scenarios/${encodeURIComponent(props.scenarioId)}/source/${encodeURIComponent(filename)}`
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
        <el-result
          v-if="conflictMessage"
          icon="warning"
          title="场景正在更新"
          :sub-title="conflictMessage"
        >
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
                  <span class="overview-title">场景状态</span>
                  <el-tag :type="activationTagType()" size="small">{{ activationTitle() }}</el-tag>
                  <el-tag v-if="hasMissingSourceFile" type="danger" size="small">资源缺失</el-tag>
                </div>
                <el-button
                  type="primary"
                  :disabled="busy || activationStatus === 'invalid'"
                  @click="openActivateDialog"
                >
                  {{ activationActionLabel() }}
                </el-button>
              </div>
              <p class="state-subtitle">{{ activationSubtitle() }}</p>
              <div class="source-file-list">
                <div v-for="file in sourceFiles" :key="file.name" class="source-file-row">
                  <div class="source-file-name">
                    <span>{{ sourceFileLabel(file.name) }}</span>
                    <el-tag v-if="!file.exists" type="danger" size="small">缺失</el-tag>
                  </div>
                  <el-link v-if="file.exists" :href="downloadUrl(file.name)" target="_blank">下载</el-link>
                  <span v-else class="muted-text">-</span>
                </div>
              </div>
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
                <span class="overview-title">场景规模</span>
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
            <template v-if="activationStatus === 'active'">
              <el-card class="scenario-section" shadow="never">
                <template #header>
                  <div class="card-header">
                    <span>扰动事件</span>
                    <el-space>
                      <el-button
                        :loading="timetableLoading"
                        :disabled="busy || timetableLoading"
                        @click="loadTimetable"
                      >
                        加载运行图
                      </el-button>
                      <el-button type="primary" :disabled="busy || !canEditDisturbances" @click="openDisturbanceDialog">
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

              <el-card class="scenario-section" shadow="never">
                <template #header>场景扰动数量-时间分布</template>
                <ChartPanel
                  v-if="timetable"
                  v-loading="timetableLoading"
                  :option="disturbanceTimeOption"
                  filename="scenario-detail-time-distribution"
                  height="260px"
                />
                <el-empty v-else v-loading="timetableLoading" description="正在读取运行图数据" />
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
            </template>
            <el-empty v-else class="scenario-section" :description="activationSubtitle()" />
          </div>
        </template>
      </div>
    </div>

    <el-dialog v-model="activateDialogVisible" title="校验场景" width="620px">
      <el-form label-width="120px">
        <el-form-item label="时刻表">
          <el-space wrap>
            <el-link v-if="detail?.has_timetable" :href="downloadUrl('timetable.xlsx')" target="_blank">timetable.xlsx</el-link>
            <span v-else>timetable.xlsx 缺失</span>
            <el-upload
              v-model:file-list="timetableFiles"
              :auto-upload="false"
              :limit="1"
              :on-change="setTimetableFile"
              :on-exceed="warnSingleFile"
              :disabled="activating"
            >
              <el-button :disabled="activating">重新上传</el-button>
            </el-upload>
          </el-space>
        </el-form-item>
        <el-form-item label="里程表">
          <el-space wrap>
            <el-link v-if="detail?.has_mileage" :href="downloadUrl('mileage.xlsx')" target="_blank">mileage.xlsx</el-link>
            <span v-else>mileage.xlsx 缺失</span>
            <el-upload
              v-model:file-list="mileageFiles"
              :auto-upload="false"
              :limit="1"
              :on-change="setMileageFile"
              :on-exceed="warnSingleFile"
              :disabled="activating"
            >
              <el-button :disabled="activating">重新上传</el-button>
            </el-upload>
          </el-space>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="activating" @click="activateDialogVisible = false">取消</el-button>
        <el-button :loading="activating" :disabled="!hasSelectedSourceFile" @click="saveSourceFiles">保存源文件</el-button>
        <el-button type="primary" :loading="activating" :disabled="!canActivate" @click="activateScenario">执行校验</el-button>
      </template>
    </el-dialog>

    <ScenarioDialog
      v-model="disturbanceDialogVisible"
      title="编辑扰动事件"
      :project-id="projectId"
      :scenario-set-id="scenarioSetId"
      :initial-scenario-id="scenarioId"
      :options-scenario-id="scenarioId"
      :existing-scenario="scenarioPayload as JsonObject | null"
      :busy="busy || savingDisturbances"
      :submitting="savingDisturbances"
      @submit="saveDisturbances"
    />
  </section>
</template>

<style scoped>
.scenario-overview-grid {
  display: grid;
  grid-template-columns: minmax(300px, 1.35fr) repeat(2, minmax(220px, 1fr));
  align-items: stretch;
  gap: 12px;
  margin-top: 16px;
}

.scenario-overview-grid :deep(.el-card__body) {
  height: 100%;
  box-sizing: border-box;
}

.scenario-state-card :deep(.el-card__body),
.compact-overview-card :deep(.el-card__body) {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
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

.overview-title-extra,
.state-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.state-subtitle {
  margin: 0;
  line-height: 1.45;
}

.compact-metric-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: auto;
}

.compact-metric {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
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
  font-size: 20px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scenario-section {
  margin-top: 16px;
}

.scenario-main-stack {
  min-width: 0;
}

.source-file-list {
  display: grid;
  gap: 10px;
}

.source-file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.source-file-name {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
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

@media (max-width: 900px) {
  .scenario-overview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
