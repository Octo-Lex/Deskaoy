# BATCH-30 BLUEPRINT — Shell Completions & CLI Polish

**Batch:** BATCH-30 | **Version:** v0.37.0 → v0.38.0 | **Cycle:** STANDARD | **AIV:** v5.3
**Lead:** Craft Agent (Lead Override per §5.3) | **Blueprint Version:** 1.0

## Strategic Bet
Shell completions from argparse metadata + improved CLI UX for production readiness.

## Scope
- **IN**: PowerShell/bash/zsh completions, `--verbose` flag, improved help, `docs` command
- **OUT**: fish completions, man pages, GUI

## Hard Boundaries
| ID | Constraint |
|----|-----------|
| HB-01 | Completions generated from argparse — no hardcoded lists |
| HB-02 | All baseline tests pass |
| HB-03 | No new required dependencies |

## Tasks (SEQUENTIAL)

### TASK-01: Shell Completion Generator
New module `src/agent_core/cli/completions.py` — `CompletionGenerator` class.
- `generate_powershell()` — Register-ArgumentCompleter script
- `generate_bash()` — complete -F function
- `generate_zsh()` — compdef function
- All generated from argparse parser introspection
- CLI: `desktop-agent completions <shell>` outputs completion script
- Tests: 10

### TASK-02: CLI Polish
- `--verbose` / `-v` flag: enables DEBUG logging
- Improved help text for all commands (description, examples)
- `desktop-agent docs` command: opens README/QUICKSTART in browser or prints
- Error messages with suggestions ("did you mean ...?")
- Tests: 8

### TASK-03: Version Bump + Integration
- Version 0.37.0 → 0.38.0
- Tests: 7 (completion output validation, verbose flag, help text)

**Total:** 25 new tests | **Expected suite:** 3,268
