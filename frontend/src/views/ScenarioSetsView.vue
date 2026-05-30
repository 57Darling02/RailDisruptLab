<script setup lang="ts">
import ScenarioCategoryDetail from '@/components/ScenarioCategoryDetail.vue'
import EntityToolbar from '@/components/EntityToolbar.vue'
import type { ResourceOption, ScenarioResourceSummary, ScenarioSet } from '@/types'

defineProps<{
  selectedProjectId: string
  selectedScenarioSetId: string
  scenarioSets: ScenarioSet[]
  scenarioSummary: ScenarioResourceSummary | null
  scenarioSetOptions: ResourceOption[]
  resourceLoading: boolean
  busy?: boolean
}>()

defineEmits<{
  'update:selectedScenarioSetId': [value: string]
  reloadScenarioSets: [visible: boolean]
  searchScenarioSets: [query: string]
  createScenarioSet: []
  deleteScenarioSet: [scenarioSetId: string]
  createScenario: []
  simulateScenario: []
  deleteScenario: [scenarioId: string]
  viewScenario: [scenarioId: string]
  categoryLoaded: []
}>()
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-row :gutter="16">
        <el-col :xs="12" :sm="12" :md="6">
          <el-card shadow="never">
            <el-statistic title="总场景数" :value="scenarioSummary?.scenario_count ?? 0" />
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="12" :md="6">
          <el-card shadow="never">
            <el-statistic title="晚点事件" :value="scenarioSummary?.disturbance_counts.delay ?? 0" />
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="12" :md="6">
          <el-card shadow="never">
            <el-statistic title="限速事件" :value="scenarioSummary?.disturbance_counts.speed_limit ?? 0" />
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="12" :md="6">
          <el-card shadow="never">
            <el-statistic title="中断事件" :value="scenarioSummary?.disturbance_counts.interruption ?? 0" />
          </el-card>
        </el-col>
      </el-row>

      <EntityToolbar
        label="场景分类"
        :model-value="selectedScenarioSetId"
        :options="scenarioSetOptions"
        :loading="resourceLoading"
        placeholder="选择场景分类"
        delete-label="删除场景分类"
        :busy="busy"
        @update:model-value="$emit('update:selectedScenarioSetId', $event)"
        @visible-change="$emit('reloadScenarioSets', $event)"
        @search="$emit('searchScenarioSets', $event)"
        @add="$emit('createScenarioSet')"
        @delete="$emit('deleteScenarioSet', $event)"
      />

      <el-empty v-if="!scenarioSets.length" description="暂无场景分类">
        <el-space>
          <el-button type="primary" :disabled="busy" @click="$emit('createScenarioSet')">新增场景分类</el-button>
          <el-button :disabled="busy" @click="$emit('createScenario')">新增场景</el-button>
        </el-space>
      </el-empty>

      <ScenarioCategoryDetail
        v-else-if="selectedProjectId && selectedScenarioSetId"
        :project-id="selectedProjectId"
        :scenario-set-id="selectedScenarioSetId"
        :busy="busy"
        @create-scenario="$emit('createScenario')"
        @simulate-scenario="$emit('simulateScenario')"
        @delete-scenario="$emit('deleteScenario', $event)"
        @view-scenario="$emit('viewScenario', $event)"
        @loaded="$emit('categoryLoaded')"
      />
      <el-empty v-else description="请选择场景分类">
        <el-button type="primary" :disabled="busy" @click="$emit('createScenario')">新增场景</el-button>
      </el-empty>
    </div>
  </section>
</template>
