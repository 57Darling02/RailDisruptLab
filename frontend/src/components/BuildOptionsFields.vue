<script setup lang="ts">
import type { DatasetBuildForm } from '@/views/types'

const props = defineProps<{
  modelValue: DatasetBuildForm
}>()

const emit = defineEmits<{
  'update:modelValue': [value: DatasetBuildForm]
}>()

function patch<K extends keyof DatasetBuildForm>(key: K, value: DatasetBuildForm[K]) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <el-form-item label="目标权重">
    <el-input-number
      :model-value="modelValue.objective_delay_weight"
      :min="0.000001"
      :step="0.1"
      @update:model-value="patch('objective_delay_weight', Number($event))"
    />
  </el-form-item>
  <el-form-item label="目标模式">
    <el-select
      :model-value="modelValue.objective_mode"
      class="full-width"
      @update:model-value="patch('objective_mode', String($event))"
    >
      <el-option label="绝对延误 abs" value="abs" />
      <el-option label="累计延误 delay" value="delay" />
    </el-select>
  </el-form-item>
  <el-form-item label="允许取消">
    <el-switch
      :model-value="modelValue.cancellation_enabled"
      @update:model-value="patch('cancellation_enabled', Boolean($event))"
    />
  </el-form-item>
  <el-form-item label="取消惩罚权重">
    <el-input-number
      :model-value="modelValue.cancellation_penalty_weight"
      :min="0"
      :step="100"
      @update:model-value="patch('cancellation_penalty_weight', Number($event))"
    />
  </el-form-item>
  <el-form-item label="到到间隔秒数">
    <el-input-number
      :model-value="modelValue.arr_arr_headway_seconds"
      :min="1"
      @update:model-value="patch('arr_arr_headway_seconds', Number($event))"
    />
  </el-form-item>
  <el-form-item label="发发间隔秒数">
    <el-input-number
      :model-value="modelValue.dep_dep_headway_seconds"
      :min="1"
      @update:model-value="patch('dep_dep_headway_seconds', Number($event))"
    />
  </el-form-item>
  <el-form-item label="停站秒数">
    <el-input-number
      :model-value="modelValue.dwell_seconds_at_stops"
      :min="1"
      @update:model-value="patch('dwell_seconds_at_stops', Number($event))"
    />
  </el-form-item>
  <el-form-item label="Big-M">
    <el-input-number
      :model-value="modelValue.big_m"
      :min="1"
      :step="1000"
      @update:model-value="patch('big_m', Number($event))"
    />
  </el-form-item>
  <el-form-item label="延误容忍秒数">
    <el-input-number
      :model-value="modelValue.tolerance_delay_seconds"
      :min="1"
      @update:model-value="patch('tolerance_delay_seconds', Number($event))"
    />
  </el-form-item>
</template>
