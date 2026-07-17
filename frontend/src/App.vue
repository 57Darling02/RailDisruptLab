<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ScrollbarInstance } from 'element-plus'

import { api, ApiError } from '@/api/client'
import AppNavigation from '@/components/AppNavigation.vue'
import BuildOptionsFields from '@/components/BuildOptionsFields.vue'
import FieldLabelTip from '@/components/FieldLabelTip.vue'
import ProjectSelector from '@/components/ProjectSelector.vue'
import RemoteResourceSelect from '@/components/RemoteResourceSelect.vue'
import RunGraphSelector from '@/components/RunGraphSelector.vue'
import TaskPanel from '@/components/TaskPanel.vue'
import TaskLogDialog from '@/components/TaskLogDialog.vue'
import { Menu, Tickets } from '@/icons'
import {
  isTaskCancellable,
  isTaskFailed,
  isTaskSuccessful,
  isTaskTerminal,
} from '@/task-status'
import type {
  AdjustmentPlanBuildForm,
  AdjustmentPlanRunForm,
  TrainForm,
} from '@/views/types'
import type {
  AdjustmentPlanSummary,
  ModelCheckpoint,
  ModelDetail,
  ProjectState,
  ProjectSummary,
  ResourceOption,
  RunGraphReference,
  ScenarioSet,
  Task,
} from '@/types'

type PageKey = 'dashboard' | 'run-graphs' | 'scenario-overview' | 'scenario-resources' | 'scenario-detail' | 'adjustment-plans' | 'models' | 'ablation-scenarios' | 'ablation-plans'
type AdjustmentPlanBuildSource = 'scenario_set' | 'scenario'
type GenerationContextSource = 'run_graph' | 'scenario_set'
type ResourceKind = 'scenario_sets' | 'models'

const TimetableDialog = defineAsyncComponent(() => import('@/components/TimetableDialog.vue'))
const AdjustmentPlanAnalysisView = defineAsyncComponent(() => import('@/views/AdjustmentPlanAnalysisView.vue'))
const AdjustmentPlansView = defineAsyncComponent(() => import('@/views/AdjustmentPlansView.vue'))
const DashboardView = defineAsyncComponent(() => import('@/views/DashboardView.vue'))
const ModelsView = defineAsyncComponent(() => import('@/views/ModelsView.vue'))
const RunGraphsView = defineAsyncComponent(() => import('@/views/RunGraphsView.vue'))
const ScenarioComparisonView = defineAsyncComponent(() => import('@/views/ScenarioComparisonView.vue'))
const ScenarioDetailView = defineAsyncComponent(() => import('@/views/ScenarioDetailView.vue'))
const ScenarioSetsView = defineAsyncComponent(() => import('@/views/ScenarioSetsView.vue'))

const ACTIVE_TASK_POLL_MS = 2500
const IDLE_TASK_POLL_MS = 15000
const TASK_DURATION_TICK_MS = 1000
const DEFAULT_PLAN_RUN_FORM: AdjustmentPlanRunForm = {
  solveLimit: 0,
  solveTimeLimit: 120,
  solveMipGap: 0,
  solveThreads: 0,
  skipSolved: false,
}
const DEFAULT_PLAN_BUILD_FORM: AdjustmentPlanBuildForm = {
  objective_delay_weight: 1,
  objective_mode: 'abs',
  cancellation_enabled: false,
  cancellation_penalty_weight: 1000,
  arr_arr_headway_seconds: 180,
  dep_dep_headway_seconds: 180,
  dwell_seconds_at_stops: 120,
  big_m: 100000,
  tolerance_delay_seconds: 7200,
}
const DEFAULT_TRAIN_FORM: TrainForm = {
  model_id: '',
  scenario_set_id: '',
  max_slots: 8,
  event_time_window: 3600,
  event_top_k: 8,
  section_order_window: 2,
  hidden_dim: 64,
  latent_dim: 16,
  message_passing_steps: 2,
  epochs: 800,
  checkpoint_every: 5,
  batch_size: 8,
  lr: 0.0003,
  seed: 1,
  device: 'auto',
  count_weight: 1,
  anchor_weight: 1,
  param_weight: 2,
  kl_weight: 0.0015,
  use_relation_graph: true,
  relation_weight: 0.5,
}
const DEFAULT_SPEED_INTERRUPTION_THRESHOLD = 20
const DEVICE_OPTIONS = ['auto', 'cpu', 'cuda:0', 'cuda:1', 'cuda:2', 'cuda:3']
const TRAIN_FIELD_TIPS = {
  model_id: '本次训练产物的模型目录 ID，用于后续选择 checkpoint 生成场景。',
  scenario_set_id: '训练样本来源，固定使用一个完整场景分类。',
  max_slots: '扰动目标图 G_D 中每类扰动任务最多保留/预测的最大扰动数。',
  event_time_window: '上下文图 C 中，连接相邻时刻事件节点的时间窗口，单位秒。',
  event_top_k: '上下文图 C 中，每个事件节点最多保留的事件近邻数量，用于控制 C 的事件边密度。',
  section_order_window: '上下文图 C 中，沿线路顺序连接前后区间节点的邻接窗口。',
  hidden_dim: 'VAE 编码器/解码器隐藏层维度，越大表达能力越强但训练更重。',
  latent_dim: '潜变量维度，控制模型压缩扰动模式的容量。',
  message_passing_steps: '图神经网络消息传递轮数，越大可聚合更远邻域信息。',
  epochs: '完整遍历训练场景分类的轮数。',
  checkpoint_every: '每隔多少轮评估并更新一次最佳 checkpoint；最后一轮仍会保存为最后模型。',
  batch_size: '每次优化使用的样本数量。',
  lr: '优化器学习率。',
  seed: '随机种子，用于复现实验。',
  device: '训练设备，auto 会优先使用 CUDA；指定 GPU 卡号可填写 cuda:0、cuda:1，CPU 填 cpu。',
  count_weight: '扰动数量预测损失权重。',
  anchor_weight: '扰动锚点位置预测损失权重。',
  param_weight: '扰动参数预测损失权重，例如延误秒数、限速速度等。',
  kl_weight: 'VAE KL 散度损失权重，控制潜空间正则强度。',
  use_relation_graph: '训练 posterior 是否引入扰动关系图 R；关闭后可用于 R 消融实验。',
  relation_weight: '关系图 R 的辅助损失权重；仅在启用 R 时参与训练目标。',
} as const
const GENERATION_FIELD_TIPS = {
  scenario_set_id: '模型生成的场景会写入这个场景分类。',
  num_samples: '本次从模型采样并解码出的场景数量。',
  seed: '生成随机种子，用于复现采样结果。',
  device: '生成使用的设备，auto 会优先使用 CUDA；指定 GPU 卡号可填写 cuda:0、cuda:1，CPU 填 cpu。',
  speed_interruption_threshold:
    '生成解码时，低于或等于该速度阈值的限速会被转成 limit_speed=0；后续 build 会按中断建模。',
  overwrite: '开启后会覆盖同名输出场景。',
} as const
const TASK_LABELS = {
  adjustmentPlans: ['build', 'solve'],
  models: ['train', 'generation'],
} as const

const projects = ref<ProjectSummary[]>([])
const projectOptions = ref<ResourceOption[]>([])
const projectOptionsLoading = ref(false)
const selectedProjectId = ref('')
const project = ref<ProjectState | null>(null)
const tasks = ref<Task[]>([])
const taskNow = ref(Date.now())
const activePage = ref<PageKey>('dashboard')
const activeOperation = ref('')
const mainScrollbar = ref<ScrollbarInstance>()
const navigationDrawerVisible = ref(false)
const navigationPinnedExpanded = ref(false)
const taskDrawerVisible = ref(false)

const selectedScenarioSetId = ref('')
const loadedScenarioSetId = ref('')
const scenarioCategoryRefreshKey = ref(0)
const scenarioCategoryDetailLoading = ref(false)
const scenarioSetOptions = ref<ResourceOption[]>([])
const scenarioSetOptionsLoading = ref(false)
const scenarioOptions = ref<ResourceOption[]>([])
const scenarioOptionsLoading = ref(false)
const selectedScenarioId = ref('')
const scenarioSetDialogVisible = ref(false)
const newScenarioSetId = ref('')
const scenarioDialogVisible = ref(false)
const scenarioCreateScenarioSetId = ref('')
const scenarioCreateScenarioId = ref('')
const scenarioCreateRunGraph = ref<RunGraphReference | null>(null)
const normalGenerateDialogVisible = ref(false)
const normalGenerateScenarioSetId = ref('')
const normalGenerateForm = ref({
  scenario_id_prefix: 'sim',
  simulation_count: 1,
  seed: 20260320,
  delay_count: 10,
  speed_count: 10,
  interruption_count: 10,
  combo_per_type: 10,
  overwrite: false,
})
const normalGenerateRunGraph = ref<RunGraphReference | null>(null)

const selectedPlanId = ref('')
const loadedPlanId = ref('')
const planDetailRefreshKey = ref(0)
const planDetailLoading = ref(false)
const adjustmentPlans = ref<AdjustmentPlanSummary[]>([])
const adjustmentPlanOptions = ref<ResourceOption[]>([])
const adjustmentPlanOptionsLoading = ref(false)
const planCreateDialogVisible = ref(false)
const newPlanId = ref('')
const planBuildDialogVisible = ref(false)
const planBuildForm = ref({
  scenario_set_id: '',
  source: 'scenario_set' as AdjustmentPlanBuildSource,
  scenario_id: '',
  ...DEFAULT_PLAN_BUILD_FORM,
})
const solveDialogVisible = ref(false)
const solveTargetCaseId = ref('')
const timetableDialogVisible = ref(false)
const timetableCaseId = ref('')
const taskLogDialogVisible = ref(false)
const taskLogTarget = ref<Task | null>(null)
const planRunForm = ref<AdjustmentPlanRunForm>({ ...DEFAULT_PLAN_RUN_FORM })

const selectedModelId = ref('')
const loadedModelId = ref('')
const modelDetailLoading = ref(false)
const modelOptions = ref<ResourceOption[]>([])
const modelOptionsLoading = ref(false)
const pendingModelId = ref('')
const pendingModelTaskId = ref<number | null>(null)
const retrainModelDetail = ref<ModelDetail | null>(null)
const trainDialogVisible = ref(false)
const trainDialogMode = ref<'create' | 'retrain'>('create')
const generationDialogVisible = ref(false)
const trainForm = reactive<TrainForm>({ ...DEFAULT_TRAIN_FORM })
const trainModelSuffix = ref('')
const generationForm = ref({
  checkpoint: '',
  scenario_set_id: '',
  context_source: 'run_graph' as GenerationContextSource,
  source_scenario_set_id: '',
  run_graph: null as RunGraphReference | null,
  output_prefix: 'generated',
  num_samples: 100,
  seed: 1,
  device: 'auto',
  speed_interruption_threshold: DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
  overwrite: false,
})

let taskPollHandle = 0
let taskPolling = false
let taskPollInFlight = false
let taskRequestSeq = 0
let durationTickHandle = 0
const resourceOptionRequestSeq = reactive<Record<ResourceKind, number>>({
  scenario_sets: 0,
  models: 0,
})
let adjustmentPlanOptionRequestSeq = 0
let adjustmentPlanListRequestSeq = 0
let scenarioOptionRequestSeq = 0
let projectOptionRequestSeq = 0

const hasProject = computed(() => Boolean(selectedProjectId.value && project.value?.exists))
const runGraphSets = computed(() => project.value?.run_graph_sets ?? [])
const trainModelPrefix = computed(() => {
  const scenarioSetId = trainForm.scenario_set_id.trim()
  return scenarioSetId ? `train_${scenarioSetId}` : ''
})
const projectSelectOptions = computed(() =>
  mergeSelectedResourceOption(
    projectOptions.value,
    selectedProjectId.value,
    selectedProjectId.value,
  ),
)
const scenarioSets = computed(() => project.value?.scenario_sets ?? [])
const adjustmentPlanCount = computed(() =>
  scenarioSets.value.reduce((total, item) => total + (item.plan_count ?? 0), 0),
)
const models = computed(() => {
  const items = project.value?.models ?? []
  const pendingId = pendingModelId.value.trim()
  if (!pendingId || items.some((item) => item.model_id === pendingId)) return items
  return [
    ...items,
    {
      model_id: pendingId,
      root: '',
      is_ready: false,
      has_context_graph: false,
      sample_count: 0,
      has_dataset_profile: false,
      has_best_model: false,
      has_last_model: false,
      has_training_summary: false,
    },
  ]
})
const scenarioSetSelectOptions = computed(() =>
  mergeSelectedResourceOptions(scenarioSetOptions.value, [
    {
      value: selectedScenarioSetId.value,
      label: resourceLabel(scenarioSets.value, 'scenario_set_id', selectedScenarioSetId.value, 'case_count'),
    },
    {
      value: loadedScenarioSetId.value,
      label: resourceLabel(scenarioSets.value, 'scenario_set_id', loadedScenarioSetId.value, 'case_count'),
    },
    {
      value: planBuildForm.value.scenario_set_id,
      label: resourceLabel(scenarioSets.value, 'scenario_set_id', planBuildForm.value.scenario_set_id, 'case_count'),
    },
    {
      value: trainForm.scenario_set_id,
      label: resourceLabel(scenarioSets.value, 'scenario_set_id', trainForm.scenario_set_id, 'case_count'),
    },
    {
      value: generationForm.value.source_scenario_set_id,
      label: resourceLabel(
        scenarioSets.value,
        'scenario_set_id',
        generationForm.value.source_scenario_set_id,
        'case_count',
      ),
    },
  ]),
)
const scenarioSelectOptions = computed(() =>
  mergeSelectedResourceOption(
    scenarioOptions.value,
    planBuildForm.value.scenario_id,
    planBuildForm.value.scenario_id,
  ),
)
const adjustmentPlanSelectOptions = computed(() =>
  mergeSelectedResourceOptions(adjustmentPlanOptions.value, [
    {
      value: selectedPlanId.value,
      label: resourceLabel(adjustmentPlans.value, 'plan_id', selectedPlanId.value, 'case_count'),
    },
    {
      value: loadedPlanId.value,
      label: resourceLabel(adjustmentPlans.value, 'plan_id', loadedPlanId.value, 'case_count'),
    },
  ]),
)
const modelSelectOptions = computed(() =>
  mergeSelectedResourceOptions(modelOptions.value, [
    {
      value: selectedModelId.value,
      label: resourceLabel(models.value, 'model_id', selectedModelId.value, 'sample_count'),
    },
    {
      value: loadedModelId.value,
      label: resourceLabel(models.value, 'model_id', loadedModelId.value, 'sample_count'),
    },
  ]),
)
const loadedPlan = computed(
  () => adjustmentPlans.value.find((item) => item.plan_id === loadedPlanId.value) ?? null,
)
const loadedModel = computed(
  () => models.value.find((item) => item.model_id === loadedModelId.value) ?? null,
)
const taskProjectOptions = computed(() => [
  { label: '全部项目', value: '' },
  ...projects.value.map((item) => ({ label: item.project_id, value: item.project_id })),
])
const modelTasks = computed(() => filterTasks(TASK_LABELS.models))
const visibleTasks = computed(() => tasks.value)
const hasRunningTasks = computed(() => tasks.value.some((task) => !isTaskTerminal(task)))
const projectTasks = computed(() => tasks.value.filter((task) => task.group === selectedProjectId.value))
const runningTaskCount = computed(() => projectTasks.value.filter((task) => !isTaskTerminal(task)).length)
const doneTaskCount = computed(() => projectTasks.value.filter(isTaskSuccessful).length)
const failedTaskCount = computed(() => projectTasks.value.filter(isTaskFailed).length)
const operationPending = computed(() => Boolean(activeOperation.value))
const operationText = computed(() => (activeOperation.value ? `${activeOperation.value}中...` : '处理中...'))

watch(selectedProjectId, async (_projectId, previousProjectId) => {
  if (previousProjectId) {
    selectedScenarioSetId.value = ''
    loadedScenarioSetId.value = ''
    selectedPlanId.value = ''
    loadedPlanId.value = ''
    adjustmentPlans.value = []
    selectedModelId.value = ''
    loadedModelId.value = ''
    clearResourceOptions()
  }
  await loadSelectedProject()
})

watch(activePage, async () => {
  await scrollMainToTop()
  await hydrateActivePage()
})

watch(selectedPlanId, (planId) => {
  timetableDialogVisible.value = false
  timetableCaseId.value = ''
  loadedPlanId.value = planId
  if (planId) planDetailRefreshKey.value += 1
})

watch(selectedScenarioSetId, async (scenarioSetId) => {
  loadedScenarioSetId.value = scenarioSetId
  await loadAdjustmentPlans(false)
})

watch(selectedModelId, (modelId) => {
  loadedModelId.value = modelId
  retrainModelDetail.value = null
})

watch(
  () => trainForm.scenario_set_id,
  () => {
    if (trainDialogMode.value === 'create') syncTrainModelId()
  },
)

watch(trainModelSuffix, () => {
  if (trainDialogMode.value === 'create') syncTrainModelId()
})

watch(hasRunningTasks, (hasRunning) => {
  if (hasRunning) {
    startDurationTick()
  } else {
    stopDurationTick()
  }
  rescheduleTaskPoll()
})

onMounted(async () => {
  await bootstrap()
  startTaskPolling()
  if (hasRunningTasks.value) startDurationTick()
})

onUnmounted(() => {
  stopTaskPolling()
  stopDurationTick()
})

async function bootstrap() {
  await runAction('连接后端', async () => {
    await api.health()
    await refreshProjects()
    await refreshTasks(false)
  })
}

async function refreshProjects() {
  projects.value = await api.listProjects()
  if (!selectedProjectId.value && projects.value[0]) {
    selectedProjectId.value = projects.value[0].project_id
  }
}

async function loadProjectOptions(query = '') {
  const requestSeq = projectOptionRequestSeq + 1
  projectOptionRequestSeq = requestSeq
  projectOptionsLoading.value = true
  try {
    const options = await api.listProjectOptions(query)
    if (requestSeq === projectOptionRequestSeq) projectOptions.value = options
  } catch (error) {
    if (requestSeq === projectOptionRequestSeq) {
      projectOptions.value = []
      notifyError(error)
    }
  } finally {
    if (requestSeq === projectOptionRequestSeq) projectOptionsLoading.value = false
  }
}

async function reloadProjectOptionsOnOpen(visible: boolean) {
  if (!visible) return
  await loadProjectOptions('')
  await refreshProjects()
}

async function loadSelectedProject(showMessage = true) {
  if (!selectedProjectId.value) {
    project.value = null
    clearResourceOptions()
    return
  }
  try {
    project.value = await api.getProject(selectedProjectId.value)
    selectFirstOptions()
    await hydrateActivePage(showMessage)
  } catch (error) {
    project.value = null
    clearResourceOptions()
    if (showMessage) notifyError(error)
  }
}

function clearResourceOptions() {
  scenarioSetOptions.value = []
  scenarioOptions.value = []
  adjustmentPlanOptions.value = []
  adjustmentPlans.value = []
  modelOptions.value = []
}

function selectFirstOptions() {
  const currentProject = project.value
  if (!currentProject) return
  const hasScenarioSet = (scenarioSetId: string) =>
    currentProject.scenario_sets.some((item) => item.scenario_set_id === scenarioSetId)
  const firstScenarioSetId = currentProject.scenario_sets[0]?.scenario_set_id ?? ''
  if (!selectedScenarioSetId.value || !hasScenarioSet(selectedScenarioSetId.value)) {
    selectedScenarioSetId.value = firstScenarioSetId
  }
  if (!loadedScenarioSetId.value || !hasScenarioSet(loadedScenarioSetId.value)) {
    loadedScenarioSetId.value = selectedScenarioSetId.value
  }
  const readyPendingModel = currentProject.models.find((item) => item.model_id === pendingModelId.value)
  if (readyPendingModel) {
    selectedModelId.value = readyPendingModel.model_id
    loadedModelId.value = readyPendingModel.model_id
    clearPendingModel()
  } else if (
    !selectedModelId.value ||
    (
      selectedModelId.value !== pendingModelId.value &&
      !currentProject.models.some((item) => item.model_id === selectedModelId.value)
    )
  ) {
    selectedModelId.value = currentProject.models[0]?.model_id ?? ''
  }
  if (
    loadedModelId.value &&
    loadedModelId.value !== pendingModelId.value &&
    !currentProject.models.some((item) => item.model_id === loadedModelId.value)
  ) {
    loadedModelId.value = ''
  }
  reconcilePendingModel()
}

async function loadResourceOptions(
  resource: ResourceKind,
  query: string,
  state: { target: { value: ResourceOption[] }; loading: { value: boolean } },
) {
  if (!selectedProjectId.value) {
    state.target.value = []
    return
  }
  const projectId = selectedProjectId.value
  const requestSeq = resourceOptionRequestSeq[resource] + 1
  resourceOptionRequestSeq[resource] = requestSeq
  state.loading.value = true
  try {
    const options = await api.listResourceOptions(projectId, resource, query)
    if (requestSeq === resourceOptionRequestSeq[resource] && projectId === selectedProjectId.value) {
      state.target.value = options
    }
  } catch (error) {
    if (requestSeq === resourceOptionRequestSeq[resource] && projectId === selectedProjectId.value) {
      state.target.value = []
      notifyError(error)
    }
  } finally {
    if (requestSeq === resourceOptionRequestSeq[resource] && projectId === selectedProjectId.value) {
      state.loading.value = false
    }
  }
}

function mergeSelectedResourceOption(
  options: ResourceOption[],
  value: string,
  label: string,
) {
  if (!value || options.some((item) => item.value === value)) return options
  return [{ label: label || value, value }, ...options]
}

function mergeSelectedResourceOptions(
  options: ResourceOption[],
  selected: Array<{ value: string; label: string }>,
) {
  let result = options
  for (const item of selected) {
    result = mergeSelectedResourceOption(result, item.value, item.label)
  }
  return result
}

function mergeScenarioSet(item: ScenarioSet) {
  if (!project.value) return
  project.value = {
    ...project.value,
    scenario_sets: [
      ...project.value.scenario_sets.filter(
        (scenarioSet) => scenarioSet.scenario_set_id !== item.scenario_set_id,
      ),
      item,
    ],
  }
}

function resourceLabel<T extends Record<string, unknown>>(
  items: T[],
  idKey: keyof T,
  value: string,
  countKey: keyof T,
) {
  const item = items.find((entry) => entry[idKey] === value)
  return item ? resourceOptionLabel(value, item[countKey]) : value
}

function resourceOptionLabel(value: string, count: unknown) {
  return typeof count === 'number' ? `${value} (${count})` : value
}

async function hydrateActivePage(showLoading = true) {
  if (!hasProject.value) return
  void showLoading
  if (activePage.value === 'adjustment-plans') {
    await loadAdjustmentPlans(false)
  }
}

async function refreshTasks(showMessage = true) {
  const requestSeq = taskRequestSeq + 1
  taskRequestSeq = requestSeq
  try {
    const nextTasks = await api.listTasks()
    if (requestSeq !== taskRequestSeq) return null
    const previousTasks = tasks.value
    tasks.value = nextTasks
    reconcilePendingModel()
    return previousTasks
  } catch (error) {
    if (requestSeq === taskRequestSeq && showMessage) notifyError(error)
    return null
  }
}

async function pollTasks() {
  taskNow.value = Date.now()
  const previousTasks = await refreshTasks(false)
  if (previousTasks == null) return
  if (shouldRefreshSelectedProjectAfterTaskPoll(previousTasks, tasks.value)) {
    await loadSelectedProject(false)
  }
  refreshLoadedResourceDetailsAfterTaskPoll(previousTasks, tasks.value)
}

function startTaskPolling() {
  if (taskPolling) return
  taskPolling = true
  scheduleTaskPoll()
}

function stopTaskPolling() {
  taskPolling = false
  taskRequestSeq += 1
  if (!taskPollHandle) return
  window.clearTimeout(taskPollHandle)
  taskPollHandle = 0
}

function rescheduleTaskPoll() {
  if (!taskPolling || taskPollInFlight) return
  if (taskPollHandle) window.clearTimeout(taskPollHandle)
  taskPollHandle = 0
  scheduleTaskPoll()
}

function scheduleTaskPoll() {
  if (!taskPolling || taskPollHandle || taskPollInFlight) return
  const delay = hasRunningTasks.value ? ACTIVE_TASK_POLL_MS : IDLE_TASK_POLL_MS
  taskPollHandle = window.setTimeout(async () => {
    taskPollHandle = 0
    taskPollInFlight = true
    try {
      await pollTasks()
    } finally {
      taskPollInFlight = false
      scheduleTaskPoll()
    }
  }, delay)
}

function shouldRefreshSelectedProjectAfterTaskPoll(previous: Task[], current: Task[]) {
  if (!selectedProjectId.value) return false
  const previousById = new Map(previous.map((task) => [task.id, task]))
  return current.some((task) => {
    if (task.group !== selectedProjectId.value) return false
    const oldTask = previousById.get(task.id)
    if (!oldTask) return isTaskTerminal(task)
    if (!isTaskTerminal(task)) return false
    return taskPollSignature(oldTask) !== taskPollSignature(task)
  })
}

function taskPollSignature(task: Task) {
  return [
    task.status,
    task.finished_at ?? '',
    stableTaskDetail(task.status_detail),
  ].join('\u0000')
}

function stableTaskDetail(value: unknown) {
  try {
    return JSON.stringify(value) ?? ''
  } catch {
    return String(value ?? '')
  }
}

function refreshLoadedResourceDetailsAfterTaskPoll(previous: Task[], current: Task[]) {
  const previousById = new Map(previous.map((task) => [task.id, task]))
  for (const task of current) {
    if (!didLoadedResourceTaskFinish(task, previousById.get(task.id))) continue
    refreshLoadedResourceForTask(task)
  }
}

function didLoadedResourceTaskFinish(task: Task, previous?: Task) {
  if (!isTaskTerminal(task)) return false
  if (previous && isTaskTerminal(previous) && taskPollSignature(previous) === taskPollSignature(task)) {
    return false
  }
  return task.group === selectedProjectId.value
}

function refreshLoadedResourceForTask(task: Task) {
  const label = String(task.label ?? task.action ?? '')
  const params = task.params ?? {}
  if (
    loadedScenarioSetId.value &&
    ['normal_generate', 'scenario_delete', 'generation', 'scenario_set_validate'].includes(label) &&
    params.scenario_set_id === loadedScenarioSetId.value
  ) {
    scenarioCategoryDetailLoading.value = false
    scenarioCategoryRefreshKey.value += 1
  }
  if (
    loadedPlanId.value &&
    ['build', 'solve'].includes(label) &&
    params.scenario_set_id === loadedScenarioSetId.value &&
    params.plan_id === loadedPlanId.value
  ) {
    planDetailRefreshKey.value += 1
    void loadAdjustmentPlans(false)
  }
  if (label === 'run_graph_build') {
    void loadSelectedProject(false)
  }
}

function startDurationTick() {
  if (durationTickHandle) return
  durationTickHandle = window.setInterval(() => {
    taskNow.value = Date.now()
  }, TASK_DURATION_TICK_MS)
}

function stopDurationTick() {
  if (!durationTickHandle) return
  window.clearInterval(durationTickHandle)
  durationTickHandle = 0
}

async function createProject(projectId: string) {
  projectId = projectId.trim()
  if (!projectId) return
  await runAction('创建项目', async () => {
    const createdProject = await api.createProject(projectId)
    project.value = createdProject
    selectedProjectId.value = createdProject.project_id
    projects.value = [
      ...projects.value.filter((item) => item.project_id !== createdProject.project_id),
      { project_id: createdProject.project_id, root: createdProject.root },
    ]
    projectOptions.value = [{ label: createdProject.project_id, value: createdProject.project_id }]
    await refreshProjects()
    return `项目 ${createdProject.project_id} 已创建`
  })
}

function openProjectCreatePrompt() {
  void ElMessageBox.prompt('项目 ID', '新建项目', {
    confirmButtonText: '创建',
    cancelButtonText: '取消',
    inputPattern: /\S+/,
    inputErrorMessage: '请输入项目 ID',
  }).then(({ value }) => {
    void createProject(String(value || ''))
  })
}

async function removeProject(projectId: string) {
  projectId = projectId.trim()
  if (!projectId) return
  await submitTask('移除项目', async () => {
    const response = await api.deleteProject(projectId)
    if (selectedProjectId.value === projectId) {
      selectedProjectId.value = ''
      project.value = null
      clearResourceOptions()
    }
    projectOptions.value = projectOptions.value.filter((item) => item.value !== projectId)
    return response.task
  })
}

async function createScenarioSet() {
  const scenarioSetId = newScenarioSetId.value.trim()
  if (!scenarioSetId) return
  await runAction('创建场景分类', async () => {
    const createdScenarioSet = await api.createScenarioSet(selectedProjectId.value, scenarioSetId)
    mergeScenarioSet(createdScenarioSet)
    selectedScenarioSetId.value = createdScenarioSet.scenario_set_id
    loadedScenarioSetId.value = createdScenarioSet.scenario_set_id
    scenarioSetOptions.value = [
      {
        label: resourceOptionLabel(createdScenarioSet.scenario_set_id, createdScenarioSet.case_count),
        value: createdScenarioSet.scenario_set_id,
      },
    ]
    newScenarioSetId.value = ''
    scenarioSetDialogVisible.value = false
    await loadSelectedProject(false)
    return `场景分类 ${createdScenarioSet.scenario_set_id} 已创建`
  })
}

async function deleteScenarioSetById(scenarioSetId: string) {
  if (!selectedProjectId.value || !scenarioSetId) return
  try {
    await ElMessageBox.confirm(
      `确认删除场景分类 ${scenarioSetId}？该操作会删除对应场景文件目录。`,
      '删除场景分类',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await runAction('删除场景分类', async () => {
    await api.deleteScenarioSet(selectedProjectId.value, scenarioSetId)
    if (selectedScenarioSetId.value === scenarioSetId) {
      selectedScenarioSetId.value = ''
    }
    if (loadedScenarioSetId.value === scenarioSetId) {
      loadedScenarioSetId.value = ''
    }
    scenarioSetOptions.value = scenarioSetOptions.value.filter((item) => item.value !== scenarioSetId)
    await loadSelectedProject(false)
    return `场景分类 ${scenarioSetId} 已删除`
  })
}

function reloadSelectedScenarioSetDetail() {
  if (!selectedScenarioSetId.value) {
    ElMessage.warning('请先选择场景分类。')
    return
  }
  scenarioCategoryDetailLoading.value = false
  loadedScenarioSetId.value = selectedScenarioSetId.value
  scenarioCategoryRefreshKey.value += 1
}

function reloadSelectedPlanDetail() {
  if (!selectedPlanId.value) {
    ElMessage.warning('请先选择调整计划。')
    return
  }
  loadedPlanId.value = selectedPlanId.value
  planDetailRefreshKey.value += 1
}

function reloadSelectedModelDetail() {
  if (!selectedModelId.value) {
    ElMessage.warning('请先选择模型。')
    return
  }
  loadedModelId.value = selectedModelId.value
  retrainModelDetail.value = null
}

async function reloadScenarioSetsOnOpen(visible: boolean) {
  if (!visible) return
  await loadResourceOptions('scenario_sets', '', {
    target: scenarioSetOptions,
    loading: scenarioSetOptionsLoading,
  })
  await loadSelectedProject(false)
}

async function searchScenarioSetOptions(query: string) {
  await loadResourceOptions('scenario_sets', query, {
    target: scenarioSetOptions,
    loading: scenarioSetOptionsLoading,
  })
}

async function loadScenarioOptions(query = '') {
  const projectId = selectedProjectId.value
  const scenarioSetId = planBuildForm.value.scenario_set_id.trim()
  const requestSeq = scenarioOptionRequestSeq + 1
  scenarioOptionRequestSeq = requestSeq

  if (!projectId || !scenarioSetId) {
    scenarioOptions.value = []
    return
  }

  scenarioOptionsLoading.value = true
  try {
    const options = await api.listScenarioOptions(projectId, scenarioSetId, query)
    if (
      requestSeq === scenarioOptionRequestSeq &&
      projectId === selectedProjectId.value &&
      scenarioSetId === planBuildForm.value.scenario_set_id.trim()
    ) {
      scenarioOptions.value = options
    }
  } catch (error) {
    if (requestSeq === scenarioOptionRequestSeq) {
      scenarioOptions.value = []
      notifyError(error)
    }
  } finally {
    if (requestSeq === scenarioOptionRequestSeq) scenarioOptionsLoading.value = false
  }
}

function reloadScenarioOptionsOnOpen(visible: boolean) {
  if (visible) void loadScenarioOptions('')
}

async function loadAdjustmentPlans(showMessage = true) {
  const projectId = selectedProjectId.value
  const scenarioSetId = loadedScenarioSetId.value || selectedScenarioSetId.value
  const requestSeq = adjustmentPlanListRequestSeq + 1
  adjustmentPlanListRequestSeq = requestSeq
  if (!projectId || !scenarioSetId) {
    adjustmentPlans.value = []
    selectedPlanId.value = ''
    loadedPlanId.value = ''
    return
  }
  try {
    const result = await api.listAdjustmentPlans(projectId, scenarioSetId)
    if (
      requestSeq !== adjustmentPlanListRequestSeq ||
      projectId !== selectedProjectId.value ||
      scenarioSetId !== (loadedScenarioSetId.value || selectedScenarioSetId.value)
    ) {
      return
    }
    adjustmentPlans.value = result
    if (!selectedPlanId.value || !result.some((item) => item.plan_id === selectedPlanId.value)) {
      selectedPlanId.value = result[0]?.plan_id ?? ''
    }
    if (loadedPlanId.value && !result.some((item) => item.plan_id === loadedPlanId.value)) {
      loadedPlanId.value = ''
    }
  } catch (error) {
    if (requestSeq === adjustmentPlanListRequestSeq) {
      adjustmentPlans.value = []
      if (showMessage) notifyError(error)
    }
  }
}

async function loadAdjustmentPlanOptions(query = '') {
  const projectId = selectedProjectId.value
  const scenarioSetId = loadedScenarioSetId.value || selectedScenarioSetId.value
  const requestSeq = adjustmentPlanOptionRequestSeq + 1
  adjustmentPlanOptionRequestSeq = requestSeq
  if (!projectId || !scenarioSetId) {
    adjustmentPlanOptions.value = []
    return
  }
  adjustmentPlanOptionsLoading.value = true
  try {
    const options = await api.listAdjustmentPlanOptions(projectId, scenarioSetId, query)
    if (
      requestSeq === adjustmentPlanOptionRequestSeq &&
      projectId === selectedProjectId.value &&
      scenarioSetId === (loadedScenarioSetId.value || selectedScenarioSetId.value)
    ) {
      adjustmentPlanOptions.value = options
    }
  } catch (error) {
    if (requestSeq === adjustmentPlanOptionRequestSeq) {
      adjustmentPlanOptions.value = []
      notifyError(error)
    }
  } finally {
    if (requestSeq === adjustmentPlanOptionRequestSeq) adjustmentPlanOptionsLoading.value = false
  }
}

async function reloadAdjustmentPlansOnOpen(visible: boolean) {
  if (!visible) return
  await loadAdjustmentPlanOptions('')
  await loadAdjustmentPlans(false)
}

async function searchAdjustmentPlanOptions(query: string) {
  await loadAdjustmentPlanOptions(query)
}

function openScenarioDialog() {
  if (operationPending.value) return
  scenarioCreateScenarioSetId.value = loadedScenarioSetId.value || selectedScenarioSetId.value
  if (!scenarioCreateScenarioSetId.value) {
    ElMessage.warning('请先选择场景分类。')
    return
  }
  scenarioCreateScenarioId.value = ''
  scenarioCreateRunGraph.value = null
  scenarioDialogVisible.value = true
}

async function createScenarioCase() {
  const scenarioSetId = scenarioCreateScenarioSetId.value.trim()
  const scenarioId = scenarioCreateScenarioId.value.trim()
  if (!scenarioSetId || !scenarioId) {
    ElMessage.warning('请填写场景 ID 并选择场景分类。')
    return
  }
  const runGraph = scenarioCreateRunGraph.value
  if (!runGraph) {
    ElMessage.warning('请选择运行图。')
    return
  }
  await runAction('新增场景', async () => {
    await api.createScenarioCase(
      selectedProjectId.value,
      scenarioSetId,
      scenarioId,
      runGraph,
    )
    selectedScenarioSetId.value = scenarioSetId
    loadedScenarioSetId.value = scenarioSetId
    selectedScenarioId.value = scenarioId
    activePage.value = 'scenario-detail'
    scenarioCategoryRefreshKey.value += 1
    scenarioDialogVisible.value = false
    await loadSelectedProject(false)
    return `场景 ${scenarioId} 已创建。`
  })
}

async function deleteScenario(id: string) {
  const scenarioSetId = loadedScenarioSetId.value || selectedScenarioSetId.value
  if (!scenarioSetId) return
  try {
    await ElMessageBox.confirm(`确认删除场景 ${id}？`, '删除场景', { type: 'warning' })
  } catch {
    return
  }
  await submitTask('删除场景', async () => {
    const response = await api.deleteScenario(
      selectedProjectId.value,
      scenarioSetId,
      id,
    )
    return response.task
  })
}

function viewScenario(id: string) {
  if (loadedScenarioSetId.value) {
    selectedScenarioSetId.value = loadedScenarioSetId.value
  }
  selectedScenarioId.value = id
  activePage.value = 'scenario-detail'
}

function backToScenarios() {
  activePage.value = 'scenario-resources'
}

function openNormalGenerateDialog() {
  if (operationPending.value) return
  if (!loadedScenarioSetId.value) {
    ElMessage.warning('请先载入场景分类。')
    return
  }
  normalGenerateScenarioSetId.value = loadedScenarioSetId.value
  normalGenerateRunGraph.value = null
  normalGenerateDialogVisible.value = true
}

async function submitNormalGenerate() {
  const scenarioSetId = normalGenerateScenarioSetId.value.trim()
  if (!scenarioSetId) return
  const runGraph = normalGenerateRunGraph.value
  if (!runGraph) {
    ElMessage.warning('请选择运行图。')
    return
  }
  await submitTask('模拟场景', async () => {
    const response = await api.submitNormalGenerate(selectedProjectId.value, {
      scenario_set_id: scenarioSetId,
      scenario_id_prefix: normalGenerateForm.value.scenario_id_prefix,
      simulation_count: normalGenerateForm.value.simulation_count,
      run_graph: runGraph,
      seed: normalGenerateForm.value.seed,
      delay_count: normalGenerateForm.value.delay_count,
      speed_count: normalGenerateForm.value.speed_count,
      interruption_count: normalGenerateForm.value.interruption_count,
      combo_per_type: normalGenerateForm.value.combo_per_type,
      overwrite: normalGenerateForm.value.overwrite,
    })
    selectedScenarioSetId.value = scenarioSetId
    loadedScenarioSetId.value = scenarioSetId
    scenarioCategoryDetailLoading.value = false
    scenarioCategoryRefreshKey.value += 1
    normalGenerateDialogVisible.value = false
    return response.task
  })
}

async function validateLoadedScenarios() {
  const scenarioSetId = loadedScenarioSetId.value.trim()
  if (!scenarioSetId) {
    ElMessage.warning('请先载入场景分类。')
    return
  }
  await submitTask('批量校验场景', async () => {
    const response = await api.submitValidateScenarios(selectedProjectId.value, scenarioSetId)
    scenarioCategoryDetailLoading.value = false
    scenarioCategoryRefreshKey.value += 1
    return response.task
  })
}

async function submitBuildPlan() {
  const planId = loadedPlanId.value.trim()
  const scenarioSetId = planBuildForm.value.scenario_set_id.trim()
  const scenarioId =
    planBuildForm.value.source === 'scenario' ? planBuildForm.value.scenario_id.trim() : ''
  if (!planId || !scenarioSetId) {
    ElMessage.warning('请先选择调整计划和场景来源。')
    return
  }
  if (planBuildForm.value.source === 'scenario' && !scenarioId) {
    ElMessage.warning('请选择要构建的场景。')
    return
  }
  await submitTask('构建调整计划', async () => {
    const response = await api.submitBuild(
      selectedProjectId.value,
      scenarioSetId,
      planId,
      scenarioId,
      normalizedBuildOptions(),
    )
    selectedScenarioSetId.value = scenarioSetId
    loadedScenarioSetId.value = scenarioSetId
    selectedPlanId.value = planId
    loadedPlanId.value = planId
    planBuildDialogVisible.value = false
    await loadAdjustmentPlans(false)
    return response.task
  })
}

function normalizedBuildOptions(): AdjustmentPlanBuildForm {
  return {
    objective_delay_weight: positiveNumber(
      planBuildForm.value.objective_delay_weight,
      DEFAULT_PLAN_BUILD_FORM.objective_delay_weight,
    ),
    objective_mode: planBuildForm.value.objective_mode || DEFAULT_PLAN_BUILD_FORM.objective_mode,
    cancellation_enabled: Boolean(planBuildForm.value.cancellation_enabled),
    cancellation_penalty_weight: positiveNumber(
      planBuildForm.value.cancellation_penalty_weight,
      DEFAULT_PLAN_BUILD_FORM.cancellation_penalty_weight,
    ),
    arr_arr_headway_seconds: Math.floor(
      positiveNumber(
        planBuildForm.value.arr_arr_headway_seconds,
        DEFAULT_PLAN_BUILD_FORM.arr_arr_headway_seconds,
      ),
    ),
    dep_dep_headway_seconds: Math.floor(
      positiveNumber(
        planBuildForm.value.dep_dep_headway_seconds,
        DEFAULT_PLAN_BUILD_FORM.dep_dep_headway_seconds,
      ),
    ),
    dwell_seconds_at_stops: Math.floor(
      positiveNumber(
        planBuildForm.value.dwell_seconds_at_stops,
        DEFAULT_PLAN_BUILD_FORM.dwell_seconds_at_stops,
      ),
    ),
    big_m: Math.floor(positiveNumber(planBuildForm.value.big_m, DEFAULT_PLAN_BUILD_FORM.big_m)),
    tolerance_delay_seconds: Math.floor(
      positiveNumber(
        planBuildForm.value.tolerance_delay_seconds,
        DEFAULT_PLAN_BUILD_FORM.tolerance_delay_seconds,
      ),
    ),
  }
}

function positiveNumber(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback
}

async function createAdjustmentPlan() {
  const scenarioSetId = loadedScenarioSetId.value || selectedScenarioSetId.value
  const planId = newPlanId.value.trim()
  const scenarioId =
    planBuildForm.value.source === 'scenario' ? planBuildForm.value.scenario_id.trim() : ''
  if (!scenarioSetId) {
    ElMessage.warning('请先选择场景分类。')
    return
  }
  if (!planId) {
    ElMessage.warning('请填写调整计划 ID。')
    return
  }
  if (planBuildForm.value.source === 'scenario' && !scenarioId) {
    ElMessage.warning('请选择要构建的场景。')
    return
  }
  const existingPlan = adjustmentPlans.value.find((item) => item.plan_id === planId)
  if (existingPlan) {
    try {
      await ElMessageBox.confirm(
        `调整计划 ${planId} 已存在。继续会清空并重建该计划产物。`,
        '重建调整计划',
        { type: 'warning', confirmButtonText: '清空并重建', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  await submitTask('构建调整计划', async () => {
    selectedScenarioSetId.value = scenarioSetId
    loadedScenarioSetId.value = scenarioSetId
    selectedPlanId.value = planId
    loadedPlanId.value = planId
    const response = await api.submitBuild(
      selectedProjectId.value,
      scenarioSetId,
      planId,
      scenarioId,
      normalizedBuildOptions(),
    )
    resetPlanCreateForm()
    planCreateDialogVisible.value = false
    await loadAdjustmentPlans(false)
    return response.task
  })
}

async function deleteAdjustmentPlanById(planId: string) {
  const scenarioSetId = loadedScenarioSetId.value || selectedScenarioSetId.value
  if (!selectedProjectId.value || !scenarioSetId || !planId) return
  try {
    await ElMessageBox.confirm(
      `确认删除调整计划 ${planId}？该操作会删除构建、求解和时刻表产物。`,
      '删除调整计划',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await runAction('删除调整计划', async () => {
    await api.deleteAdjustmentPlan(selectedProjectId.value, scenarioSetId, planId)
    if (selectedPlanId.value === planId) {
      selectedPlanId.value = ''
      timetableCaseId.value = ''
      timetableDialogVisible.value = false
    }
    if (loadedPlanId.value === planId) {
      loadedPlanId.value = ''
    }
    adjustmentPlanOptions.value = adjustmentPlanOptions.value.filter((item) => item.value !== planId)
    adjustmentPlans.value = adjustmentPlans.value.filter((item) => item.plan_id !== planId)
    await loadSelectedProject(false)
    await loadAdjustmentPlans(false)
    return `调整计划 ${planId} 已删除`
  })
}

async function submitSolve(caseId = '') {
  if (!loadedScenarioSetId.value || !loadedPlanId.value) return
  const options = normalizedSolveOptions()
  await submitTask('求解', async () => {
    const response = await api.submitSolve(
      selectedProjectId.value,
      loadedScenarioSetId.value,
      loadedPlanId.value,
      caseId ? 0 : options.solveLimit,
      options.solveTimeLimit,
      caseId,
      options.solveMipGap,
      options.solveThreads,
      caseId ? false : options.skipSolved,
    )
    solveDialogVisible.value = false
    return response.task
  })
}

function openSolveDialog(caseId = '') {
  if (operationPending.value) return
  if (!loadedPlanId.value) return
  solveTargetCaseId.value = caseId
  resetSolveForm()
  solveDialogVisible.value = true
}

async function submitSolveDialog() {
  await submitSolve(solveTargetCaseId.value)
}

function resetSolveForm() {
  planRunForm.value = { ...DEFAULT_PLAN_RUN_FORM }
}

function normalizedSolveOptions(): AdjustmentPlanRunForm {
  return {
    solveLimit: nonNegativeNumber(planRunForm.value.solveLimit, DEFAULT_PLAN_RUN_FORM.solveLimit),
    solveTimeLimit: nonNegativeNumber(
      planRunForm.value.solveTimeLimit,
      DEFAULT_PLAN_RUN_FORM.solveTimeLimit,
    ),
    solveMipGap: nonNegativeNumber(planRunForm.value.solveMipGap, DEFAULT_PLAN_RUN_FORM.solveMipGap),
    solveThreads: Math.floor(
      nonNegativeNumber(planRunForm.value.solveThreads, DEFAULT_PLAN_RUN_FORM.solveThreads),
    ),
    skipSolved: Boolean(planRunForm.value.skipSolved),
  }
}

function nonNegativeNumber(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback
}

async function openPlanCreateDialog() {
  if (operationPending.value) return
  const scenarioSetId = loadedScenarioSetId.value || selectedScenarioSetId.value || scenarioSets.value[0]?.scenario_set_id || ''
  if (!scenarioSetId) {
    ElMessage.warning('请先创建并选择场景分类。')
    return
  }
  selectedScenarioSetId.value = scenarioSetId
  loadedScenarioSetId.value = scenarioSetId
  newPlanId.value = ''
  resetPlanBuildForm({
    source: 'scenario_set',
    scenarioSetId,
  })
  planCreateDialogVisible.value = true
}

function resetPlanCreateForm() {
  newPlanId.value = ''
  resetPlanBuildForm({
    source: 'scenario_set',
    scenarioSetId: loadedScenarioSetId.value || selectedScenarioSetId.value,
  })
}

async function openPlanBuildDialog() {
  if (operationPending.value) return
  if (!loadedPlanId.value) {
    ElMessage.warning('请先载入一个调整计划。')
    return
  }
  resetPlanBuildForm({
    source: 'scenario_set',
    scenarioSetId: loadedScenarioSetId.value || selectedScenarioSetId.value || scenarioSets.value[0]?.scenario_set_id || '',
  })
  if (planBuildForm.value.scenario_set_id) {
    selectedScenarioSetId.value = planBuildForm.value.scenario_set_id
    await loadScenarioOptions('')
  }
  planBuildDialogVisible.value = true
}

function resetPlanBuildForm(options: { source: AdjustmentPlanBuildSource; scenarioSetId: string }) {
  planBuildForm.value = {
    scenario_set_id: options.scenarioSetId,
    source: options.source,
    scenario_id: '',
    ...DEFAULT_PLAN_BUILD_FORM,
  }
}

function updatePlanBuildOptions(options: AdjustmentPlanBuildForm) {
  planBuildForm.value = {
    ...planBuildForm.value,
    ...options,
  }
}

async function onPlanBuildScenarioSetChange() {
  planBuildForm.value.scenario_id = ''
  await loadScenarioOptions('')
}

function openCaseTimetable(caseId: string) {
  if (!selectedProjectId.value || !loadedScenarioSetId.value || !loadedPlanId.value) return
  timetableCaseId.value = caseId
  timetableDialogVisible.value = true
}

function openTaskLog(task: Task | null) {
  if (!task) return
  taskLogTarget.value = task
  taskLogDialogVisible.value = true
}

async function cancelTask(task: Task) {
  if (!isTaskCancellable(task)) return
  try {
    await ElMessageBox.confirm(`确认中断任务 #${task.id}？`, '中断任务', {
      type: 'warning',
    })
  } catch {
    return
  }
  await runAction('中断任务', async () => {
    await api.cancelTask(task.id)
    await refreshTasks(false)
    return `任务 #${task.id} 已请求中断`
  })
}

async function removeTask(task: Task) {
  if (!isTaskTerminal(task)) return
  await runAction('清除任务', async () => {
    await api.removeTask(task.id)
    tasks.value = tasks.value.filter((item) => item.id !== task.id)
    if (taskLogTarget.value?.id === task.id) {
      taskLogDialogVisible.value = false
      taskLogTarget.value = null
    }
    await refreshTasks(false)
    return `任务 #${task.id} 已清除`
  })
}

async function openTrainDialog(
  mode: 'create' | 'retrain' = 'create',
  detail: ModelDetail | null = null,
) {
  if (operationPending.value) return
  trainDialogMode.value = mode
  retrainModelDetail.value = mode === 'retrain' ? detail : null
  resetTrainForm(mode)
  trainDialogVisible.value = true
  await nextTick()
  resetTrainForm(mode)
}

function resetTrainForm(mode: 'create' | 'retrain' = trainDialogMode.value) {
  const config = mode === 'retrain' ? retrainModelDetail.value?.config ?? {} : {}
  const scenarioSetId =
    stringConfigValue(config.scenario_set_id) ||
    selectedScenarioSetId.value ||
    scenarioSets.value[0]?.scenario_set_id ||
    ''
  const modelId = mode === 'retrain' && loadedModelId.value ? loadedModelId.value : ''
  Object.assign(trainForm, {
    ...DEFAULT_TRAIN_FORM,
    ...trainFormDefaultsFromConfig(config),
    model_id: modelId,
    scenario_set_id: scenarioSetId,
  })
  if (mode === 'create') {
    trainModelSuffix.value = ''
    syncTrainModelId()
  } else {
    trainModelSuffix.value = ''
  }
}

function syncTrainModelId() {
  const prefix = trainModelPrefix.value
  const suffix = trainModelSuffix.value.trim()
  trainForm.model_id = prefix && suffix ? `${prefix}_${suffix}` : prefix || suffix
}

async function submitTrain() {
  if (!trainForm.model_id.trim() || !trainForm.scenario_set_id.trim()) {
    ElMessage.warning('请填写模型 ID 并选择训练场景分类。')
    return
  }
  const existingModel = models.value.find((item) => item.model_id === trainForm.model_id.trim())
  if (existingModel && trainDialogMode.value !== 'retrain') {
    try {
      await ElMessageBox.confirm(
        `模型 ${existingModel.model_id} 已存在。重新训练会先删除旧模型产物，再开始训练。`,
        '覆盖模型',
        { type: 'warning', confirmButtonText: '覆盖并训练', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  await submitTask('训练模型', async () => {
    const modelId = trainForm.model_id.trim()
    const response = await api.submitTrain(selectedProjectId.value, { ...trainForm, model_id: modelId })
    pendingModelId.value = modelId
    pendingModelTaskId.value = response.task.id
    selectedModelId.value = modelId
    loadedModelId.value = modelId
    retrainModelDetail.value = null
    trainDialogVisible.value = false
    return response.task
  })
}

function openGenerationDialog(file: ModelCheckpoint) {
  if (operationPending.value) return
  if (!loadedModelId.value) {
    ElMessage.warning('请先载入模型。')
    return
  }
  generationForm.value.checkpoint = file.relative_path
  generationForm.value.scenario_set_id = ''
  generationForm.value.context_source = 'run_graph'
  generationForm.value.source_scenario_set_id = ''
  generationForm.value.run_graph = null
  generationForm.value.speed_interruption_threshold = DEFAULT_SPEED_INTERRUPTION_THRESHOLD
  generationDialogVisible.value = true
}

function updateGenerationContextSource(source: GenerationContextSource) {
  generationForm.value.context_source = source
  if (source === 'run_graph') {
    generationForm.value.source_scenario_set_id = ''
  } else {
    generationForm.value.run_graph = null
  }
}

async function submitGeneration() {
  if (!loadedModelId.value) return
  if (!generationForm.value.checkpoint) {
    ElMessage.warning('请先选择 checkpoint 文件。')
    return
  }
  if (!generationForm.value.scenario_set_id.trim()) {
    ElMessage.warning('请填写生成到的场景分类 ID。')
    return
  }
  const useRunGraph = generationForm.value.context_source === 'run_graph'
  const sourceScenarioSetId = useRunGraph ? '' : generationForm.value.source_scenario_set_id.trim()
  const runGraph = useRunGraph ? generationForm.value.run_graph : null
  if (!sourceScenarioSetId && !runGraph) {
    ElMessage.warning(useRunGraph ? '请选择运行图。' : '请选择来源场景分类。')
    return
  }
  await submitTask('生成场景', async () => {
    const response = await api.submitGeneration(
      selectedProjectId.value,
      loadedModelId.value,
      generationForm.value.checkpoint,
      generationForm.value.scenario_set_id,
      sourceScenarioSetId,
      runGraph,
      generationForm.value.output_prefix,
      generationForm.value.num_samples,
      generationForm.value.seed,
      generationForm.value.device,
      generationForm.value.speed_interruption_threshold,
      generationForm.value.overwrite,
    )
    generationDialogVisible.value = false
    return response.task
  })
}

async function deleteModelById(modelId: string) {
  if (!selectedProjectId.value || !modelId) return
  try {
    await ElMessageBox.confirm(
      `确认删除模型 ${modelId}？该操作会删除模型产物目录。`,
      '删除模型',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await runAction('删除模型', async () => {
    await api.deleteModel(selectedProjectId.value, modelId)
    if (selectedModelId.value === modelId) {
      selectedModelId.value = ''
      retrainModelDetail.value = null
    }
    if (loadedModelId.value === modelId) {
      loadedModelId.value = ''
    }
    if (pendingModelId.value === modelId) {
      clearPendingModel()
    }
    modelOptions.value = modelOptions.value.filter((item) => item.value !== modelId)
    await loadSelectedProject(false)
    return `模型 ${modelId} 已删除`
  })
}

async function reloadModelsOnOpen(visible: boolean) {
  if (!visible) return
  await loadResourceOptions('models', '', {
    target: modelOptions,
    loading: modelOptionsLoading,
  })
  await loadSelectedProject(false)
}

async function searchModelOptions(query: string) {
  await loadResourceOptions('models', query, {
    target: modelOptions,
    loading: modelOptionsLoading,
  })
}

function trackTask(task: Task, options: { refresh?: boolean } = {}) {
  const index = tasks.value.findIndex((item) => item.id === task.id)
  if (index >= 0) {
    tasks.value[index] = task
  } else {
    tasks.value.push(task)
  }
  if (options.refresh ?? true) void refreshTasks(false)
}

function reconcilePendingModel() {
  if (!pendingModelId.value) {
    pendingModelTaskId.value = null
    return
  }
  if (project.value?.models.some((item) => item.model_id === pendingModelId.value)) {
    clearPendingModel()
    return
  }
  if (pendingModelTaskId.value == null) return
  const task = tasks.value.find((item) => item.id === pendingModelTaskId.value)
  if (!task) {
    clearPendingModel()
    return
  }
  if (isTaskTerminal(task)) {
    clearPendingModel()
  }
}

function clearPendingModel() {
  pendingModelId.value = ''
  pendingModelTaskId.value = null
}

function filterTasks(labels: readonly string[]) {
  return projectTasks.value.filter((task) => labels.includes(String(task.label ?? '')))
}

function trainFormDefaultsFromConfig(config: Record<string, unknown>): Partial<TrainForm> {
  const result: Partial<TrainForm> = {}
  for (const [key, defaultValue] of Object.entries(DEFAULT_TRAIN_FORM)) {
    if (key === 'model_id' || key === 'scenario_set_id') continue
    const value = config[key]
    if (typeof defaultValue === 'number' && typeof value === 'number') {
      result[key as keyof TrainForm] = value as never
    } else if (typeof defaultValue === 'string' && typeof value === 'string') {
      result[key as keyof TrainForm] = value as never
    } else if (typeof defaultValue === 'boolean' && typeof value === 'boolean') {
      result[key as keyof TrainForm] = value as never
    }
  }
  return result
}

function stringConfigValue(value: unknown) {
  return typeof value === 'string' ? value : ''
}

async function scrollMainToTop() {
  await nextTick()
  mainScrollbar.value?.setScrollTop(0)
}

async function runAction(label: string, action: () => Promise<string | void>) {
  if (operationPending.value) return
  activeOperation.value = label
  try {
    const message = await action()
    ElMessage.success(message || label)
  } catch (error) {
    notifyError(error)
  } finally {
    activeOperation.value = ''
  }
}

async function submitTask(label: string, action: () => Promise<Task>) {
  if (operationPending.value) return
  activeOperation.value = label
  try {
    const task = await action()
    trackTask(task, { refresh: false })
    ElMessage.success(`${label}已提交：任务 #${task.id}`)
    await refreshTasks(false)
  } catch (error) {
    notifyError(error)
  } finally {
    activeOperation.value = ''
  }
}

function selectPage(key: string) {
  activePage.value = key as PageKey
  navigationDrawerVisible.value = false
}

function notifyError(error: unknown) {
  if (error instanceof ApiError) {
    ElMessage.error(`${error.status}: ${error.message}`)
  } else if (error instanceof Error) {
    ElMessage.error(error.message)
  } else {
    ElMessage.error(String(error))
  }
}
</script>

<template>
  <div class="common-layout">
    <el-container>
      <el-aside
        :width="navigationPinnedExpanded ? '220px' : '64px'"
        class="app-aside"
      >
        <AppNavigation
          :active-page="activePage"
          variant="desktop"
          @select="selectPage"
          @pinned-expanded-change="navigationPinnedExpanded = $event"
        />
      </el-aside>

      <el-container>
        <el-header class="app-header">
          <el-button
            class="mobile-nav-button"
            :icon="Menu"
            :disabled="operationPending"
            @click="navigationDrawerVisible = true"
          >
            菜单
          </el-button>
          <div class="header-actions">
            <ProjectSelector
              v-model="selectedProjectId"
              :options="projectSelectOptions"
              :loading="projectOptionsLoading"
              :busy="operationPending"
              @visible-change="reloadProjectOptionsOnOpen"
              @search="loadProjectOptions"
              @create="openProjectCreatePrompt"
              @delete="removeProject"
            />
            <el-badge
              v-if="hasProject"
              class="mobile-task-badge"
              :value="failedTaskCount || runningTaskCount"
              :type="failedTaskCount ? 'danger' : 'primary'"
              :hidden="!failedTaskCount && !runningTaskCount"
            >
              <el-button
                class="mobile-task-button"
                :icon="Tickets"
                @click="taskDrawerVisible = true"
              >
                任务
              </el-button>
            </el-badge>
          </div>
        </el-header>

        <el-container class="workspace-container">
          <el-main
            v-loading="operationPending"
            :element-loading-text="operationText"
            class="app-main"
          >
            <el-scrollbar ref="mainScrollbar" class="main-scroll">
              <div v-if="!hasProject" class="primary-empty-panel project-empty-panel">
                <el-empty :image-size="120">
                  <template #description>
                    <div class="primary-empty-title">还没有可用项目</div>
                  </template>
                  <el-button
                    type="primary"
                    size="large"
                    :disabled="operationPending"
                    @click="openProjectCreatePrompt"
                  >
                    新建项目
                  </el-button>
                </el-empty>
              </div>

              <template v-else>
                <DashboardView
                  v-if="activePage === 'dashboard'"
                  :selected-project-id="selectedProjectId"
                  :run-graph-set-count="runGraphSets.length"
                  :scenario-set-count="scenarioSets.length"
                  :adjustment-plan-count="adjustmentPlanCount"
                  :models="models"
                  :tasks="tasks"
                  :running-task-count="runningTaskCount"
                  :done-task-count="doneTaskCount"
                  :failed-task-count="failedTaskCount"
                  :busy="operationPending"
                  @create-run-graph-set="activePage = 'run-graphs'"
                  @create-scenario-set="scenarioSetDialogVisible = true"
                  @create-plan="openPlanCreateDialog"
                  @train="() => openTrainDialog('create')"
                  @refresh-tasks="refreshTasks"
                />

                <RunGraphsView
                  v-else-if="activePage === 'run-graphs'"
                  :project-id="selectedProjectId"
                  :run-graph-sets="runGraphSets"
                  :busy="operationPending"
                  @refresh-project="loadSelectedProject(false)"
                  @task-submitted="trackTask"
                />

                <ScenarioSetsView
                  v-else-if="activePage === 'scenario-overview' || activePage === 'scenario-resources'"
                  :key="scenarioCategoryRefreshKey"
                  v-model:selected-scenario-set-id="selectedScenarioSetId"
                  :selected-project-id="selectedProjectId"
                  :loaded-scenario-set-id="loadedScenarioSetId"
                  :scenario-sets="scenarioSets"
                  :scenario-set-options="scenarioSetSelectOptions"
                  :resource-loading="scenarioSetOptionsLoading"
                  :detail-loading="scenarioCategoryDetailLoading"
                  :busy="operationPending"
                  :section="activePage === 'scenario-overview' ? 'overview' : 'resources'"
                  @reload-scenario-sets="reloadScenarioSetsOnOpen"
                  @search-scenario-sets="searchScenarioSetOptions"
                  @create-scenario-set="scenarioSetDialogVisible = true"
                  @load-scenario-set="reloadSelectedScenarioSetDetail"
                  @delete-scenario-set="deleteScenarioSetById"
                  @create-scenario="openScenarioDialog"
                  @simulate-scenario="openNormalGenerateDialog"
                  @validate-scenarios="validateLoadedScenarios"
                  @delete-scenario="deleteScenario"
                  @view-scenario="viewScenario"
                  @detail-loading-change="scenarioCategoryDetailLoading = $event"
                />

                <ScenarioDetailView
                  v-else-if="activePage === 'scenario-detail'"
                  :project-id="selectedProjectId"
                  :scenario-set-id="selectedScenarioSetId"
                  :scenario-id="selectedScenarioId"
                  :busy="operationPending"
                  @back="backToScenarios"
                  @validated="loadSelectedProject(false)"
                />

                <AdjustmentPlansView
                  v-else-if="activePage === 'adjustment-plans'"
                  :key="planDetailRefreshKey"
                  v-model:selected-scenario-set-id="selectedScenarioSetId"
                  :selected-project-id="selectedProjectId"
                  :loaded-scenario-set-id="loadedScenarioSetId"
                  :scenario-sets="scenarioSets"
                  :scenario-set-options="scenarioSetSelectOptions"
                  :scenario-set-resource-loading="scenarioSetOptionsLoading"
                  :scenario-set-detail-loading="scenarioCategoryDetailLoading"
                  v-model:selected-plan-id="selectedPlanId"
                  :loaded-plan-id="loadedPlanId"
                  :loaded-plan="loadedPlan"
                  :adjustment-plans="adjustmentPlans"
                  :adjustment-plan-options="adjustmentPlanSelectOptions"
                  :adjustment-plan-loading="adjustmentPlanOptionsLoading"
                  :detail-loading="planDetailLoading"
                  :busy="operationPending"
                  @reload-scenario-sets="reloadScenarioSetsOnOpen"
                  @search-scenario-sets="searchScenarioSetOptions"
                  @create-scenario-set="scenarioSetDialogVisible = true"
                  @load-scenario-set="reloadSelectedScenarioSetDetail"
                  @delete-scenario-set="deleteScenarioSetById"
                  @reload-plans="reloadAdjustmentPlansOnOpen"
                  @search-plans="searchAdjustmentPlanOptions"
                  @create-plan="openPlanCreateDialog"
                  @load-plan="reloadSelectedPlanDetail"
                  @delete-plan="deleteAdjustmentPlanById"
                  @build-plan="openPlanBuildDialog"
                  @solve-all="() => openSolveDialog()"
                  @solve-case="openSolveDialog"
                  @open-timetable="openCaseTimetable"
                  @loading-change="planDetailLoading = $event"
                />

                <ModelsView
                  v-else-if="activePage === 'models'"
                  v-model:selected-model-id="selectedModelId"
                  :selected-project-id="selectedProjectId"
                  :loaded-model-id="loadedModelId"
                  :pending-model-id="pendingModelId"
                  :loaded-model="loadedModel"
                  :models="models"
                  :model-options="modelSelectOptions"
                  :resource-loading="modelOptionsLoading"
                  :detail-loading="modelDetailLoading"
                  :tasks="modelTasks"
                  :busy="operationPending"
                  @reload-models="reloadModelsOnOpen"
                  @search-models="searchModelOptions"
                  @load-model="reloadSelectedModelDetail"
                  @train="() => openTrainDialog('create')"
                  @retrain="(detail) => openTrainDialog('retrain', detail)"
                  @delete-model="deleteModelById"
                  @open-task-log="openTaskLog"
                  @generate="openGenerationDialog"
                  @loading-change="modelDetailLoading = $event"
                />

                <ScenarioComparisonView
                  v-else-if="activePage === 'ablation-scenarios'"
                  :selected-project-id="selectedProjectId"
                  :scenario-sets="scenarioSets"
                  :scenario-set-options="scenarioSetSelectOptions"
                  :scenario-set-resource-loading="scenarioSetOptionsLoading"
                  :busy="operationPending"
                  @reload-scenario-sets="reloadScenarioSetsOnOpen"
                  @search-scenario-sets="searchScenarioSetOptions"
                  @create-scenario-set="scenarioSetDialogVisible = true"
                />

                <AdjustmentPlanAnalysisView
                  v-else-if="activePage === 'ablation-plans'"
                  :selected-project-id="selectedProjectId"
                  :scenario-sets="scenarioSets"
                  :busy="operationPending"
                  @create-scenario-set="scenarioSetDialogVisible = true"
                />
              </template>
            </el-scrollbar>
          </el-main>
          <el-aside v-if="hasProject" width="300px" class="task-aside">
            <TaskPanel
              :tasks="visibleTasks"
              :now="taskNow"
              :project-options="taskProjectOptions"
              :initial-project-id="selectedProjectId"
              :busy="operationPending"
              @refresh="refreshTasks"
              @cancel="cancelTask"
              @remove="removeTask"
            />
          </el-aside>
        </el-container>
      </el-container>
    </el-container>

    <el-drawer
      v-model="navigationDrawerVisible"
      direction="ltr"
      size="260px"
      :with-header="false"
      class="navigation-drawer"
    >
      <AppNavigation :active-page="activePage" variant="drawer" @select="selectPage" />
    </el-drawer>

    <el-drawer
      v-if="hasProject"
      v-model="taskDrawerVisible"
      direction="rtl"
      size="380px"
      title="任务"
      class="task-drawer"
    >
      <TaskPanel
        :tasks="visibleTasks"
        :now="taskNow"
        :project-options="taskProjectOptions"
        :initial-project-id="selectedProjectId"
        :busy="operationPending"
        @refresh="refreshTasks"
        @cancel="cancelTask"
        @remove="removeTask"
      />
    </el-drawer>

    <el-dialog v-model="scenarioSetDialogVisible" title="新增场景分类" width="420px">
      <el-input
        v-model="newScenarioSetId"
        placeholder="场景分类 ID"
        :disabled="operationPending"
        @keyup.enter="createScenarioSet"
      />
      <template #footer>
        <el-button :disabled="operationPending" @click="scenarioSetDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '创建场景分类'"
          :disabled="operationPending"
          @click="createScenarioSet"
        >
          确定
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="scenarioDialogVisible" title="新增场景" width="620px">
      <el-form label-width="120px">
        <el-form-item label="场景分类">
          <el-input :model-value="scenarioCreateScenarioSetId" disabled />
        </el-form-item>
        <el-form-item label="场景 ID">
          <el-input v-model="scenarioCreateScenarioId" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="运行图">
          <RunGraphSelector
            v-model="scenarioCreateRunGraph"
            :project-id="selectedProjectId"
            :disabled="operationPending"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="operationPending" @click="scenarioDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '新增场景'"
          :disabled="operationPending"
          @click="createScenarioCase"
        >
          确定
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="normalGenerateDialogVisible" title="模拟场景" width="640px">
      <el-form class="dialog-section" label-width="150px">
        <el-form-item label="当前场景分类">
          <el-input :model-value="normalGenerateScenarioSetId" disabled />
        </el-form-item>
        <el-form-item label="运行图">
          <RunGraphSelector
            v-model="normalGenerateRunGraph"
            :project-id="selectedProjectId"
            :disabled="operationPending"
          />
        </el-form-item>
        <el-form-item label="场景 ID 前缀">
          <el-input v-model="normalGenerateForm.scenario_id_prefix" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="模拟数量">
          <el-input-number v-model="normalGenerateForm.simulation_count" :min="1" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="随机种子">
          <el-input-number v-model="normalGenerateForm.seed" :min="0" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="晚点扰动数">
          <el-input-number v-model="normalGenerateForm.delay_count" :min="0" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="限速扰动数">
          <el-input-number v-model="normalGenerateForm.speed_count" :min="0" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="中断扰动数">
          <el-input-number
            v-model="normalGenerateForm.interruption_count"
            :min="0"
            :disabled="operationPending"
          />
        </el-form-item>
        <el-form-item label="组合场景数/类型">
          <el-input-number
            v-model="normalGenerateForm.combo_per_type"
            :min="0"
            :disabled="operationPending"
          />
        </el-form-item>
        <el-form-item label="覆盖同名场景">
          <el-switch v-model="normalGenerateForm.overwrite" :disabled="operationPending" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="operationPending" @click="normalGenerateDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '模拟场景'"
          :disabled="operationPending"
          @click="submitNormalGenerate"
        >
          {{ activeOperation === '模拟场景' ? '正在模拟构建中......' : '确定模拟' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="trainDialogVisible"
      :title="trainDialogMode === 'retrain' ? '重新训练模型' : '训练新模型'"
      width="920px"
      class="train-dialog"
    >
      <el-scrollbar max-height="68vh">
        <el-form label-position="top" class="train-form">
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="训练场景分类" :tip="TRAIN_FIELD_TIPS.scenario_set_id" />
                </template>
                <RemoteResourceSelect
                  v-model="trainForm.scenario_set_id"
                  :options="scenarioSetSelectOptions"
                  placeholder="选择训练场景分类"
                  :disabled="operationPending"
                  :loading="scenarioSetOptionsLoading"
                  @search="searchScenarioSetOptions"
                  @visible-change="reloadScenarioSetsOnOpen"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="模型 ID" :tip="TRAIN_FIELD_TIPS.model_id" />
                </template>
                <el-input
                  v-if="trainDialogMode === 'create'"
                  v-model="trainModelSuffix"
                  placeholder="请输入模型后缀"
                  :disabled="operationPending"
                >
                  <template #prepend>{{ trainModelPrefix || '请选择场景分类' }}_</template>
                </el-input>
                <el-input v-else v-model="trainForm.model_id" disabled />
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider content-position="left">训练图结构</el-divider>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="G_D 最大扰动数" :tip="TRAIN_FIELD_TIPS.max_slots" />
                </template>
                <el-input-number v-model="trainForm.max_slots" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="C 事件时间窗口" :tip="TRAIN_FIELD_TIPS.event_time_window" />
                </template>
                <el-input-number
                  v-model="trainForm.event_time_window"
                  :min="1"
                  :disabled="operationPending"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="C 事件邻接上限" :tip="TRAIN_FIELD_TIPS.event_top_k" />
                </template>
                <el-input-number v-model="trainForm.event_top_k" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="C 区间邻接窗口" :tip="TRAIN_FIELD_TIPS.section_order_window" />
                </template>
                <el-input-number
                  v-model="trainForm.section_order_window"
                  :min="1"
                  :disabled="operationPending"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="启用关系图 R" :tip="TRAIN_FIELD_TIPS.use_relation_graph" />
                </template>
                <el-switch v-model="trainForm.use_relation_graph" :disabled="operationPending" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider content-position="left">模型与优化</el-divider>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="隐藏维度" :tip="TRAIN_FIELD_TIPS.hidden_dim" />
                </template>
                <el-input-number v-model="trainForm.hidden_dim" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="潜变量维度" :tip="TRAIN_FIELD_TIPS.latent_dim" />
                </template>
                <el-input-number v-model="trainForm.latent_dim" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="消息传递步数" :tip="TRAIN_FIELD_TIPS.message_passing_steps" />
                </template>
                <el-input-number
                  v-model="trainForm.message_passing_steps"
                  :min="1"
                  :disabled="operationPending"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="训练轮数" :tip="TRAIN_FIELD_TIPS.epochs" />
                </template>
                <el-input-number v-model="trainForm.epochs" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="检查点间隔" :tip="TRAIN_FIELD_TIPS.checkpoint_every" />
                </template>
                <el-input-number v-model="trainForm.checkpoint_every" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="Batch Size" :tip="TRAIN_FIELD_TIPS.batch_size" />
                </template>
                <el-input-number v-model="trainForm.batch_size" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="学习率" :tip="TRAIN_FIELD_TIPS.lr" />
                </template>
                <el-input-number
                  v-model="trainForm.lr"
                  :min="0"
                  :step="0.0001"
                  :disabled="operationPending"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="随机种子" :tip="TRAIN_FIELD_TIPS.seed" />
                </template>
                <el-input-number v-model="trainForm.seed" :min="0" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="设备" :tip="TRAIN_FIELD_TIPS.device" />
                </template>
                <el-select
                  v-model="trainForm.device"
                  filterable
                  allow-create
                  default-first-option
                  class="full-width"
                  :disabled="operationPending"
                >
                  <el-option
                    v-for="device in DEVICE_OPTIONS"
                    :key="device"
                    :label="device"
                    :value="device"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider content-position="left">损失权重</el-divider>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="Count" :tip="TRAIN_FIELD_TIPS.count_weight" />
                </template>
                <el-input-number
                  v-model="trainForm.count_weight"
                  :min="0"
                  :step="0.1"
                  :disabled="operationPending"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="Anchor" :tip="TRAIN_FIELD_TIPS.anchor_weight" />
                </template>
                <el-input-number
                  v-model="trainForm.anchor_weight"
                  :min="0"
                  :step="0.1"
                  :disabled="operationPending"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="Param" :tip="TRAIN_FIELD_TIPS.param_weight" />
                </template>
                <el-input-number
                  v-model="trainForm.param_weight"
                  :min="0"
                  :step="0.1"
                  :disabled="operationPending"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="KL" :tip="TRAIN_FIELD_TIPS.kl_weight" />
                </template>
                <el-input-number
                  v-model="trainForm.kl_weight"
                  :min="0"
                  :step="0.0005"
                  :disabled="operationPending"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="R 损失权重" :tip="TRAIN_FIELD_TIPS.relation_weight" />
                </template>
                <el-input-number
                  v-model="trainForm.relation_weight"
                  :min="0"
                  :step="0.1"
                  :disabled="operationPending || !trainForm.use_relation_graph"
                />
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>
      </el-scrollbar>
      <template #footer>
        <el-button :disabled="operationPending" @click="trainDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '训练模型'"
          :disabled="operationPending"
          @click="submitTrain"
        >
          提交训练
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="generationDialogVisible" title="使用模型生成场景" width="560px">
      <el-form label-width="150px">
        <el-form-item label="模型">
          <el-input :model-value="selectedModelId" disabled />
        </el-form-item>
        <el-form-item label="Checkpoint">
          <el-input :model-value="generationForm.checkpoint" disabled />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="生成到新的场景分类" :tip="GENERATION_FIELD_TIPS.scenario_set_id" />
          </template>
          <el-input
            v-model="generationForm.scenario_set_id"
            placeholder="请输入完整场景分类 ID，例如 gen_real_R05"
            :disabled="operationPending"
          />
        </el-form-item>
        <el-form-item label="上下文来源">
          <el-radio-group
            :model-value="generationForm.context_source"
            :disabled="operationPending"
            @update:model-value="updateGenerationContextSource"
          >
            <el-radio-button value="run_graph">运行图</el-radio-button>
            <el-radio-button value="scenario_set">场景分类</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="generationForm.context_source === 'scenario_set'" label="来源场景分类">
          <RemoteResourceSelect
            v-model="generationForm.source_scenario_set_id"
            :options="scenarioSetSelectOptions"
            placeholder="从场景分类采样上下文"
            :disabled="operationPending"
            :loading="scenarioSetOptionsLoading"
            @search="searchScenarioSetOptions"
            @visible-change="reloadScenarioSetsOnOpen"
          />
        </el-form-item>
        <el-form-item v-else label="指定运行图">
          <RunGraphSelector
            v-model="generationForm.run_graph"
            :project-id="selectedProjectId"
            placeholder="选择生成使用的运行图"
            :disabled="operationPending"
          />
        </el-form-item>
        <el-form-item label="输出场景前缀">
          <el-input v-model="generationForm.output_prefix" :disabled="operationPending" />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="生成样本数" :tip="GENERATION_FIELD_TIPS.num_samples" />
          </template>
          <el-input-number v-model="generationForm.num_samples" :min="1" :disabled="operationPending" />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="随机种子" :tip="GENERATION_FIELD_TIPS.seed" />
          </template>
          <el-input-number v-model="generationForm.seed" :min="0" :disabled="operationPending" />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="设备" :tip="GENERATION_FIELD_TIPS.device" />
          </template>
          <el-select
            v-model="generationForm.device"
            filterable
            allow-create
            default-first-option
            class="full-width"
            :disabled="operationPending"
          >
            <el-option
              v-for="device in DEVICE_OPTIONS"
              :key="device"
              :label="device"
              :value="device"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip
              label="中断判定阈值"
              :tip="GENERATION_FIELD_TIPS.speed_interruption_threshold"
            />
          </template>
          <el-input-number
            v-model="generationForm.speed_interruption_threshold"
            :min="0"
            :step="1"
            :disabled="operationPending"
          />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="覆盖同名集合" :tip="GENERATION_FIELD_TIPS.overwrite" />
          </template>
          <el-switch v-model="generationForm.overwrite" :disabled="operationPending" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="operationPending" @click="generationDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '生成场景'"
          :disabled="operationPending"
          @click="submitGeneration"
        >
          使用模型生成场景
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="planCreateDialogVisible" title="构建调整计划" width="640px">
      <el-form label-width="150px">
        <el-form-item label="场景分类">
          <el-input :model-value="loadedScenarioSetId || selectedScenarioSetId" disabled />
        </el-form-item>
        <el-form-item label="调整计划 ID">
          <el-input
            v-model="newPlanId"
            placeholder="例如 plan_reference"
            :disabled="operationPending"
            @keydown.enter.prevent="createAdjustmentPlan"
          />
        </el-form-item>
        <el-form-item label="构建来源">
          <el-radio-group v-model="planBuildForm.source" :disabled="operationPending">
            <el-radio-button value="scenario_set">从场景分类中构建</el-radio-button>
            <el-radio-button value="scenario">从场景中构建</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="planBuildForm.source === 'scenario'" label="场景">
          <RemoteResourceSelect
            v-model="planBuildForm.scenario_id"
            :options="scenarioSelectOptions"
            placeholder="选择单个场景"
            :disabled="operationPending"
            :loading="scenarioOptionsLoading"
            @search="loadScenarioOptions"
            @visible-change="reloadScenarioOptionsOnOpen"
          />
        </el-form-item>
        <el-collapse :model-value="['build-options']">
          <el-collapse-item title="构建参数" name="build-options">
            <BuildOptionsFields
              :model-value="planBuildForm"
              @update:model-value="updatePlanBuildOptions"
            />
          </el-collapse-item>
        </el-collapse>
      </el-form>
      <template #footer>
        <el-button :disabled="operationPending" @click="planCreateDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '构建调整计划'"
          :disabled="operationPending"
          @click="createAdjustmentPlan"
        >
          提交构建
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="planBuildDialogVisible" title="构建/重建调整计划" width="640px">
      <el-form label-width="150px">
        <el-form-item label="调整计划 ID">
          <el-input :model-value="loadedPlanId" disabled />
        </el-form-item>
        <el-form-item label="构建来源">
          <el-radio-group v-model="planBuildForm.source" :disabled="operationPending">
            <el-radio-button value="scenario_set">从场景分类中构建</el-radio-button>
            <el-radio-button value="scenario">从场景中构建</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="场景分类">
          <RemoteResourceSelect
            v-model="planBuildForm.scenario_set_id"
            :options="scenarioSetSelectOptions"
            placeholder="选择场景分类"
            :disabled="operationPending"
            :loading="scenarioSetOptionsLoading"
            @search="searchScenarioSetOptions"
            @visible-change="reloadScenarioSetsOnOpen"
            @change="onPlanBuildScenarioSetChange"
          />
        </el-form-item>
        <el-form-item v-if="planBuildForm.source === 'scenario'" label="场景">
          <RemoteResourceSelect
            v-model="planBuildForm.scenario_id"
            :options="scenarioSelectOptions"
            placeholder="选择单个场景"
            :disabled="operationPending"
            :loading="scenarioOptionsLoading"
            @search="loadScenarioOptions"
            @visible-change="reloadScenarioOptionsOnOpen"
          />
        </el-form-item>
        <el-collapse :model-value="['build-options']">
          <el-collapse-item title="构建参数" name="build-options">
            <BuildOptionsFields
              :model-value="planBuildForm"
              @update:model-value="updatePlanBuildOptions"
            />
          </el-collapse-item>
        </el-collapse>
        <el-alert
          title="构建会写入并覆盖当前调整计划的 build 产物；从单个场景构建的计划，后续求解和导出也只处理该场景。"
          type="info"
          show-icon
          :closable="false"
        />
      </el-form>
      <template #footer>
        <el-button :disabled="operationPending" @click="planBuildDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '构建调整计划'"
          :disabled="operationPending"
          @click="submitBuildPlan"
        >
          确认构建
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="solveDialogVisible" title="求解参数" width="560px">
      <el-form label-width="150px">
        <el-form-item label="求解范围">
          <el-tag v-if="solveTargetCaseId" type="primary">{{ solveTargetCaseId }}</el-tag>
          <el-tag v-else type="primary">全部实例</el-tag>
        </el-form-item>
        <el-form-item v-if="!solveTargetCaseId" label="数量上限">
          <el-input-number v-model="planRunForm.solveLimit" :min="0" :disabled="operationPending" />
          <span class="form-hint">0 表示全部</span>
        </el-form-item>
        <el-form-item v-if="!solveTargetCaseId" label="已有解则跳过">
          <el-switch v-model="planRunForm.skipSolved" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="单次限时秒数">
          <el-input-number v-model="planRunForm.solveTimeLimit" :min="0" :disabled="operationPending" />
          <span class="form-hint">0 表示不限制</span>
        </el-form-item>
        <el-form-item label="MIP Gap">
          <el-input-number
            v-model="planRunForm.solveMipGap"
            :min="0"
            :step="0.001"
            :disabled="operationPending"
          />
        </el-form-item>
        <el-form-item label="线程数">
          <el-input-number v-model="planRunForm.solveThreads" :min="0" :disabled="operationPending" />
          <span class="form-hint">0 表示 Gurobi 默认</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="operationPending" @click="solveDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '求解'"
          :disabled="operationPending"
          @click="submitSolveDialog"
        >
          开始求解
        </el-button>
      </template>
    </el-dialog>

    <TimetableDialog
      v-if="timetableDialogVisible"
      v-model="timetableDialogVisible"
      :project-id="selectedProjectId"
      :scenario-set-id="loadedScenarioSetId"
      :plan-id="loadedPlanId"
      :case-id="timetableCaseId"
    />

    <TaskLogDialog v-model="taskLogDialogVisible" :task="taskLogTarget" />
  </div>
</template>
