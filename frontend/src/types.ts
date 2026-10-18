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
  columns: string[]
  rows: Cell[][]
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
