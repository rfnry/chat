export type IdentityRole = 'user' | 'assistant' | 'system'

export type UserIdentity = {
  role: 'user'
  id: string
  name: string
  metadata: Record<string, unknown>
}

export type AssistantIdentity = {
  role: 'assistant'
  id: string
  name: string
  metadata: Record<string, unknown>
}

export type SystemIdentity = {
  role: 'system'
  id: string
  name: string
  metadata: Record<string, unknown>
}

export type Identity = UserIdentity | AssistantIdentity | SystemIdentity

export type IdentityWire = {
  role: IdentityRole
  id: string
  name: string
  metadata: Record<string, unknown>
}
