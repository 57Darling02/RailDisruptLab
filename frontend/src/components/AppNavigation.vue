<script setup lang="ts">
defineProps<{
  activePage: string
}>()

defineEmits<{
  select: [page: string]
}>()
</script>

<template>
  <div class="app-navigation">
    <div class="brand">RailDisruptLab</div>
    <el-menu :default-active="activePage" @select="$emit('select', String($event))">
      <el-menu-item index="dashboard">仪表盘</el-menu-item>
      <el-menu-item index="scenarios">扰动场景</el-menu-item>
      <el-menu-item index="datasets">MILP 实例</el-menu-item>
      <el-menu-item index="models">模型训练</el-menu-item>
      <el-sub-menu index="ablation">
        <template #title>消融分析</template>
        <el-menu-item index="ablation-scenarios">场景分析</el-menu-item>
        <el-menu-item index="ablation-datasets">MILP 分析</el-menu-item>
      </el-sub-menu>
    </el-menu>
  </div>
</template>
