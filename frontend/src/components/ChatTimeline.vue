<script setup lang="ts">
import { computed } from 'vue'
import RichTextBlock from './RichTextBlock.vue'
import type { AgentSpec, DecisionMemory, PendingRound, RoundMode, RoundRecord, WorkspaceDocument } from '../types'

const props = defineProps<{
  projectName: string
  rounds: RoundRecord[]
  summary: string
  compactContext: string
  agentSpecs: Record<'S' | 'A' | 'B' | 'C', AgentSpec>
  uploadedDocs: WorkspaceDocument[]
  loading: boolean
  pendingRound: PendingRound | null
  decisionMemory: DecisionMemory
  roundMode: RoundMode
}>()

const latestRoundIndex = computed(() => props.rounds.length - 1)
const liveRounds = computed(() => (props.pendingRound ? [...props.rounds, props.pendingRound] : props.rounds))

function modelLabel(round: RoundRecord | PendingRound, agentId: string) {
  return round.active_agent_models[agentId] || '未配置模型'
}

function isPendingRound(round: RoundRecord | PendingRound): round is PendingRound {
  return 'events' in round
}

function pendingMessageState(round: RoundRecord | PendingRound, agentId: string) {
  if (!isPendingRound(round)) return null
  return round.agent_messages.find((message) => message.agent === agentId)?.status || null
}

function pendingMessageError(round: RoundRecord | PendingRound, agentId: string) {
  if (!isPendingRound(round)) return ''
  return round.agent_messages.find((message) => message.agent === agentId)?.error || ''
}
</script>

<template>
  <main class="workspace">
    <section class="hero-card">
      <div>
        <div class="eyebrow">Council</div>
        <h2>{{ projectName }}</h2>
        <p>当前模式：{{ roundMode }}。讨论、收敛和记忆在同一工作区沉淀。</p>
      </div>
      <div class="hero-meta">
        <span>{{ rounds.length }} 轮归档</span>
        <span>{{ uploadedDocs.length }} 份文档</span>
      </div>
    </section>

    <section v-if="summary" class="summary-card">
      <div class="section-header">
        <h3>长期摘要</h3>
        <span>会话记忆</span>
      </div>
      <RichTextBlock :content="summary" />
    </section>

    <section v-if="compactContext" class="summary-card">
      <div class="section-header">
        <h3>Compact Context</h3>
        <span>压缩后上下文</span>
      </div>
      <RichTextBlock :content="compactContext" />
    </section>

    <section class="summary-card">
      <div class="section-header">
        <h3>决策记忆</h3>
        <span>{{ decisionMemory.updated_at || '未更新' }}</span>
      </div>
      <div class="doc-grid">
        <article class="doc-card">
          <strong>已确认决策</strong>
          <p>{{ decisionMemory.decisions.join(' / ') || '暂无' }}</p>
        </article>
        <article class="doc-card">
          <strong>已否决方案</strong>
          <p>{{ decisionMemory.rejected_options.join(' / ') || '暂无' }}</p>
        </article>
        <article class="doc-card">
          <strong>下一步动作</strong>
          <p>{{ decisionMemory.next_actions.join(' / ') || '暂无' }}</p>
        </article>
        <article class="doc-card">
          <strong>未解决问题</strong>
          <p>{{ decisionMemory.open_questions.join(' / ') || '暂无' }}</p>
        </article>
      </div>
    </section>

    <section v-if="uploadedDocs.length" class="summary-card">
      <div class="section-header">
        <h3>已挂载文档</h3>
        <span>{{ uploadedDocs.length }} 个文件</span>
      </div>
      <div class="doc-grid">
        <article v-for="doc in uploadedDocs" :key="doc.doc_id" class="doc-card">
          <strong>{{ doc.name }}</strong>
          <p>{{ (doc.content || '').slice(0, 220) }}</p>
        </article>
      </div>
    </section>

    <section class="timeline">
      <div v-if="!liveRounds.length" class="empty-state">
        <h3>输入议题后开始第一轮</h3>
        <p>右侧会实时显示 Agent 输出。</p>
      </div>

      <article
        v-for="(round, index) in liveRounds"
        :key="`${index}-${round.human_input}`"
        class="round-card"
        :class="{ 'round-card-live': pendingRound && index === liveRounds.length - 1 }"
      >
        <div class="round-head">
          <div class="round-title-group">
            <span class="round-chip">第 {{ index + 1 }} 轮</span>
            <span v-if="index === latestRoundIndex && !pendingRound" class="round-chip round-chip-latest">最新</span>
            <span v-if="isPendingRound(round) && round.status === 'streaming'" class="round-chip round-chip-live">流式执行中</span>
            <span v-if="isPendingRound(round) && round.status === 'paused'" class="round-chip round-chip-latest">等待审批</span>
          </div>
          <span class="round-agents">{{ round.active_agents.join(' · ') }}</span>
        </div>

        <div v-if="isPendingRound(round)" class="live-trace">
          <div class="trace-header">
            <strong>执行轨迹</strong>
            <span>{{ round.status === 'error' ? '已中断' : round.status === 'paused' ? '等待继续' : '实时更新' }}</span>
          </div>
          <div class="trace-list">
            <div v-for="event in round.events" :key="event" class="trace-item">{{ event }}</div>
          </div>
        </div>

        <div class="message user-message">
          <div class="message-role">控制中心</div>
          <div class="message-content">{{ round.human_input }}</div>
        </div>

        <div
          v-for="message in round.agent_messages"
          :key="`${index}-${message.agent}`"
          class="message agent-message"
          :class="{ 'message-streaming': 'status' in message && message.status !== 'done' }"
        >
          <div class="message-meta">
            <div class="message-role" :style="{ color: agentSpecs[message.agent].color }">
              {{ agentSpecs[message.agent].avatar }} {{ agentSpecs[message.agent].display_name }}
            </div>
            <div class="message-model">{{ modelLabel(round, message.agent) }}</div>
          </div>
          <div v-if="message.reasoning" class="reasoning-panel">
            <div class="reasoning-title">思考过程</div>
            <RichTextBlock :content="message.reasoning" />
          </div>
          <RichTextBlock :content="message.content || '正在思考…'" />
          <div v-if="pendingMessageState(round, message.agent) === 'streaming'" class="streaming-caret" />
          <div v-if="pendingMessageState(round, message.agent) === 'pending'" class="message-placeholder">等待该 Agent 开始输出</div>
          <div v-if="pendingMessageState(round, message.agent) === 'error'" class="message-placeholder">
            {{ pendingMessageError(round, message.agent) || '该 Agent 输出中断' }}
          </div>
        </div>

        <div v-if="round.judge_message" class="message judge-message">
          <div class="message-meta">
            <div class="message-role judge-title">Judge · 裁判收敛</div>
          </div>
          <RichTextBlock :content="round.judge_message.content || round.judge_message.error || 'Judge 执行中…'" />
        </div>
      </article>
    </section>
  </main>
</template>
