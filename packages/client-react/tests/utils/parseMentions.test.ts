import type { Identity } from '@rfnry/chat-protocol'
import { describe, expect, it } from 'vitest'
import { parseMemberMentions } from '../../src/utils/parseMentions'

const alice: Identity = { role: 'user', id: 'u_alice', name: 'Alice', metadata: {} }
const bob: Identity = { role: 'user', id: 'u_bob', name: 'Bob', metadata: {} }
const helper: Identity = { role: 'assistant', id: 'a_helper', name: 'Helper', metadata: {} }
const codex: Identity = { role: 'assistant', id: 'a_codex', name: 'Codex', metadata: {} }
const system: Identity = { role: 'system', id: 's_1', name: 'System', metadata: {} }

describe('parseMemberMentions', () => {
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
        text: 'alice',
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
      // No member named "here" → unknown, dropped.
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
