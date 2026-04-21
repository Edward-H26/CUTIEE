// Shared Memoria tokens + tiny primitive components.
// Drop into window so all <script type="text/babel"> files share.
const { useState } = React;

/* --- Icon (Feather/Lucide 2px stroke) --- */
function Icon({ name, size = 20, color = "currentColor", strokeWidth = 2 }) {
  const paths = {
    message: <><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></>,
    search: <><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></>,
    file: <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></>,
    link: <><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></>,
    users: <><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></>,
    plus: <><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></>,
    send: <><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></>,
    brain: <><path d="M9.5 2A2.5 2.5 0 0112 4.5v15a2.5 2.5 0 01-4.96.44 2.5 2.5 0 01-2.96-3.08 3 3 0 01-.34-5.58 2.5 2.5 0 011.32-4.24 2.5 2.5 0 014.44-1.04z"/><path d="M14.5 2A2.5 2.5 0 0012 4.5v15a2.5 2.5 0 004.96.44 2.5 2.5 0 002.96-3.08 3 3 0 00.34-5.58 2.5 2.5 0 00-1.32-4.24 2.5 2.5 0 00-4.44-1.04z"/></>,
    sparkles: <><path d="M12 3l1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></>,
    bell: <><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></>,
    home: <><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></>,
    arrowRight: <><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></>,
    thumbsUp: <><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></>,
    thumbsDown: <><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3zm7-13h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17"/></>,
    edit: <><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 113 3L7 19l-4 1 1-4z"/></>,
    x: <><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></>,
    logo3: null, // special
    chev: <><polyline points="6 9 12 15 18 9"/></>,
    paperclip: <><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></>,
    book: <><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></>,
    bars: <><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></>,
    help: <><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></>,
    shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></>,
  };
  if (name === "logo3") {
    return (
      <svg width={size} height={size * (40/43)} viewBox="0 0 43 40" fill={color} xmlns="http://www.w3.org/2000/svg">
        <circle cx="10" cy="30" r="10"/><circle cx="21.5" cy="10" r="10"/><circle cx="33" cy="30" r="10"/>
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      {paths[name] || null}
    </svg>
  );
}

/* --- Wordmark --- */
function MemoriaWordmark({ size = 22 }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <img src="../../assets/logo-mark.png" alt=""
        style={{ width: size * 1.15, height: size * 1.15, display: "block" }} />
      <span style={{
        fontFamily: '"Manrope", sans-serif', fontWeight: 800, fontSize: size,
        letterSpacing: "-1px", color: "#6C86C0",
      }}>Memoria</span>
    </div>
  );
}

/* --- Glass card primitive --- */
function Glass({ children, style, strong, hover, ...rest }) {
  return (
    <div {...rest} style={{
      background: strong ? "rgba(255,255,255,.7)" : "rgba(255,255,255,.55)",
      border: "1px solid rgba(255,255,255,.55)",
      backdropFilter: "saturate(150%) blur(20px)",
      WebkitBackdropFilter: "saturate(150%) blur(20px)",
      borderRadius: 16,
      boxShadow: hover ? "0 18px 40px rgba(108,134,192,.12)" : "0 12px 32px rgba(108,134,192,.08)",
      ...style,
    }}>{children}</div>
  );
}

/* --- Button --- */
function Btn({ variant = "primary", children, icon, onClick, style }) {
  const [hov, setHov] = useState(false);
  const [press, setPress] = useState(false);
  const base = {
    border: 0, borderRadius: 10, padding: "12px 22px", minHeight: 44,
    fontFamily: '"Inter",sans-serif', fontWeight: 600, fontSize: 14,
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
    cursor: "pointer", transition: "all 180ms cubic-bezier(.4,0,.2,1)",
    transform: press ? "scale(.97)" : (hov ? "translateY(-1px)" : "none"),
    ...style,
  };
  const vs = {
    primary: {
      background: hov ? (press ? "#4A6399" : "#5A74AD") : "#6C86C0",
      color: "#fff",
      boxShadow: hov ? "0 8px 20px rgba(108,134,192,.25)" : "0 4px 12px rgba(108,134,192,.18)",
    },
    ghost: {
      background: hov ? "rgba(255,255,255,.9)" : "rgba(255,255,255,.7)",
      border: "1px solid rgba(255,255,255,.7)", color: "#0f172a",
      backdropFilter: "blur(14px)",
    },
    secondary: {
      background: hov ? "#F5F6FA" : "#fff", border: "1px solid #E5E7EB", color: "#1C1E2E",
    },
    cta: {
      background: "#6C86C0", color: "#fff",
      boxShadow: hov ? "0 14px 30px rgba(108,134,192,.35)" : "0 10px 24px rgba(108,134,192,.28)",
    },
  };
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => { setHov(false); setPress(false); }}
      onMouseDown={() => setPress(true)} onMouseUp={() => setPress(false)}
      style={{ ...base, ...vs[variant] }}>
      {children}
      {icon && <Icon name={icon} size={16} />}
    </button>
  );
}

Object.assign(window, { Icon, MemoriaWordmark, Glass, Btn });
