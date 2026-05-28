<script setup lang="ts">
import type { ArtifactGroup } from '@/views/types'
import type { DatasetSummary } from '@/types'

defineProps<{
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
  refreshArtifacts: []
  buildDataset: []
  solveAll: []
  solveCase: [caseId: string]
  exportAllTimetables: []
  exportTimetable: [caseId: string]
  openTimetable: [group: ArtifactGroup]
}>()
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-card shadow="never">
        <div class="toolbar-row">
          <div class="inline-control">
            <span>MILP 数据集：</span>
            <el-select
              :model-value="selectedDatasetId"
              filterable
              placeholder="选择 MILP 数据集"
              class="toolbar-select"
              @update:model-value="$emit('update:selectedDatasetId', $event)"
              @visible-change="$emit('reloadDatasets', $event)"
            >
              <el-option
                v-for="item in datasets"
                :key="item.dataset_id"
                :label="item.dataset_id"
                :value="item.dataset_id"
              />
            </el-select>
            <el-button circle @click="$emit('createDataset')">+</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>MILP 数据集信息</span>
            <el-button @click="$emit('refreshArtifacts')">刷新</el-button>
          </div>
        </template>
        <el-empty v-if="!selectedDatasetId" description="请选择或新增 MILP 数据集" />
        <template v-else>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="MILP 数据集 ID">
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
  </section>
</template>
