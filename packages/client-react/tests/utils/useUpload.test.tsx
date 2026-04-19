import { act, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useUpload } from '../../src/utils/useUpload'

function makeFile(name: string): File {
  return new File(['hello'], name, { type: 'text/plain' })
}

function Probe({
  uploader,
  onState,
}: {
  uploader: (f: File) => Promise<{ url: string }>
  onState: (s: ReturnType<typeof useUpload<{ url: string }>>) => void
}) {
  const state = useUpload(uploader)
  onState(state)
  return null
}

describe('useUpload', () => {
  it('tracks a successful upload through uploading → done', async () => {
    let resolveFn: ((v: { url: string }) => void) | null = null
    const uploader = vi.fn(
      () =>
        new Promise<{ url: string }>((resolve) => {
          resolveFn = resolve
        })
    )

    let latest: ReturnType<typeof useUpload<{ url: string }>> | null = null
    render(
      <Probe
        uploader={uploader}
        onState={(s) => {
          latest = s
        }}
      />
    )

    expect(latest!.items).toHaveLength(0)

    let uploadPromise: Promise<{ url: string }> | null = null
    act(() => {
      uploadPromise = latest!.upload(makeFile('a.txt'))
    })
    expect(latest!.items).toHaveLength(1)
    expect(latest!.items[0]!.status).toBe('uploading')

    await act(async () => {
      resolveFn!({ url: 'https://cdn/a' })
      await uploadPromise
    })

    expect(latest!.items[0]!.status).toBe('done')
    expect(latest!.items[0]!.result).toEqual({ url: 'https://cdn/a' })
  })

  it('tracks a failed upload through uploading → error and re-throws', async () => {
    const uploader = vi.fn(() => Promise.reject(new Error('boom')))

    let latest: ReturnType<typeof useUpload<{ url: string }>> | null = null
    render(
      <Probe
        uploader={uploader}
        onState={(s) => {
          latest = s
        }}
      />
    )

    const caught: { err: Error | null } = { err: null }
    await act(async () => {
      try {
        await latest!.upload(makeFile('a.txt'))
      } catch (err) {
        caught.err = err as Error
      }
    })

    expect(caught.err?.message).toBe('boom')
    expect(latest!.items[0]!.status).toBe('error')
    expect(latest!.items[0]!.error?.message).toBe('boom')
  })

  it('handles multiple concurrent uploads independently', async () => {
    const resolvers: Array<(v: { url: string }) => void> = []
    const uploader = vi.fn(
      () =>
        new Promise<{ url: string }>((resolve) => {
          resolvers.push(resolve)
        })
    )

    let latest: ReturnType<typeof useUpload<{ url: string }>> | null = null
    render(
      <Probe
        uploader={uploader}
        onState={(s) => {
          latest = s
        }}
      />
    )

    let p1: Promise<{ url: string }> | null = null
    let p2: Promise<{ url: string }> | null = null
    act(() => {
      p1 = latest!.upload(makeFile('a.txt'))
      p2 = latest!.upload(makeFile('b.txt'))
    })
    expect(latest!.items).toHaveLength(2)
    expect(latest!.items.every((i) => i.status === 'uploading')).toBe(true)

    await act(async () => {
      resolvers[1]!({ url: 'https://cdn/b' })
      await p2
    })
    // b resolved, a still uploading
    const aItem = latest!.items.find((i) => i.file.name === 'a.txt')!
    const bItem = latest!.items.find((i) => i.file.name === 'b.txt')!
    expect(aItem.status).toBe('uploading')
    expect(bItem.status).toBe('done')

    await act(async () => {
      resolvers[0]!({ url: 'https://cdn/a' })
      await p1
    })
    expect(latest!.items.every((i) => i.status === 'done')).toBe(true)
  })

  it('reset clears all items', async () => {
    const uploader = vi.fn(async () => ({ url: 'https://cdn/x' }))

    let latest: ReturnType<typeof useUpload<{ url: string }>> | null = null
    render(
      <Probe
        uploader={uploader}
        onState={(s) => {
          latest = s
        }}
      />
    )

    await act(async () => {
      await latest!.upload(makeFile('a.txt'))
      await latest!.upload(makeFile('b.txt'))
    })
    expect(latest!.items).toHaveLength(2)

    act(() => latest!.reset())
    expect(latest!.items).toHaveLength(0)
  })

  it('remove drops a specific item by id', async () => {
    const uploader = vi.fn(async () => ({ url: 'https://cdn/x' }))
    let latest: ReturnType<typeof useUpload<{ url: string }>> | null = null
    render(
      <Probe
        uploader={uploader}
        onState={(s) => {
          latest = s
        }}
      />
    )

    await act(async () => {
      await latest!.upload(makeFile('a.txt'))
      await latest!.upload(makeFile('b.txt'))
    })
    const firstId = latest!.items[0]!.id
    act(() => latest!.remove(firstId))
    expect(latest!.items).toHaveLength(1)
    expect(latest!.items[0]!.file.name).toBe('b.txt')
  })
})
