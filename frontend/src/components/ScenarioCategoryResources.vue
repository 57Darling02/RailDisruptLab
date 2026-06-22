<script setup lang="ts">
import type { ScenarioVisualizationItem } from '@/types'

defineProps<{
  scenarios: ScenarioVisualizationItem[]
  busy?: boolean
}>()

const emit = defineEmits<{
  createScenario: []
  simulateScenario: []
  validateScenarios: []
  deleteScenario: [scenarioId: string]
  viewScenario: [scenarioId: string]
}>()

function scenarioTagType(category: string) {
  if (category === 'empty') return 'info'
  if (category === 'mixed') return 'warning'
  return 'success'
}

function scenarioTypeLabel(item: ScenarioVisualizationItem) {
  if (item.yaml_status === 'invalid') return '文件错误'
  const labels: Record<string, string> = {
    empty: '空场景',
    delay: '纯晚点',
    speed_limit: '纯限速',
    interruption: '纯中断',
    mixed: '混合',
  }
  return labels[item.category] ?? item.category
}

function validationTagType(item: ScenarioVisualizationItem) {
  const status = item.validation_state?.status
  if (item.yaml_status === 'invalid' || status === 'invalid') return 'danger'
  if (status === 'valid') return 'success'
  return 'info'
}

function validationLabel(item: ScenarioVisualizationItem) {
  if (item.yaml_status === 'invalid') return '文件错误'
  const status = item.validation_state?.status
  if (status === 'valid') return '校验通过'
  if (status === 'stale') return '需重新校验'
  if (status === 'pending') return '未校验'
  return '校验失败'
}

function validationReason(item: ScenarioVisualizationItem) {
  if (item.yaml_reason) return item.yaml_reason
  return item.validation_state?.reason || '-'
}
</script>

<template>
  <el-card class="scenario-section scenario-resource-card" shadow="never">
    <template #header>
      <div class="card-header">
        <span>场景资源</span>
        <el-space>
          <el-button :disabled="busy || !scenarios.length" @click="emit('validateScenarios')">批量校验</el-button>
          <el-button type="primary" :disabled="busy" @click="emit('createScenario')">新增场景</el-button>
          <el-button type="primary" :disabled="busy" @click="emit('simulateScenario')">模拟场景</el-button>
        </el-space>
      </div>
    </template>
    <el-table
      class="scenario-resource-table"
      :data="scenarios"
      height="100%"
      table-layout="fixed"
      empty-text="暂无场景"
    >
      <el-table-column prop="scenario_id" label="场景 ID" show-overflow-tooltip />
      <el-table-column label="场景文件" width="110">
        <template #default="{ row }">
          <el-button link type="primary" :disabled="busy" @click="emit('viewScenario', row.scenario_id)">
            查看详情
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag :type="scenarioTagType(row.category)" size="small">{{ scenarioTypeLabel(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="校验" width="120">
        <template #default="{ row }">
          <el-tag :type="validationTagType(row)" size="small">{{ validationLabel(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="晚点" width="90">
        <template #default="{ row }">{{ row.counts.delay }}</template>
      </el-table-column>
      <el-table-column label="限速" width="90">
        <template #default="{ row }">{{ row.counts.speed_limit }}</template>
      </el-table-column>
      <el-table-column label="中断" width="90">
        <template #default="{ row }">{{ row.counts.interruption }}</template>
      </el-table-column>
      <el-table-column label="原因" width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ validationReason(row) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button link type="danger" :disabled="busy" @click="emit('deleteScenario', row.scenario_id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.scenario-section {
  margin-top: 16px;
}
</style>
