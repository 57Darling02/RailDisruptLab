<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'

import { api, ApiError } from '@/api/client'
import type { ScenarioOptions } from '@/types'

type ScenarioDelayForm = { event_anchor_id: string; seconds: number }
type ScenarioSpeedLimitForm = {
  section_anchor_id: string
  start_time: string
  duration: number
  limit_speed: number
}
export type ScenarioPayload = {
  delays: Array<{ event_anchor_id: string; seconds: number }>
  speed_limits: Array<{
    section_anchor_id: string
    start_time: string
    duration: number
    limit_speed: number
  }>
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    projectId: string
    scenarioSetId: string
    busy?: boolean
    submitting?: boolean
    initialScenarioId?: string
  }>(),
  {
    busy: false,
    submitting: false,
    initialScenarioId: '',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: { scenarioId: string; overwrite: boolean; data: ScenarioPayload }]
}>()

const scenarioId = ref('')
const overwrite = ref(false)
const options = ref<ScenarioOptions | null>(null)
const delays = ref<ScenarioDelayForm[]>([])
const speedLimits = ref<ScenarioSpeedLimitForm[]>([])
const loading = ref(false)
const errorMessage = ref('')
let requestSeq = 0

const eventOptions = computed(() => options.value?.event_anchors ?? [])
const sectionOptions = computed(() => options.value?.section_anchors ?? [])

watch(
  () => [props.modelValue, props.projectId, props.initialScenarioId] as const,
  ([visible]) => {
    if (!visible) {
      requestSeq += 1
      loading.value = false
      return
    }
    resetForm()
    void loadOptions()
  },
  { immediate: true },
)

async function loadOptions() {
  const projectId = props.projectId
  const seq = requestSeq + 1
  requestSeq = seq
  errorMessage.value = ''

  if (!props.modelValue || !projectId) {
    options.value = null
    loading.value = false
    return
  }

  loading.value = true
  try {
    const result = await api.readScenarioOptions(projectId)
    if (seq !== requestSeq || projectId !== props.projectId) return
    options.value = result
  } catch (error) {
    if (seq !== requestSeq || projectId !== props.projectId) return
    options.value = null
    errorMessage.value = formatError(error)
  } finally {
    if (seq === requestSeq && projectId === props.projectId) {
      loading.value = false
    }
  }
}

function resetForm() {
  scenarioId.value = props.initialScenarioId
  overwrite.value = false
  delays.value = []
  speedLimits.value = []
  errorMessage.value = ''
}

function addDelayRow() {
  delays.value.push({
    event_anchor_id: eventOptions.value[0]?.anchor_id ?? '',
    seconds: 600,
  })
}

function removeDelayRow(index: number) {
  delays.value.splice(index, 1)
}

function addSpeedLimitRow(limitSpeed = 160) {
  speedLimits.value.push({
    section_anchor_id: sectionOptions.value[0]?.anchor_id ?? '',
    start_time: '08:00:00',
    duration: 1800,
    limit_speed: limitSpeed,
  })
}

function removeSpeedLimitRow(index: number) {
  speedLimits.value.splice(index, 1)
}

function submitScenario() {
  emit('submit', {
    scenarioId: scenarioId.value.trim(),
    overwrite: overwrite.value,
    data: {
      delays: delays.value
        .filter((item) => item.event_anchor_id)
        .map((item) => ({
          event_anchor_id: item.event_anchor_id,
          seconds: Math.floor(positiveNumber(item.seconds, 600)),
        })),
      speed_limits: speedLimits.value
        .filter((item) => item.section_anchor_id)
        .map((item) => ({
          section_anchor_id: item.section_anchor_id,
          start_time: item.start_time || '08:00:00',
          duration: Math.floor(positiveNumber(item.duration, 1800)),
          limit_speed: Math.max(0, Number.isFinite(item.limit_speed) ? item.limit_speed : 160),
        })),
    },
  })
}

function positiveNumber(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback
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
    title="新增场景"
    width="920px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="scenario-dialog-body" element-loading-text="正在加载场景锚点...">
      <el-result v-if="errorMessage" icon="error" title="场景锚点加载失败" :sub-title="errorMessage">
        <template #extra>
          <el-button type="primary" :icon="Refresh" :loading="loading" :disabled="busy" @click="loadOptions">
            重试
          </el-button>
        </template>
      </el-result>
      <el-form v-else label-width="100px">
        <el-form-item label="场景集">
          <el-input :model-value="scenarioSetId" disabled />
        </el-form-item>
        <el-form-item label="场景 ID">
          <el-input v-model="scenarioId" :disabled="busy" />
        </el-form-item>
        <el-form-item label="覆盖">
          <el-switch v-model="overwrite" :disabled="busy" />
        </el-form-item>
        <el-alert
          title="中断按 limit_speed = 0 记录，与 core 的场景格式保持一致。"
          type="info"
          show-icon
          :closable="false"
        />
        <el-divider content-position="left">晚点扰动</el-divider>
        <el-table :data="delays" empty-text="暂无晚点扰动">
          <el-table-column label="计划事件" min-width="280">
            <template #default="{ row }">
              <el-select v-model="row.event_anchor_id" filterable class="full-width" :disabled="busy">
                <el-option
                  v-for="item in eventOptions"
                  :key="item.anchor_id"
                  :label="`${item.train_id} · ${item.station} · ${item.event_type} · ${item.planned_time_text}`"
                  :value="item.anchor_id"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="晚点秒数" width="180">
            <template #default="{ row }">
              <el-input-number v-model="row.seconds" :min="1" :disabled="busy" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ $index }">
              <el-button link type="danger" :disabled="busy" @click="removeDelayRow($index)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="dialog-actions">
          <el-button :disabled="busy || !eventOptions.length" @click="addDelayRow">添加晚点</el-button>
        </div>

        <el-divider content-position="left">限速 / 中断扰动</el-divider>
        <el-table :data="speedLimits" empty-text="暂无限速或中断扰动">
          <el-table-column label="区间" min-width="240">
            <template #default="{ row }">
              <el-select v-model="row.section_anchor_id" filterable class="full-width" :disabled="busy">
                <el-option
                  v-for="item in sectionOptions"
                  :key="item.anchor_id"
                  :label="`${item.start_station} -> ${item.end_station}`"
                  :value="item.anchor_id"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="开始时间" width="150">
            <template #default="{ row }">
              <el-input v-model="row.start_time" placeholder="HH:MM:SS" :disabled="busy" />
            </template>
          </el-table-column>
          <el-table-column label="持续秒数" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.duration" :min="1" :disabled="busy" />
            </template>
          </el-table-column>
          <el-table-column label="限速" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.limit_speed" :min="0" :disabled="busy" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ $index }">
              <el-button link type="danger" :disabled="busy" @click="removeSpeedLimitRow($index)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="dialog-actions">
          <el-button :disabled="busy || !sectionOptions.length" @click="addSpeedLimitRow()">添加限速</el-button>
          <el-button :disabled="busy || !sectionOptions.length" @click="addSpeedLimitRow(0)">添加中断</el-button>
        </div>
      </el-form>
    </div>

    <template #footer>
      <el-button :disabled="busy" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        :disabled="busy || loading || Boolean(errorMessage)"
        @click="submitScenario"
      >
        确定
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.scenario-dialog-body {
  min-height: 420px;
}
</style>
