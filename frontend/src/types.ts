export type Cell = string | number | boolean | null

export interface ChartSpec {
  type: 'line' | 'bar'
  x: string
  y: string[]
  series?: string
}

export interface AskResult {
  question: string
  answer: string
  sql: string | null
  columns: string[]
  rows: Cell[][]
  truncated: boolean
  chart: ChartSpec | null
  assumptions: string
  clarification: string | null
  follow_ups: string[]
  error: string | null
  attempts: number
  latency_ms: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  model: string
  timings?: Record<string, number>
}

export type StreamEvent =
  | ({ type: 'result' } & AskResult)
  | { type: 'delta'; text: string }
  | ({ type: 'done' } & Pick<AskResult, 'answer' | 'error' | 'attempts' | 'latency_ms' | 'input_tokens' | 'output_tokens' | 'cost_usd' | 'model'> & { timings: Record<string, number> })

/** What the browser remembers of a finished turn and sends back so follow-ups make sense. */
export interface HistoryItem {
  question: string
  answer: string
  sql: string | null
  assumptions: string
  clarification: string | null
  follow_ups: string[]
  columns: string[]
  rows: Cell[][]
}

export interface StoreInfo {
  slug: string
  name: string
  currency: string
  demo: boolean
  last_synced_at: string | null
}

export interface Example {
  group: string
  question: string
}

export interface Health {
  status: string
  model: string
  orders: number
  data_as_of: string
  memory_turns?: number
}

export interface Turn {
  id: number
  question: string
  status: 'loading' | 'streaming' | 'done' | 'error'
  startedAt: number
  result?: AskResult
  error?: string
}

export interface User {
  email: string
  name: string
  picture: string
  is_admin: boolean
}

export interface AuthConfig {
  google_client_id: string | null
  auth_enabled: boolean
}
