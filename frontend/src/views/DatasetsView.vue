<script setup lang="ts">
import { computed } from 'vue'

import EntityToolbar, { type EntityOption } from '@/components/EntityToolbar.vue'
import type { ArtifactGroup } from '@/views/types'
import type { DatasetSummary } from '@/types'

const props = defineProps<{
  selectedDatasetId: string
  selectedDataset: DatasetSummary | null
  datasets: DatasetSummary[]
  artifactGroups: ArtifactGroup[]
  formatBytes: (size: number) => string
}>()

defineEmits<{
  'update:selectedDatasetId': [value: string]
  reloadDatasets: [visible: boolean]
  createDataset: []
  deleteDataset: [datasetId: string]
  refreshArtifacts: []
  buildDataset: []
  solveAll: []
  solveCase: [caseId: string]
  exportAllTimetables: []
  exportTimetable: [caseId: string]
  openTimetable: [group: ArtifactGroup]
}>()

const datasetOptions = computed<EntityOption[]>(() =>
  props.datasets.map((item) => ({
    label: item.dataset_id,
    value: item.dataset_id,
  })),
)
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <EntityToolbar
        label="MILP 实例集"
        :model-value="selectedDatasetId"
        :options="datasetOptions"
        placeholder="选择 MILP 实例集"
        delete-label="删除 MILP 实例集"
        @update:model-value="$emit('update:selectedDatasetId', $event)"
        @visible-change="$emit('reloadDatasets', $event)"
        @add="$emit('createDataset')"
        @delete="$emit('deleteDataset', $event)"
      />

      <div v-if="!datasets.length" class="primary-empty-panel">
        <el-empty :image-size="120">
          <template #description>
            <div class="primary-empty-title">请先新建MILP实例集</div>
          </template>
          <el-button type="primary" size="large" @click="$emit('createDataset')">
            新建MILP实例集
          </el-button>
        </el-empty>
      </div>

      <div v-else class="page-stack">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>MILP 实例集信息</span>
            <el-button @click="$emit('refreshArtifacts')">刷新</el-button>
          </div>
        </template>
        <el-empty v-if="!selectedDatasetId" description="请选择或新增 MILP 实例集" />
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
            <span>构建产物</span>
            <div class="scenario-actions">
              <span class="muted-text">{{ artifactGroups.length }} 个实例</span>
              <el-button :disabled="!selectedDatasetId" @click="$emit('buildDataset')">
                从场景构建
              </el-button>
              <el-button :disabled="!selectedDatasetId" @click="$emit('solveAll')">
                全部求解
              </el-button>
              <el-button :disabled="!selectedDatasetId" @click="$emit('exportAllTimetables')">
                全部导出时刻表
              </el-button>
            </div>
          </div>
        </template>
        <el-scrollbar class="table-scroll" max-height="420px">
          <el-table :data="artifactGroups" empty-text="暂无构建产物">
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
                  :disabled="!row.has_lp"
                  @click="$emit('solveCase', row.case_id)"
                >
                  求解
                </el-button>
                <el-button
                  link
                  type="primary"
                  :disabled="!row.has_solution"
                  @click="$emit('exportTimetable', row.case_id)"
                >
                  导出时刻表
                </el-button>
                <el-button
                  link
                  type="primary"
                  :disabled="!row.has_timetable_data"
                  @click="$emit('openTimetable', row)"
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
