<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import { api, ApiError } from '@/api/client'
import TimetableChart from '@/components/TimetableChart.vue'
import type { PlanTimetableState } from '@/types'

const props = withDefaults(
  defineProps<{
    projectId: string
    active: boolean
    busy?: boolean
  }>(),
  {
    busy: false,
  },
)

const emit = defineEmits<{
  prepare: []
}>()

const timetable = ref<PlanTimetableState | null>(null)
const loading = ref(false)
const errorMessage = ref('')
let requestSeq = 0

const planStats = computed(() => {
  const rows = timetable.value?.plan.rows ?? []
  const mileages = Object.values(timetable.value?.mileage_by_station ?? {}).filter(Number.isFinite)
  const totalMileage =
    mileages.length >= 2 ? Math.max(...mileages) - Math.min(...mileages) : 0
  return {
    stationCount: timetable.value?.station_order.length ?? 0,
    trainCount: new Set(rows.map((row) => row.train_id)).size,
    totalMileage: Math.max(0, totalMileage),
  }
})

const hasRows = computed(() => Boolean(timetable.value?.plan.rows.length))

watch(
  () => [props.projectId, props.active] as const,
  () => {
    void loadTimetable()
  },
  { immediate: true },
)

async function loadTimetable() {
  const projectId = props.projectId
  const active = props.active
  const seq = requestSeq + 1
  requestSeq = seq
  errorMessage.value = ''

  if (!projectId || !active) {
    timetable.value = null
    loading.value = false
    return
  }

  loading.value = true
  try {
    const result = await api.readPlanTimetable(projectId)
    if (seq !== requestSeq || projectId !== props.projectId) return
    timetable.value = result
  } catch (error) {
    if (seq !== requestSeq || projectId !== props.projectId) return
    timetable.value = null
    errorMessage.value = formatError(error)
  } finally {
    if (seq === requestSeq && projectId === props.projectId) {
      loading.value = false
    }
  }
}

function handlePrepare() {
  if (props.busy) return
  emit('prepare')
}

function formatError(error: unknown) {
  if (error instanceof ApiError) return `${error.status}: ${error.message}`
  if (error instanceof Error) return error.message
  return String(error)
}
</script>

<template>
  <div class="page-stack">
    <el-row class="dashboard-summary-row" :gutter="16">
      <el-col class="dashboard-summary-col" :span="6">
        <el-card
          class="plan-status-card"
          :class="{
            'is-active': active,
            'is-inactive': !active,
            'is-clickable': !active && !busy,
          }"
          shadow="never"
          @click="handlePrepare"
        >
          <el-result
            class="compact-result"
            :icon="active ? 'success' : 'warning'"
            :title="active ? '已激活' : '未激活'"
            :sub-title="active ? '原计划运行图' : '上传时刻表和里程表后激活'"
          />
        </el-card>
      </el-col>
      <el-col class="dashboard-summary-col" :span="18">
        <div class="dashboard-stat-grid">
          <el-card v-loading="loading" shadow="never">
            <el-statistic title="站点数量" :value="planStats.stationCount" />
          </el-card>
          <el-card v-loading="loading" shadow="never">
            <el-statistic title="车次数量" :value="planStats.trainCount" />
          </el-card>
          <el-card v-loading="loading" shadow="never">
            <el-statistic title="总里程" :value="planStats.totalMileage" suffix="km" />
          </el-card>
        </div>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>原计划运行图</span>
          <el-button
            :icon="Refresh"
            :disabled="!projectId || !active || busy"
            :loading="loading"
            @click="loadTimetable"
          >
            刷新
          </el-button>
        </div>
      </template>

      <div v-loading="loading" class="plan-timetable-body" element-loading-text="正在加载原计划运行图...">
        <el-empty v-if="!projectId" description="请选择项目" />
        <el-empty v-else-if="!active" description="原计划运行图未激活">
          <el-button type="primary" :disabled="busy" @click="handlePrepare">激活原计划运行图</el-button>
        </el-empty>
        <el-result v-else-if="errorMessage" icon="error" title="运行图加载失败" :sub-title="errorMessage">
          <template #extra>
            <el-button type="primary" :loading="loading" :disabled="busy" @click="loadTimetable">
              重试
            </el-button>
          </template>
        </el-result>
        <TimetableChart
          v-else-if="hasRows"
          :rows="timetable?.plan.rows ?? []"
          :station-order="timetable?.station_order ?? []"
          title="原计划运行图"
        />
        <el-empty v-else description="暂无原计划运行图数据" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.plan-timetable-body {
  min-height: 360px;
}
</style>
