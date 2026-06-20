<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api, ApiError } from '@/api/client'
import type {
  AdjustmentPlanRef,
  AdjustmentPlanSummary,
  ScenarioSet,
} from '@/types'

type CascaderOption = {
  value: string
  label: string
  leaf?: boolean
  disabled?: boolean
  children?: CascaderOption[]
}

type LazyNode = {
  value?: unknown
  level: number
}

const props = defineProps<{
  modelValue: AdjustmentPlanRef | AdjustmentPlanRef[] | null
  projectId: string
  scenarioSets: ScenarioSet[]
  label: string
  multiple?: boolean
  disabled?: boolean
  excludedKeys?: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: AdjustmentPlanRef | AdjustmentPlanRef[] | null]
  loaded: [plans: AdjustmentPlanSummary[]]
}>()

const plansByScenarioSet = ref<Record<string, AdjustmentPlanSummary[]>>({})
const selectedValue = computed(() => props.multiple
  ? selectedRefs.value.map((ref) => [ref.scenario_set_id, ref.plan_id])
  : selectedRefs.value[0]
    ? [selectedRefs.value[0].scenario_set_id, selectedRefs.value[0].plan_id]
    : [],
)
const selectedRefs = computed(() => {
  if (!props.modelValue) return []
  return Array.isArray(props.modelValue) ? props.modelValue : [props.modelValue]
})
const options = computed<CascaderOption[]>(() =>
  props.scenarioSets.map((scenarioSet) => {
    const plans = plansByScenarioSet.value[scenarioSet.scenario_set_id]
    return {
      value: scenarioSet.scenario_set_id,
      label: `${scenarioSet.scenario_set_id} (${scenarioSet.plan_count ?? 0})`,
      leaf: false,
      children: plans?.map((plan) => ({
        value: plan.plan_id,
        label: `${plan.plan_id} (${plan.solved_count}/${plan.case_count})`,
        leaf: true,
        disabled: props.excludedKeys?.includes(planKey(plan.scenario_set_id, plan.plan_id)),
      })),
    }
  }),
)
const cascaderProps = computed(() => ({
  lazy: true,
  lazyLoad: loadChildren,
  checkStrictly: false,
  emitPath: true,
  multiple: props.multiple,
  value: 'value',
  label: 'label',
  children: 'children',
  disabled: 'disabled',
}))

watch(
  () => selectedRefs.value.map((ref) => ref.scenario_set_id).join('\u0000'),
  () => {
    for (const scenarioSetId of new Set(selectedRefs.value.map((ref) => ref.scenario_set_id))) {
      if (scenarioSetId && !plansByScenarioSet.value[scenarioSetId]) {
        void loadPlans(scenarioSetId)
      }
    }
  },
  { immediate: true },
)

async function loadChildren(node: LazyNode, resolve: (data: CascaderOption[]) => void) {
  const scenarioSetId = String(node.value || '')
  if (!scenarioSetId || node.level !== 1) {
    resolve([])
    return
  }
  const plans = await loadPlans(scenarioSetId)
  resolve(planOptions(scenarioSetId, plans))
}

async function loadPlans(scenarioSetId: string) {
  if (!props.projectId || !scenarioSetId) return []
  const existing = plansByScenarioSet.value[scenarioSetId]
  if (existing) return existing

  try {
    const plans = await api.listAdjustmentPlans(props.projectId, scenarioSetId)
    plansByScenarioSet.value = { ...plansByScenarioSet.value, [scenarioSetId]: plans }
    emit('loaded', plans)
    return plans
  } catch (error) {
    ElMessage.error(formatError(error))
    return []
  }
}

function updatePath(value: unknown) {
  if (props.multiple) {
    const refs = (Array.isArray(value) ? value : [])
      .map((path) => Array.isArray(path) ? path.map(String) : [])
      .map(pathToRef)
      .filter((ref): ref is AdjustmentPlanRef => Boolean(ref))
    emit('update:modelValue', refs)
    return
  }
  const path = Array.isArray(value) ? value.map(String) : []
  emit('update:modelValue', pathToRef(path))
}

function pathToRef(path: string[]) {
  const [scenarioSetId, planId] = path
  return scenarioSetId && planId
    ? { scenario_set_id: scenarioSetId, plan_id: planId }
    : null
}

function planOptions(scenarioSetId: string, plans: AdjustmentPlanSummary[]): CascaderOption[] {
  return plans.map((plan) => ({
    value: plan.plan_id,
    label: `${plan.plan_id} (${plan.solved_count}/${plan.case_count})`,
    leaf: true,
    disabled: props.excludedKeys?.includes(planKey(scenarioSetId, plan.plan_id)),
  }))
}

function planKey(scenarioSetId: string, planId: string) {
  return `${scenarioSetId}/${planId}`
}

function formatError(error: unknown) {
  if (error instanceof ApiError) return `${error.status}: ${error.message}`
  if (error instanceof Error) return error.message
  return String(error)
}
</script>

<template>
  <div class="analysis-field">
    <span class="control-label">{{ label }}</span>
    <el-cascader
      :model-value="selectedValue"
      :options="options"
      :props="cascaderProps"
      :disabled="disabled"
      clearable
      filterable
      class="full-width"
      placeholder="选择场景分类 / 调整计划"
      :show-all-levels="true"
      @update:model-value="updatePath"
    />
  </div>
</template>

<style scoped>
.analysis-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}
</style>
