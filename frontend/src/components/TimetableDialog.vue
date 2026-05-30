<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import type { Column } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { api, ApiError } from '@/api/client'
import TimetableChart from '@/components/TimetableChart.vue'
import type { CaseTimetableState, TimetableRowState } from '@/types'

const TIMETABLE_TABLE_HEIGHT = 460

const props = defineProps<{
  modelValue: boolean
  projectId: string
  datasetId: string
  caseId: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const timetable = ref<CaseTimetableState | null>(null)
const loading = ref(false)
const errorMessage = ref('')
let requestSeq = 0

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
  const activeTimetable = timetable.value
  if (!activeTimetable) return []
  const planByKey = new Map(activeTimetable.plan.rows.map((row) => [rowKey(row), row]))
  return activeTimetable.adjusted.rows.flatMap((row) => {
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

watch(
  () => [props.modelValue, props.projectId, props.datasetId, props.caseId] as const,
  ([visible]) => {
    if (visible) {
      void loadTimetable()
    } else {
      requestSeq += 1
      loading.value = false
    }
  },
  { immediate: true },
)

async function loadTimetable() {
  const projectId = props.projectId
  const datasetId = props.datasetId
  const caseId = props.caseId
  const seq = requestSeq + 1
  requestSeq = seq
  errorMessage.value = ''

  if (!props.modelValue || !projectId || !datasetId || !caseId) {
    timetable.value = null
    loading.value = false
    return
  }

  loading.value = true
  try {
    const result = await api.readCaseTimetable(projectId, datasetId, caseId)
    if (
      seq !== requestSeq ||
      projectId !== props.projectId ||
      datasetId !== props.datasetId ||
      caseId !== props.caseId
    ) {
      return
    }
    timetable.value = result
  } catch (error) {
    if (
      seq !== requestSeq ||
      projectId !== props.projectId ||
      datasetId !== props.datasetId ||
      caseId !== props.caseId
    ) {
      return
    }
    timetable.value = null
    errorMessage.value = formatError(error)
  } finally {
    if (
      seq === requestSeq &&
      projectId === props.projectId &&
      datasetId === props.datasetId &&
      caseId === props.caseId
    ) {
      loading.value = false
    }
  }
}

function timetableTextCell(value: unknown) {
  return h('span', value == null || value === '' ? '-' : String(value))
}

function rowKey(row: TimetableRowState) {
  return `${row.train_id}\u0000${row.station}`
}

function normalizeTime(value: string | null) {
  return value || ''
}

function formatError(error: unknown) {
  if (error instanceof ApiError) return `${error.status}: ${error.message}`
  if (error instanceof Error) return error.message
  return String(error)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="时刻表数据"
    width="920px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="timetable-dialog-body" element-loading-text="正在加载时刻表数据...">
      <el-empty v-if="!projectId || !datasetId || !caseId" description="请选择实例资源" />
      <el-result v-else-if="errorMessage" icon="error" title="时刻表加载失败" :sub-title="errorMessage">
        <template #extra>
          <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadTimetable">
            重试
          </el-button>
        </template>
      </el-result>
      <template v-else-if="timetable">
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
      <el-empty v-else description="暂无时刻表数据" />
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.timetable-dialog-body {
  min-height: 360px;
}
</style>
