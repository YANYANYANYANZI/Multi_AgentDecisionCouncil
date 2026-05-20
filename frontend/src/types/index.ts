export interface AgentSettings {
  enabled: boolean
  model: string
  skill_id: string
  prompt: string
}

export interface RuntimeConfig {
  project_name: string
  preset_prompt: string
  deepseek_api_key: string
  ark_api_key: string
  summary_model: string
  agents: Record<'A' | 'B' | 'C', AgentSettings>
  uploaded_docs: UploadedDoc[]
}

export interface UploadedDoc {
  name: string
  content: string
}

export interface AgentMessage {
  agent: 'A' | 'B' | 'C'
  content: string
  reasoning?: string
}

export interface StreamingAgentMessage extends AgentMessage {
  status: 'pending' | 'streaming' | 'done' | 'error'
  error?: string
}

export interface RoundRecord {
  human_input: string
  active_agents: string[]
  active_agent_models: Record<string, string>
  agent_messages: AgentMessage[]
}

export interface PendingRound {
  human_input: string
  active_agents: string[]
  active_agent_models: Record<string, string>
  agent_messages: StreamingAgentMessage[]
  status: 'streaming' | 'error'
  events: string[]
}

export interface SessionSnapshot {
  session_id: string
  project_name: string
  rounds: RoundRecord[]
  summary: string
}

export interface ModelOption {
  id: string
  label: string
  provider: string
  base_url: string
}

export interface AgentSpec {
  agent_id: 'A' | 'B' | 'C'
  display_name: string
  avatar: string
  color: string
  system_prompt: string
  node_name: string
  run_name: string
}

export interface SkillOption {
  skill_id: string
  agent_id: 'A' | 'B' | 'C'
  name: string
  version: string
  description: string
  is_latest: boolean
}

export interface BootstrapPayload {
  session: SessionSnapshot
  defaults: RuntimeConfig
  models: ModelOption[]
  available_models: ModelOption[]
  availability: Record<string, boolean>
  interventions: Record<string, string>
  agent_specs: Record<'A' | 'B' | 'C', AgentSpec>
  skills: Record<'A' | 'B' | 'C', SkillOption[]>
}
