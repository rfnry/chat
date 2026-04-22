import type { Identity } from '@rfnry/chat-protocol'
import { describe, expect, it } from 'vitest'
import { identitiesEqual } from '../../src/provider/ChatProvider'

const base: Identity = { role: 'user', id: 'u_1', name: 'Alice', metadata: {} }

describe('identitiesEqual', () => {
  it('returns true when id+role+name are equal even if metadata differs', () => {
    const a: Identity = { ...base, metadata: { foo: 1 } }
    const b: Identity = { ...base, metadata: { foo: 2, bar: 'extra' } }
    expect(identitiesEqual(a, b)).toBe(true)
  })

  it('returns false when id differs', () => {
    const a: Identity = { ...base, id: 'u_1' }
    const b: Identity = { ...base, id: 'u_2' }
    expect(identitiesEqual(a, b)).toBe(false)
  })

  it('returns false when role differs', () => {
    const a: Identity = { ...base, role: 'user' }
    const b: Identity = { ...base, role: 'assistant' }
    expect(identitiesEqual(a, b)).toBe(false)
  })

  it('handles null/undefined symmetrically', () => {
    expect(identitiesEqual(null, null)).toBe(true)
    expect(identitiesEqual(undefined, undefined)).toBe(true)
    expect(identitiesEqual(null, undefined)).toBe(true)
    expect(identitiesEqual(undefined, null)).toBe(true)
    expect(identitiesEqual(null, base)).toBe(false)
    expect(identitiesEqual(base, null)).toBe(false)
    expect(identitiesEqual(undefined, base)).toBe(false)
    expect(identitiesEqual(base, undefined)).toBe(false)
  })
})
