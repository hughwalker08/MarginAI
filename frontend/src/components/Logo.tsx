/** Two arches that read as an "m", with a moss-green dot for the AI. Colours come from CSS tokens. */
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" style={{ flex: 'none' }}>
      <rect width="32" height="32" rx="6" fill="var(--mark-bg)" />
      <path
        d="M9 23V15a3.5 3.5 0 0 1 7 0V23M16 23V15a3.5 3.5 0 0 1 7 0V23"
        fill="none"
        stroke="var(--mark-fg)"
        strokeWidth="2.3"
        strokeLinecap="round"
      />
      <circle cx="23" cy="8" r="2.1" fill="var(--moss)" />
    </svg>
  )
}

export function Wordmark() {
  return (
    <span className="wordmark">
      margin<em>ai</em>
    </span>
  )
}
