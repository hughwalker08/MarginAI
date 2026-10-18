import { useState } from 'react'

export function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable (insecure context): ignore */
    }
  }
  return (
    <details className="sql">
      <summary>
        <svg className="chev" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Show the query behind this answer
      </summary>
      <pre className="sql-code">
        <button className="copy" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        {sql}
      </pre>
    </details>
  )
}
