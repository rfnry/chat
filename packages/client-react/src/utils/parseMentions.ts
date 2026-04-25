import type { Identity, IdentityRole } from '@rfnry/chat-protocol'

/**
 * Characters that count as a word boundary after a mention token.
 * Letters, digits, hyphen, and underscore are NOT boundaries (to prevent
 * partial matches like @Alice matching inside @AliceBoo).
 */
const BOUNDARY_CHARS = new Set([' ', '\t', '\n', '\r', ',', '.', '!', '?', ';', ':', ')', ']', '}'])

function isBoundary(ch: string | undefined): boolean {
  return ch === undefined || BOUNDARY_CHARS.has(ch)
}

/**
 * True when text[pos : pos + candidate.length] equals candidate
 * (case-insensitive) AND the character immediately after is a word boundary.
 */
function matchesAt(text: string, pos: number, candidate: string): boolean {
  const n = candidate.length
  if (pos + n > text.length) return false
  if (text.slice(pos, pos + n).toLowerCase() !== candidate.toLowerCase()) return false
  return isBoundary(text[pos + n])
}

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
 * Extract `@name` or `@id` mentions from text, resolve them against `members`,
 * and return both the deduped recipient ids (for the wire) and the positional
 * spans (for local render highlighting).
 *
 * Uses a member-aware longest-prefix scanner (no regex) so names with spaces
 * (e.g. "Agent A") are matched correctly. Ambiguity is resolved by longest
 * match — "Agent A" wins over a shorter "Agent" member.
 *
 * Role-neutral by default. Narrow with `opts.roles` when a UI needs
 * role-specific semantics (e.g. assistants-only for a "summon agent" bar).
 *
 * - `@<name>` — matched case-insensitively against member display names.
 * - `@<id>` — fallback when no name matches.
 * - `@here` — expands to all role-filtered members (when hereExpansion !== 'none').
 * - Unknown mentions are silently ignored.
 * - Recipients are deduped, preserving first-seen order.
 * - The `@` must be preceded by a word boundary (or start-of-string) to
 *   prevent false positives in email addresses (foo@Alice → no match).
 */
export function parseMemberMentions(
  text: string,
  members: Identity[],
  opts: ParseMemberMentionsOptions = {}
): ParseMentionsResult {
  const roles = opts.roles
  const hereExpansion = opts.hereExpansion ?? 'matched'

  const matched = roles ? members.filter((m) => roles.includes(m.role)) : members

  // Sort longest name first; tiebreak by id length DESC so longer matches win.
  const sorted = [...matched].sort((a, b) => {
    const nameDiff = b.name.length - a.name.length
    if (nameDiff !== 0) return nameDiff
    return b.id.length - a.id.length
  })

  const seen = new Set<string>()
  const recipients: string[] = []
  const spans: MentionSpan[] = []

  const add = (id: string) => {
    if (!seen.has(id)) {
      seen.add(id)
      recipients.push(id)
    }
  }

  let i = 0
  while (i < text.length) {
    if (text[i] !== '@') {
      i++
      continue
    }

    // The character before '@' must be a boundary (or start-of-string) so that
    // email addresses like foo@Alice are not matched.
    const prevCh = i > 0 ? text[i - 1] : undefined
    if (!isBoundary(prevCh)) {
      i++
      continue
    }

    const cursor = i + 1
    let didMatch = false

    // Try each member in longest-first order.
    for (const m of sorted) {
      if (matchesAt(text, cursor, m.name)) {
        spans.push({ identityId: m.id, text: m.name, start: i, length: 1 + m.name.length })
        add(m.id)
        i = cursor + m.name.length
        didMatch = true
        break
      }
      if (matchesAt(text, cursor, m.id)) {
        spans.push({ identityId: m.id, text: m.id, start: i, length: 1 + m.id.length })
        add(m.id)
        i = cursor + m.id.length
        didMatch = true
        break
      }
    }

    if (didMatch) continue

    // Fall back to @here expansion.
    if (hereExpansion === 'matched' && matchesAt(text, cursor, 'here')) {
      for (const m of matched) add(m.id)
      i = cursor + 'here'.length
      continue
    }

    // No match — skip past this '@'.
    i++
  }

  return { recipients, spans }
}
