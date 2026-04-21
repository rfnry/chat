import type { ReactNode } from 'react'

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div style={styles.shell}>
      <header style={styles.header}>
        <h1 style={styles.title}>customer-support</h1>
        <p style={styles.subtitle}>
          External AI agent (rfnry-chat-client + Anthropic) joins the thread as
          a participant. The UI addresses it via <code>recipients=['cs-agent']</code>{' '}
          and watches <code>useThreadIsWorking</code> while the agent runs.
        </p>
      </header>
      <main style={styles.main}>{children}</main>
      <footer style={styles.footer}>
        rfnry/chat · examples/react/customer-support
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
  header: { borderBottom: '1px solid #eee', paddingBottom: 12, marginBottom: 16 },
  title: { margin: 0, fontSize: 24 },
  subtitle: { margin: '4px 0 0', color: '#555', fontSize: 14 },
  main: { minHeight: 320 },
  footer: { marginTop: 32, fontSize: 12, color: '#999' },
} as const
