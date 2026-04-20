const { useState: useStateMV } = React;

/* MemoryBullet — a single learned memory the user can rate/edit */
function MemoryBullet({ mem, onVote, onEdit }) {
  const [hov, setHov] = useStateMV(false);
  const conf = mem.confidence;
  return (
    <Glass strong onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} style={{
      padding: 16, borderRadius: 14, display: "flex", gap: 14, alignItems: "flex-start",
      transition: "all 180ms cubic-bezier(.4,0,.2,1)",
      transform: hov ? "translateY(-2px)" : "none",
      boxShadow: hov ? "0 18px 40px rgba(108,134,192,.12)" : "0 12px 32px rgba(108,134,192,.08)",
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: 10, flexShrink: 0,
        background: "rgba(108,134,192,.12)", color: "#6C86C0",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <Icon name={mem.type === "skill" ? "sparkles" : "brain"} size={18} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{
            fontSize: 10, fontWeight: 600, textTransform: "uppercase",
            letterSpacing: 1, color: "#94a3b8",
          }}>{mem.category}</span>
          <span style={{ fontSize: 10, color: "#9CA3AF" }}>·</span>
          <span style={{ fontSize: 10, color: "#9CA3AF" }}>learned {mem.learned}</span>
        </div>
        <div style={{
          fontFamily: '"Inter",sans-serif', fontWeight: 500, fontSize: 14,
          color: "#1C1E2E", lineHeight: 1.5,
        }}>{mem.text}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 60, height: 4, borderRadius: 9999, background: "#E5E7EB", position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", inset: 0, width: `${conf * 100}%`, background: "#6C86C0", borderRadius: 9999 }} />
            </div>
            <span style={{ fontSize: 11, color: "#6B7280", fontFamily: '"Inter",sans-serif' }}>{Math.round(conf * 100)}% confidence</span>
          </div>
          <div style={{ flex: 1 }} />
          <IconBtn name="thumbsUp" />
          <IconBtn name="thumbsDown" />
          <IconBtn name="edit" />
        </div>
      </div>
    </Glass>
  );
}

/* AgentCard — a participant's agent summary */
function AgentCard({ agent }) {
  return (
    <Glass style={{ padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12, flexShrink: 0,
          background: agent.color,
          color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
          fontWeight: 700, fontSize: 14,
          boxShadow: "0 4px 12px rgba(108,134,192,.2)",
        }}>{agent.initials}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: '"Inter",sans-serif', fontWeight: 600, fontSize: 14, color: "#1C1E2E" }}>{agent.name}</div>
          <div style={{ fontSize: 12, color: "#6B7280" }}>{agent.role}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <div style={{ width: 8, height: 8, borderRadius: 9999, background: "#10b981" }} />
          <span style={{ fontSize: 11, color: "#6B7280" }}>Active</span>
        </div>
      </div>
      <div style={{ display: "flex", gap: 14, fontSize: 11, color: "#6B7280" }}>
        <div><strong style={{ color: "#1C1E2E", fontWeight: 600 }}>{agent.memories}</strong> memories</div>
        <div><strong style={{ color: "#1C1E2E", fontWeight: 600 }}>{agent.skills}</strong> skills</div>
        <div><strong style={{ color: "#1C1E2E", fontWeight: 600 }}>{agent.connections}</strong> integrations</div>
      </div>
    </Glass>
  );
}

/* Integration row with connect state */
function IntegrationRow({ logo, name, connected }) {
  const [hov, setHov] = useStateMV(false);
  return (
    <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} style={{
      display: "flex", alignItems: "center", gap: 12, padding: "10px 12px", borderRadius: 12,
      background: hov ? "rgba(255,255,255,.45)" : "transparent",
      border: "1px solid rgba(255,255,255,.25)",
      transition: "background 150ms cubic-bezier(.4,0,.2,1)",
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: 10, flexShrink: 0,
        background: "rgba(255,255,255,.65)", border: "1px solid rgba(255,255,255,.5)",
        display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: "0 4px 12px rgba(108,134,192,.08)",
      }}>
        <img src={logo} alt="" style={{ width: 22, height: 22 }} />
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: '"Inter",sans-serif', fontWeight: 600, fontSize: 13, color: "#1C1E2E" }}>{name}</div>
        <div style={{ fontSize: 11, color: connected ? "#10b981" : "#9CA3AF" }}>
          {connected ? "Connected" : "Not connected"}
        </div>
      </div>
      <Btn variant={connected ? "secondary" : "primary"} style={{ padding: "6px 14px", minHeight: 32, fontSize: 12 }}>
        {connected ? "Manage" : "Connect"}
      </Btn>
    </div>
  );
}

Object.assign(window, { MemoryBullet, AgentCard, IntegrationRow });
