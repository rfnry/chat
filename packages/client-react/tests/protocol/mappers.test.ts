import { describe, expect, it } from 'vitest'
import {
  toContentPart,
  toContentPartWire,
  toEvent,
  toEventDraftWire,
  toIdentity,
  toRun,
  toThread,
  toThreadMember,
} from '../../src/protocol/mappers'
import { tenantMatches } from '../../src/protocol/tenant'

describe('mappers', () => {
  it('toThread converts snake_case to camelCase', () => {
    const t = toThread({
      id: 'th_1',
      tenant: { org: 'A' },
      metadata: {},
      created_at: '2026-04-10T00:00:00Z',
      updated_at: '2026-04-10T00:01:00Z',
    })
    expect(t.createdAt).toBe('2026-04-10T00:00:00Z')
    expect(t.updatedAt).toBe('2026-04-10T00:01:00Z')
    expect(t.tenant).toEqual({ org: 'A' })
  })

  it('toIdentity preserves role discriminator', () => {
    const i = toIdentity({ role: 'assistant', id: 'a1', name: 'H', metadata: {} })
    expect(i.role).toBe('assistant')
  })

  it('toContentPart converts audio duration_ms → durationMs', () => {
    const p = toContentPart({
      type: 'audio',
      url: 'x',
      mime: 'a/b',
      duration_ms: 1234,
    })
    if (p.type === 'audio') {
      expect(p.durationMs).toBe(1234)
    } else {
      throw new Error('expected audio')
    }
  })

  it('toContentPart converts form_id → formId', () => {
    const p = toContentPart({
      type: 'form',
      form_id: 'f1',
      schema: {},
      status: 'pending',
    })
    if (p.type === 'form') {
      expect(p.formId).toBe('f1')
    } else {
      throw new Error('expected form')
    }
  })

  it('toContentPartWire round-trips audio', () => {
    const wire = toContentPartWire({
      type: 'audio',
      url: 'x',
      mime: 'a/b',
      durationMs: 9999,
    })
    expect(wire).toMatchObject({ type: 'audio', duration_ms: 9999 })
  })

  it('toRun converts thread_id and triggered_by', () => {
    const r = toRun({
      id: 'run_1',
      thread_id: 'th_1',
      assistant: { role: 'assistant', id: 'a1', name: 'H', metadata: {} },
      triggered_by: { role: 'user', id: 'u1', name: 'A', metadata: {} },
      status: 'pending',
      started_at: '2026-04-10T00:00:00Z',
      metadata: {},
    })
    expect(r.threadId).toBe('th_1')
    expect(r.triggeredBy.id).toBe('u1')
    expect(r.startedAt).toBe('2026-04-10T00:00:00Z')
  })

  it('toEvent converts message event with content parts', () => {
    const e = toEvent({
      id: 'evt_1',
      thread_id: 'th_1',
      type: 'message',
      author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
      created_at: '2026-04-10T00:00:00Z',
      metadata: {},
      content: [{ type: 'text', text: 'hi' }],
    } as never)
    expect(e.type).toBe('message')
    if (e.type === 'message') {
      expect(e.content[0]).toEqual({ type: 'text', text: 'hi' })
    }
  })

  it('toEvent converts thread.tenant_changed with from/to', () => {
    const e = toEvent({
      id: 'evt_2',
      thread_id: 'th_1',
      type: 'thread.tenant_changed',
      author: { role: 'user', id: 'u1', name: 'A', metadata: {} },
      created_at: '2026-04-10T00:00:00Z',
      metadata: {},
      from: { org: 'A' },
      to: { org: 'B' },
    } as never)
    if (e.type === 'thread.tenant_changed') {
      expect(e.from).toEqual({ org: 'A' })
      expect(e.to).toEqual({ org: 'B' })
    } else {
      throw new Error('expected tenant_changed')
    }
  })

  it('toEvent converts run.failed with error payload', () => {
    const e = toEvent({
      id: 'evt_3',
      thread_id: 'th_1',
      type: 'run.failed',
      author: { role: 'assistant', id: 'a1', name: 'H', metadata: {} },
      created_at: '2026-04-10T00:00:00Z',
      metadata: {},
      run_id: 'run_1',
      error: { code: 'handler_error', message: 'boom' },
    } as never)
    if (e.type === 'run.failed') {
      expect(e.error.code).toBe('handler_error')
      expect(e.runId).toBe('run_1')
    } else {
      throw new Error('expected run.failed')
    }
  })

  it('toEventDraftWire converts clientId → client_id', () => {
    const wire = toEventDraftWire({
      clientId: 'cid_1',
      content: [{ type: 'text', text: 'hi' }],
    })
    expect(wire.client_id).toBe('cid_1')
  })

  it('toThreadMember converts nested identities', () => {
    const m = toThreadMember({
      thread_id: 'th_1',
      identity_id: 'u1',
      identity: { role: 'user', id: 'u1', name: 'A', metadata: {} },
      role: 'member',
      added_at: '2026-04-10T00:00:00Z',
      added_by: { role: 'user', id: 'u_sys', name: 'Sys', metadata: {} },
    })
    expect(m.threadId).toBe('th_1')
    expect(m.addedBy.id).toBe('u_sys')
  })
})

describe('tenantMatches', () => {
  it('exact match', () => {
    expect(tenantMatches({ org: 'A' }, { org: 'A' })).toBe(true)
  })
  it('identity has extra keys', () => {
    expect(tenantMatches({ org: 'A' }, { org: 'A', ws: 'X' })).toBe(true)
  })
  it('thread requires key identity lacks', () => {
    expect(tenantMatches({ org: 'A', ws: 'X' }, { org: 'A' })).toBe(false)
  })
  it('empty thread tenant matches anything', () => {
    expect(tenantMatches({}, { org: 'A' })).toBe(true)
  })
  it('value mismatch fails', () => {
    expect(tenantMatches({ org: 'A' }, { org: 'B' })).toBe(false)
  })
})
