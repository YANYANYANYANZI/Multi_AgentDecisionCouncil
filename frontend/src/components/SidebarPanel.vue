<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { AgentId, AgentSpec, ModelOption, RuntimeConfig, SkillOption, WorkspaceDocument, WorkspaceSummary } from '../types'

const props = defineProps<{
  config: RuntimeConfig
  models: ModelOption[]
  availability: Record<string, boolean>
  agentSpecs: Record<'S' | 'A' | 'B' | 'C', AgentSpec>
  skills: Record<'S' | 'A' | 'B' | 'C', SkillOption[]>
  availableTeams: string[]
  activeTeam: string
  savedSessions: string[]
  isBusy: boolean
  theme: 'light' | 'dark'
  workspaces: WorkspaceSummary[]
  documents: WorkspaceDocument[]
  activeDocumentId: string
  activeDocument: WorkspaceDocument | null
}>()

const emit = defineEmits<{
  refreshModels: []
  createSession: []
  saveSession: []
  changeTeam: [teamName: string]
  loadSession: [fileName: string]
  deleteSession: [fileName: string]
  toggleTheme: []
  createWorkspace: []
  changeWorkspace: [workspaceId: string]
  saveWorkspace: []
  openDocument: [docId: string]
  toggleDocumentSelection: [docId: string, selected: boolean]
  saveDocument: []
  createDocument: []
  deleteDocument: []
  updateActiveDocument: [document: WorkspaceDocument]
}>()

const agentIds: AgentId[] = ['S', 'A', 'B', 'C']
const taskTypeOptions = ['general', 'startup_validation', 'product_design', 'engineering_review', 'research_brainstorm', 'business_plan', 'ui_review', 'personal_decision']
const advancedDetails = ref<HTMLDetailsElement | null>(null)
const agentSection = ref<HTMLElement | null>(null)
const expandedAgents = ref<Record<AgentId, boolean>>({
  S: false,
  A: false,
  B: false,
  C: false,
})

const enabledAgentCount = computed(() => agentIds.filter((agentId) => props.config.agents[agentId].enabled).length)
const currentModelLabel = computed(() => props.models.find((item) => item.id === props.config.agents.S.model)?.label || '未配置模型')

function isAgentAvailable(agentId: AgentId) {
  const agent = props.config.agents[agentId]
  return agent.enabled && Boolean(props.availability[agent.model])
}

function agentStatusText(agentId: AgentId) {
  if (!props.config.agents[agentId].enabled) return '未启用'
  return isAgentAvailable(agentId) ? '可用' : '待验证'
}

function onTeamChange(event: Event) {
  emit('changeTeam', (event.target as HTMLSelectElement).value)
}

function onWorkspaceChange(event: Event) {
  emit('changeWorkspace', (event.target as HTMLSelectElement).value)
}

function onDocumentChange(event: Event) {
  if (!props.activeDocument) return
  emit('updateActiveDocument', {
    ...props.activeDocument,
    content: (event.target as HTMLTextAreaElement).value,
  })
}

function toggleAgent(agentId: AgentId) {
  expandedAgents.value[agentId] = !expandedAgents.value[agentId]
}

async function openAgentEditor() {
  if (advancedDetails.value && !advancedDetails.value.open) {
    advancedDetails.value.open = true
  }
  await nextTick()
  agentSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <aside class="sidebar">
    <section class="sidebar-card sidebar-card-hero">
      <div class="eyebrow">Workspace</div>
      <h1>默认可用的决策工作台</h1>
      <p>首屏只保留全局约束和 Judge 标准，Agent 配置收纳到高级设置。</p>
      <div class="status-row">
        <button class="ghost-button" :disabled="isBusy" @click="emit('refreshModels')">刷新模型</button>
        <button class="theme-button" type="button" @click="emit('toggleTheme')">
          {{ theme === 'dark' ? '浅色' : '深色' }}
        </button>
      </div>
    </section>

    <section class="sidebar-card">
      <div class="section-header">
        <h2>Workspace</h2>
      </div>
      <label>
        <span>当前工作区</span>
        <select :value="config.workspace_id" @change="onWorkspaceChange">
          <option v-for="workspace in workspaces" :key="workspace.workspace_id" :value="workspace.workspace_id">
            {{ workspace.workspace_name }}
          </option>
        </select>
      </label>
      <label>
        <span>工作区名称</span>
        <input v-model="config.workspace_name" type="text" placeholder="默认工作区" />
      </label>
      <div class="project-actions-row">
        <button class="primary-button project-action-button" :disabled="isBusy" @click="emit('createWorkspace')">新建</button>
        <button class="ghost-button project-action-button" :disabled="isBusy" @click="emit('saveWorkspace')">保存</button>
      </div>
    </section>

    <section class="sidebar-card">
      <div class="section-header">
        <h2>Core Protocol</h2>
      </div>
      <label>
        <span>项目全局约束</span>
        <textarea
          v-model="config.global_constraint"
          rows="7"
          placeholder="写入项目预算、时间、禁止事项、已有资源、输出边界。所有 Agent 必须遵守。"
        />
      </label>
      <label>
        <span>Judge 判断标准</span>
        <textarea
          v-model="config.judge_rubric"
          rows="7"
          placeholder="写入 Judge 如何判断方案是否跑偏、超预算、违反约束、是否需要砍掉。"
        />
      </label>
    </section>

    <section class="sidebar-card">
      <div class="section-header">
        <h2>智能默认配置</h2>
        <button class="ghost-button" type="button" @click="openAgentEditor">编辑 Agent</button>
      </div>
      <div class="trace-list">
        <div class="trace-item">团队：{{ config.team_name || activeTeam }}</div>
        <div class="trace-item">模型：{{ currentModelLabel }}</div>
        <div class="trace-item">Judge：{{ config.enable_judge ? '已启用' : '已关闭' }}</div>
        <div class="trace-item">自动模式：{{ config.auto_mode ? '已启用' : '已关闭' }}</div>
        <div class="trace-item">Agent：已启用 {{ enabledAgentCount }}/4</div>
      </div>
    </section>

    <details ref="advancedDetails" class="sidebar-card sidebar-details">
      <summary class="details-summary">
        <span>高级设置</span>
        <span>默认折叠</span>
      </summary>
      <div class="details-body">
        <label>
          <span>团队</span>
          <select :value="activeTeam" @change="onTeamChange">
            <option v-for="teamName in availableTeams" :key="teamName" :value="teamName">{{ teamName }}</option>
          </select>
        </label>
        <label>
          <span>Task Type</span>
          <select v-model="config.task_brief.task_type">
            <option v-for="option in taskTypeOptions" :key="option" :value="option">{{ option }}</option>
          </select>
        </label>
        <label>
          <span>Round Mode</span>
          <select v-model="config.round_mode">
            <option value="auto">auto</option>
            <option value="converge">converge</option>
            <option value="critique">critique</option>
            <option value="execute">execute</option>
            <option value="diverge">diverge</option>
          </select>
        </label>
        <label class="toggle-row">
          <span>自动压缩</span>
          <input v-model="config.auto_compress_enabled" type="checkbox" />
        </label>
        <label>
          <span>压缩轮次阈值</span>
          <input v-model.number="config.auto_compress_turn_threshold" type="number" min="1" />
        </label>
        <label>
          <span>压缩字符阈值</span>
          <input v-model.number="config.auto_compress_char_threshold" type="number" min="1000" step="500" />
        </label>
        <label>
          <span>保留最近轮次</span>
          <input v-model.number="config.keep_recent_turns" type="number" min="1" max="6" />
        </label>
        <label>
          <span>预算限制</span>
          <input v-model="config.task_brief.budget_limit" type="text" />
        </label>
        <label>
          <span>时间限制</span>
          <input v-model="config.task_brief.time_limit" type="text" />
        </label>
        <label>
          <span>成功指标</span>
          <input v-model="config.task_brief.success_metric" type="text" />
        </label>
        <label>
          <span>失败标准</span>
          <input v-model="config.task_brief.failure_criteria" type="text" />
        </label>
        <label>
          <span>目标</span>
          <textarea v-model="config.task_brief.objective" rows="2" />
        </label>
        <label>
          <span>背景</span>
          <textarea v-model="config.task_brief.background" rows="3" />
        </label>
        <label>
          <span>已有资源</span>
          <textarea v-model="config.task_brief.existing_assets" rows="2" />
        </label>
        <label>
          <span>期望输出</span>
          <textarea v-model="config.task_brief.expected_output" rows="2" />
        </label>

        <section ref="agentSection" class="agent-config-section">
          <div class="section-header compact-section-header">
            <h3>Agent 编排</h3>
            <span>可完整编辑 S/A/B/C</span>
          </div>
          <div class="agent-stack">
            <article v-for="agentId in agentIds" :key="agentId" class="agent-row-card agent-row-card-collapsible">
              <button class="agent-summary-button" type="button" @click="toggleAgent(agentId)">
                <div class="agent-topline">
                  <label class="agent-enable">
                    <input v-model="config.agents[agentId].enabled" class="agent-enable-checkbox" type="checkbox" @click.stop />
                  </label>
                  <div class="agent-identity">
                    <span class="agent-code">{{ agentId }}</span>
                    <span class="agent-dot">·</span>
                    <span class="agent-title" :style="{ color: agentSpecs[agentId].color }">{{ agentSpecs[agentId].display_name }}</span>
                  </div>
                  <span class="agent-availability" :class="{ 'is-offline': !config.agents[agentId].enabled || !isAgentAvailable(agentId) }">
                    <i />
                    {{ agentStatusText(agentId) }}
                  </span>
                </div>
                <div class="agent-summary-meta">
                  <span>{{ config.agents[agentId].model || '未配置模型' }}</span>
                  <span>{{ config.agents[agentId].skill_id || '未选择 skill' }}</span>
                  <span>{{ expandedAgents[agentId] ? '收起' : '展开' }}</span>
                </div>
              </button>

              <div v-if="expandedAgents[agentId]" class="agent-control-stack">
                <label class="field-compact">
                  <span>模型</span>
                  <select v-model="config.agents[agentId].model">
                    <option v-for="model in models" :key="model.id" :value="model.id">{{ model.label }} · {{ model.provider }}</option>
                  </select>
                </label>
                <label class="field-compact">
                  <span>提示词人设</span>
                  <select v-model="config.agents[agentId].skill_id">
                    <option value="">未选择</option>
                    <option v-for="skill in skills[agentId]" :key="skill.skill_id" :value="skill.skill_id">
                      {{ skill.name }}{{ skill.is_latest ? ' · 最新' : ` · v${skill.version}` }}
                    </option>
                  </select>
                </label>
                <label class="field-compact">
                  <span>局部 Prompt</span>
                  <textarea v-model="config.agents[agentId].prompt" rows="3" placeholder="可选覆盖" />
                </label>
              </div>
            </article>
          </div>
        </section>

        <details class="inline-details">
          <summary class="details-summary">
            <span>高级协议与 Key</span>
            <span>可选</span>
          </summary>
          <div class="details-body">
            <label>
              <span>Preset Prompt</span>
              <textarea v-model="config.preset_prompt" rows="3" />
            </label>
            <label>
              <span>Project Prompt</span>
              <textarea v-model="config.project_prompt" rows="3" />
            </label>
            <label>
              <span>Output Protocol</span>
              <textarea v-model="config.output_protocol_prompt" rows="3" />
            </label>
            <label>
              <span>总结模型</span>
              <select v-model="config.summary_model">
                <option v-for="model in models" :key="model.id" :value="model.id">{{ model.label }} · {{ model.provider }}</option>
              </select>
            </label>
            <label>
              <span>DeepSeek API Key</span>
              <input v-model="config.deepseek_api_key" type="password" placeholder="sk-..." />
            </label>
            <label>
              <span>Ark API Key</span>
              <input v-model="config.ark_api_key" type="password" placeholder="ark-..." />
            </label>
          </div>
        </details>
      </div>
    </details>

    <details class="sidebar-card sidebar-details">
      <summary class="details-summary">
        <span>Documents</span>
        <span>{{ documents.length }} 份</span>
      </summary>
      <div class="details-body">
        <div class="project-actions-row">
          <button class="primary-button project-action-button" :disabled="isBusy" @click="emit('createDocument')">新建文档</button>
          <button class="ghost-button project-action-button" :disabled="isBusy || !activeDocument" @click="emit('saveDocument')">保存文档</button>
        </div>
        <div class="document-list">
          <label v-for="doc in documents" :key="doc.doc_id" class="document-item">
            <div class="document-meta">
              <input
                :checked="config.selected_documents.includes(doc.doc_id)"
                type="checkbox"
                @change="emit('toggleDocumentSelection', doc.doc_id, ($event.target as HTMLInputElement).checked)"
              />
              <button type="button" class="session-name-button" @click="emit('openDocument', doc.doc_id)">{{ doc.name }}</button>
            </div>
          </label>
        </div>
        <div v-if="activeDocument" class="document-editor">
          <div class="section-header compact-section-header">
            <h3>{{ activeDocument.name }}</h3>
            <button class="session-delete-button" type="button" @click="emit('deleteDocument')">删除</button>
          </div>
          <textarea :value="activeDocument.content || ''" rows="10" @input="onDocumentChange" />
        </div>
      </div>
    </details>

    <details class="sidebar-card sidebar-details">
      <summary class="details-summary">
        <span>Decision Memory</span>
        <span>{{ config.decision_memory.decisions.length }} 项</span>
      </summary>
      <div class="details-body">
        <label>
          <span>已确认决策</span>
          <textarea :value="config.decision_memory.decisions.join('\n')" rows="3" readonly />
        </label>
        <label>
          <span>已否决方案</span>
          <textarea :value="config.decision_memory.rejected_options.join('\n')" rows="3" readonly />
        </label>
        <label>
          <span>下一步动作</span>
          <textarea :value="config.decision_memory.next_actions.join('\n')" rows="3" readonly />
        </label>
        <label>
          <span>未解决问题</span>
          <textarea :value="config.decision_memory.open_questions.join('\n')" rows="3" readonly />
        </label>
      </div>
    </details>

    <section class="sidebar-card">
      <div class="section-header">
        <h2>会话存档</h2>
        <span>{{ savedSessions.length }} 份</span>
      </div>
      <div class="project-actions-row">
        <button class="primary-button project-action-button" :disabled="isBusy" @click="emit('createSession')">新建会话</button>
        <button class="ghost-button project-action-button" :disabled="isBusy" @click="emit('saveSession')">保存会话</button>
      </div>
      <div class="saved-session-list">
        <div v-for="file in savedSessions" :key="`saved-${file}`" class="saved-session-item">
          <button class="session-name-button" type="button" @click="emit('loadSession', file)">{{ file }}</button>
          <button class="session-delete-button" type="button" @click="emit('deleteSession', file)">删除</button>
        </div>
      </div>
    </section>
  </aside>
</template>
