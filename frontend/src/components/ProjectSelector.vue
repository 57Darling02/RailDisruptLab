<script setup lang="ts">
import { ElMessageBox } from 'element-plus'

import { Close, Plus } from '@/icons'
import type { ResourceOption } from '@/types'

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: ResourceOption[]
    loading?: boolean
    busy?: boolean
  }>(),
  {
    loading: false,
    busy: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  visibleChange: [visible: boolean]
  search: [query: string]
  create: [projectId: string]
  delete: [projectId: string]
}>()

function handleCreate() {
  void ElMessageBox.prompt('项目 ID', '新建项目', {
    confirmButtonText: '创建',
    cancelButtonText: '取消',
    inputPattern: /\S+/,
    inputErrorMessage: '请输入项目 ID',
  }).then(({ value }) => {
    const projectId = String(value || '').trim()
    if (projectId) emit('create', projectId)
  })
}

function handleDelete(projectId: string) {
  if (!projectId) return
  void ElMessageBox.confirm(`确认移除项目 ${projectId}？`, '移除项目', {
    type: 'warning',
    confirmButtonText: '移除',
    cancelButtonText: '取消',
  }).then(() => {
    emit('delete', projectId)
  })
}
</script>

<template>
  <div class="project-selector">
    <span class="control-label">项目</span>
    <el-select
      :model-value="modelValue"
      placeholder="选择项目"
      filterable
      remote
      reserve-keyword
      class="project-select"
      :disabled="busy"
      :loading="loading || busy"
      :remote-method="(query: string) => emit('search', query)"
      no-match-text="无匹配项目"
      no-data-text="暂无项目"
      @update:model-value="emit('update:modelValue', String($event))"
      @visible-change="emit('visibleChange', $event)"
    >
      <el-option
        v-for="item in props.options"
        :key="item.value"
        :label="item.label"
        :value="item.value"
      >
        <el-space alignment="center" class="project-option-row">
          <el-text truncated>{{ item.label }}</el-text>
          <el-button
            class="project-option-delete"
            link
            type="danger"
            :disabled="busy"
            aria-label="移除项目"
            title="移除项目"
            @click.stop.prevent="handleDelete(item.value)"
          >
            <el-icon><Close /></el-icon>
          </el-button>
        </el-space>
      </el-option>
      <template #footer>
        <el-button
          class="project-create-button"
          type="primary"
          plain
          :icon="Plus"
          :disabled="busy"
          @click.stop="handleCreate"
        >
          新建项目
        </el-button>
      </template>
    </el-select>
  </div>
</template>

<style scoped>
.project-selector {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 8px;
}

.project-option-row {
  width: 100%;
}

.project-option-row :deep(.el-space__item:first-child) {
  flex: 1;
  min-width: 0;
}

.project-option-delete {
  min-height: 24px;
  padding: 0 4px;
  font-size: 14px;
}

.project-create-button {
  width: 100%;
}
</style>
