<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ModelOption, RuntimeConfig } from '../types'

const props = defineProps<{
  config: RuntimeConfig
  models: ModelOption[]
  interventions: Record<string, string>
  isBusy: boolean
}>()

const emit = defineEmits<{
  send: [prompt: string]
  attachFiles: [files: File[]]
  exportMarkdown: []
}>()

const draft = ref('')
const menuOpen = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const agentIds = ['A', 'B', 'C'] as const

const enabledAgents = computed(() =>
  agentIds.filter((agentId) => props.config.agents[agentId].enabled)
)

function submit() {
  const value = draft.value.trim()
  if (!value || props.isBusy) return
  emit('send', value)
  draft.value = ''
}

function triggerAttach() {
  fileInput.value?.click()
  menuOpen.value = false
}

function onFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  const files = target.files ? Array.from(target.files) : []
  if (files.length) {
    emit('attachFiles', files)
  }
  target.value = ''
}

function useIntervention(key: string) {
  draft.value = props.interventions[key]
  menuOpen.value = false
}
</script>

<template>
  <div class="composer-dock">
    <div class="dock-shell">
      <div class="dock-toolbar">
        <div class="dock-status">
          <span class="eyebrow">输入</span>
          <strong>本轮：{{ enabledAgents.join(' / ') || '未启用' }}</strong>
        </div>
        <div class="dock-models">
          <span v-for="agentId in enabledAgents" :key="agentId">
            {{ agentId }} · {{ models.find((model) => model.id === config.agents[agentId].model)?.label || '未配置' }}
          </span>
        </div>
      </div>

      <div class="composer-row">
        <div class="plus-wrapper">
          <button class="plus-button" :disabled="isBusy" @click="menuOpen = !menuOpen">+</button>
          <div v-if="menuOpen" class="plus-menu">
            <button @click="triggerAttach">添加文件</button>
            <button @click="useIntervention('overdesign')">反过度设计</button>
            <button @click="useIntervention('common_sense')">工程红线</button>
            <button @click="useIntervention('catastrophe')">风险视角</button>
            <button @click="emit('exportMarkdown'); menuOpen = false">导出</button>
          </div>
          <input
            ref="fileInput"
            class="hidden-input"
            type="file"
            multiple
            accept=".txt,.md,.pdf,.docx,.csv,.json,.yaml,.yml"
            @change="onFileChange"
          />
        </div>

        <textarea
          v-model="draft"
          class="composer-input"
          rows="1"
          :disabled="isBusy"
          placeholder="输入指令，Enter 发送"
          @keydown.enter.exact.prevent="submit"
        />

        <button class="send-button" :disabled="isBusy || !draft.trim()" @click="submit">发送</button>
      </div>
    </div>
  </div>
</template>
