<script setup lang="ts">
import type { DatasetSummary, ModelSummary, Task } from '@/types'

defineProps<{
  selectedProjectId: string
  scenarioSetCount: number
  datasets: DatasetSummary[]
  models: ModelSummary[]
  tasks: Task[]
  runningTaskCount: number
  doneTaskCount: number
  failedTaskCount: number
  busy?: boolean
}>()

defineEmits<{
  refreshTasks: []
}>()
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>项目资源</span>
          </div>
        </template>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-statistic title="扰动场景类别" :value="scenarioSetCount" />
          </el-col>
          <el-col :span="8">
            <el-statistic title="MILP实例类别" :value="datasets.length" />
          </el-col>
          <el-col :span="8">
            <el-statistic title="扰动生成模型数量" :value="models.length" />
          </el-col>
        </el-row>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>任务总览</span>
            <el-button :disabled="busy" @click="$emit('refreshTasks')">刷新</el-button>
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
