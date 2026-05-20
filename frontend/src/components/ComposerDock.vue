<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { RoundMode, RuntimeConfig } from '../types'

const props = defineProps<{
  config: RuntimeConfig
  interventions: Record<string, string>
  isBusy: boolean
  roundState: 'idle' | 'running' | 'paused'
}>()

const emit = defineEmits<{
  send: [prompt: string]
  continueRound: []
  terminateRound: []
  attachFiles: [files: File[]]
  exportMarkdown: []
  setRoundMode: [mode: RoundMode]
  compressContext: []
}>()

const draft = ref('')
const menuOpen = ref(false)
const modeMenuOpen = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const plusWrapper = ref<HTMLElement | null>(null)
const modeWrapper = ref<HTMLElement | null>(null)

const canSubmit = computed(() => props.roundState === 'idle' && !props.isBusy && Boolean(draft.value.trim()))
const canTerminate = computed(() => props.roundState !== 'idle')
const canContinue = computed(() => props.roundState === 'paused' && !props.isBusy)

function closeMenus(event: MouseEvent) {
  const target = event.target as Node
  if (plusWrapper.value && !plusWrapper.value.contains(target)) {
    menuOpen.value = false
  }
  if (modeWrapper.value && !modeWrapper.value.contains(target)) {
    modeMenuOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', closeMenus))
onBeforeUnmount(() => document.removeEventListener('click', closeMenus))

function submit() {
  const value = draft.value.trim()
  if (!canSubmit.value) return
  emit('send', value)
  draft.value = ''
}

function terminate() {
  if (!canTerminate.value) return
  emit('terminateRound')
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

function applyMode(mode: RoundMode) {
  emit('setRoundMode', mode)
  modeMenuOpen.value = false
}
</script>

<template>
  <div class="composer-dock">
    <div class="dock-shell">
      <div class="dock-toolbar">
        <div class="dock-status">
          <span class="eyebrow">输入</span>
          <strong>{{ config.auto_mode ? '自动模式已启用' : `当前模式：${config.round_mode}` }}</strong>
        </div>
        <div class="dock-models">
          <label class="trace-item composer-toggle">
            <input v-model="config.auto_mode" type="checkbox" />
            <span>自动模式</span>
          </label>
        </div>
      </div>

      <div class="composer-row composer-row-slim">
        <div ref="plusWrapper" class="plus-wrapper">
          <button class="plus-button" :disabled="isBusy" @click.stop="menuOpen = !menuOpen">+</button>
          <div v-if="menuOpen" class="plus-menu plus-menu-solid" @click.stop>
            <button @click="triggerAttach">添加文档</button>
            <button @click="emit('compressContext'); menuOpen = false">压缩上下文</button>
            <button @click="emit('exportMarkdown'); menuOpen = false">导出</button>
          </div>
          <input ref="fileInput" class="hidden-input" type="file" multiple accept=".txt,.md,.pdf,.docx,.csv,.json,.yaml,.yml" @change="onFileChange" />
        </div>

        <textarea
          v-model="draft"
          class="composer-input"
          rows="1"
          :disabled="isBusy || roundState !== 'idle'"
          placeholder="直接输入问题即可；默认会自动选择讨论模式。"
          @keydown.enter.exact.prevent="submit"
        />

        <div class="composer-actions">
          <button class="send-button secondary-action" :disabled="props.isBusy" @click="emit('compressContext')">压缩上下文</button>
          <button class="send-button secondary-action" :disabled="!canContinue" @click="emit('continueRound')">继续</button>
          <button class="send-button" :disabled="roundState === 'idle' ? !canSubmit : !canTerminate" @click="roundState === 'idle' ? submit() : terminate()">
            {{ roundState === 'idle' ? '发送' : '终止' }}
          </button>
          <div ref="modeWrapper" class="plus-wrapper">
            <button class="send-button secondary-action" type="button" @click.stop="modeMenuOpen = !modeMenuOpen">模式</button>
            <div v-if="modeMenuOpen" class="plus-menu plus-menu-solid mode-menu" @click.stop>
              <button @click="applyMode('auto')">自动</button>
              <button @click="applyMode('converge')">收敛</button>
              <button @click="applyMode('critique')">挑刺</button>
              <button @click="applyMode('execute')">执行</button>
              <button @click="applyMode('diverge')">发散</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
