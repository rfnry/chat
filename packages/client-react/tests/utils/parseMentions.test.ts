import type { Identity } from '@rfnry/chat-protocol'
import { describe, expect, it } from 'vitest'
import { parseMemberMentions } from '../../src/utils/parseMentions'

// ---------------------------------------------------------------------------
// Shared fixtures (original suite)
// ---------------------------------------------------------------------------
const alice: Identity = { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} }
const bob: Identity = { role: 'user', id: 'u_bob', name: 'Bob', metadata: {} }
const helper: Identity = { role: 'assistant', id: 'a_helper', name: 'Helper', metadata: {} }
const codex: Identity = { role: 'assistant', id: 'a_codex', name: 'Codex', metadata: {} }
const system: Identity = { role: 'system', id: 's_1', name: 'System', metadata: {} }

// ---------------------------------------------------------------------------
// Plan test fixture (task-1 cases from the implementation plan)
// ---------------------------------------------------------------------------
const planMembers: Identity[] = [
  { id: 'agent-a', role: 'assistant', name: 'Agent A', metadata: {} },
  { id: 'agent-b', role: 'assistant', name: 'Agent B', metadata: {} },
  { id: 'u_alice', role: 'user', name: 'Alice', metadata: {} },
  { id: 'u_bob', role: 'user', name: 'Bobby Smith', metadata: {} },
]

// ---------------------------------------------------------------------------
// Task-1 plan test cases (12 cases verbatim from the implementation plan)
// ---------------------------------------------------------------------------
describe('parseMemberMentions (plan test cases)', () => {
  // 1. Single-word name
  it('1. single-word name', () => {
    const result = parseMemberMentions('@Alice hi', planMembers)
    expect(result.recipients).toEqual(['u_alice'])
    expect(result.spans).toEqual([{ identityId: 'u_alice', text: 'Alice', start: 0, length: 6 }])
  })

  // 2. Multi-word name
  it('2. multi-word name', () => {
    const result = parseMemberMentions('@Agent A what is up?', planMembers)
    expect(result.recipients).toEqual(['agent-a'])
    expect(result.spans).toEqual([{ identityId: 'agent-a', text: 'Agent A', start: 0, length: 8 }])
  })

  // 3. ID form
  it('3. @id fallback form', () => {
    const result = parseMemberMentions('@agent-b can you handle this?', planMembers)
    expect(result.recipients).toEqual(['agent-b'])
    expect(result.spans).toEqual([{ identityId: 'agent-b', text: 'agent-b', start: 0, length: 8 }])
  })

  // 4. Multi-word with trailing punctuation
  it('4. multi-word name with trailing punctuation', () => {
    const result = parseMemberMentions('@Bobby Smith, please review', planMembers)
    expect(result.recipients).toEqual(['u_bob'])
  })

  // 5. Two distinct mentions
  it('5. two distinct mentions', () => {
    const result = parseMemberMentions('@Agent A and @Agent B', planMembers)
    expect(result.recipients).toEqual(['agent-a', 'agent-b'])
  })

  // 6. Same mention twice — deduped recipients, both spans recorded
  it('6. same mention twice — deduped recipients, both spans kept', () => {
    const result = parseMemberMentions('@Agent A and @Agent A again', planMembers)
    expect(result.recipients).toHaveLength(1)
    expect(result.recipients).toEqual(['agent-a'])
    expect(result.spans).toHaveLength(2)
  })

  // 7. Unknown mention — silently dropped
  it('7. unknown mention silently dropped', () => {
    const result = parseMemberMentions('@Nobody hi', planMembers)
    expect(result.recipients).toEqual([])
    expect(result.spans).toEqual([])
  })

  // 8. Ambiguity — longest match wins
  it('8. longest match wins over shorter prefix member', () => {
    const m2: Identity[] = [
      { id: 'agent', role: 'assistant', name: 'Agent', metadata: {} },
      { id: 'agent-a', role: 'assistant', name: 'Agent A', metadata: {} },
    ]
    const result = parseMemberMentions('@Agent A hi', m2)
    expect(result.recipients).toEqual(['agent-a'])
  })

  // 9. @here expansion with role filter
  it('9. @here expands to role-filtered members only', () => {
    const result = parseMemberMentions('@here ping', planMembers, { roles: ['assistant'] })
    expect(result.recipients).toEqual(['agent-a', 'agent-b'])
  })

  // 10. Boundary respected — no partial match inside a longer token
  it('10. no match when boundary is absent after name (@AliceBoo)', () => {
    const result = parseMemberMentions('@AliceBoo', planMembers)
    expect(result.recipients).toEqual([])
  })

  // 11. Case-insensitive name match
  it('11. case-insensitive match', () => {
    const result = parseMemberMentions('@agent a hi', planMembers)
    expect(result.recipients).toEqual(['agent-a'])
  })

  // 12. Mention in mid-text — span.start is correct
  it('12. mention mid-text — span.start reflects offset', () => {
    const result = parseMemberMentions('hey @Agent A check this', planMembers)
    expect(result.recipients).toEqual(['agent-a'])
    expect(result.spans[0]!.start).toBe(4)
  })
})

// ---------------------------------------------------------------------------
// Email-address guard (pre-@ boundary check)
// ---------------------------------------------------------------------------
describe('parseMemberMentions (email guard)', () => {
  it('does not match @name when preceded by a non-boundary character (email address)', () => {
    const result = parseMemberMentions('foo@Alice', [alice])
    expect(result.recipients).toEqual([])
    expect(result.spans).toEqual([])
  })

  it('matches @name when @ is at start-of-string', () => {
    const result = parseMemberMentions('@Alice hi', [alice])
    expect(result.recipients).toEqual(['u_alice'])
  })

  it('matches @name when @ is preceded by whitespace', () => {
    const result = parseMemberMentions('hi @Alice', [alice])
    expect(result.recipients).toEqual(['u_alice'])
  })
})

// ---------------------------------------------------------------------------
// Original suite — preserved and updated for new span.text contract
// (text is now the canonical member name, not the raw input token)
// ---------------------------------------------------------------------------
describe('parseMemberMentions (original suite)', () => {
  describe('default (role-neutral)', () => {
    it('matches any member by name, regardless of role', () => {
      expect(parseMemberMentions('hey @alice and @helper', [alice, helper]).recipients).toEqual([
        'u_alice',
        'a_helper',
      ])
    })

    it('case-insensitive', () => {
      expect(parseMemberMentions('@ALICE @HELPER', [alice, helper]).recipients).toEqual([
        'u_alice',
        'a_helper',
      ])
    })

    it('@here expands to all members in first-seen thread order', () => {
      expect(parseMemberMentions('ping @here', [helper, alice, codex]).recipients).toEqual([
        'a_helper',
        'u_alice',
        'a_codex',
      ])
    })

    it('silently drops unknown mentions', () => {
      expect(parseMemberMentions('@nobody @alice', [alice]).recipients).toEqual(['u_alice'])
    })

    it('dedupes repeated mentions, preserving first-seen order', () => {
      expect(parseMemberMentions('@alice @helper @alice', [alice, helper]).recipients).toEqual([
        'u_alice',
        'a_helper',
      ])
    })

    it('returns empty recipients and spans for plain text', () => {
      const result = parseMemberMentions('hello world', [alice, helper])
      expect(result.recipients).toEqual([])
      expect(result.spans).toEqual([])
    })

    it('merges @here with explicit mentions, still deduped', () => {
      expect(parseMemberMentions('@alice @here', [alice, helper]).recipients).toEqual([
        'u_alice',
        'a_helper',
      ])
    })

    it('spans report the positional range of each named mention', () => {
      const result = parseMemberMentions('hey @alice look', [alice])
      expect(result.spans).toHaveLength(1)
      expect(result.spans[0]).toMatchObject({
        identityId: 'u_alice',
        // text is the canonical member name (not the raw input token)
        text: 'Alice',
        start: 4,
        length: 6,
      })
    })

    it('spans are not emitted for @here', () => {
      const result = parseMemberMentions('ping @here', [alice, helper])
      expect(result.spans).toEqual([])
    })
  })

  describe('roles filter', () => {
    it("roles: ['assistant'] matches the classic summon-agent UX", () => {
      expect(
        parseMemberMentions('@alice @helper', [alice, helper], { roles: ['assistant'] }).recipients
      ).toEqual(['a_helper'])
    })

    it("roles: ['user'] supports user-to-user mentions", () => {
      expect(
        parseMemberMentions('@alice @helper @bob', [alice, bob, helper], { roles: ['user'] })
          .recipients
      ).toEqual(['u_alice', 'u_bob'])
    })

    it('roles narrows @here to matching roles only', () => {
      expect(
        parseMemberMentions('@here', [alice, bob, helper, system], { roles: ['user'] }).recipients
      ).toEqual(['u_alice', 'u_bob'])
    })

    it('empty roles list matches nothing', () => {
      expect(
        parseMemberMentions('@alice @helper', [alice, helper], { roles: [] }).recipients
      ).toEqual([])
    })
  })

  describe('hereExpansion', () => {
    it("'matched' is the default and expands @here", () => {
      expect(parseMemberMentions('@here', [alice, helper]).recipients).toEqual([
        'u_alice',
        'a_helper',
      ])
    })

    it("'none' skips @here expansion (falls through to name lookup)", () => {
      // No member named "here" — unknown, dropped.
      expect(
        parseMemberMentions('@here', [alice, helper], { hereExpansion: 'none' }).recipients
      ).toEqual([])
    })

    it("'none' still resolves @here if a member happens to be named 'here'", () => {
      const namedHere: Identity = { role: 'user', id: 'u_here', name: 'here', metadata: {} }
      expect(
        parseMemberMentions('@here', [alice, namedHere], { hereExpansion: 'none' }).recipients
      ).toEqual(['u_here'])
    })
  })
})
