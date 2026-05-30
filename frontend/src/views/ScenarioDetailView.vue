<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { UploadFile, UploadUserFile } from 'element-plus'
import { ElMessage } from 'element-plus'

import { api } from '@/api/client'
import TimetableChart from '@/components/TimetableChart.vue'
import type { ScenarioDetail } from '@/types'

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
const timetableFiles = ref<UploadUserFile[]>([])
const mileageFiles = ref<UploadUserFile[]>([])
const timetableFile = ref<File | null>(null)
const mileageFile = ref<File | null>(null)
let requestSeq = 0

const contextStats = computed(() => detail.value?.context_stats)

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
  timetableFiles.value = []
  mileageFiles.value = []
  timetableFile.value = null
  mileageFile.value = null
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
    activateDialogVisible.value = false
    emit('activated')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    activating.value = false
  }
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
                :icon="detail.activated ? 'success' : 'warning'"
                :title="detail.activated ? '已激活' : '未激活'"
                :sub-title="detail.activated ? '可用于 MILP 和模型训练' : '点击激活场景运行图'"
              />
            </el-card>
            <div class="stats-grid">
              <el-card shadow="never"><el-statistic title="站点数量" :value="contextStats?.station_count ?? '-'" /></el-card>
              <el-card shadow="never"><el-statistic title="车次数量" :value="contextStats?.train_count ?? '-'" /></el-card>
              <el-card shadow="never"><el-statistic title="总里程" :value="contextStats?.total_mileage ?? '-'" /></el-card>
              <el-card shadow="never"><el-statistic title="事件节点数" :value="contextStats?.event_node_count ?? '-'" /></el-card>
              <el-card shadow="never"><el-statistic title="区间节点数" :value="contextStats?.section_node_count ?? '-'" /></el-card>
              <el-card shadow="never"><el-statistic title="预留" value="-" /></el-card>
            </div>
          </div>

          <el-card v-if="detail.timetable" class="scenario-section" shadow="never">
            <template #header>场景扰动运行图</template>
            <TimetableChart
              :rows="detail.timetable.plan.rows"
              :station-order="detail.timetable.station_order"
              :disturbances="detail.timetable.disturbances"
              :title="`${scenarioId} 场景扰动运行图`"
            />
          </el-card>
          <el-empty v-else class="scenario-section" description="场景未激活，暂无运行图" />
        </template>
      </div>
    </div>

    <el-dialog v-model="activateDialogVisible" title="激活场景" width="620px">
      <el-form label-width="120px">
        <el-form-item label="时刻表">
          <el-space wrap>
            <el-link :href="downloadUrl('timetable.xlsx')" target="_blank">timetable.xlsx</el-link>
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
            <el-link :href="downloadUrl('mileage.xlsx')" target="_blank">mileage.xlsx</el-link>
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
        <el-button type="primary" :loading="activating" @click="activateScenario">确定激活</el-button>
      </template>
    </el-dialog>
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

@media (max-width: 900px) {
  .scenario-detail-grid {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
