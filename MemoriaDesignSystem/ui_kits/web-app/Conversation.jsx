const { useState: useStateCV, useRef: useRefCV, useEffect: useEffectCV } = React;

/* ConversationList — left rail inside chat */
function ConversationList({ threads, activeId, onPick, onNew }) {
  return (
    <div style={{
      width: 260, flexShrink: 0,
      borderRight: "1px solid rgba(255,255,255,.2)",
      display: "flex", flexDirection: "column",
    }}>
      <div style={{ padding: 14, display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ flex: 1, position: "relative" }}>
          <input placeholder="Search chats…" style={{
            width: "100%", boxSizing: "border-box",
            background: "rgba(255,255,255,.6)", border: "1px solid rgba(255,255,255,.4)",
            borderRadius: 8, padding: "8px 10px 8px 30px",
            fontFamily: '"Inter",sans-serif', fontSize: 12, color: "#1C1E2E", outline: "none",
          }} />
          <div style={{ position: "absolute", left: 9, top: 8, color: "#9CA3AF" }}>
            <Icon name="search" size={14} />
          </div>
        </div>
        <button onClick={onNew} style={{
          width: 32, height: 32, borderRadius: 9, border: 0, background: "#6C86C0",
          color: "#fff", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 4px 12px rgba(108,134,192,.18)",
        }}><Icon name="plus" size={16} color="#fff" /></button>
      </div>
      <div style={{
        padding: "4px 10px 8px", fontFamily: '"Inter",sans-serif',
        fontSize: 11, fontWeight: 600, letterSpacing: 0.5,
        textTransform: "uppercase", color: "#9CA3AF",
      }}>Recent</div>
      <div style={{ flex: 1, overflowY: "auto", padding: "0 10px 10px", display: "flex", flexDirection: "column", gap: 2 }}>
        {threads.map(t => (
          <ConvRow key={t.id} thread={t} active={activeId === t.id} onClick={() => onPick(t.id)} />
        ))}
      </div>
    </div>
  );
}
function ConvRow({ thread, active, onClick }) {
  const [hov, setHov] = useStateCV(false);
  return (
    <a onClick={onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{
        padding: "10px 12px", borderRadius: 12, cursor: "pointer", textDecoration: "none",
        background: active ? "rgba(255,255,255,.7)" : (hov ? "rgba(255,255,255,.35)" : "transparent"),
        border: active ? "1px solid rgba(255,255,255,.4)" : "1px solid transparent",
        boxShadow: active ? "0 4px 16px rgba(108,134,192,.1)" : "none",
        transition: "all 150ms cubic-bezier(.4,0,.2,1)",
        display: "flex", flexDirection: "column", gap: 2,
      }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div style={{
          fontFamily: '"Inter",sans-serif', fontSize: 13, fontWeight: 600,
          color: active ? "#6C86C0" : "#1C1E2E",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{thread.title}</div>
        <span style={{ fontSize: 10, color: "#9CA3AF", flexShrink: 0 }}>{thread.when}</span>
      </div>
      <div style={{
        fontSize: 12, color: "#6B7280",
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      }}>{thread.preview}</div>
    </a>
  );
}

/* Conversation view (messages + composer) */
function Conversation({ messages, onSend, participants = [] }) {
  const [draft, setDraft] = useStateCV("");
  const endRef = useRefCV(null);
  useEffectCV(() => { endRef.current?.scrollTo?.({ top: endRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);
  const submit = () => { if (draft.trim()) { onSend(draft.trim()); setDraft(""); } };
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
      {participants.length > 0 && (
        <div style={{
          padding: "10px 20px", borderBottom: "1px solid rgba(255,255,255,.25)",
          display: "flex", alignItems: "center", gap: 10,
          background: "rgba(255,255,255,.3)",
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#6B7280", textTransform: "uppercase", letterSpacing: 1 }}>Agents in this group</div>
          <div style={{ display: "flex", gap: 6 }}>
            {participants.map(p => (
              <div key={p.name} style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "4px 10px 4px 4px", borderRadius: 9999,
                background: "rgba(255,255,255,.6)", border: "1px solid rgba(255,255,255,.5)",
                fontSize: 12, color: "#1C1E2E", fontWeight: 500,
              }}>
                <span style={{
                  width: 20, height: 20, borderRadius: 9999,
                  background: p.color, color: "#fff",
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  fontWeight: 700, fontSize: 10,
                }}>{p.initials}</span>
                {p.name}
              </div>
            ))}
          </div>
        </div>
      )}
      <div ref={endRef} style={{ flex: 1, overflowY: "auto", padding: "24px 20px" }}>
        <div style={{ maxWidth: 760, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
          {messages.map((m, i) => <Message key={i} m={m} />)}
        </div>
      </div>
      <div style={{ padding: "12px 20px 20px" }}>
        <div style={{ maxWidth: 760, margin: "0 auto" }}>
          <Glass strong style={{ borderRadius: 16, padding: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <button style={{
              width: 36, height: 36, borderRadius: 9, border: 0, background: "transparent",
              color: "#6B7280", cursor: "pointer",
            }}><Icon name="paperclip" size={18} /></button>
            <input value={draft} onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
              placeholder="Ask your agent anything…"
              style={{
                flex: 1, border: 0, outline: "none", background: "transparent",
                fontFamily: '"Inter",sans-serif', fontSize: 14, color: "#1C1E2E", padding: "8px 4px",
              }} />
            <button onClick={submit} disabled={!draft.trim()} style={{
              width: 36, height: 36, borderRadius: 9, border: 0,
              background: draft.trim() ? "#6C86C0" : "#E5E7EB",
              color: "#fff", cursor: draft.trim() ? "pointer" : "default",
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: draft.trim() ? "0 4px 12px rgba(108,134,192,.25)" : "none",
              transition: "all 150ms cubic-bezier(.4,0,.2,1)",
            }}><Icon name="send" size={16} color="#fff" /></button>
          </Glass>
          <div style={{ marginTop: 8, textAlign: "center", fontSize: 11, color: "#9CA3AF" }}>
            Memoria remembers this conversation. Review what it learned in Memory.
          </div>
        </div>
      </div>
    </div>
  );
}

function Message({ m }) {
  if (m.role === "user") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <div style={{
          background: "#6C86C0", color: "#fff",
          borderRadius: "16px 16px 4px 16px",
          padding: "10px 14px", maxWidth: "78%",
          fontSize: 14, lineHeight: 1.55,
          boxShadow: "0 4px 12px rgba(108,134,192,.18)",
        }}>{m.text}</div>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
      <div style={{
        width: 32, height: 32, borderRadius: 9999, flexShrink: 0,
        background: m.agent?.color || "linear-gradient(135deg,#6C86C0,#4A6399)",
        color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
        fontWeight: 700, fontSize: 11,
      }}>{m.agent?.initials || "MA"}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        {m.agent && (
          <div style={{ fontSize: 11, color: "#6B7280", fontWeight: 600, marginBottom: 4 }}>
            {m.agent.name} <span style={{ color: "#9CA3AF", fontWeight: 400 }}>· agent</span>
          </div>
        )}
        <div style={{
          background: "rgba(255,255,255,.7)", border: "1px solid rgba(255,255,255,.6)",
          backdropFilter: "saturate(150%) blur(20px)", WebkitBackdropFilter: "saturate(150%) blur(20px)",
          borderRadius: "16px 16px 16px 4px",
          padding: "12px 16px",
          fontSize: 14, lineHeight: 1.6, color: "#1C1E2E",
          boxShadow: "0 4px 14px rgba(108,134,192,.08)",
        }}>
          {m.text}
          {m.memories && (
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px dashed rgba(108,134,192,.25)" }}>
              <div style={{ fontSize: 10, color: "#9CA3AF", fontWeight: 600, textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
                Drawn from memory
              </div>
              {m.memories.map((mem, i) => (
                <div key={i} style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "3px 9px", borderRadius: 9999, marginRight: 6, marginBottom: 4,
                  background: "rgba(108,134,192,.08)", color: "#4A6399",
                  fontSize: 11, fontWeight: 500,
                }}>
                  <Icon name="brain" size={10} color="#4A6399" />
                  {mem}
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
          <FeedbackBtn name="thumbsUp" />
          <FeedbackBtn name="thumbsDown" />
        </div>
      </div>
    </div>
  );
}
function FeedbackBtn({ name }) {
  const [hov, setHov] = useStateCV(false);
  return (
    <button onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} style={{
      width: 26, height: 26, border: 0, borderRadius: 6,
      background: hov ? "rgba(255,255,255,.6)" : "transparent",
      color: "#9CA3AF", cursor: "pointer",
    }}><Icon name={name} size={12} /></button>
  );
}

Object.assign(window, { ConversationList, Conversation, Message });
