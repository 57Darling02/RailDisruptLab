<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api, formatApiError } from '@/api/client'
import EntityToolbar from '@/components/EntityToolbar.vue'
import ScenarioSetSelectorCard from '@/components/ScenarioSetSelectorCard.vue'
import { Refresh } from '@/icons'
import { formatBytes, groupArtifactsByCase } from '@/views/types'
import type {
  AdjustmentPlanDetail,
  AdjustmentPlanSummary,
  ArtifactSummary,
  ResourceOption,
  ScenarioSet,
} from '@/types'

const props = defineProps<{
  selectedProjectId: string
  selectedScenarioSetId: string
  loadedScenarioSetId: string
  scenarioSets: ScenarioSet[]
  scenarioSetOptions: ResourceOption[]
  scenarioSetResourceLoading: boolean
  scenarioSetDetailLoading?: boolean
  selectedPlanId: string
  loadedPlanId: string
  loadedPlan: AdjustmentPlanSummary | null
  adjustmentPlans: AdjustmentPlanSummary[]
  adjustmentPlanOptions: ResourceOption[]
  adjustmentPlanLoading: boolean
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
  'update:selectedPlanId': [value: string]
  reloadPlans: [visible: boolean]
  searchPlans: [query: string]
  createPlan: []
  loadPlan: []
  deletePlan: [planId: string]
  buildPlan: []
  solveAll: []
  solveCase: [caseId: string]
  openTimetable: [caseId: string]
  loadingChange: [loading: boolean]
}>()

const artifacts = ref<ArtifactSummary[]>([])
const planDetail = ref<AdjustmentPlanDetail | null>(null)
const loading = ref(false)
const errorMessage = ref('')
let requestSeq = 0

const artifactGroups = computed(() => groupArtifactsByCase(artifacts.value))
const loadedDetail = computed(() => planDetail.value)
const reloadingPlan = computed(
  () => Boolean(props.selectedPlanId) && props.selectedPlanId === props.loadedPlanId && Boolean(props.detailLoading),
)
const buildConfig = computed(() => loadedDetail.value?.build_config ?? {})
const sourceScenarioSetText = computed(() => {
  const items = loadedDetail.value?.source_scenario_sets ?? []
  if (!items.length) return props.loadedScenarioSetId || '未知'
  return items.map((item) => `${item.scenario_set_id} (${item.count})`).join('、')
})
const buildConfigStatusText = computed(() => {
  const detail = loadedDetail.value
  if (!detail || !detail.build_config_known_count) return '未知'
  if (detail.build_config_consistent) return '一致'
  return `不一致 (${detail.build_config_signatures.length} 组)`
})

watch(loading, (value) => {
  emit('loadingChange', value)
}, { immediate: true })

watch(
  () => [
    props.selectedProjectId,
    props.loadedScenarioSetId,
    props.loadedPlanId,
    props.loadedPlan?.case_count ?? 0,
    props.loadedPlan?.built_count ?? 0,
    props.loadedPlan?.solved_count ?? 0,
    props.loadedPlan?.timetable_count ?? 0,
  ] as const,
  () => {
    void loadArtifacts()
  },
  { immediate: true },
)

async function loadArtifacts() {
  const projectId = props.selectedProjectId
  const scenarioSetId = props.loadedScenarioSetId
  const planId = props.loadedPlanId
  const seq = requestSeq + 1
  requestSeq = seq
  errorMessage.value = ''

  if (!projectId || !scenarioSetId || !planId) {
    artifacts.value = []
    planDetail.value = null
    loading.value = false
    return
  }

  loading.value = true
  try {
    const [detail, result] = await Promise.all([
      api.readAdjustmentPlanDetail(projectId, scenarioSetId, planId),
      api.listArtifacts(projectId, scenarioSetId, planId),
    ])
    if (
      seq !== requestSeq ||
      projectId !== props.selectedProjectId ||
      scenarioSetId !== props.loadedScenarioSetId ||
      planId !== props.loadedPlanId
    ) {
      return
    }
    planDetail.value = detail
    artifacts.value = result
  } catch (error) {
    if (
      seq !== requestSeq ||
      projectId !== props.selectedProjectId ||
      scenarioSetId !== props.loadedScenarioSetId ||
      planId !== props.loadedPlanId
    ) {
      return
    }
    artifacts.value = []
    planDetail.value = null
    errorMessage.value = formatApiError(error)
  } finally {
    if (
      seq === requestSeq &&
      projectId === props.selectedProjectId &&
      scenarioSetId === props.loadedScenarioSetId &&
      planId === props.loadedPlanId
    ) {
      loading.value = false
    }
  }
}

function configValue(key: string) {
  const value = buildConfig.value[key]
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value === null || value === undefined || value === '') return '未知'
  return String(value)
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <ScenarioSetSelectorCard
        :selected-scenario-set-id="selectedScenarioSetId"
        :loaded-scenario-set-id="loadedScenarioSetId"
        :scenario-sets="scenarioSets"
        :scenario-set-options="scenarioSetOptions"
        :resource-loading="scenarioSetResourceLoading"
        :detail-loading="scenarioSetDetailLoading"
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

      <el-empty v-else-if="!loadedScenarioSetId" description="请选择场景分类">
        <el-button
          type="primary"
          :icon="Refresh"
          :loading-icon="Refresh"
          :loading="scenarioSetDetailLoading"
          :disabled="busy || !selectedScenarioSetId"
          @click="$emit('loadScenarioSet')"
        >
          加载
        </el-button>
      </el-empty>

      <template v-else>
        <EntityToolbar
          label="调整计划"
          :model-value="selectedPlanId"
          :options="adjustmentPlanOptions"
          :loading="adjustmentPlanLoading"
          placeholder="选择调整计划"
          add-label="构建调整计划"
          delete-label="删除调整计划"
          add-in-dropdown
          :busy="busy"
          @update:model-value="$emit('update:selectedPlanId', $event)"
          @visible-change="$emit('reloadPlans', $event)"
          @search="$emit('searchPlans', $event)"
          @add="$emit('createPlan')"
          @delete="$emit('deletePlan', $event)"
        >
          <template #actions>
            <el-button
              type="primary"
              :icon="Refresh"
              :loading-icon="Refresh"
              :loading="reloadingPlan"
              :disabled="busy || !selectedPlanId"
              @click="$emit('loadPlan')"
            >
              加载
            </el-button>
          </template>
        </EntityToolbar>

        <div v-if="!adjustmentPlans.length" class="primary-empty-panel">
          <el-empty :image-size="120">
            <template #description>
              <div class="primary-empty-title">暂无调整计划</div>
            </template>
            <el-button type="primary" size="large" :disabled="busy" @click="$emit('createPlan')">
              构建调整计划
            </el-button>
          </el-empty>
        </div>

        <el-empty v-else-if="!loadedPlanId" description="请选择调整计划">
          <el-button
            type="primary"
            :icon="Refresh"
            :loading-icon="Refresh"
            :loading="reloadingPlan"
            :disabled="busy || !selectedPlanId"
            @click="$emit('loadPlan')"
          >
            加载
          </el-button>
        </el-empty>

        <div v-else v-loading="loading" element-loading-text="正在加载调整计划数据...">
          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>调整计划：{{ loadedPlanId }}</span>
                <div class="scenario-actions">
                  <span class="muted-text">{{ artifactGroups.length }} 个实例</span>
                  <el-button
                    :icon="Refresh"
                    :loading-icon="Refresh"
                    :loading="loading"
                    :disabled="busy"
                    @click="loadArtifacts"
                  >
                    刷新
                  </el-button>
                  <el-button :disabled="busy" @click="$emit('buildPlan')">
                    构建/重建
                  </el-button>
                  <el-button :disabled="busy" @click="$emit('solveAll')">
                    全部求解
                  </el-button>
                </div>
              </div>
            </template>
            <el-result v-if="errorMessage" icon="error" title="调整计划加载失败" :sub-title="errorMessage">
              <template #extra>
                <el-button
                  type="primary"
                  :icon="Refresh"
                  :loading-icon="Refresh"
                  :loading="loading"
                  :disabled="busy"
                  @click="loadArtifacts"
                >
                  重试
                </el-button>
              </template>
            </el-result>
            <template v-else>
              <el-descriptions class="plan-detail" :column="3" border>
                <el-descriptions-item label="来源场景分类">
                  {{ sourceScenarioSetText }}
                </el-descriptions-item>
                <el-descriptions-item label="构建参数">
                  {{ buildConfigStatusText }}
                </el-descriptions-item>
                <el-descriptions-item label="实例状态">
                  {{ loadedDetail?.built_count ?? loadedPlan?.built_count ?? 0 }}/{{ loadedDetail?.case_count ?? loadedPlan?.case_count ?? 0 }} 已构建，
                  {{ loadedDetail?.solved_count ?? loadedPlan?.solved_count ?? 0 }} 已求解
                </el-descriptions-item>
                <el-descriptions-item label="目标函数">
                  {{ configValue('objective_mode') }} / 权重 {{ configValue('objective_delay_weight') }}
                </el-descriptions-item>
                <el-descriptions-item label="取消列车">
                  {{ configValue('cancellation_enabled') }} / 惩罚 {{ configValue('cancellation_penalty_weight') }}
                </el-descriptions-item>
                <el-descriptions-item label="到到/发发间隔">
                  {{ configValue('arr_arr_headway_seconds') }}s / {{ configValue('dep_dep_headway_seconds') }}s
                </el-descriptions-item>
                <el-descriptions-item label="停站时间">
                  {{ configValue('dwell_seconds_at_stops') }}s
                </el-descriptions-item>
                <el-descriptions-item label="Big-M">
                  {{ configValue('big_m') }}
                </el-descriptions-item>
                <el-descriptions-item label="延误容差">
                  {{ configValue('tolerance_delay_seconds') }}s
                </el-descriptions-item>
              </el-descriptions>

              <el-alert
                v-if="loadedDetail && loadedDetail.build_config_known_count && !loadedDetail.build_config_consistent"
                class="plan-warning"
                type="warning"
                show-icon
                :closable="false"
                title="该调整计划内存在多组构建参数，请检查是否混合了不同构建批次。"
              />

              <el-table
                :data="artifactGroups"
                max-height="420"
                table-layout="fixed"
                empty-text="暂无实例资源"
              >
                <el-table-column prop="case_id" label="场景 ID" show-overflow-tooltip />
                <el-table-column label="总大小" width="120">
                  <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
                </el-table-column>
                <el-table-column label="求解" width="260">
                  <template #default="{ row }">
                    <el-space wrap>
                      <el-tag :type="row.has_lp ? 'success' : 'info'">
                        {{ row.has_lp ? 'LP 已构建' : 'LP 缺失' }}
                      </el-tag>
                      <el-tag :type="row.has_solution && row.has_solution_csv ? 'success' : 'info'">
                        {{ row.has_solution && row.has_solution_csv ? '解数据完整' : '未求解' }}
                      </el-tag>
                    </el-space>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="128" align="right">
                  <template #default="{ row }">
                    <el-button
                      link
                      type="primary"
                      :disabled="!row.has_lp || busy"
                      @click="$emit('solveCase', row.case_id)"
                    >
                      求解
                    </el-button>
                    <el-button
                      link
                      type="primary"
                      :disabled="!row.has_solution || busy"
                      @click="$emit('openTimetable', row.case_id)"
                    >
                      查看
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </template>
          </el-card>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.plan-detail {
  margin-bottom: 12px;
}

.plan-warning {
  margin-bottom: 12px;
}
</style>
