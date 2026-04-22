import type { Identity, IdentityRole } from '@rfnry/chat-protocol'

const MENTION_RE = /@([\w-]+)/g

export type MentionSpan = {
  identityId: string
  text: string
  start: number
  length: number
}

export type ParseMentionsResult = {
  recipients: string[]
  spans: MentionSpan[]
}

export type ParseMemberMentionsOptions = {
  /**
   * Filter `members` down to these roles before matching. When omitted, every
   * role is considered — useful for user-to-user mentions, assistant-to-user
   * mentions, or mixed-role threads. Pass `['assistant']` for the classic
   * "summon an agent" UX.
   */
  roles?: IdentityRole[]
  /**
   * How to treat `@here`. `'matched'` (default) expands to every member that
   * survived the role filter, in first-seen order. `'none'` skips the magic
   * expansion entirely — `@here` then resolves via normal name matching (i.e.
   * only hits if a member is actually named "here") or is dropped as unknown.
   */
  hereExpansion?: 'none' | 'matched'
}

/**
 * Extract `@name` mentions from text, resolve them against `members`, and
 * return both the deduped recipient ids (for the wire) and the positional
 * spans (for local render highlighting).
 *
 * Role-neutral by default. Narrow with `opts.roles` when a UI needs
 * role-specific semantics (e.g. assistants-only for a "summon agent" bar).
 *
 * - Matches `@name` tokens (word characters + hyphen) against member names,
 *   case-insensitively.
 * - `@here` expansion does not emit a span (it resolves to multiple identities).
 * - Unknown mentions are silently ignored.
 * - Recipients are deduped, preserving first-seen order.
 */
export function parseMemberMentions(
  text: string,
  members: Identity[],
  opts: ParseMemberMentionsOptions = {}
): ParseMentionsResult {
  const roles = opts.roles
  const hereExpansion = opts.hereExpansion ?? 'matched'
  const matched = roles ? members.filter((m) => roles.includes(m.role)) : members
  const byLowercaseName = new Map<string, Identity>()
  for (const m of matched) {
    byLowercaseName.set(m.name.toLowerCase(), m)
  }

  const seen = new Set<string>()
  const recipients: string[] = []
  const spans: MentionSpan[] = []

  const add = (id: string) => {
    if (!seen.has(id)) {
      seen.add(id)
      recipients.push(id)
    }
  }

  for (const match of text.matchAll(MENTION_RE)) {
    const raw = match[1]!
    const token = raw.toLowerCase()
    if (token === 'here' && hereExpansion === 'matched') {
      for (const m of matched) add(m.id)
      continue
    }
    const hit = byLowercaseName.get(token)
    if (!hit) continue
    add(hit.id)
    spans.push({
      identityId: hit.id,
      text: raw,
      start: match.index ?? 0,
      length: match[0].length,
    })
  }

  return { recipients, spans }
}
