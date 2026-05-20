<script setup lang="ts">
import { computed } from 'vue'
import type { AgentSpec, ModelOption, RuntimeConfig, SkillOption } from '../types'

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
}>()

const emit = defineEmits<{
  refreshModels: []
  createSession: []
  saveSession: []
  changeTeam: [teamName: string]
  loadSession: [fileName: string]
  deleteSession: [fileName: string]
  toggleTheme: []
}>()

const agentIds = ['S', 'A', 'B', 'C'] as const
type AgentId = (typeof agentIds)[number]

const availableModelCount = computed(() => props.models.length)
const enabledAgentCount = computed(() =>
  agentIds.filter((agentId) => props.config.agents[agentId].enabled).length
)

function isAgentAvailable(agentId: AgentId) {
  return Boolean(props.availability[props.config.agents[agentId].model])
}

function onTeamChange(event: Event) {
  const target = event.target as HTMLSelectElement
  emit('changeTeam', target.value)
}
</script>

<template>
  <aside class="sidebar">
    <section class="sidebar-card sidebar-card-hero">
      <div class="eyebrow">Control</div>
      <h1>多智能体决策台</h1>
      <p>配置 Agent、模型与会话。</p>
      <div class="status-row">
        <span>{{ availableModelCount }} 个可用模型</span>
        <div class="hero-actions">
          <button class="ghost-button" :disabled="isBusy" @click="emit('refreshModels')">刷新探测</button>
          <button class="theme-button" type="button" @click="emit('toggleTheme')">
            {{ theme === 'dark' ? '切换浅色模式' : '切换黑暗模式' }}
          </button>
        </div>
      </div>
    </section>

    <section class="sidebar-card">
      <div class="section-header project-settings-header">
        <h2>项目设置</h2>
      </div>
      <label>
        <span>智能体团队</span>
        <select :value="activeTeam" @change="onTeamChange">
          <option v-for="teamName in availableTeams" :key="teamName" :value="teamName">
            {{ teamName }}
          </option>
        </select>
      </label>
      <label class="project-name-inline">
        <span>项目名</span>
        <input v-model="config.project_name" type="text" placeholder="未命名议题" />
      </label>
      <div class="project-actions-row">
        <button class="primary-button project-action-button" :disabled="isBusy" @click="emit('createSession')">新建</button>
        <button class="ghost-button project-action-button" :disabled="isBusy" @click="emit('saveSession')">保存</button>
      </div>
      <label>
        <span>预设提示词</span>
        <textarea v-model="config.preset_prompt" rows="4" />
      </label>
      <details class="inline-details">
        <summary class="details-summary">
          <span>API Key</span>
          <span>可选</span>
        </summary>
        <div class="details-body">
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
    </section>

    <section class="sidebar-card agent-orchestration-card">
      <div class="section-header compact-section-header">
        <h2>Agent 编排</h2>
        <span>已启用 {{ enabledAgentCount }}/4</span>
      </div>

      <div class="agent-stack">
        <article v-for="agentId in agentIds" :key="agentId" class="agent-row-card">
          <div class="agent-topline">
            <label class="agent-enable">
              <input
                v-model="config.agents[agentId].enabled"
                class="agent-enable-checkbox"
                type="checkbox"
              />
            </label>

            <div class="agent-identity">
              <span class="agent-code">{{ agentId }}</span>
              <span class="agent-dot">·</span>
              <span
                class="agent-title"
                :style="{ color: agentSpecs[agentId].color }"
              >
                {{ agentSpecs[agentId].display_name.replace(`${agentId}·`, '') }}
              </span>
            </div>

            <span class="agent-availability" :class="{ 'is-offline': !isAgentAvailable(agentId) }">
              <i />
              {{ isAgentAvailable(agentId) ? '可用' : '未探测' }}
            </span>
          </div>

          <div class="agent-control-stack">
            <label class="field-compact">
              <span>模型</span>
              <select v-model="config.agents[agentId].model">
                <option v-for="model in models" :key="model.id" :value="model.id">
                  {{ model.label }} · {{ model.provider }}
                </option>
              </select>
            </label>

            <label class="field-compact">
              <span>提示词人设</span>
              <select v-model="config.agents[agentId].skill_id">
                <option v-for="skill in skills[agentId]" :key="skill.skill_id" :value="skill.skill_id">
                  {{ skill.name }}{{ skill.is_latest ? ' · 最新' : ` · v${skill.version}` }}
                </option>
              </select>
            </label>
          </div>
        </article>
      </div>

      <label class="field-compact summary-model-field">
        <span>总结模型</span>
        <select v-model="config.summary_model">
          <option v-for="model in models" :key="model.id" :value="model.id">
            {{ model.label }} · {{ model.provider }}
          </option>
        </select>
      </label>
    </section>

    <details class="sidebar-card sidebar-details">
      <summary class="details-summary">
        <span>高级提示词</span>
        <span>可选</span>
      </summary>
      <div class="details-body">
        <label v-for="agentId in agentIds" :key="`prompt-${agentId}`" class="field-compact">
          <span>{{ agentSpecs[agentId].display_name }}</span>
          <textarea v-model="config.agents[agentId].prompt" rows="4" placeholder="追加局部指令" />
        </label>
      </div>
    </details>

    <section class="sidebar-card">
      <div class="section-header">
        <h2>会话存档</h2>
        <span>{{ savedSessions.length }} 份</span>
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
