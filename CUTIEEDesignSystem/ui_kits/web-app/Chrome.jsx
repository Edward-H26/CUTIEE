const { useState: useStateSB } = React;

function Sidebar({ active, onNav }) {
  const primary = [
    { id: "chat",      icon: "message",  label: "Chat" },
    { id: "agent",     icon: "sparkles", label: "My Agent" },
    { id: "team",      icon: "users",    label: "Team" },
    { id: "dashboard", icon: "bars",     label: "Dashboard" },
  ];
  const footer = [
    { id: "help",    icon: "help",   label: "Help" },
    { id: "privacy", icon: "shield", label: "Privacy" },
  ];
  return (
    <aside style={{
      width: 229, flexShrink: 0,
      background: "rgba(253,253,253,.6)",
      backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)",
      borderRight: "1px solid rgba(255,255,255,.2)",
      padding: "20px 12px",
      display: "flex", flexDirection: "column", gap: 4,
    }}>
      {/* Integration status card */}
      <div style={{
        background: "linear-gradient(135deg,rgba(190,170,230,.25),rgba(150,190,245,.25))",
        backdropFilter: "blur(8px)", WebkitBackdropFilter: "blur(8px)",
        border: "1px solid rgba(255,255,255,.5)",
        borderRadius: 16, padding: 12, display: "flex", gap: 10,
        alignItems: "flex-start", marginBottom: 12,
        boxShadow: "0 4px 16px rgba(108,134,192,.10)",
      }}>
        <div style={{
          width: 40, height: 40, flexShrink: 0, borderRadius: 12,
          background: "linear-gradient(135deg,#6C86C0,#6C86C0)",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 6px 14px rgba(108,134,192,.30)",
        }}>
          <Icon name="link" size={20} color="#fff" />
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontFamily: '"Inter",sans-serif', fontWeight: 600, color: "#334155", fontSize: 14, lineHeight: "20px" }}>Integrations</div>
          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
            <div style={{
              width: 6, height: 6, borderRadius: 9999, background: "#34d399",
              boxShadow: "0 0 8px rgba(52,211,153,.6)",
            }} />
            <div style={{ fontFamily: '"Inter",sans-serif', fontWeight: 500, color: "#475569", fontSize: 12, lineHeight: "16px" }}>Connected</div>
          </div>
        </div>
      </div>

      {/* Nav section label */}
      <div style={{
        fontFamily: '"Inter",sans-serif', fontWeight: 600,
        fontSize: 10, letterSpacing: 1.2, textTransform: "uppercase",
        opacity: .6, color: "#6B7280", padding: "8px 10px 4px",
      }}>Navigation</div>

      {primary.map(it => (
        <NavLink key={it.id} {...it} active={active === it.id} onClick={() => onNav(it.id)} />
      ))}

      <div style={{ flex: 1 }} />

      <div style={{ display: "flex", flexDirection: "column", gap: 2, paddingBottom: 4 }}>
        {footer.map(it => (
          <NavLink key={it.id} {...it} muted active={active === it.id} onClick={() => onNav(it.id)} />
        ))}
      </div>
    </aside>
  );
}

function NavLink({ icon, label, active, muted, onClick }) {
  const [hov, setHov] = useStateSB(false);
  const idleColor = muted ? "rgba(100,116,139,.6)" : "#6B7280";
  return (
    <a onClick={onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "10px 12px", borderRadius: 12,
        cursor: "pointer", textDecoration: "none",
        color: active ? "#6C86C0" : idleColor,
        background: active ? "rgba(255,255,255,.6)" : (hov ? "rgba(255,255,255,.3)" : "transparent"),
        border: active ? "1px solid rgba(255,255,255,.4)" : "1px solid transparent",
        boxShadow: active ? "0 4px 16px rgba(108,134,192,.15)" : "none",
        transition: "all 180ms cubic-bezier(.4,0,.2,1)",
      }}>
      <Icon name={icon} size={18} color={active ? "#6C86C0" : idleColor} />
      <span style={{
        fontFamily: '"Inter",sans-serif', fontWeight: muted ? 500 : 600, fontSize: 13,
        color: active ? "#6C86C0" : idleColor,
      }}>{label}</span>
    </a>
  );
}

function TopBar({ title, subtitle }) {
  return (
    <header style={{
      height: 64, flexShrink: 0,
      background: "rgba(253,253,253,.6)",
      backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)",
      borderBottom: "1px solid rgba(255,255,255,.2)",
      boxShadow: "0 1px 20px rgba(0,0,0,.03)",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "0 24px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <MemoriaWordmark size={20} />
        {(title || subtitle) && (
          <div style={{
            paddingLeft: 14, borderLeft: "1px solid rgba(15,23,42,.08)",
          }}>
            <div style={{
              fontFamily: '"Manrope",sans-serif', fontWeight: 700, fontSize: 16,
              letterSpacing: "-.01em", color: "#1C1E2E",
            }}>{title}</div>
            {subtitle && <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>{subtitle}</div>}
          </div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <IconBtn name="search" />
        <IconBtn name="bell" />
        <IconBtn name="settings" />
        <div style={{
          width: 40, height: 40, borderRadius: 9999, overflow: "hidden",
          background: "linear-gradient(135deg,#6C86C0,#4A6399)",
          color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
          fontWeight: 700, fontSize: 13, border: "2px solid rgba(255,255,255,.6)",
        }}>KH</div>
      </div>
    </header>
  );
}

function IconBtn({ name, onClick }) {
  const [hov, setHov] = useStateSB(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{
        width: 40, height: 40, borderRadius: 9999, border: 0,
        background: hov ? "rgba(255,255,255,.5)" : "transparent",
        color: hov ? "#6C86C0" : "#6B7280", cursor: "pointer",
        display: "flex", alignItems: "center", justifyContent: "center",
        transition: "all 150ms cubic-bezier(.4,0,.2,1)",
      }}>
      <Icon name={name} size={20} />
    </button>
  );
}

Object.assign(window, { Sidebar, TopBar, NavLink, IconBtn });
