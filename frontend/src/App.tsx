import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { askStream, getConfig, getExamples, getHealth, getMe, getStores, loginWithGoogle, logout } from './api'
import { AnswerCard } from './components/AnswerCard'
import { Composer } from './components/Composer'
import { LogoMark, Wordmark } from './components/Logo'
import { Sidebar } from './components/Sidebar'
import { SignInScreen } from './components/SignIn'
import { type Chat, clearSavedChats, loadChats, newChatId, pruneChats, saveChats, titleFrom } from './chats'
import { ago, fmtDate } from './format'
import type { AuthConfig, Example, Health, HistoryItem, StoreInfo, Turn, User } from './types'

type Theme = 'light' | 'dark' | null

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('theme')
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}

const HISTORY_SENT = 10 // the server decides how many it actually uses (MEMORY_TURNS)

/** Finished, successful turns only, in a compact form. */
function toHistory(turns: Turn[]): HistoryItem[] {
  return turns
    .filter((t) => t.status === 'done' && t.result && (t.result.sql || t.result.clarification))
    .slice(-HISTORY_SENT)
    .map((t) => ({
      question: t.question,
      answer: t.result!.answer,
      sql: t.result!.sql,
      assumptions: t.result!.assumptions,
      clarification: t.result!.clarification,
      columns: t.result!.columns,
      rows: t.result!.rows.slice(0, 5),
    }))
}

export default function App() {
  const [chats, setChats] = useState<Chat[]>(loadChats)
  const [activeId, setActiveId] = useState<string | null>(null) // null = a new chat that has no question yet
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)
  const [examples, setExamples] = useState<Example[]>([])
  const [stores, setStores] = useState<StoreInfo[]>([])
  const [store, setStore] = useState('demo')
  const [theme, setTheme] = useState<Theme>(readTheme)
  const [drawer, setDrawer] = useState(false)
  const [authCfg, setAuthCfg] = useState<AuthConfig | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [signInError, setSignInError] = useState<string | null>(null)
  const [demoOnly, setDemoOnly] = useState(() => {
    try { return sessionStorage.getItem('demoOnly') === '1' } catch { return false }
  })
  const [menu, setMenu] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const turnSeq = useRef(Date.now())

  const storeChats = useMemo(() => chats.filter((c) => c.store === store), [chats, store])
  const turns = useMemo(() => chats.find((c) => c.id === activeId)?.turns ?? [], [chats, activeId])
  const busyIds = useMemo(
    () => new Set(chats.filter((c) => c.turns.some((t) => t.status === 'loading' || t.status === 'streaming')).map((c) => c.id)),
    [chats])
  const busy = turns.some((t) => t.status === 'loading' || t.status === 'streaming')
  const current = stores.find((s) => s.slug === store)

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setOffline(true))
    Promise.all([getConfig().catch(() => null), getMe().catch(() => null)]).then(([cfg, me]) => {
      setAuthCfg(cfg)
      setUser(me)
      setAuthChecked(true)
    })
  }, [])

  // Who is signed in decides which stores exist for them, so reload the list whenever that changes.
  useEffect(() => {
    const loadStores = () => getStores().then(setStores).catch(() => {})
    loadStores()
    const t = setInterval(loadStores, 60_000) // keeps "updated 12 min ago" honest
    return () => clearInterval(t)
  }, [user?.email])

  useEffect(() => {
    getExamples(store).then(setExamples).catch(() => {})
  }, [store])

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme
    else delete document.documentElement.dataset.theme
  }, [theme])

  // Save chats shortly after they change (not on every streamed word).
  useEffect(() => {
    const t = setTimeout(() => saveChats(chats), 600)
    return () => clearTimeout(t)
  }, [chats])

  // Bring a newly asked question to the top of the view so its answer can be read from the start.
  useEffect(() => {
    const items = scroller.current?.querySelectorAll('.turn')
    items?.[items.length - 1]?.scrollIntoView({ block: 'start' })
  }, [turns.length, activeId])

  const toggleTheme = () => {
    const dark = theme ? theme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
    const next: Theme = dark ? 'light' : 'dark'
    setTheme(next)
    try {
      localStorage.setItem('theme', next!)
    } catch {
      /* storage blocked: theme still applies for this session */
    }
  }

  const changeStore = (slug: string) => {
    setStore(slug)
    setActiveId(null) // chats belong to one store: start fresh in the new one, its own chats are in the sidebar
  }

  const onGoogle = async (credential: string) => {
    setSignInError(null)
    try {
      const u = await loginWithGoogle(credential)
      // Chats of real stores belong to whoever was signed in: never show them to a different person on this browser.
      if (user && user.email !== u.email) setChats((cs) => cs.filter((c) => c.store === 'demo'))
      setUser(u)
      setActiveId(null)
      const list = await getStores().catch(() => [] as StoreInfo[])
      setStores(list)
      const real = list.find((x) => !x.demo)
      if (real) setStore(real.slug)
    } catch (e) {
      setSignInError((e as Error).message)
    }
  }

  const signOut = async () => {
    await logout().catch(() => undefined)
    setUser(null)
    setMenu(false)
    setChats((cs) => cs.filter((c) => c.store === 'demo')) // real-store chats must not outlive the session
    setStore('demo')
    setActiveId(null)
    setDemoOnly(false)
    try { sessionStorage.removeItem('demoOnly') } catch { /* ignore */ }
  }

  const enterDemo = () => {
    setDemoOnly(true)
    try { sessionStorage.setItem('demoOnly', '1') } catch { /* ignore */ }
  }

  const submit = useCallback((question: string) => {
    const turnId = turnSeq.current++
    const chatId = activeId ?? newChatId()
    const history = toHistory(chats.find((c) => c.id === chatId)?.turns ?? [])
    const patch = (fn: (t: Turn) => Turn) => setChats((cs) => cs.map((c) =>
      c.id !== chatId ? c : { ...c, updatedAt: Date.now(), turns: c.turns.map((t) => (t.id === turnId ? fn(t) : t)) }))
    const turn: Turn = { id: turnId, question, status: 'loading', startedAt: Date.now() }
    setChats((cs) => cs.some((c) => c.id === chatId)
      ? cs.map((c) => (c.id === chatId ? { ...c, updatedAt: Date.now(), turns: [...c.turns, turn] } : c))
      : [{ id: chatId, store, title: titleFrom(question), createdAt: Date.now(), updatedAt: Date.now(), turns: [turn] }, ...cs])
    setActiveId(chatId)
    askStream(question, history, store, (e) => {
      setOffline(false)
      if (e.type === 'result') {
        const { type: _type, ...result } = e
        // Data and chart arrive first; the written answer streams in after. No answer text yet means "still writing".
        patch((t) => ({ ...t, status: result.answer ? 'done' : 'streaming', result }))
      } else if (e.type === 'delta') {
        patch((t) => (t.result ? { ...t, result: { ...t.result, answer: t.result.answer + e.text } } : t))
      } else {
        const { type: _type, ...final } = e
        patch((t) => ({ ...t, status: 'done', result: t.result ? { ...t.result, ...final } : t.result }))
      }
    }).catch((err: Error) => {
      patch((t) => (t.result && t.result.answer
        ? { ...t, status: 'done' }
        : { ...t, status: 'error', error: err.message }))
    })
  }, [activeId, chats, store])

  const deleteChat = (id: string) => {
    setChats((cs) => cs.filter((c) => c.id !== id))
    if (id === activeId) setActiveId(null)
  }
  const clearAll = () => {
    setChats((cs) => cs.filter((c) => c.store !== store))
    setActiveId(null)
    if (!chats.some((c) => c.store !== store)) clearSavedChats()
  }

  if (!authChecked) return <div className="gate" aria-busy="true" />
  if (authCfg?.auth_enabled && authCfg.google_client_id && !user && !demoOnly) {
    return <SignInScreen clientId={authCfg.google_client_id} error={signInError} onCredential={onGoogle} onDemo={enterDemo} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-left">
          <button className="icon-btn menu-btn" onClick={() => setDrawer(true)} aria-label="Open chats">
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
          </button>
          <div className="brand">
            <LogoMark />
            <Wordmark />
          </div>
        </div>
        <div className="topbar-right">
          <div className="status" title={health ? `Model: ${health.model}` : undefined}>
            <span className={`dot${offline ? ' off' : ''}`} />
            {offline ? 'API offline: start the backend' : health ? (
              current && !current.demo
                ? <>{current.name}<span className="long"> · updated {ago(current.last_synced_at)}</span></>
                : <>Willow &amp; Finch<span className="long"> · demo data to {fmtDate(health.data_as_of)}</span></>
            ) : 'Connecting…'}
          </div>
          {stores.length > 1 && (
            <select className="store-select" value={store} onChange={(e) => changeStore(e.target.value)}
              disabled={busy} aria-label="Store">
              {stores.map((s) => <option key={s.slug} value={s.slug}>{s.demo ? `${s.name} (demo)` : s.name}</option>)}
            </select>
          )}
          {user ? (
            <div className="user-menu">
              <button className="avatar" onClick={() => setMenu(!menu)} aria-label="Account" aria-expanded={menu}>
                {user.picture ? <img src={user.picture} alt="" referrerPolicy="no-referrer" /> : (user.name || user.email)[0].toUpperCase()}
              </button>
              {menu && (
                <div className="menu-pop" role="menu">
                  <div className="menu-who"><b>{user.name || user.email}</b><span>{user.email}</span></div>
                  <button role="menuitem" onClick={signOut}>Sign out</button>
                </div>
              )}
            </div>
          ) : authCfg?.auth_enabled && (
            <button className="btn signin-btn" onClick={() => { setDemoOnly(false); try { sessionStorage.removeItem('demoOnly') } catch { /* ignore */ } }}>
              Sign in
            </button>
          )}
          <button className="icon-btn" onClick={toggleTheme} aria-label="Toggle dark mode" title="Toggle dark mode">
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>
          </button>
        </div>
      </header>

      <Sidebar chats={pruneChats(storeChats)} activeId={activeId} busyIds={busyIds} open={drawer}
        onNew={() => setActiveId(null)} onSelect={setActiveId} onDelete={deleteChat} onClearAll={clearAll}
        onClose={() => setDrawer(false)} />

      <main className="scroll" ref={scroller}>
        <div className="column">
          {turns.length === 0 ? (
            <section className="welcome">
              <span className="store-chip">
                {current && !current.demo ? `${current.name} · live data` : 'Demo store · Willow & Finch, Sydney'}
              </span>
              <h1>Know your numbers</h1>
              <p>Ask about your sales in plain English. Every answer comes with the table, a chart and the query behind it.</p>
              {user && stores.every((x) => x.demo) && (
                <p className="notice">
                  You’re signed in as <b>{user.email}</b>. No store has been shared with this account yet, so you can use the
                  demo. Ask the store owner to add you.
                </p>
              )}
              <div className="examples">
                {examples.map((e) => (
                  <button key={e.question} className="example" onClick={() => submit(e.question)} disabled={busy}>
                    <small>{e.group}</small>
                    {e.question}
                  </button>
                ))}
              </div>
            </section>
          ) : (
            turns.map((t) => (
              <div className="turn" key={t.id}>
                <div className="user-row"><div className="user-bubble">{t.question}</div></div>
                <AnswerCard turn={t} onRetry={submit} />
              </div>
            ))
          )}
        </div>
      </main>

      <Composer onSubmit={submit} busy={busy} followUp={turns.length > 0} memory={health?.memory_turns}
        demo={!current || current.demo} />
    </div>
  )
}
