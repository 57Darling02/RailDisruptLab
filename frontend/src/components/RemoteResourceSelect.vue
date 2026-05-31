<script setup lang="ts">
import type { ResourceOption } from '@/types'

const props = withDefaults(
  defineProps<{
    modelValue: string | string[]
    options: ResourceOption[]
    placeholder?: string
    multiple?: boolean
    loading?: boolean
    disabled?: boolean
    collapseTags?: boolean
  }>(),
  {
    placeholder: '请选择',
    multiple: false,
    loading: false,
    disabled: false,
    collapseTags: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string | string[]]
  visibleChange: [visible: boolean]
  search: [query: string]
  change: [value: string | string[]]
}>()

function handleUpdate(value: string | string[]) {
  emit('update:modelValue', value)
}

function handleChange(value: string | string[]) {
  emit('change', value)
}
</script>

<template>
  <el-select
    :model-value="modelValue"
    filterable
    remote
    reserve-keyword
    class="full-width"
    :multiple="multiple"
    :collapse-tags="collapseTags"
    :collapse-tags-tooltip="collapseTags"
    :placeholder="placeholder"
    :disabled="disabled"
    :loading="loading"
    :remote-method="(query: string) => emit('search', query)"
    no-match-text="无匹配资源"
    no-data-text="暂无资源"
    @update:model-value="handleUpdate"
    @change="handleChange"
    @visible-change="emit('visibleChange', $event)"
  >
    <el-option
      v-for="item in props.options"
      :key="item.value"
      :label="item.label"
      :value="item.value"
    />
  </el-select>
</template>
