import type {
  ArtifactSummary,
  CaseTimetableState,
  DatasetDetail,
  DatasetSolveAnalysis,
  JsonObject,
  ModelCheckpoint,
  ModelDetail,
  ProjectState,
  ProjectSummary,
  ResourceOption,
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
  listProjectOptions: (query = '', limit = 50) => {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    })
    return request<ResourceOption[]>(`/project-options?${params}`)
  },
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
  readScenarioOptions: (projectId: string, scenarioSetId: string, scenarioId: string) =>
    request<ScenarioOptions>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}/options`,
    ),
  createScenarioCase: (
    projectId: string,
    scenarioSetId: string,
    scenarioId: string,
    timetableFile: File,
    mileageFile: File,
    overwrite = false,
  ) => {
    const params = new URLSearchParams({ scenario_id: scenarioId, overwrite: String(overwrite) })
    const data = new FormData()
    data.append('timetable_file', timetableFile)
    data.append('mileage_file', mileageFile)
    return request<ScenarioSummary>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/upload?${params}`,
      { method: 'POST', body: data },
    )
  },
  activateScenarioCase: (
    projectId: string,
    scenarioSetId: string,
    scenarioId: string,
    timetableFile?: File | null,
    mileageFile?: File | null,
  ) => {
    const data = new FormData()
    if (timetableFile) data.append('timetable_file', timetableFile)
    if (mileageFile) data.append('mileage_file', mileageFile)
    return request<ScenarioDetail>(
      `/projects/${projectId}/scenario-sets/${scenarioSetId}/scenarios/${scenarioId}/activate`,
      { method: 'POST', body: data },
    )
  },
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
  submitNormalGenerate: (projectId: string, payload: object) =>
    request<TaskResponse>(`/projects/${projectId}/tasks/normal-generate`, {
      method: 'POST',
      ...jsonBody(payload),
    }),
  submitNormalGenerateUpload: (
    projectId: string,
    payload: {
      scenarioSetId: string
      scenarioIdPrefix: string
      simulationCount: number
      seed: number
      delayCount: number
      speedCount: number
      interruptionCount: number
      comboPerType: number
      overwrite: boolean
      timetableFile: File
      mileageFile: File
    },
  ) => {
    const params = new URLSearchParams({
      scenario_set_id: payload.scenarioSetId,
      scenario_id_prefix: payload.scenarioIdPrefix,
      simulation_count: String(payload.simulationCount),
      seed: String(payload.seed),
      delay_count: String(payload.delayCount),
      speed_count: String(payload.speedCount),
      interruption_count: String(payload.interruptionCount),
      combo_per_type: String(payload.comboPerType),
      overwrite: String(payload.overwrite),
    })
    const data = new FormData()
    data.append('timetable_file', payload.timetableFile)
    data.append('mileage_file', payload.mileageFile)
    return request<TaskResponse>(`/projects/${projectId}/tasks/normal-generate-upload?${params}`, {
      method: 'POST',
      body: data,
    })
  },
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
    sourceScenarioSetId: string,
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
        output_prefix: outputPrefix,
        num_samples: numSamples,
        seed,
        device,
        speed_interruption_threshold: speedInterruptionThreshold,
        overwrite,
      }),
    }),
  submitGenerationUpload: (
    projectId: string,
    payload: {
      modelId: string
      checkpoint: string
      scenarioSetId: string
      outputPrefix: string
      numSamples: number
      seed: number
      device: string
      speedInterruptionThreshold: number
      overwrite: boolean
      timetableFile: File
      mileageFile: File
    },
  ) => {
    const params = new URLSearchParams({
      model_id: payload.modelId,
      checkpoint: payload.checkpoint,
      scenario_set_id: payload.scenarioSetId,
      output_prefix: payload.outputPrefix,
      num_samples: String(payload.numSamples),
      seed: String(payload.seed),
      device: payload.device,
      speed_interruption_threshold: String(payload.speedInterruptionThreshold),
      overwrite: String(payload.overwrite),
    })
    const data = new FormData()
    data.append('timetable_file', payload.timetableFile)
    data.append('mileage_file', payload.mileageFile)
    return request<TaskResponse>(`/projects/${projectId}/tasks/generation-upload?${params}`, {
      method: 'POST',
      body: data,
    })
  },
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
  readDatasetDetail: (projectId: string, datasetId: string) =>
    request<DatasetDetail>(`/projects/${projectId}/datasets/${datasetId}/detail`),
  readCaseTimetable: (projectId: string, datasetId: string, caseId: string) =>
    request<CaseTimetableState>(
      `/projects/${projectId}/datasets/${datasetId}/cases/${caseId}/timetable`,
    ),
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
