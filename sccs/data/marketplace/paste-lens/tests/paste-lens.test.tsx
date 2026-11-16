import { expect, test } from 'claude-code/testing'

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
