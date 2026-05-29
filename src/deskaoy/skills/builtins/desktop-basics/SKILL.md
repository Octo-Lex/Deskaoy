---
name: desktop-basics
description: >
  Core desktop interaction primitives — click, type, scroll, key press.
  Use for any desktop automation task that involves interacting with
  windows, dialogs, or applications via their UI elements.
triggers:
  - keyword: click
  - keyword: type
  - keyword: scroll
  - keyword: press
  - keyword: desktop
allowed-tools:
  - click
  - fill
  - type_text
  - key_press
  - scroll
  - snapshot
  - wait
---

# Desktop Basics

Interact with desktop application UI elements.

## Constraints

- Always take a snapshot before interacting to verify element positions
- Use Bezier mouse curves for click actions (automatic)
- Add randomized delays between actions to appear human-like
- Never interact with security-sensitive dialogs (UAC, credential prompts)

## Examples

- Click the Submit button in the dialog
- Type "hello world" into the search field
- Scroll down 3 times in the browser window
- Press Enter to confirm
