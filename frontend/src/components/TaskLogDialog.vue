<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api, ApiError } from '@/api/client'
import {
  isTaskFailed,
  taskDisplayLabel,
  taskDisplayStatus,
  taskTagType,
} from '@/task-status'
import { formatTaskDuration, formatTaskTime } from '@/task-time'
import { Refresh } from '@/icons'
import type { Task } from '@/types'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    task: Task | null
    title?: string
  }>(),
  {
    title: '任务日志',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const loading = ref(false)
const log = ref('')
const liveTask = ref<Task | null>(null)
const logView = ref<HTMLElement | null>(null)
const now = ref(Date.now())
let logRequestSeq = 0

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const activeTask = computed(() => liveTask.value ?? props.task)
const paramEntries = computed(() => Object.entries(activeTask.value?.params ?? {}))
const command = computed(() => activeTask.value?.command || activeTask.value?.original_command || '-')
const activeTaskId = computed(() => activeTask.value?.id ?? props.task?.id ?? null)

watch(
  () => [props.modelValue, props.task?.id] as const,
  ([isVisible, taskId]) => {
    logRequestSeq += 1
    liveTask.value = props.task
    log.value = ''
    if (!isVisible || taskId == null) {
      return
    }
    void refreshLog(taskId, { showLoading: true })
  },
  { immediate: true },
)

async function refreshCurrentLog() {
  if (activeTaskId.value == null) return
  await refreshLog(activeTaskId.value, { showLoading: true })
}

async function refreshLog(taskId: number, options: { showLoading?: boolean } = {}) {
  const requestSeq = logRequestSeq + 1
  logRequestSeq = requestSeq
  now.value = Date.now()
  if (options.showLoading) {
    loading.value = true
  }
  try {
    const [nextLog, nextTask] = await Promise.all([api.getTaskLog(taskId), readTask(taskId)])
    if (requestSeq !== logRequestSeq || taskId !== activeTaskId.value) return
    log.value = nextLog
    liveTask.value = nextTask ?? liveTask.value
    await nextTick()
    if (requestSeq === logRequestSeq) scrollLogToBottom()
  } catch (error) {
    if (requestSeq === logRequestSeq) notifyError(error)
  } finally {
    if (options.showLoading && requestSeq === logRequestSeq) loading.value = false
  }
}

async function readTask(taskId: number) {
  try {
    return await api.getTask(taskId)
  } catch {
    return null
  }
}

function scrollLogToBottom() {
  if (!logView.value) return
  logView.value.scrollTop = logView.value.scrollHeight
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

function formatParamValue(value: unknown) {
  if (value == null || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>

<template>
  <el-dialog v-model="visible" :title="title" width="860px" destroy-on-close>
    <el-descriptions v-if="activeTask" :column="3" border size="small">
      <el-descriptions-item label="任务">
        #{{ activeTask.id }} {{ taskDisplayLabel(activeTask) }}
      </el-descriptions-item>
      <el-descriptions-item label="项目">
        {{ activeTask.group || '-' }}
      </el-descriptions-item>
      <el-descriptions-item label="状态">
        <el-tag
          size="small"
          :type="taskTagType(activeTask)"
          :class="{ 'task-status-failed': isTaskFailed(activeTask) }"
        >
          {{ taskDisplayStatus(activeTask) }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="提交时间">
        {{ formatTaskTime(activeTask.created_at) }}
      </el-descriptions-item>
      <el-descriptions-item label="开始时间">
        {{ formatTaskTime(activeTask.started_at) }}
      </el-descriptions-item>
      <el-descriptions-item label="结束时间">
        {{ formatTaskTime(activeTask.finished_at) }}
      </el-descriptions-item>
      <el-descriptions-item label="耗时">
        {{ formatTaskDuration(activeTask, now) }}
      </el-descriptions-item>
      <el-descriptions-item label="动作">
        {{ activeTask.action || activeTask.label || '-' }}
      </el-descriptions-item>
      <el-descriptions-item
        v-for="[key, value] in paramEntries"
        :key="key"
        :label="key"
      >
        <el-text truncated>{{ formatParamValue(value) }}</el-text>
      </el-descriptions-item>
    </el-descriptions>

    <el-collapse class="task-debug-collapse">
      <el-collapse-item title="调试信息" name="debug">
        <pre class="task-command">{{ command }}</pre>
      </el-collapse-item>
    </el-collapse>

    <el-divider content-position="left">日志</el-divider>
    <div class="log-toolbar">
      <el-button
        :icon="Refresh"
        :loading-icon="Refresh"
        :loading="loading"
        @click="refreshCurrentLog"
      >
        刷新
      </el-button>
    </div>
    <pre ref="logView" v-loading="loading" class="task-log-view">{{ log || '暂无日志输出' }}</pre>
  </el-dialog>
</template>

<style scoped>
.task-command,
.task-log-view {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
}

.task-command {
  max-height: 96px;
  overflow: auto;
  color: var(--el-text-color-regular);
}

.task-debug-collapse {
  margin-top: 10px;
}

.log-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  margin-bottom: 10px;
}

.task-log-view {
  box-sizing: border-box;
  height: clamp(260px, 42vh, 420px);
  overflow: auto;
  padding: 12px;
  border-radius: 4px;
  color: var(--el-text-color-primary);
  background: var(--el-fill-color-light);
}

.task-status-failed {
  border-color: #ff1f1f;
  color: #fff;
  font-weight: 700;
  background: #e60012;
  box-shadow: 0 0 0 1px rgb(230 0 18 / 18%);
}
</style>
