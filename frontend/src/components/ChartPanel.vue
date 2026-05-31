<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import VChart from 'vue-echarts'

import { Download, FullScreen } from '@/icons'
const props = withDefaults(
  defineProps<{
    option: EChartsCoreOption
    filename?: string
    chartClass?: string
    fullscreenClass?: string
    height?: string
    fullscreenHeight?: string
  }>(),
  {
    filename: 'rail-disrupt-chart',
    chartClass: '',
    fullscreenClass: '',
    height: '320px',
    fullscreenHeight: 'calc(100vh - 96px)',
  },
)

const emit = defineEmits<{
  mouseover: [payload: unknown]
  mousemove: [payload: unknown]
  mouseout: [payload: unknown]
  globalout: [payload: unknown]
}>()

const chartRef = ref<InstanceType<typeof VChart> | null>(null)
const fullscreenChartRef = ref<InstanceType<typeof VChart> | null>(null)
const fullscreenVisible = ref(false)
const activeChart = computed(() => (fullscreenVisible.value ? fullscreenChartRef.value : chartRef.value))

defineExpose({
  get root() {
    return activeChart.value?.root
  },
})

function openFullscreen() {
  fullscreenVisible.value = true
}

function downloadPng() {
  const chart = activeChart.value ?? chartRef.value
  if (!chart) return
  const url = chart.getDataURL({
    type: 'png',
    pixelRatio: 2,
    backgroundColor: '#fff',
  })
  const link = document.createElement('a')
  link.href = url
  link.download = `${safeFilename(props.filename)}.png`
  link.click()
}

function safeFilename(value: string) {
  return value.trim().replace(/[^\p{L}\p{N}_-]+/gu, '-').replace(/^-+|-+$/g, '') || 'rail-disrupt-chart'
}
</script>

<template>
  <div class="chart-panel">
    <div class="chart-panel-actions">
      <el-button :icon="FullScreen" size="small" @click="openFullscreen">全屏</el-button>
      <el-button :icon="Download" size="small" @click="downloadPng">下载</el-button>
    </div>
    <VChart
      ref="chartRef"
      :option="option"
      autoresize
      class="chart-panel-chart"
      :class="chartClass"
      :style="{ height: props.height }"
      @mouseover="emit('mouseover', $event)"
      @mousemove="emit('mousemove', $event)"
      @mouseout="emit('mouseout', $event)"
      @globalout="emit('globalout', $event)"
    />
    <el-dialog v-model="fullscreenVisible" fullscreen append-to-body destroy-on-close>
      <div class="chart-panel-fullscreen-actions">
        <el-button :icon="Download" @click="downloadPng">下载</el-button>
      </div>
      <VChart
        ref="fullscreenChartRef"
        :option="option"
        autoresize
        class="chart-panel-chart"
        :class="fullscreenClass"
        :style="{ height: props.fullscreenHeight }"
        @mouseover="emit('mouseover', $event)"
        @mousemove="emit('mousemove', $event)"
        @mouseout="emit('mouseout', $event)"
        @globalout="emit('globalout', $event)"
      />
    </el-dialog>
  </div>
</template>

<style scoped>
.chart-panel {
  position: relative;
  width: 100%;
}

.chart-panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 8px;
}

.chart-panel-chart {
  display: block;
  width: 100%;
  min-height: 1px;
}

.chart-panel-fullscreen-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}
</style>
