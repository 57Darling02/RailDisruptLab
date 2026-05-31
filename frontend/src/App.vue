<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ScrollbarInstance, UploadFile, UploadUserFile } from 'element-plus'

import { api, ApiError } from '@/api/client'
import AppNavigation from '@/components/AppNavigation.vue'
import BuildOptionsFields from '@/components/BuildOptionsFields.vue'
import FieldLabelTip from '@/components/FieldLabelTip.vue'
import ProjectSelector from '@/components/ProjectSelector.vue'
import RemoteResourceSelect from '@/components/RemoteResourceSelect.vue'
import TaskPanel from '@/components/TaskPanel.vue'
import TimetableDialog from '@/components/TimetableDialog.vue'
import TaskLogDialog from '@/components/TaskLogDialog.vue'
import AblationView from '@/views/AblationView.vue'
import DashboardView from '@/views/DashboardView.vue'
import DatasetsView from '@/views/DatasetsView.vue'
import ModelsView from '@/views/ModelsView.vue'
import ScenarioDetailView from '@/views/ScenarioDetailView.vue'
import ScenarioSetsView from '@/views/ScenarioSetsView.vue'
import { Menu, Tickets } from '@/icons'
import {
  isTaskCancellable,
  isTaskFailed,
  isTaskSuccessful,
  isTaskTerminal,
} from '@/task-status'
import type {
  DatasetBuildForm,
  DatasetRunForm,
  TrainForm,
} from '@/views/types'
import type {
  DatasetSummary,
  ModelCheckpoint,
  ModelDetail,
  ProjectState,
  ProjectSummary,
  ResourceOption,
  ScenarioSummary,
  Task,
} from '@/types'

type PageKey = 'dashboard' | 'scenarios' | 'scenario-detail' | 'datasets' | 'models' | 'ablation-scenarios' | 'ablation-datasets'
type DatasetBuildSource = 'scenario_set' | 'scenario'
type DatasetCreateMode = 'empty' | 'scenario_set'
type GenerationContextSourceMode = 'scenario_set' | 'upload'
type ResourceKind = 'scenario_sets' | 'datasets' | 'models'

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
  relation_weight: 0.5,
}
const DEFAULT_SPEED_INTERRUPTION_THRESHOLD = 20
const DEVICE_OPTIONS = ['auto', 'cpu', 'cuda:0', 'cuda:1', 'cuda:2', 'cuda:3']
const TRAIN_FIELD_TIPS = {
  model_id: '本次训练产物的模型目录 ID，用于后续选择 checkpoint 生成场景。',
  scenario_set_id: '训练样本来源，固定使用一个完整场景分类。',
  max_slots: '每类扰动最多保留/预测的事件槽位数，决定辅助扰动图的目标容量。',
  event_time_window: '判断两个时刻事件是否存在近邻关系的时间窗口，单位秒。',
  event_top_k: '每个时刻事件最多连接的近邻事件数量，用于控制辅助扰动图稠密度。',
  section_order_window: '沿线路顺序连接前后区间的窗口大小，用于表达邻近区间关系。',
  hidden_dim: 'VAE 编码器/解码器隐藏层维度，越大表达能力越强但训练更重。',
  latent_dim: '潜变量维度，控制模型压缩扰动模式的容量。',
  message_passing_steps: '图神经网络消息传递轮数，越大可聚合更远邻域信息。',
  epochs: '完整遍历训练场景分类的轮数。',
  batch_size: '每次优化使用的样本数量。',
  lr: '优化器学习率。',
  seed: '随机种子，用于复现实验。',
  device: '训练设备，auto 会优先使用 CUDA；指定 GPU 卡号可填写 cuda:0、cuda:1，CPU 填 cpu。',
  count_weight: '扰动数量预测损失权重。',
  anchor_weight: '扰动锚点位置预测损失权重。',
  param_weight: '扰动参数预测损失权重，例如延误秒数、限速速度等。',
  kl_weight: 'VAE KL 散度损失权重，控制潜空间正则强度。',
  relation_weight: '扰动关系辅助损失权重，用于强化 target_relations 的时空关联学习。',
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
  scenarios: ['normal_generate', 'scenario_set_create', 'scenario_add', 'scenario_delete'],
  datasets: ['dataset_create', 'build', 'solve', 'export_timetable'],
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
const taskDrawerVisible = ref(false)

const selectedScenarioSetId = ref('')
const loadedScenarioSetId = ref('')
const scenarioCategoryRefreshKey = ref(0)
const scenarioCategoryDetailLoading = ref(false)
const scenarioSetOptions = ref<ResourceOption[]>([])
const scenarioSetOptionsLoading = ref(false)
const scenarios = ref<ScenarioSummary[]>([])
const scenarioOptions = ref<ResourceOption[]>([])
const scenarioOptionsLoading = ref(false)
const selectedScenarioId = ref('')
const scenarioSetDialogVisible = ref(false)
const newScenarioSetId = ref('')
const scenarioDialogVisible = ref(false)
const scenarioCreateScenarioSetId = ref('')
const scenarioDialogInitialId = ref('')
const scenarioCreateFiles = ref({
  timetable_file: null as File | null,
  mileage_file: null as File | null,
})
const scenarioCreateTimetableFiles = ref<UploadUserFile[]>([])
const scenarioCreateMileageFiles = ref<UploadUserFile[]>([])
const normalGenerateDialogVisible = ref(false)
const normalGenerateScenarioSetId = ref('')
const normalGenerateForm = ref({
  scenario_id_prefix: 'sim',
  simulation_count: 1,
  timetable_file: null as File | null,
  mileage_file: null as File | null,
  seed: 20260320,
  delay_count: 10,
  speed_count: 10,
  interruption_count: 10,
  combo_per_type: 10,
  overwrite: false,
})
const normalGenerateTimetableFiles = ref<UploadUserFile[]>([])
const normalGenerateMileageFiles = ref<UploadUserFile[]>([])

const selectedDatasetId = ref('')
const loadedDatasetId = ref('')
const datasetDetailRefreshKey = ref(0)
const datasetDetailLoading = ref(false)
const datasetOptions = ref<ResourceOption[]>([])
const datasetOptionsLoading = ref(false)
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
const timetableCaseId = ref('')
const taskLogDialogVisible = ref(false)
const taskLogTarget = ref<Task | null>(null)
const datasetRunForm = ref<DatasetRunForm>({ ...DEFAULT_DATASET_RUN_FORM })

const selectedModelId = ref('')
const loadedModelId = ref('')
const modelDetailRefreshKey = ref(0)
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
const generationScenarioSetSuffix = ref('')
const generationForm = ref({
  checkpoint: '',
  scenario_set_id: '',
  source_mode: 'scenario_set' as GenerationContextSourceMode,
  source_scenario_set_id: '',
  output_prefix: 'generated',
  num_samples: 100,
  seed: 1,
  device: 'auto',
  speed_interruption_threshold: DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
  overwrite: false,
  timetable_file: null as File | null,
  mileage_file: null as File | null,
})
const generationTimetableFiles = ref<UploadUserFile[]>([])
const generationMileageFiles = ref<UploadUserFile[]>([])

let pollHandle = 0
let durationTickHandle = 0
const resourceOptionRequestSeq = reactive<Record<ResourceKind, number>>({
  scenario_sets: 0,
  datasets: 0,
  models: 0,
})
let scenarioOptionRequestSeq = 0
let projectOptionRequestSeq = 0

const hasProject = computed(() => Boolean(selectedProjectId.value && project.value?.exists))
const trainModelPrefix = computed(() => {
  const scenarioSetId = trainForm.scenario_set_id.trim()
  return scenarioSetId ? `train_${scenarioSetId}` : ''
})
const generationScenarioSetPrefix = computed(() => loadedModelId.value.trim())
const projectSelectOptions = computed(() =>
  mergeSelectedResourceOption(
    projectOptions.value,
    selectedProjectId.value,
    selectedProjectId.value,
  ),
)
const scenarioSets = computed(() => project.value?.scenario_sets ?? [])
const datasets = computed(() => project.value?.datasets ?? [])
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
      value: scenarioCreateScenarioSetId.value,
      label: resourceLabel(scenarioSets.value, 'scenario_set_id', scenarioCreateScenarioSetId.value, 'case_count'),
    },
    {
      value: datasetCreateScenarioSetId.value,
      label: resourceLabel(scenarioSets.value, 'scenario_set_id', datasetCreateScenarioSetId.value, 'case_count'),
    },
    {
      value: datasetBuildForm.value.scenario_set_id,
      label: resourceLabel(scenarioSets.value, 'scenario_set_id', datasetBuildForm.value.scenario_set_id, 'case_count'),
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
    datasetBuildForm.value.scenario_id,
    datasetBuildForm.value.scenario_id,
  ),
)
const datasetSelectOptions = computed(() =>
  mergeSelectedResourceOptions(datasetOptions.value, [
    {
      value: selectedDatasetId.value,
      label: resourceLabel(datasets.value, 'dataset_id', selectedDatasetId.value, 'case_count'),
    },
    {
      value: loadedDatasetId.value,
      label: resourceLabel(datasets.value, 'dataset_id', loadedDatasetId.value, 'case_count'),
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
const loadedDataset = computed(
  () => datasets.value.find((item) => item.dataset_id === loadedDatasetId.value) ?? null,
)
const loadedModel = computed(
  () => models.value.find((item) => item.model_id === loadedModelId.value) ?? null,
)
const taskProjectOptions = computed(() => [
  { label: '全部项目', value: '' },
  ...projects.value.map((item) => ({ label: item.project_id, value: item.project_id })),
])
const scenarioTasks = computed(() => filterTasks(TASK_LABELS.scenarios))
const datasetTasks = computed(() => filterTasks(TASK_LABELS.datasets))
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
    selectedDatasetId.value = ''
    loadedDatasetId.value = ''
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

watch(selectedDatasetId, (datasetId) => {
  timetableDialogVisible.value = false
  timetableCaseId.value = ''
  loadedDatasetId.value = datasetId
  if (datasetId) datasetDetailRefreshKey.value += 1
})

watch(selectedScenarioSetId, (scenarioSetId) => {
  loadedScenarioSetId.value = scenarioSetId
})

watch(selectedModelId, (modelId) => {
  loadedModelId.value = modelId
  retrainModelDetail.value = null
  if (modelId) modelDetailRefreshKey.value += 1
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
  if (datasetCreateMode.value === 'scenario_set') {
    syncDatasetCreateId()
    datasetBuildForm.value.scenario_set_id = datasetCreateScenarioSetId.value.trim()
  }
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
  datasetOptions.value = []
  modelOptions.value = []
}

function selectFirstOptions() {
  if (!project.value) return
  if (
    selectedScenarioSetId.value &&
    !project.value.scenario_sets.some(
      (item) => item.scenario_set_id === selectedScenarioSetId.value,
    )
  ) {
    selectedScenarioSetId.value = ''
  }
  if (
    loadedScenarioSetId.value &&
    !project.value.scenario_sets.some(
      (item) => item.scenario_set_id === loadedScenarioSetId.value,
    )
  ) {
    loadedScenarioSetId.value = ''
  }
  if (
    !selectedDatasetId.value ||
    !project.value.datasets.some((item) => item.dataset_id === selectedDatasetId.value)
  ) {
    selectedDatasetId.value = project.value.datasets[0]?.dataset_id ?? ''
  }
  if (
    loadedDatasetId.value &&
    !project.value.datasets.some((item) => item.dataset_id === loadedDatasetId.value)
  ) {
    loadedDatasetId.value = ''
  }
  const readyPendingModel = project.value.models.find((item) => item.model_id === pendingModelId.value)
  if (readyPendingModel) {
    selectedModelId.value = readyPendingModel.model_id
    loadedModelId.value = readyPendingModel.model_id
    modelDetailRefreshKey.value += 1
    clearPendingModel()
  } else if (
    !selectedModelId.value ||
    (
      selectedModelId.value !== pendingModelId.value &&
      !project.value.models.some((item) => item.model_id === selectedModelId.value)
    )
  ) {
    selectedModelId.value = project.value.models[0]?.model_id ?? ''
  }
  if (
    loadedModelId.value &&
    loadedModelId.value !== pendingModelId.value &&
    !project.value.models.some((item) => item.model_id === loadedModelId.value)
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
  const previousTasks = tasks.value
  await refreshTasks(false)
  if (shouldRefreshSelectedProjectAfterTaskPoll(previousTasks, tasks.value)) {
    await loadSelectedProject(false)
  }
  refreshLoadedResourceDetailsAfterTaskPoll(previousTasks, tasks.value)
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
    ['normal_generate', 'scenario_delete', 'generation'].includes(label) &&
    params.scenario_set_id === loadedScenarioSetId.value
  ) {
    scenarioCategoryRefreshKey.value += 1
  }
  if (
    loadedDatasetId.value &&
    ['build', 'solve', 'export_timetable'].includes(label) &&
    params.dataset_id === loadedDatasetId.value
  ) {
    datasetDetailRefreshKey.value += 1
  }
  if (loadedModelId.value && label === 'train' && params.model_id === loadedModelId.value) {
    modelDetailRefreshKey.value += 1
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
  await submitTask('创建项目', async () => {
    const response = await api.createProject(projectId)
    trackTask(response.task)
    selectedProjectId.value = projectId
    projectOptions.value = [{ label: projectId, value: projectId }]
    await refreshTasks(false)
    return response.task
  })
}

async function removeProject(projectId: string) {
  projectId = projectId.trim()
  if (!projectId) return
  await submitTask('移除项目', async () => {
    const response = await api.deleteProject(projectId)
    trackTask(response.task)
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
  await submitTask('创建场景分类', async () => {
    const response = await api.createScenarioSet(selectedProjectId.value, scenarioSetId)
    trackTask(response.task)
    selectedScenarioSetId.value = scenarioSetId
    scenarioSetOptions.value = [{ label: scenarioSetId, value: scenarioSetId }]
    newScenarioSetId.value = ''
    scenarioSetDialogVisible.value = false
    await refreshTasks(false)
    return response.task
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
      scenarios.value = []
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
  loadedScenarioSetId.value = selectedScenarioSetId.value
  scenarioCategoryRefreshKey.value += 1
}

function reloadSelectedDatasetDetail() {
  if (!selectedDatasetId.value) {
    ElMessage.warning('请先选择 MILP 实例集。')
    return
  }
  loadedDatasetId.value = selectedDatasetId.value
  datasetDetailRefreshKey.value += 1
}

function reloadSelectedModelDetail() {
  if (!selectedModelId.value) {
    ElMessage.warning('请先选择模型训练资源。')
    return
  }
  loadedModelId.value = selectedModelId.value
  retrainModelDetail.value = null
  modelDetailRefreshKey.value += 1
}

async function loadScenarios(
  showMessage = true,
  projectId = selectedProjectId.value,
  scenarioSetId = selectedScenarioSetId.value,
) {
  if (!projectId || !scenarioSetId) {
    if (projectId === selectedProjectId.value && scenarioSetId === selectedScenarioSetId.value) {
      scenarios.value = []
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
  const scenarioSetId = datasetBuildForm.value.scenario_set_id.trim()
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
      scenarioSetId === datasetBuildForm.value.scenario_set_id.trim()
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

function openScenarioDialog() {
  if (operationPending.value) return
  scenarioCreateScenarioSetId.value = selectedScenarioSetId.value
  scenarioDialogInitialId.value = ''
  scenarioCreateFiles.value = { timetable_file: null, mileage_file: null }
  scenarioCreateTimetableFiles.value = []
  scenarioCreateMileageFiles.value = []
  scenarioDialogVisible.value = true
}

function setScenarioCreateTimetableFile(file: UploadFile) {
  if (file.raw) scenarioCreateFiles.value.timetable_file = file.raw
}

function setScenarioCreateMileageFile(file: UploadFile) {
  if (file.raw) scenarioCreateFiles.value.mileage_file = file.raw
}

async function createScenarioCase() {
  const scenarioId = scenarioDialogInitialId.value.trim()
  const scenarioSetId = scenarioCreateScenarioSetId.value.trim()
  if (!scenarioId || !scenarioSetId) {
    ElMessage.warning('请填写场景 ID 并选择场景分类。')
    return
  }
  if (!scenarioCreateFiles.value.timetable_file || !scenarioCreateFiles.value.mileage_file) {
    ElMessage.warning('请上传时刻表和里程表。')
    return
  }
  await runAction('新增场景', async () => {
    await api.createScenarioCase(
      selectedProjectId.value,
      scenarioSetId,
      scenarioId,
      scenarioCreateFiles.value.timetable_file as File,
      scenarioCreateFiles.value.mileage_file as File,
    )
    selectedScenarioSetId.value = scenarioSetId
    loadedScenarioSetId.value = scenarioSetId
    selectedScenarioId.value = scenarioId
    scenarioCategoryRefreshKey.value += 1
    scenarioDialogVisible.value = false
    await loadSelectedProject(false)
    return `场景 ${scenarioId} 已创建`
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
    trackTask(response.task)
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
  activePage.value = 'scenarios'
}

function openNormalGenerateDialog() {
  if (operationPending.value) return
  if (!loadedScenarioSetId.value) {
    ElMessage.warning('请先载入场景分类。')
    return
  }
  normalGenerateScenarioSetId.value = loadedScenarioSetId.value
  normalGenerateTimetableFiles.value = []
  normalGenerateMileageFiles.value = []
  normalGenerateForm.value.timetable_file = null
  normalGenerateForm.value.mileage_file = null
  normalGenerateDialogVisible.value = true
}

function setNormalGenerateTimetableFile(file: UploadFile) {
  if (file.raw) normalGenerateForm.value.timetable_file = file.raw
}

function setNormalGenerateMileageFile(file: UploadFile) {
  if (file.raw) normalGenerateForm.value.mileage_file = file.raw
}

async function submitNormalGenerate() {
  const scenarioSetId = normalGenerateScenarioSetId.value.trim()
  if (!scenarioSetId) return
  if (!normalGenerateForm.value.timetable_file || !normalGenerateForm.value.mileage_file) {
    ElMessage.warning('请上传时刻表和里程表。')
    return
  }
  await submitTask('模拟场景', async () => {
    const response = await api.submitNormalGenerateUpload(selectedProjectId.value, {
      scenarioSetId,
      scenarioIdPrefix: normalGenerateForm.value.scenario_id_prefix,
      simulationCount: normalGenerateForm.value.simulation_count,
      seed: normalGenerateForm.value.seed,
      delayCount: normalGenerateForm.value.delay_count,
      speedCount: normalGenerateForm.value.speed_count,
      interruptionCount: normalGenerateForm.value.interruption_count,
      comboPerType: normalGenerateForm.value.combo_per_type,
      overwrite: normalGenerateForm.value.overwrite,
      timetableFile: normalGenerateForm.value.timetable_file as File,
      mileageFile: normalGenerateForm.value.mileage_file as File,
    })
    trackTask(response.task)
    selectedScenarioSetId.value = scenarioSetId
    loadedScenarioSetId.value = scenarioSetId
    normalGenerateDialogVisible.value = false
    return response.task
  })
}

async function submitBuild() {
  const datasetId = loadedDatasetId.value.trim()
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
  await submitTask('构建 MILP', async () => {
    const response = await api.submitBuild(
      selectedProjectId.value,
      scenarioSetId,
      datasetId,
      scenarioId,
      normalizedBuildOptions(),
    )
    trackTask(response.task)
    selectedDatasetId.value = datasetId
    loadedDatasetId.value = datasetId
    datasetBuildDialogVisible.value = false
    return response.task
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
        ? '请先选择要引入的场景分类。'
        : '请填写 MILP 实例集 ID。',
    )
    return
  }
  if (importScenarioSet && !scenarioSetId) {
    ElMessage.warning('请先选择要引入的场景分类。')
    return
  }
  const existingDataset = datasets.value.find((item) => item.dataset_id === datasetId)
  if (existingDataset && !importScenarioSet) {
    ElMessage.warning(`MILP 实例集 ${datasetId} 已存在，请换一个 ID。`)
    return
  }
  if (existingDataset) {
    try {
      await ElMessageBox.confirm(
        `MILP 实例集 ${datasetId} 已存在。继续会清空并重建该实例集产物。`,
        '重建 MILP 实例集',
        { type: 'warning', confirmButtonText: '清空并重建', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  await submitTask(importScenarioSet ? '构建 MILP 实例集' : '创建空 MILP 实例集', async () => {
    selectedDatasetId.value = datasetId
    loadedDatasetId.value = datasetId
    if (importScenarioSet) {
      selectedScenarioSetId.value = scenarioSetId
      const buildResponse = await api.submitBuild(
        selectedProjectId.value,
        scenarioSetId,
        datasetId,
        '',
        normalizedBuildOptions(),
      )
      trackTask(buildResponse.task)
      resetDatasetCreateForm()
      datasetCreateDialogVisible.value = false
      return buildResponse.task
    }
    const response = await api.createDataset(selectedProjectId.value, datasetId)
    trackTask(response.task)
    resetDatasetCreateForm()
    datasetCreateDialogVisible.value = false
    return response.task
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
  await runAction('删除 MILP 实例集', async () => {
    await api.deleteDataset(selectedProjectId.value, datasetId)
    if (selectedDatasetId.value === datasetId) {
      selectedDatasetId.value = ''
      timetableCaseId.value = ''
      timetableDialogVisible.value = false
    }
    if (loadedDatasetId.value === datasetId) {
      loadedDatasetId.value = ''
    }
    datasetOptions.value = datasetOptions.value.filter((item) => item.value !== datasetId)
    await loadSelectedProject(false)
    return `MILP 实例集 ${datasetId} 已删除`
  })
}

async function submitSolve(caseId = '') {
  if (!loadedDatasetId.value) return
  const options = normalizedSolveOptions()
  await submitTask('求解', async () => {
    const response = await api.submitSolve(
      selectedProjectId.value,
      loadedDatasetId.value,
      caseId ? 0 : options.solveLimit,
      options.solveTimeLimit,
      caseId,
      options.solveMipGap,
      options.solveThreads,
      caseId ? false : options.skipSolved,
    )
    trackTask(response.task)
    solveDialogVisible.value = false
    return response.task
  })
}

async function submitExportTimetable(caseId = '') {
  if (!loadedDatasetId.value) return
  await submitTask('导出时刻表', async () => {
    const response = await api.submitExportTimetable(
      selectedProjectId.value,
      loadedDatasetId.value,
      0,
      caseId,
    )
    trackTask(response.task)
    return response.task
  })
}

function openSolveDialog(caseId = '') {
  if (operationPending.value) return
  if (!loadedDatasetId.value) return
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

async function reloadDatasetsOnOpen(visible: boolean) {
  if (!visible) return
  await loadResourceOptions('datasets', '', {
    target: datasetOptions,
    loading: datasetOptionsLoading,
  })
  await loadSelectedProject(false)
}

async function searchDatasetOptions(query: string) {
  await loadResourceOptions('datasets', query, {
    target: datasetOptions,
    loading: datasetOptionsLoading,
  })
}

async function openDatasetCreateDialog() {
  if (operationPending.value) return
  datasetCreateMode.value = scenarioSets.value.length ? 'scenario_set' : 'empty'
  datasetCreateScenarioSetId.value = selectedScenarioSetId.value || scenarioSets.value[0]?.scenario_set_id || ''
  newDatasetId.value = ''
  resetDatasetBuildForm({
    source: 'scenario_set',
    scenarioSetId: datasetCreateScenarioSetId.value,
  })
  if (datasetCreateMode.value === 'scenario_set') syncDatasetCreateId()
  datasetCreateDialogVisible.value = true
}

function resetDatasetCreateForm() {
  newDatasetId.value = ''
  datasetCreateScenarioSetId.value = ''
  datasetCreateMode.value = 'scenario_set'
}

function syncDatasetCreateId() {
  newDatasetId.value = datasetCreateScenarioSetId.value.trim()
}

async function openDatasetBuildDialog() {
  if (operationPending.value) return
  if (!loadedDatasetId.value) {
    ElMessage.warning('请先载入一个 MILP 实例集。')
    return
  }
  resetDatasetBuildForm({
    source: 'scenario_set',
    scenarioSetId: selectedScenarioSetId.value || scenarioSets.value[0]?.scenario_set_id || '',
  })
  if (datasetBuildForm.value.scenario_set_id) {
    selectedScenarioSetId.value = datasetBuildForm.value.scenario_set_id
    await loadScenarioOptions('')
  }
  datasetBuildDialogVisible.value = true
}

function resetDatasetBuildForm(options: { source: DatasetBuildSource; scenarioSetId: string }) {
  datasetBuildForm.value = {
    scenario_set_id: options.scenarioSetId,
    source: options.source,
    scenario_id: '',
    ...DEFAULT_DATASET_BUILD_FORM,
  }
}

function updateDatasetBuildOptions(options: DatasetBuildForm) {
  datasetBuildForm.value = {
    ...datasetBuildForm.value,
    ...options,
  }
}

async function onDatasetBuildScenarioSetChange() {
  datasetBuildForm.value.scenario_id = ''
  await loadScenarioOptions('')
}

function openCaseTimetable(caseId: string) {
  if (!selectedProjectId.value || !loadedDatasetId.value) return
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
        `模型训练 ${existingModel.model_id} 已存在。重新训练会先删除旧模型产物，再开始训练。`,
        '覆盖训练模型',
        { type: 'warning', confirmButtonText: '覆盖并训练', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  await submitTask('训练模型', async () => {
    const modelId = trainForm.model_id.trim()
    const response = await api.submitTrain(selectedProjectId.value, { ...trainForm, model_id: modelId })
    trackTask(response.task)
    pendingModelId.value = modelId
    pendingModelTaskId.value = response.task.id
    selectedModelId.value = modelId
    loadedModelId.value = modelId
    modelDetailRefreshKey.value += 1
    retrainModelDetail.value = null
    trainDialogVisible.value = false
    return response.task
  })
}

function openGenerationDialog(file: ModelCheckpoint) {
  if (operationPending.value) return
  if (!loadedModelId.value) {
    ElMessage.warning('请先载入模型训练资源。')
    return
  }
  generationForm.value.checkpoint = file.relative_path
  generationScenarioSetSuffix.value = nextTimestampSuffix()
  syncGenerationScenarioSetId()
  generationForm.value.source_mode = 'scenario_set'
  generationForm.value.source_scenario_set_id = ''
  generationForm.value.timetable_file = null
  generationForm.value.mileage_file = null
  generationTimetableFiles.value = []
  generationMileageFiles.value = []
  generationForm.value.speed_interruption_threshold = DEFAULT_SPEED_INTERRUPTION_THRESHOLD
  generationDialogVisible.value = true
}

function syncGenerationScenarioSetId() {
  const prefix = generationScenarioSetPrefix.value
  const suffix = generationScenarioSetSuffix.value.trim()
  generationForm.value.scenario_set_id = prefix && suffix ? `${prefix}_${suffix}` : prefix || suffix
}

async function submitGeneration() {
  if (!loadedModelId.value) return
  syncGenerationScenarioSetId()
  if (!generationForm.value.checkpoint) {
    ElMessage.warning('请先选择 checkpoint 文件。')
    return
  }
  if (!generationForm.value.scenario_set_id.trim()) {
    ElMessage.warning('请填写生成到的场景分类 ID。')
    return
  }
  if (generationForm.value.source_mode === 'scenario_set' && !generationForm.value.source_scenario_set_id.trim()) {
    ElMessage.warning('请选择 Context 来源分类。')
    return
  }
  if (
    generationForm.value.source_mode === 'upload' &&
    (!generationForm.value.timetable_file || !generationForm.value.mileage_file)
  ) {
    ElMessage.warning('请上传时刻表和里程表。')
    return
  }
  await submitTask('生成场景', async () => {
    const response = generationForm.value.source_mode === 'upload'
      ? await api.submitGenerationUpload(selectedProjectId.value, {
        modelId: loadedModelId.value,
        checkpoint: generationForm.value.checkpoint,
        scenarioSetId: generationForm.value.scenario_set_id,
        outputPrefix: generationForm.value.output_prefix,
        numSamples: generationForm.value.num_samples,
        seed: generationForm.value.seed,
        device: generationForm.value.device,
        speedInterruptionThreshold: generationForm.value.speed_interruption_threshold,
        overwrite: generationForm.value.overwrite,
        timetableFile: generationForm.value.timetable_file as File,
        mileageFile: generationForm.value.mileage_file as File,
      })
      : await api.submitGeneration(
        selectedProjectId.value,
        loadedModelId.value,
        generationForm.value.checkpoint,
        generationForm.value.scenario_set_id,
        generationForm.value.source_scenario_set_id,
        generationForm.value.output_prefix,
        generationForm.value.num_samples,
        generationForm.value.seed,
        generationForm.value.device,
        generationForm.value.speed_interruption_threshold,
        generationForm.value.overwrite,
      )
    trackTask(response.task)
    generationDialogVisible.value = false
    return response.task
  })
}

function setGenerationTimetableFile(file: UploadFile) {
  if (file.raw) generationForm.value.timetable_file = file.raw
}

function setGenerationMileageFile(file: UploadFile) {
  if (file.raw) generationForm.value.mileage_file = file.raw
}

async function deleteModelById(modelId: string) {
  if (!selectedProjectId.value || !modelId) return
  try {
    await ElMessageBox.confirm(
      `确认删除模型训练 ${modelId}？该操作会删除模型产物目录。`,
      '删除模型训练',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await runAction('删除模型训练', async () => {
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
    return `模型训练 ${modelId} 已删除`
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

async function scrollMainToTop() {
  await nextTick()
  mainScrollbar.value?.setScrollTop(0)
}

function warnSingleFile() {
  ElMessage.warning('每项只需要一个文件，请先移除后重新选择。')
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
      <el-aside width="220px" class="app-aside">
        <AppNavigation :active-page="activePage" @select="selectPage" />
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
              @create="createProject"
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
              <el-empty v-if="!hasProject" description="还没有可用项目">
                <el-text type="info">请在顶部项目下拉框中新建项目</el-text>
              </el-empty>

              <template v-else>
                <DashboardView
                  v-if="activePage === 'dashboard'"
                  :selected-project-id="selectedProjectId"
                  :scenario-set-count="scenarioSets.length"
                  :datasets="datasets"
                  :models="models"
                  :tasks="tasks"
                  :running-task-count="runningTaskCount"
                  :done-task-count="doneTaskCount"
                  :failed-task-count="failedTaskCount"
                  :busy="operationPending"
                  @refresh-tasks="refreshTasks"
                />

                <ScenarioSetsView
                  v-else-if="activePage === 'scenarios'"
                  :key="scenarioCategoryRefreshKey"
                  v-model:selected-scenario-set-id="selectedScenarioSetId"
                  :selected-project-id="selectedProjectId"
                  :loaded-scenario-set-id="loadedScenarioSetId"
                  :scenario-sets="scenarioSets"
                  :scenario-set-options="scenarioSetSelectOptions"
                  :resource-loading="scenarioSetOptionsLoading"
                  :detail-loading="scenarioCategoryDetailLoading"
                  :busy="operationPending"
                  @reload-scenario-sets="reloadScenarioSetsOnOpen"
                  @search-scenario-sets="searchScenarioSetOptions"
                  @create-scenario-set="scenarioSetDialogVisible = true"
                  @load-scenario-set="reloadSelectedScenarioSetDetail"
                  @delete-scenario-set="deleteScenarioSetById"
                  @simulate-scenario="openNormalGenerateDialog"
                  @create-scenario="openScenarioDialog"
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
                  @activated="loadSelectedProject(false)"
                />

                <DatasetsView
                  v-else-if="activePage === 'datasets'"
                  :key="datasetDetailRefreshKey"
                  v-model:selected-dataset-id="selectedDatasetId"
                  :selected-project-id="selectedProjectId"
                  :loaded-dataset-id="loadedDatasetId"
                  :loaded-dataset="loadedDataset"
                  :datasets="datasets"
                  :dataset-options="datasetSelectOptions"
                  :resource-loading="datasetOptionsLoading"
                  :detail-loading="datasetDetailLoading"
                  :busy="operationPending"
                  @reload-datasets="reloadDatasetsOnOpen"
                  @search-datasets="searchDatasetOptions"
                  @create-dataset="openDatasetCreateDialog"
                  @load-dataset="reloadSelectedDatasetDetail"
                  @delete-dataset="deleteDatasetById"
                  @build-dataset="openDatasetBuildDialog"
                  @solve-all="() => openSolveDialog()"
                  @solve-case="openSolveDialog"
                  @export-all-timetables="() => submitExportTimetable()"
                  @export-timetable="submitExportTimetable"
                  @open-timetable="openCaseTimetable"
                  @loading-change="datasetDetailLoading = $event"
                />

                <ModelsView
                  v-else-if="activePage === 'models'"
                  :key="modelDetailRefreshKey"
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

                <AblationView
                  v-else-if="activePage === 'ablation-scenarios' || activePage === 'ablation-datasets'"
                  :page="activePage"
                  :selected-project-id="selectedProjectId"
                  :scenario-sets="scenarioSets"
                  :datasets="datasets"
                  :busy="operationPending"
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
      <AppNavigation :active-page="activePage" @select="selectPage" />
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
        <el-form-item label="时刻表">
          <el-upload
            v-model:file-list="scenarioCreateTimetableFiles"
            :auto-upload="false"
            :limit="1"
            :on-change="setScenarioCreateTimetableFile"
            :on-exceed="warnSingleFile"
            :disabled="operationPending"
          >
            <el-button :disabled="operationPending">上传时刻表</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="里程表">
          <el-upload
            v-model:file-list="scenarioCreateMileageFiles"
            :auto-upload="false"
            :limit="1"
            :on-change="setScenarioCreateMileageFile"
            :on-exceed="warnSingleFile"
            :disabled="operationPending"
          >
            <el-button :disabled="operationPending">上传里程表</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="场景 ID">
          <el-input v-model="scenarioDialogInitialId" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="场景分类">
          <div class="inline-control-row">
            <RemoteResourceSelect
              v-model="scenarioCreateScenarioSetId"
              :options="scenarioSetSelectOptions"
              placeholder="选择场景分类"
              :disabled="operationPending"
              :loading="scenarioSetOptionsLoading"
              @search="searchScenarioSetOptions"
              @visible-change="reloadScenarioSetsOnOpen"
            />
            <el-button :disabled="operationPending" @click="scenarioSetDialogVisible = true">新增</el-button>
          </div>
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
        <el-form-item label="时刻表">
          <el-upload
            v-model:file-list="normalGenerateTimetableFiles"
            :auto-upload="false"
            :limit="1"
            :on-change="setNormalGenerateTimetableFile"
            :on-exceed="warnSingleFile"
            :disabled="operationPending"
          >
            <el-button :disabled="operationPending">上传时刻表</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="里程表">
          <el-upload
            v-model:file-list="normalGenerateMileageFiles"
            :auto-upload="false"
            :limit="1"
            :on-change="setNormalGenerateMileageFile"
            :on-exceed="warnSingleFile"
            :disabled="operationPending"
          >
            <el-button :disabled="operationPending">上传里程表</el-button>
          </el-upload>
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

          <el-divider content-position="left">辅助扰动判断</el-divider>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="最大槽位" :tip="TRAIN_FIELD_TIPS.max_slots" />
                </template>
                <el-input-number v-model="trainForm.max_slots" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="事件窗口" :tip="TRAIN_FIELD_TIPS.event_time_window" />
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
                  <FieldLabelTip label="事件 Top K" :tip="TRAIN_FIELD_TIPS.event_top_k" />
                </template>
                <el-input-number v-model="trainForm.event_top_k" :min="1" :disabled="operationPending" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <el-form-item>
                <template #label>
                  <FieldLabelTip label="区间窗口" :tip="TRAIN_FIELD_TIPS.section_order_window" />
                </template>
                <el-input-number
                  v-model="trainForm.section_order_window"
                  :min="1"
                  :disabled="operationPending"
                />
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
                  <FieldLabelTip label="Relation" :tip="TRAIN_FIELD_TIPS.relation_weight" />
                </template>
                <el-input-number
                  v-model="trainForm.relation_weight"
                  :min="0"
                  :step="0.1"
                  :disabled="operationPending"
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

    <el-dialog v-model="generationDialogVisible" title="使用模型生成数据" width="560px">
      <el-form label-width="150px">
        <el-form-item label="模型训练">
          <el-input :model-value="selectedModelId" disabled />
        </el-form-item>
        <el-form-item label="Checkpoint">
          <el-input :model-value="generationForm.checkpoint" disabled />
        </el-form-item>
        <el-form-item>
          <template #label>
            <FieldLabelTip label="输出场景分类" :tip="GENERATION_FIELD_TIPS.scenario_set_id" />
          </template>
          <el-input
            v-model="generationScenarioSetSuffix"
            placeholder="默认使用当前时间戳"
            :disabled="operationPending"
          >
            <template #prepend>{{ generationScenarioSetPrefix }}_</template>
          </el-input>
        </el-form-item>
        <el-form-item label="Context 来源">
          <el-radio-group v-model="generationForm.source_mode" :disabled="operationPending">
            <el-radio-button value="scenario_set">场景分类</el-radio-button>
            <el-radio-button value="upload">上传文件</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="generationForm.source_mode === 'scenario_set'" label="来源场景分类">
          <RemoteResourceSelect
            v-model="generationForm.source_scenario_set_id"
            :options="scenarioSetSelectOptions"
            placeholder="选择已激活场景分类"
            :disabled="operationPending"
            :loading="scenarioSetOptionsLoading"
            @search="searchScenarioSetOptions"
            @visible-change="reloadScenarioSetsOnOpen"
          />
        </el-form-item>
        <template v-else>
          <el-form-item label="时刻表">
            <el-upload
              v-model:file-list="generationTimetableFiles"
              :auto-upload="false"
              :limit="1"
              :on-change="setGenerationTimetableFile"
              :on-exceed="warnSingleFile"
              :disabled="operationPending"
            >
              <el-button :disabled="operationPending">上传时刻表</el-button>
            </el-upload>
          </el-form-item>
          <el-form-item label="里程表">
            <el-upload
              v-model:file-list="generationMileageFiles"
              :auto-upload="false"
              :limit="1"
              :on-change="setGenerationMileageFile"
              :on-exceed="warnSingleFile"
              :disabled="operationPending"
            >
              <el-button :disabled="operationPending">上传里程表</el-button>
            </el-upload>
          </el-form-item>
        </template>
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
          提交生成
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="datasetCreateDialogVisible" title="构建 MILP 实例集" width="560px">
      <el-form label-width="130px" @submit.prevent="createDataset">
        <el-form-item label="创建方式">
          <el-radio-group v-model="datasetCreateMode" :disabled="operationPending">
            <el-radio-button value="scenario_set" :disabled="!scenarioSets.length">
              从场景分类构建
            </el-radio-button>
            <el-radio-button value="empty">创建空资源</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <template v-if="datasetCreateMode === 'scenario_set'">
          <el-form-item label="场景分类">
            <RemoteResourceSelect
              v-model="datasetCreateScenarioSetId"
              :options="scenarioSetSelectOptions"
              placeholder="选择场景分类"
              :disabled="operationPending"
              :loading="scenarioSetOptionsLoading"
              @search="searchScenarioSetOptions"
              @visible-change="reloadScenarioSetsOnOpen"
            />
          </el-form-item>
          <el-form-item label="MILP 实例集 ID">
            <el-input
              :model-value="newDatasetId"
              disabled
              @keydown.enter.prevent="createDataset"
            />
          </el-form-item>
          <el-collapse :model-value="['build-options']">
            <el-collapse-item title="构建参数" name="build-options">
              <BuildOptionsFields
                :model-value="datasetBuildForm"
                @update:model-value="updateDatasetBuildOptions"
              />
            </el-collapse-item>
          </el-collapse>
        </template>
        <el-form-item v-else label="MILP 实例集 ID">
          <el-input
            v-model="newDatasetId"
            placeholder="例如 milp_reference"
            :disabled="operationPending"
            @keydown.enter.prevent="createDataset"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="operationPending" @click="datasetCreateDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '构建 MILP 实例集' || activeOperation === '创建空 MILP 实例集'"
          :disabled="operationPending"
          @click="createDataset"
        >
          {{ datasetCreateMode === 'scenario_set' ? '提交构建' : '创建空资源' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="datasetBuildDialogVisible" title="构建/重建 MILP 实例集" width="640px">
      <el-form label-width="150px">
        <el-form-item label="MILP 实例集 ID">
          <el-input :model-value="loadedDatasetId" disabled />
        </el-form-item>
        <el-form-item label="构建来源">
          <el-radio-group v-model="datasetBuildForm.source" :disabled="operationPending">
            <el-radio-button value="scenario_set">从场景分类中构建</el-radio-button>
            <el-radio-button value="scenario">从场景中构建</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="场景分类">
          <RemoteResourceSelect
            v-model="datasetBuildForm.scenario_set_id"
            :options="scenarioSetSelectOptions"
            placeholder="选择场景分类"
            :disabled="operationPending"
            :loading="scenarioSetOptionsLoading"
            @search="searchScenarioSetOptions"
            @visible-change="reloadScenarioSetsOnOpen"
            @change="onDatasetBuildScenarioSetChange"
          />
        </el-form-item>
        <el-form-item v-if="datasetBuildForm.source === 'scenario'" label="场景">
          <RemoteResourceSelect
            v-model="datasetBuildForm.scenario_id"
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
              :model-value="datasetBuildForm"
              @update:model-value="updateDatasetBuildOptions"
            />
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
        <el-button :disabled="operationPending" @click="datasetBuildDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="activeOperation === '构建 MILP'"
          :disabled="operationPending"
          @click="submitBuild"
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
          <el-input-number v-model="datasetRunForm.solveLimit" :min="0" :disabled="operationPending" />
          <span class="form-hint">0 表示全部</span>
        </el-form-item>
        <el-form-item v-if="!solveTargetCaseId" label="已有解则跳过">
          <el-switch v-model="datasetRunForm.skipSolved" :disabled="operationPending" />
        </el-form-item>
        <el-form-item label="单次限时秒数">
          <el-input-number v-model="datasetRunForm.solveTimeLimit" :min="0" :disabled="operationPending" />
          <span class="form-hint">0 表示不限制</span>
        </el-form-item>
        <el-form-item label="MIP Gap">
          <el-input-number
            v-model="datasetRunForm.solveMipGap"
            :min="0"
            :step="0.001"
            :disabled="operationPending"
          />
        </el-form-item>
        <el-form-item label="线程数">
          <el-input-number v-model="datasetRunForm.solveThreads" :min="0" :disabled="operationPending" />
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
      v-model="timetableDialogVisible"
      :project-id="selectedProjectId"
      :dataset-id="loadedDatasetId"
      :case-id="timetableCaseId"
    />

    <TaskLogDialog v-model="taskLogDialogVisible" :task="taskLogTarget" />
  </div>
</template>
