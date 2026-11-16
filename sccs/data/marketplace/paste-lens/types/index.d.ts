/**
 * One collapsed paste in the current draft: the placeholder the prompt box
 * shows and, where it could be read, the text behind it.
 */
export type Paste = {
  /** The number in `[Pasted text #N ...]`. */
  id: number
  /** The placeholder exactly as it stands in the draft. */
  token: string
  /** The pasted text; `null` when neither the edit nor the clipboard held it. */
  text: string | null
  /** Where `text` came from. */
  source: 'edit' | 'clipboard' | 'none'
}

declare module 'claude-code' {
  interface PluginState {
    'paste-lens': {
      pastes: Shaped<Paste[]>
    }
  }
}
