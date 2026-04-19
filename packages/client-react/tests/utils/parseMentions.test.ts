import { describe, expect, it } from 'vitest'
import type { Identity } from '../../src/protocol/identity'
import { parseMentions } from '../../src/utils/parseMentions'

const alice: Identity = { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} }
const helper: Identity = { role: 'assistant', id: 'a_helper', name: 'Helper', metadata: {} }
const codex: Identity = { role: 'assistant', id: 'a_codex', name: 'Codex', metadata: {} }
const system: Identity = { role: 'system', id: 's_1', name: 'System', metadata: {} }

describe('parseMentions', () => {
  it('matches an assistant by exact name (case-insensitive)', () => {
    expect(parseMentions('hey @helper do X', [alice, helper]).recipients).toEqual(['a_helper'])
    expect(parseMentions('hey @HELPER do X', [alice, helper]).recipients).toEqual(['a_helper'])
  })

  it('ignores non-assistant identities', () => {
    expect(parseMentions('@alice @helper', [alice, helper]).recipients).toEqual(['a_helper'])
  })

  it('@here expands to all assistants in first-seen thread order', () => {
    expect(parseMentions('ping @here', [helper, codex, alice]).recipients).toEqual([
      'a_helper',
      'a_codex',
    ])
  })

  it('silently drops unknown mentions', () => {
    expect(parseMentions('@nobody @helper', [helper]).recipients).toEqual(['a_helper'])
  })

  it('dedupes repeated mentions but preserves first-seen order', () => {
    expect(parseMentions('@helper @codex @helper', [helper, codex]).recipients).toEqual([
      'a_helper',
      'a_codex',
    ])
  })

  it('returns empty recipients and spans for plain text', () => {
    const result = parseMentions('hello world', [helper])
    expect(result.recipients).toEqual([])
    expect(result.spans).toEqual([])
  })

  it('ignores system identities for @here', () => {
    expect(parseMentions('@here', [system, helper]).recipients).toEqual(['a_helper'])
  })

  it('merges @here with explicit mentions, still deduped', () => {
    expect(parseMentions('@helper @here', [helper, codex]).recipients).toEqual([
      'a_helper',
      'a_codex',
    ])
  })

  it('spans report the positional range of each named mention', () => {
    const result = parseMentions('hey @helper look', [helper])
    expect(result.spans).toHaveLength(1)
    expect(result.spans[0]).toMatchObject({
      identityId: 'a_helper',
      text: 'helper',
      start: 4,
      length: 7,
    })
  })

  it('spans are not emitted for @here', () => {
    const result = parseMentions('ping @here', [helper, codex])
    expect(result.spans).toEqual([])
    expect(result.recipients).toEqual(['a_helper', 'a_codex'])
  })
})
