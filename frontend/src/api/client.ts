import type {
  ArtifactSummary,
  CaseTimetableState,
  DatasetSolveAnalysis,
  JsonObject,
  ModelCheckpoint,
  ModelDetail,
  PlanTimetableState,
  ProjectState,
  ProjectSummary,
  ScenarioSet,
  ScenarioSetVisualization,
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
  try {
    const payload = (await response.json()) as { detail?: unknown }
    return typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
  } catch {
    return await response.text()
  }
}

function jsonBody(payload: unknown): RequestInit {
  return { body: JSON.stringify(payload) }
}

export const api = {
  health: () => request<JsonObject>('/health'),
  listProjects: () => request<ProjectSummary[]>('/projects'),
  createProject: (projectId: string) =>
    request<TaskResponse>('/projects', {
      method: 'POST',
      ...jsonBody({ project_id: projectId }),
    }),
  deleteProject: (projectId: string) =>
    request<TaskResponse>(`/projects/${projectId}`, {
      method: 'DELETE',
    }),
  getProject: (projectId: string) => request<ProjectState>(`/projects/${projectId}`),
  listScenarioSets: (projectId: string) =>
    request<ScenarioSet[]>(`/projects/${projectId}/scenario-sets`),
  createScenarioSet: (projectId: string, scenarioSetId: string, existOk = false) =>
    request<TaskResponse>(`/projects/${projectId}/scenario-sets`, {
      method: 'POST',
      ...jsonBody({ scenario_set_id: scenarioSetId, exist_ok: existOk }),
    }),
  deleteScenarioSet: (projectId: string, scenarioSetId: string) =>
    request<JsonObject>(`/projects/${projectId}/scenario-sets/${scenarioSetId}`, {
      method: 'DELETE',
    }),
  listScenarios: (projectId: string, scenarioSetId: string) =>
    request<ScenarioSummary[]>(`/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios`),
  readScenarioSetVisualization: (projectId: string, scenarioSetId: string) =>
    request<ScenarioSetVisualization>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/visualization`,
    ),
  readScenario: (projectId: string, scenarioSetId: string, scenarioId: string) =>
    request<JsonObject>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}`,
    ),
  readScenarioOptions: (projectId: string) =>
    request<ScenarioOptions>(`/projects/${projectId}/scenario-options`),
  addScenario: (
    projectId: string,
    scenarioSetId: string,
    scenarioId: string,
    payload: { delays: object[]; speed_limits: object[] },
    overwrite = false,
  ) =>
    request<TaskResponse>(`/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios`, {
      method: 'POST',
      ...jsonBody({ scenario_id: scenarioId, ...payload, overwrite }),
    }),
  deleteScenario: (projectId: string, scenarioSetId: string, scenarioId: string) =>
    request<TaskResponse>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}`,
      {
        method: 'DELETE',
      },
    ),
  activatePlan: (
    projectId: string,
    timetableFile: File,
    mileageFile: File,
    timetableSheetName: string,
    mileageSheetName: string,
  ) => {
    const data = new FormData()
    data.append('timetable_file', timetableFile)
    data.append('mileage_file', mileageFile)
    data.append('timetable_sheet_name', timetableSheetName)
    data.append('mileage_sheet_name', mileageSheetName)
    return request<TaskResponse>(`/projects/${projectId}/plan/activate`, {
      method: 'POST',
      body: data,
    })
  },
  submitPrepare: (projectId: string, payload: object) =>
    request<TaskResponse>(`/projects/${projectId}/tasks/prepare`, {
      method: 'POST',
      ...jsonBody(payload),
    }),
  submitNormalGenerate: (projectId: string, payload: object) =>
    request<TaskResponse>(`/projects/${projectId}/tasks/normal-generate`, {
      method: 'POST',
      ...jsonBody(payload),
    }),
  createDataset: (projectId: string, datasetId: string, existOk = false) =>
    request<TaskResponse>(`/projects/${projectId}/datasets`, {
      method: 'POST',
      ...jsonBody({ dataset_id: datasetId, exist_ok: existOk }),
    }),
  deleteDataset: (projectId: string, datasetId: string) =>
    request<JsonObject>(`/projects/${projectId}/datasets/${datasetId}`, {
      method: 'DELETE',
    }),
  submitBuild: (
    projectId: string,
    scenarioSetId: string,
    datasetId: string,
    scenarioId = '',
    options: object = {},
  ) =>
    request<TaskResponse>(`/projects/${projectId}/tasks/build`, {
      method: 'POST',
      ...jsonBody({
        scenario_set_id: scenarioSetId,
        dataset_id: datasetId,
        scenario_id: scenarioId,
        ...options,
      }),
    }),
  submitSolve: (
    projectId: string,
    datasetId: string,
    limit = 0,
    timeLimit?: number,
    caseId = '',
    mipGap?: number,
    threads?: number,
    skipSolved = false,
  ) =>
    request<TaskResponse>(`/projects/${projectId}/tasks/solve`, {
      method: 'POST',
      ...jsonBody({
        dataset_id: datasetId,
        case_id: caseId,
        limit,
        time_limit: timeLimit ?? null,
        mip_gap: mipGap ?? null,
        threads: threads ?? null,
        skip_solved: skipSolved,
      }),
    }),
  submitExportTimetable: (projectId: string, datasetId: string, limit = 0, caseId = '') =>
    request<TaskResponse>(`/projects/${projectId}/tasks/export-timetable`, {
      method: 'POST',
      ...jsonBody({
        dataset_id: datasetId,
        case_id: caseId,
        limit,
      }),
    }),
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
  getTaskLog: (taskId: number, lines = 120) =>
    request<string>(`/tasks/${taskId}/log?lines=${lines}`),
  cancelTask: (taskId: number) =>
    request<Task | JsonObject>(`/tasks/${taskId}/cancel`, { method: 'POST' }),
  listArtifacts: (projectId: string, datasetId: string) =>
    request<ArtifactSummary[]>(`/projects/${projectId}/datasets/${datasetId}/artifacts`),
  readCaseTimetable: (projectId: string, datasetId: string, caseId: string) =>
    request<CaseTimetableState>(
      `/projects/${projectId}/datasets/${datasetId}/cases/${caseId}/timetable`,
    ),
  readPlanTimetable: (projectId: string) =>
    request<PlanTimetableState>(`/projects/${projectId}/plan-timetable`),
  readDatasetSolveAnalysis: (projectId: string, datasetIds: string[]) => {
    const query = datasetIds
      .map((datasetId) => `dataset_ids=${encodeURIComponent(datasetId)}`)
      .join('&')
    return request<DatasetSolveAnalysis>(`/projects/${projectId}/analysis/dataset-solve?${query}`)
  },
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
