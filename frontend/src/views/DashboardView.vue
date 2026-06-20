<script setup lang="ts">
import type { ModelSummary, Task } from '@/types'

defineProps<{
  selectedProjectId: string
  scenarioSetCount: number
  adjustmentPlanCount: number
  models: ModelSummary[]
  tasks: Task[]
  runningTaskCount: number
  doneTaskCount: number
  failedTaskCount: number
  busy?: boolean
}>()

defineEmits<{
  createScenarioSet: []
  createPlan: []
  train: []
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
        <div v-if="!scenarioSetCount && !adjustmentPlanCount && !models.length" class="primary-empty-panel dashboard-empty-panel">
          <el-empty :image-size="120">
            <template #description>
              <div class="primary-empty-title">暂无项目资源</div>
            </template>
            <div class="dashboard-empty-actions">
              <el-button type="primary" size="large" :disabled="busy" @click="$emit('createScenarioSet')">
                新增场景分类
              </el-button>
              <el-button size="large" :disabled="busy" @click="$emit('createPlan')">
                构建调整计划
              </el-button>
              <el-button size="large" :disabled="busy" @click="$emit('train')">
                训练新模型
              </el-button>
            </div>
          </el-empty>
        </div>
        <el-row v-else :gutter="16">
          <el-col :span="8">
            <el-statistic title="扰动场景类别" :value="scenarioSetCount" />
          </el-col>
          <el-col :span="8">
            <el-statistic title="调整计划数量" :value="adjustmentPlanCount" />
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

<style scoped>
.dashboard-empty-panel {
  min-height: 320px;
}

.dashboard-empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
}
</style>
