import type { ReactNode } from 'react'
import type { Workspace } from './workspaces'

export type LayoutProps = {
  workspaces: Workspace[]
  activeId: Workspace['id']
  onSelect: (id: Workspace['id']) => void
  children: ReactNode
}

export function Layout({ workspaces, activeId, onSelect, children }: LayoutProps) {
  const active = workspaces.find((w) => w.id === activeId) ?? workspaces[0]!
  return (
    <div style={styles.shell}>
      <header style={styles.header}>
        <h1 style={styles.title}>organization-workspace</h1>
        <p style={styles.subtitle}>
          One chat client, many chat servers. Each workspace runs its own backend
          + specialized AI. Switching workspaces disconnects from the current
          server and reconnects to the new one.
        </p>
        <nav style={styles.nav}>
          {workspaces.map((w) => {
            const isActive = w.id === active.id
            return (
              <button
                key={w.id}
                type="button"
                onClick={() => onSelect(w.id)}
                style={{
                  ...styles.navButton,
                  ...(isActive ? styles.navButtonActive : null),
                }}
              >
                {w.label}
                <span style={styles.navUrl}>{w.url}</span>
              </button>
            )
          })}
        </nav>
      </header>
      <main style={styles.main}>{children}</main>
      <footer style={styles.footer}>
        rfnry/chat · examples/react/organization-workspace
      </footer>
    </div>
  )
}

const styles = {
  shell: {
    maxWidth: 720,
    margin: '0 auto',
    padding: 24,
    fontFamily: 'system-ui, -apple-system, sans-serif',
    color: '#111',
  },
  header: { borderBottom: '1px solid #eee', paddingBottom: 16, marginBottom: 16 },
  title: { margin: 0, fontSize: 24 },
  subtitle: { margin: '4px 0 12px', color: '#555', fontSize: 14 },
  nav: { display: 'flex', gap: 8 },
  navButton: {
    flex: 1,
    padding: '8px 12px',
    border: '1px solid #ddd',
    borderRadius: 4,
    background: 'white',
    cursor: 'pointer',
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'flex-start',
  },
  navButtonActive: {
    borderColor: '#111',
    background: '#111',
    color: 'white',
  },
  navUrl: { fontSize: 11, opacity: 0.7, marginTop: 2 },
  main: { minHeight: 320 },
  footer: { marginTop: 32, fontSize: 12, color: '#999' },
} as const
