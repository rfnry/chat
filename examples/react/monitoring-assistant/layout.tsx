import type { ReactNode } from 'react'

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div style={styles.shell}>
      <header style={styles.header}>
        <h1 style={styles.title}>monitoring-assistant</h1>
        <p style={styles.subtitle}>
          Logged in as a user. Any thread the agent opens for you should appear
          here in real time, delivered via the <code>thread:invited</code> inbox
          room signal — no polling, no refresh.
        </p>
      </header>
      <main style={styles.main}>{children}</main>
      <footer style={styles.footer}>
        rfnry/chat · examples/react/monitoring-assistant
      </footer>
    </div>
  )
}

const styles = {
  shell: {
    maxWidth: 720,
    margin: '0 auto',
    padding: '24px 16px',
    fontFamily: 'system-ui, sans-serif',
  },
  header: { marginBottom: 24 },
  title: { fontSize: 20, margin: 0 },
  subtitle: { color: '#666', fontSize: 14, marginTop: 4 },
  main: { minHeight: 200 },
  footer: { marginTop: 32, fontSize: 12, color: '#999' },
} as const
