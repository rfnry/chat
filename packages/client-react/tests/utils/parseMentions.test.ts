import type { Identity } from '@rfnry/chat-protocol'
import { describe, expect, it } from 'vitest'
import { parseMemberMentions } from '../../src/utils/parseMentions'

const members: Identity[] = [
  { id: 'engineer', role: 'assistant', name: 'Engineer', metadata: {} },
  { id: 'coordinator', role: 'assistant', name: 'Coordinator', metadata: {} },
  { id: 'liaison', role: 'assistant', name: 'Liaison', metadata: {} },
  { id: 'u_alice', role: 'user', name: 'Alice', metadata: {} },
  { id: 'u_bob', role: 'user', name: 'Bob', metadata: {} },
]

describe('parseMemberMentions (id-only)', () => {
  it('single mention at start', () => {
    const r = parseMemberMentions('@engineer hello', members)
    expect(r.recipients).toEqual(['engineer'])
    expect(r.spans).toHaveLength(1)
    expect(r.spans[0]).toMatchObject({ identityId: 'engineer', start: 0, length: 9 })
  })

  it('single mention at end', () => {
    expect(parseMemberMentions('hello @coordinator', members).recipients).toEqual(['coordinator'])
  })

  it('two distinct mentions in first-seen order', () => {
    expect(parseMemberMentions('@engineer and @coordinator', members).recipients).toEqual([
      'engineer',
      'coordinator',
    ])
  })

  it('dedupes on recipients but spans are kept per occurrence', () => {
    const r = parseMemberMentions('@engineer and @engineer again', members)
    expect(r.recipients).toEqual(['engineer'])
    expect(r.spans).toHaveLength(2)
  })

  it('trims trailing comma', () => {
    expect(parseMemberMentions('@engineer, hi', members).recipients).toEqual(['engineer'])
  })

  it('trims trailing period', () => {
    expect(parseMemberMentions('ping @engineer.', members).recipients).toEqual(['engineer'])
  })

  it('trims trailing question mark', () => {
    expect(parseMemberMentions('@engineer?', members).recipients).toEqual(['engineer'])
  })

  it('trims multiple trailing punctuation chars', () => {
    expect(parseMemberMentions('@engineer!!!', members).recipients).toEqual(['engineer'])
  })

  it('does not match unknown ids', () => {
    expect(parseMemberMentions('@nobody hi', members).recipients).toEqual([])
  })

  it('case sensitive on id', () => {
    expect(parseMemberMentions('@Engineer hi', members).recipients).toEqual([])
  })

  it('respects optional roles filter', () => {
    expect(
      parseMemberMentions('@engineer @u_alice', members, { roles: ['user'] }).recipients
    ).toEqual(['u_alice'])
  })

  it('id with underscore matches', () => {
    expect(parseMemberMentions('@u_alice', members).recipients).toEqual(['u_alice'])
  })

  it('email-like input does not match (engineer.com is unknown id)', () => {
    expect(parseMemberMentions('contact @engineer.com', members).recipients).toEqual([])
  })

  it('span length covers @ + id (excludes trimmed punct)', () => {
    const r = parseMemberMentions('@engineer, hello', members)
    expect(r.spans[0]?.length).toBe(9)
  })

  it('span start reflects mid-text offset', () => {
    const r = parseMemberMentions('hey @engineer check', members)
    expect(r.spans[0]?.start).toBe(4)
  })

  it('mid-word @ still matches (permissive)', () => {
    expect(parseMemberMentions('foo@engineer', members).recipients).toEqual(['engineer'])
  })

  it('empty text yields empty result', () => {
    const r = parseMemberMentions('', members)
    expect(r.recipients).toEqual([])
    expect(r.spans).toEqual([])
  })

  it('text with no @ yields empty result', () => {
    expect(parseMemberMentions('hello world', members).recipients).toEqual([])
  })

  it('@ followed by whitespace is not a mention', () => {
    expect(parseMemberMentions('hello @ world', members).recipients).toEqual([])
  })

  it('three distinct mentions in first-seen order', () => {
    const r = parseMemberMentions('@engineer @coordinator @liaison go', members)
    expect(r.recipients).toEqual(['engineer', 'coordinator', 'liaison'])
  })

  it('preserves insertion order even with intermixed unknown tokens', () => {
    const r = parseMemberMentions('@engineer @nobody @liaison', members)
    expect(r.recipients).toEqual(['engineer', 'liaison'])
  })

  it('is mutation-safe on the members input', () => {
    const snapshot = members.map((m) => ({ ...m }))
    parseMemberMentions('@engineer @coordinator', members)
    expect(members).toEqual(snapshot)
  })

  it('returns a fresh result each call', () => {
    const a = parseMemberMentions('@engineer', members)
    a.recipients.push('mutated')
    const b = parseMemberMentions('@engineer', members)
    expect(b.recipients).toEqual(['engineer'])
  })

  it('empty members list matches nothing', () => {
    expect(parseMemberMentions('@engineer hi', []).recipients).toEqual([])
  })

  it('multiple text parts: the parser is text-agnostic, no boundary handling', () => {
    expect(parseMemberMentions("@engineer'", members).recipients).toEqual(['engineer'])
  })
})
