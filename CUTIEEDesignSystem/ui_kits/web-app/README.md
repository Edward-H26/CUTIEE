# Memoria — Web App UI Kit

A hi-fi recreation of Memoria's authenticated web app, distilled from the MIRA Django codebase.

## Components
- `Primitives.jsx` — `Icon`, `MemoriaWordmark`, `Glass`, `Btn`
- `Chrome.jsx` — `Sidebar`, `TopBar`, `NavLink`, `IconBtn`
- `Conversation.jsx` — `ConversationList`, `Conversation`, `Message`
- `MemoryAndAgents.jsx` — `MemoryBullet`, `AgentCard`, `IntegrationRow`

## Screens (in `index.html`)
- **Home** — welcome + action cards + recent chats
- **Chats** — thread list, multi-agent conversation with "drawn from memory" chips
- **My Agent** — agent cards for each teammate + integrations
- **Memory** — learned memories with confidence bars, rate / edit

## Design notes
Glass everything. Single accent `#6C86C0`. Feather/Lucide icons at 2px. Pill radii = 9999; card radii = 16; button radii = 10.
