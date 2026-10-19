import { useState } from 'react'
import { groupChats, type Chat } from '../chats'

interface Props {
  chats: Chat[]
  activeId: string | null
  busyIds: Set<string>
  open: boolean
  onNew: () => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onClearAll: () => void
  onClose: () => void
}

export function Sidebar({ chats, activeId, busyIds, open, onNew, onSelect, onDelete, onClearAll, onClose }: Props) {
  const [confirmClear, setConfirmClear] = useState(false)
  const groups = groupChats(chats)
  return (
    <>
      <div className={`scrim${open ? ' show' : ''}`} onClick={onClose} aria-hidden="true" />
      <aside className={`sidebar${open ? ' open' : ''}`} aria-label="Chats">
        <button className="new-chat" onClick={() => { onNew(); onClose() }}>
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></svg>
          New chat
        </button>

        <nav className="chat-list">
          {groups.length === 0 && <p className="chat-empty">Your chats will appear here. Each chat remembers its own conversation.</p>}
          {groups.map((g) => (
            <section key={g.label}>
              <h3>{g.label}</h3>
              {g.chats.map((c) => (
                <div key={c.id} className={`chat-item${c.id === activeId ? ' active' : ''}`}>
                  <button className="chat-open" onClick={() => { onSelect(c.id); onClose() }} aria-current={c.id === activeId}>
                    {busyIds.has(c.id) && <span className="dots mini" aria-label="Answering"><i /><i /><i /></span>}
                    <span className="chat-title">{c.title}</span>
                  </button>
                  <button className="chat-del" onClick={() => onDelete(c.id)} aria-label={`Delete chat: ${c.title}`} title="Delete chat">
                    <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
                  </button>
                </div>
              ))}
            </section>
          ))}
        </nav>

        <div className="sidebar-foot">
          {chats.length > 0 && (confirmClear ? (
            <div className="confirm">
              <span>Delete all {chats.length} chats?</span>
              <button onClick={() => { onClearAll(); setConfirmClear(false) }}>Delete</button>
              <button onClick={() => setConfirmClear(false)}>Keep</button>
            </div>
          ) : (
            <button className="link-btn" onClick={() => setConfirmClear(true)}>Clear all chats</button>
          ))}
          <p>Saved only in this browser, for 7 days.</p>
        </div>
      </aside>
    </>
  )
}
