# paste-lens

A Claude Code mod that keeps a long paste readable and editable, and lets you mark
text in the prompt box with the keyboard.

Claude Code folds a long paste into a placeholder such as `[Pasted text #1 +42 lines]`.
You cannot read it or change it before you send it. With paste-lens the full text is put
straight back into the prompt box in place of the placeholder, a moment after the paste.
Nothing to press, nothing to click.

## What it does

- A paste of fewer than 400 lines is unfolded automatically.
- A longer paste keeps its placeholder and gets one row above the prompt with an
  `Unfold` button.
- After sending or deleting the text nothing of it is kept.

## Marking text with the keyboard

The prompt box of the terminal has no selection of its own. paste-lens adds one:

| Keys | What is marked |
| --- | --- |
| `Shift+Left` / `Shift+Right` | one character |
| `Shift+Option+Left` / `Shift+Option+Right` (`Shift+Alt` on Windows and Linux) | one word |
| `Shift+Home` / `Shift+End` | to the start or the end of the row |

- `Backspace` or `Delete` removes the marked block at once.
- Typing or pasting replaces it.
- A plain `Left` or `Right` drops the mark and stands the caret at that edge of the block;
  any other move drops it too.

A block of several rows is marked a word or a row at a time: `Shift+Up` and `Shift+Down`
are not handed to a mod. A key that would change nothing is not handed to one either, so
`Delete` does nothing while the block ends at the very end of the text; `Backspace`
always works.

Without the mod, Claude Code already moves a word at a time with `Option+Left` and
`Option+Right` (`Alt` on Windows and Linux), deletes a word with `Option+Backspace`, and
in the fullscreen view removes a block marked with the mouse on `Backspace` or `Delete`.
If the Option keys do nothing, the terminal does not send Option as Meta or Alt; that is a
setting of the terminal.

## How it gets the text

Claude Code hands a mod only the placeholder, not what was pasted. paste-lens therefore
reads the clipboard (`pbpaste` on macOS, `wl-paste` or `xclip` on Linux) and takes its
content only when the line count fits the placeholder's. A clipboard that holds something
else is never put into the prompt. If the clipboard was already replaced, the row says
that the text is not readable.

## Install

It ships with [sccs](https://pypi.org/project/sccs/). Add it to `~/.config/sccs/config.yaml`
and run `sccs doctor install`:

```yaml
doctor:
  bundled_mods:
  - paste-lens
```

It takes effect in the next Claude Code session. Mods are an early-access part of Claude
Code, so a Claude Code update can change what this mod is able to do.
