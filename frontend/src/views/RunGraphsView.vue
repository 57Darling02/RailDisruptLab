<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { UploadFile, UploadUserFile } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'

import { api, formatApiError } from '@/api/client'
import TimetableChart from '@/components/TimetableChart.vue'
import { ChartNoAxesCombined, Delete, Refresh } from '@/icons'
import type { RunGraphSet, RunGraphSummary, RunGraphTimetableState, Task } from '@/types'

const props = defineProps<{
  projectId: string
  runGraphSets: RunGraphSet[]
  busy?: boolean
}>()

const emit = defineEmits<{
  refreshProject: []
  taskSubmitted: [task: Task]
}>()

const selectedSetId = ref('')
const runGraphs = ref<RunGraphSummary[]>([])
const loading = ref(false)
const setDialogVisible = ref(false)
const graphDialogVisible = ref(false)
const newSetId = ref('')
const newGraphId = ref('')
const timetableFiles = ref<UploadUserFile[]>([])
const mileageFiles = ref<UploadUserFile[]>([])
const timetableFile = ref<File | null>(null)
const mileageFile = ref<File | null>(null)
const overwriteGraph = ref(false)
const activeOperation = ref('')
const previewDialogVisible = ref(false)
const previewGraph = ref<RunGraphSummary | null>(null)
const previewTimetable = ref<RunGraphTimetableState | null>(null)
const previewLoading = ref(false)
const previewErrorMessage = ref('')
let requestSeq = 0
let previewRequestSeq = 0

const selectedSet = computed(
  () => props.runGraphSets.find((item) => item.run_graph_set_id === selectedSetId.value) ?? null,
)
const pending = computed(() => props.busy || Boolean(activeOperation.value))

watch(
  () => props.runGraphSets.map((item) => item.run_graph_set_id).join('\u0000'),
  () => {
    if (!selectedSetId.value || !props.runGraphSets.some((item) => item.run_graph_set_id === selectedSetId.value)) {
      selectedSetId.value = props.runGraphSets[0]?.run_graph_set_id ?? ''
    }
  },
  { immediate: true },
)

watch(
  () => [props.projectId, selectedSetId.value].join('\u0000'),
  () => {
    void loadRunGraphs()
  },
  { immediate: true },
)

async function loadRunGraphs() {
  const projectId = props.projectId
  const setId = selectedSetId.value
  const seq = requestSeq + 1
  requestSeq = seq
  if (!projectId || !setId) {
    runGraphs.value = []
    return
  }
  loading.value = true
  try {
    const result = await api.listRunGraphs(projectId, setId)
    if (seq === requestSeq && projectId === props.projectId && setId === selectedSetId.value) {
      runGraphs.value = result
    }
  } catch (error) {
    if (seq === requestSeq) {
      runGraphs.value = []
      ElMessage.error(formatApiError(error))
    }
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

async function runAction(label: string, action: () => Promise<void>, successMessage = label) {
  if (pending.value) return
  activeOperation.value = label
  try {
    await action()
    ElMessage.success(successMessage)
  } catch (error) {
    ElMessage.error(formatApiError(error))
  } finally {
    activeOperation.value = ''
  }
}

async function createRunGraphSet() {
  const setId = newSetId.value.trim()
  if (!setId) {
    ElMessage.warning('请填写运行图分类 ID。')
    return
  }
  await runAction('新增运行图分类', async () => {
    await api.createRunGraphSet(props.projectId, setId)
    selectedSetId.value = setId
    newSetId.value = ''
    setDialogVisible.value = false
    emit('refreshProject')
  })
}

async function deleteRunGraphSet(setId: string) {
  if (!setId) return
  try {
    await ElMessageBox.confirm(`确认删除运行图分类 ${setId}？`, '删除运行图分类', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await runAction('删除运行图分类', async () => {
    await api.deleteRunGraphSet(props.projectId, setId)
    if (selectedSetId.value === setId) selectedSetId.value = ''
    emit('refreshProject')
  })
}

function openGraphDialog() {
  if (!selectedSetId.value) {
    ElMessage.warning('请先选择或新增运行图分类。')
    return
  }
  newGraphId.value = ''
  timetableFiles.value = []
  mileageFiles.value = []
  timetableFile.value = null
  mileageFile.value = null
  overwriteGraph.value = false
  graphDialogVisible.value = true
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

async function createRunGraph() {
  const setId = selectedSetId.value
  const graphId = newGraphId.value.trim()
  if (!setId || !graphId) {
    ElMessage.warning('请填写运行图 ID。')
    return
  }
  if (!timetableFile.value || !mileageFile.value) {
    ElMessage.warning('请上传时刻表和里程表。')
    return
  }
  const timetable = timetableFile.value
  const mileage = mileageFile.value
  await runAction('构建运行图', async () => {
    const response = await api.createRunGraph(
      props.projectId,
      setId,
      graphId,
      timetable,
      mileage,
      overwriteGraph.value,
    )
    graphDialogVisible.value = false
    emit('taskSubmitted', response.task)
  }, '构建运行图任务已提交')
}

async function deleteRunGraph(graph: RunGraphSummary) {
  try {
    await ElMessageBox.confirm(
      `确认删除运行图 ${graph.run_graph_set_id} / ${graph.run_graph_id}？`,
      '删除运行图',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await runAction('删除运行图', async () => {
    await api.deleteRunGraph(props.projectId, graph.run_graph_set_id, graph.run_graph_id)
    await loadRunGraphs()
    emit('refreshProject')
  })
}

async function openPreviewDialog(graph: RunGraphSummary) {
  previewDialogVisible.value = true
  previewGraph.value = graph
  previewTimetable.value = null
  previewErrorMessage.value = ''
  const seq = previewRequestSeq + 1
  previewRequestSeq = seq
  previewLoading.value = true
  try {
    const result = await api.readRunGraphTimetable(props.projectId, graph.run_graph_set_id, graph.run_graph_id)
    if (seq === previewRequestSeq) previewTimetable.value = result
  } catch (error) {
    if (seq === previewRequestSeq) {
      previewTimetable.value = null
      previewErrorMessage.value = formatApiError(error)
    }
  } finally {
    if (seq === previewRequestSeq) previewLoading.value = false
  }
}

function closePreviewDialog() {
  previewRequestSeq += 1
  previewDialogVisible.value = false
  previewLoading.value = false
  previewTimetable.value = null
  previewErrorMessage.value = ''
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-card shadow="never">
        <div class="run-graph-toolbar">
          <div class="run-graph-toolbar-main">
            <span class="control-label">运行图分类：</span>
            <el-select
              v-model="selectedSetId"
              class="full-width"
              filterable
              placeholder="选择运行图分类"
              :disabled="pending"
              :loading="loading"
              no-data-text="暂无数据"
            >
              <el-option
                v-for="item in runGraphSets"
                :key="item.run_graph_set_id"
                :label="`${item.run_graph_set_id} (${item.run_graph_count})`"
                :value="item.run_graph_set_id"
              />
              <template #empty>暂无数据</template>
            </el-select>
          </div>
          <el-space>
            <el-button :disabled="pending" @click="setDialogVisible = true">新增分类</el-button>
            <el-button :disabled="pending || !selectedSetId" @click="deleteRunGraphSet(selectedSetId)">删除分类</el-button>
            <el-button
              type="primary"
              :icon="Refresh"
              :loading-icon="Refresh"
              :loading="loading"
              :disabled="pending || !selectedSetId"
              @click="loadRunGraphs"
            >
              加载
            </el-button>
          </el-space>
        </div>
      </el-card>

      <div v-if="!runGraphSets.length" class="primary-empty-panel">
        <el-empty :image-size="120">
          <template #description>
            <div class="primary-empty-title">暂无线路运行图</div>
          </template>
          <el-button type="primary" size="large" :disabled="pending" @click="setDialogVisible = true">
            新增运行图分类
          </el-button>
        </el-empty>
      </div>

      <el-card v-else shadow="never">
        <template #header>
          <div class="card-header">
            <span>{{ selectedSet?.run_graph_set_id || '线路运行图' }}</span>
            <el-button type="primary" :disabled="pending || !selectedSetId" @click="openGraphDialog">
              上传运行图
            </el-button>
          </div>
        </template>
        <div class="run-graph-table-wrap">
          <el-table
            v-loading="loading"
            class="run-graph-table"
            :data="runGraphs"
            :fit="true"
            table-layout="fixed"
            empty-text="暂无运行图"
          >
            <el-table-column prop="run_graph_id" label="运行图" show-overflow-tooltip />
            <el-table-column label="摘要" width="190" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.station_count }} 站 · {{ row.train_count }} 车次 · {{ row.section_node_count }} 区间
              </template>
            </el-table-column>
            <el-table-column prop="context_sha256" label="Context SHA256" width="180" show-overflow-tooltip />
            <el-table-column prop="created_at" label="创建时间" width="150" show-overflow-tooltip />
            <el-table-column label="操作" width="88" align="right">
              <template #default="{ row }">
                <el-space :size="6">
                  <el-tooltip content="查看运行图" placement="top">
                    <el-button
                      link
                      type="primary"
                      :icon="ChartNoAxesCombined"
                      :disabled="pending"
                      @click="openPreviewDialog(row)"
                    />
                  </el-tooltip>
                  <el-tooltip content="删除运行图" placement="top">
                    <el-button link type="danger" :icon="Delete" :disabled="pending" @click="deleteRunGraph(row)" />
                  </el-tooltip>
                </el-space>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="setDialogVisible" title="新增运行图分类" width="420px">
      <el-input
        v-model="newSetId"
        placeholder="例如 京沪高铁"
        :disabled="pending"
        @keyup.enter="createRunGraphSet"
      />
      <template #footer>
        <el-button :disabled="pending" @click="setDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="activeOperation === '新增运行图分类'" :disabled="pending" @click="createRunGraphSet">
          确定
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="graphDialogVisible" title="上传运行图" width="560px">
      <el-form label-width="120px">
        <el-form-item label="运行图分类">
          <el-input :model-value="selectedSetId" disabled />
        </el-form-item>
        <el-form-item label="运行图 ID">
          <el-input v-model="newGraphId" placeholder="例如 日常 / 周末 / 节假日" :disabled="pending" />
        </el-form-item>
        <el-form-item label="时刻表">
          <el-upload
            v-model:file-list="timetableFiles"
            :auto-upload="false"
            :limit="1"
            :on-change="setTimetableFile"
            :on-exceed="warnSingleFile"
            :disabled="pending"
          >
            <el-button :disabled="pending">选择时刻表</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="里程表">
          <el-upload
            v-model:file-list="mileageFiles"
            :auto-upload="false"
            :limit="1"
            :on-change="setMileageFile"
            :on-exceed="warnSingleFile"
            :disabled="pending"
          >
            <el-button :disabled="pending">选择里程表</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="覆盖同名">
          <el-switch v-model="overwriteGraph" :disabled="pending" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="pending" @click="graphDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="activeOperation === '构建运行图'" :disabled="pending" @click="createRunGraph">
          构建运行图
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="previewDialogVisible"
      :title="previewGraph ? `${previewGraph.run_graph_set_id} / ${previewGraph.run_graph_id}` : '查看运行图'"
      width="86vw"
      top="5vh"
      destroy-on-close
      @closed="closePreviewDialog"
    >
      <el-alert
        v-if="previewErrorMessage"
        type="error"
        :title="previewErrorMessage"
        show-icon
        :closable="false"
      />
      <div v-else v-loading="previewLoading" element-loading-text="正在加载运行图...">
        <TimetableChart
          v-if="previewTimetable"
          :rows="previewTimetable.plan.rows"
          :station-order="previewTimetable.station_order"
          :title="`${previewGraph?.run_graph_id ?? '运行图'}`"
        />
        <el-empty v-else description="暂无可展示的运行图" :image-size="72" />
      </div>
    </el-dialog>
  </section>
</template>

<style scoped>
.run-graph-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.run-graph-toolbar-main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.run-graph-table-wrap {
  width: 100%;
  overflow-x: hidden;
}

.run-graph-table {
  width: 100%;
}

@media (max-width: 720px) {
  .run-graph-toolbar,
  .run-graph-toolbar-main {
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .run-graph-toolbar-main {
    flex-direction: column;
  }

  .run-graph-table-wrap {
    overflow-x: auto;
  }

  .run-graph-table {
    min-width: 720px;
  }
}
</style>
