<script setup lang="ts">
import { InfoFilled } from '@element-plus/icons-vue'

defineProps<{
  label: string
  tip: string
}>()
</script>

<template>
  <span class="field-label">
    <span>{{ label }}</span>
    <el-tooltip :content="tip" placement="top" effect="light">
      <el-icon class="field-label-icon"><InfoFilled /></el-icon>
    </el-tooltip>
  </span>
</template>

<style scoped>
.field-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.field-label-icon {
  color: var(--el-text-color-secondary);
  cursor: help;
}
</style>
