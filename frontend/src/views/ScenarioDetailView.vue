<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { UploadFile, UploadUserFile } from 'element-plus'
import { ElMessage } from 'element-plus'

import { api } from '@/api/client'
import ScenarioDialog from '@/components/ScenarioDialog.vue'
import type { ScenarioPayload } from '@/components/ScenarioDialog.vue'
import TimetableChart from '@/components/TimetableChart.vue'
import type { JsonObject, ScenarioDetail, TimetableDisturbance } from '@/types'

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
const loading = ref(false)
const activating = ref(false)
const errorMessage = ref('')
const activateDialogVisible = ref(false)
const disturbanceDialogVisible = ref(false)
const savingDisturbances = ref(false)
const timetableFiles = ref<UploadUserFile[]>([])
const mileageFiles = ref<UploadUserFile[]>([])
const timetableFile = ref<File | null>(null)
const mileageFile = ref<File | null>(null)
let requestSeq = 0

const contextStats = computed(() => detail.value?.context_stats)
const disturbances = computed(() => detail.value?.timetable?.disturbances ?? [])
const scenarioPayload = computed(() => detail.value?.scenario ?? null)
const sourceFiles = computed(() => detail.value?.source_files ?? [])
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
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await api.readScenario(props.projectId, props.scenarioSetId, props.scenarioId)
    if (seq === requestSeq) detail.value = data
  } catch (error) {
    if (seq === requestSeq) {
      detail.value = null
      errorMessage.value = error instanceof Error ? error.message : String(error)
      ElMessage.error(errorMessage.value)
    }
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function openActivateDialog() {
  if (activationStatus.value === 'invalid') {
    ElMessage.warning('请先修正 scenario.yml，再激活场景。')
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
    ElMessage.success('场景已激活')
    resetUploadFiles()
    activateDialogVisible.value = false
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
    ElMessage.success('源文件已保存，场景已回到未激活状态')
    resetUploadFiles()
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
    ElMessage.warning('请先激活场景，再编辑扰动事件。')
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

function secondsToHms(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  const total = Math.max(0, Math.round(value))
  const hour = Math.floor(total / 3600)
  const minute = Math.floor((total % 3600) / 60)
  const second = total % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`
}

function activationIcon() {
  if (activationStatus.value === 'active') return 'success'
  if (activationStatus.value === 'invalid') return 'error'
  return 'warning'
}

function activationTitle() {
  const labels: Record<string, string> = {
    active: '已激活',
    inactive: '未激活',
    invalid: '激活无效',
  }
  return labels[activationStatus.value] ?? activationStatus.value
}

function activationSubtitle() {
  if (!detail.value) return ''
  if (detail.value.activation_reason) return detail.value.activation_reason
  if (activationStatus.value === 'active') return '可用于 MILP 和模型训练'
  if (activationStatus.value === 'invalid') return '请修正 scenario.yml 后刷新'
  return '点击激活场景运行图'
}

function fileSizeText(size: number) {
  if (!Number.isFinite(size) || size <= 0) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
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
        <el-result v-if="errorMessage" icon="error" title="场景加载失败" :sub-title="errorMessage">
          <template #extra>
            <el-button @click="loadDetail">重试</el-button>
          </template>
        </el-result>

        <template v-else-if="detail">
          <div class="scenario-detail-grid">
            <el-card class="activation-card" shadow="never" @click="openActivateDialog">
              <el-result
                :icon="activationIcon()"
                :title="activationTitle()"
                :sub-title="activationSubtitle()"
              />
            </el-card>
            <div class="stats-grid">
              <el-card shadow="never"><el-statistic title="晚点" :value="detail.counts.delay" /></el-card>
              <el-card shadow="never"><el-statistic title="限速" :value="detail.counts.speed_limit" /></el-card>
              <el-card shadow="never"><el-statistic title="中断" :value="detail.counts.interruption" /></el-card>
              <el-card shadow="never"><el-statistic title="站点数量" :value="contextStats?.station_count ?? '-'" /></el-card>
              <el-card shadow="never"><el-statistic title="车次数量" :value="contextStats?.train_count ?? '-'" /></el-card>
              <el-card shadow="never"><el-statistic title="事件节点数" :value="contextStats?.event_node_count ?? '-'" /></el-card>
            </div>
          </div>

          <el-card class="scenario-section" shadow="never">
            <template #header>
              <div class="card-header">
                <span>场景资源</span>
                <el-button
                  type="primary"
                  :disabled="busy || activationStatus === 'invalid'"
                  @click="openActivateDialog"
                >
                  激活 / 更新源文件
                </el-button>
              </div>
            </template>
            <el-table :data="sourceFiles" empty-text="暂无源文件">
              <el-table-column prop="name" label="文件" width="180" />
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <el-tag :type="row.exists ? 'success' : 'danger'" size="small">
                    {{ row.exists ? '已上传' : '缺失' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="120">
                <template #default="{ row }">{{ fileSizeText(row.size_bytes) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template #default="{ row }">
                  <el-link v-if="row.exists" :href="downloadUrl(row.name)" target="_blank">下载</el-link>
                  <span v-else>-</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <template v-if="activationStatus === 'active' && detail.timetable">
            <el-card class="scenario-section" shadow="never">
              <template #header>场景扰动运行图</template>
              <TimetableChart
                :rows="detail.timetable.plan.rows"
                :station-order="detail.timetable.station_order"
                :disturbances="detail.timetable.disturbances"
                :title="`${scenarioId} 场景扰动运行图`"
              />
            </el-card>

            <el-card class="scenario-section" shadow="never">
              <template #header>
                <div class="card-header">
                  <span>扰动事件</span>
                  <el-button type="primary" :disabled="busy || !canEditDisturbances" @click="openDisturbanceDialog">
                    新增 / 编辑
                  </el-button>
                </div>
              </template>
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
          </template>
          <el-empty v-else class="scenario-section" :description="activationSubtitle()" />
        </template>
      </div>
    </div>

    <el-dialog v-model="activateDialogVisible" title="激活场景" width="620px">
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
        <el-button type="primary" :loading="activating" :disabled="!canActivate" @click="activateScenario">确定激活</el-button>
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
.scenario-detail-grid {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 16px;
  margin-top: 16px;
}

.activation-card {
  cursor: pointer;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.scenario-section {
  margin-top: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

@media (max-width: 900px) {
  .scenario-detail-grid {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
