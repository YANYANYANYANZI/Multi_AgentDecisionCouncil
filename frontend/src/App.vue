<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import ChatTimeline from './components/ChatTimeline.vue'
import ComposerDock from './components/ComposerDock.vue'
import SidebarPanel from './components/SidebarPanel.vue'
import { councilApi } from './composables/api'
import type {
  BootstrapPayload,
  DecisionMemory,
  PendingRound,
  RoundMode,
  RuntimeConfig,
  SessionSnapshot,
  TaskBrief,
  WorkspaceDocument,
  WorkspaceState,
  WorkspaceSummary,
} from './types'

function emptyTaskBrief(): TaskBrief {
  return {
    objective: '',
    background: '',
    task_type: 'general',
    budget_limit: '',
    time_limit: '',
    existing_assets: '',
    constraints: '',
    success_metric: '',
    failure_criteria: '',
    expected_output: '',
  }
}

function emptyDecisionMemory(): DecisionMemory {
  return {
    round_summary: '',
    decisions: [],
    rejected_options: [],
    open_questions: [],
    next_actions: [],
    active_constraints: [],
    updated_at: '',
  }
}

const bootstrap = ref<BootstrapPayload | null>(null)
const session = ref<SessionSnapshot | null>(null)
const workspaces = ref<WorkspaceSummary[]>([])
const documents = ref<WorkspaceDocument[]>([])
const activeDocumentId = ref('')
const activeDocument = ref<WorkspaceDocument | null>(null)
const pendingRound = ref<PendingRound | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const exportText = ref('')
const savedSessions = ref<string[]>([])
const theme = ref<'light' | 'dark'>('dark')
const roundState = ref<'idle' | 'running' | 'paused'>('idle')
const streamController = ref<AbortController | null>(null)
const suppressAbortError = ref(false)

const config = reactive<RuntimeConfig>({
  project_name: '默认工作区',
  preset_prompt: '',
  global_constraint: '',
  constraint_prompt: '',
  judge_rubric: '',
  project_prompt: '',
  judge_prompt: '',
  output_protocol_prompt: '',
  workspace_id: '',
  workspace_name: '',
  deepseek_api_key: '',
  ark_api_key: '',
  summary_model: '',
  team_name: 'mvp_hacker_team',
  task_brief: emptyTaskBrief(),
  selected_documents: [],
  selected_documents_context: '',
  compact_context: '',
  auto_mode: true,
  auto_compress_enabled: true,
  auto_compress_turn_threshold: 6,
  auto_compress_char_threshold: 20000,
  keep_recent_turns: 3,
  round_mode: 'auto',
  enable_judge: true,
  summary_enabled: true,
  decision_memory: emptyDecisionMemory(),
  agents: {
    S: { enabled: true, model: '', skill_id: '', prompt: '' },
    A: { enabled: true, model: '', skill_id: '', prompt: '' },
    B: { enabled: true, model: '', skill_id: '', prompt: '' },
    C: { enabled: true, model: '', skill_id: '', prompt: '' },
  },
  uploaded_docs: [],
})

const configurationWarnings = computed(() => {
  const warnings: string[] = []
  const deepseekMissing = !config.deepseek_api_key.trim()
  const arkMissing = !config.ark_api_key.trim()

  for (const [agentId, agentConfig] of Object.entries(config.agents)) {
    if (!agentConfig.enabled) continue
    if (agentConfig.model.startsWith('deepseek') && deepseekMissing) {
      warnings.push(`Agent ${agentId} 当前选择 ${agentConfig.model}，但未填写 DeepSeek API Key。`)
    }
    if (!agentConfig.model.startsWith('deepseek') && arkMissing) {
      warnings.push(`Agent ${agentId} 当前选择 ${agentConfig.model}，但未填写 Ark API Key。`)
    }
  }
  return warnings
})

const selectedDocumentsContext = computed(() => {
  return documents.value
    .filter((doc) => config.selected_documents.includes(doc.doc_id))
    .map((doc) => `文档：${doc.name}\n内容摘录：\n${(doc.content || '').slice(0, 2400)}`)
    .join('\n\n')
})

const activeWorkspaceLabel = computed(() => config.workspace_name || '未命名工作区')

function snapshotConfig(): RuntimeConfig {
  const payload = JSON.parse(JSON.stringify(config)) as RuntimeConfig
  payload.constraint_prompt = payload.global_constraint
  payload.judge_prompt = payload.judge_rubric
  payload.selected_documents_context = selectedDocumentsContext.value
  return payload
}

function applyTheme(value: 'light' | 'dark') {
  theme.value = value
  document.documentElement.dataset.theme = value
  window.localStorage.setItem('council-theme', value)
}

function initTheme() {
  const stored = window.localStorage.getItem('council-theme')
  if (stored === 'light' || stored === 'dark') {
    applyTheme(stored)
    return
  }
  const preferredDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  applyTheme(preferredDark ? 'dark' : 'light')
}

function applyWorkspaceToConfig(workspace: WorkspaceState) {
  config.workspace_id = workspace.workspace_id
  config.workspace_name = workspace.workspace_name
  config.project_name = workspace.workspace_name
  config.task_brief = { ...emptyTaskBrief(), ...workspace.task_brief }
  config.global_constraint = workspace.global_constraint || workspace.constraint_prompt || ''
  config.constraint_prompt = workspace.constraint_prompt || ''
  config.judge_rubric = workspace.judge_rubric || workspace.judge_prompt || ''
  config.project_prompt = workspace.project_prompt || ''
  config.preset_prompt = workspace.preset_prompt || ''
  config.judge_prompt = workspace.judge_prompt || ''
  config.output_protocol_prompt = workspace.output_protocol_prompt || ''
  config.compact_context = workspace.compact_context || ''
  config.auto_mode = workspace.auto_mode ?? true
  config.auto_compress_enabled = workspace.auto_compress_enabled ?? true
  config.auto_compress_turn_threshold = workspace.auto_compress_turn_threshold || 6
  config.auto_compress_char_threshold = workspace.auto_compress_char_threshold || 20000
  config.keep_recent_turns = workspace.keep_recent_turns || 3
  config.team_name = workspace.selected_team || config.team_name
  config.selected_documents = [...(workspace.selected_documents || [])]
  config.round_mode = workspace.round_mode || 'auto'
  config.enable_judge = workspace.enable_judge ?? true
  config.summary_enabled = workspace.summary_enabled ?? true
  config.decision_memory = { ...emptyDecisionMemory(), ...workspace.decision_memory }
  for (const agentId of ['S', 'A', 'B', 'C'] as const) {
    if (workspace.selected_skills?.[agentId]) {
      config.agents[agentId].skill_id = workspace.selected_skills[agentId]
    }
    if (workspace.prompt_overrides?.[agentId] !== undefined) {
      config.agents[agentId].prompt = workspace.prompt_overrides[agentId]
    }
  }
}

function applyRuntimeConfig(runtimeConfig: Partial<RuntimeConfig>) {
  if (!runtimeConfig) return
  Object.assign(config, {
    ...config,
    ...runtimeConfig,
    task_brief: { ...config.task_brief, ...(runtimeConfig.task_brief || {}) },
    decision_memory: { ...config.decision_memory, ...(runtimeConfig.decision_memory || {}) },
    agents: {
      ...config.agents,
      ...(runtimeConfig.agents || {}),
    },
  })
}

function applyDefaults(payload: BootstrapPayload) {
  bootstrap.value = payload
  session.value = payload.session
  workspaces.value = payload.workspaces
  documents.value = payload.documents
  Object.assign(config, JSON.parse(JSON.stringify(payload.defaults)))
  applyWorkspaceToConfig(payload.workspace)
  if (!config.summary_model && payload.available_models.length) {
    config.summary_model = payload.available_models[0].id
  }
}

async function refreshSavedSessions() {
  try {
    const response = await councilApi.listSavedSessions()
    savedSessions.value = response.files
  } catch (error) {
    console.error(error)
  }
}

async function refreshWorkspaceList() {
  const response = await councilApi.listWorkspaces()
  workspaces.value = response.workspaces
}

async function loadWorkspace(workspaceId: string) {
  loading.value = true
  errorMessage.value = ''
  try {
    const [workspaceResponse, documentResponse] = await Promise.all([
      councilApi.getWorkspace(workspaceId),
      councilApi.listWorkspaceDocuments(workspaceId),
    ])
    applyWorkspaceToConfig(workspaceResponse.workspace)
    config.project_name = workspaceResponse.workspace.workspace_name
    documents.value = documentResponse.documents
    if (documents.value.length) {
      await openDocument(documents.value[0].doc_id)
    } else {
      activeDocumentId.value = ''
      activeDocument.value = null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工作区加载失败'
  } finally {
    loading.value = false
  }
}

async function loadBootstrap(teamName?: string) {
  loading.value = true
  errorMessage.value = ''
  try {
    const payload = await councilApi.bootstrap(teamName)
    applyDefaults(payload)
    if (documents.value.length) {
      await openDocument(documents.value[0].doc_id)
    }
    await refreshSavedSessions()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '初始化失败'
  } finally {
    loading.value = false
  }
}

async function changeTeam(teamName: string) {
  if (roundState.value !== 'idle') {
    errorMessage.value = '请先完成当前轮次，再切换团队。'
    return
  }
  config.team_name = teamName
  if (bootstrap.value) {
    const payload = await councilApi.bootstrap(teamName)
    bootstrap.value = payload
    workspaces.value = payload.workspaces
  }
}

function createPendingRound(prompt: string) {
  const activeAgents = (['S', 'A', 'B', 'C'] as const).filter((agentId) => config.agents[agentId].enabled)
  const labelFor = (agentId: 'S' | 'A' | 'B' | 'C') => {
    const model = bootstrap.value?.models.find((item) => item.id === config.agents[agentId].model)
    return model?.label ? `${model.label} · ${model.provider}` : '未配置模型'
  }
  return {
    human_input: prompt,
    workspace_id: config.workspace_id,
    workspace_name: config.workspace_name,
    round_mode: config.round_mode,
    auto_mode: config.auto_mode,
    enable_judge: config.enable_judge,
    active_agents: activeAgents,
    active_agent_models: {
      S: labelFor('S'),
      A: labelFor('A'),
      B: labelFor('B'),
      C: labelFor('C'),
    },
    agent_messages: activeAgents.map((agent) => ({
      agent,
      content: '',
      reasoning: '',
      status: 'pending' as const,
    })),
    judge_message: config.enable_judge
      ? {
          agent: 'JUDGE' as const,
          content: '',
          reasoning: '',
          status: 'pending' as const,
        }
      : null,
    decision_memory: config.decision_memory,
    status: 'streaming' as const,
    events: ['会话已发送，等待调度器分发任务'],
  }
}

function startPendingRound(prompt: string) {
  pendingRound.value = createPendingRound(prompt)
  roundState.value = 'running'
}

function appendPendingEvent(message: string) {
  if (!pendingRound.value) return
  pendingRound.value.events = [...pendingRound.value.events, message].slice(-12)
}

function agentDisplayName(agentId: string) {
  if (!bootstrap.value) return agentId
  if (agentId === 'JUDGE') return 'Judge · 裁判收敛'
  const key = agentId as 'S' | 'A' | 'B' | 'C'
  return bootstrap.value.agent_specs[key]?.display_name || agentId
}

function buildStreamHandlers() {
  return {
    onEvent(event: string, payload: any) {
      if (!pendingRound.value) return
      if (event === 'round_started') {
        appendPendingEvent('调度完成，开始按顺序执行 Agent')
        return
      }
      if (event === 'round_resumed') {
        appendPendingEvent(`继续执行${payload.next_agent?.display_name ? `：${payload.next_agent.display_name}` : ''}`)
        return
      }
      if (event === 'agent_started') {
        roundState.value = 'running'
        const target = pendingRound.value.agent_messages.find((item) => item.agent === payload.agent)
        if (target) target.status = 'streaming'
        appendPendingEvent(`${payload.display_name} 开始输出`)
        return
      }
      if (event === 'agent_delta') {
        const target = pendingRound.value.agent_messages.find((item) => item.agent === payload.agent)
        if (target) {
          if (payload.channel === 'reasoning') {
            target.reasoning = (target.reasoning || '') + payload.delta
          } else {
            target.content += payload.delta
          }
          target.status = 'streaming'
        }
        return
      }
      if (event === 'agent_completed') {
        const target = pendingRound.value.agent_messages.find((item) => item.agent === payload.agent)
        if (target) {
          target.content = payload.content
          target.reasoning = payload.reasoning || target.reasoning || ''
          target.status = 'done'
        }
        appendPendingEvent(`${agentDisplayName(payload.agent)} 已完成`)
        return
      }
      if (event === 'judge_started') {
        if (pendingRound.value.judge_message) {
          pendingRound.value.judge_message.status = 'streaming'
        }
        appendPendingEvent('Judge 开始裁判收敛')
        return
      }
      if (event === 'judge_completed') {
        if (pendingRound.value.judge_message) {
          pendingRound.value.judge_message.content = payload.content
          pendingRound.value.judge_message.status = 'done'
        }
        pendingRound.value.decision_memory = payload.decision_memory
        config.decision_memory = payload.decision_memory
        appendPendingEvent('Judge 已完成收敛')
        return
      }
      if (event === 'judge_failed') {
        if (pendingRound.value.judge_message) {
          pendingRound.value.judge_message.status = 'error'
          pendingRound.value.judge_message.error = payload.detail || 'Judge 失败'
        }
        appendPendingEvent(`Judge 失败：${payload.detail || '未知错误'}`)
        return
      }
      if (event === 'round_paused') {
        pendingRound.value.status = 'paused'
        roundState.value = 'paused'
        appendPendingEvent(`等待人工审批，下一位：${payload.next_agent?.display_name || '无'}`)
        return
      }
      if (event === 'summary_updated') {
        if (session.value) {
          session.value = { ...session.value, summary: payload.summary, compact_context: payload.compact_context || session.value.compact_context }
        }
        if (payload.compact_context) {
          config.compact_context = payload.compact_context
        }
        appendPendingEvent('长期摘要已更新')
        return
      }
      if (event === 'summary_failed') {
        appendPendingEvent(`摘要更新失败：${payload.detail || '未知错误'}`)
        return
      }
      if (event === 'round_completed') {
        session.value = payload.session
        if (payload.session?.decision_memory) {
          config.decision_memory = payload.session.decision_memory
        }
        if (payload.session?.compact_context) {
          config.compact_context = payload.session.compact_context
        }
        pendingRound.value = null
        roundState.value = 'idle'
        return
      }
      if (event === 'agent_failed' || event === 'round_failed') {
        errorMessage.value = payload.detail || '流式执行失败'
        pendingRound.value.status = 'error'
        roundState.value = 'idle'
        appendPendingEvent(`执行中断：${errorMessage.value}`)
      }
    },
  }
}

async function runRoundRequest(task: (controller: AbortController) => Promise<void>) {
  const controller = new AbortController()
  streamController.value = controller
  loading.value = true
  try {
    await task(controller)
  } catch (error) {
    const isAbort = error instanceof DOMException && error.name === 'AbortError'
    if (!isAbort || !suppressAbortError.value) {
      errorMessage.value = error instanceof Error ? error.message : '发送失败'
      roundState.value = 'idle'
    }
  } finally {
    suppressAbortError.value = false
    if (streamController.value === controller) {
      streamController.value = null
    }
    loading.value = false
  }
}

async function sendPrompt(prompt: string) {
  if (!session.value) return
  errorMessage.value = ''
  startPendingRound(prompt)
  await runRoundRequest((controller) =>
    councilApi.streamRound(session.value!.session_id, prompt, snapshotConfig(), config.auto_mode ? 'auto' : 'manual', {
      ...buildStreamHandlers(),
      signal: controller.signal,
    }),
  )
}

async function continueRound() {
  if (!session.value || roundState.value !== 'paused') return
  errorMessage.value = ''
  pendingRound.value!.status = 'streaming'
  roundState.value = 'running'
  await runRoundRequest((controller) =>
    councilApi.continueRound(session.value!.session_id, config.auto_mode ? 'auto' : 'manual', {
      ...buildStreamHandlers(),
      signal: controller.signal,
    }),
  )
}

async function terminateRound() {
  if (!session.value || roundState.value === 'idle') return
  suppressAbortError.value = true
  streamController.value?.abort()
  try {
    await councilApi.terminateRound(session.value.session_id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '终止失败'
  } finally {
    pendingRound.value = null
    roundState.value = 'idle'
    loading.value = false
    streamController.value = null
  }
}

async function refreshModels() {
  errorMessage.value = ''
  try {
    const response = await councilApi.probeModels({
      deepseek_api_key: config.deepseek_api_key,
      ark_api_key: config.ark_api_key,
    })
    if (bootstrap.value) {
      bootstrap.value.availability = response.availability
      bootstrap.value.available_models = bootstrap.value.models.filter((model) => response.availability[model.id])
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '模型探测失败'
  }
}

async function createSession() {
  loading.value = true
  errorMessage.value = ''
  pendingRound.value = null
  roundState.value = 'idle'
  try {
    const response = await councilApi.createSession(config.project_name)
    session.value = response.session
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '新建会话失败'
  } finally {
    loading.value = false
  }
}

async function saveSession() {
  if (!session.value) return
  try {
    await saveWorkspace()
    await councilApi.saveSession(session.value.session_id, config.project_name)
    await refreshSavedSessions()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  }
}

async function loadSession(fileName: string) {
  loading.value = true
  errorMessage.value = ''
  pendingRound.value = null
  roundState.value = 'idle'
  try {
    const response = await councilApi.loadSession(fileName)
    session.value = response.session
    if (response.session.runtime_config) {
      applyRuntimeConfig(response.session.runtime_config)
    }
    if (response.session.workspace_id) {
      await loadWorkspace(response.session.workspace_id)
    }
    if (response.session.decision_memory) {
      config.decision_memory = response.session.decision_memory
    }
    if (response.session.compact_context) {
      config.compact_context = response.session.compact_context
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function deleteSession(fileName: string) {
  if (!window.confirm(`删除存档 ${fileName}？`)) return
  try {
    await councilApi.deleteSavedSession(fileName)
    await refreshSavedSessions()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除失败'
  }
}

async function saveWorkspace() {
  if (!config.workspace_id) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await councilApi.updateWorkspace(config.workspace_id, {
      workspace_name: config.workspace_name,
      task_brief: config.task_brief,
      global_constraint: config.global_constraint,
      constraint_prompt: config.global_constraint,
      judge_rubric: config.judge_rubric,
      project_prompt: config.project_prompt,
      preset_prompt: config.preset_prompt,
      compact_context: config.compact_context,
      judge_prompt: config.judge_rubric,
      output_protocol_prompt: config.output_protocol_prompt,
      selected_team: config.team_name,
      selected_skills: Object.fromEntries(
        (['S', 'A', 'B', 'C'] as const).map((agentId) => [agentId, config.agents[agentId].skill_id]),
      ),
      prompt_overrides: Object.fromEntries(
        (['S', 'A', 'B', 'C'] as const).map((agentId) => [agentId, config.agents[agentId].prompt]),
      ),
      selected_documents: config.selected_documents,
      round_mode: config.round_mode,
      auto_mode: config.auto_mode,
      auto_compress_enabled: config.auto_compress_enabled,
      auto_compress_turn_threshold: config.auto_compress_turn_threshold,
      auto_compress_char_threshold: config.auto_compress_char_threshold,
      keep_recent_turns: config.keep_recent_turns,
      enable_judge: config.enable_judge,
      summary_enabled: config.summary_enabled,
      decision_memory: config.decision_memory,
    })
    applyWorkspaceToConfig(response.workspace)
    await refreshWorkspaceList()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工作区保存失败'
  } finally {
    loading.value = false
  }
}

async function createWorkspace() {
  const workspaceName = window.prompt('输入工作区名称', config.workspace_name || '新工作区')
  if (!workspaceName) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await councilApi.createWorkspace({
      workspace_name: workspaceName,
      task_brief: emptyTaskBrief(),
      decision_memory: emptyDecisionMemory(),
      global_constraint: '',
      judge_rubric: config.judge_rubric,
      compact_context: '',
      round_mode: 'auto',
      auto_mode: true,
      auto_compress_enabled: true,
      auto_compress_turn_threshold: 6,
      auto_compress_char_threshold: 20000,
      keep_recent_turns: 3,
      enable_judge: true,
      summary_enabled: true,
      selected_team: config.team_name,
      selected_skills: {},
      prompt_overrides: {},
      selected_documents: [],
    })
    await refreshWorkspaceList()
    await loadWorkspace(response.workspace.workspace_id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '新建工作区失败'
  } finally {
    loading.value = false
  }
}

async function changeWorkspace(workspaceId: string) {
  if (!workspaceId || workspaceId === config.workspace_id) return
  await loadWorkspace(workspaceId)
}

async function openDocument(docId: string) {
  if (!config.workspace_id || !docId) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await councilApi.getWorkspaceDocument(config.workspace_id, docId)
    activeDocumentId.value = docId
    activeDocument.value = {
      ...response.document,
      selected: config.selected_documents.includes(docId),
    }
    documents.value = documents.value.map((doc) =>
      doc.doc_id === docId ? { ...doc, content: response.document.content, selected: config.selected_documents.includes(docId) } : doc,
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '文档加载失败'
  } finally {
    loading.value = false
  }
}

function updateActiveDocument(document: WorkspaceDocument) {
  activeDocument.value = document
}

async function saveActiveDocument() {
  if (!config.workspace_id || !activeDocument.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await councilApi.updateWorkspaceDocument(config.workspace_id, activeDocument.value.doc_id, {
      name: activeDocument.value.name,
      content: activeDocument.value.content || '',
    })
    activeDocument.value = { ...response.document, selected: config.selected_documents.includes(response.document.doc_id) }
    await refreshDocuments()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '文档保存失败'
  } finally {
    loading.value = false
  }
}

async function refreshDocuments() {
  if (!config.workspace_id) return
  const response = await councilApi.listWorkspaceDocuments(config.workspace_id)
  documents.value = response.documents
}

async function createBlankDocument() {
  if (!config.workspace_id) return
  const name = window.prompt('输入文档名称', 'notes.md')
  if (!name) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await councilApi.createWorkspaceDocument(config.workspace_id, { name, content: '' })
    await refreshDocuments()
    await openDocument(response.document.doc_id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '新建文档失败'
  } finally {
    loading.value = false
  }
}

async function deleteActiveDocument() {
  if (!config.workspace_id || !activeDocument.value) return
  if (!window.confirm(`删除文档 ${activeDocument.value.name}？`)) return
  loading.value = true
  try {
    await councilApi.deleteWorkspaceDocument(config.workspace_id, activeDocument.value.doc_id)
    config.selected_documents = config.selected_documents.filter((item) => item !== activeDocument.value?.doc_id)
    activeDocumentId.value = ''
    activeDocument.value = null
    await refreshDocuments()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '文档删除失败'
  } finally {
    loading.value = false
  }
}

async function attachFiles(files: File[]) {
  if (!config.workspace_id) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await councilApi.parseFiles(files)
    for (const file of response.files) {
      await councilApi.createWorkspaceDocument(config.workspace_id, { name: file.name, content: file.content })
    }
    await refreshDocuments()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '文件解析失败'
  } finally {
    loading.value = false
  }
}

function toggleDocumentSelection(docId: string, selected: boolean) {
  if (selected) {
    if (!config.selected_documents.includes(docId)) {
      config.selected_documents = [...config.selected_documents, docId]
    }
  } else {
    config.selected_documents = config.selected_documents.filter((item) => item !== docId)
  }
  documents.value = documents.value.map((doc) => (doc.doc_id === docId ? { ...doc, selected } : doc))
  if (activeDocument.value?.doc_id === docId) {
    activeDocument.value.selected = selected
  }
}

function setRoundMode(mode: RoundMode) {
  config.round_mode = mode
  config.auto_mode = mode === 'auto'
}

async function compressContext() {
  if (!session.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await councilApi.compressSession(session.value.session_id)
    config.compact_context = response.compact_context
    if (session.value) {
      session.value = { ...session.value, compact_context: response.compact_context, summary: response.summary }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '压缩失败'
  } finally {
    loading.value = false
  }
}

async function exportMarkdown() {
  if (!session.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const bundle = await councilApi.exportSession(session.value.session_id, snapshotConfig())
    exportText.value = `${bundle.markdown}\n\n## Mermaid\n\n\`\`\`mermaid\n${bundle.mermaid}\n\`\`\``
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  } finally {
    loading.value = false
  }
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

watch(theme, (value) => {
  document.documentElement.dataset.theme = value
})

watch(
  () => config.round_mode,
  (value) => {
    if (value !== 'auto') {
      config.auto_mode = false
    }
  },
)

watch(
  () => config.auto_mode,
  (value) => {
    if (value) {
      config.round_mode = 'auto'
    }
  },
)

onMounted(() => {
  initTheme()
  loadBootstrap()
})
</script>

<template>
  <div class="app-layout">
    <div class="global-notifications">
      <TransitionGroup name="toast">
        <div v-for="(warning, index) in configurationWarnings" :key="`warn-${index}`" class="toast warning-toast">
          <span class="icon">!</span>
          <span class="text">{{ warning }}</span>
        </div>
        <div v-if="errorMessage" class="toast error-toast">
          <span class="icon">!</span>
          <span class="text">{{ errorMessage }}</span>
        </div>
      </TransitionGroup>
    </div>

    <SidebarPanel
      v-if="bootstrap"
      class="app-sidebar"
      :config="config"
      :models="bootstrap.available_models.length ? bootstrap.available_models : bootstrap.models"
      :availability="bootstrap.availability"
      :agent-specs="bootstrap.agent_specs"
      :available-teams="bootstrap.available_teams"
      :active-team="bootstrap.active_team"
      :saved-sessions="savedSessions"
      :is-busy="loading"
      :theme="theme"
      :skills="bootstrap.skills"
      :workspaces="workspaces"
      :documents="documents"
      :active-document-id="activeDocumentId"
      :active-document="activeDocument"
      @change-team="changeTeam"
      @refresh-models="refreshModels"
      @create-session="createSession"
      @save-session="saveSession"
      @load-session="loadSession"
      @delete-session="deleteSession"
      @toggle-theme="toggleTheme"
      @create-workspace="createWorkspace"
      @change-workspace="changeWorkspace"
      @save-workspace="saveWorkspace"
      @open-document="openDocument"
      @toggle-document-selection="toggleDocumentSelection"
      @save-document="saveActiveDocument"
      @create-document="createBlankDocument"
      @delete-document="deleteActiveDocument"
      @update-active-document="updateActiveDocument"
    />

    <main class="app-main">
      <template v-if="bootstrap && session">
        <div class="chat-viewport">
          <ChatTimeline
            :project-name="activeWorkspaceLabel"
            :rounds="session.rounds"
            :summary="session.summary"
            :compact-context="config.compact_context || session.compact_context"
            :agent-specs="bootstrap.agent_specs"
            :uploaded-docs="documents"
            :loading="loading"
            :pending-round="pendingRound"
            :decision-memory="config.decision_memory"
            :round-mode="config.round_mode"
          />
        </div>

        <div class="composer-container">
          <ComposerDock
            :config="config"
            :interventions="bootstrap.interventions"
            :is-busy="loading"
            :round-state="roundState"
            @send="sendPrompt"
            @continue-round="continueRound"
            @terminate-round="terminateRound"
            @attach-files="attachFiles"
            @export-markdown="exportMarkdown"
            @set-round-mode="setRoundMode"
            @compress-context="compressContext"
          />
        </div>
      </template>

      <Transition name="fade">
        <div v-if="exportText" class="export-overlay" @click.self="exportText = ''">
          <div class="export-modal">
            <div class="modal-header">
              <h3>导出预览 (Markdown)</h3>
              <button class="close-btn" @click="exportText = ''">✕</button>
            </div>
            <div class="modal-body">
              <textarea class="export-textarea" :value="exportText" readonly />
            </div>
          </div>
        </div>
      </Transition>
    </main>
  </div>
</template>

<style scoped>
.global-notifications {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: min(420px, calc(100vw - 32px));
}

.toast {
  padding: 12px 14px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  border: 1px solid var(--panel-border);
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
}

.icon {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 800;
}

.warning-toast {
  background: rgba(246, 199, 111, 0.14);
  color: var(--warning);
}

.error-toast {
  background: rgba(255, 107, 122, 0.14);
  color: var(--danger);
}

.export-overlay {
  position: fixed;
  inset: 0;
  background: rgba(5, 8, 14, 0.72);
  backdrop-filter: blur(10px);
  display: grid;
  place-items: center;
  z-index: 2000;
  padding: 24px;
}

.export-modal {
  width: 100%;
  max-width: 900px;
  height: 80vh;
  border-radius: 22px;
  border: 1px solid var(--panel-border);
  background: var(--panel-bg-strong);
  box-shadow: var(--shadow-soft);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header,
.modal-body {
  padding: 16px;
}

.modal-body,
.export-textarea {
  flex: 1;
}

.export-textarea {
  width: 100%;
  height: 100%;
  background: transparent;
  color: inherit;
}
</style>
