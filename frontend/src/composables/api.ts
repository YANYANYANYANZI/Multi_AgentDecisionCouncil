import type {
  BootstrapPayload,
  RuntimeConfig,
  SessionSnapshot,
  UploadedDoc,
  WorkspaceDocument,
  WorkspaceState,
  WorkspaceSummary,
} from '../types'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!response.ok) {
    let detail = `Request failed with ${response.status}`
    try {
      const payload = await response.json()
      detail = payload.detail || detail
    } catch {
      detail = await response.text()
    }
    throw new Error(detail)
  }

  return response.json() as Promise<T>
}

export const councilApi = {
  bootstrap(teamName?: string) {
    const query = teamName ? `?team_name=${encodeURIComponent(teamName)}` : ''
    return request<BootstrapPayload>('/api/bootstrap' + query)
  },
  createSession(projectName: string) {
    return request<{ session: SessionSnapshot }>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ project_name: projectName }),
    })
  },
  createRound(sessionId: string, userInput: string, config: RuntimeConfig) {
    return request<{ session: SessionSnapshot }>('/api/sessions/' + sessionId + '/rounds', {
      method: 'POST',
      body: JSON.stringify({ user_input: userInput, config }),
    })
  },
  async streamRound(
    sessionId: string,
    userInput: string,
    config: RuntimeConfig,
    mode: 'manual' | 'auto',
    handlers: {
      onEvent: (event: string, payload: any) => void
      signal?: AbortSignal
    },
  ) {
    const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/rounds/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_input: userInput, config, mode }),
      signal: handlers.signal,
    })
    if (!response.ok) {
      let detail = `Request failed with ${response.status}`
      try {
        const payload = await response.json()
        detail = payload.detail || detail
      } catch {
        detail = await response.text()
      }
      throw new Error(detail)
    }
    if (!response.body) {
      throw new Error('流式响应不可用')
    }

    const decoder = new TextDecoder('utf-8')
    const reader = response.body.getReader()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''

      for (const chunk of chunks) {
        const lines = chunk.split('\n')
        const eventLine = lines.find((line) => line.startsWith('event: '))
        const dataLine = lines.find((line) => line.startsWith('data: '))
        if (!eventLine || !dataLine) continue
        const event = eventLine.slice(7).trim()
        const payload = JSON.parse(dataLine.slice(6))
        handlers.onEvent(event, payload)
      }

      if (done) break
    }
  },
  async continueRound(
    sessionId: string,
    mode: 'manual' | 'auto',
    handlers: {
      onEvent: (event: string, payload: any) => void
      signal?: AbortSignal
    },
  ) {
    const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/rounds/continue/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
      signal: handlers.signal,
    })
    if (!response.ok) {
      let detail = `Request failed with ${response.status}`
      try {
        const payload = await response.json()
        detail = payload.detail || detail
      } catch {
        detail = await response.text()
      }
      throw new Error(detail)
    }
    if (!response.body) {
      throw new Error('流式响应不可用')
    }

    const decoder = new TextDecoder('utf-8')
    const reader = response.body.getReader()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''

      for (const chunk of chunks) {
        const lines = chunk.split('\n')
        const eventLine = lines.find((line) => line.startsWith('event: '))
        const dataLine = lines.find((line) => line.startsWith('data: '))
        if (!eventLine || !dataLine) continue
        const event = eventLine.slice(7).trim()
        const payload = JSON.parse(dataLine.slice(6))
        handlers.onEvent(event, payload)
      }

      if (done) break
    }
  },
  terminateRound(sessionId: string) {
    return request<{ terminated: boolean }>('/api/sessions/' + sessionId + '/rounds/terminate', {
      method: 'POST',
    })
  },
  compressSession(sessionId: string) {
    return request<{ compact_context: string; summary: string; chars: number }>('/api/sessions/' + sessionId + '/compress', {
      method: 'POST',
    })
  },
  exportSession(sessionId: string, config: RuntimeConfig) {
    return request<{ markdown: string; mermaid: string }>('/api/sessions/' + sessionId + '/export', {
      method: 'POST',
      body: JSON.stringify(config),
    })
  },
  async parseFiles(files: File[]) {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    const response = await fetch(`${API_BASE}/api/files/parse`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      let detail = `Request failed with ${response.status}`
      try {
        const payload = await response.json()
        detail = payload.detail || detail
      } catch {
        detail = await response.text()
      }
      throw new Error(detail)
    }
    return response.json() as Promise<{ files: UploadedDoc[] }>
  },
  probeModels(keys: Pick<RuntimeConfig, 'deepseek_api_key' | 'ark_api_key'>) {
    return request<{ availability: Record<string, boolean> }>('/api/models/probe', {
      method: 'POST',
      body: JSON.stringify(keys),
    })
  },
  listSavedSessions() {
    return request<{ files: string[] }>('/api/saved-sessions')
  },
  deleteSavedSession(fileName: string) {
    return request<{ deleted: string }>('/api/saved-sessions/' + encodeURIComponent(fileName), {
      method: 'DELETE',
    })
  },
  loadSession(fileName: string) {
    return request<{ session: SessionSnapshot }>('/api/sessions/load', {
      method: 'POST',
      body: JSON.stringify({ file_name: fileName }),
    })
  },
  saveSession(sessionId: string, saveName: string) {
    return request<{ file_name: string }>('/api/sessions/' + sessionId + '/save', {
      method: 'POST',
      body: JSON.stringify({ save_name: saveName }),
    })
  },
  listWorkspaces() {
    return request<{ workspaces: WorkspaceSummary[] }>('/api/workspaces')
  },
  createWorkspace(payload: Partial<WorkspaceState> & { workspace_name: string }) {
    return request<{ workspace: WorkspaceState }>('/api/workspaces', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  getWorkspace(workspaceId: string) {
    return request<{ workspace: WorkspaceState }>(`/api/workspaces/${encodeURIComponent(workspaceId)}`)
  },
  updateWorkspace(workspaceId: string, payload: Partial<WorkspaceState>) {
    return request<{ workspace: WorkspaceState }>(`/api/workspaces/${encodeURIComponent(workspaceId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },
  listWorkspaceDocuments(workspaceId: string) {
    return request<{ documents: WorkspaceDocument[] }>(`/api/workspaces/${encodeURIComponent(workspaceId)}/documents`)
  },
  getWorkspaceDocument(workspaceId: string, docId: string) {
    return request<{ document: WorkspaceDocument }>(
      `/api/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(docId)}`,
    )
  },
  updateWorkspaceDocument(workspaceId: string, docId: string, payload: { name?: string; content: string }) {
    return request<{ document: WorkspaceDocument }>(
      `/api/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(docId)}`,
      {
        method: 'PUT',
        body: JSON.stringify(payload),
      },
    )
  },
  async createWorkspaceDocument(workspaceId: string, payload: { name: string; content: string }) {
    const formData = new FormData()
    formData.append('name', payload.name)
    formData.append('content', payload.content)
    const response = await fetch(`${API_BASE}/api/workspaces/${encodeURIComponent(workspaceId)}/documents`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      let detail = `Request failed with ${response.status}`
      try {
        const body = await response.json()
        detail = body.detail || detail
      } catch {
        detail = await response.text()
      }
      throw new Error(detail)
    }
    return response.json() as Promise<{ document: WorkspaceDocument }>
  },
  deleteWorkspaceDocument(workspaceId: string, docId: string) {
    return request<{ deleted: string }>(
      `/api/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(docId)}`,
      { method: 'DELETE' },
    )
  },
}
