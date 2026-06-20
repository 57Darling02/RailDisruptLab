<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Component } from 'vue'

import {
  Blocks,
  Brain,
  ChartNoAxesCombined,
  ChartPie,
  Database,
  FlaskConical,
  FolderKanban,
  LayoutDashboard,
  PanelLeftClose,
  PanelLeftOpen,
} from '@/icons'

const props = defineProps<{
  activePage: string
  variant?: 'desktop' | 'drawer'
}>()

const emit = defineEmits<{
  select: [page: string]
  pinnedExpandedChange: [value: boolean]
}>()

type NavigationItem = {
  index: string
  label: string
  icon: Component
}

const primaryItems: NavigationItem[] = [
  { index: 'dashboard', label: '仪表盘', icon: LayoutDashboard },
]

const scenarioItems: NavigationItem[] = [
  { index: 'scenario-overview', label: '场景总览', icon: Blocks },
  { index: 'scenario-resources', label: '场景资源', icon: Database },
  { index: 'adjustment-plans', label: 'MILP 调整计划', icon: ChartNoAxesCombined },
]

const modelItems: NavigationItem[] = [
  { index: 'models', label: '模型', icon: Brain },
]

const ablationItems: NavigationItem[] = [
  { index: 'ablation-scenarios', label: '场景对照', icon: FlaskConical },
  { index: 'ablation-plans', label: '调整计划分析', icon: ChartNoAxesCombined },
]

const activeMenuIndex = computed(() =>
  props.activePage === 'scenario-detail' ? 'scenario-resources' : props.activePage,
)
const defaultOpenedMenus = ['scenarios']
const navigationRoot = ref<HTMLElement | null>(null)
const pinnedExpanded = ref(false)
const hoveringMenu = ref(false)
const introExpanded = ref(props.variant !== 'drawer')
const isDesktop = computed(() => props.variant !== 'drawer')
const isExpanded = computed(
  () => !isDesktop.value || pinnedExpanded.value || hoveringMenu.value || introExpanded.value,
)
const isCollapsed = computed(() => isDesktop.value && !isExpanded.value)
const pinButtonTooltip = computed(() => (pinnedExpanded.value ? '折叠侧边栏' : '展开侧边栏'))
const pinButtonIcon = computed(() => (pinnedExpanded.value ? PanelLeftClose : PanelLeftOpen))

function togglePinnedExpanded() {
  pinnedExpanded.value = !pinnedExpanded.value
  hoveringMenu.value = false
  introExpanded.value = false
  if (isDesktop.value) emit('pinnedExpandedChange', pinnedExpanded.value)
}

function enterNavigationMenu() {
  if (isDesktop.value && !pinnedExpanded.value) hoveringMenu.value = true
}

function leaveNavigationMenu() {
  hoveringMenu.value = false
}

function clearIntroExpanded(event: Event) {
  if (!introExpanded.value || !isDesktop.value) return
  const target = event.target
  if (target instanceof Node && navigationRoot.value?.contains(target)) return
  introExpanded.value = false
}

function selectMenuItem(page: string) {
  if (isDesktop.value && !pinnedExpanded.value) {
    introExpanded.value = false
  }
  emit('select', page)
}

onMounted(() => {
  if (!isDesktop.value) return
  document.addEventListener('pointerdown', clearIntroExpanded, true)
  document.addEventListener('focusin', clearIntroExpanded, true)
})

onBeforeUnmount(() => {
  if (!isDesktop.value) return
  document.removeEventListener('pointerdown', clearIntroExpanded, true)
  document.removeEventListener('focusin', clearIntroExpanded, true)
})
</script>

<template>
  <div
    ref="navigationRoot"
    class="app-navigation"
    :class="{
      'is-desktop-navigation': isDesktop,
      'is-drawer-navigation': !isDesktop,
      'is-collapsed': isCollapsed,
      'is-expanded': !isCollapsed,
      'is-pinned-expanded': pinnedExpanded,
    }"
  >
    <div class="navigation-hover-zone" @mouseenter="enterNavigationMenu" @mouseleave="leaveNavigationMenu">
      <div class="brand">
        <span class="brand-full">RailDisruptLab</span>
        <span class="brand-short">RDL</span>
      </div>
      <div class="navigation-main">
        <el-menu
          :collapse="false"
          :default-active="activeMenuIndex"
          :default-openeds="defaultOpenedMenus"
          @select="selectMenuItem(String($event))"
        >
          <el-menu-item v-for="item in primaryItems" :key="item.index" :index="item.index">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
          <el-sub-menu index="scenarios">
            <template #title>
              <el-icon><FolderKanban /></el-icon>
              <span>场景</span>
            </template>
            <el-menu-item v-for="item in scenarioItems" :key="item.index" :index="item.index">
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-for="item in modelItems" :key="item.index" :index="item.index">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
          <el-sub-menu index="ablation">
            <template #title>
              <el-icon><ChartPie /></el-icon>
              <span>消融分析</span>
            </template>
            <el-menu-item v-for="item in ablationItems" :key="item.index" :index="item.index">
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </div>
    </div>

    <div v-if="isDesktop" class="navigation-footer">
      <el-tooltip :content="pinButtonTooltip" placement="right">
        <button
          class="navigation-pin-button"
          type="button"
          :aria-label="pinButtonTooltip"
          @click="togglePinnedExpanded"
        >
          <el-icon><component :is="pinButtonIcon" /></el-icon>
        </button>
      </el-tooltip>
    </div>
  </div>
</template>

<style scoped>
.app-navigation {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
}

.app-navigation.is-desktop-navigation {
  width: var(--app-nav-expanded-width);
  transition: width 180ms ease;
}

.app-navigation.is-drawer-navigation {
  width: 100%;
}

.app-navigation.is-desktop-navigation.is-collapsed {
  width: var(--app-nav-collapsed-width);
}

.app-navigation.is-desktop-navigation:not(.is-pinned-expanded).is-expanded {
  box-shadow: 8px 0 18px rgb(0 0 0 / 8%);
}

.app-navigation.is-desktop-navigation :deep(.el-menu-item span),
.app-navigation.is-desktop-navigation :deep(.el-sub-menu__title span),
.app-navigation.is-desktop-navigation :deep(.el-sub-menu__icon-arrow),
.app-navigation.is-desktop-navigation .brand-full {
  overflow: hidden;
  max-width: 160px;
  transform: translateX(0);
  opacity: 1;
  transition:
    opacity 140ms ease,
    transform 180ms ease,
    max-width 180ms ease;
}

.app-navigation.is-desktop-navigation.is-collapsed :deep(.el-menu-item span),
.app-navigation.is-desktop-navigation.is-collapsed :deep(.el-sub-menu__title span),
.app-navigation.is-desktop-navigation.is-collapsed :deep(.el-sub-menu__icon-arrow),
.app-navigation.is-desktop-navigation.is-collapsed .brand-full {
  max-width: 0;
  transform: translateX(-6px);
  opacity: 0;
  pointer-events: none;
}

.brand {
  width: 100%;
  box-sizing: border-box;
  white-space: nowrap;
}

.brand-short {
  display: none;
}

.app-navigation.is-desktop-navigation.is-collapsed .brand {
  justify-content: center;
  padding: 0;
}

.app-navigation.is-desktop-navigation.is-collapsed .brand-short {
  display: inline;
}

.navigation-hover-zone {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  flex-direction: column;
}

.navigation-main {
  flex: 1 1 auto;
  min-height: 0;
}

.navigation-main :deep(.el-menu) {
  height: 100%;
  border-right: 0;
}

.app-navigation.is-desktop-navigation.is-collapsed :deep(.el-menu-item),
.app-navigation.is-desktop-navigation.is-collapsed :deep(.el-sub-menu__title) {
  padding: 0 20px;
}

.navigation-footer {
  flex: 0 0 auto;
  padding: 8px;
  border-top: 1px solid var(--el-border-color-light);
}

.navigation-pin-button {
  display: flex;
  width: 100%;
  height: 40px;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 8px;
  color: var(--el-text-color-regular);
  background: transparent;
  cursor: pointer;
  font: inherit;
}

.navigation-pin-button:hover {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
}

.navigation-pin-button .el-icon {
  flex: 0 0 auto;
}
</style>
