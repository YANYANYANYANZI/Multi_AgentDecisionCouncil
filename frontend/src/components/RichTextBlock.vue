<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  content: string
}>()

const html = computed(() => renderRichText(props.content))

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function renderInline(value: string) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
}

function renderBlocks(lines: string[]) {
  const blocks: string[] = []
  let paragraph: string[] = []
  let listItems: string[] = []
  let orderedItems: string[] = []
  let codeLines: string[] = []
  let inCode = false

  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(`<p>${paragraph.map(renderInline).join('<br />')}</p>`)
    paragraph = []
  }
  const flushList = () => {
    if (!listItems.length) return
    blocks.push(`<ul>${listItems.map((item) => `<li>${renderInline(item)}</li>`).join('')}</ul>`)
    listItems = []
  }
  const flushOrdered = () => {
    if (!orderedItems.length) return
    blocks.push(`<ol>${orderedItems.map((item) => `<li>${renderInline(item)}</li>`).join('')}</ol>`)
    orderedItems = []
  }
  const flushCode = () => {
    if (!codeLines.length) return
    blocks.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
    codeLines = []
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('```')) {
      flushParagraph()
      flushList()
      flushOrdered()
      if (inCode) {
        flushCode()
      }
      inCode = !inCode
      continue
    }
    if (inCode) {
      codeLines.push(line)
      continue
    }
    if (!trimmed) {
      flushParagraph()
      flushList()
      flushOrdered()
      continue
    }
    if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph()
      flushOrdered()
      listItems.push(trimmed.replace(/^[-*]\s+/, ''))
      continue
    }
    if (/^\d+\.\s+/.test(trimmed)) {
      flushParagraph()
      flushList()
      orderedItems.push(trimmed.replace(/^\d+\.\s+/, ''))
      continue
    }
    if (trimmed.startsWith('>')) {
      flushParagraph()
      flushList()
      flushOrdered()
      blocks.push(`<blockquote>${renderInline(trimmed.replace(/^>\s?/, ''))}</blockquote>`)
      continue
    }
    if (trimmed.startsWith('### ')) {
      flushParagraph()
      flushList()
      flushOrdered()
      blocks.push(`<h4>${renderInline(trimmed.slice(4))}</h4>`)
      continue
    }
    if (trimmed.startsWith('## ')) {
      flushParagraph()
      flushList()
      flushOrdered()
      blocks.push(`<h3>${renderInline(trimmed.slice(3))}</h3>`)
      continue
    }
    if (trimmed.startsWith('# ')) {
      flushParagraph()
      flushList()
      flushOrdered()
      blocks.push(`<h2>${renderInline(trimmed.slice(2))}</h2>`)
      continue
    }
    paragraph.push(trimmed)
  }

  flushParagraph()
  flushList()
  flushOrdered()
  flushCode()

  return blocks.join('')
}

function renderRichText(source: string) {
  const normalized = source
    .replace(/\[致命漏洞\]/g, '## 致命漏洞')
    .replace(/\[核心破局点\]/g, '## 核心破局点')
    .replace(/\[可执行蓝图\]/g, '## 可执行蓝图')
  return renderBlocks(normalized.split('\n'))
}
</script>

<template>
  <div class="rich-text" v-html="html" />
</template>
