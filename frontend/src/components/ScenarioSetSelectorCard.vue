<script setup lang="ts">
import { computed } from 'vue'

import EntityToolbar from '@/components/EntityToolbar.vue'
import { Refresh } from '@/icons'
import type { ResourceOption, ScenarioSet } from '@/types'

const props = defineProps<{
  selectedScenarioSetId: string
  loadedScenarioSetId: string
  scenarioSets: ScenarioSet[]
  scenarioSetOptions: ResourceOption[]
  resourceLoading: boolean
  detailLoading?: boolean
  busy?: boolean
}>()

const emit = defineEmits<{
  'update:selectedScenarioSetId': [value: string]
  reloadScenarioSets: [visible: boolean]
  searchScenarioSets: [query: string]
  createScenarioSet: []
  loadScenarioSet: []
  deleteScenarioSet: [scenarioSetId: string]
}>()

const reloadingSelection = computed(
  () => Boolean(props.selectedScenarioSetId) &&
    props.selectedScenarioSetId === props.loadedScenarioSetId &&
    Boolean(props.detailLoading),
)
</script>

<template>
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
    @update:model-value="emit('update:selectedScenarioSetId', $event)"
    @visible-change="emit('reloadScenarioSets', $event)"
    @search="emit('searchScenarioSets', $event)"
    @add="emit('createScenarioSet')"
    @delete="emit('deleteScenarioSet', $event)"
  >
    <template #actions>
      <el-button
        type="primary"
        :icon="Refresh"
        :loading-icon="Refresh"
        :loading="reloadingSelection"
        :disabled="busy || !selectedScenarioSetId"
        @click="emit('loadScenarioSet')"
      >
        加载
      </el-button>
    </template>
  </EntityToolbar>
</template>
