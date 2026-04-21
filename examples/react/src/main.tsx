import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { App as CustomerSupport } from './examples/customer-support/app'
import { App as OrganizationWorkspace } from './examples/organization-workspace/app'
import { App as StockTool } from './examples/stock-tool/app'
import './styles.css'

type ExampleId = 'stock-tool' | 'customer-support' | 'organization-workspace'

const EXAMPLES: { id: ExampleId; label: string; hint: string }[] = [
  { id: 'stock-tool', label: 'stock-tool', hint: 'server-side tools only' },
  { id: 'customer-support', label: 'customer-support', hint: 'external AI agent' },
  { id: 'organization-workspace', label: 'organization-workspace', hint: 'multi-workspace switcher' },
]

function Root() {
  const [active, setActive] = useState<ExampleId>('stock-tool')
  return (
    <div className="min-h-screen max-w-3xl mx-auto px-6 py-8 font-mono">
      <h1 className="text-xl mb-1">rfnry/chat — react examples</h1>
      <p className="text-xs text-neutral-500 mb-4">
        pick a demo. each talks to its own Python backend on the port below.
      </p>
      <nav className="flex gap-2 mb-6">
        {EXAMPLES.map((e) => (
          <button
            key={e.id}
            type="button"
            onClick={() => setActive(e.id)}
            className={`px-3 py-2 border text-xs flex flex-col items-start gap-0.5 flex-1 ${
              e.id === active
                ? 'border-neutral-200 bg-neutral-200 text-black'
                : 'border-neutral-700 text-neutral-300 hover:border-neutral-500'
            }`}
          >
            <span>{e.label}</span>
            <span className={`text-[10px] ${e.id === active ? 'text-neutral-600' : 'text-neutral-500'}`}>
              {e.hint}
            </span>
          </button>
        ))}
      </nav>
      {active === 'stock-tool' && <StockTool key="stock-tool" />}
      {active === 'customer-support' && <CustomerSupport key="customer-support" />}
      {active === 'organization-workspace' && <OrganizationWorkspace key="organization-workspace" />}
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
