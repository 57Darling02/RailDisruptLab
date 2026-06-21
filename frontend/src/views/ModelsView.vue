<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import { api, ApiError } from '@/api/client'
import ChartPanel from '@/components/ChartPanel.vue'
import EntityToolbar from '@/components/EntityToolbar.vue'
import { Refresh } from '@/icons'
import { formatBytes } from '@/views/types'
import type { MetadataEntry, SchemaEdgeRow, SchemaPoolRow, SchemaTaskRow } from '@/views/types'
import type {
  JsonObject,
  ModelCheckpoint,
  ModelDetail,
  ModelLossSeriesPoint,
  ModelTrainingProgress,
  ModelSummary,
  ResourceOption,
  Task,
} from '@/types'
import { isTaskTerminal } from '@/task-status'
import type { TaskTagType } from '@/task-status'

const props = defineProps<{
  selectedProjectId: string
  selectedModelId: string
  loadedModelId: string
  pendingModelId: string
  loadedModel: ModelSummary | null
  models: ModelSummary[]
  modelOptions: ResourceOption[]
  resourceLoading: boolean
  detailLoading?: boolean
  tasks: Task[]
  busy?: boolean
}>()

const emit = defineEmits<{
  'update:selectedModelId': [value: string]
  reloadModels: [visible: boolean]
  searchModels: [query: string]
  loadModel: []
  train: []
  retrain: [detail: ModelDetail | null]
  deleteModel: [modelId: string]
  openTaskLog: [task: Task]
  generate: [checkpoint: ModelCheckpoint]
  loadingChange: [loading: boolean]
}>()

const TRAINING_CONFIG_LABELS: Record<string, string> = {
  scenario_set_id: '训练场景分类',
  max_slots: 'G_D 最大扰动数',
  event_time_window: 'C 事件时间窗口',
  event_top_k: 'C 事件邻接上限',
  section_order_window: 'C 区间邻接窗口',
  hidden_dim: '隐藏维度',
  latent_dim: '潜变量维度',
  message_passing_steps: '消息传递步数',
  epochs: '训练轮数',
  checkpoint_every: '检查点间隔',
  batch_size: 'Batch Size',
  lr: '学习率',
  seed: '随机种子',
  device: '设备',
  count_weight: 'Count 权重',
  anchor_weight: 'Anchor 权重',
  param_weight: 'Param 权重',
  kl_weight: 'KL 权重',
  use_relation_graph: '启用关系图 R',
  relation_weight: 'R 损失权重',
}
const TRAINING_CONFIG_ORDER = Object.keys(TRAINING_CONFIG_LABELS)
const MODEL_DETAIL_POLL_MS = 2500
const LOSS_METRICS = [
  { key: 'loss', label: '总 loss' },
  { key: 'count_loss', label: '数量' },
  { key: 'anchor_loss', label: '锚点' },
  { key: 'param_loss', label: '参数' },
  { key: 'relation_loss', label: 'Relation' },
  { key: 'kl', label: 'KL' },
] as const

const modelDetail = ref<ModelDetail | null>(null)
const modelDetailLoading = ref(false)
const modelDetailError = ref('')
let modelDetailRequestSeq = 0
let modelDetailPollHandle = 0

type LossMetricKey = (typeof LOSS_METRICS)[number]['key']
type ProgressStatus = 'success' | 'exception' | 'warning' | undefined

interface LossSeriesDatum {
  value: [number, number]
  epoch: number
  metric: LossMetricKey
  label: string
  count: number
  min: number
  max: number
  last: number
}

interface TrainingMetricCard {
  key: string
  label: string
  value: string
  detail: string
}

interface LossTooltipParam {
  data?: LossSeriesDatum
  marker?: string
  seriesName?: string
}

const trainingSummary = computed(() => modelDetail.value?.summary ?? null)
const modelCheckpoints = computed(() => modelDetail.value?.checkpoints ?? [])
const primaryCheckpoint = computed(
  () =>
    modelCheckpoints.value.find((item) => checkpointRoles(item).includes('best')) ??
    modelCheckpoints.value.find((item) => checkpointRoles(item).includes('last')) ??
    modelCheckpoints.value[0] ??
    null,
)
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
const trainingProgress = computed(() => modelDetail.value?.training_progress ?? null)
const epochLossSeriesByMetric = computed(() => normalizeLossSeries(modelDetail.value?.loss_series ?? {}))
const primaryEpochLossPoints = computed(() => epochLossSeriesByMetric.value.loss)
const lossChartOption = computed(() => buildLossChartOption(epochLossSeriesByMetric.value))
const latestEpochLoss = computed(() => primaryEpochLossPoints.value.at(-1))
const loadedTrainTask = computed(() => findModelTrainTask(props.tasks, props.loadedModelId))
const loadedModelRunning = computed(() => Boolean(loadedTrainTask.value && !isTaskTerminal(loadedTrainTask.value)))
const reloadingSelection = computed(
  () =>
    Boolean(props.selectedModelId) &&
    props.selectedModelId === props.loadedModelId &&
    loadedModelRunning.value &&
    Boolean(props.detailLoading),
)
const overallTrainingProgress = computed(() => trainingProgress.value?.percentage ?? 0)
const overallProgressStatus = computed<ProgressStatus>(() => progressStatus(trainingProgress.value?.status))
const trainingStatus = computed(() => trainingProgressStatus(trainingProgress.value))
const trainingMetricCards = computed(() => modelTrainingMetricCards())
const progressStages = computed(() => modelProgressStages())
const bestLoss = computed(() =>
  primaryEpochLossPoints.value.reduce<LossSeriesDatum | null>(
    (best, point) => (!best || point.value[1] < best.value[1] ? point : best),
    null,
  ),
)

watch(
  () => [
    props.selectedProjectId,
    props.loadedModelId,
    props.loadedModel?.sample_count ?? 0,
    props.loadedModel?.is_ready ?? false,
    props.pendingModelId,
    loadedTrainTask.value?.status ?? '',
  ] as const,
  (current, previous) => {
    const modelChanged = current[0] !== previous?.[0] || current[1] !== previous?.[1]
    void loadModelDetails({ showLoading: modelChanged || !modelDetail.value })
  },
  { immediate: true },
)

watch(loadedModelRunning, (isRunning) => {
  if (isRunning) {
    startModelDetailPolling()
  } else {
    stopModelDetailPolling()
  }
}, { immediate: true })

watch(modelDetailLoading, (value) => {
  emit('loadingChange', value)
}, { immediate: true })

onUnmounted(() => {
  stopModelDetailPolling()
})

async function refreshModelDetails() {
  await loadModelDetails()
}

async function loadModelDetails(options: { showLoading?: boolean } = {}) {
  const projectId = props.selectedProjectId
  const modelId = props.loadedModelId
  modelDetailRequestSeq += 1
  const requestSeq = modelDetailRequestSeq
  modelDetailError.value = ''

  if (!projectId || !modelId) {
    modelDetail.value = null
    modelDetailLoading.value = false
    return
  }

  const showLoading = options.showLoading ?? true
  if (showLoading) modelDetailLoading.value = true
  try {
    const detail = await api.readModelDetail(projectId, modelId)
    if (requestSeq === modelDetailRequestSeq && projectId === props.selectedProjectId && modelId === props.loadedModelId) {
      modelDetail.value = detail
    }
  } catch (error) {
    if (requestSeq === modelDetailRequestSeq && projectId === props.selectedProjectId && modelId === props.loadedModelId) {
      modelDetail.value = null
      modelDetailError.value = formatError(error)
    }
  } finally {
    if (
      showLoading &&
      requestSeq === modelDetailRequestSeq &&
      projectId === props.selectedProjectId &&
      modelId === props.loadedModelId
    ) {
      modelDetailLoading.value = false
    }
  }
}

function handleRetrain() {
  emit('retrain', modelDetail.value)
}

function useCheckpointForGeneration(checkpoint: ModelCheckpoint | null) {
  if (!checkpoint || props.busy) return
  emit('generate', checkpoint)
}

function startModelDetailPolling() {
  if (modelDetailPollHandle) return
  modelDetailPollHandle = window.setInterval(() => {
    void loadModelDetails({ showLoading: false })
  }, MODEL_DETAIL_POLL_MS)
}

function stopModelDetailPolling() {
  if (!modelDetailPollHandle) return
  window.clearInterval(modelDetailPollHandle)
  modelDetailPollHandle = 0
}

function formatMetadataValue(key: string, value: unknown) {
  if (value == null || value === '') return '无'
  if (key === 'created_at' && typeof value === 'string') return value.replace('T', ' ')
  if (key === 'source') {
    if (value === 'scenario') return '单个场景'
    if (value === 'scenario_set') return '场景分类'
  }
  if (typeof value === 'boolean') return value ? '是' : '否'
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

function checkpointRoles(checkpoint: ModelCheckpoint) {
  const roles = checkpoint.roles?.length ? checkpoint.roles : [checkpoint.role]
  return roles.filter(Boolean)
}

function checkpointTooltip(checkpoint: ModelCheckpoint) {
  return `${checkpointRoles(checkpoint).map(checkpointRoleLabel).join(' / ')} · ${checkpoint.relative_path} · ${formatBytes(checkpoint.size_bytes)}`
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

function formatError(error: unknown) {
  if (error instanceof ApiError) return `${error.status}: ${error.message}`
  if (error instanceof Error) return error.message
  return String(error)
}

function modelTrainingMetricCards(): TrainingMetricCard[] {
  const metrics = trainingProgress.value?.metrics
  return [
    {
      key: 'epoch',
      label: 'Epoch',
      value: metrics?.latest_epoch ? String(metrics.latest_epoch) : '无',
      detail: metrics?.total_epochs ? `目标 ${metrics.total_epochs}` : '未开始',
    },
    {
      key: 'latest_loss',
      label: '最新 Loss',
      value: formatMetric(metrics?.latest_loss),
      detail: metrics?.latest_step ? `step ${metrics.latest_step}` : '等待日志',
    },
    {
      key: 'best_loss',
      label: '最佳 Loss',
      value: formatMetric(metrics?.best_loss),
      detail: metrics?.best_epoch ? `epoch ${metrics.best_epoch}` : '等待日志',
    },
    {
      key: 'checkpoints',
      label: 'Checkpoint',
      value: String(metrics?.checkpoint_count ?? 0),
      detail: props.loadedModel?.is_ready ? '可用于生成' : '训练完成后生成',
    },
  ]
}

function modelProgressStages() {
  return (trainingProgress.value?.stages ?? []).map((stage) => ({
    ...stage,
    tagType: stageTagType(stage.status),
    progressStatus: progressStatus(stage.status),
  }))
}

function trainingProgressStatus(progress: ModelTrainingProgress | null) {
  return {
    label: progress?.label ?? '等待训练',
    tag: progressStatusLabel(progress?.status),
    tagType: progressTagType(progress?.status),
    detail: progress?.detail ?? '点击训练新模型开始',
  }
}

function progressStatusLabel(status: string | undefined) {
  return {
    idle: '空闲',
    graphing: '构图中',
    training: '训练中',
    ready: '可用',
    incomplete: '未完成',
    failed: '失败',
  }[status || 'idle'] ?? status ?? '空闲'
}

function progressTagType(status: string | undefined): TaskTagType {
  if (status === 'ready') return 'success'
  if (status === 'graphing' || status === 'training') return 'primary'
  if (status === 'incomplete') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

function stageTagType(status: string): TaskTagType {
  if (status === 'done') return 'success'
  if (status === 'running') return 'primary'
  if (status === 'failed') return 'danger'
  return 'info'
}

function progressStatus(status: string | undefined): ProgressStatus {
  if (status === 'ready' || status === 'done') return 'success'
  if (status === 'failed') return 'exception'
  return undefined
}

function normalizeLossSeries(series: Record<string, ModelLossSeriesPoint[]>) {
  const result: Record<LossMetricKey, LossSeriesDatum[]> = {
    loss: [],
    count_loss: [],
    anchor_loss: [],
    param_loss: [],
    relation_loss: [],
    kl: [],
  }
  for (const metric of LOSS_METRICS) {
    result[metric.key] = (series[metric.key] ?? []).map((point) => ({
      value: [point.epoch, point.value],
      epoch: point.epoch,
      metric: metric.key,
      label: metric.label,
      count: point.count,
      min: point.min,
      max: point.max,
      last: point.last,
    }))
  }
  return result
}

function buildLossChartOption(seriesByMetric: Record<LossMetricKey, LossSeriesDatum[]>) {
  const series = LOSS_METRICS
    .map((metric) => ({ metric, data: seriesByMetric[metric.key] ?? [] }))
    .filter((item) => item.data.length)
    .map((item) => ({
      name: item.metric.label,
      type: 'line',
      smooth: true,
      showSymbol: item.data.length <= 80,
      data: item.data,
    }))
  return {
    animationDuration: 300,
    legend: { top: 0, type: 'scroll' },
    grid: { top: 34, right: 24, bottom: 36, left: 58 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: LossTooltipParam[] | LossTooltipParam) => {
        const items = Array.isArray(params) ? params : [params]
        const firstPoint = items.find((item) => item?.data)?.data
        if (!firstPoint) return ''
        return [
          `epoch ${firstPoint.epoch}`,
          ...items
            .filter((item) => item?.data)
            .map((item) => {
              const point = item.data as LossSeriesDatum
              return `${item.marker || ''}${item.seriesName || point.label}: ${point.value[1].toFixed(6)}`
            }),
        ].join('<br/>')
      },
    },
    xAxis: { type: 'value', name: 'epoch', minInterval: 1 },
    yAxis: { type: 'value', name: 'loss', scale: true },
    series,
  }
}

function findModelTrainTask(tasks: Task[], modelId: string) {
  if (!modelId) return null
  const pattern = new RegExp(`(?:^|\\s)model\\s+train\\s+${escapeRegExp(modelId)}(?:\\s|$)`)
  return (
    tasks
      .filter((task) => task.label === 'train')
      .slice()
      .reverse()
      .find((task) => trainTaskModelId(task) === modelId || pattern.test(task.command || task.original_command || '')) ?? null
  )
}

function trainTaskModelId(task: Task) {
  const params = task.params ?? {}
  const modelId = params.model_id
  return typeof modelId === 'string' ? modelId : ''
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <EntityToolbar
        label="选择模型"
        :model-value="selectedModelId"
        :options="modelOptions"
        :loading="resourceLoading"
        add-label="训练新模型"
        placeholder="选择模型"
        delete-label="删除模型"
        :busy="busy"
        @update:model-value="$emit('update:selectedModelId', $event)"
        @visible-change="$emit('reloadModels', $event)"
        @search="$emit('searchModels', $event)"
        @add="$emit('train')"
        @delete="$emit('deleteModel', $event)"
      >
        <template #actions>
          <el-button
            type="primary"
            :icon="Refresh"
            :loading-icon="Refresh"
            :loading="reloadingSelection"
            :disabled="busy || !selectedModelId"
            @click="$emit('loadModel')"
          >
            加载
          </el-button>
        </template>
      </EntityToolbar>
      <div v-if="!models.length && !pendingModelId" class="primary-empty-panel">
        <el-empty :image-size="120">
          <template #description>
            <div class="primary-empty-title">暂无模型资源</div>
          </template>
          <el-button type="primary" size="large" :disabled="busy" @click="$emit('train')">
            训练新模型
          </el-button>
        </el-empty>
      </div>
      <el-alert
        v-if="pendingModelId"
        class="dialog-section"
        :title="`模型 ${pendingModelId} 正在训练，产物状态会随任务更新。`"
        type="info"
        show-icon
        :closable="false"
      />

      <el-card
        v-if="models.length || pendingModelId"
        v-loading="modelDetailLoading && !modelDetail"
        element-loading-text="正在加载模型数据..."
        shadow="never"
      >
        <template #header>
          <div class="card-header">
            <el-space>
              <span>{{ loadedModelId ? `模型ID: ${loadedModelId}` : '模型ID' }}</span>
              <el-button :disabled="!loadedModelId || busy" type="warning" plain @click="handleRetrain">
                重新训练
              </el-button>
            </el-space>
            <el-space wrap>
              <el-tooltip
                :disabled="!primaryCheckpoint"
                :content="primaryCheckpoint ? checkpointTooltip(primaryCheckpoint) : ''"
                placement="top"
              >
                <el-button
                  type="primary"
                  :disabled="busy || !primaryCheckpoint"
                  @click="useCheckpointForGeneration(primaryCheckpoint)"
                >
                  使用模型生成场景
                </el-button>
              </el-tooltip>
              <el-button
                :icon="Refresh"
                :loading-icon="Refresh"
                :disabled="busy || !loadedModelId"
                :loading="modelDetailLoading"
                @click="refreshModelDetails"
              >
                刷新
              </el-button>
            </el-space>
          </div>
        </template>

        <el-empty v-if="!loadedModelId" description="请选择模型">
          <el-button
            type="primary"
            :icon="Refresh"
            :loading-icon="Refresh"
            :loading="reloadingSelection"
            :disabled="busy || !selectedModelId"
            @click="$emit('loadModel')"
          >
            加载
          </el-button>
        </el-empty>
        <el-result v-else-if="modelDetailError" icon="error" title="模型数据加载失败" :sub-title="modelDetailError">
          <template #extra>
            <el-button
              type="primary"
              :icon="Refresh"
              :loading-icon="Refresh"
              :loading="modelDetailLoading"
              :disabled="busy"
              @click="refreshModelDetails"
            >
              重试
            </el-button>
          </template>
        </el-result>
        <template v-else>
          <div class="model-progress-board">
            <div class="training-status-panel">
              <div class="training-status-heading">
                <div>
                  <span class="training-status-title">{{ trainingStatus.label }}</span>
                  <span class="training-status-detail">{{ trainingStatus.detail }}</span>
                </div>
                <el-tag :type="trainingStatus.tagType" size="large">{{ trainingStatus.tag }}</el-tag>
              </div>
              <el-progress
                :percentage="overallTrainingProgress"
                :status="overallProgressStatus"
                :stroke-width="12"
              />
              <div class="training-metric-grid">
                <div v-for="item in trainingMetricCards" :key="item.key" class="training-metric">
                  <span class="training-metric-label">{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                  <span>{{ item.detail }}</span>
                </div>
              </div>
              <div class="training-stage-grid">
                <div v-for="stage in progressStages" :key="stage.key" class="training-stage">
                  <div class="training-stage-header">
                    <span>{{ stage.label }}</span>
                    <el-tag :type="stage.tagType" size="small">{{ stage.status }}</el-tag>
                  </div>
                  <el-progress
                    :percentage="stage.percentage"
                    :status="stage.progressStatus"
                    :stroke-width="8"
                  />
                  <span class="training-stage-detail">{{ stage.detail }}</span>
                </div>
              </div>
            </div>

            <div class="checkpoint-panel">
              <div class="checkpoint-panel-header">
                <span>模型产物</span>
                <el-button
                  v-if="loadedTrainTask"
                  link
                  type="primary"
                  @click="$emit('openTaskLog', loadedTrainTask)"
                >
                  任务 #{{ loadedTrainTask.id }}
                </el-button>
              </div>
              <div v-if="modelCheckpoints.length" class="checkpoint-list">
                <div v-for="checkpoint in modelCheckpoints" :key="checkpoint.relative_path" class="checkpoint-row">
                  <div class="checkpoint-tags">
                    <el-tag
                      v-for="role in checkpointRoles(checkpoint)"
                      :key="role"
                      :type="checkpointRoleType(role)"
                      size="small"
                    >
                      {{ checkpointRoleLabel(role) }}
                    </el-tag>
                  </div>
                  <el-tooltip :content="checkpointTooltip(checkpoint)" placement="top">
                    <span class="checkpoint-name">{{ checkpoint.name }}</span>
                  </el-tooltip>
                  <span class="checkpoint-size">{{ formatBytes(checkpoint.size_bytes) }}</span>
                  <el-button
                    link
                    type="primary"
                    :disabled="busy"
                    @click="useCheckpointForGeneration(checkpoint)"
                  >
                    用此产物生成
                  </el-button>
                </div>
              </div>
              <el-empty v-else description="暂无可用 checkpoint" :image-size="72" />
            </div>
          </div>

          <el-divider content-position="left">训练参数</el-divider>
          <el-descriptions
            v-if="hasTrainingConfig"
            class="metadata-descriptions"
            :column="3"
            border
            size="small"
          >
            <el-descriptions-item
              v-for="entry in modelConfigEntries"
              :key="entry.key"
              :label="entry.label"
            >
              {{ entry.value }}
            </el-descriptions-item>
          </el-descriptions>
          <el-empty v-else description="暂无训练参数" />

          <el-divider content-position="left">训练摘要</el-divider>
          <div class="loss-panel">
            <el-descriptions
              v-if="hasTrainingSummary"
              class="metadata-descriptions"
              :column="5"
              border
              size="small"
            >
              <el-descriptions-item
                v-for="entry in modelSummaryEntries"
                :key="entry.key"
                :label="entry.label"
              >
                {{ entry.value }}
              </el-descriptions-item>
            </el-descriptions>
            <div class="loss-chart-card">
              <div class="loss-chart-header">
                <span>Loss 曲线（按 Epoch 平均）</span>
                <el-space v-if="latestEpochLoss" size="small">
                  <el-tag size="small">最新 {{ latestEpochLoss.value[1].toFixed(6) }}</el-tag>
                  <el-tag v-if="bestLoss" size="small" type="success">
                    最佳 {{ bestLoss.value[1].toFixed(6) }}
                  </el-tag>
                </el-space>
              </div>
              <ChartPanel
                v-if="primaryEpochLossPoints.length"
                :option="lossChartOption"
                filename="training-loss"
                chart-class="loss-chart"
                height="260px"
              />
              <el-empty v-else description="刷新后将从训练日志解析 loss" :image-size="72" />
            </div>
          </div>

          <el-divider content-position="left">图结构摘要</el-divider>
          <template v-if="hasSchemaSummary">
            <el-descriptions class="metadata-descriptions" :column="5" border size="small">
              <el-descriptions-item
                v-for="entry in modelSchemaSummaryEntries"
                :key="entry.key"
                :label="entry.label"
              >
                {{ entry.value }}
              </el-descriptions-item>
            </el-descriptions>
            <el-tabs class="dialog-section">
              <el-tab-pane label="节点池">
                <el-table :data="modelPoolRows" max-height="240" table-layout="fixed" empty-text="暂无节点池信息">
                  <el-table-column prop="id" label="ID" width="90" show-overflow-tooltip />
                  <el-table-column prop="size" label="节点数" />
                  <el-table-column prop="feature_dim" label="特征维度" />
                </el-table>
              </el-tab-pane>
              <el-tab-pane label="边类型">
                <el-table :data="modelEdgeRows" max-height="240" table-layout="fixed" empty-text="暂无边类型信息">
                  <el-table-column prop="id" label="ID" width="90" show-overflow-tooltip />
                  <el-table-column prop="source_pool_id" label="源节点池" show-overflow-tooltip />
                  <el-table-column prop="target_pool_id" label="目标节点池" show-overflow-tooltip />
                  <el-table-column prop="feature_dim" label="特征维度" />
                </el-table>
              </el-tab-pane>
              <el-tab-pane label="预测任务">
                <el-table :data="modelTaskRows" max-height="240" table-layout="fixed" empty-text="暂无任务信息">
                  <el-table-column prop="id" label="ID" width="90" show-overflow-tooltip />
                  <el-table-column prop="target_pool_id" label="目标节点池" show-overflow-tooltip />
                  <el-table-column prop="max_slots" label="最大槽位" />
                  <el-table-column prop="count_bounds" label="数量范围" show-overflow-tooltip />
                  <el-table-column prop="param_dim" label="参数维度" />
                </el-table>
              </el-tab-pane>
            </el-tabs>
          </template>
          <el-empty v-else description="暂无图结构摘要" />
        </template>
      </el-card>
    </div>
  </section>
</template>

<style scoped>
.model-progress-board {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.38fr);
  gap: 16px;
  align-items: stretch;
}

.training-status-panel,
.checkpoint-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.training-status-heading,
.checkpoint-panel-header,
.training-stage-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.training-status-heading > div {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 4px;
}

.training-status-title,
.checkpoint-panel-header {
  font-weight: 600;
}

.training-status-detail,
.training-metric span,
.training-stage-detail {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.training-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.training-metric {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
}

.training-metric strong {
  overflow: hidden;
  font-size: 18px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.training-metric-label {
  color: var(--el-text-color-regular);
  font-size: 12px;
}

.training-stage-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.training-stage {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
}

.training-stage-header span:first-child {
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.checkpoint-list {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
}

.checkpoint-row {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr) 72px auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.checkpoint-tags {
  display: flex;
  min-width: 0;
  gap: 4px;
}

.checkpoint-row:last-child {
  border-bottom: 0;
}

.checkpoint-name {
  overflow: hidden;
  min-width: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.checkpoint-size {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-align: right;
  white-space: nowrap;
}

.loss-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.loss-chart-card {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.loss-chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-weight: 600;
}

@media (max-width: 760px) {
  .model-progress-board,
  .training-metric-grid,
  .training-stage-grid {
    grid-template-columns: 1fr;
  }

  .checkpoint-row {
    grid-template-columns: 92px minmax(0, 1fr) auto;
  }

  .checkpoint-size {
    display: none;
  }
}

</style>
