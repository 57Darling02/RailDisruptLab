<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ScrollbarInstance, UploadFile, UploadUserFile } from 'element-plus'

import { api, ApiError } from '@/api/client'
import FieldLabelTip from '@/components/FieldLabelTip.vue'
import TaskPanel from '@/components/TaskPanel.vue'
import TimetableDialog from '@/components/TimetableDialog.vue'
import TaskLogDialog from '@/components/TaskLogDialog.vue'
import AblationView from '@/views/AblationView.vue'
import DashboardView from '@/views/DashboardView.vue'
import DatasetsView from '@/views/DatasetsView.vue'
import ModelsView from '@/views/ModelsView.vue'
import ScenarioSetsView from '@/views/ScenarioSetsView.vue'
import {
  isTaskCancellable,
  isTaskFailed,
  isTaskSuccessful,
  isTaskTerminal,
  taskDisplayStatus,
  taskTagType,
} from '@/task-status'
import type { TaskTagType } from '@/task-status'
import type {
  ArtifactGroup,
  DatasetBuildForm,
  DatasetRunForm,
  MetadataEntry,
  SchemaEdgeRow,
  SchemaPoolRow,
  SchemaTaskRow,
  TrainForm,
} from '@/views/types'
import type {
  ArtifactSummary,
  CaseTimetableState,
  DatasetSummary,
  JsonObject,
  ModelCheckpoint,
  ModelDetail,
  PlanTimetableState,
  ProjectState,
  ProjectSummary,
  ScenarioOptions,
  ScenarioSetVisualization,
  ScenarioSummary,
  Task,
} from '@/types'

type PageKey = 'dashboard' | 'scenarios' | 'datasets' | 'models' | 'ablation-scenarios' | 'ablation-datasets'
type DatasetBuildSource = 'scenario_set' | 'scenario'
type DatasetCreateMode = 'empty' | 'scenario_set'
type ScenarioDelayForm = { event_anchor_id: string; seconds: number }
type ScenarioSpeedLimitForm = {
  section_anchor_id: string
  start_time: string
  duration: number
  limit_speed: number
}

const SHORT_TASK_WAIT_MS = 12000
const SHORT_TASK_POLL_MS = 500
const TASK_POLL_MS = 2500
const TASK_DURATION_TICK_MS = 1000
const DEFAULT_DATASET_RUN_FORM: DatasetRunForm = {
  solveLimit: 0,
  solveTimeLimit: 120,
  solveMipGap: 0,
  solveThreads: 0,
  skipSolved: false,
}
const DEFAULT_DATASET_BUILD_FORM: DatasetBuildForm = {
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
  batch_size: 8,
  lr: 0.0003,
  seed: 1,
  device: 'auto',
  count_weight: 1,
  anchor_weight: 1,
  param_weight: 2,
  kl_weight: 0.0015,
}
const DEFAULT_SPEED_INTERRUPTION_THRESHOLD = 20
const DEVICE_OPTIONS = ['auto', 'cpu', 'cuda:0', 'cuda:1', 'cuda:2', 'cuda:3']
const TRAIN_FIELD_TIPS = {
  model_id: '本次训练产物的扰动生成模型目录 ID，用于后续选择 checkpoint 生成场景。',
  scenario_set_id: '训练样本来源，固定使用一个完整扰动场景集。',
  max_slots: '每类扰动最多保留/预测的事件槽位数，决定辅助扰动图的目标容量。',
  event_time_window: '判断两个时刻事件是否存在近邻关系的时间窗口，单位秒。',
  event_top_k: '每个时刻事件最多连接的近邻事件数量，用于控制辅助扰动图稠密度。',
  section_order_window: '沿线路顺序连接前后区间的窗口大小，用于表达邻近区间关系。',
  hidden_dim: 'VAE 编码器/解码器隐藏层维度，越大表达能力越强但训练更重。',
  latent_dim: '潜变量维度，控制扰动生成模型压缩扰动模式的容量。',
  message_passing_steps: '图神经网络消息传递轮数，越大可聚合更远邻域信息。',
  epochs: '完整遍历训练扰动场景集的轮数。',
  batch_size: '每次优化使用的样本数量。',
  lr: '优化器学习率。',
  seed: '随机种子，用于复现实验。',
  device: '训练设备，auto 会优先使用 CUDA；指定 GPU 卡号可填写 cuda:0、cuda:1，CPU 填 cpu。',
  count_weight: '扰动数量预测损失权重。',
  anchor_weight: '扰动锚点位置预测损失权重。',
  param_weight: '扰动参数预测损失权重，例如延误秒数、限速速度等。',
  kl_weight: 'VAE KL 散度损失权重，控制潜空间正则强度。',
} as const
const GENERATION_FIELD_TIPS = {
  scenario_set_id: '扰动生成模型生成的场景会写入这个扰动场景集。',
  num_samples: '本次从扰动生成模型采样并解码出的场景数量。',
  seed: '生成随机种子，用于复现采样结果。',
  device: '生成使用的设备，auto 会优先使用 CUDA；指定 GPU 卡号可填写 cuda:0、cuda:1，CPU 填 cpu。',
  speed_interruption_threshold:
    '生成解码时，低于该速度阈值的限速会被转成 limit_speed=0；后续 build 会按中断建模。',
  overwrite: '开启后会覆盖同名扰动场景集。',
} as const
const TASK_LABELS = {
  dashboard: ['newproject', 'deleteproject', 'source_delete', 'prepare'],
  scenarios: ['normal_generate', 'scenario_set_create', 'scenario_add', 'scenario_delete'],
  datasets: ['dataset_create', 'build', 'solve', 'export_timetable'],
  models: ['train', 'generation'],
} as const
const PAGE_TASK_FILTERS = [
  { value: 'dashboard', label: '仪表盘', labels: TASK_LABELS.dashboard },
  { value: 'scenarios', label: '构建扰动场景', labels: TASK_LABELS.scenarios },
  { value: 'datasets', label: '构建MILP实例', labels: TASK_LABELS.datasets },
  { value: 'models', label: '扰动生成模型', labels: TASK_LABELS.models },
  { value: 'ablation', label: '消融分析', labels: [] },
] as const
const TRAINING_CONFIG_LABELS: Record<string, string> = {
  created_at: '训练时间',
  graphs_root: '训练图目录',
  hidden_dim: '隐藏维度',
  latent_dim: '潜变量维度',
  message_passing_steps: '消息传递步数',
  epochs: '训练轮数',
  batch_size: 'Batch Size',
  lr: '学习率',
  seed: '随机种子',
  device: '设备',
  count_weight: 'Count 权重',
  anchor_weight: 'Anchor 权重',
  param_weight: 'Param 权重',
  kl_weight: 'KL 权重',
}
const TRAINING_CONFIG_ORDER = Object.keys(TRAINING_CONFIG_LABELS)

const projects = ref<ProjectSummary[]>([])
const selectedProjectId = ref('')
const project = ref<ProjectState | null>(null)
const planTimetable = ref<PlanTimetableState | null>(null)
const tasks = ref<Task[]>([])
const taskNow = ref(Date.now())
const activePage = ref<PageKey>('dashboard')
const busy = ref(false)
const mainScrollbar = ref<ScrollbarInstance>()

const projectDialogVisible = ref(false)
const newProjectId = ref('')

const prepareDialogVisible = ref(false)
const prepareTimetableFiles = ref<UploadUserFile[]>([])
const prepareMileageFiles = ref<UploadUserFile[]>([])
const prepareForm = ref({
  timetable_file: null as File | null,
  mileage_file: null as File | null,
  timetable_sheet_name: 'Sheet1',
  mileage_sheet_name: 'Sheet1',
})

const selectedScenarioSetId = ref('')
const scenarios = ref<ScenarioSummary[]>([])
const scenarioSetVisualization = ref<ScenarioSetVisualization | null>(null)
const scenarioSetLoading = ref(false)
const scenarioSetDialogVisible = ref(false)
const newScenarioSetId = ref('')
const scenarioDialogVisible = ref(false)
const scenarioId = ref('manual_case')
const scenarioOverwrite = ref(false)
const scenarioOptions = ref<ScenarioOptions | null>(null)
const scenarioDelays = ref<ScenarioDelayForm[]>([])
const scenarioSpeedLimits = ref<ScenarioSpeedLimitForm[]>([])
const normalGenerateDialogVisible = ref(false)
const normalGenerateForm = ref({
  seed: 20260320,
  delay_count: 10,
  speed_count: 10,
  interruption_count: 10,
  combo_per_type: 10,
})

const selectedDatasetId = ref('')
const datasetArtifacts = ref<ArtifactSummary[]>([])
const datasetCreateDialogVisible = ref(false)
const datasetCreateMode = ref<DatasetCreateMode>('scenario_set')
const newDatasetId = ref('')
const datasetCreateScenarioSetId = ref('')
const datasetBuildDialogVisible = ref(false)
const datasetBuildForm = ref({
  scenario_set_id: '',
  source: 'scenario_set' as DatasetBuildSource,
  scenario_id: '',
  ...DEFAULT_DATASET_BUILD_FORM,
})
const solveDialogVisible = ref(false)
const solveTargetCaseId = ref('')
const timetableDialogVisible = ref(false)
const caseTimetable = ref<CaseTimetableState | null>(null)
const taskLogDialogVisible = ref(false)
const taskLogTarget = ref<Task | null>(null)
const datasetRunForm = ref<DatasetRunForm>({ ...DEFAULT_DATASET_RUN_FORM })

const selectedModelId = ref('')
const pendingModelId = ref('')
const pendingModelTaskId = ref<number | null>(null)
const modelDetail = ref<ModelDetail | null>(null)
const trainDialogVisible = ref(false)
const trainDialogMode = ref<'create' | 'retrain'>('create')
const generationDialogVisible = ref(false)
const trainForm = reactive<TrainForm>({ ...DEFAULT_TRAIN_FORM })
const trainModelSuffix = ref('')
const generationScenarioSetSuffix = ref('')
const generationForm = ref({
  checkpoint: '',
  scenario_set_id: '',
  num_samples: 100,
  seed: 1,
  device: 'auto',
  speed_interruption_threshold: DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
  overwrite: false,
})

let pollHandle = 0
let durationTickHandle = 0

const hasProject = computed(() => Boolean(selectedProjectId.value && project.value?.exists))
const originalGraphActive = computed(() => Boolean(project.value?.has_context))
const trainModelPrefix = computed(() => {
  const scenarioSetId = trainForm.scenario_set_id.trim()
  return scenarioSetId ? `train_${scenarioSetId}` : ''
})
const generationScenarioSetPrefix = computed(() => selectedModelId.value.trim())
const scenarioSets = computed(() => project.value?.scenario_sets ?? [])
const datasets = computed(() => project.value?.datasets ?? [])
const models = computed(() => project.value?.models ?? [])
const selectedDataset = computed(
  () => datasets.value.find((item) => item.dataset_id === selectedDatasetId.value) ?? null,
)
const selectedModel = computed(
  () => models.value.find((item) => item.model_id === selectedModelId.value) ?? null,
)
const taskProjectOptions = computed(() => [
  { label: '全部项目', value: '' },
  ...projects.value.map((item) => ({ label: item.project_id, value: item.project_id })),
])
const datasetArtifactGroups = computed(() => groupArtifactsByCase(datasetArtifacts.value))
const selectedBuildScenarios = computed(() =>
  selectedScenarioSetId.value === datasetBuildForm.value.scenario_set_id ? scenarios.value : [],
)
const scenarioEventOptions = computed(() => scenarioOptions.value?.event_anchors ?? [])
const scenarioSectionOptions = computed(() => scenarioOptions.value?.section_anchors ?? [])
const trainingSummary = computed(() => modelDetail.value?.summary ?? null)
const modelCheckpoints = computed(() => modelDetail.value?.checkpoints ?? [])
const modelSummaryEntries = computed(() =>
  modelInfoEntries(trainingSummary.value, modelDetail.value?.history),
)
const modelConfigEntries = computed(() => trainingConfigEntries(modelDetail.value?.config ?? {}))
const modelSchemaSummaryEntries = computed(() =>
  modelSchemaSummary(modelDetail.value?.schema ?? {}),
)
const modelPoolRows = computed(() => schemaPoolRows(modelDetail.value?.schema ?? {}))
const modelEdgeRows = computed(() => schemaEdgeRows(modelDetail.value?.schema ?? {}))
const modelTaskRows = computed(() => schemaTaskRows(modelDetail.value?.schema ?? {}))
const hasTrainingSummary = computed(() => hasEntries(trainingSummary.value))
const hasTrainingConfig = computed(() => hasEntries(modelDetail.value?.config))
const hasSchemaSummary = computed(() => hasEntries(modelDetail.value?.schema))
const scenarioTasks = computed(() => filterTasks(TASK_LABELS.scenarios))
const datasetTasks = computed(() => filterTasks(TASK_LABELS.datasets))
const modelTasks = computed(() => filterTasks(TASK_LABELS.models))
const taskPageOptions = computed(() => [
  { label: '全部页面', value: '' },
  ...PAGE_TASK_FILTERS.map((item) => ({ label: item.label, value: item.value })),
])
const visibleTasks = computed(() => tasks.value)
const hasRunningTasks = computed(() => tasks.value.some((task) => !isTaskTerminal(task)))
const projectTasks = computed(() => tasks.value.filter((task) => task.group === selectedProjectId.value))
const runningTaskCount = computed(() => projectTasks.value.filter((task) => !isTaskTerminal(task)).length)
const doneTaskCount = computed(() => projectTasks.value.filter(isTaskSuccessful).length)
const failedTaskCount = computed(() => projectTasks.value.filter(isTaskFailed).length)

watch(selectedProjectId, async (_projectId, previousProjectId) => {
  resetPrepareForm()
  if (previousProjectId) {
    selectedScenarioSetId.value = ''
    selectedDatasetId.value = ''
    selectedModelId.value = ''
    planTimetable.value = null
  }
  await loadSelectedProject()
})

watch(activePage, async () => {
  await scrollMainToTop()
  await hydrateActivePage()
})

watch(selectedScenarioSetId, async () => {
  await loadScenarioSetData()
})

watch(selectedDatasetId, async () => {
  await loadDatasetArtifacts()
})

watch(datasetCreateMode, (mode) => {
  if (mode === 'scenario_set' && !datasetCreateScenarioSetId.value) {
    datasetCreateScenarioSetId.value = selectedScenarioSetId.value || scenarioSets.value[0]?.scenario_set_id || ''
    syncDatasetCreateId()
  }
  if (mode === 'empty' && !newDatasetId.value) {
    newDatasetId.value = ''
  }
})

watch(datasetCreateScenarioSetId, () => {
  if (datasetCreateMode.value === 'scenario_set') syncDatasetCreateId()
})

watch(selectedModelId, async () => {
  if (activePage.value === 'models') await loadModelDetails(false)
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

watch(generationScenarioSetSuffix, () => {
  if (generationDialogVisible.value) syncGenerationScenarioSetId()
})

watch(hasRunningTasks, (hasRunning) => {
  if (hasRunning) {
    startDurationTick()
  } else {
    stopDurationTick()
  }
})

onMounted(async () => {
  await bootstrap()
  pollHandle = window.setInterval(() => {
    void pollTasks()
  }, TASK_POLL_MS)
  if (hasRunningTasks.value) startDurationTick()
})

onUnmounted(() => {
  window.clearInterval(pollHandle)
  stopDurationTick()
})

async function bootstrap() {
  await run('连接后端', async () => {
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

async function loadSelectedProject(showMessage = true) {
  if (!selectedProjectId.value) {
    project.value = null
    planTimetable.value = null
    return
  }
  try {
    project.value = await api.getProject(selectedProjectId.value)
    if (planTimetable.value?.project_id !== selectedProjectId.value) {
      planTimetable.value = null
    }
    selectFirstOptions()
    await hydrateActivePage()
  } catch (error) {
    project.value = null
    planTimetable.value = null
    if (showMessage) notifyError(error)
  }
}

function selectFirstOptions() {
  if (!project.value) return
  if (
    !selectedScenarioSetId.value ||
    !project.value.scenario_sets.some(
      (item) => item.scenario_set_id === selectedScenarioSetId.value,
    )
  ) {
    selectedScenarioSetId.value = project.value.scenario_sets[0]?.scenario_set_id ?? ''
  }
  if (
    !selectedDatasetId.value ||
    !project.value.datasets.some((item) => item.dataset_id === selectedDatasetId.value)
  ) {
    selectedDatasetId.value = project.value.datasets[0]?.dataset_id ?? ''
  }
  const readyPendingModel = project.value.models.find((item) => item.model_id === pendingModelId.value)
  if (readyPendingModel) {
    selectedModelId.value = readyPendingModel.model_id
    clearPendingModel()
  } else if (
    !selectedModelId.value ||
    !project.value.models.some((item) => item.model_id === selectedModelId.value)
  ) {
    selectedModelId.value = project.value.models[0]?.model_id ?? ''
  }
  reconcilePendingModel()
}

async function hydrateActivePage() {
  if (!hasProject.value) return
  if (activePage.value === 'dashboard') await loadPlanTimetable(false)
  if (activePage.value === 'scenarios') {
    await loadScenarioSetData(false)
  }
  if (activePage.value === 'datasets') await loadDatasetArtifacts(false)
  if (activePage.value === 'models') await loadModelDetails(false)
}

async function loadPlanTimetable(showMessage = true) {
  if (!selectedProjectId.value || !originalGraphActive.value) {
    planTimetable.value = null
    return
  }
  if (planTimetable.value?.project_id === selectedProjectId.value) return
  try {
    planTimetable.value = await api.readPlanTimetable(selectedProjectId.value)
  } catch (error) {
    planTimetable.value = null
    if (showMessage) notifyError(error)
  }
}

async function refreshTasks(showMessage = true) {
  try {
    tasks.value = await api.listTasks()
    reconcilePendingModel()
  } catch (error) {
    if (showMessage) notifyError(error)
  }
}

async function pollTasks() {
  taskNow.value = Date.now()
  await refreshTasks(false)
  if (selectedProjectId.value) await loadSelectedProject(false)
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

async function createProject() {
  const projectId = newProjectId.value.trim()
  if (!projectId) return
  await run('创建项目', async () => {
    const response = await api.createProject(projectId)
    const message = await finishShortTask(response.task, '创建项目')
    newProjectId.value = ''
    projectDialogVisible.value = false
    await refreshProjects()
    selectedProjectId.value = projectId
    await loadSelectedProject(false)
    return message
  })
}

async function removeSelectedProject() {
  if (!selectedProjectId.value) return
  try {
    await ElMessageBox.confirm(
      `确认移除项目 ${selectedProjectId.value}？该操作会删除本地项目目录。`,
      '移除项目',
      {
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await run('移除项目', async () => {
    const response = await api.deleteProject(selectedProjectId.value)
    const message = await finishShortTask(response.task, '移除项目')
    selectedProjectId.value = ''
    project.value = null
    await refreshProjects()
    return message
  })
}

function openPrepareDialog() {
  resetPrepareForm()
  prepareDialogVisible.value = true
}

async function submitPrepare() {
  if (!prepareForm.value.timetable_file || !prepareForm.value.mileage_file) {
    ElMessage.warning('请上传时刻表和里程表文件。')
    return
  }
  await run('激活原计划运行图', async () => {
    const response = await api.activatePlan(
      selectedProjectId.value,
      prepareForm.value.timetable_file as File,
      prepareForm.value.mileage_file as File,
      prepareForm.value.timetable_sheet_name,
      prepareForm.value.mileage_sheet_name,
    )
    trackTask(response.task)
    planTimetable.value = null
    prepareDialogVisible.value = false
    resetPrepareForm()
  })
}

async function createScenarioSet() {
  const scenarioSetId = newScenarioSetId.value.trim()
  if (!scenarioSetId) return
  await run('创建扰动场景集', async () => {
    const response = await api.createScenarioSet(selectedProjectId.value, scenarioSetId)
    const message = await finishShortTask(response.task, '创建扰动场景集')
    selectedScenarioSetId.value = scenarioSetId
    newScenarioSetId.value = ''
    scenarioSetDialogVisible.value = false
    await loadSelectedProject(false)
    await loadScenarioSetData(false)
    return message
  })
}

async function deleteScenarioSetById(scenarioSetId: string) {
  if (!selectedProjectId.value || !scenarioSetId) return
  try {
    await ElMessageBox.confirm(
      `确认删除扰动场景集 ${scenarioSetId}？该操作会删除对应场景文件目录。`,
      '删除扰动场景集',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await run('删除扰动场景集', async () => {
    await api.deleteScenarioSet(selectedProjectId.value, scenarioSetId)
    if (selectedScenarioSetId.value === scenarioSetId) {
      selectedScenarioSetId.value = ''
      scenarios.value = []
      scenarioSetVisualization.value = null
    }
    await loadSelectedProject(false)
    return `扰动场景集 ${scenarioSetId} 已删除`
  })
}

async function loadScenarioSetData(showMessage = true) {
  const projectId = selectedProjectId.value
  const scenarioSetId = selectedScenarioSetId.value
  if (showMessage) scenarioSetLoading.value = true
  try {
    await loadScenarios(showMessage, projectId, scenarioSetId)
    await loadScenarioSetVisualization(showMessage, projectId, scenarioSetId)
  } finally {
    if (
      showMessage &&
      projectId === selectedProjectId.value &&
      scenarioSetId === selectedScenarioSetId.value
    ) {
      scenarioSetLoading.value = false
    }
  }
}

async function loadScenarios(
  showMessage = true,
  projectId = selectedProjectId.value,
  scenarioSetId = selectedScenarioSetId.value,
) {
  if (!projectId || !scenarioSetId) {
    if (projectId === selectedProjectId.value && scenarioSetId === selectedScenarioSetId.value) {
      scenarios.value = []
      scenarioSetVisualization.value = null
    }
    return
  }
  try {
    const result = await api.listScenarios(projectId, scenarioSetId)
    if (projectId === selectedProjectId.value && scenarioSetId === selectedScenarioSetId.value) {
      scenarios.value = result
    }
  } catch (error) {
    if (projectId === selectedProjectId.value && scenarioSetId === selectedScenarioSetId.value) {
      scenarios.value = []
    }
    if (showMessage) notifyError(error)
  }
}

async function loadScenarioSetVisualization(
  showMessage = true,
  projectId = selectedProjectId.value,
  scenarioSetId = selectedScenarioSetId.value,
) {
  if (!projectId || !scenarioSetId) {
    if (projectId === selectedProjectId.value && scenarioSetId === selectedScenarioSetId.value) {
      scenarioSetVisualization.value = null
    }
    return
  }
  try {
    const result = await api.readScenarioSetVisualization(projectId, scenarioSetId)
    if (projectId === selectedProjectId.value && scenarioSetId === selectedScenarioSetId.value) {
      scenarioSetVisualization.value = result
    }
  } catch (error) {
    if (projectId === selectedProjectId.value && scenarioSetId === selectedScenarioSetId.value) {
      scenarioSetVisualization.value = null
    }
    if (showMessage) notifyError(error)
  }
}

async function reloadScenarioSetsOnOpen(visible: boolean) {
  if (!visible) return
  await loadSelectedProject(false)
  await loadScenarioSetData(false)
}

async function openScenarioDialog() {
  if (!selectedScenarioSetId.value) {
    ElMessage.warning('请先选择扰动场景集。')
    return
  }
  if (!originalGraphActive.value) {
    ElMessage.warning('请先激活原计划运行图。')
    return
  }
  await ensureScenarioOptions()
  scenarioId.value = nextScenarioId()
  scenarioOverwrite.value = false
  scenarioDelays.value = []
  scenarioSpeedLimits.value = []
  scenarioDialogVisible.value = true
}

async function ensureScenarioOptions() {
  if (scenarioOptions.value?.project_id === selectedProjectId.value) return
  scenarioOptions.value = await api.readScenarioOptions(selectedProjectId.value)
}

function addDelayRow() {
  scenarioDelays.value.push({
    event_anchor_id: scenarioEventOptions.value[0]?.anchor_id ?? '',
    seconds: 600,
  })
}

function removeDelayRow(index: number) {
  scenarioDelays.value.splice(index, 1)
}

function addSpeedLimitRow(limitSpeed = 160) {
  scenarioSpeedLimits.value.push({
    section_anchor_id: scenarioSectionOptions.value[0]?.anchor_id ?? '',
    start_time: '08:00:00',
    duration: 1800,
    limit_speed: limitSpeed,
  })
}

function removeSpeedLimitRow(index: number) {
  scenarioSpeedLimits.value.splice(index, 1)
}

async function addScenario() {
  const id = scenarioId.value.trim()
  if (!id) return
  if (!scenarioDelays.value.length && !scenarioSpeedLimits.value.length) {
    ElMessage.warning('请至少添加一个扰动。')
    return
  }
  await run('新增场景', async () => {
    const response = await api.addScenario(
      selectedProjectId.value,
      selectedScenarioSetId.value,
      id,
      scenarioPayload(),
      scenarioOverwrite.value,
    )
    const message = await finishShortTask(response.task, '新增场景')
    scenarioDialogVisible.value = false
    await loadSelectedProject(false)
    await loadScenarioSetData(false)
    return message
  })
}

function scenarioPayload() {
  return {
    delays: scenarioDelays.value
      .filter((item) => item.event_anchor_id)
      .map((item) => ({
        event_anchor_id: item.event_anchor_id,
        seconds: Math.floor(positiveNumber(item.seconds, 600)),
      })),
    speed_limits: scenarioSpeedLimits.value
      .filter((item) => item.section_anchor_id)
      .map((item) => ({
        section_anchor_id: item.section_anchor_id,
        start_time: item.start_time || '08:00:00',
        duration: Math.floor(positiveNumber(item.duration, 1800)),
        limit_speed: Math.max(0, Number.isFinite(item.limit_speed) ? item.limit_speed : 160),
      })),
  }
}

async function deleteScenario(id: string) {
  try {
    await ElMessageBox.confirm(`确认删除场景 ${id}？`, '删除场景', { type: 'warning' })
  } catch {
    return
  }
  await run('删除场景', async () => {
    const response = await api.deleteScenario(
      selectedProjectId.value,
      selectedScenarioSetId.value,
      id,
    )
    const message = await finishShortTask(response.task, '删除场景')
    await loadSelectedProject(false)
    await loadScenarioSetData(false)
    return message
  })
}

function openNormalGenerateDialog() {
  if (!selectedScenarioSetId.value) {
    ElMessage.warning('请先选择扰动场景集。')
    return
  }
  normalGenerateDialogVisible.value = true
}

async function submitNormalGenerate() {
  if (!selectedScenarioSetId.value) return
  await run('批量生成场景', async () => {
    const response = await api.submitNormalGenerate(selectedProjectId.value, {
        scenario_set_id: selectedScenarioSetId.value,
        merge: true,
        overwrite: true,
        ...normalGenerateForm.value,
      })
    trackTask(response.task)
    normalGenerateDialogVisible.value = false
    await loadScenarioSetData(false)
  })
}

async function submitBuild() {
  const datasetId = selectedDatasetId.value.trim()
  const scenarioSetId = datasetBuildForm.value.scenario_set_id.trim()
  const scenarioId =
    datasetBuildForm.value.source === 'scenario' ? datasetBuildForm.value.scenario_id.trim() : ''
  if (!datasetId || !scenarioSetId) {
    ElMessage.warning('请先选择 MILP 实例集和场景来源。')
    return
  }
  if (datasetBuildForm.value.source === 'scenario' && !scenarioId) {
    ElMessage.warning('请选择要构建的场景。')
    return
  }
  await run('提交构建任务', async () => {
    const response = await api.submitBuild(
      selectedProjectId.value,
      scenarioSetId,
      datasetId,
      scenarioId,
      normalizedBuildOptions(),
    )
    trackTask(response.task)
    selectedDatasetId.value = datasetId
    datasetBuildDialogVisible.value = false
  })
}

function normalizedBuildOptions(): DatasetBuildForm {
  return {
    objective_delay_weight: positiveNumber(
      datasetBuildForm.value.objective_delay_weight,
      DEFAULT_DATASET_BUILD_FORM.objective_delay_weight,
    ),
    objective_mode: datasetBuildForm.value.objective_mode || DEFAULT_DATASET_BUILD_FORM.objective_mode,
    cancellation_enabled: Boolean(datasetBuildForm.value.cancellation_enabled),
    cancellation_penalty_weight: positiveNumber(
      datasetBuildForm.value.cancellation_penalty_weight,
      DEFAULT_DATASET_BUILD_FORM.cancellation_penalty_weight,
    ),
    arr_arr_headway_seconds: Math.floor(
      positiveNumber(
        datasetBuildForm.value.arr_arr_headway_seconds,
        DEFAULT_DATASET_BUILD_FORM.arr_arr_headway_seconds,
      ),
    ),
    dep_dep_headway_seconds: Math.floor(
      positiveNumber(
        datasetBuildForm.value.dep_dep_headway_seconds,
        DEFAULT_DATASET_BUILD_FORM.dep_dep_headway_seconds,
      ),
    ),
    dwell_seconds_at_stops: Math.floor(
      positiveNumber(
        datasetBuildForm.value.dwell_seconds_at_stops,
        DEFAULT_DATASET_BUILD_FORM.dwell_seconds_at_stops,
      ),
    ),
    big_m: Math.floor(positiveNumber(datasetBuildForm.value.big_m, DEFAULT_DATASET_BUILD_FORM.big_m)),
    tolerance_delay_seconds: Math.floor(
      positiveNumber(
        datasetBuildForm.value.tolerance_delay_seconds,
        DEFAULT_DATASET_BUILD_FORM.tolerance_delay_seconds,
      ),
    ),
  }
}

function positiveNumber(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback
}

async function createDataset() {
  const importScenarioSet = datasetCreateMode.value === 'scenario_set'
  const scenarioSetId = datasetCreateScenarioSetId.value.trim()
  if (importScenarioSet) syncDatasetCreateId()
  const datasetId = newDatasetId.value.trim()
  if (!datasetId) {
    ElMessage.warning(
      importScenarioSet
        ? '请先选择要引入的扰动场景集。'
        : '请填写 MILP 实例集 ID。',
    )
    return
  }
  if (importScenarioSet && !scenarioSetId) {
    ElMessage.warning('请先选择要引入的扰动场景集。')
    return
  }
  await run('新增 MILP 实例集', async () => {
    const response = await api.createDataset(selectedProjectId.value, datasetId)
    const message = importScenarioSet
      ? await requireShortTaskSuccess(response.task, '新增 MILP 实例集')
      : await finishShortTask(response.task, '新增 MILP 实例集')
    selectedDatasetId.value = datasetId
    if (importScenarioSet) {
      selectedScenarioSetId.value = scenarioSetId
      const buildResponse = await api.submitBuild(
        selectedProjectId.value,
        scenarioSetId,
        datasetId,
        '',
        defaultBuildOptions(),
      )
      trackTask(buildResponse.task)
    }
    resetDatasetCreateForm()
    datasetCreateDialogVisible.value = false
    await loadSelectedProject(false)
    await loadDatasetArtifacts(false)
    return importScenarioSet
      ? `${message}，已提交从扰动场景集 ${scenarioSetId} 构建任务`
      : message
  })
}

async function deleteDatasetById(datasetId: string) {
  if (!selectedProjectId.value || !datasetId) return
  try {
    await ElMessageBox.confirm(
      `确认删除 MILP 实例集 ${datasetId}？该操作会删除构建、求解和时刻表产物。`,
      '删除 MILP 实例集',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await run('删除 MILP 实例集', async () => {
    await api.deleteDataset(selectedProjectId.value, datasetId)
    if (selectedDatasetId.value === datasetId) {
      selectedDatasetId.value = ''
      datasetArtifacts.value = []
    }
    await loadSelectedProject(false)
    return `MILP 实例集 ${datasetId} 已删除`
  })
}

async function submitSolve(caseId = '') {
  if (!selectedDatasetId.value) return
  const options = normalizedSolveOptions()
  await run('提交求解任务', async () => {
    const response = await api.submitSolve(
      selectedProjectId.value,
      selectedDatasetId.value,
      caseId ? 0 : options.solveLimit,
      options.solveTimeLimit,
      caseId,
      options.solveMipGap,
      options.solveThreads,
      caseId ? false : options.skipSolved,
    )
    trackTask(response.task)
    solveDialogVisible.value = false
  })
}

async function submitExportTimetable(caseId = '') {
  if (!selectedDatasetId.value) return
  await run('提交导出时刻表任务', async () => {
    const response = await api.submitExportTimetable(
      selectedProjectId.value,
      selectedDatasetId.value,
      0,
      caseId,
    )
    trackTask(response.task)
  })
}

function openSolveDialog(caseId = '') {
  if (!selectedDatasetId.value) return
  solveTargetCaseId.value = caseId
  resetSolveForm()
  solveDialogVisible.value = true
}

async function submitSolveDialog() {
  await submitSolve(solveTargetCaseId.value)
}

function resetSolveForm() {
  datasetRunForm.value = { ...DEFAULT_DATASET_RUN_FORM }
}

function normalizedSolveOptions(): DatasetRunForm {
  return {
    solveLimit: nonNegativeNumber(datasetRunForm.value.solveLimit, DEFAULT_DATASET_RUN_FORM.solveLimit),
    solveTimeLimit: nonNegativeNumber(
      datasetRunForm.value.solveTimeLimit,
      DEFAULT_DATASET_RUN_FORM.solveTimeLimit,
    ),
    solveMipGap: nonNegativeNumber(datasetRunForm.value.solveMipGap, DEFAULT_DATASET_RUN_FORM.solveMipGap),
    solveThreads: Math.floor(
      nonNegativeNumber(datasetRunForm.value.solveThreads, DEFAULT_DATASET_RUN_FORM.solveThreads),
    ),
    skipSolved: Boolean(datasetRunForm.value.skipSolved),
  }
}

function nonNegativeNumber(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback
}

async function loadDatasetArtifacts(showMessage = true) {
  if (!selectedProjectId.value || !selectedDatasetId.value) {
    datasetArtifacts.value = []
    return
  }
  try {
    datasetArtifacts.value = await api.listArtifacts(
      selectedProjectId.value,
      selectedDatasetId.value,
    )
  } catch (error) {
    datasetArtifacts.value = []
    if (showMessage) notifyError(error)
  }
}

async function reloadDatasetsOnOpen(visible: boolean) {
  if (!visible) return
  await loadSelectedProject(false)
  await loadDatasetArtifacts(false)
}

async function openDatasetCreateDialog() {
  datasetCreateMode.value = scenarioSets.value.length ? 'scenario_set' : 'empty'
  datasetCreateScenarioSetId.value = selectedScenarioSetId.value || scenarioSets.value[0]?.scenario_set_id || ''
  newDatasetId.value = ''
  if (datasetCreateMode.value === 'scenario_set') syncDatasetCreateId()
  datasetCreateDialogVisible.value = true
}

function resetDatasetCreateForm() {
  newDatasetId.value = ''
  datasetCreateScenarioSetId.value = ''
  datasetCreateMode.value = 'scenario_set'
}

function defaultBuildOptions(): DatasetBuildForm {
  return { ...DEFAULT_DATASET_BUILD_FORM }
}

function syncDatasetCreateId() {
  newDatasetId.value = datasetCreateScenarioSetId.value.trim()
}

async function openDatasetBuildDialog() {
  if (!selectedDatasetId.value) {
    ElMessage.warning('请先新增或选择一个 MILP 实例集。')
    return
  }
  datasetBuildForm.value.scenario_set_id =
    selectedScenarioSetId.value || scenarioSets.value[0]?.scenario_set_id || ''
  datasetBuildForm.value.source = 'scenario_set'
  datasetBuildForm.value.scenario_id = ''
  if (datasetBuildForm.value.scenario_set_id) {
    selectedScenarioSetId.value = datasetBuildForm.value.scenario_set_id
    await loadScenarios(false)
  }
  datasetBuildDialogVisible.value = true
}

async function onDatasetBuildScenarioSetChange() {
  selectedScenarioSetId.value = datasetBuildForm.value.scenario_set_id
  datasetBuildForm.value.scenario_id = ''
  await loadScenarios(false)
}

async function reloadDatasetBuildScenariosOnOpen(visible: boolean) {
  if (!visible) return
  await onDatasetBuildScenarioSetChange()
}

async function openCaseTimetable(group: ArtifactGroup) {
  if (!selectedProjectId.value || !selectedDatasetId.value) return
  await run('读取时刻表数据', async () => {
    caseTimetable.value = await api.readCaseTimetable(
      selectedProjectId.value,
      selectedDatasetId.value,
      group.case_id,
    )
    timetableDialogVisible.value = true
  })
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
  await run('中断任务', async () => {
    await api.cancelTask(task.id)
    await refreshTasks(false)
    return `任务 #${task.id} 已请求中断`
  })
}

async function cleanTasks(projectId = '') {
  const targetText = projectId ? `项目 ${projectId}` : '全部项目'
  try {
    await ElMessageBox.confirm(
      `清理${targetText}已结束的历史任务？运行中和排队中的任务不会被清理。`,
      '清理历史任务',
      {
        type: 'warning',
        confirmButtonText: '清理',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await run('清理历史任务', async () => {
    const result = await api.cleanTasks(projectId || undefined)
    await refreshTasks(false)
    const removed = Number(result.removed ?? 0)
    return `已清理 ${removed} 个历史任务`
  })
}

async function openTrainDialog(mode: 'create' | 'retrain' = 'create') {
  trainDialogMode.value = mode
  if (mode === 'retrain' && selectedModelId.value) {
    await loadModelDetails(false)
  }
  resetTrainForm(mode)
  trainDialogVisible.value = true
  await nextTick()
  resetTrainForm(mode)
}

function resetTrainForm(mode: 'create' | 'retrain' = trainDialogMode.value) {
  const config = modelDetail.value?.config ?? {}
  const scenarioSetId =
    stringConfigValue(config.scenario_set_id) ||
    selectedScenarioSetId.value ||
    scenarioSets.value[0]?.scenario_set_id ||
    ''
  const modelId = mode === 'retrain' && selectedModelId.value ? selectedModelId.value : ''
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
    ElMessage.warning('请填写扰动生成模型 ID 并选择训练扰动场景集。')
    return
  }
  const existingModel = models.value.find((item) => item.model_id === trainForm.model_id.trim())
  if (existingModel && trainDialogMode.value !== 'retrain') {
    try {
      await ElMessageBox.confirm(
        `扰动生成模型 ${existingModel.model_id} 已存在。重新训练会先删除旧模型产物，再开始训练。`,
        '覆盖训练扰动生成模型',
        { type: 'warning', confirmButtonText: '覆盖并训练', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  await run('提交训练任务', async () => {
    const response = await api.submitTrain(selectedProjectId.value, { ...trainForm })
    trackTask(response.task)
    pendingModelId.value = trainForm.model_id
    pendingModelTaskId.value = response.task.id
    trainDialogVisible.value = false
  })
}

function openGenerationDialog(file: ModelCheckpoint) {
  if (!selectedModelId.value) {
    ElMessage.warning('请先选择扰动生成模型。')
    return
  }
  generationForm.value.checkpoint = file.relative_path
  generationScenarioSetSuffix.value = nextTimestampSuffix()
  syncGenerationScenarioSetId()
  generationForm.value.speed_interruption_threshold = DEFAULT_SPEED_INTERRUPTION_THRESHOLD
  generationDialogVisible.value = true
}

function syncGenerationScenarioSetId() {
  const prefix = generationScenarioSetPrefix.value
  const suffix = generationScenarioSetSuffix.value.trim()
  generationForm.value.scenario_set_id = prefix && suffix ? `${prefix}_${suffix}` : prefix || suffix
}

async function submitGeneration() {
  if (!selectedModelId.value) return
  syncGenerationScenarioSetId()
  if (!generationForm.value.checkpoint) {
    ElMessage.warning('请先选择 checkpoint 文件。')
    return
  }
  if (!generationForm.value.scenario_set_id.trim()) {
    ElMessage.warning('请填写生成到的扰动场景集 ID。')
    return
  }
  await run('提交生成任务', async () => {
    const response = await api.submitGeneration(
      selectedProjectId.value,
      selectedModelId.value,
      generationForm.value.checkpoint,
      generationForm.value.scenario_set_id,
      generationForm.value.num_samples,
      generationForm.value.seed,
      generationForm.value.device,
      generationForm.value.speed_interruption_threshold,
      generationForm.value.overwrite,
    )
    trackTask(response.task)
    generationDialogVisible.value = false
  })
}

async function deleteModelById(modelId: string) {
  if (!selectedProjectId.value || !modelId) return
  try {
    await ElMessageBox.confirm(
      `确认删除扰动生成模型 ${modelId}？该操作会删除模型产物目录。`,
      '删除扰动生成模型',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await run('删除扰动生成模型', async () => {
    await api.deleteModel(selectedProjectId.value, modelId)
    if (selectedModelId.value === modelId) {
      selectedModelId.value = ''
      modelDetail.value = null
    }
    if (pendingModelId.value === modelId) {
      clearPendingModel()
    }
    await loadSelectedProject(false)
    return `扰动生成模型 ${modelId} 已删除`
  })
}

async function reloadModelsOnOpen(visible: boolean) {
  if (!visible) return
  await loadSelectedProject(false)
  await loadModelDetails(false)
}

async function loadModelDetails(showMessage = true) {
  if (!selectedProjectId.value || !selectedModelId.value) {
    modelDetail.value = null
    return
  }
  try {
    modelDetail.value = await api.readModelDetail(selectedProjectId.value, selectedModelId.value)
  } catch (error) {
    modelDetail.value = null
    if (showMessage) notifyError(error)
  }
}

function trackTask(task: Task) {
  const index = tasks.value.findIndex((item) => item.id === task.id)
  if (index >= 0) {
    tasks.value[index] = task
  } else {
    tasks.value.push(task)
  }
  void refreshTasks(false)
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
  if (isTaskFailed(task)) {
    clearPendingModel()
  }
}

function clearPendingModel() {
  pendingModelId.value = ''
  pendingModelTaskId.value = null
}

async function finishShortTask(task: Task, label: string) {
  const doneTask = await waitForShortTask(task)
  const log = await api.getTaskLog(task.id, 160)
  await refreshTasks(false)

  if (!isTerminalTask(doneTask)) {
    return `${label}已提交：任务 ${task.id} ${taskDisplayStatus(doneTask)}，输出将在任务面板继续刷新`
  }

  if (isTaskSuccessful(doneTask)) {
    const lastLine = lastMeaningfulLine(log)
    return lastLine ? `${label}完成：${lastLine}` : `${label}完成`
  }

  const detail = lastMeaningfulLine(log)
  throw new Error(
    detail
      ? `${label}失败：${taskDisplayStatus(doneTask)}，${detail}`
      : `${label}失败：${taskDisplayStatus(doneTask)}`,
  )
}

async function requireShortTaskSuccess(task: Task, label: string) {
  const doneTask = await waitForShortTask(task)
  const log = await api.getTaskLog(task.id, 160)
  await refreshTasks(false)

  if (isTaskSuccessful(doneTask)) {
    const lastLine = lastMeaningfulLine(log)
    return lastLine ? `${label}完成：${lastLine}` : `${label}完成`
  }

  const detail = lastMeaningfulLine(log)
  throw new Error(
    detail
      ? `${label}未完成：${taskDisplayStatus(doneTask)}，${detail}`
      : `${label}未完成：${taskDisplayStatus(doneTask)}`,
  )
}

async function waitForShortTask(task: Task) {
  let current = task
  const deadline = Date.now() + SHORT_TASK_WAIT_MS
  while (!isTerminalTask(current) && Date.now() < deadline) {
    await sleep(SHORT_TASK_POLL_MS)
    current = await api.getTask(task.id)
  }
  return current
}

function isTerminalTask(task: Task) {
  return isTaskTerminal(task)
}

function filterTasks(labels: readonly string[]) {
  return projectTasks.value.filter((task) => labels.includes(String(task.label ?? '')))
}

function groupArtifactsByCase(artifacts: ArtifactSummary[]) {
  const groups = new Map<string, ArtifactGroup>()
  for (const artifact of artifacts) {
    const group = groups.get(artifact.case_id) ?? {
      case_id: artifact.case_id,
      size_bytes: 0,
      has_lp: false,
      has_solution: false,
      has_solution_csv: false,
      has_timetable_data: false,
    }
    group.size_bytes += artifact.size_bytes
    group.has_lp = group.has_lp || artifact.name.endsWith('.lp')
    group.has_solution = group.has_solution || artifact.name.endsWith('.sol')
    group.has_solution_csv = group.has_solution_csv || artifact.name.endsWith('.sol.csv')
    group.has_timetable_data = group.has_timetable_data || artifact.name === 'adjusted_timetable.json'
    groups.set(artifact.case_id, group)
  }
  return [...groups.values()]
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatMetadataValue(key: string, value: unknown) {
  if (value == null || value === '') return '无'
  if (key === 'created_at' && typeof value === 'string') return value.replace('T', ' ')
  if (key === 'source') {
    if (value === 'scenario') return '单个场景'
    if (value === 'scenario_set') return '扰动场景集'
  }
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function modelInfoEntries(
  summary: JsonObject | null,
  history?: { count?: number; latest?: JsonObject; best?: JsonObject },
): MetadataEntry[] {
  const bestMetrics = objectValue(summary?.best_metrics)
  const lastMetrics = objectValue(summary?.last_metrics)
  return [
    {
      key: 'best_epoch',
      label: '最佳轮次',
      value: formatMetadataValue('best_epoch', summary?.best_epoch),
    },
    { key: 'best_loss', label: '最佳损失', value: formatMetric(bestMetrics?.loss) },
    {
      key: 'last_epoch',
      label: '最后轮次',
      value: formatMetadataValue('last_epoch', summary?.last_epoch),
    },
    { key: 'last_loss', label: '最后损失', value: formatMetric(lastMetrics?.loss) },
    {
      key: 'history_count',
      label: '历史记录数',
      value: formatMetadataValue('history_count', history?.count),
    },
  ]
}

function trainingConfigEntries(config: JsonObject): MetadataEntry[] {
  return TRAINING_CONFIG_ORDER.filter((key) =>
    Object.prototype.hasOwnProperty.call(config, key),
  ).map((key) => ({
    key,
    label: TRAINING_CONFIG_LABELS[key] ?? key,
    value: formatMetadataValue(key, config[key]),
  }))
}

function modelSchemaSummary(schema: JsonObject): MetadataEntry[] {
  const messagePassing = objectValue(schema.message_passing)
  return [
    { key: 'pools', label: '节点池', value: String(schemaPoolRows(schema).length) },
    { key: 'edge_types', label: '边类型', value: String(schemaEdgeRows(schema).length) },
    { key: 'tasks', label: '预测任务', value: String(schemaTaskRows(schema).length) },
    {
      key: 'uses_edge_index',
      label: '使用边索引',
      value: messagePassing?.uses_edge_index ? '是' : '否',
    },
    {
      key: 'uses_edge_attr',
      label: '使用边特征',
      value: messagePassing?.uses_edge_attr ? '是' : '否',
    },
  ]
}

function schemaPoolRows(schema: JsonObject): SchemaPoolRow[] {
  return Object.entries(objectValue(schema.pools) ?? {}).map(([id, value]) => {
    const item = objectValue(value)
    return {
      id,
      size: formatMetadataValue('size', item?.size),
      feature_dim: formatMetadataValue('feature_dim', item?.feature_dim),
    }
  })
}

function schemaEdgeRows(schema: JsonObject): SchemaEdgeRow[] {
  return Object.entries(objectValue(schema.edge_types) ?? {}).map(([id, value]) => {
    const item = objectValue(value)
    return {
      id,
      source_pool_id: formatMetadataValue('source_pool_id', item?.source_pool_id),
      target_pool_id: formatMetadataValue('target_pool_id', item?.target_pool_id),
      feature_dim: formatMetadataValue('feature_dim', item?.feature_dim),
    }
  })
}

function schemaTaskRows(schema: JsonObject): SchemaTaskRow[] {
  return Object.entries(objectValue(schema.tasks) ?? {}).map(([id, value]) => {
    const item = objectValue(value)
    return {
      id,
      target_pool_id: formatMetadataValue('target_pool_id', item?.target_pool_id),
      max_slots: formatMetadataValue('max_slots', item?.max_slots),
      count_bounds: formatMetadataValue('count_bounds', item?.count_bounds),
      param_dim: formatMetadataValue('param_dim', item?.param_dim),
    }
  })
}

function checkpointRoleLabel(role: string) {
  if (role === 'best') return '最佳'
  if (role === 'last') return '最后'
  return '检查点'
}

function checkpointRoleType(role: string): TaskTagType {
  if (role === 'best') return 'success'
  if (role === 'last') return 'warning'
  return 'info'
}

function objectValue(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : null
}

function hasEntries(value: unknown) {
  const object = objectValue(value)
  return Boolean(object && Object.keys(object).length)
}

function formatMetric(value: unknown) {
  return typeof value === 'number' ? value.toFixed(6) : '无'
}

function trainFormDefaultsFromConfig(config: JsonObject): Partial<TrainForm> {
  const result: Partial<TrainForm> = {}
  for (const [key, defaultValue] of Object.entries(DEFAULT_TRAIN_FORM)) {
    if (key === 'model_id' || key === 'scenario_set_id') continue
    const value = config[key]
    if (typeof defaultValue === 'number' && typeof value === 'number') {
      result[key as keyof TrainForm] = value as never
    } else if (typeof defaultValue === 'string' && typeof value === 'string') {
      result[key as keyof TrainForm] = value as never
    }
  }
  return result
}

function stringConfigValue(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function nextTimestampSuffix() {
  return new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
}

function nextScenarioId() {
  const stamp = nextTimestampSuffix()
  return `scenario_${stamp}`
}

function lastMeaningfulLine(log: string) {
  return log
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .at(-1)
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function scrollMainToTop() {
  await nextTick()
  mainScrollbar.value?.setScrollTop(0)
}

function resetPrepareForm() {
  prepareForm.value = {
    timetable_file: null,
    mileage_file: null,
    timetable_sheet_name: 'Sheet1',
    mileage_sheet_name: 'Sheet1',
  }
  prepareTimetableFiles.value = []
  prepareMileageFiles.value = []
}

function setPrepareFile(kind: 'timetable_file' | 'mileage_file', file: UploadFile) {
  if (file.raw) prepareForm.value[kind] = file.raw
}

function setTimetableFile(file: UploadFile) {
  setPrepareFile('timetable_file', file)
}

function setMileageFile(file: UploadFile) {
  setPrepareFile('mileage_file', file)
}

function warnSingleFile() {
  ElMessage.warning('每项只需要一个文件，请先移除后重新选择。')
}

async function run(label: string, action: () => Promise<string | void>) {
  busy.value = true
  try {
    const message = await action()
    ElMessage.success(message || label)
  } catch (error) {
    notifyError(error)
  } finally {
    busy.value = false
  }
}

function selectPage(key: string) {
  activePage.value = key as PageKey
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
      <el-aside width="220px" class="app-aside">
        <div class="brand">RailDisruptLab</div>
        <el-menu :default-active="activePage" @select="selectPage">
          <el-menu-item index="dashboard">仪表盘</el-menu-item>
          <el-menu-item index="scenarios">构建扰动场景</el-menu-item>
          <el-menu-item index="datasets">构建MILP实例</el-menu-item>
          <el-menu-item index="models">扰动生成模型</el-menu-item>
          <el-sub-menu index="ablation">
            <template #title>消融分析</template>
            <el-menu-item index="ablation-scenarios">场景分析</el-menu-item>
            <el-menu-item index="ablation-datasets">MILP 分析</el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-aside>

      <el-container>
        <el-header class="app-header">
          <div class="header-actions">
            <span class="control-label">项目</span>
            <el-select
              v-model="selectedProjectId"
              placeholder="选择项目"
              filterable
              class="project-select"
            >
              <el-option
                v-for="item in projects"
                :key="item.project_id"
                :label="item.project_id"
                :value="item.project_id"
              />
            </el-select>
            <el-button @click="projectDialogVisible = true">新建</el-button>
            <el-button
              :disabled="!selectedProjectId"
              type="danger"
              @click="removeSelectedProject"
            >
              移除
            </el-button>
          </div>
        </el-header>

        <el-container class="workspace-container">
          <el-main v-loading="busy" class="app-main">
            <el-scrollbar ref="mainScrollbar" class="main-scroll">
              <el-empty v-if="!hasProject" description="还没有可用项目">
                <el-button type="primary" @click="projectDialogVisible = true">新建项目</el-button>
              </el-empty>

              <template v-else>
                <DashboardView
                  v-if="activePage === 'dashboard'"
                  :plan-timetable="planTimetable"
                  :scenario-set-count="scenarioSets.length"
                  :datasets="datasets"
                  :models="models"
                  :original-graph-active="originalGraphActive"
                  :tasks="tasks"
                  :running-task-count="runningTaskCount"
                  :done-task-count="doneTaskCount"
                  :failed-task-count="failedTaskCount"
                  @prepare="openPrepareDialog"
                  @refresh-tasks="refreshTasks"
                />

                <ScenarioSetsView
                  v-else-if="activePage === 'scenarios'"
                  v-model:selected-scenario-set-id="selectedScenarioSetId"
                  :scenario-sets="scenarioSets"
                  :scenarios="scenarios"
                  :visualization="scenarioSetVisualization"
                  :loading="scenarioSetLoading"
                  @reload-scenario-sets="reloadScenarioSetsOnOpen"
                  @create-scenario-set="scenarioSetDialogVisible = true"
                  @delete-scenario-set="deleteScenarioSetById"
                  @normal-generate="openNormalGenerateDialog"
                  @create-scenario="openScenarioDialog"
                  @delete-scenario="deleteScenario"
                />

                <DatasetsView
                  v-else-if="activePage === 'datasets'"
                  v-model:selected-dataset-id="selectedDatasetId"
                  :selected-dataset="selectedDataset"
                  :datasets="datasets"
                  :artifact-groups="datasetArtifactGroups"
                  :format-bytes="formatBytes"
                  @reload-datasets="reloadDatasetsOnOpen"
                  @create-dataset="openDatasetCreateDialog"
                  @delete-dataset="deleteDatasetById"
                  @refresh-artifacts="loadDatasetArtifacts"
                  @build-dataset="openDatasetBuildDialog"
                  @solve-all="() => openSolveDialog()"
                  @solve-case="openSolveDialog"
                  @export-all-timetables="() => submitExportTimetable()"
                  @export-timetable="submitExportTimetable"
                  @open-timetable="openCaseTimetable"
                />

                <ModelsView
                  v-else-if="activePage === 'models'"
                  v-model:selected-model-id="selectedModelId"
                  :pending-model-id="pendingModelId"
                  :selected-model="selectedModel"
                  :models="models"
                  :model-detail="modelDetail"
                  :model-summary-entries="modelSummaryEntries"
                  :model-config-entries="modelConfigEntries"
                  :model-schema-summary-entries="modelSchemaSummaryEntries"
                  :model-pool-rows="modelPoolRows"
                  :model-edge-rows="modelEdgeRows"
                  :model-task-rows="modelTaskRows"
                  :model-checkpoints="modelCheckpoints"
                  :has-training-summary="hasTrainingSummary"
                  :has-training-config="hasTrainingConfig"
                  :has-schema-summary="hasSchemaSummary"
                  :tasks="modelTasks"
                  :format-bytes="formatBytes"
                  :checkpoint-role-label="checkpointRoleLabel"
                  :checkpoint-role-type="checkpointRoleType"
                  @reload-models="reloadModelsOnOpen"
                  @train="() => openTrainDialog('create')"
                  @retrain="() => openTrainDialog('retrain')"
                  @delete-model="deleteModelById"
                  @refresh-model="loadModelDetails"
                  @open-task-log="openTaskLog"
                  @generate="openGenerationDialog"
                />

                <AblationView
                  v-else-if="activePage === 'ablation-scenarios' || activePage === 'ablation-datasets'"
                  :page="activePage"
                  :selected-project-id="selectedProjectId"
                  :scenario-sets="scenarioSets"
                  :datasets="datasets"
                />
              </template>
            </el-scrollbar>
          </el-main>
          <el-aside v-if="hasProject" width="340px" class="task-aside">
            <TaskPanel
              :tasks="visibleTasks"
              :now="taskNow"
              :project-options="taskProjectOptions"
              :page-options="taskPageOptions"
              :initial-project-id="selectedProjectId"
              :page-filters="PAGE_TASK_FILTERS"
              @refresh="refreshTasks"
              @clean="cleanTasks"
              @cancel="cancelTask"
            />
          </el-aside>
        </el-container>
      </el-container>
    </el-container>

    <el-dialog v-model="projectDialogVisible" title="新建项目" width="420px">
      <el-input v-model="newProjectId" placeholder="项目 ID" @keyup.enter="createProject" />
      <template #footer>
        <el-button @click="projectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createProject">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="prepareDialogVisible" title="激活原计划运行图" width="560px">
      <el-form label-width="140px">
        <el-form-item label="时刻表文件">
          <el-upload
            v-model:file-list="prepareTimetableFiles"
            :auto-upload="false"
            :limit="1"
            :on-change="setTimetableFile"
            :on-exceed="warnSingleFile"
          >
            <el-button>选择文件</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="里程表文件">
          <el-upload
            v-model:file-list="prepareMileageFiles"
            :auto-upload="false"
            :limit="1"
            :on-change="setMileageFile"
            :on-exceed="warnSingleFile"
          >
            <el-button>选择文件</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="时刻表工作表">
          <el-input v-model="prepareForm.timetable_sheet_name" />
        </el-form-item>
        <el-form-item label="里程表工作表">
          <el-input v-model="prepareForm.mileage_sheet_name" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="prepareDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPrepare">激活</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="scenarioSetDialogVisible" title="新建扰动场景集" width="420px">
      <el-input
        v-model="newScenarioSetId"
        placeholder="扰动场景集 ID"
        @keyup.enter="createScenarioSet"
      />
      <template #footer>
        <el-button @click="scenarioSetDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createScenarioSet">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="scenarioDialogVisible" title="新增场景" width="920px">
      <el-form label-width="100px">
        <el-form-item label="场景 ID">
          <el-input v-model="scenarioId" />
        </el-form-item>
        <el-form-item label="覆盖">
          <el-switch v-model="scenarioOverwrite" />
        </el-form-item>
        <el-alert
          title="中断按 limit_speed = 0 记录，与 core 的场景格式保持一致。"
          type="info"
          show-icon
          :closable="false"
        />
        <el-divider content-position="left">晚点扰动</el-divider>
        <el-table :data="scenarioDelays" empty-text="暂无晚点扰动">
          <el-table-column label="计划事件" min-width="280">
            <template #default="{ row }">
              <el-select v-model="row.event_anchor_id" filterable class="full-width">
                <el-option
                  v-for="item in scenarioEventOptions"
                  :key="item.anchor_id"
                  :label="`${item.train_id} · ${item.station} · ${item.event_type} · ${item.planned_time_text}`"
                  :value="item.anchor_id"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="晚点秒数" width="180">
            <template #default="{ row }">
              <el-input-number v-model="row.seconds" :min="1" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ $index }">
              <el-button link type="danger" @click="removeDelayRow($index)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="dialog-actions">
          <el-button @click="addDelayRow">添加晚点</el-button>
        </div>

        <el-divider content-position="left">限速 / 中断扰动</el-divider>
        <el-table :data="scenarioSpeedLimits" empty-text="暂无限速或中断扰动">
          <el-table-column label="区间" min-width="240">
            <template #default="{ row }">
              <el-select v-model="row.section_anchor_id" filterable class="full-width">
                <el-option
                  v-for="item in scenarioSectionOptions"
                  :key="item.anchor_id"
                  :label="`${item.start_station} -> ${item.end_station}`"
                  :value="item.anchor_id"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="开始时间" width="150">
            <template #default="{ row }">
              <el-input v-model="row.start_time" placeholder="HH:MM:SS" />
            </template>
          </el-table-column>
          <el-table-column label="持续秒数" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.duration" :min="1" />
            </template>
          </el-table-column>
          <el-table-column label="限速" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.limit_speed" :min="0" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ $index }">
              <el-button link type="danger" @click="removeSpeedLimitRow($index)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="dialog-actions">
          <el-button @click="addSpeedLimitRow()">添加限速</el-button>
          <el-button @click="addSpeedLimitRow(0)">添加中断</el-button>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="scenarioDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="addScenario">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="normalGenerateDialogVisible" title="批量生成场景" width="560px">
      <el-alert
        title="将生成到当前扰动场景集；若生成的场景 ID 已存在，会覆盖同名场景。"
        type="warning"
        show-icon
        :closable="false"
      />
      <el-form class="dialog-section" label-width="150px">
        <el-form-item label="当前扰动场景集">
          <el-input :model-value="selectedScenarioSetId" disabled />
        </el-form-item>
        <el-form-item label="随机种子">
          <el-input-number v-model="normalGenerateForm.seed" :min="0" />
        </el-form-item>
        <el-form-item label="延误场景数">
          <el-input-number v-model="normalGenerateForm.delay_count" :min="0" />
        </el-form-item>
        <el-form-item label="限速场景数">
          <el-input-number v-model="normalGenerateForm.speed_count" :min="0" />
        </el-form-item>
        <el-form-item label="中断场景数">
          <el-input-number v-model="normalGenerateForm.interruption_count" :min="0" />
        </el-form-item>
        <el-form-item label="组合场景数/类型">
          <el-input-number v-model="normalGenerateForm.combo_per_type" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="normalGenerateDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitNormalGenerate">确定生成</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="trainDialogVisible"
      :title="trainDialogMode === 'retrain' ? '重新训练扰动生成模型' : '训练新扰动生成模型'"
      width="920px"
      class="train-dialog"
    >
      <el-scrollbar max-height="68vh">
        <el-form label-position="top" class="train-form">
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="训练扰动场景集" :tip="TRAIN_FIELD_TIPS.scenario_set_id" />
                </template>
                <el-select
                  v-model="trainForm.scenario_set_id"
                  class="full-width"
                  placeholder="选择训练扰动场景集"
                  @visible-change="reloadScenarioSetsOnOpen"
                >
                  <el-option
                    v-for="item in scenarioSets"
                    :key="item.scenario_set_id"
                    :label="`${item.scenario_set_id} (${item.case_count})`"
                    :value="item.scenario_set_id"
                  />
                </el-select>
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
                >
                  <template #prepend>{{ trainModelPrefix || '请选择扰动场景集' }}_</template>
                </el-input>
                <el-input v-else v-model="trainForm.model_id" disabled />
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider content-position="left">辅助扰动判断</el-divider>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="最大槽位" :tip="TRAIN_FIELD_TIPS.max_slots" />
                </template>
                <el-input-number v-model="trainForm.max_slots" :min="1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="事件窗口" :tip="TRAIN_FIELD_TIPS.event_time_window" />
                </template>
                <el-input-number v-model="trainForm.event_time_window" :min="1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="事件 Top K" :tip="TRAIN_FIELD_TIPS.event_top_k" />
                </template>
                <el-input-number v-model="trainForm.event_top_k" :min="1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="区间窗口" :tip="TRAIN_FIELD_TIPS.section_order_window" />
                </template>
                <el-input-number v-model="trainForm.section_order_window" :min="1" />
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
                <el-input-number v-model="trainForm.hidden_dim" :min="1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="潜变量维度" :tip="TRAIN_FIELD_TIPS.latent_dim" />
                </template>
                <el-input-number v-model="trainForm.latent_dim" :min="1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="消息传递步数" :tip="TRAIN_FIELD_TIPS.message_passing_steps" />
                </template>
                <el-input-number v-model="trainForm.message_passing_steps" :min="1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="训练轮数" :tip="TRAIN_FIELD_TIPS.epochs" />
                </template>
                <el-input-number v-model="trainForm.epochs" :min="1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="Batch Size" :tip="TRAIN_FIELD_TIPS.batch_size" />
                </template>
                <el-input-number v-model="trainForm.batch_size" :min="1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="学习率" :tip="TRAIN_FIELD_TIPS.lr" />
                </template>
                <el-input-number v-model="trainForm.lr" :min="0" :step="0.0001" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="随机种子" :tip="TRAIN_FIELD_TIPS.seed" />
                </template>
                <el-input-number v-model="trainForm.seed" :min="0" />
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
                <el-input-number v-model="trainForm.count_weight" :min="0" :step="0.1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="Anchor" :tip="TRAIN_FIELD_TIPS.anchor_weight" />
                </template>
                <el-input-number v-model="trainForm.anchor_weight" :min="0" :step="0.1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="Param" :tip="TRAIN_FIELD_TIPS.param_weight" />
                </template>
                <el-input-number v-model="trainForm.param_weight" :min="0" :step="0.1" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="KL" :tip="TRAIN_FIELD_TIPS.kl_weight" />
                </template>
                <el-input-number v-model="trainForm.kl_weight" :min="0" :step="0.0005" />
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>
      </el-scrollbar>
      <template #footer>
        <el-button @click="trainDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitTrain">提交训练</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="generationDialogVisible" title="使用扰动生成模型生成数据" width="560px">
      <el-form label-width="150px">
        <el-form-item label="扰动生成模型">
          <el-input :model-value="selectedModelId" disabled />
        </el-form-item>
        <el-form-item label="Checkpoint">
          <el-input :model-value="generationForm.checkpoint" disabled />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="输出扰动场景集" :tip="GENERATION_FIELD_TIPS.scenario_set_id" />
          </template>
          <el-input
            v-model="generationScenarioSetSuffix"
            placeholder="默认使用当前时间戳"
          >
            <template #prepend>{{ generationScenarioSetPrefix }}_</template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="生成样本数" :tip="GENERATION_FIELD_TIPS.num_samples" />
          </template>
          <el-input-number v-model="generationForm.num_samples" :min="1" />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="随机种子" :tip="GENERATION_FIELD_TIPS.seed" />
          </template>
          <el-input-number v-model="generationForm.seed" :min="0" />
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
          />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="覆盖同名集合" :tip="GENERATION_FIELD_TIPS.overwrite" />
          </template>
          <el-switch v-model="generationForm.overwrite" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="generationDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitGeneration">提交生成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="datasetCreateDialogVisible" title="新增 MILP 实例集" width="560px">
      <el-form label-width="130px" @submit.prevent="createDataset">
        <el-form-item label="创建方式">
          <el-radio-group v-model="datasetCreateMode">
            <el-radio-button value="scenario_set" :disabled="!scenarioSets.length">
              从扰动场景集引入
            </el-radio-button>
            <el-radio-button value="empty">空建</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="datasetCreateMode === 'scenario_set'">
          <el-form-item label="扰动场景集">
            <el-select
              v-model="datasetCreateScenarioSetId"
              class="full-width"
              placeholder="选择扰动场景集"
              @visible-change="reloadScenarioSetsOnOpen"
            >
              <el-option
                v-for="item in scenarioSets"
                :key="item.scenario_set_id"
                :label="`${item.scenario_set_id} (${item.case_count})`"
                :value="item.scenario_set_id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="MILP 实例集 ID">
            <el-input
              :model-value="newDatasetId"
              disabled
              @keydown.enter.prevent="createDataset"
            />
          </el-form-item>
        </template>
        <el-form-item v-else label="MILP 实例集 ID">
          <el-input
            v-model="newDatasetId"
            placeholder="例如 milp_reference"
            @keydown.enter.prevent="createDataset"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="datasetCreateDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createDataset">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="datasetBuildDialogVisible" title="从场景构建 MILP 实例集" width="640px">
      <el-form label-width="150px">
        <el-form-item label="MILP 实例集 ID">
          <el-input :model-value="selectedDatasetId" disabled />
        </el-form-item>
        <el-form-item label="构建来源">
          <el-radio-group v-model="datasetBuildForm.source">
            <el-radio-button value="scenario_set">从扰动场景集中构建</el-radio-button>
            <el-radio-button value="scenario">从场景中构建</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="扰动场景集">
          <el-select
            v-model="datasetBuildForm.scenario_set_id"
            class="full-width"
            @visible-change="reloadScenarioSetsOnOpen"
            @change="onDatasetBuildScenarioSetChange"
          >
            <el-option
              v-for="item in scenarioSets"
              :key="item.scenario_set_id"
              :label="`${item.scenario_set_id} (${item.case_count})`"
              :value="item.scenario_set_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="datasetBuildForm.source === 'scenario'" label="场景">
          <el-select
            v-model="datasetBuildForm.scenario_id"
            class="full-width"
            placeholder="选择单个场景"
            @visible-change="reloadDatasetBuildScenariosOnOpen"
          >
            <el-option
              v-for="item in selectedBuildScenarios"
              :key="item.scenario_id"
              :label="item.scenario_id"
              :value="item.scenario_id"
            />
          </el-select>
        </el-form-item>
        <el-collapse :model-value="['build-options']">
          <el-collapse-item title="构建参数" name="build-options">
            <el-form-item label="目标权重">
              <el-input-number
                v-model="datasetBuildForm.objective_delay_weight"
                :min="0.000001"
                :step="0.1"
              />
            </el-form-item>
            <el-form-item label="目标模式">
              <el-select v-model="datasetBuildForm.objective_mode" class="full-width">
                <el-option label="绝对延误 abs" value="abs" />
                <el-option label="平方延误 square" value="square" />
              </el-select>
            </el-form-item>
            <el-form-item label="允许取消">
              <el-switch v-model="datasetBuildForm.cancellation_enabled" />
            </el-form-item>
            <el-form-item label="取消惩罚权重">
              <el-input-number
                v-model="datasetBuildForm.cancellation_penalty_weight"
                :min="0"
                :step="100"
              />
            </el-form-item>
            <el-form-item label="到到间隔秒数">
              <el-input-number v-model="datasetBuildForm.arr_arr_headway_seconds" :min="1" />
            </el-form-item>
            <el-form-item label="发发间隔秒数">
              <el-input-number v-model="datasetBuildForm.dep_dep_headway_seconds" :min="1" />
            </el-form-item>
            <el-form-item label="停站秒数">
              <el-input-number v-model="datasetBuildForm.dwell_seconds_at_stops" :min="1" />
            </el-form-item>
            <el-form-item label="Big-M">
              <el-input-number v-model="datasetBuildForm.big_m" :min="1" :step="1000" />
            </el-form-item>
            <el-form-item label="延误容忍秒数">
              <el-input-number v-model="datasetBuildForm.tolerance_delay_seconds" :min="1" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
        <el-alert
          title="构建会写入并覆盖当前 MILP 实例集的 build 产物；从单个场景构建的实例集，后续求解和导出也只处理该场景。"
          type="info"
          show-icon
          :closable="false"
        />
      </el-form>
      <template #footer>
        <el-button @click="datasetBuildDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBuild">确认构建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="solveDialogVisible" title="求解参数" width="560px">
      <el-form label-width="150px">
        <el-form-item label="求解范围">
          <el-tag v-if="solveTargetCaseId" type="primary">{{ solveTargetCaseId }}</el-tag>
          <el-tag v-else type="primary">全部实例</el-tag>
        </el-form-item>
        <el-form-item v-if="!solveTargetCaseId" label="数量上限">
          <el-input-number v-model="datasetRunForm.solveLimit" :min="0" />
          <span class="form-hint">0 表示全部</span>
        </el-form-item>
        <el-form-item v-if="!solveTargetCaseId" label="已有解则跳过">
          <el-switch v-model="datasetRunForm.skipSolved" />
        </el-form-item>
        <el-form-item label="单次限时秒数">
          <el-input-number v-model="datasetRunForm.solveTimeLimit" :min="0" />
          <span class="form-hint">0 表示不限制</span>
        </el-form-item>
        <el-form-item label="MIP Gap">
          <el-input-number v-model="datasetRunForm.solveMipGap" :min="0" :step="0.001" />
        </el-form-item>
        <el-form-item label="线程数">
          <el-input-number v-model="datasetRunForm.solveThreads" :min="0" />
          <span class="form-hint">0 表示 Gurobi 默认</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="solveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitSolveDialog">开始求解</el-button>
      </template>
    </el-dialog>

    <TimetableDialog v-model="timetableDialogVisible" :timetable="caseTimetable" />

    <TaskLogDialog v-model="taskLogDialogVisible" :task="taskLogTarget" />
  </div>
</template>
