import type { Identity, IdentityRole } from '@rfnry/chat-protocol'

const TRAILING_PUNCT = new Set([',', '.', '!', '?', ';', ':', ')', ']', '}', "'", '"'])

export type MentionSpan = {
  identityId: string
  start: number
  length: number
}

export type ParseMentionsResult = {
  recipients: string[]
  spans: MentionSpan[]
}

export type ParseMemberMentionsOptions = {
  roles?: IdentityRole[]
}

export function parseMemberMentions(
  text: string,
  members: Identity[],
  opts: ParseMemberMentionsOptions = {}
): ParseMentionsResult {
  const eligible = opts.roles ? members.filter((m) => opts.roles!.includes(m.role)) : members
  const memberIds = new Set(eligible.map((m) => m.id))

  const seen = new Set<string>()
  const recipients: string[] = []
  const spans: MentionSpan[] = []

  let i = 0
  while (i < text.length) {
    if (text[i] !== '@') {
      i++
      continue
    }
    let j = i + 1
    while (j < text.length && !/\s/.test(text[j]!)) j++
    let token = text.slice(i + 1, j)
    let trimEnd = j
    while (token.length > 0 && TRAILING_PUNCT.has(token[token.length - 1]!)) {
      token = token.slice(0, -1)
      trimEnd--
    }
    if (token && memberIds.has(token)) {
      if (!seen.has(token)) {
        seen.add(token)
        recipients.push(token)
      }
      spans.push({ identityId: token, start: i, length: trimEnd - i })
    }
    i = j > i ? j : i + 1
  }

  return { recipients, spans }
}
