<script setup lang="ts">
import { computed } from 'vue'

import ChartPanel from '@/components/ChartPanel.vue'
import {
  DISTURBANCE_SERIES,
  buildRunGraphSpaceSeries,
} from '@/components/scenario-category'
import type { TimetableDisturbance } from '@/types'

const props = withDefaults(
  defineProps<{
    disturbances: TimetableDisturbance[]
    stationOrder: string[]
    mileageByStation: Record<string, number>
    filename: string
    height?: string
  }>(),
  {
    height: '300px',
  },
)

const rows = computed(() =>
  buildRunGraphSpaceSeries(props.disturbances, props.stationOrder, props.mileageByStation),
)

const mileageExtent = computed(() => {
  const mileageValues = rows.value
    .map((item) => item.mileage)
    .filter((value) => Number.isFinite(value))
  if (!mileageValues.length) return { min: 0, max: 1 }
  const min = Math.min(...mileageValues)
  const max = Math.max(...mileageValues)
  return { min, max: Math.max(max, min + 1) }
})

const option = computed(() => ({
  tooltip: {
    trigger: 'axis',
    formatter: (params: unknown) => spaceLineTooltip(params),
  },
  legend: {
    top: 0,
    selected: {
      总数: true,
      晚点: false,
      限速: false,
      中断: false,
    },
  },
  grid: { top: 48, right: 18, bottom: 72, left: 56 },
  xAxis: {
    type: 'value',
    min: mileageExtent.value.min,
    max: mileageExtent.value.max,
    axisLabel: { show: false },
    axisTick: { show: false },
  },
  yAxis: { type: 'value', name: '数量' },
  dataZoom: [
    { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
    { type: 'slider', xAxisIndex: 0, height: 22, bottom: 18, filterMode: 'none' },
  ],
  series: [
    ...DISTURBANCE_SERIES.map((series) => ({
      name: series.label,
      type: 'line',
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.12 },
      emphasis: { focus: 'series' },
      data: rows.value.map((item) => ({
        value: [item.mileage, item[series.key]],
        spaceLabel: item.label,
        tooltipLabel: item.tooltipLabel,
      })),
    })),
    {
      name: '车站',
      type: 'scatter',
      symbolSize: 0,
      silent: true,
      tooltip: { show: false },
      label: {
        show: true,
        formatter: (params: { data?: { spaceLabel?: string } }) => params.data?.spaceLabel ?? '',
        position: 'bottom',
        color: '#6b7280',
        fontSize: 10,
        overflow: 'truncate',
        width: 72,
      },
      data: rows.value
        .filter((item) => item.label)
        .map((item) => ({
          value: [item.mileage, 0],
          spaceLabel: item.label,
        })),
      z: 0,
    },
  ],
}))

function spaceLineTooltip(params: unknown) {
  if (!Array.isArray(params)) return ''
  const first = params[0] as { data?: { tooltipLabel?: string; value?: unknown[] } } | undefined
  const label = first?.data?.tooltipLabel || '未知位置'
  const mileage = Array.isArray(first?.data?.value) ? Number(first.data.value[0]) : null
  const lines = [
    `${label}${Number.isFinite(mileage) ? ` (${mileage} km)` : ''}`,
    ...params.map((item) => {
      const payload = item as { marker?: string; seriesName?: string; data?: { value?: unknown[] } }
      const value = Array.isArray(payload.data?.value) ? payload.data.value[1] : 0
      return `${payload.marker ?? ''}${payload.seriesName ?? ''}: ${value}`
    }),
  ]
  return lines.join('<br/>')
}
</script>

<template>
  <ChartPanel :option="option" :filename="filename" :height="height" />
</template>
