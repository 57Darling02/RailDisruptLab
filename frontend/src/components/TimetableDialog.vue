<script setup lang="ts">
import { computed, h } from 'vue'
import type { Column } from 'element-plus'

import TimetableChart from '@/components/TimetableChart.vue'
import type { CaseTimetableState, TimetableRowState } from '@/types'

const TIMETABLE_TABLE_HEIGHT = 460

const props = defineProps<{
  modelValue: boolean
  timetable: CaseTimetableState | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const planTimetableColumns: Column<TimetableRowState>[] = [
  { key: 'row_number', dataKey: 'row_number', title: '#', width: 70, align: 'right' },
  { key: 'train_id', dataKey: 'train_id', title: '车次', width: 120 },
  { key: 'station', dataKey: 'station', title: '车站', width: 220, flexGrow: 1 },
  {
    key: 'arrival_time',
    dataKey: 'arrival_time',
    title: '到达',
    width: 130,
    cellRenderer: ({ cellData }) => timetableTextCell(cellData),
  },
  {
    key: 'departure_time',
    dataKey: 'departure_time',
    title: '出发',
    width: 130,
    cellRenderer: ({ cellData }) => timetableTextCell(cellData),
  },
]

interface AdjustedDiffRow {
  key: string
  row_number: number
  train_id: string
  station: string
  plan_arrival_time: string | null
  plan_departure_time: string | null
  adjusted_arrival_time: string | null
  adjusted_departure_time: string | null
  is_canceled: boolean
}

const adjustedTimetableColumns: Column<AdjustedDiffRow>[] = [
  { key: 'row_number', dataKey: 'row_number', title: '#', width: 70, align: 'right' },
  { key: 'train_id', dataKey: 'train_id', title: '车次', width: 110 },
  { key: 'station', dataKey: 'station', title: '车站', width: 160, flexGrow: 1 },
  {
    key: 'plan_arrival_time',
    dataKey: 'plan_arrival_time',
    title: '原到达',
    width: 120,
    cellRenderer: ({ cellData }) => timetableTextCell(cellData),
  },
  {
    key: 'plan_departure_time',
    dataKey: 'plan_departure_time',
    title: '原出发',
    width: 120,
    cellRenderer: ({ cellData }) => timetableTextCell(cellData),
  },
  {
    key: 'adjusted_arrival_time',
    dataKey: 'adjusted_arrival_time',
    title: '调整到达',
    width: 120,
    cellRenderer: ({ cellData }) => timetableTextCell(cellData),
  },
  {
    key: 'adjusted_departure_time',
    dataKey: 'adjusted_departure_time',
    title: '调整出发',
    width: 120,
    cellRenderer: ({ cellData }) => timetableTextCell(cellData),
  },
  {
    key: 'is_canceled',
    dataKey: 'is_canceled',
    title: '取消',
    width: 90,
    cellRenderer: ({ rowData }) => timetableTextCell(rowData.is_canceled ? '是' : '否'),
  },
]

const changedAdjustedRows = computed(() => {
  const timetable = props.timetable
  if (!timetable) return []
  const planByKey = new Map(timetable.plan.rows.map((row) => [rowKey(row), row]))
  return timetable.adjusted.rows.flatMap((row) => {
    const plan = planByKey.get(rowKey(row))
    const changed =
      !plan ||
      normalizeTime(row.arrival_time) !== normalizeTime(plan.arrival_time) ||
      normalizeTime(row.departure_time) !== normalizeTime(plan.departure_time) ||
      Boolean(row.is_canceled) !== Boolean(plan.is_canceled)
    if (!changed) return []
    return [
      {
        key: rowKey(row),
        row_number: row.row_number,
        train_id: row.train_id,
        station: row.station,
        plan_arrival_time: plan?.arrival_time ?? null,
        plan_departure_time: plan?.departure_time ?? null,
        adjusted_arrival_time: row.arrival_time,
        adjusted_departure_time: row.departure_time,
        is_canceled: Boolean(row.is_canceled),
      },
    ]
  })
})

function timetableTextCell(value: unknown) {
  return h('span', value == null || value === '' ? '-' : String(value))
}

function rowKey(row: TimetableRowState) {
  return `${row.train_id}\u0000${row.station}`
}

function normalizeTime(value: string | null) {
  return value || ''
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="时刻表数据"
    width="920px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template v-if="timetable">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="数据集">
          {{ timetable.dataset_id }}
        </el-descriptions-item>
        <el-descriptions-item label="Case">
          {{ timetable.case_id }}
        </el-descriptions-item>
        <el-descriptions-item label="车站数">
          {{ timetable.station_order.length }}
        </el-descriptions-item>
        <el-descriptions-item label="原计划行数">
          {{ timetable.plan.rows.length }}
        </el-descriptions-item>
        <el-descriptions-item label="调整行数">
          {{ changedAdjustedRows.length }}
        </el-descriptions-item>
      </el-descriptions>

      <el-tabs class="dialog-section" lazy>
        <el-tab-pane label="调整运行图">
          <TimetableChart
            :rows="timetable.adjusted.rows"
            :plan-rows="timetable.plan.rows"
            :station-order="timetable.station_order"
            :disturbances="timetable.disturbances"
            :title="`${timetable.case_id} 调整运行图`"
            compare-mode
          />
        </el-tab-pane>
        <el-tab-pane label="调整后计划">
          <el-auto-resizer class="virtual-table-resizer">
            <template #default="{ width }">
              <el-table-v2
                :columns="adjustedTimetableColumns"
                :data="changedAdjustedRows"
                :width="width"
                :height="TIMETABLE_TABLE_HEIGHT"
                :row-height="42"
                row-key="key"
                fixed
              />
            </template>
          </el-auto-resizer>
        </el-tab-pane>
        <el-tab-pane label="原计划">
          <el-auto-resizer class="virtual-table-resizer">
            <template #default="{ width }">
              <el-table-v2
                :columns="planTimetableColumns"
                :data="timetable.plan.rows"
                :width="width"
                :height="TIMETABLE_TABLE_HEIGHT"
                :row-height="42"
                row-key="row_number"
                fixed
              />
            </template>
          </el-auto-resizer>
        </el-tab-pane>
      </el-tabs>
    </template>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>
