import { useEffect, useRef, useState } from 'react'
import { LogoMark, Wordmark } from './Logo'

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (cfg: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string }) => void
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void
        }
      }
    }
  }
}

const GSI = 'https://accounts.google.com/gsi/client'
let loading: Promise<void> | null = null

/** Load Google's sign-in script once. */
function loadGoogle(): Promise<void> {
  if (window.google?.accounts) return Promise.resolve()
  loading ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement('script')
    s.src = GSI
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => {
      loading = null
      reject(new Error('Could not load Google sign-in. Check your connection or ad blocker.'))
    }
    document.head.appendChild(s)
  })
  return loading
}

/** Renders Google's own "Continue with Google" button. */
export function GoogleButton({ clientId, onCredential, width = 300 }: {
  clientId: string
  onCredential: (credential: string) => void
  width?: number
}) {
  const box = useRef<HTMLDivElement>(null)
  const cb = useRef(onCredential)
  cb.current = onCredential
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    loadGoogle()
      .then(() => {
        if (!alive || !box.current || !window.google) return
        window.google.accounts.id.initialize({ client_id: clientId, callback: (r) => cb.current(r.credential), ux_mode: 'popup' })
        window.google.accounts.id.renderButton(box.current, {
          type: 'standard', theme: 'outline', size: 'large', text: 'continue_with', shape: 'rectangular',
          logo_alignment: 'left', width,
        })
      })
      .catch((e: Error) => alive && setError(e.message))
    return () => { alive = false }
  }, [clientId, width])

  return error ? <p className="error-text">{error}</p> : <div ref={box} className="gbtn" aria-label="Continue with Google" />
}

export function SignInScreen({ clientId, error, onCredential, onDemo }: {
  clientId: string
  error: string | null
  onCredential: (credential: string) => void
  onDemo: () => void
}) {
  return (
    <div className="gate">
      <div className="gate-card">
        <div className="brand gate-brand"><LogoMark size={34} /><Wordmark /></div>
        <h1>Know your numbers</h1>
        <p>Sign in to ask questions about your store’s sales in plain English.</p>
        <GoogleButton clientId={clientId} onCredential={onCredential} />
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="gate-or"><span>or</span></div>
        <button className="btn gate-demo" onClick={onDemo}>Try the demo store</button>
        <small>The demo uses made-up data for a fictional boutique. No sign-in needed.</small>
      </div>
    </div>
  )
}
