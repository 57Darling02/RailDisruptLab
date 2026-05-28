<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'

import type {
  MetadataEntry,
  SchemaEdgeRow,
  SchemaPoolRow,
  SchemaTaskRow,
} from '@/views/types'
import type { ModelCheckpoint, ModelDetail, ModelLossPoint, ModelSummary, Task } from '@/types'
import { taskOutcome } from '@/task-status'
import type { TaskTagType } from '@/task-status'

const props = defineProps<{
  selectedModelId: string
  pendingModelId: string
  selectedModel: ModelSummary | null
  models: ModelSummary[]
  modelDetail: ModelDetail | null
  modelSummaryEntries: MetadataEntry[]
  modelConfigEntries: MetadataEntry[]
  modelSchemaSummaryEntries: MetadataEntry[]
  modelPoolRows: SchemaPoolRow[]
  modelEdgeRows: SchemaEdgeRow[]
  modelTaskRows: SchemaTaskRow[]
  modelCheckpoints: ModelCheckpoint[]
  hasTrainingSummary: boolean
  hasTrainingConfig: boolean
  hasSchemaSummary: boolean
  tasks: Task[]
  formatBytes: (size: number) => string
  checkpointRoleLabel: (role: string) => string
  checkpointRoleType: (role: string) => TaskTagType
}>()

defineEmits<{
  'update:selectedModelId': [value: string]
  reloadModels: [visible: boolean]
  train: []
  retrain: []
  refreshModel: []
  openTaskLog: [task: Task]
  generate: [checkpoint: ModelCheckpoint]
}>()

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

const lossPoints = computed(() => props.modelDetail?.loss_points || [])
const epochLossPoints = computed(() => epochLossSeries(lossPoints.value))
const lossChartOption = computed(() => buildLossChartOption(epochLossPoints.value))
const latestLoss = computed(() => lossPoints.value.at(-1))
const latestEpochLoss = computed(() => epochLossPoints.value.at(-1))
const selectedTrainTask = computed(() => findModelTrainTask(props.tasks, props.selectedModelId))
const trainProgress = computed(() => modelTrainingProgress())
const graphProgress = computed(() => props.modelDetail?.graph_progress ?? {})
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

function modelTrainingProgress() {
  if (props.selectedModel?.is_ready) return 100
  const latest = latestLoss.value
  const epochs = numberFromConfig(props.modelDetail?.config?.epochs)
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
      .find((task) => pattern.test(task.command || task.original_command || '')) ?? null
  )
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-card shadow="never">
        <div class="toolbar-row">
          <div class="inline-control">
            <span>模型：</span>
            <el-select
              :model-value="selectedModelId"
              placeholder="选择模型"
              class="toolbar-select"
              @update:model-value="$emit('update:selectedModelId', $event)"
              @visible-change="$emit('reloadModels', $event)"
            >
              <el-option
                v-for="item in models"
                :key="item.model_id"
                :label="item.model_id"
                :value="item.model_id"
              />
            </el-select>
          </div>
          <el-button type="primary" @click="$emit('train')">训练新模型</el-button>
        </div>
        <el-alert
          v-if="pendingModelId"
          class="dialog-section"
          :title="`模型 ${pendingModelId} 正在训练，产物状态会随任务更新。`"
          type="info"
          show-icon
          :closable="false"
        />
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <el-space>
              <span>{{ selectedModelId ? `模型ID: ${selectedModelId}` : '模型ID' }}</span>
              <el-button :disabled="!selectedModelId" type="warning" plain @click="$emit('retrain')">
                重新训练
              </el-button>
            </el-space>
            <el-button @click="$emit('refreshModel')">刷新</el-button>
          </div>
        </template>

        <el-empty v-if="!selectedModelId" description="请选择或训练模型" />
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
                      <el-button link type="primary" @click="$emit('generate', row)">
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
              <VChart v-if="epochLossPoints.length" :option="lossChartOption" autoresize class="loss-chart" />
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

.loss-chart {
  display: block;
  width: 100%;
  height: 220px;
}

@media (max-width: 760px) {
  .model-overview {
    grid-template-columns: 1fr;
  }
}

</style>
