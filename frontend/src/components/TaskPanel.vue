<script setup lang="ts">
import { computed, ref } from 'vue'

import TaskLogDialog from '@/components/TaskLogDialog.vue'
import {
  isTaskCancellable,
  isTaskFailed,
  taskDisplayLabel,
  taskDisplayStatus,
  taskTagType,
} from '@/task-status'
import type { Task } from '@/types'

const ALL_TASKS = '__all__'

const props = withDefaults(
  defineProps<{
    title: string
    tasks: Task[]
    emptyText?: string
  }>(),
  {
    emptyText: '暂无任务',
  },
)

const emit = defineEmits<{
  refresh: []
  cancel: [task: Task]
}>()

const logDialogVisible = ref(false)
const selectedTask = ref<Task | null>(null)
const selectedCategory = ref(ALL_TASKS)

const categoryOptions = computed(() => {
  const labels = new Set(props.tasks.map((task) => taskCategory(task)))
  return [
    { label: props.title, value: ALL_TASKS },
    ...[...labels].sort().map((label) => ({ label, value: label })),
  ]
})
const activeCategory = computed(() =>
  categoryOptions.value.some((option) => option.value === selectedCategory.value)
    ? selectedCategory.value
    : ALL_TASKS,
)
const displayTasks = computed(() =>
  props.tasks
    .filter(
      (task) => activeCategory.value === ALL_TASKS || taskCategory(task) === activeCategory.value,
    )
    .slice()
    .reverse(),
)

function openLog(task: Task) {
  selectedTask.value = task
  logDialogVisible.value = true
}

function taskCategory(task: Task) {
  return taskDisplayLabel(task)
}
</script>

<template>
  <el-card class="task-panel" shadow="never">
    <template #header>
      <div class="task-panel-header">
        <el-select v-model="selectedCategory" size="small" class="task-filter-select">
          <el-option
            v-for="option in categoryOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button link type="primary" @click="emit('refresh')">刷新</el-button>
      </div>
    </template>

    <el-scrollbar class="task-scroll" height="100%">
      <el-empty v-if="!displayTasks.length" :description="emptyText" :image-size="72" />
      <div v-else class="task-list">
        <article v-for="task in displayTasks" :key="task.id" class="task-item">
          <div class="task-item-main">
            <div class="task-title">
              <span>#{{ task.id }}</span>
              <span>{{ taskDisplayLabel(task) }}</span>
            </div>
            <el-tag
              size="small"
              :type="taskTagType(task)"
              :class="{ 'task-status-failed': isTaskFailed(task) }"
            >
              {{ taskDisplayStatus(task) }}
            </el-tag>
          </div>
          <div class="task-meta">{{ task.group || '-' }}</div>
          <div class="task-actions">
            <el-button link type="primary" @click="openLog(task)">日志</el-button>
            <el-button
              v-if="isTaskCancellable(task)"
              link
              type="danger"
              @click="emit('cancel', task)"
            >
              中断
            </el-button>
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
  height: calc(100% - 58px);
  padding: 0;
}

.task-panel-header,
.task-item-main,
.task-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.task-filter-select {
  width: 180px;
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

.task-title span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-meta {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.task-actions {
  margin-top: 6px;
  justify-content: flex-end;
}

.task-status-failed {
  border-color: #ff1f1f;
  color: #fff;
  font-weight: 700;
  background: #e60012;
  box-shadow: 0 0 0 1px rgb(230 0 18 / 18%);
}
</style>
