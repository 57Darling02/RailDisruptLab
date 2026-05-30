<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import { api, ApiError } from '@/api/client'
import ChartPanel from '@/components/ChartPanel.vue'
import EntityToolbar from '@/components/EntityToolbar.vue'
import { formatBytes } from '@/views/types'
import type { MetadataEntry, SchemaEdgeRow, SchemaPoolRow, SchemaTaskRow } from '@/views/types'
import type {
  JsonObject,
  ModelCheckpoint,
  ModelDetail,
  ModelLossPoint,
  ModelSummary,
  ResourceOption,
  Task,
} from '@/types'
import { isTaskTerminal, taskOutcome } from '@/task-status'
import type { TaskTagType } from '@/task-status'

const props = defineProps<{
  selectedProjectId: string
  selectedModelId: string
  pendingModelId: string
  selectedModel: ModelSummary | null
  models: ModelSummary[]
  modelOptions: ResourceOption[]
  resourceLoading: boolean
  tasks: Task[]
  busy?: boolean
}>()

const emit = defineEmits<{
  'update:selectedModelId': [value: string]
  reloadModels: [visible: boolean]
  searchModels: [query: string]
  train: []
  retrain: [detail: ModelDetail | null]
  deleteModel: [modelId: string]
  openTaskLog: [task: Task]
  generate: [checkpoint: ModelCheckpoint]
}>()

const TRAINING_CONFIG_LABELS: Record<string, string> = {
  scenario_set_id: '训练场景分类',
  max_slots: '最大槽位',
  event_time_window: '事件时间窗口',
  event_top_k: '事件候选 Top K',
  section_order_window: '区间序窗口',
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
const MODEL_DETAIL_POLL_MS = 2500

const modelDetail = ref<ModelDetail | null>(null)
const modelDetailLoading = ref(false)
const modelDetailError = ref('')
let modelDetailRequestSeq = 0
let modelDetailPollHandle = 0

interface LossSeriesDatum {
  value: [number, number]
  epoch: number
  count: number
  min: number
  max: number
  last: number
}

interface LossTooltipParam {
  data?: LossSeriesDatum
  marker?: string
  seriesName?: string
}

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
const lossPoints = computed(() => modelDetail.value?.loss_points || [])
const epochLossPoints = computed(() => epochLossSeries(lossPoints.value))
const lossChartOption = computed(() => buildLossChartOption(epochLossPoints.value))
const latestLoss = computed(() => lossPoints.value.at(-1))
const latestEpochLoss = computed(() => epochLossPoints.value.at(-1))
const selectedTrainTask = computed(() => findModelTrainTask(props.tasks, props.selectedModelId))
const selectedModelRunning = computed(() => Boolean(selectedTrainTask.value && !isTaskTerminal(selectedTrainTask.value)))
const trainProgress = computed(() => modelTrainingProgress())
const graphProgress = computed(() => modelDetail.value?.graph_progress ?? {})
const graphSampleProgress = computed(() => graphProgress.value.sample_graphs ?? {})
const graphSamplePercent = computed(() => {
  const total = graphSampleProgress.value.total ?? 0
  const completed = graphSampleProgress.value.completed ?? 0
  if (!total) return graphSampleProgress.value.status === 'done' ? 100 : 0
  return Math.min(100, Math.max(0, Math.round((completed / total) * 100)))
})
const selectedTrainTaskFailed = computed(
  () => Boolean(selectedTrainTask.value) && taskOutcome(selectedTrainTask.value as Task) === 'failed',
)
const trainingStepActive = computed(() => {
  if (props.selectedModel?.is_ready) return 3
  if (lossPoints.value.length > 0) return 2
  if (graphProgress.value.sample_graphs?.status === 'done') return 2
  if (graphProgress.value.sample_graphs?.status === 'running') return 1
  if (graphProgress.value.global_graph?.status === 'done') return 1
  return 0
})
const trainingStepProcessStatus = computed(() =>
  selectedTrainTaskFailed.value ? 'error' : 'process',
)
const stageProgress = computed(() => {
  if (selectedTrainTaskFailed.value) {
    return {
      percentage: Math.max(graphSamplePercent.value, trainProgress.value),
      label: '任务异常',
      detail: '查看任务日志',
    }
  }
  if (props.selectedModel?.is_ready) {
    return { percentage: 100, label: '训练完成', detail: 'checkpoint 已生成' }
  }
  if (trainingStepActive.value === 2) {
    return { percentage: trainProgress.value, label: 'GNN + 训练 VAE', detail: `${trainProgress.value}%` }
  }
  if (trainingStepActive.value === 1) {
    return {
      percentage: graphSamplePercent.value,
      label: '生成扰动图 / 辅助图',
      detail: `${graphSampleProgress.value.completed ?? 0}/${graphSampleProgress.value.total ?? 0}`,
    }
  }
  return { percentage: 0, label: '全局图建模', detail: '准备图结构' }
})
const trainProgressStatus = computed(() => {
  if (selectedTrainTaskFailed.value) return 'exception'
  if (trainProgress.value >= 100 && props.selectedModel?.is_ready) return 'success'
  return undefined
})
const bestLoss = computed(() =>
  epochLossPoints.value.reduce<LossSeriesDatum | null>(
    (best, point) => (!best || point.value[1] < best.value[1] ? point : best),
    null,
  ),
)

watch(
  () => [
    props.selectedProjectId,
    props.selectedModelId,
    props.selectedModel?.sample_count ?? 0,
    props.selectedModel?.is_ready ?? false,
    props.pendingModelId,
    selectedTrainTask.value?.status ?? '',
  ] as const,
  () => {
    void loadModelDetails()
  },
  { immediate: true },
)

watch(selectedModelRunning, (isRunning) => {
  if (isRunning) {
    startModelDetailPolling()
  } else {
    stopModelDetailPolling()
  }
}, { immediate: true })

onUnmounted(() => {
  stopModelDetailPolling()
})

async function refreshModelDetails() {
  await loadModelDetails()
}

async function loadModelDetails(options: { showLoading?: boolean } = {}) {
  const projectId = props.selectedProjectId
  const modelId = props.selectedModelId
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
    if (requestSeq === modelDetailRequestSeq && projectId === props.selectedProjectId && modelId === props.selectedModelId) {
      modelDetail.value = detail
    }
  } catch (error) {
    if (requestSeq === modelDetailRequestSeq && projectId === props.selectedProjectId && modelId === props.selectedModelId) {
      modelDetail.value = null
      modelDetailError.value = formatError(error)
    }
  } finally {
    if (
      showLoading &&
      requestSeq === modelDetailRequestSeq &&
      projectId === props.selectedProjectId &&
      modelId === props.selectedModelId
    ) {
      modelDetailLoading.value = false
    }
  }
}

function handleRetrain() {
  emit('retrain', modelDetail.value)
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

function formatError(error: unknown) {
  if (error instanceof ApiError) return `${error.status}: ${error.message}`
  if (error instanceof Error) return error.message
  return String(error)
}

function modelTrainingProgress() {
  if (props.selectedModel?.is_ready) return 100
  const latest = latestLoss.value
  const epochs = numberFromConfig(modelDetail.value?.config?.epochs)
  if (!latest || !epochs || !latest.total_steps) return 0
  const total = epochs * latest.total_steps
  return Math.min(99, Math.max(0, Math.round((latest.step / total) * 100)))
}

function numberFromConfig(value: unknown) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
  }
  return 0
}

function epochLossSeries(points: ModelLossPoint[]) {
  const groups = new Map<number, ModelLossPoint[]>()
  for (const point of points) {
    const epoch = Number(point.epoch)
    if (!Number.isFinite(epoch)) continue
    const items = groups.get(epoch) ?? []
    items.push(point)
    groups.set(epoch, items)
  }
  return [...groups.entries()]
    .sort(([left], [right]) => left - right)
    .map<LossSeriesDatum>(([epoch, items]) => {
      const losses = items.map((item) => Number(item.loss)).filter(Number.isFinite)
      const mean = losses.reduce((total, loss) => total + loss, 0) / Math.max(losses.length, 1)
      return {
        value: [epoch, mean],
        epoch,
        count: losses.length,
        min: Math.min(...losses),
        max: Math.max(...losses),
        last: losses.at(-1) ?? mean,
      }
    })
}

function buildLossChartOption(data: LossSeriesDatum[]) {
  return {
    animationDuration: 300,
    grid: { top: 24, right: 24, bottom: 36, left: 58 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: LossTooltipParam[] | LossTooltipParam) => {
        const item = Array.isArray(params) ? params[0] : params
        const point = item?.data
        if (!point) return ''
        const [epoch, loss] = point.value
        return [
          `epoch ${epoch}`,
          `${item.marker || ''}${item.seriesName || 'loss'}: ${loss.toFixed(6)}`,
          `样本数 ${point.count}`,
          `最小 ${point.min.toFixed(6)} · 最大 ${point.max.toFixed(6)}`,
          `最后 ${point.last.toFixed(6)}`,
        ].join('<br/>')
      },
    },
    xAxis: { type: 'value', name: 'epoch', minInterval: 1 },
    yAxis: { type: 'value', name: 'loss', scale: true },
    series: [
      {
        name: 'epoch 平均 loss',
        type: 'line',
        smooth: true,
        showSymbol: data.length <= 80,
        data,
      },
    ],
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
        label="模型训练"
        :model-value="selectedModelId"
        :options="modelOptions"
        :loading="resourceLoading"
        placeholder="选择模型训练"
        delete-label="删除模型训练"
        :busy="busy"
        @update:model-value="$emit('update:selectedModelId', $event)"
        @visible-change="$emit('reloadModels', $event)"
        @search="$emit('searchModels', $event)"
        @add="$emit('train')"
        @delete="$emit('deleteModel', $event)"
      />
      <div v-if="!models.length && !pendingModelId" class="primary-empty-panel">
        <el-empty :image-size="120">
          <template #description>
            <div class="primary-empty-title">暂无模型训练资源</div>
          </template>
          <el-button type="primary" size="large" :disabled="busy" @click="$emit('train')">
            训练模型
          </el-button>
        </el-empty>
      </div>
      <el-alert
        v-if="pendingModelId"
        class="dialog-section"
        :title="`模型训练 ${pendingModelId} 正在训练，产物状态会随任务更新。`"
        type="info"
        show-icon
        :closable="false"
      />

      <el-card
        v-if="models.length || pendingModelId"
        v-loading="modelDetailLoading"
        element-loading-text="正在加载模型数据..."
        shadow="never"
      >
        <template #header>
          <div class="card-header">
            <el-space>
              <span>{{ selectedModelId ? `模型ID: ${selectedModelId}` : '模型ID' }}</span>
              <el-button :disabled="!selectedModelId || busy" type="warning" plain @click="handleRetrain">
                重新训练
              </el-button>
            </el-space>
            <el-button
              :icon="Refresh"
              :disabled="busy || !selectedModelId"
              :loading="modelDetailLoading"
              @click="refreshModelDetails"
            >
              刷新
            </el-button>
          </div>
        </template>

        <el-empty v-if="!selectedModelId" description="请选择或训练模型" />
        <el-result v-else-if="modelDetailError" icon="error" title="模型数据加载失败" :sub-title="modelDetailError">
          <template #extra>
            <el-button
              type="primary"
              :icon="Refresh"
              :loading="modelDetailLoading"
              :disabled="busy"
              @click="refreshModelDetails"
            >
              重试
            </el-button>
          </template>
        </el-result>
        <template v-else>
          <div class="model-overview">
            <div class="model-overview-main">
              <el-descriptions class="model-metadata" :column="1" border size="small">
                <el-descriptions-item label="训练样本数">
                  {{ selectedModel?.sample_count ?? 0 }}
                </el-descriptions-item>
                <el-descriptions-item label="日志">
                  <el-button
                    v-if="selectedTrainTask"
                    link
                    type="primary"
                    @click="$emit('openTaskLog', selectedTrainTask)"
                  >
                    查看任务 #{{ selectedTrainTask.id }}
                  </el-button>
                  <span v-else>暂无任务日志</span>
                </el-descriptions-item>
              </el-descriptions>
              <el-steps
                class="training-steps"
                :active="trainingStepActive"
                finish-status="success"
                :process-status="trainingStepProcessStatus"
              >
                <el-step title="全局图建模" />
                <el-step title="生成扰动图 / 辅助图" />
                <el-step title="GNN + 训练 VAE" />
              </el-steps>
              <el-scrollbar class="checkpoint-scroll" max-height="190px">
                <el-table :data="modelCheckpoints" empty-text="暂无可用 checkpoint" size="small">
                  <el-table-column label="类型" width="88">
                    <template #default="{ row }">
                      <el-tag :type="checkpointRoleType(row.role)" size="small">
                        {{ checkpointRoleLabel(row.role) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="name" label="模型检查点" show-overflow-tooltip />
                  <el-table-column label="大小" width="100">
                    <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="120">
                    <template #default="{ row }">
                      <el-button link type="primary" :disabled="busy" @click="$emit('generate', row)">
                        生成数据
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-scrollbar>
            </div>
            <div class="training-progress">
              <el-progress
                type="dashboard"
                :percentage="stageProgress.percentage"
                :status="trainProgressStatus"
                :width="132"
              />
              <span class="training-progress-label">{{ stageProgress.label }}</span>
              <span class="training-progress-detail">{{ stageProgress.detail }}</span>
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
                v-if="epochLossPoints.length"
                :option="lossChartOption"
                filename="training-loss"
                chart-class="loss-chart"
                height="220px"
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
                <el-scrollbar class="table-scroll" max-height="240px">
                  <el-table :data="modelPoolRows" empty-text="暂无节点池信息">
                    <el-table-column prop="id" label="ID" width="90" />
                    <el-table-column prop="size" label="节点数" />
                    <el-table-column prop="feature_dim" label="特征维度" />
                  </el-table>
                </el-scrollbar>
              </el-tab-pane>
              <el-tab-pane label="边类型">
                <el-scrollbar class="table-scroll" max-height="240px">
                  <el-table :data="modelEdgeRows" empty-text="暂无边类型信息">
                    <el-table-column prop="id" label="ID" width="90" />
                    <el-table-column prop="source_pool_id" label="源节点池" />
                    <el-table-column prop="target_pool_id" label="目标节点池" />
                    <el-table-column prop="feature_dim" label="特征维度" />
                  </el-table>
                </el-scrollbar>
              </el-tab-pane>
              <el-tab-pane label="预测任务">
                <el-scrollbar class="table-scroll" max-height="240px">
                  <el-table :data="modelTaskRows" empty-text="暂无任务信息">
                    <el-table-column prop="id" label="ID" width="90" />
                    <el-table-column prop="target_pool_id" label="目标节点池" />
                    <el-table-column prop="max_slots" label="最大槽位" />
                    <el-table-column prop="count_bounds" label="数量范围" />
                    <el-table-column prop="param_dim" label="参数维度" />
                  </el-table>
                </el-scrollbar>
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
.model-overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px;
  gap: 16px;
  align-items: stretch;
}

.model-overview-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
}

.model-metadata,
.checkpoint-scroll {
  min-width: 0;
}

.training-steps {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.training-progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 244px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.training-progress-label {
  font-weight: 600;
}

.training-progress-detail {
  color: var(--el-text-color-secondary);
  font-size: 13px;
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
  .model-overview {
    grid-template-columns: 1fr;
  }
}

</style>
