<script setup lang="ts">
import { computed } from 'vue'
import TimetableChart from '@/components/TimetableChart.vue'
import type { DatasetSummary, ModelSummary, PlanTimetableState, Task } from '@/types'

const props = defineProps<{
  planTimetable: PlanTimetableState | null
  scenarioSetCount: number
  datasets: DatasetSummary[]
  models: ModelSummary[]
  originalGraphActive: boolean
  tasks: Task[]
  runningTaskCount: number
  doneTaskCount: number
  failedTaskCount: number
}>()

const emit = defineEmits<{
  prepare: []
  refreshTasks: []
}>()

const planStats = computed(() => {
  const timetable = props.planTimetable
  const rows = timetable?.plan.rows ?? []
  const mileages = Object.values(timetable?.mileage_by_station ?? {}).filter(Number.isFinite)
  const totalMileage =
    mileages.length >= 2 ? Math.max(...mileages) - Math.min(...mileages) : 0
  return {
    stationCount: timetable?.station_order.length ?? 0,
    trainCount: new Set(rows.map((row) => row.train_id)).size,
    totalMileage: Math.max(0, totalMileage),
  }
})

function handlePlanCardClick() {
  if (!props.originalGraphActive) emit('prepare')
}
</script>

<template>
  <section class="page-layout">
    <div class="page-stack">
      <el-row class="dashboard-summary-row" :gutter="16">
        <el-col class="dashboard-summary-col" :span="6">
          <el-card
            class="plan-status-card"
            :class="{
              'is-active': originalGraphActive,
              'is-inactive': !originalGraphActive,
              'is-clickable': !originalGraphActive,
            }"
            shadow="never"
            @click="handlePlanCardClick"
          >
            <el-result
              class="compact-result"
              :icon="originalGraphActive ? 'success' : 'warning'"
              :title="originalGraphActive ? '已激活' : '未激活'"
              :sub-title="
                originalGraphActive ? '原计划运行图' : '上传时刻表和里程表后激活'
              "
            />
          </el-card>
        </el-col>
        <el-col class="dashboard-summary-col" :span="18">
          <div class="dashboard-stat-grid">
            <el-card shadow="never">
              <el-statistic title="站点数量" :value="planStats.stationCount" />
            </el-card>
            <el-card shadow="never">
              <el-statistic title="车次数量" :value="planStats.trainCount" />
            </el-card>
            <el-card shadow="never">
              <el-statistic title="总里程" :value="planStats.totalMileage" suffix="km" />
            </el-card>
            <el-card shadow="never">
              <el-statistic title="扰动场景集" :value="scenarioSetCount" />
            </el-card>
            <el-card shadow="never">
              <el-statistic title="MILP实例集" :value="datasets.length" />
            </el-card>
            <el-card shadow="never">
              <el-statistic title="扰动生成模型" :value="models.length" />
            </el-card>
          </div>
        </el-col>
      </el-row>

      <el-card v-if="originalGraphActive" shadow="never">
        <template #header>
          <div class="card-header">
            <span>原计划运行图</span>
          </div>
        </template>
        <TimetableChart
          :rows="planTimetable?.plan.rows ?? []"
          :station-order="planTimetable?.station_order ?? []"
          title="原计划运行图"
        />
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>任务总览</span>
            <el-button @click="$emit('refreshTasks')">刷新</el-button>
          </div>
        </template>
        <el-row :gutter="16">
          <el-col :span="6">
            <el-statistic title="全部任务" :value="tasks.length" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="运行/排队" :value="runningTaskCount" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="已完成" :value="doneTaskCount" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="失败/终止" :value="failedTaskCount" />
          </el-col>
        </el-row>
      </el-card>
    </div>
  </section>
</template>
