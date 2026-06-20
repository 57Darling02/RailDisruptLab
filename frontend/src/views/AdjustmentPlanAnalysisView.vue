<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api, formatApiError, isApiConflict } from '@/api/client'
import AdjustmentPlanPicker from '@/components/AdjustmentPlanPicker.vue'
import ChartPanel from '@/components/ChartPanel.vue'
import { Refresh } from '@/icons'
import type {
  AdjustmentPlanRef,
  AdjustmentPlanSolveAnalysis,
  AdjustmentPlanSummary,
  ScenarioSet,
} from '@/types'
import {
  buildAblationMetricCards,
  buildComparisonDeltaChartOption,
  buildComparisonSummaryRows,
  buildMetricMeanChartOption,
  buildSolvePlanRows,
  formatMetricValue,
  formatPercent,
  formatSignedMetricValue,
  roleLabel,
  solveMetricLabel,
} from '@/views/ablation-analysis'

const props = defineProps<{
  selectedProjectId: string
  scenarioSets: ScenarioSet[]
  busy?: boolean
}>()

defineEmits<{
  createScenarioSet: []
}>()

const baselinePlan = ref<AdjustmentPlanRef | null>(null)
const candidatePlans = ref<AdjustmentPlanRef[]>([])
const discoveredPlans = ref<AdjustmentPlanSummary[]>([])
const analysis = ref<AdjustmentPlanSolveAnalysis | null>(null)
const analysisLoading = ref(false)
const errorMessage = ref('')
const conflictMessage = ref('')
let analysisRequestSeq = 0

const selectedPlans = computed(() => [
  ...dedupePlanRefs([
    baselinePlan.value,
    ...candidatePlans.value,
  ]),
])
const candidatePlanRefs = computed(() =>
  selectedPlans.value.filter((plan) => planKey(plan) !== (baselinePlan.value ? planKey(baselinePlan.value) : '')),
)
const selectedPlanCount = computed(() => selectedPlans.value.length)
const canLoadAnalysis = computed(() =>
  Boolean(props.selectedProjectId && baselinePlan.value && selectedPlans.value.length),
)
const loading = computed(() => analysisLoading.value)
const metricCards = computed(() => buildAblationMetricCards(analysis.value, selectedPlanCount.value))
const solvePlanRows = computed(() => buildSolvePlanRows(analysis.value))
const comparisonRows = computed(() => buildComparisonSummaryRows(analysis.value))
const metricMeanChartOption = computed(() => buildMetricMeanChartOption(analysis.value))
const comparisonDeltaChartOption = computed(() => buildComparisonDeltaChartOption(comparisonRows.value))

watch(
  () => props.selectedProjectId,
  () => {
    baselinePlan.value = null
    candidatePlans.value = []
    discoveredPlans.value = []
    analysis.value = null
    errorMessage.value = ''
    conflictMessage.value = ''
  },
)

watch(
  () => baselinePlan.value ? planKey(baselinePlan.value) : '',
  (baselineKey) => {
    if (!baselineKey) return
    candidatePlans.value = candidatePlans.value.filter((plan) => planKey(plan) !== baselineKey)
  },
)

watch(
  () => selectedPlans.value.map(planKey).join('\u0000'),
  () => {
    if (canLoadAnalysis.value) {
      void loadSolveAnalysis()
    } else {
      analysis.value = null
      errorMessage.value = ''
      conflictMessage.value = ''
    }
  },
)

function mergeDiscoveredPlans(plans: AdjustmentPlanSummary[], options: { fillBaseline?: boolean } = {}) {
  const byKey = new Map(discoveredPlans.value.map((plan) => [planKey(plan), plan]))
  for (const plan of plans) byKey.set(planKey(plan), plan)
  discoveredPlans.value = [...byKey.values()]
  if (options.fillBaseline && !baselinePlan.value) {
    baselinePlan.value = preferredBaselinePlan(plans)
  }
}

async function loadSolveAnalysis() {
  const projectId = props.selectedProjectId
  const plans = selectedPlans.value
  const seq = analysisRequestSeq + 1
  analysisRequestSeq = seq

  if (!projectId || !plans.length) {
    analysis.value = null
    analysisLoading.value = false
    return
  }

  errorMessage.value = ''
  conflictMessage.value = ''
  analysisLoading.value = true
  try {
    const result = await api.readProjectAdjustmentPlanSolveAnalysis(projectId, plans)
    if (
      seq !== analysisRequestSeq ||
      projectId !== props.selectedProjectId ||
      plans.map(planKey).join('\u0000') !== selectedPlans.value.map(planKey).join('\u0000')
    ) {
      return
    }
    analysis.value = result
  } catch (error) {
    if (seq !== analysisRequestSeq || projectId !== props.selectedProjectId) return
    analysis.value = null
    if (isApiConflict(error)) {
      conflictMessage.value = formatApiError(error)
    } else {
      errorMessage.value = formatApiError(error)
    }
  } finally {
    if (seq === analysisRequestSeq && projectId === props.selectedProjectId) {
      analysisLoading.value = false
    }
  }
}

function refreshAnalysis() {
  if (!baselinePlan.value) {
    ElMessage.warning('请先选择基准调整计划。')
    return
  }
  void loadSolveAnalysis()
}

function planLabel(plan: AdjustmentPlanRef | null) {
  return plan ? planKey(plan) : '未选择'
}

function preferredBaselinePlan(plans: AdjustmentPlanSummary[]) {
  const plan = plans.find((item) => item.solved_count > 0) ?? plans[0]
  return plan ? toPlanRef(plan) : null
}

function dedupePlanRefs(plans: Array<AdjustmentPlanRef | null>) {
  const result: AdjustmentPlanRef[] = []
  const seen = new Set<string>()
  for (const plan of plans) {
    if (!plan) continue
    const key = planKey(plan)
    if (seen.has(key)) continue
    result.push(plan)
    seen.add(key)
  }
  return result
}

function toPlanRef(plan: AdjustmentPlanSummary): AdjustmentPlanRef {
  return { scenario_set_id: plan.scenario_set_id, plan_id: plan.plan_id }
}

function planKey(plan: Pick<AdjustmentPlanRef, 'scenario_set_id' | 'plan_id'>) {
  return `${plan.scenario_set_id}/${plan.plan_id}`
}

</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>调整计划分析</span>
            <el-button
              :icon="Refresh"
              :loading-icon="Refresh"
              :loading="loading"
              :disabled="busy || !baselinePlan"
              @click="refreshAnalysis"
            >
              刷新
            </el-button>
          </div>
        </template>

        <div class="plan-analysis-controls">
          <AdjustmentPlanPicker
            :model-value="baselinePlan"
            :project-id="selectedProjectId"
            :scenario-sets="scenarioSets"
            label="基准调整计划"
            :disabled="busy"
            :excluded-keys="candidatePlanRefs.map(planKey)"
            @update:model-value="baselinePlan = Array.isArray($event) ? null : $event"
            @loaded="(plans) => mergeDiscoveredPlans(plans, { fillBaseline: true })"
          />

          <AdjustmentPlanPicker
            :model-value="candidatePlans"
            :project-id="selectedProjectId"
            :scenario-sets="scenarioSets"
            label="候选调整计划"
            multiple
            :disabled="busy"
            :excluded-keys="baselinePlan ? [planKey(baselinePlan)] : []"
            @update:model-value="candidatePlans = Array.isArray($event) ? $event : []"
            @loaded="mergeDiscoveredPlans"
          />
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

      <el-empty v-else-if="!baselinePlan" description="请选择基准调整计划" />

      <el-card
        v-else
        shadow="never"
        v-loading="loading"
        element-loading-text="正在读取调整计划对照..."
      >
        <template #header>
          <div class="card-header">
            <span>调整计划对照</span>
            <span class="muted-text">基准：{{ planLabel(baselinePlan) }}</span>
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

        <el-alert
          v-if="!candidatePlanRefs.length"
          class="analysis-alert"
          type="info"
          show-icon
          :closable="false"
          title="可继续添加候选调整计划进行对照。"
        />

        <template v-else>
          <div class="analysis-metric-grid">
            <div v-for="item in metricCards" :key="item.key" class="analysis-metric">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small>{{ item.detail }}</small>
            </div>
          </div>

          <el-alert
            v-for="warning in analysis?.warnings ?? []"
            :key="`${warning.type}-${warning.plan_id}-${warning.message}`"
            class="analysis-alert"
            type="warning"
            show-icon
            :closable="false"
            :title="warning.message"
          />

          <el-tabs class="analysis-tabs">
            <el-tab-pane label="计划矩阵">
              <el-scrollbar class="table-scroll" max-height="360px">
                <el-table :data="solvePlanRows" empty-text="暂无求解分析数据">
                  <el-table-column prop="plan_label" label="调整计划" min-width="220" show-overflow-tooltip />
                  <el-table-column label="角色" width="86">
                    <template #default="{ row }">
                      <el-tag :type="row.role === 'baseline' ? 'success' : 'primary'" size="small">
                        {{ roleLabel(row.role) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="求解进度" width="130">
                    <template #default="{ row }">
                      {{ row.solved_count }}/{{ row.case_count }} ({{ formatPercent(row.solved_ratio) }})
                    </template>
                  </el-table-column>
                  <el-table-column label="目标均值" width="120">
                    <template #default="{ row }">{{ formatMetricValue(row.metrics.objective, 'objective') }}</template>
                  </el-table-column>
                  <el-table-column label="MIP Gap" width="110">
                    <template #default="{ row }">{{ formatMetricValue(row.metrics.mip_gap, 'mip_gap') }}</template>
                  </el-table-column>
                  <el-table-column label="求解耗时" width="120">
                    <template #default="{ row }">{{ formatMetricValue(row.metrics.duration_sec, 'duration_sec') }}</template>
                  </el-table-column>
                  <el-table-column prop="config_status" label="求解器配置" width="120" />
                  <el-table-column prop="solver_config_text" label="参数" min-width="220" show-overflow-tooltip />
                  <el-table-column prop="status_text" label="状态分布" min-width="160" show-overflow-tooltip />
                </el-table>
              </el-scrollbar>
            </el-tab-pane>

            <el-tab-pane label="指标对比">
              <div class="analysis-chart-grid">
                <ChartPanel
                  :option="metricMeanChartOption"
                  filename="adjustment-plan-metric-means"
                  height="300px"
                />
                <ChartPanel
                  :option="comparisonDeltaChartOption"
                  filename="adjustment-plan-relative-delta"
                  height="300px"
                />
              </div>
            </el-tab-pane>

            <el-tab-pane label="差异明细">
              <el-scrollbar class="table-scroll" max-height="420px">
                <el-table :data="comparisonRows" empty-text="至少选择一个候选计划后显示差异">
                  <el-table-column prop="plan_label" label="候选计划" min-width="220" show-overflow-tooltip />
                  <el-table-column prop="metric_label" label="指标" width="120">
                    <template #default="{ row }">{{ solveMetricLabel(analysis, row.metric) }}</template>
                  </el-table-column>
                  <el-table-column prop="case_count" label="对齐场景" width="96" />
                  <el-table-column label="基准均值" width="120">
                    <template #default="{ row }">{{ formatMetricValue(row.baseline_mean, row.metric) }}</template>
                  </el-table-column>
                  <el-table-column label="候选均值" width="120">
                    <template #default="{ row }">{{ formatMetricValue(row.value_mean, row.metric) }}</template>
                  </el-table-column>
                  <el-table-column label="平均差值" width="120">
                    <template #default="{ row }">{{ formatSignedMetricValue(row.signed_delta_mean, row.metric) }}</template>
                  </el-table-column>
                  <el-table-column label="平均绝对误差" width="140">
                    <template #default="{ row }">{{ formatMetricValue(row.absolute_error_mean, row.metric) }}</template>
                  </el-table-column>
                  <el-table-column label="平均相对误差" width="140">
                    <template #default="{ row }">{{ formatPercent(row.relative_error_mean) }}</template>
                  </el-table-column>
                </el-table>
              </el-scrollbar>
            </el-tab-pane>
          </el-tabs>
        </template>
      </el-card>
    </div>
  </section>
</template>

<style scoped>
.plan-analysis-controls {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 14px;
}

</style>
