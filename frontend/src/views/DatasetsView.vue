<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import { api, ApiError } from '@/api/client'
import EntityToolbar from '@/components/EntityToolbar.vue'
import { formatBytes, groupArtifactsByCase } from '@/views/types'
import type { ArtifactSummary, DatasetDetail, DatasetSummary, ResourceOption } from '@/types'

const props = defineProps<{
  selectedProjectId: string
  selectedDatasetId: string
  loadedDatasetId: string
  loadedDataset: DatasetSummary | null
  datasets: DatasetSummary[]
  datasetOptions: ResourceOption[]
  resourceLoading: boolean
  detailLoading?: boolean
  busy?: boolean
}>()

const emit = defineEmits<{
  'update:selectedDatasetId': [value: string]
  reloadDatasets: [visible: boolean]
  searchDatasets: [query: string]
  createDataset: []
  loadDataset: []
  deleteDataset: [datasetId: string]
  buildDataset: []
  solveAll: []
  solveCase: [caseId: string]
  exportAllTimetables: []
  exportTimetable: [caseId: string]
  openTimetable: [caseId: string]
  loadingChange: [loading: boolean]
}>()

const artifacts = ref<ArtifactSummary[]>([])
const datasetDetail = ref<DatasetDetail | null>(null)
const loading = ref(false)
const errorMessage = ref('')
let requestSeq = 0

const artifactGroups = computed(() => groupArtifactsByCase(artifacts.value))
const loadedDetail = computed(() => datasetDetail.value)
const reloadingSelection = computed(
  () => Boolean(props.selectedDatasetId) && props.selectedDatasetId === props.loadedDatasetId && Boolean(props.detailLoading),
)
const buildConfig = computed(() => loadedDetail.value?.build_config ?? {})
const sourceScenarioSetText = computed(() => {
  const items = loadedDetail.value?.source_scenario_sets ?? []
  if (!items.length) return '未知'
  return items.map((item) => `${item.scenario_set_id} (${item.count})`).join('、')
})
const buildConfigStatusText = computed(() => {
  const detail = loadedDetail.value
  if (!detail || !detail.build_config_known_count) return '未知'
  if (detail.build_config_consistent) return '一致'
  return `不一致 (${detail.build_config_signatures.length} 组)`
})

watch(loading, (value) => {
  emit('loadingChange', value)
}, { immediate: true })

watch(
  () => [
    props.selectedProjectId,
    props.loadedDatasetId,
    props.loadedDataset?.case_count ?? 0,
    props.loadedDataset?.built_count ?? 0,
    props.loadedDataset?.solved_count ?? 0,
    props.loadedDataset?.timetable_count ?? 0,
  ] as const,
  () => {
    void loadArtifacts()
  },
  { immediate: true },
)

async function loadArtifacts() {
  const projectId = props.selectedProjectId
  const datasetId = props.loadedDatasetId
  const seq = requestSeq + 1
  requestSeq = seq
  errorMessage.value = ''

  if (!projectId || !datasetId) {
    artifacts.value = []
    datasetDetail.value = null
    loading.value = false
    return
  }

  loading.value = true
  try {
    const [detail, result] = await Promise.all([
      api.readDatasetDetail(projectId, datasetId),
      api.listArtifacts(projectId, datasetId),
    ])
    if (seq !== requestSeq || projectId !== props.selectedProjectId || datasetId !== props.loadedDatasetId) {
      return
    }
    datasetDetail.value = detail
    artifacts.value = result
  } catch (error) {
    if (seq !== requestSeq || projectId !== props.selectedProjectId || datasetId !== props.loadedDatasetId) {
      return
    }
    artifacts.value = []
    datasetDetail.value = null
    errorMessage.value = formatError(error)
  } finally {
    if (seq === requestSeq && projectId === props.selectedProjectId && datasetId === props.loadedDatasetId) {
      loading.value = false
    }
  }
}

function formatError(error: unknown) {
  if (error instanceof ApiError) return `${error.status}: ${error.message}`
  if (error instanceof Error) return error.message
  return String(error)
}

function configValue(key: string) {
  const value = buildConfig.value[key]
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value === null || value === undefined || value === '') return '未知'
  return String(value)
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
        add-label="构建 MILP 实例集"
        delete-label="删除 MILP 实例集"
        add-in-dropdown
        :busy="busy"
        @update:model-value="$emit('update:selectedDatasetId', $event)"
        @visible-change="$emit('reloadDatasets', $event)"
        @search="$emit('searchDatasets', $event)"
        @add="$emit('createDataset')"
        @delete="$emit('deleteDataset', $event)"
      >
        <template #actions>
          <el-button
            type="primary"
            :disabled="busy || !selectedDatasetId"
            :loading="reloadingSelection"
            @click="$emit('loadDataset')"
          >
            重新加载
          </el-button>
        </template>
      </EntityToolbar>

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

      <el-empty v-else-if="!loadedDatasetId" description="请选择 MILP 实例集">
        <el-button
          type="primary"
          :disabled="busy || !selectedDatasetId"
          :loading="reloadingSelection"
          @click="$emit('loadDataset')"
        >
          重新加载
        </el-button>
      </el-empty>

      <div v-else v-loading="loading" element-loading-text="正在加载 MILP 实例集数据...">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>实例分类：{{ loadedDatasetId }}</span>
              <div class="scenario-actions">
                <span class="muted-text">{{ artifactGroups.length }} 个实例</span>
                <el-button :icon="Refresh" :loading="loading" :disabled="busy" @click="loadArtifacts">
                  刷新
                </el-button>
                <el-button :disabled="busy" @click="$emit('buildDataset')">
                  构建/重建
                </el-button>
                <el-button :disabled="busy" @click="$emit('solveAll')">
                  全部求解
                </el-button>
                <el-button :disabled="busy" @click="$emit('exportAllTimetables')">
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
          <template v-else>
            <el-descriptions class="dataset-detail" :column="3" border>
              <el-descriptions-item label="来源场景分类">
                {{ sourceScenarioSetText }}
              </el-descriptions-item>
              <el-descriptions-item label="构建参数">
                {{ buildConfigStatusText }}
              </el-descriptions-item>
              <el-descriptions-item label="实例状态">
                {{ loadedDetail?.built_count ?? loadedDataset?.built_count ?? 0 }}/{{ loadedDetail?.case_count ?? loadedDataset?.case_count ?? 0 }} 已构建，
                {{ loadedDetail?.solved_count ?? loadedDataset?.solved_count ?? 0 }} 已求解，
                {{ loadedDetail?.timetable_count ?? loadedDataset?.timetable_count ?? 0 }} 已导出
              </el-descriptions-item>
              <el-descriptions-item label="目标函数">
                {{ configValue('objective_mode') }} / 权重 {{ configValue('objective_delay_weight') }}
              </el-descriptions-item>
              <el-descriptions-item label="取消列车">
                {{ configValue('cancellation_enabled') }} / 惩罚 {{ configValue('cancellation_penalty_weight') }}
              </el-descriptions-item>
              <el-descriptions-item label="到到/发发间隔">
                {{ configValue('arr_arr_headway_seconds') }}s / {{ configValue('dep_dep_headway_seconds') }}s
              </el-descriptions-item>
              <el-descriptions-item label="停站时间">
                {{ configValue('dwell_seconds_at_stops') }}s
              </el-descriptions-item>
              <el-descriptions-item label="Big-M">
                {{ configValue('big_m') }}
              </el-descriptions-item>
              <el-descriptions-item label="延误容差">
                {{ configValue('tolerance_delay_seconds') }}s
              </el-descriptions-item>
            </el-descriptions>

            <el-alert
              v-if="loadedDetail && loadedDetail.build_config_known_count && !loadedDetail.build_config_consistent"
              class="dataset-warning"
              type="warning"
              show-icon
              :closable="false"
              title="该实例分类内存在多组构建参数，请检查是否混合了不同构建批次。"
            />

            <el-scrollbar class="table-scroll" max-height="420px">
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
          </template>
        </el-card>
      </div>
    </div>
  </section>
</template>

<style scoped>
.dataset-detail {
  margin-bottom: 12px;
}

.dataset-warning {
  margin-bottom: 12px;
}
</style>
