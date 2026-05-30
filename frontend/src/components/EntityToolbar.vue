<script lang="ts">
export interface EntityOption {
  label: string
  value: string
  deletableLabel?: string
}
</script>

<script setup lang="ts">
import { Close } from '@element-plus/icons-vue'

const props = withDefaults(
  defineProps<{
    label: string
    modelValue: string
    options: EntityOption[]
    placeholder?: string
    addLabel?: string
    deleteLabel?: string
    filterable?: boolean
    loading?: boolean
    busy?: boolean
  }>(),
  {
    placeholder: '请选择',
    addLabel: '新增',
    deleteLabel: '删除',
    filterable: true,
    loading: false,
    busy: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  visibleChange: [visible: boolean]
  search: [query: string]
  add: []
  delete: [value: string]
}>()

function handleRemoteSearch(query: string) {
  emit('search', query)
}

function handleVisibleChange(visible: boolean) {
  emit('visibleChange', visible)
}
</script>

<template>
  <el-card shadow="never">
    <el-row :gutter="12" align="middle">
      <el-col :span="20">
        <el-space alignment="center" class="entity-toolbar-main">
          <span class="control-label">{{ label }}：</span>
          <el-select
            :model-value="modelValue"
            :filterable="filterable"
            :remote="filterable"
            reserve-keyword
            :remote-method="handleRemoteSearch"
            class="entity-toolbar-select"
            :placeholder="placeholder"
            :disabled="busy"
            :loading="loading || busy"
            no-match-text="无匹配资源"
            no-data-text="暂无资源"
            @update:model-value="emit('update:modelValue', String($event))"
            @visible-change="handleVisibleChange"
          >
            <el-option
              v-for="item in props.options"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            >
              <el-space alignment="center" class="entity-option-row">
                <el-text truncated>{{ item.label }}</el-text>
                <el-button
                  class="entity-option-delete"
                  link
                  type="danger"
                  :disabled="busy"
                  :aria-label="deleteLabel"
                  :title="deleteLabel"
                  @click.stop.prevent="emit('delete', item.value)"
                >
                  <el-icon><Close /></el-icon>
                </el-button>
              </el-space>
            </el-option>
          </el-select>
        </el-space>
      </el-col>
      <el-col :span="4">
        <el-button class="full-width" :disabled="busy" @click="emit('add')">{{ addLabel }}</el-button>
      </el-col>
    </el-row>
  </el-card>
</template>

<style scoped>
.entity-toolbar-main {
  width: 100%;
}

.entity-toolbar-main :deep(.el-space__item:last-child) {
  flex: 1;
  min-width: 0;
}

.entity-toolbar-select {
  width: 100%;
}

.entity-option-row {
  width: 100%;
}

.entity-option-row :deep(.el-space__item:first-child) {
  flex: 1;
  min-width: 0;
}

.entity-option-delete {
  min-height: 24px;
  padding: 0 4px;
  font-size: 14px;
}
</style>
