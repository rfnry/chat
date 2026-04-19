import { useThreadActiveRuns } from './useThreadActiveRuns'

export function useThreadIsWorking(threadId: string | null): boolean {
  const runs = useThreadActiveRuns(threadId)
  return runs.length > 0
}
