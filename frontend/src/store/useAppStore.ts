import { create } from 'zustand'

interface AppState {
  repoId: string | null
  setRepoId: (id: string) => void
}

export const useAppStore = create<AppState>((set) => ({
  repoId: null,
  setRepoId: (id) => set({ repoId: id }),
}))
