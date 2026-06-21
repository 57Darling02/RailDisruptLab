<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api, formatApiError } from '@/api/client'
import type { RunGraphReference, RunGraphSet, RunGraphSummary } from '@/types'

type CascaderOption = {
  value: string
  label: string
  leaf?: boolean
  children?: CascaderOption[]
}

type LazyNode = {
  value?: unknown
  level: number
}

const props = withDefaults(
  defineProps<{
    modelValue: RunGraphReference | null
    projectId: string
    disabled?: boolean
    placeholder?: string
  }>(),
  {
    disabled: false,
    placeholder: '选择运行图',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: RunGraphReference | null]
  change: [value: RunGraphReference | null, summary: RunGraphSummary | null]
}>()

const loading = ref(false)
const errorMessage = ref('')
const runGraphSets = ref<RunGraphSet[]>([])
const graphsBySet = ref<Record<string, RunGraphSummary[]>>({})
let requestSeq = 0

const selectedValue = computed(() =>
  props.modelValue ? [props.modelValue.set_id, props.modelValue.graph_id] : [],
)
const options = computed<CascaderOption[]>(() =>
  runGraphSets.value.map((item) => ({
    value: item.run_graph_set_id,
    label: `${item.run_graph_set_id} (${item.run_graph_count ?? 0})`,
    leaf: false,
    children: graphsBySet.value[item.run_graph_set_id]?.map(runGraphToOption),
  })),
)
const cascaderProps = {
  lazy: true,
  lazyLoad: loadChildren,
  emitPath: true,
  value: 'value',
  label: 'label',
  children: 'children',
}

watch(
  () => props.projectId,
  () => {
    runGraphSets.value = []
    graphsBySet.value = {}
    if (props.projectId) void loadRunGraphSets()
  },
  { immediate: true },
)

watch(
  () => [props.projectId, props.modelValue?.set_id ?? '', props.modelValue?.graph_id ?? ''].join('\u0000'),
  () => {
    if (props.projectId && props.modelValue?.set_id) {
      void ensureSelectedGraphLoaded()
    }
  },
  { immediate: true },
)

async function loadRunGraphSets() {
  if (!props.projectId) return []
  const seq = requestSeq + 1
  requestSeq = seq
  loading.value = true
  errorMessage.value = ''
  try {
    const sets = await api.listRunGraphSets(props.projectId)
    if (seq !== requestSeq) return []
    runGraphSets.value = sets
    return sets
  } catch (error) {
    if (seq === requestSeq) {
      runGraphSets.value = []
      errorMessage.value = formatApiError(error)
    }
    return []
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

async function loadChildren(node: LazyNode, resolve: (data: CascaderOption[]) => void) {
  const runGraphSetId = String(node.value || '')
  if (!runGraphSetId || node.level !== 1) {
    resolve([])
    return
  }
  const graphs = await loadRunGraphs(runGraphSetId)
  resolve(graphs.map(runGraphToOption))
}

async function loadRunGraphs(runGraphSetId: string) {
  if (!props.projectId || !runGraphSetId) return []
  const existing = graphsBySet.value[runGraphSetId]
  if (existing) return existing

  errorMessage.value = ''
  try {
    const graphs = await api.listRunGraphs(props.projectId, runGraphSetId)
    graphsBySet.value = { ...graphsBySet.value, [runGraphSetId]: graphs }
    return graphs
  } catch (error) {
    errorMessage.value = formatApiError(error)
    return []
  }
}

async function ensureSelectedGraphLoaded() {
  if (!props.modelValue) return
  if (!runGraphSets.value.length) await loadRunGraphSets()
  await loadRunGraphs(props.modelValue.set_id)
}

function updatePath(value: unknown) {
  const path = Array.isArray(value) ? value.map(String) : []
  const [setId, graphId] = path
  if (!setId || !graphId) {
    emit('update:modelValue', null)
    emit('change', null, null)
    return
  }
  const summary = graphsBySet.value[setId]?.find((item) => item.run_graph_id === graphId) ?? null
  if (!summary) {
    emit('update:modelValue', null)
    emit('change', null, null)
    return
  }
  const runGraph = {
    set_id: summary.run_graph_set_id,
    graph_id: summary.run_graph_id,
    context_sha256: summary.context_sha256,
  }
  emit('update:modelValue', runGraph)
  emit('change', runGraph, summary)
}

function runGraphToOption(summary: RunGraphSummary): CascaderOption {
  return {
    value: summary.run_graph_id,
    label: `${summary.run_graph_id} (${summary.station_count || '-'} 站 · ${summary.train_count || '-'} 车次)`,
    leaf: true,
  }
}
</script>

<template>
  <div class="run-graph-selector">
    <el-cascader
      :model-value="selectedValue"
      :options="options"
      :props="cascaderProps"
      :placeholder="placeholder"
      :disabled="disabled"
      :loading="loading"
      clearable
      filterable
      class="full-width"
      :show-all-levels="true"
      @update:model-value="updatePath"
    >
      <template #empty>暂无数据</template>
    </el-cascader>
    <el-text v-if="errorMessage" class="run-graph-error" type="danger" size="small">
      {{ errorMessage }}
    </el-text>
  </div>
</template>

<style scoped>
.run-graph-selector {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.run-graph-error {
  line-height: 1.3;
}
</style>
