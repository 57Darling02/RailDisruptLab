<script setup lang="ts">
import { computed } from 'vue'

import ScenarioCategoryDetail from '@/components/ScenarioCategoryDetail.vue'
import EntityToolbar from '@/components/EntityToolbar.vue'
import type { ResourceOption, ScenarioSet } from '@/types'

const props = defineProps<{
  selectedProjectId: string
  selectedScenarioSetId: string
  loadedScenarioSetId: string
  scenarioSets: ScenarioSet[]
  scenarioSetOptions: ResourceOption[]
  resourceLoading: boolean
  detailLoading?: boolean
  busy?: boolean
}>()

const reloadingSelection = computed(
  () => Boolean(props.selectedScenarioSetId) && props.selectedScenarioSetId === props.loadedScenarioSetId && Boolean(props.detailLoading),
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
  deleteScenario: [scenarioId: string]
  viewScenario: [scenarioId: string]
  detailLoadingChange: [loading: boolean]
}>()
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <EntityToolbar
        label="场景分类"
        :model-value="selectedScenarioSetId"
        :options="scenarioSetOptions"
        :loading="resourceLoading"
        placeholder="选择场景分类"
        add-label="新增场景分类"
        delete-label="删除场景分类"
        add-in-dropdown
        :busy="busy"
        @update:model-value="$emit('update:selectedScenarioSetId', $event)"
        @visible-change="$emit('reloadScenarioSets', $event)"
        @search="$emit('searchScenarioSets', $event)"
        @add="$emit('createScenarioSet')"
        @delete="$emit('deleteScenarioSet', $event)"
      >
        <template #actions>
          <el-button
            type="primary"
            :disabled="busy || !selectedScenarioSetId"
            :loading="reloadingSelection"
            @click="$emit('loadScenarioSet')"
          >
            重新加载
          </el-button>
        </template>
      </EntityToolbar>

      <el-empty v-if="!scenarioSets.length" description="暂无场景分类">
        <el-button type="primary" :disabled="busy" @click="$emit('createScenarioSet')">新增场景分类</el-button>
      </el-empty>

      <ScenarioCategoryDetail
        v-else-if="selectedProjectId && loadedScenarioSetId"
        :project-id="selectedProjectId"
        :scenario-set-id="loadedScenarioSetId"
        :busy="busy"
        @create-scenario="$emit('createScenario')"
        @simulate-scenario="$emit('simulateScenario')"
        @delete-scenario="$emit('deleteScenario', $event)"
        @view-scenario="$emit('viewScenario', $event)"
        @loading-change="$emit('detailLoadingChange', $event)"
      />
      <el-empty v-else description="请选择场景分类">
        <el-space>
          <el-button type="primary" :disabled="busy || !selectedScenarioSetId" @click="$emit('loadScenarioSet')">
            重新加载
          </el-button>
          <el-button :disabled="busy" @click="$emit('createScenario')">新增场景</el-button>
        </el-space>
      </el-empty>
    </div>
  </section>
</template>
