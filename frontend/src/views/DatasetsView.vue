<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import { api, ApiError } from '@/api/client'
import EntityToolbar from '@/components/EntityToolbar.vue'
import { formatBytes, groupArtifactsByCase } from '@/views/types'
import type { ArtifactSummary, DatasetSummary, ResourceOption } from '@/types'

const props = defineProps<{
  selectedProjectId: string
  selectedDatasetId: string
  selectedDataset: DatasetSummary | null
  datasets: DatasetSummary[]
  datasetOptions: ResourceOption[]
  resourceLoading: boolean
  busy?: boolean
}>()

defineEmits<{
  'update:selectedDatasetId': [value: string]
  reloadDatasets: [visible: boolean]
  searchDatasets: [query: string]
  createDataset: []
  deleteDataset: [datasetId: string]
  buildDataset: []
  solveAll: []
  solveCase: [caseId: string]
  exportAllTimetables: []
  exportTimetable: [caseId: string]
  openTimetable: [caseId: string]
}>()

const artifacts = ref<ArtifactSummary[]>([])
const loading = ref(false)
const errorMessage = ref('')
let requestSeq = 0

const artifactGroups = computed(() => groupArtifactsByCase(artifacts.value))

watch(
  () => [
    props.selectedProjectId,
    props.selectedDatasetId,
    props.selectedDataset?.case_count ?? 0,
    props.selectedDataset?.built_count ?? 0,
    props.selectedDataset?.solved_count ?? 0,
    props.selectedDataset?.timetable_count ?? 0,
  ] as const,
  () => {
    void loadArtifacts()
  },
  { immediate: true },
)

async function loadArtifacts() {
  const projectId = props.selectedProjectId
  const datasetId = props.selectedDatasetId
  const seq = requestSeq + 1
  requestSeq = seq
  errorMessage.value = ''

  if (!projectId || !datasetId) {
    artifacts.value = []
    loading.value = false
    return
  }

  loading.value = true
  try {
    const result = await api.listArtifacts(projectId, datasetId)
    if (seq !== requestSeq || projectId !== props.selectedProjectId || datasetId !== props.selectedDatasetId) {
      return
    }
    artifacts.value = result
  } catch (error) {
    if (seq !== requestSeq || projectId !== props.selectedProjectId || datasetId !== props.selectedDatasetId) {
      return
    }
    artifacts.value = []
    errorMessage.value = formatError(error)
  } finally {
    if (seq === requestSeq && projectId === props.selectedProjectId && datasetId === props.selectedDatasetId) {
      loading.value = false
    }
  }
}

function formatError(error: unknown) {
  if (error instanceof ApiError) return `${error.status}: ${error.message}`
  if (error instanceof Error) return error.message
  return String(error)
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <EntityToolbar
        label="MILP 实例集"
        :model-value="selectedDatasetId"
        :options="datasetOptions"
        :loading="resourceLoading"
        placeholder="选择 MILP 实例集"
        delete-label="删除 MILP 实例集"
        :busy="busy"
        @update:model-value="$emit('update:selectedDatasetId', $event)"
        @visible-change="$emit('reloadDatasets', $event)"
        @search="$emit('searchDatasets', $event)"
        @add="$emit('createDataset')"
        @delete="$emit('deleteDataset', $event)"
      />

      <div v-if="!datasets.length" class="primary-empty-panel">
        <el-empty :image-size="120">
          <template #description>
            <div class="primary-empty-title">暂无 MILP 实例集资源</div>
          </template>
          <el-button type="primary" size="large" :disabled="busy" @click="$emit('createDataset')">
            构建 MILP 实例集
          </el-button>
        </el-empty>
      </div>

      <div
        v-else
        v-loading="loading"
        class="page-stack"
        element-loading-text="正在加载 MILP 实例集数据..."
      >
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>MILP 实例集概览</span>
              <el-button
                :icon="Refresh"
                :disabled="busy || !selectedDatasetId"
                :loading="loading"
                @click="loadArtifacts"
              >
                刷新
              </el-button>
            </div>
          </template>
          <el-empty v-if="!selectedDatasetId" description="请选择或构建 MILP 实例集" />
          <template v-else>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="MILP 实例集 ID">
                {{ selectedDatasetId }}
              </el-descriptions-item>
              <el-descriptions-item label="场景数">
                {{ selectedDataset?.case_count ?? 0 }}
              </el-descriptions-item>
              <el-descriptions-item label="已求解">
                {{ selectedDataset?.solved_count ?? 0 }} / {{ selectedDataset?.case_count ?? 0 }}
              </el-descriptions-item>
              <el-descriptions-item label="已导出时刻表">
                {{ selectedDataset?.timetable_count ?? 0 }} / {{ selectedDataset?.case_count ?? 0 }}
              </el-descriptions-item>
              <el-descriptions-item label="产物目录" :span="2">
                {{ selectedDataset?.root ?? '尚未创建产物目录' }}
              </el-descriptions-item>
            </el-descriptions>
          </template>
        </el-card>

        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>实例资源</span>
              <div class="scenario-actions">
                <span class="muted-text">{{ artifactGroups.length }} 个实例</span>
                <el-button :disabled="!selectedDatasetId || busy" @click="$emit('buildDataset')">
                  构建/重建
                </el-button>
                <el-button :disabled="!selectedDatasetId || busy" @click="$emit('solveAll')">
                  全部求解
                </el-button>
                <el-button :disabled="!selectedDatasetId || busy" @click="$emit('exportAllTimetables')">
                  全部导出时刻表
                </el-button>
              </div>
            </div>
          </template>
          <el-result v-if="errorMessage" icon="error" title="实例资源加载失败" :sub-title="errorMessage">
            <template #extra>
              <el-button type="primary" :icon="Refresh" :loading="loading" :disabled="busy" @click="loadArtifacts">
                重试
              </el-button>
            </template>
          </el-result>
          <el-scrollbar v-else class="table-scroll" max-height="420px">
            <el-table :data="artifactGroups" empty-text="暂无实例资源">
              <el-table-column prop="case_id" label="场景 ID" width="180" />
              <el-table-column label="总大小" width="120">
                <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
              </el-table-column>
              <el-table-column label="求解" min-width="260">
                <template #default="{ row }">
                  <el-space wrap>
                    <el-tag :type="row.has_lp ? 'success' : 'info'">
                      {{ row.has_lp ? 'LP 已构建' : 'LP 缺失' }}
                    </el-tag>
                    <el-tag :type="row.has_solution && row.has_solution_csv ? 'success' : 'info'">
                      {{ row.has_solution && row.has_solution_csv ? '解数据完整' : '未求解' }}
                    </el-tag>
                    <el-tag :type="row.has_timetable_data ? 'success' : 'info'">
                      {{ row.has_timetable_data ? '时刻表已生成' : '时刻表缺失' }}
                    </el-tag>
                  </el-space>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="220">
                <template #default="{ row }">
                  <el-button
                    link
                    type="primary"
                    :disabled="!row.has_lp || busy"
                    @click="$emit('solveCase', row.case_id)"
                  >
                    求解
                  </el-button>
                  <el-button
                    link
                    type="primary"
                    :disabled="!row.has_solution || busy"
                    @click="$emit('exportTimetable', row.case_id)"
                  >
                    导出时刻表
                  </el-button>
                  <el-button
                    link
                    type="primary"
                    :disabled="!row.has_timetable_data || busy"
                    @click="$emit('openTimetable', row.case_id)"
                  >
                    查看
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
