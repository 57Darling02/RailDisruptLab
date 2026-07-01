<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api, formatApiError, isApiConflict } from '@/api/client'
import ChartPanel from '@/components/ChartPanel.vue'
import RemoteResourceSelect from '@/components/RemoteResourceSelect.vue'
import { Refresh } from '@/icons'
import type {
  ResourceOption,
  ScenarioSet,
  ScenarioSetVisualization,
} from '@/types'
import {
  DEFAULT_ABLATION_SCENARIO_LIMIT,
  buildScenarioMetricCards,
  buildScenarioStyleLegendRows,
  buildScenarioTypeCountChartOption,
  buildScenarioTypeTimeChartOption,
  mergeSelectedOptions,
  scenarioSetLabel,
  selectedScenarioSetIds,
  scenarioSetOptions as buildScenarioSetOptions,
  type AblationScenarioSelection,
} from '@/views/ablation-analysis'

const props = defineProps<{
  selectedProjectId: string
  scenarioSets: ScenarioSet[]
  scenarioSetOptions: ResourceOption[]
  scenarioSetResourceLoading: boolean
  busy?: boolean
}>()

defineEmits<{
  reloadScenarioSets: [visible: boolean]
  searchScenarioSets: [query: string]
  createScenarioSet: []
}>()

const visualizations = ref<ScenarioSetVisualization[]>([])
const loading = ref(false)
const errorMessage = ref('')
const conflictMessage = ref('')
const selection = ref<AblationScenarioSelection>({
  baselineScenarioSetId: '',
  candidateScenarioSetIds: [],
})
let requestSeq = 0

const localScenarioSetOptions = computed(() => buildScenarioSetOptions(props.scenarioSets))
const activeScenarioSetIds = computed(() => selectedScenarioSetIds(selection.value))
const selectOptions = computed(() =>
  mergeSelectedOptions(
    mergeSelectedOptions(props.scenarioSetOptions, localScenarioSetOptions.value),
    activeScenarioSetIds.value.map((value) => ({
      value,
      label: scenarioSetLabel(props.scenarioSets, value),
    })),
  ),
)
const candidateOptions = computed(() =>
  selectOptions.value.filter((item) => item.value !== selection.value.baselineScenarioSetId),
)
const styleLegendRows = computed(() => buildScenarioStyleLegendRows(visualizations.value))
const metricCards = computed(() =>
  buildScenarioMetricCards(visualizations.value, activeScenarioSetIds.value.length),
)
const typeTimeChartOption = computed(() => buildScenarioTypeTimeChartOption(visualizations.value))
const typeCountChartOption = computed(() => buildScenarioTypeCountChartOption(visualizations.value))
const canLoadAnalysis = computed(() => Boolean(props.selectedProjectId && activeScenarioSetIds.value.length))
const analysisButtonLabel = computed(() =>
  visualizations.value.length || errorMessage.value || conflictMessage.value ? '刷新' : '加载',
)

watch(
  () => props.scenarioSets.map((item) => item.scenario_set_id).join('\u0000'),
  () => {
    setSelection(pruneScenarioSelection(selection.value))
  },
  { immediate: true },
)

watch(
  () => [props.selectedProjectId, activeScenarioSetIds.value.join('\u0000')] as const,
  () => {
    requestSeq += 1
    loading.value = false
    visualizations.value = []
    errorMessage.value = ''
    conflictMessage.value = ''
  },
  { immediate: true },
)

async function loadAnalysis() {
  const projectId = props.selectedProjectId
  const scenarioSetIds = activeScenarioSetIds.value
  const seq = requestSeq + 1
  requestSeq = seq

  if (!projectId || !scenarioSetIds.length) {
    visualizations.value = []
    loading.value = false
    return
  }

  errorMessage.value = ''
  conflictMessage.value = ''
  loading.value = true
  try {
    const result = await Promise.all(
      scenarioSetIds.map((scenarioSetId) => api.readScenarioSetVisualization(projectId, scenarioSetId)),
    )
    if (
      seq !== requestSeq ||
      projectId !== props.selectedProjectId ||
      scenarioSetIds.join('\u0000') !== activeScenarioSetIds.value.join('\u0000')
    ) {
      return
    }
    visualizations.value = result
  } catch (error) {
    if (seq !== requestSeq || projectId !== props.selectedProjectId) return
    visualizations.value = []
    if (isApiConflict(error)) {
      conflictMessage.value = formatApiError(error)
    } else {
      errorMessage.value = formatApiError(error)
    }
  } finally {
    if (seq === requestSeq && projectId === props.selectedProjectId) {
      loading.value = false
    }
  }
}

function updateBaselineScenarioSetId(value: string | string[]) {
  const baselineScenarioSetId = String(value || '')
  setSelection({
    baselineScenarioSetId,
    candidateScenarioSetIds: limitCandidateScenarioSetIds(
      selection.value.candidateScenarioSetIds.filter((scenarioSetId) => scenarioSetId !== baselineScenarioSetId),
      baselineScenarioSetId,
    ),
  })
}

function updateCandidateScenarioSetIds(value: string | string[]) {
  setSelection({
    baselineScenarioSetId: selection.value.baselineScenarioSetId,
    candidateScenarioSetIds: limitCandidateScenarioSetIds(
      Array.isArray(value) ? value.map(String) : [String(value)].filter(Boolean),
      selection.value.baselineScenarioSetId,
    ),
  })
}

function refreshAnalysis() {
  if (canLoadAnalysis.value) {
    void loadAnalysis()
  } else {
    ElMessage.warning('请先选择基准场景分类。')
  }
}

function pruneScenarioSelection(current: AblationScenarioSelection): AblationScenarioSelection {
  const knownIds = new Set(props.scenarioSets.map((item) => item.scenario_set_id))
  if (!knownIds.size) return { baselineScenarioSetId: '', candidateScenarioSetIds: [] }
  const baselineScenarioSetId = knownIds.has(current.baselineScenarioSetId)
    ? current.baselineScenarioSetId
    : ''
  return {
    baselineScenarioSetId,
    candidateScenarioSetIds: limitCandidateScenarioSetIds(
      current.candidateScenarioSetIds.filter((scenarioSetId) => knownIds.has(scenarioSetId)),
      baselineScenarioSetId,
    ),
  }
}

function limitCandidateScenarioSetIds(values: string[], baselineScenarioSetId: string) {
  const candidateLimit = Math.max(0, DEFAULT_ABLATION_SCENARIO_LIMIT - 1)
  const result: string[] = []
  for (const value of values) {
    if (!value || value === baselineScenarioSetId || result.includes(value)) continue
    result.push(value)
    if (result.length >= candidateLimit) break
  }
  return result
}

function setSelection(next: AblationScenarioSelection) {
  if (
    next.baselineScenarioSetId === selection.value.baselineScenarioSetId &&
    next.candidateScenarioSetIds.join('\u0000') === selection.value.candidateScenarioSetIds.join('\u0000')
  ) {
    return
  }
  selection.value = next
}

</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>场景对照</span>
            <el-button
              :icon="Refresh"
              :loading-icon="Refresh"
              :loading="loading"
              :disabled="busy || !selection.baselineScenarioSetId"
              @click="refreshAnalysis"
            >
              {{ analysisButtonLabel }}
            </el-button>
          </div>
        </template>

        <div class="comparison-control-grid">
          <div class="analysis-field">
            <span class="control-label">基准场景分类</span>
            <RemoteResourceSelect
              :model-value="selection.baselineScenarioSetId"
              :options="selectOptions"
              placeholder="选择基准场景分类"
              :disabled="busy"
              :loading="scenarioSetResourceLoading"
              @update:model-value="updateBaselineScenarioSetId"
              @search="$emit('searchScenarioSets', $event)"
              @visible-change="$emit('reloadScenarioSets', $event)"
            />
          </div>
          <div class="analysis-field analysis-field-wide">
            <span class="control-label">候选场景分类</span>
            <RemoteResourceSelect
              :model-value="selection.candidateScenarioSetIds"
              :options="candidateOptions"
              multiple
              collapse-tags
              placeholder="选择候选场景分类"
              :disabled="busy || !selection.baselineScenarioSetId"
              :loading="scenarioSetResourceLoading"
              @update:model-value="updateCandidateScenarioSetIds"
              @search="$emit('searchScenarioSets', $event)"
              @visible-change="$emit('reloadScenarioSets', $event)"
            />
          </div>
        </div>
      </el-card>

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

      <el-empty v-else-if="!selection.baselineScenarioSetId" description="请选择基准场景分类" />

      <el-card
        v-else
        shadow="never"
        v-loading="loading"
        element-loading-text="正在读取场景对照..."
      >
        <template #header>
          <div class="card-header">
            <span>扰动分布对照</span>
            <span class="muted-text">图例可切换总数、晚点、限速、中断</span>
          </div>
        </template>

        <el-alert
          v-if="conflictMessage"
          class="analysis-alert"
          type="warning"
          show-icon
          :closable="false"
          :title="conflictMessage"
        />

        <el-alert
          v-else-if="errorMessage"
          class="analysis-alert"
          type="error"
          show-icon
          :closable="false"
          :title="errorMessage"
        />

        <template v-else>
          <div class="analysis-metric-grid">
            <div v-for="item in metricCards" :key="item.key" class="analysis-metric">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small>{{ item.detail }}</small>
            </div>
          </div>

          <div v-if="styleLegendRows.length" class="scenario-style-legend">
            <span v-for="item in styleLegendRows" :key="item.scenario_set_id" class="scenario-style-item">
              <span
                class="scenario-style-swatch"
                :class="[`line-${item.line_type}`, `symbol-${item.symbol}`]"
                aria-hidden="true"
              />
              <span class="scenario-style-text">
                {{ item.role_label }}：{{ item.scenario_set_id }}（{{ item.line_type_label }} / {{ item.symbol_label }}）
              </span>
            </span>
          </div>

          <div class="scenario-comparison-chart-grid">
            <ChartPanel
              :option="typeTimeChartOption"
              filename="scenario-comparison-type-time"
              height="380px"
            />
            <ChartPanel
              :option="typeCountChartOption"
              filename="scenario-comparison-type-count"
              height="360px"
            />
          </div>
        </template>
      </el-card>
    </div>
  </section>
</template>

<style scoped>
.comparison-control-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(320px, 1.4fr);
  gap: 14px;
  align-items: end;
}

.analysis-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.analysis-field-wide {
  min-width: 0;
}

.scenario-comparison-chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.scenario-style-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  margin: 14px 0 10px;
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.scenario-style-item {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 6px;
}

.scenario-style-swatch {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 14px;
  flex: 0 0 auto;
}

.scenario-style-swatch::before {
  width: 42px;
  border-top: 2px solid var(--el-text-color-primary);
  content: '';
}

.scenario-style-swatch.line-dashed::before {
  border-top-style: dashed;
}

.scenario-style-swatch.line-dotted::before {
  border-top-style: dotted;
}

.scenario-style-swatch::after {
  position: absolute;
  left: 17px;
  width: 8px;
  height: 8px;
  background: var(--el-text-color-primary);
  content: '';
}

.scenario-style-swatch.symbol-circle::after {
  border-radius: 50%;
}

.scenario-style-swatch.symbol-diamond::after {
  transform: rotate(45deg);
}

.scenario-style-swatch.symbol-triangle::after {
  width: 0;
  height: 0;
  border-right: 5px solid transparent;
  border-bottom: 9px solid var(--el-text-color-primary);
  border-left: 5px solid transparent;
  background: transparent;
}

.scenario-style-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 980px) {
  .comparison-control-grid {
    grid-template-columns: 1fr;
  }
}
</style>
