<script setup lang="ts">
import { Delete, Document, Refresh, VideoPause } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import TaskLogDialog from '@/components/TaskLogDialog.vue'
import {
  isTaskCancellable,
  isTaskFailed,
  isTaskTerminal,
  taskDisplayLabel,
  taskDisplayStatus,
  taskTagType,
} from '@/task-status'
import { formatTaskDuration, formatTaskTime, taskSortTime } from '@/task-time'
import type { Task } from '@/types'

type TaskOption = { label: string; value: string }

const props = withDefaults(
  defineProps<{
    tasks: Task[]
    projectOptions: TaskOption[]
    initialProjectId?: string
    emptyText?: string
    now?: number
    busy?: boolean
  }>(),
  {
    initialProjectId: '',
    emptyText: '暂无任务',
    now: () => Date.now(),
    busy: false,
  },
)

const emit = defineEmits<{
  refresh: []
  cancel: [task: Task]
  remove: [task: Task]
}>()

const logDialogVisible = ref(false)
const selectedTask = ref<Task | null>(null)
const selectedProjectId = ref(props.initialProjectId)
const selectedTaskType = ref('')

const taskTypeOptions = computed(() => {
  const seen = new Set<string>()
  const options: TaskOption[] = [{ label: '全部类型', value: '' }]
  for (const task of props.tasks) {
    const value = taskTypeValue(task)
    if (!value || seen.has(value)) continue
    seen.add(value)
    options.push({ label: taskDisplayLabel(value), value })
  }
  return options
})

const displayTasks = computed(() =>
  props.tasks
    .filter((task) => matchesProject(task) && matchesTaskType(task))
    .slice()
    .sort(compareTasks),
)

watch(
  () => props.initialProjectId,
  (projectId) => {
    selectedProjectId.value = projectId
  },
)

function matchesProject(task: Task) {
  return !selectedProjectId.value || task.group === selectedProjectId.value
}

function matchesTaskType(task: Task) {
  return !selectedTaskType.value || taskTypeValue(task) === selectedTaskType.value
}

function taskTypeValue(task: Task) {
  return String(task.label || task.action || '').trim()
}

function openLog(task: Task) {
  selectedTask.value = task
  logDialogVisible.value = true
}

function compareTasks(left: Task, right: Task) {
  const leftRunning = !isTaskTerminal(left)
  const rightRunning = !isTaskTerminal(right)
  if (leftRunning !== rightRunning) return leftRunning ? -1 : 1

  const timeDelta = taskSortTime(right) - taskSortTime(left)
  if (timeDelta !== 0) return timeDelta

  return right.id - left.id
}
</script>

<template>
  <el-card class="task-panel" shadow="never">
    <template #header>
      <div class="task-panel-header">
        <div class="task-panel-title">任务管理器</div>
        <div class="task-header-actions">
          <el-button link type="primary" :icon="Refresh" :disabled="busy" @click="emit('refresh')">刷新</el-button>
        </div>
      </div>
    </template>

    <div class="task-filters">
      <label class="task-filter">
        <span>项目</span>
        <el-select v-model="selectedProjectId" class="task-filter-select">
          <el-option
            v-for="option in projectOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </label>
      <label class="task-filter">
        <span>任务类型</span>
        <el-select v-model="selectedTaskType" class="task-filter-select">
          <el-option
            v-for="option in taskTypeOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </label>
    </div>

    <el-scrollbar class="task-scroll" height="100%">
      <el-empty v-if="!displayTasks.length" :description="emptyText" :image-size="72" />
      <div v-else class="task-list">
        <article v-for="task in displayTasks" :key="task.id" class="task-item">
          <div class="task-item-main">
            <div class="task-title">
              <span>#{{ task.id }}</span>
              <el-text truncated>{{ taskDisplayLabel(task) }}</el-text>
            </div>
            <el-tag
              size="small"
              :type="taskTagType(task)"
              :class="{ 'task-status-failed': isTaskFailed(task) }"
            >
              {{ taskDisplayStatus(task) }}
            </el-tag>
          </div>
          <div class="task-meta">
            <div class="task-meta-row">
              <span>项目：{{ task.group || '-' }}</span>
              <span v-if="task.started_at || task.finished_at">耗时：{{ formatTaskDuration(task, now) }}</span>
            </div>
            <span>提交：{{ formatTaskTime(task.created_at) }}</span>
            <span v-if="task.started_at">开始：{{ formatTaskTime(task.started_at) }}</span>
            <span v-if="task.finished_at">结束：{{ formatTaskTime(task.finished_at) }}</span>
          </div>
          <div class="task-footer">
            <span class="task-action-label">操作</span>
            <div class="task-action-buttons">
              <el-button size="small" :icon="Document" @click="openLog(task)">日志</el-button>
              <el-button
                v-if="isTaskCancellable(task)"
                plain
                size="small"
                type="danger"
                :icon="VideoPause"
                :disabled="busy"
                @click="emit('cancel', task)"
              >
                中断任务
              </el-button>
              <el-popconfirm
                v-else
                title="清除这条历史任务记录？"
                confirm-button-text="清除"
                cancel-button-text="取消"
                @confirm="emit('remove', task)"
              >
                <template #reference>
                  <el-button plain size="small" type="danger" :icon="Delete" :disabled="busy">
                    清除记录
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
        </article>
      </div>
    </el-scrollbar>
  </el-card>

  <TaskLogDialog v-model="logDialogVisible" :task="selectedTask" />
</template>

<style scoped>
.task-panel {
  height: 100%;
  min-height: 420px;
}

.task-panel :deep(.el-card__body) {
  display: flex;
  height: calc(100% - 58px);
  flex-direction: column;
  padding: 0;
}

.task-panel-header,
.task-item-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.task-panel-title {
  font-size: 16px;
  font-weight: 700;
}

.task-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.task-filters {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.task-filter {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 700;
}

.task-filter-select {
  width: 100%;
}

.task-scroll {
  flex: 1;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
}

.task-item {
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
}

.task-title {
  display: flex;
  min-width: 0;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}

.task-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.task-meta-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.task-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 10px -10px -10px;
  padding: 8px 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  border-radius: 0 0 6px 6px;
  background: var(--el-fill-color-extra-light);
}

.task-action-label {
  flex: 0 0 auto;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 600;
}

.task-action-buttons {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.task-action-buttons :deep(.el-button) {
  margin-left: 0;
}

.task-status-failed {
  border-color: #ff1f1f;
  color: #fff;
  font-weight: 700;
  background: #e60012;
  box-shadow: 0 0 0 1px rgb(230 0 18 / 18%);
}
</style>
