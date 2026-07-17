import type {
  AdjustmentPlanDetail,
  AdjustmentPlanRef,
  AdjustmentPlanSummary,
  AdjustmentPlanSolveAnalysis,
  ArtifactSummary,
  CaseTimetableState,
  JsonObject,
  ModelCheckpoint,
  ModelDetail,
  PlanTimetableState,
  ProjectState,
  ProjectSummary,
  ResourceOption,
  RunGraphReference,
  RunGraphSet,
  RunGraphSummary,
  RunGraphTimetableState,
  ScenarioSet,
  ScenarioSetVisualization,
  ScenarioDetail,
  ScenarioOptions,
  ScenarioSummary,
  Task,
  TaskResponse,
} from '@/types'

const API_PREFIX = '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

export function formatApiError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.status === 409 ? error.message : `${error.status}: ${error.message}`
  }
  if (error instanceof Error) return error.message
  return String(error)
}

export function isApiConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init.headers,
    },
  })
  if (!response.ok) {
    const detail = await readError(response)
    throw new ApiError(detail || response.statusText, response.status)
  }
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    return (await response.json()) as T
  }
  return (await response.text()) as T
}

async function readError(response: Response): Promise<string> {
  const body = await response.text()
  if (!body) return ''
  try {
    const payload = JSON.parse(body) as { detail?: unknown }
    return typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
  } catch {
    return body
  }
}

function jsonBody(payload: unknown): RequestInit {
  return { body: JSON.stringify(payload) }
}

export const api = {
  health: () => request<JsonObject>('/health'),
  listProjects: () => request<ProjectSummary[]>('/projects'),
  listProjectOptions: (query = '', limit = 50) => {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    })
    return request<ResourceOption[]>(`/project-options?${params}`)
  },
  createProject: (projectId: string) =>
    request<ProjectState>('/projects', {
      method: 'POST',
      ...jsonBody({ project_id: projectId }),
    }),
  deleteProject: (projectId: string) =>
    request<TaskResponse>(`/projects/${projectId}`, {
      method: 'DELETE',
    }),
  getProject: (projectId: string) => request<ProjectState>(`/projects/${projectId}`),
  listResourceOptions: (projectId: string, resource: string, query = '', limit = 50) => {
    const params = new URLSearchParams({
      resource,
      q: query,
      limit: String(limit),
    })
    return request<ResourceOption[]>(`/projects/${projectId}/resource-options?${params}`)
  },
  listScenarioSets: (projectId: string) =>
    request<ScenarioSet[]>(`/projects/${projectId}/scenario-sets`),
  listRunGraphSets: (projectId: string) =>
    request<RunGraphSet[]>(`/projects/${projectId}/run-graph-sets`),
  createRunGraphSet: (projectId: string, runGraphSetId: string, existOk = false) =>
    request<RunGraphSet>(`/projects/${projectId}/run-graph-sets`, {
      method: 'POST',
      ...jsonBody({ run_graph_set_id: runGraphSetId, exist_ok: existOk }),
    }),
  deleteRunGraphSet: (projectId: string, runGraphSetId: string) =>
    request<JsonObject>(`/projects/${projectId}/run-graph-sets/${runGraphSetId}`, {
      method: 'DELETE',
    }),
  listRunGraphs: (projectId: string, runGraphSetId: string) =>
    request<RunGraphSummary[]>(
      `/projects/${projectId}/run-graph-sets/${runGraphSetId}/run-graphs`,
    ),
  createRunGraph: (
    projectId: string,
    runGraphSetId: string,
    runGraphId: string,
    timetableFile: File,
    mileageFile: File,
    overwrite = false,
  ) => {
    const params = new URLSearchParams({ run_graph_id: runGraphId, overwrite: String(overwrite) })
    const data = new FormData()
    data.append('timetable_file', timetableFile)
    data.append('mileage_file', mileageFile)
    return request<TaskResponse>(
      `/projects/${projectId}/run-graph-sets/${runGraphSetId}/run-graphs?${params}`,
      { method: 'POST', body: data },
    )
  },
  readRunGraph: (projectId: string, runGraphSetId: string, runGraphId: string) =>
    request<RunGraphSummary>(
      `/projects/${projectId}/run-graph-sets/${runGraphSetId}/run-graphs/${runGraphId}`,
    ),
  readRunGraphTimetable: (projectId: string, runGraphSetId: string, runGraphId: string) =>
    request<RunGraphTimetableState>(
      `/projects/${projectId}/run-graph-sets/${runGraphSetId}/run-graphs/${runGraphId}/timetable`,
    ),
  readRunGraphOptions: (projectId: string, runGraphSetId: string, runGraphId: string) =>
    request<ScenarioOptions>(
      `/projects/${projectId}/run-graph-sets/${runGraphSetId}/run-graphs/${runGraphId}/options`,
    ),
  deleteRunGraph: (projectId: string, runGraphSetId: string, runGraphId: string) =>
    request<JsonObject>(
      `/projects/${projectId}/run-graph-sets/${runGraphSetId}/run-graphs/${runGraphId}`,
      { method: 'DELETE' },
    ),
  createScenarioSet: (projectId: string, scenarioSetId: string, existOk = false) =>
    request<ScenarioSet>(`/projects/${projectId}/scenario-sets`, {
      method: 'POST',
      ...jsonBody({ scenario_set_id: scenarioSetId, exist_ok: existOk }),
    }),
  deleteScenarioSet: (projectId: string, scenarioSetId: string) =>
    request<JsonObject>(`/projects/${projectId}/scenario-sets/${scenarioSetId}`, {
      method: 'DELETE',
    }),
  listScenarios: (projectId: string, scenarioSetId: string) =>
    request<ScenarioSummary[]>(`/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios`),
  listScenarioOptions: (projectId: string, scenarioSetId: string, query = '', limit = 50) => {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    })
    return request<ResourceOption[]>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenario-options?${params}`,
    )
  },
  readScenarioSetVisualization: (projectId: string, scenarioSetId: string) =>
    request<ScenarioSetVisualization>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/visualization`,
    ),
  readScenario: (projectId: string, scenarioSetId: string, scenarioId: string) =>
    request<ScenarioDetail>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}`,
    ),
  readScenarioTimetable: (projectId: string, scenarioSetId: string, scenarioId: string) =>
    request<PlanTimetableState>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}/timetable`,
    ),
  readScenarioOptions: (projectId: string, scenarioSetId: string, scenarioId: string) =>
    request<ScenarioOptions>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}/options`,
    ),
  createScenarioCase: (
    projectId: string,
    scenarioSetId: string,
    scenarioId: string,
    runGraph: RunGraphReference,
    payload: { delays: object[]; speed_limits: object[] } = { delays: [], speed_limits: [] },
    overwrite = false,
  ) =>
    request<ScenarioSummary>(`/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios`, {
      method: 'POST',
      ...jsonBody({ scenario_id: scenarioId, run_graph: runGraph, ...payload, overwrite }),
    }),
  updateScenarioDisturbances: (
    projectId: string,
    scenarioSetId: string,
    scenarioId: string,
    payload: { delays: object[]; speed_limits: object[] },
    runGraph?: RunGraphReference | null,
  ) =>
    request<ScenarioDetail>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}/disturbances`,
      {
        method: 'PUT',
        ...jsonBody({ ...payload, run_graph: runGraph ?? null }),
      },
    ),
  validateScenario: (
    projectId: string,
    scenarioSetId: string,
    scenarioId: string,
    runGraph?: RunGraphReference | null,
  ) =>
    request<ScenarioDetail>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}/validation`,
      {
        method: 'POST',
        ...jsonBody({ run_graph: runGraph ?? null }),
      },
    ),
  deleteScenario: (projectId: string, scenarioSetId: string, scenarioId: string) =>
    request<TaskResponse>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}`,
      {
        method: 'DELETE',
      },
    ),
  submitNormalGenerate: (projectId: string, payload: object) =>
    request<TaskResponse>(`/projects/${projectId}/tasks/normal-generate`, {
      method: 'POST',
      ...jsonBody(payload),
    }),
  submitValidateScenarios: (projectId: string, scenarioSetId: string) =>
    request<TaskResponse>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/tasks/validate-scenarios`,
      { method: 'POST' },
    ),
  listAdjustmentPlans: (projectId: string, scenarioSetId: string) =>
    request<AdjustmentPlanSummary[]>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plans`,
    ),
  listAdjustmentPlanOptions: (projectId: string, scenarioSetId: string, query = '', limit = 50) => {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    })
    return request<ResourceOption[]>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plan-options?${params}`,
    )
  },
  createAdjustmentPlan: (projectId: string, scenarioSetId: string, planId: string, existOk = false) =>
    request<AdjustmentPlanSummary>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plans`,
      {
        method: 'POST',
        ...jsonBody({ plan_id: planId, exist_ok: existOk }),
      },
    ),
  deleteAdjustmentPlan: (projectId: string, scenarioSetId: string, planId: string) =>
    request<JsonObject>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plans/${planId}`,
      {
        method: 'DELETE',
      },
    ),
  submitBuild: (
    projectId: string,
    scenarioSetId: string,
    planId: string,
    scenarioId = '',
    options: object = {},
  ) =>
    request<TaskResponse>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plans/${planId}/tasks/build`,
      {
        method: 'POST',
        ...jsonBody({
          scenario_id: scenarioId,
          ...options,
        }),
      },
    ),
  submitSolve: (
    projectId: string,
    scenarioSetId: string,
    planId: string,
    limit = 0,
    timeLimit?: number,
    caseId = '',
    mipGap?: number,
    threads?: number,
    skipSolved = false,
  ) =>
    request<TaskResponse>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plans/${planId}/tasks/solve`,
      {
        method: 'POST',
        ...jsonBody({
          case_id: caseId,
          limit,
          time_limit: timeLimit ?? null,
          mip_gap: mipGap ?? null,
          threads: threads ?? null,
          skip_solved: skipSolved,
        }),
      },
    ),
  submitTrain: (projectId: string, payload: unknown) =>
    request<TaskResponse>(`/projects/${projectId}/tasks/train`, {
      method: 'POST',
      ...jsonBody(payload),
    }),
  submitGeneration: (
    projectId: string,
    modelId: string,
    checkpoint: string,
    scenarioSetId: string,
    sourceScenarioSetId: string,
    runGraph: RunGraphReference | null,
    outputPrefix: string,
    numSamples: number,
    seed: number,
    device: string,
    speedInterruptionThreshold: number,
    overwrite: boolean,
  ) =>
    request<TaskResponse>(`/projects/${projectId}/tasks/generation`, {
      method: 'POST',
      ...jsonBody({
        model_id: modelId,
        checkpoint,
        scenario_set_id: scenarioSetId,
        source_scenario_set_id: sourceScenarioSetId,
        run_graph: runGraph,
        output_prefix: outputPrefix,
        num_samples: numSamples,
        seed,
        device,
        speed_interruption_threshold: speedInterruptionThreshold,
        overwrite,
      }),
    }),
  listTasks: (projectId?: string) =>
    request<Task[]>(projectId ? `/tasks?project_id=${encodeURIComponent(projectId)}` : '/tasks'),
  removeTask: (taskId: number) => request<JsonObject>(`/tasks/${taskId}`, { method: 'DELETE' }),
  getTask: (taskId: number) => request<Task>(`/tasks/${taskId}`),
  getTaskLog: (taskId: number, lines?: number) =>
    request<string>(
      `/tasks/${taskId}/log${lines == null ? '' : `?lines=${encodeURIComponent(lines)}`}`,
    ),
  cancelTask: (taskId: number) =>
    request<Task | JsonObject>(`/tasks/${taskId}/cancel`, { method: 'POST' }),
  listArtifacts: (projectId: string, scenarioSetId: string, planId: string) =>
    request<ArtifactSummary[]>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plans/${planId}/artifacts`,
    ),
  readAdjustmentPlanDetail: (projectId: string, scenarioSetId: string, planId: string) =>
    request<AdjustmentPlanDetail>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plans/${planId}/detail`,
    ),
  readCaseTimetable: (projectId: string, scenarioSetId: string, planId: string, caseId: string) =>
    request<CaseTimetableState>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/adjustment-plans/${planId}/cases/${caseId}/timetable`,
    ),
  readAdjustmentPlanSolveAnalysis: (projectId: string, scenarioSetId: string, planIds: string[]) => {
    const query = planIds
      .map((planId) => `plan_ids=${encodeURIComponent(planId)}`)
      .join('&')
    return request<AdjustmentPlanSolveAnalysis>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/analysis/adjustment-plan-solve?${query}`,
    )
  },
  readProjectAdjustmentPlanSolveAnalysis: (projectId: string, plans: AdjustmentPlanRef[]) =>
    request<AdjustmentPlanSolveAnalysis>(
      `/projects/${projectId}/analysis/adjustment-plan-solve`,
      {
        method: 'POST',
        ...jsonBody({ plans }),
      },
    ),
  readTrainingSummary: (projectId: string, modelId: string) =>
    request<JsonObject>(`/projects/${projectId}/models/${modelId}/training-summary`),
  readModelDetail: (projectId: string, modelId: string) =>
    request<ModelDetail>(`/projects/${projectId}/models/${modelId}/detail`),
  listModelFiles: (projectId: string, modelId: string) =>
    request<ModelCheckpoint[]>(`/projects/${projectId}/models/${modelId}/files`),
  deleteModel: (projectId: string, modelId: string) =>
    request<JsonObject>(`/projects/${projectId}/models/${modelId}`, {
      method: 'DELETE',
    }),
}
