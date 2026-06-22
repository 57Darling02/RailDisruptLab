<script setup lang="ts">
import ScenarioCategoryDetail from '@/components/ScenarioCategoryDetail.vue'
import ScenarioSetSelectorCard from '@/components/ScenarioSetSelectorCard.vue'
import { Refresh } from '@/icons'
import type { ResourceOption, ScenarioSet } from '@/types'

withDefaults(
  defineProps<{
    selectedProjectId: string
    selectedScenarioSetId: string
    loadedScenarioSetId: string
    scenarioSets: ScenarioSet[]
    scenarioSetOptions: ResourceOption[]
    resourceLoading: boolean
    detailLoading?: boolean
    busy?: boolean
    section?: 'overview' | 'resources' | 'all'
  }>(),
  {
    section: 'all',
  },
)

defineEmits<{
  'update:selectedScenarioSetId': [value: string]
  reloadScenarioSets: [visible: boolean]
  searchScenarioSets: [query: string]
  createScenarioSet: []
  loadScenarioSet: []
  deleteScenarioSet: [scenarioSetId: string]
  createScenario: []
  simulateScenario: []
  validateScenarios: []
  deleteScenario: [scenarioId: string]
  viewScenario: [scenarioId: string]
  detailLoadingChange: [loading: boolean]
}>()
</script>

<template>
  <section
    class="page-layout scenario-sets-view"
    :class="{ 'is-resource-list-layout': section === 'resources' && scenarioSets.length > 0 && !!loadedScenarioSetId }"
  >
    <div class="page-stack scenario-sets-stack">
      <ScenarioSetSelectorCard
        :selected-scenario-set-id="selectedScenarioSetId"
        :loaded-scenario-set-id="loadedScenarioSetId"
        :scenario-sets="scenarioSets"
        :scenario-set-options="scenarioSetOptions"
        :resource-loading="resourceLoading"
        :detail-loading="detailLoading"
        :busy="busy"
        @update:selected-scenario-set-id="$emit('update:selectedScenarioSetId', $event)"
        @reload-scenario-sets="$emit('reloadScenarioSets', $event)"
        @search-scenario-sets="$emit('searchScenarioSets', $event)"
        @create-scenario-set="$emit('createScenarioSet')"
        @load-scenario-set="$emit('loadScenarioSet')"
        @delete-scenario-set="$emit('deleteScenarioSet', $event)"
      />

      <div v-if="!scenarioSets.length" class="primary-empty-panel">
        <el-empty :image-size="120">
          <template #description>
            <div class="primary-empty-title">暂无场景分类资源</div>
          </template>
          <el-button type="primary" size="large" :disabled="busy" @click="$emit('createScenarioSet')">
            新增场景分类
          </el-button>
        </el-empty>
      </div>

      <ScenarioCategoryDetail
        v-else-if="selectedProjectId && loadedScenarioSetId"
        :project-id="selectedProjectId"
        :scenario-set-id="loadedScenarioSetId"
        :section="section"
        :busy="busy"
        @create-scenario="$emit('createScenario')"
        @simulate-scenario="$emit('simulateScenario')"
        @validate-scenarios="$emit('validateScenarios')"
        @delete-scenario="$emit('deleteScenario', $event)"
        @view-scenario="$emit('viewScenario', $event)"
        @loading-change="$emit('detailLoadingChange', $event)"
      />
      <el-empty v-else description="请选择场景分类">
        <el-space>
          <el-button
            type="primary"
            :icon="Refresh"
            :loading-icon="Refresh"
            :loading="detailLoading"
            :disabled="busy || !selectedScenarioSetId"
            @click="$emit('loadScenarioSet')"
          >
            加载
          </el-button>
          <el-button :disabled="busy || !selectedScenarioSetId" @click="$emit('createScenario')">新增场景</el-button>
        </el-space>
      </el-empty>
    </div>
  </section>
</template>

<style scoped>
@media (min-width: 1101px) {
  .scenario-sets-view.is-resource-list-layout {
    height: calc(100vh - 92px);
    min-height: 0;
    overflow: hidden;
  }

  .scenario-sets-view.is-resource-list-layout .scenario-sets-stack {
    height: 100%;
    min-height: 0;
  }
}
</style>
