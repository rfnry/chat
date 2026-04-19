import type { AssistantIdentity, Identity } from '../protocol/identity'

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

/**
 * Extract `@name` mentions from text, resolve them to assistant ids, and
 * return both the deduped recipient ids (for the wire) and the positional
 * spans (for local render highlighting).
 *
 * - Matches `@name` tokens (word characters + hyphen) against assistant names,
 *   case-insensitively.
 * - `@here` expands to every assistant in `members` in first-seen order. It
 *   does not emit a span, since it does not resolve to a single identity.
 * - Unknown mentions are silently ignored.
 * - Recipients are deduped, preserving first-seen order.
 * - Non-assistant identities are always ignored.
 */
export function parseMentions(text: string, members: Identity[]): ParseMentionsResult {
  const assistants = members.filter((m): m is AssistantIdentity => m.role === 'assistant')
  const byLowercaseName = new Map<string, AssistantIdentity>()
  for (const a of assistants) {
    byLowercaseName.set(a.name.toLowerCase(), a)
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
    if (token === 'here') {
      for (const a of assistants) add(a.id)
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
