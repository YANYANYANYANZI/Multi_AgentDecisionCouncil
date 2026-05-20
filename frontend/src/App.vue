<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import ChatTimeline from './components/ChatTimeline.vue'
import ComposerDock from './components/ComposerDock.vue'
import SidebarPanel from './components/SidebarPanel.vue'
import { councilApi } from './composables/api'
import type { BootstrapPayload, PendingRound, RuntimeConfig, SessionSnapshot } from './types'

const bootstrap = ref<BootstrapPayload | null>(null)
const session = ref<SessionSnapshot | null>(null)
const config = reactive<RuntimeConfig>({
  project_name: '未命名议题',
  preset_prompt: '优先输出高信息密度结论，避免空泛建议。',
  deepseek_api_key: '',
  ark_api_key: '',
  summary_model: '',
  team_name: 'mvp_hacker_team',
  agents: {
    S: { enabled: true, model: '', skill_id: '', prompt: '' },
    A: { enabled: true, model: '', skill_id: '', prompt: '' },
    B: { enabled: true, model: '', skill_id: '', prompt: '' },
    C: { enabled: true, model: '', skill_id: '', prompt: '' },
  },
  uploaded_docs: [],
})
const loading = ref(false)
const errorMessage = ref('')
const exportText = ref('')
const savedSessions = ref<string[]>([])
const pendingRound = ref<PendingRound | null>(null)
const theme = ref<'light' | 'dark'>('dark')
const roundState = ref<'idle' | 'running' | 'paused'>('idle')
const streamController = ref<AbortController | null>(null)
const suppressAbortError = ref(false)

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

  const summaryModel = config.summary_model.trim()
  if (summaryModel) {
    if (summaryModel.startsWith('deepseek') && deepseekMissing) {
      warnings.push(`总结模型 ${summaryModel} 需要 DeepSeek API Key。`)
    }
    if (!summaryModel.startsWith('deepseek') && arkMissing) {
      warnings.push(`总结模型 ${summaryModel} 需要 Ark API Key。`)
    }
  }

  return warnings
})

function snapshotConfig(): RuntimeConfig {
  return JSON.parse(JSON.stringify(config)) as RuntimeConfig
}

function applyDefaults(
  payload: BootstrapPayload,
  options: { preserveRuntime?: boolean } = {},
) {
  const preserved = options.preserveRuntime
    ? {
        projectName: config.project_name,
        deepseekApiKey: config.deepseek_api_key,
        arkApiKey: config.ark_api_key,
        uploadedDocs: [...config.uploaded_docs],
      }
    : null
  bootstrap.value = payload
  session.value = payload.session
  Object.assign(config, JSON.parse(JSON.stringify(payload.defaults)))
  if (preserved) {
    config.project_name = preserved.projectName
    config.deepseek_api_key = preserved.deepseekApiKey
    config.ark_api_key = preserved.arkApiKey
    config.uploaded_docs = preserved.uploadedDocs
  }
  if (!config.summary_model && payload.available_models.length) {
    config.summary_model = payload.available_models[0].id
  }
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

async function refreshSavedSessions() {
  try {
    const response = await councilApi.listSavedSessions()
    savedSessions.value = response.files
  } catch (error) {
    console.error(error)
  }
}

async function loadBootstrap(teamName?: string, preserveRuntime = false) {
  loading.value = true
  errorMessage.value = ''
  try {
    const payload = await councilApi.bootstrap(teamName)
    applyDefaults(payload, { preserveRuntime })
    await refreshSavedSessions()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '初始化失败'
  } finally {
    loading.value = false
  }
}

async function changeTeam(teamName: string) {
  if (roundState.value !== 'idle') {
    errorMessage.value = '请先终止或完成当前轮次，再切换团队。'
    return
  }
  config.team_name = teamName
  await loadBootstrap(teamName, true)
}

function createPendingRound(prompt: string) {
  const activeAgents = (['S', 'A', 'B', 'C'] as const).filter((agentId) => config.agents[agentId].enabled)
  const labelFor = (agentId: 'S' | 'A' | 'B' | 'C') => {
    const model = bootstrap.value?.models.find((item) => item.id === config.agents[agentId].model)
    return model?.label ? `${model.label} · ${model.provider}` : '未配置模型'
  }
  return {
    human_input: prompt,
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
        pendingRound.value.status = 'streaming'
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
          target.error = undefined
        }
        appendPendingEvent(`${agentDisplayName(payload.agent)} 已完成`)
        return
      }
      if (event === 'agent_failed') {
        const target = pendingRound.value.agent_messages.find((item) => item.agent === payload.agent)
        if (target) {
          target.status = 'error'
          target.error = payload.detail || '执行失败'
          target.content = ''
          target.reasoning = ''
        }
        pendingRound.value.status = 'error'
        roundState.value = 'idle'
        appendPendingEvent(`${agentDisplayName(payload.agent)} 失败：${payload.detail || '执行失败'}`)
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
          session.value = { ...session.value, summary: payload.summary }
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
        pendingRound.value = null
        roundState.value = 'idle'
        return
      }
      if (event === 'round_failed') {
        errorMessage.value = payload.detail || '流式执行失败'
        pendingRound.value.status = 'error'
        pendingRound.value.agent_messages = pendingRound.value.agent_messages.map((item) => {
          if (item.status === 'done' || item.status === 'error') return item
          return { ...item, status: 'error', error: payload.detail || '流式执行失败' }
        })
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
      if (pendingRound.value) {
        pendingRound.value.status = 'error'
        appendPendingEvent(`执行失败：${errorMessage.value}`)
      }
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
    councilApi.streamRound(session.value!.session_id, prompt, snapshotConfig(), 'manual', {
      ...buildStreamHandlers(),
      signal: controller.signal,
    }),
  )
}

async function autoRound(prompt: string) {
  if (!session.value) return
  errorMessage.value = ''
  if (roundState.value === 'idle') {
    startPendingRound(prompt)
    await runRoundRequest((controller) =>
      councilApi.streamRound(session.value!.session_id, prompt, snapshotConfig(), 'auto', {
        ...buildStreamHandlers(),
        signal: controller.signal,
      }),
    )
    return
  }
  if (roundState.value === 'paused') {
    pendingRound.value!.status = 'streaming'
    roundState.value = 'running'
    await runRoundRequest((controller) =>
      councilApi.continueRound(session.value!.session_id, 'auto', {
        ...buildStreamHandlers(),
        signal: controller.signal,
      }),
    )
  }
}

async function continueRound() {
  if (!session.value || roundState.value !== 'paused') return
  errorMessage.value = ''
  pendingRound.value!.status = 'streaming'
  roundState.value = 'running'
  await runRoundRequest((controller) =>
    councilApi.continueRound(session.value!.session_id, 'manual', {
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

async function attachFiles(files: File[]) {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await councilApi.parseFiles(files)
    config.uploaded_docs = [...config.uploaded_docs, ...response.files]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '文件解析失败'
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
    exportText.value = `${bundle.markdown}\n\n## Mermaid 架构图\n\n\`\`\`mermaid\n${bundle.mermaid}\n\`\`\``
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  } finally {
    loading.value = false
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
    config.project_name = response.session.project_name
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
    if (fileName === savedSessions.value[0]) {
      exportText.value = ''
    }
    await refreshSavedSessions()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除失败'
  }
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

watch(theme, (value) => {
  document.documentElement.dataset.theme = value
})

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
      @change-team="changeTeam"
      @refresh-models="refreshModels"
      @create-session="createSession"
      @save-session="saveSession"
      @load-session="loadSession"
      @delete-session="deleteSession"
      @toggle-theme="toggleTheme"
    />

    <main class="app-main">
      <template v-if="bootstrap && session">
        <div class="chat-viewport">
          <ChatTimeline
            :project-name="config.project_name"
            :rounds="session.rounds"
            :summary="session.summary"
            :agent-specs="bootstrap.agent_specs"
            :uploaded-docs="config.uploaded_docs"
            :loading="loading"
            :pending-round="pendingRound"
          />
        </div>

        <div class="composer-container">
          <ComposerDock
            :config="config"
            :models="bootstrap.available_models.length ? bootstrap.available_models : bootstrap.models"
            :interventions="bootstrap.interventions"
            :is-busy="loading"
            :round-state="roundState"
            @send="sendPrompt"
            @continue-round="continueRound"
            @auto-round="autoRound"
            @terminate-round="terminateRound"
            @attach-files="attachFiles"
            @export-markdown="exportMarkdown"
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
              <textarea class="export-textarea" :value="exportText" readonly></textarea>
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

.warning-toast .icon {
  background: rgba(246, 199, 111, 0.16);
}

.error-toast {
  background: rgba(255, 107, 122, 0.14);
  color: var(--danger);
}

.error-toast .icon {
  background: rgba(255, 107, 122, 0.16);
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

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 20px;
  border-bottom: 1px solid var(--panel-border);
}

.modal-body {
  flex: 1;
  min-height: 0;
}

.export-textarea {
  width: 100%;
  height: 100%;
  border: 0;
  padding: 18px 20px;
  resize: none;
  background: transparent;
  color: var(--text-main);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  line-height: 1.6;
  outline: none;
}

.close-btn {
  width: 34px;
  height: 34px;
  border-radius: 999px;
  border: 1px solid var(--panel-border);
  background: rgba(255, 255, 255, 0.055);
  color: var(--text-main);
}

.fade-enter-active,
.fade-leave-active,
.toast-enter-active,
.toast-leave-active {
  transition: all 0.24s ease;
}

.fade-enter-from,
.fade-leave-to,
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

@media (max-width: 960px) {
  .global-notifications {
    left: 16px;
    right: 16px;
    top: 16px;
    max-width: none;
  }

  .export-overlay {
    padding: 16px;
  }

  .export-modal {
    height: min(82vh, 760px);
  }
}
</style>
