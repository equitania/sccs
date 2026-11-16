# paste-lens

A Claude Code mod that keeps a long paste readable and editable.

Claude Code folds a long paste into a placeholder such as `[Pasted text #1 +42 lines]`.
You cannot read it or change it before you send it. With paste-lens the full text is put
straight back into the prompt box in place of the placeholder, a moment after the paste.
Nothing to press, nothing to click.

## What it does

- A paste of fewer than 400 lines is unfolded automatically.
- A longer paste keeps its placeholder and gets one row above the prompt with an
  `Unfold` button.
- After sending or deleting the text nothing of it is kept.

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
