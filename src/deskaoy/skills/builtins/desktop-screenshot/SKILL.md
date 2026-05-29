---
name: desktop-screenshot
description: >
  Capture and analyze screenshots of the desktop or specific windows.
  Use when the user wants to read screen content, verify what's visible,
  or extract text via OCR.
triggers:
  - keyword: screenshot
  - keyword: capture
  - keyword: read screen
  - keyword: what's on screen
allowed-tools:
  - snapshot
  - evaluate
---

# Desktop Screenshot

Capture desktop screenshots and extract information.

## Constraints

- Screenshots are read-only — no side effects
- OCR accuracy depends on font size and clarity
- Sensitive content (passwords, keys) should be redacted from results

## Examples

- Take a screenshot of the current window
- Read the text in the error dialog
- What's currently on screen?
