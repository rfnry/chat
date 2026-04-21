import type { ReactNode } from 'react'

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div style={styles.shell}>
      <header style={styles.header}>
        <h1 style={styles.title}>stock-tool</h1>
        <p style={styles.subtitle}>
          Server-side tool handlers — no AI agent. The user emits{' '}
          <code>tool.call</code> events; <code>@server.on_tool_call</code> answers
          inline.
        </p>
      </header>
      <main style={styles.main}>{children}</main>
      <footer style={styles.footer}>rfnry/chat · examples/react/stock-tool</footer>
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
