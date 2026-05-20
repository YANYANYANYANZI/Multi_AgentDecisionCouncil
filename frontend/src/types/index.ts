export type AgentId = 'S' | 'A' | 'B' | 'C'
export type RoundMode = 'auto' | 'diverge' | 'critique' | 'converge' | 'execute'
export type TaskType =
  | 'startup_validation'
  | 'product_design'
  | 'engineering_review'
  | 'research_brainstorm'
  | 'business_plan'
  | 'ui_review'
  | 'personal_decision'
  | 'general'

export interface AgentSettings {
  enabled: boolean
  model: string
  skill_id: string
  prompt: string
}

export interface TaskBrief {
  objective: string
  background: string
  task_type: TaskType
  budget_limit: string
  time_limit: string
  existing_assets: string
  constraints: string
  success_metric: string
  failure_criteria: string
  expected_output: string
}

export interface DecisionMemory {
  round_summary: string
  decisions: string[]
  rejected_options: string[]
  open_questions: string[]
  next_actions: string[]
  active_constraints: string[]
  updated_at: string
}

export interface RuntimeConfig {
  project_name: string
  preset_prompt: string
  global_constraint: string
  constraint_prompt: string
  judge_rubric: string
  project_prompt: string
  judge_prompt: string
  output_protocol_prompt: string
  workspace_id: string
  workspace_name: string
  deepseek_api_key: string
  ark_api_key: string
  summary_model: string
  team_name: string
  task_brief: TaskBrief
  selected_documents: string[]
  selected_documents_context: string
  compact_context: string
  auto_mode: boolean
  auto_compress_enabled: boolean
  auto_compress_turn_threshold: number
  auto_compress_char_threshold: number
  keep_recent_turns: number
  round_mode: RoundMode
  enable_judge: boolean
  summary_enabled: boolean
  decision_memory: DecisionMemory
  agents: Record<AgentId, AgentSettings>
  uploaded_docs: UploadedDoc[]
}

export interface UploadedDoc {
  name: string
  content: string
}

export interface WorkspaceSummary {
  workspace_id: string
  workspace_name: string
  round_mode: RoundMode
  enable_judge: boolean
  selected_team: string
  updated_at: string
}

export interface WorkspaceDocument {
  doc_id: string
  name: string
  content?: string
  selected: boolean
  updated_at?: string
  size?: number
}

export interface WorkspaceState {
  workspace_id: string
  workspace_name: string
  task_brief: TaskBrief
  global_constraint: string
  constraint_prompt: string
  judge_rubric: string
  project_prompt: string
  preset_prompt: string
  judge_prompt: string
  output_protocol_prompt: string
  selected_team: string
  selected_skills: Record<string, string>
  prompt_overrides: Record<string, string>
  selected_documents: string[]
  compact_context: string
  auto_mode: boolean
  auto_compress_enabled: boolean
  auto_compress_turn_threshold: number
  auto_compress_char_threshold: number
  keep_recent_turns: number
  round_mode: RoundMode
  enable_judge: boolean
  summary_enabled: boolean
  decision_memory: DecisionMemory
  created_at: string
  updated_at: string
}

export interface AgentMessage {
  agent: AgentId
  content: string
  reasoning?: string
}

export interface JudgeMessage {
  agent: 'JUDGE'
  content: string
  reasoning?: string
  error?: string
}

export interface StreamingAgentMessage extends AgentMessage {
  status: 'pending' | 'streaming' | 'done' | 'error'
  error?: string
}

export interface StreamingJudgeMessage extends JudgeMessage {
  status: 'pending' | 'streaming' | 'done' | 'error'
}

export interface RoundRecord {
  human_input: string
  workspace_id?: string
  workspace_name?: string
  round_mode?: RoundMode
  enable_judge?: boolean
  task_brief?: TaskBrief
  global_constraint?: string
  constraint_prompt?: string
  judge_rubric?: string
  project_prompt?: string
  compact_context?: string
  selected_documents?: string[]
  active_agents: string[]
  active_agent_models: Record<string, string>
  agent_messages: AgentMessage[]
  judge_message?: JudgeMessage | null
  decision_memory?: DecisionMemory
}

export interface PendingRound {
  human_input: string
  workspace_id?: string
  workspace_name?: string
  round_mode?: RoundMode
  enable_judge?: boolean
  compact_context?: string
  active_agents: string[]
  active_agent_models: Record<string, string>
  agent_messages: StreamingAgentMessage[]
  judge_message?: StreamingJudgeMessage | null
  decision_memory?: DecisionMemory
  status: 'streaming' | 'paused' | 'error'
  events: string[]
}

export interface SessionSnapshot {
  session_id: string
  project_name: string
  workspace_id?: string
  workspace_name?: string
  rounds: RoundRecord[]
  summary: string
  compact_context: string
  decision_memory: DecisionMemory
  runtime_config?: Partial<RuntimeConfig>
}

export interface ModelOption {
  id: string
  label: string
  provider: string
  base_url: string
}

export interface AgentSpec {
  agent_id: AgentId
  display_name: string
  avatar: string
  color: string
  system_prompt: string
  node_name: string
  run_name: string
}

export interface SkillOption {
  skill_id: string
  agent_id: AgentId
  team_name?: string
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
  agent_specs: Record<AgentId, AgentSpec>
  skills: Record<AgentId, SkillOption[]>
  available_teams: string[]
  active_team: string
  workspaces: WorkspaceSummary[]
  workspace: WorkspaceState
  documents: WorkspaceDocument[]
}
