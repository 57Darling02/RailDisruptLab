<script setup lang="ts">
import { api } from '@/api/client'
import TimetableChart from '@/components/TimetableChart.vue'
import type { UploadRequestOptions } from 'element-plus'
import type { DatasetSummary, FileState, ModelSummary, PlanTimetableState, Task } from '@/types'

defineProps<{
  selectedProjectId: string
  planTimetable: PlanTimetableState | null
  sourceFiles: FileState[]
  scenarioSetCount: number
  datasets: DatasetSummary[]
  models: ModelSummary[]
  originalGraphActive: boolean
  tasks: Task[]
  runningTaskCount: number
  doneTaskCount: number
  failedTaskCount: number
}>()

const emit = defineEmits<{
  prepare: []
  uploadSource: [options: UploadRequestOptions]
  deleteSource: [file: FileState]
  refreshTasks: []
}>()

function emitUploadSource(options: UploadRequestOptions) {
  emit('uploadSource', options)
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-row :gutter="16">
        <el-col :span="6">
          <el-card shadow="never">
            <el-statistic title="源文件" :value="sourceFiles.length" />
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <el-statistic title="场景集合" :value="scenarioSetCount" />
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <el-statistic title="数据集" :value="datasets.length" />
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <el-statistic title="模型" :value="models.length" />
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>原计划运行图状态</span>
          </div>
        </template>
        <el-result
          class="activation-result"
          :icon="originalGraphActive ? 'success' : 'warning'"
          :title="originalGraphActive ? '已激活' : '未激活'"
          :sub-title="
            originalGraphActive
              ? '原计划运行图已可用于后续实验流程。'
              : '请上传时刻表和里程表后激活原计划运行图。'
          "
        >
          <template v-if="!originalGraphActive" #extra>
            <el-button type="primary" @click="$emit('prepare')">激活</el-button>
          </template>
        </el-result>
      </el-card>

      <el-card v-if="originalGraphActive" shadow="never">
        <template #header>
          <div class="card-header">
            <span>原计划运行图</span>
          </div>
        </template>
        <TimetableChart
          :rows="planTimetable?.plan.rows ?? []"
          :station-order="planTimetable?.station_order ?? []"
          title="原计划运行图"
        />
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>源文件</span>
            <el-upload
              multiple
              :show-file-list="false"
              :http-request="emitUploadSource"
            >
              <el-button type="primary">上传</el-button>
            </el-upload>
          </div>
        </template>
        <el-scrollbar class="table-scroll" max-height="420px">
          <el-table :data="sourceFiles" empty-text="暂无源文件">
            <el-table-column prop="name" label="文件名" />
            <el-table-column prop="size_bytes" label="大小(bytes)" width="140" />
            <el-table-column label="操作" width="180">
              <template #default="{ row }">
                <el-link
                  type="primary"
                  :href="api.sourceDownloadUrl(selectedProjectId, row.name)"
                  target="_blank"
                  :underline="false"
                >
                  查看
                </el-link>
                <el-button link type="danger" @click="$emit('deleteSource', row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-scrollbar>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>任务总览</span>
            <el-button @click="$emit('refreshTasks')">刷新</el-button>
          </div>
        </template>
        <el-row :gutter="16">
          <el-col :span="6">
            <el-statistic title="全部任务" :value="tasks.length" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="运行/排队" :value="runningTaskCount" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="已完成" :value="doneTaskCount" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="失败/终止" :value="failedTaskCount" />
          </el-col>
        </el-row>
      </el-card>
    </div>
  </section>
</template>
