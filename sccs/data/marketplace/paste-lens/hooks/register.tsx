// paste-lens: a long paste stays readable and editable.
//
// Claude Code folds a long paste into `[Pasted text #1 +42 lines]`. This mod
// puts the text straight back into the prompt box in place of the
// placeholder, so it can be read and changed before it is sent. A paste of
// more than AUTO_ROWS rows keeps its placeholder and gets a one-line band
// above the prompt with an `Unfold` button instead.
//
// Where the text comes from: the engine folds the paste by itself and hands a
// mod only the placeholder (`prompt.change`, origin `engine`), and no key but
// the editing ones reaches a mod (not Tab, not the arrows). So the clipboard
// is asked (`pbpaste`, `wl-paste`, `xclip`) and its answer is taken only when
// its line count fits the placeholder's: an unrelated clipboard is never put
// into the prompt as the paste.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Paste } from '../types'

const MARK = '[Pasted text #'
const PLACEHOLDER = /\[Pasted text #(\d+)(?: \+(\d+) lines?)?\]/g
// Rows written per call when the engine folds a whole text again.
const PIECE = 3
// The longest paste unfolded without being asked.
const AUTO_ROWS = 400

const pastes = atom({ plugin: 'paste-lens', key: 'pastes' } as const, [], {
  shape: 'pastes-1',
})

type Token = { id: number; token: string; lines: number | null }

export const tokensIn = (text: string): Token[] => {
  if (!text.includes(MARK)) {
    return []
  }

  return [...text.matchAll(PLACEHOLDER)].map(m => ({
    id: Number(m[1]),
    token: m[0],
    lines: m[2] === undefined ? null : Number(m[2]),
  }))
}

const normalize = (text: string): string => text.replace(/\r\n?/g, '\n')

const newlines = (text: string): number => text.split('\n').length - 1

/** True when `text` can be what stands behind `token`, by its line count. */
export const fits = (text: string, token: Token): boolean => {
  if (text.trim() === '') {
    return false
  }

  if (token.lines === null) {
    return true
  }

  // A trailing newline is counted by some terminals and not by others.
  return Math.abs(newlines(text.replace(/\n+$/, '')) - token.lines) <= 1
}

const CLIPBOARD_TOOLS: readonly (readonly string[])[] = [
  ['pbpaste'],
  ['wl-paste', '--no-newline'],
  ['xclip', '-selection', 'clipboard', '-o'],
]

// What the atom holds, kept here too: `prompt.edit` runs on every key and
// must not wait on a read while there is nothing to track.
let known: Paste[] | null = null

const load = async ($: EngineInterface): Promise<Paste[]> => {
  if (known === null) {
    known = await read($, pastes)
  }

  return known
}

const save = async ($: EngineInterface, list: Paste[]): Promise<void> => {
  known = list
  await update($, pastes, () => list)
}

const clipboard = async ($: EngineInterface): Promise<string | null> => {
  for (const argv of CLIPBOARD_TOOLS) {
    try {
      const ran = await $.process.run(argv, { timeoutMs: 2000 })

      if (ran.exitCode === 0 && ran.stdout !== '') {
        return normalize(ran.stdout)
      }
    } catch {
      // Not on this host: try the next one.
    }
  }

  return null
}

const forget = async ($: EngineInterface, paste: Paste): Promise<void> => {
  await save($, (await load($)).filter(p => p.token !== paste.token))
}

/**
 * Puts a paste's text into the box in place of its placeholder, from a
 * Button. The engine may fold a long fill again; then the text is written a
 * few rows at a time, which it leaves alone.
 */
const unfold = async ($: EngineInterface, paste: Paste): Promise<void> => {
  const text = paste.text

  if (text === null) {
    return
  }

  const box = await $.prompt.read()
  const at = box.text.indexOf(paste.token)

  if (at === -1) {
    $.ui.toast('That paste is no longer in the prompt box.')

    return
  }

  const before = box.text.slice(0, at)
  const after = box.text.slice(at + paste.token.length)
  const cursor = before.length + text.length
  // Forgotten first: the fill's own `prompt.change` must not track it anew.
  await forget($, paste)

  const whole = await $.prompt.fill({ text: before + text + after, mode: 'replace', cursor })

  if (!whole.isFilled) {
    await save($, [...(await load($)), paste])
    $.ui.toast('The prompt box did not take the text.')

    return
  }

  // Folded again when the box is far shorter than what went in. Not told by a
  // placeholder in it: the pasted text may itself quote one.
  if (whole.text.length >= before.length + after.length + text.length / 2) {
    return
  }

  // Folded again: rebuild the draft piece by piece.
  const rows = text.split('\n')
  await $.prompt.fill({ text: before, mode: 'replace' })

  for (let i = 0; i < rows.length; i += PIECE) {
    const piece = rows.slice(i, i + PIECE).join('\n')
    const isLast = i + PIECE >= rows.length
    await $.prompt.fill({ text: isLast ? piece : `${piece}\n`, mode: 'append' })
  }

  if (after !== '') {
    await $.prompt.fill({ text: after, mode: 'append', cursor })
  }
}

/**
 * Brings the tracked pastes in line with `draft`: drops what left it and
 * adds each new placeholder with its text, from `carried` (what the edit put
 * in) or else from the clipboard.
 */
const track = async ($: EngineInterface, draft: string, carried: string): Promise<void> => {
  const after = tokensIn(draft)
  const list = await load($)

  if (after.length === 0) {
    if (list.length > 0) {
      await save($, [])
    }

    return
  }

  const kept = list.filter(p => after.some(t => t.token === p.token))
  const fresh = after.filter(t => !kept.some(p => p.token === t.token))

  if (fresh.length === 0) {
    if (kept.length !== list.length) {
      await save($, kept)
    }

    return
  }

  // What the edit itself carried, unless that is only the placeholder.
  const text = normalize(carried)
  const isCarried = text !== '' && tokensIn(text).length === 0
  let fromClipboard: string | null | undefined
  const added: Paste[] = []

  for (const token of fresh) {
    if (isCarried && fresh.length === 1 && fits(text, token)) {
      added.push({ id: token.id, token: token.token, text, source: 'edit' })
      continue
    }

    if (fromClipboard === undefined) {
      fromClipboard = await clipboard($)
    }

    if (fromClipboard !== null && fits(fromClipboard, token)) {
      added.push({ id: token.id, token: token.token, text: fromClipboard, source: 'clipboard' })
      continue
    }

    added.push({ id: token.id, token: token.token, text: null, source: 'none' })
  }

  await save($, [...kept, ...added])

  // Not awaited: the box takes one change at a time, and this runs inside one.
  for (const paste of added) {
    if (paste.text !== null && newlines(paste.text) < AUTO_ROWS) {
      void unfold($, paste)
    }
  }
}

export const register: Register = on => {
  on('prompt.edit', async ($, e, next) => {
    const box = await next(e)
    await track($, box.text, e.inputText)

    return box
  })

  // The box changed without a `prompt.edit`: a long paste the engine folds
  // itself arrives here (origin `engine`), as do a submit, a clear, an undo, a
  // recalled entry and a fill. The text is not carried: the clipboard is asked.
  on('prompt.change', async ($, e, next) => {
    if (e.origin.kind === 'plugin' && e.origin.name === 'paste-lens') {
      // This mod's own fill: never answered with another, whatever the engine
      // made of it. Only what left the box is dropped.
      const list = await load($)
      const kept = list.filter(p => e.text.includes(p.token))

      if (kept.length !== list.length) {
        await save($, kept)
      }

      return next(e)
    }

    await track($, e.text, '')

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const list = await load($)

    if (e.props.hasSurvey || list.length === 0) {
      return next(e)
    }

    const { Box, Button, Text } = $.ui.resolve(e)

    return (
      <Box flexDirection="column">
        {list.map(paste =>
          paste.text === null ? (
            <Text dimColor>
              Pasted text #{paste.id}: not readable, the clipboard no longer holds it.
            </Text>
          ) : (
            <Box>
              <Button
                key={`unfold-${paste.id}`}
                label={`Unfold pasted text #${paste.id}`}
                onPress={() => unfold($, paste)}
              />
              <Text dimColor> to read and edit it in the prompt box</Text>
            </Box>
          ),
        )}
      </Box>
    )
  })
}
