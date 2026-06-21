<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api, formatApiError, isApiConflict } from '@/api/client'
import ScenarioCategoryOverview from '@/components/ScenarioCategoryOverview.vue'
import ScenarioCategoryResources from '@/components/ScenarioCategoryResources.vue'
import type {
  RunGraphReference,
  RunGraphTimetableState,
  ScenarioSetVisualization,
} from '@/types'
import {
  buildRunGraphUsages,
  runGraphKey,
  sameRunGraph,
} from '@/components/scenario-category'

const props = defineProps<{
  projectId: string
  scenarioSetId: string
  section?: 'overview' | 'resources' | 'all'
  busy?: boolean
}>()

const emit = defineEmits<{
  createScenario: []
  simulateScenario: []
  deleteScenario: [scenarioId: string]
  viewScenario: [scenarioId: string]
  loadingChange: [loading: boolean]
}>()

const loading = ref(false)
const errorMessage = ref('')
const conflictMessage = ref('')
const analysis = ref<ScenarioSetVisualization | null>(null)
const runGraphTimetable = ref<RunGraphTimetableState | null>(null)
const runGraphLoading = ref(false)
const runGraphErrorMessage = ref('')
const selectedRunGraph = ref<RunGraphReference | null>(null)
let requestSeq = 0
let runGraphRequestSeq = 0

const visibleSection = computed(() => props.section ?? 'all')
const showOverview = computed(() => visibleSection.value === 'all' || visibleSection.value === 'overview')
const showResources = computed(() => visibleSection.value === 'all' || visibleSection.value === 'resources')
const runGraphUsages = computed(() => buildRunGraphUsages(analysis.value?.scenarios ?? []))

watch(loading, (value) => {
  emit('loadingChange', value)
}, { immediate: true })

onBeforeUnmount(() => {
  emit('loadingChange', false)
})

watch(
  () => [props.projectId, props.scenarioSetId].join('\u0000'),
  () => {
    void loadDetail()
  },
  { immediate: true },
)

watch(
  runGraphUsages,
  (items) => {
    if (!items.length) {
      selectedRunGraph.value = null
      runGraphTimetable.value = null
      runGraphErrorMessage.value = ''
      return
    }
    if (!selectedRunGraph.value || !items.some((item) => sameRunGraph(item.runGraph, selectedRunGraph.value))) {
      const first = items[0]
      if (first) selectedRunGraph.value = { ...first.runGraph }
    }
  },
  { immediate: true },
)

watch(
  () => [props.projectId, selectedRunGraph.value ? runGraphKey(selectedRunGraph.value) : ''].join('\u0000'),
  () => {
    void loadSelectedRunGraphTimetable()
  },
  { immediate: true },
)

async function loadDetail() {
  if (!props.projectId || !props.scenarioSetId) {
    analysis.value = null
    loading.value = false
    return
  }
  const seq = requestSeq + 1
  requestSeq = seq
  loading.value = true
  errorMessage.value = ''
  conflictMessage.value = ''
  try {
    const data = await api.readScenarioSetVisualization(props.projectId, props.scenarioSetId)
    if (seq !== requestSeq) return
    analysis.value = data
  } catch (error) {
    if (seq !== requestSeq) return
    analysis.value = null
    if (isApiConflict(error)) {
      conflictMessage.value = formatApiError(error)
      ElMessage.warning(conflictMessage.value)
    } else {
      errorMessage.value = formatApiError(error)
      ElMessage.error(errorMessage.value)
    }
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

async function loadSelectedRunGraphTimetable() {
  const runGraph = selectedRunGraph.value
  if (!props.projectId || !runGraph) {
    runGraphTimetable.value = null
    runGraphLoading.value = false
    runGraphErrorMessage.value = ''
    return
  }
  const seq = runGraphRequestSeq + 1
  runGraphRequestSeq = seq
  runGraphLoading.value = true
  runGraphErrorMessage.value = ''
  try {
    const data = await api.readRunGraphTimetable(props.projectId, runGraph.set_id, runGraph.graph_id)
    if (seq !== runGraphRequestSeq) return
    runGraphTimetable.value = data
  } catch (error) {
    if (seq !== runGraphRequestSeq) return
    runGraphTimetable.value = null
    runGraphErrorMessage.value = formatApiError(error)
  } finally {
    if (seq === runGraphRequestSeq) runGraphLoading.value = false
  }
}

function selectRunGraph(runGraph: RunGraphReference | null) {
  selectedRunGraph.value = runGraph ? { ...runGraph } : null
}

defineExpose({ reload: loadDetail })
</script>

<template>
  <div
    v-loading="loading"
    class="scenario-category-detail"
    :class="{ 'is-resource-list': visibleSection === 'resources' }"
    element-loading-text="正在加载场景分类数据..."
  >
    <el-result
      v-if="conflictMessage"
      icon="warning"
      title="场景分类正在更新"
      :sub-title="conflictMessage"
    >
      <template #extra>
        <el-button :disabled="busy" @click="loadDetail">稍后重试</el-button>
      </template>
    </el-result>

    <el-result v-else-if="errorMessage" icon="error" title="场景分类加载失败" :sub-title="errorMessage">
      <template #extra>
        <el-button :disabled="busy" @click="loadDetail">重试</el-button>
      </template>
    </el-result>

    <template v-else-if="analysis">
      <ScenarioCategoryOverview
        v-if="showOverview"
        :analysis="analysis"
        :run-graph-usages="runGraphUsages"
        :selected-run-graph="selectedRunGraph"
        :run-graph-timetable="runGraphTimetable"
        :run-graph-loading="runGraphLoading"
        :run-graph-error-message="runGraphErrorMessage"
        @select-run-graph="selectRunGraph"
      />

      <ScenarioCategoryResources
        v-if="showResources"
        :scenarios="analysis.scenarios"
        :busy="busy"
        @create-scenario="emit('createScenario')"
        @simulate-scenario="emit('simulateScenario')"
        @delete-scenario="emit('deleteScenario', $event)"
        @view-scenario="emit('viewScenario', $event)"
      />
    </template>
  </div>
</template>

<style scoped>
.scenario-category-detail {
  min-height: 260px;
}

@media (min-width: 1101px) {
  .scenario-category-detail.is-resource-list {
    display: flex;
    min-height: 0;
    flex: 1 1 auto;
    flex-direction: column;
  }

  .scenario-category-detail.is-resource-list :deep(.scenario-resource-card) {
    display: flex;
    min-height: 0;
    flex: 1 1 auto;
    flex-direction: column;
    margin-top: 0;
  }

  .scenario-category-detail.is-resource-list :deep(.scenario-resource-card .el-card__body) {
    min-height: 0;
    flex: 1 1 auto;
    overflow: hidden;
  }

  .scenario-category-detail.is-resource-list :deep(.scenario-resource-table) {
    height: 100%;
  }
}
</style>
