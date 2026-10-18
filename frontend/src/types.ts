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
  error: string | null
  attempts: number
  latency_ms: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  model: string
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
}

export interface Turn {
  id: number
  question: string
  status: 'loading' | 'done' | 'error'
  startedAt: number
  result?: AskResult
  error?: string
}
