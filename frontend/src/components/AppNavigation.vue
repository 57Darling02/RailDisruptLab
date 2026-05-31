<script setup lang="ts">
import type { Component } from 'vue'

import {
  Blocks,
  BrainCircuit,
  ChartNoAxesCombined,
  Database,
  FlaskConical,
  FolderKanban,
  LayoutDashboard,
} from '@/icons'

defineProps<{
  activePage: string
}>()

defineEmits<{
  select: [page: string]
}>()

type NavigationItem = {
  index: string
  label: string
  icon: Component
}

const primaryItems: NavigationItem[] = [
  { index: 'dashboard', label: '仪表盘', icon: LayoutDashboard },
  { index: 'scenarios', label: '扰动场景', icon: FolderKanban },
  { index: 'datasets', label: 'MILP 实例', icon: Database },
  { index: 'models', label: '模型训练', icon: BrainCircuit },
]

const ablationItems: NavigationItem[] = [
  { index: 'ablation-scenarios', label: '场景分析', icon: FlaskConical },
  { index: 'ablation-datasets', label: 'MILP 分析', icon: ChartNoAxesCombined },
]
</script>

<template>
  <div class="app-navigation">
    <div class="brand">RailDisruptLab</div>
    <el-menu :default-active="activePage" @select="$emit('select', String($event))">
      <el-menu-item v-for="item in primaryItems" :key="item.index" :index="item.index">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </el-menu-item>
      <el-sub-menu index="ablation">
        <template #title>
          <el-icon><Blocks /></el-icon>
          <span>消融分析</span>
        </template>
        <el-menu-item v-for="item in ablationItems" :key="item.index" :index="item.index">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-sub-menu>
    </el-menu>
  </div>
</template>
