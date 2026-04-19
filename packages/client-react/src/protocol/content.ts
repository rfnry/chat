export type TextPart = {
  type: 'text'
  text: string
}

export type ImagePart = {
  type: 'image'
  url: string
  mime: string
  name?: string
  size?: number
}

export type AudioPart = {
  type: 'audio'
  url: string
  mime: string
  name?: string
  size?: number
  durationMs?: number
}

export type DocumentPart = {
  type: 'document'
  url: string
  mime: string
  name?: string
  size?: number
}

export type FormStatus = 'pending' | 'submitted' | 'cancelled'

export type FormPart = {
  type: 'form'
  formId: string
  schema: Record<string, unknown>
  status: FormStatus
  values?: Record<string, unknown>
  answersEventId?: string
  title?: string
  description?: string
}

export type ContentPart = TextPart | ImagePart | AudioPart | DocumentPart | FormPart

export type AudioPartWire = Omit<AudioPart, 'durationMs'> & { duration_ms?: number }

export type FormPartWire = Omit<FormPart, 'formId' | 'answersEventId'> & {
  form_id: string
  answers_event_id?: string
}

export type ContentPartWire = TextPart | ImagePart | AudioPartWire | DocumentPart | FormPartWire
