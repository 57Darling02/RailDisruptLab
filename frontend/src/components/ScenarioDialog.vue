<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api, formatApiError } from '@/api/client'
import { Refresh } from '@/icons'
import type { JsonObject, ScenarioOptions } from '@/types'

type ScenarioDelayForm = { event_anchor_id: string; seconds: number }
type ScenarioSpeedLimitForm = {
  section_anchor_id: string
  start_time: string
  duration: number
  limit_speed: number
}
export type ScenarioPayload = {
  delays: Array<{ train_id: string; station: string; event_type: string; seconds: number }>
  speed_limits: Array<{
    start_station: string
    end_station: string
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
    optionsScenarioId?: string
    existingScenario?: JsonObject | null
    title?: string
  }>(),
  {
    busy: false,
    submitting: false,
    initialScenarioId: '',
    optionsScenarioId: '',
    existingScenario: null,
    title: '编辑扰动事件',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: { scenarioId: string; data: ScenarioPayload }]
}>()

const scenarioId = ref('')
const options = ref<ScenarioOptions | null>(null)
const delays = ref<ScenarioDelayForm[]>([])
const speedLimits = ref<ScenarioSpeedLimitForm[]>([])
const loading = ref(false)
const errorMessage = ref('')
let requestSeq = 0

const eventOptions = computed(() => options.value?.event_anchors ?? [])
const sectionOptions = computed(() => options.value?.section_anchors ?? [])
const eventSelectOptions = computed(() =>
  eventOptions.value.map((item) => ({
    value: item.anchor_id,
    label: `${item.train_id} · ${item.station} · ${item.event_type} · ${item.planned_time_text}`,
  })),
)
const sectionSelectOptions = computed(() =>
  sectionOptions.value.map((item) => ({
    value: item.anchor_id,
    label: `${item.start_station} -> ${item.end_station}`,
  })),
)
const eventOptionById = computed(() => new Map(eventOptions.value.map((item) => [item.anchor_id, item])))
const sectionOptionById = computed(() => new Map(sectionOptions.value.map((item) => [item.anchor_id, item])))

watch(
  () => [props.modelValue, props.projectId, props.scenarioSetId, props.optionsScenarioId, props.initialScenarioId] as const,
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
  const scenarioIdForOptions = props.optionsScenarioId || props.initialScenarioId
  const seq = requestSeq + 1
  requestSeq = seq
  errorMessage.value = ''

  if (!props.modelValue || !projectId || !props.scenarioSetId || !scenarioIdForOptions) {
    options.value = null
    loading.value = false
    return
  }

  loading.value = true
  try {
    const result = await api.readScenarioOptions(projectId, props.scenarioSetId, scenarioIdForOptions)
    if (seq !== requestSeq || projectId !== props.projectId) return
    options.value = result
    resetForm()
  } catch (error) {
    if (seq !== requestSeq || projectId !== props.projectId) return
    options.value = null
    errorMessage.value = formatApiError(error)
  } finally {
    if (seq === requestSeq && projectId === props.projectId) {
      loading.value = false
    }
  }
}

function resetForm() {
  scenarioId.value = props.initialScenarioId
  delays.value = scenarioList(props.existingScenario?.delays).map((item) => ({
    event_anchor_id: eventAnchorIdForScenario(item),
    seconds: Math.floor(positiveNumber(numberValue(item.seconds), 600)),
  }))
  speedLimits.value = scenarioList(props.existingScenario?.speed_limits).map((item) => ({
    section_anchor_id: sectionAnchorIdForScenario(item),
    start_time: formatStartTime(item.start_time),
    duration: Math.floor(positiveNumber(numberValue(item.duration), 1800)),
    limit_speed: Math.max(0, numberValue(item.limit_speed) ?? 160),
  }))
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
    data: {
      delays: delays.value
        .filter((item) => item.event_anchor_id)
        .map((item) => {
          const anchor = eventOptionById.value.get(item.event_anchor_id)
          return {
            train_id: anchor?.train_id ?? '',
            station: anchor?.station ?? '',
            event_type: anchor?.event_type ?? '',
            seconds: Math.floor(positiveNumber(item.seconds, 600)),
          }
        })
        .filter((item) => item.train_id && item.station && item.event_type),
      speed_limits: speedLimits.value
        .filter((item) => item.section_anchor_id)
        .map((item) => {
          const anchor = sectionOptionById.value.get(item.section_anchor_id)
          return {
            start_station: anchor?.start_station ?? '',
            end_station: anchor?.end_station ?? '',
            start_time: item.start_time || '08:00:00',
            duration: Math.floor(positiveNumber(item.duration, 1800)),
            limit_speed: Math.max(0, Number.isFinite(item.limit_speed) ? item.limit_speed : 160),
          }
        })
        .filter((item) => item.start_station && item.end_station),
    },
  })
}

function eventAnchorIdForScenario(item: JsonObject) {
  const anchorId = stringValue(item.event_anchor_id)
  if (anchorId) return anchorId
  const trainId = stringValue(item.train_id)
  const station = stringValue(item.station)
  const eventType = stringValue(item.event_type)
  return eventOptions.value.find(
    (option) => option.train_id === trainId && option.station === station && option.event_type === eventType,
  )?.anchor_id ?? ''
}

function sectionAnchorIdForScenario(item: JsonObject) {
  const anchorId = stringValue(item.section_anchor_id)
  if (anchorId) return anchorId
  const startStation = stringValue(item.start_station)
  const endStation = stringValue(item.end_station)
  return sectionOptions.value.find(
    (option) => option.start_station === startStation && option.end_station === endStation,
  )?.anchor_id ?? ''
}

function scenarioList(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function isRecord(value: unknown): value is JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function stringValue(value: unknown) {
  return typeof value === 'string' ? value : String(value ?? '')
}

function numberValue(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function positiveNumber(value: number | null | undefined, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback
}

function formatStartTime(value: unknown) {
  if (typeof value === 'string') return value
  const number = numberValue(value)
  if (number == null) return '08:00:00'
  const total = Math.max(0, Math.floor(number))
  const hour = Math.floor(total / 3600)
  const minute = Math.floor((total % 3600) / 60)
  const second = total % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}`
}

</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="min(1080px, calc(100vw - 32px))"
    class="scenario-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="scenario-dialog-body" element-loading-text="正在加载场景锚点...">
      <el-result v-if="errorMessage" icon="error" title="场景锚点加载失败" :sub-title="errorMessage">
        <template #extra>
          <el-button
            type="primary"
            :icon="Refresh"
            :loading-icon="Refresh"
            :loading="loading"
            :disabled="busy"
            @click="loadOptions"
          >
            重试
          </el-button>
        </template>
      </el-result>
      <el-form v-else label-width="100px">
        <el-form-item label="场景分类">
          <el-input :model-value="scenarioSetId" disabled />
        </el-form-item>
        <el-form-item label="场景 ID">
          <el-input v-model="scenarioId" disabled />
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
              <el-select-v2
                v-model="row.event_anchor_id"
                filterable
                class="full-width"
                :disabled="busy"
                :options="eventSelectOptions"
              />
            </template>
          </el-table-column>
          <el-table-column label="晚点秒数" width="180">
            <template #default="{ row }">
              <el-input-number v-model="row.seconds" :min="1" controls-position="right" :disabled="busy" />
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
              <el-select-v2
                v-model="row.section_anchor_id"
                filterable
                class="full-width"
                :disabled="busy"
                :options="sectionSelectOptions"
              />
            </template>
          </el-table-column>
          <el-table-column label="开始时间" width="170">
            <template #default="{ row }">
              <el-time-picker
                v-model="row.start_time"
                format="HH:mm:ss"
                value-format="HH:mm:ss"
                placeholder="开始时间"
                :disabled="busy"
              />
            </template>
          </el-table-column>
          <el-table-column label="持续秒数" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.duration" :min="1" controls-position="right" :disabled="busy" />
            </template>
          </el-table-column>
          <el-table-column label="限速" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.limit_speed" :min="0" controls-position="right" :disabled="busy" />
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

.full-width {
  width: 100%;
}

:deep(.el-input-number),
:deep(.el-date-editor.el-input) {
  width: 100%;
}
</style>
