<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { api, ApiError } from '@/api/client'
import {
  isTaskFailed,
  isTaskTerminal,
  taskDisplayLabel,
  taskDisplayStatus,
  taskTagType,
} from '@/task-status'
import { formatTaskDuration, formatTaskTime } from '@/task-time'
import type { Task } from '@/types'

const RUNNING_LOG_POLL_MS = 1000

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
let pollHandle = 0

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const activeTask = computed(() => liveTask.value ?? props.task)
const command = computed(() => activeTask.value?.command || activeTask.value?.original_command || '-')
const activeTaskId = computed(() => activeTask.value?.id ?? props.task?.id ?? null)
const activeTaskRunning = computed(() => Boolean(activeTask.value) && !isTaskTerminal(activeTask.value as Task))

watch(
  () => [props.modelValue, props.task?.id] as const,
  ([isVisible, taskId]) => {
    stopLogPolling()
    liveTask.value = props.task
    if (!isVisible || taskId == null) {
      log.value = ''
      return
    }
    void refreshLog(taskId, { showLoading: true })
    startLogPolling(taskId)
  },
  { immediate: true },
)

onUnmounted(stopLogPolling)

async function refreshCurrentLog() {
  if (activeTaskId.value == null) return
  await refreshLog(activeTaskId.value, { showLoading: true })
}

async function refreshLog(taskId: number, options: { showLoading?: boolean } = {}) {
  now.value = Date.now()
  if (options.showLoading) {
    loading.value = true
    log.value = ''
  }
  try {
    const [nextLog, nextTask] = await Promise.all([api.getTaskLog(taskId, 400), readTask(taskId)])
    log.value = nextLog
    liveTask.value = nextTask ?? liveTask.value
    if (nextTask && isTaskTerminal(nextTask)) stopLogPolling()
    await nextTick()
    scrollLogToBottom()
  } catch (error) {
    notifyError(error)
  } finally {
    if (options.showLoading) loading.value = false
  }
}

async function readTask(taskId: number) {
  try {
    return await api.getTask(taskId)
  } catch {
    return null
  }
}

function startLogPolling(taskId: number) {
  if (!activeTaskRunning.value) return
  pollHandle = window.setInterval(() => {
    void refreshLog(taskId)
  }, RUNNING_LOG_POLL_MS)
}

function stopLogPolling() {
  if (!pollHandle) return
  window.clearInterval(pollHandle)
  pollHandle = 0
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
      <el-descriptions-item label="命令" :span="3">
        <pre class="task-command">{{ command }}</pre>
      </el-descriptions-item>
    </el-descriptions>

    <el-divider content-position="left">日志</el-divider>
    <div class="log-toolbar">
      <span class="log-refresh-note">
        {{ activeTaskRunning ? '运行中，自动每 1s 刷新' : '任务已结束，可手动刷新' }}
      </span>
      <el-button :loading="loading" @click="refreshCurrentLog">刷新</el-button>
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

.log-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: space-between;
  margin-bottom: 10px;
}

.log-refresh-note {
  color: var(--el-text-color-secondary);
  font-size: 13px;
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
