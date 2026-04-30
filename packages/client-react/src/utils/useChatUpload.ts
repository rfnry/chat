import { useCallback, useState } from 'react'

export type UploadStatus = 'idle' | 'uploading' | 'done' | 'error'

export type UploadItem<T> = {
  id: string
  file: File
  status: UploadStatus
  result?: T
  error?: Error
}

export type UseChatUploadResult<T> = {
  items: UploadItem<T>[]
  upload: (file: File) => Promise<T>
  remove: (id: string) => void
  reset: () => void
}

export function useChatUpload<T>(uploader: (file: File) => Promise<T>): UseChatUploadResult<T> {
  const [items, setItems] = useState<UploadItem<T>[]>([])

  const upload = useCallback(
    async (file: File): Promise<T> => {
      const id =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : `upl_${Math.random().toString(36).slice(2)}_${Date.now()}`
      setItems((prev) => [...prev, { id, file, status: 'uploading' }])
      try {
        const result = await uploader(file)
        setItems((prev) => prev.map((i) => (i.id === id ? { ...i, status: 'done', result } : i)))
        return result
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err))
        setItems((prev) => prev.map((i) => (i.id === id ? { ...i, status: 'error', error } : i)))
        throw error
      }
    },
    [uploader]
  )

  const remove = useCallback((id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id))
  }, [])

  const reset = useCallback(() => {
    setItems([])
  }, [])

  return { items, upload, remove, reset }
}
