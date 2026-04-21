import type { ReactNode } from 'react'
import { type Role, ROLES } from './use-workspace'
import type { Workspace } from './workspaces'

export type LayoutProps = {
  workspaces: Workspace[]
  activeId: Workspace['id']
  onSelect: (id: Workspace['id']) => void
  role: Role
  onRoleChange: (role: Role) => void
  organization: string
  children: ReactNode
}

export function Layout({
  workspaces,
  activeId,
  onSelect,
  role,
  onRoleChange,
  organization,
  children,
}: LayoutProps) {
  const active = workspaces.find((w) => w.id === activeId) ?? workspaces[0]!
  return (
    <div style={styles.shell}>
      <header style={styles.header}>
        <h1 style={styles.title}>organization-workspace</h1>
        <p style={styles.subtitle}>
          One chat client, many chat servers. Tenant data (organization, workspace,
          role) flows through auth → identity metadata → agent handler.
        </p>
        <div style={styles.tenant}>
          <span style={styles.tenantLabel}>organization</span>
          <code style={styles.tenantValue}>{organization}</code>
        </div>
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
        <div style={styles.roleRow}>
          <span style={styles.roleLabel}>role</span>
          {ROLES.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => onRoleChange(r)}
              style={{
                ...styles.roleButton,
                ...(r === role ? styles.roleButtonActive : null),
              }}
            >
              {r}
            </button>
          ))}
          {active.id === 'medical' && role === 'member' && (
            <span style={styles.roleHint}>
              medical workspace gates AI access to managers
            </span>
          )}
        </div>
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
  tenant: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 12 },
  tenantLabel: { color: '#888', textTransform: 'uppercase' as const, letterSpacing: 0.5 },
  tenantValue: { background: '#f5f5f5', padding: '2px 6px', borderRadius: 3 },
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
  roleRow: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, fontSize: 12 },
  roleLabel: { color: '#888', textTransform: 'uppercase' as const, letterSpacing: 0.5 },
  roleButton: {
    padding: '4px 10px',
    border: '1px solid #ddd',
    borderRadius: 4,
    background: 'white',
    cursor: 'pointer',
    fontSize: 12,
  },
  roleButtonActive: { borderColor: '#111', background: '#111', color: 'white' },
  roleHint: { marginLeft: 8, color: '#a33', fontSize: 12 },
  main: { minHeight: 320 },
  footer: { marginTop: 32, fontSize: 12, color: '#999' },
} as const
