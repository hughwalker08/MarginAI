import type { AskResult, Example, Health } from './types'

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const getHealth = () => fetch('/api/health').then((r) => parse<Health>(r))
export const getExamples = () => fetch('/api/examples').then((r) => parse<Example[]>(r))
export const ask = (question: string) =>
  fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  }).then((r) => parse<AskResult>(r))
