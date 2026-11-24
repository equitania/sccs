import type { PromptEditInput, PromptEditResult } from 'claude-code'
import { expect, test } from 'claude-code/testing'

import { marking } from '../hooks/register'

const TOKEN = '[Pasted text #1 +2 lines]'
const PASTED = 'first line\nsecond line\nthird line'
const LONG = Array.from({ length: 501 }, (_, i) => `row ${i}`).join('\n')
const LONG_TOKEN = '[Pasted text #2 +500 lines]'

const BAND = {
  plugin: 'paste-lens',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isCollapsed: false,
    isWorking: false,
    maxRows: 20,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 19 },
    view: {},
  },
  surface: 'terminal',
} as const

const RAN = { stderr: '', isStdoutTruncated: false, isStderrTruncated: false }

// The engine raises `prompt.change` itself; the kit's `$` runs it without
// declaring it, so the call is typed here.
type Raises = { prompt: { change: (e: unknown) => Promise<unknown> } }

const paste = ($: unknown, text: string, origin: object = { kind: 'engine' }) =>
  ($ as Raises).prompt.change({ text, cursor: text.length, origin })

const settle = async () => {
  for (let i = 0; i < 200; i += 1) {
    await Promise.resolve()
  }
}

test('a folded paste is put back into the box as text', async ($, on) => {
  const draft = `Review: ${TOKEN} please`
  const fills: string[] = []
  on('process.run', () => ({ value: { exitCode: 0, stdout: PASTED, ...RAN } }))
  on('prompt.change', (_, e) => ({ text: e.text }))
  let box = draft
  on('prompt.read', () => ({ value: { text: box, cursor: box.length } }))
  on('prompt.fill', (_, e) => {
    fills.push(e.text)
    box = e.text

    return { isFilled: true }
  })

  await paste($, draft)
  await settle()

  expect(fills).toEqual([`Review: ${PASTED} please`])
})

test('a clipboard of another length is never put into the box', async ($, on) => {
  const fills: string[] = []
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'a password', ...RAN } }))
  on('prompt.change', (_, e) => ({ text: e.text }))
  on('prompt.fill', (_, e) => {
    fills.push(e.text)

    return { isFilled: true }
  })

  await paste($, TOKEN)
  await settle()

  expect(fills).toEqual([])
  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /not readable/ })).toBeTruthy()
  await ui.unmount()
})

test('a very long paste keeps its placeholder and offers Unfold', async ($, on) => {
  const fills: string[] = []
  on('process.run', () => ({ value: { exitCode: 0, stdout: LONG, ...RAN } }))
  on('prompt.change', (_, e) => ({ text: e.text }))
  let box: string = LONG_TOKEN
  on('prompt.read', () => ({ value: { text: box, cursor: box.length } }))
  on('prompt.fill', (_, e) => {
    fills.push(e.text)
    box = e.text

    return { isFilled: true }
  })

  await paste($, LONG_TOKEN)
  await settle()
  expect(fills).toEqual([])

  const ui = await $.ui.mount(BAND)
  await ui.press({ key: 'unfold-2' })
  expect(fills).toEqual([LONG])
  await ui.unmount()
})

test('its own fill is never answered with another', async ($, on) => {
  const fills: string[] = []
  on('process.run', () => ({ value: { exitCode: 0, stdout: PASTED, ...RAN } }))
  on('prompt.change', (_, e) => ({ text: e.text }))
  on('prompt.fill', (_, e) => {
    fills.push(e.text)

    return { isFilled: true }
  })

  // The engine folded what the mod filled: a new placeholder, the mod's origin.
  await paste($, TOKEN, { kind: 'plugin', name: 'paste-lens' })
  await settle()

  expect(fills).toEqual([])
})

test('the row is gone once the placeholder left the box', async ($, on) => {
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'other', ...RAN } }))
  on('prompt.change', (_, e) => ({ text: e.text }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })

  await paste($, TOKEN)
  await paste($, '', { kind: 'clear' })

  const ui = await $.ui.mount(BAND)
  expect(await ui.find({ type: 'Text', text: /not readable/ })).toBeFalsy()
  await ui.unmount()
})

// The editor beneath the hook: the splice applied, the caret after it. A move
// arrives as an empty splice at where it lands.
const core = async (e: PromptEditInput): Promise<PromptEditResult> => ({
  text: e.text.slice(0, e.start) + e.inputText + e.text.slice(e.end),
  cursor: e.start + e.inputText.length,
})

type Key = NonNullable<PromptEditInput['key']>

const edit = (
  text: string,
  cursor: number,
  splice: { start: number; end?: number; inputText?: string; key?: Key },
): Promise<PromptEditResult> =>
  marking(
    {
      origin: { kind: 'composer' },
      text,
      cursor,
      start: splice.start,
      end: splice.end ?? splice.start,
      inputText: splice.inputText ?? '',
      ...(splice.key === undefined ? {} : { key: splice.key }),
    },
    core,
  )

const DRAFT = 'alpha beta gamma'

test('a shifted move marks a block and Backspace removes it at once', async () => {
  // Shift+Option+Left twice from the end: over `gamma`, then over `beta `.
  const one = await edit(DRAFT, 16, { start: 11, key: { key: 'left', shift: true, meta: true } })
  expect(one.decorations?.at(-1)).toMatchObject({ start: 11, end: 16 })

  const two = await edit(DRAFT, 11, { start: 6, key: { key: 'left', shift: true, meta: true } })
  expect(two.decorations?.at(-1)).toMatchObject({ start: 6, end: 16 })

  // Backspace alone would take one character before the caret.
  const gone = await edit(DRAFT, 6, { start: 5, end: 6, key: { key: 'backspace' } })
  expect(gone).toEqual({ text: 'alpha ', cursor: 6 })
})

test('typing replaces the marked block', async () => {
  await edit(DRAFT, 6, { start: 10, key: { key: 'right', shift: true, meta: true } })

  const typed = await edit(DRAFT, 10, { start: 10, inputText: 'X', key: { key: 'X', shift: true } })
  expect(typed).toEqual({ text: 'alpha X gamma', cursor: 7 })
})

test('a plain move drops the mark and lands on its edge', async () => {
  await edit(DRAFT, 16, { start: 11, key: { key: 'left', shift: true, meta: true } })

  const right = await edit(DRAFT, 11, { start: 12, key: { key: 'right' } })
  expect(right).toEqual({ text: DRAFT, cursor: 16 })

  // The mark is gone: Backspace takes one character again.
  const back = await edit(DRAFT, 16, { start: 15, end: 16, key: { key: 'backspace' } })
  expect(back).toEqual({ text: 'alpha beta gamm', cursor: 15 })
})

test('a block marked back to the start of the text keeps Backspace alive', async () => {
  // Shift+Home from 5: the caret is stood at 5, where Backspace is an edit.
  const home = await edit(DRAFT, 5, { start: 0, key: { key: 'home', shift: true } })
  expect(home.cursor).toBe(5)
  expect(home.decorations?.at(-1)).toMatchObject({ start: 0, end: 5 })

  const gone = await edit(DRAFT, 5, { start: 4, end: 5, key: { key: 'backspace' } })
  expect(gone).toEqual({ text: ' beta gamma', cursor: 0 })
})

test('a mark over another draft is never applied', async () => {
  await edit(DRAFT, 16, { start: 11, key: { key: 'left', shift: true, meta: true } })

  // A recalled entry replaced the draft in between.
  const other = 'something else'
  const back = await edit(other, 14, { start: 13, end: 14, key: { key: 'backspace' } })
  expect(back).toEqual({ text: 'something els', cursor: 13 })
})
