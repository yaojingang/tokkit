# GitHub publish plan

## Recommended repository setup

- Repository name: `tokkit`
- Visibility: start private if you want one more polish pass, otherwise public
- Default branch: `main`
- Initial release tag: `v0.1.0`

## What to publish in the first push

- Source code for `tokkit`
- Shell helper guidance for `tok`
- `launchd` scripts for automatic scan and daily reporting
- Product brief and publish plan
- MIT license
- Clean `.gitignore`

Do not publish:

- personal databases
- generated reports
- local credentials
- machine-specific runtime output

## Push strategy

### Option A: clean public launch

Use this if you want the first public commit history to already look curated.

1. Initialize a new git repo in the project directory
2. Commit the codebase as `feat: initial TokKit release`
3. Create the GitHub repo `tokkit`
4. Push `main`
5. Create release `v0.1.0`

### Option B: private staging first

Use this if you want to check README, screenshots, and license one more time.

1. Initialize a private GitHub repo
2. Push the current state
3. Add screenshots and polish docs
4. Flip the repo public when ready

## Suggested commit sequence

1. `chore: initialize TokKit project metadata`
2. `feat: add local token ledger for Codex, Warp, Kaku, and CodeBuddy`
3. `feat: add terminal, model, and client usage reports`
4. `feat: add tok helper UX with inline hints and autosuggest`
5. `docs: add product brief and publish plan`

## README packaging checklist

- Clear one-line positioning at the top
- Supported tools section
- Accuracy model section: exact vs partial vs estimated
- Quick start in under one minute
- Example commands
- Automation section
- Optional Kaku shell UX section

## Suggested GitHub topics

- `llm`
- `ai-tools`
- `terminal`
- `developer-tools`
- `token-tracking`
- `usage-analytics`
- `sqlite`
- `macos`

## Suggested release notes structure

### Headline

TokKit v0.1.0: local token accounting for desktop AI coding tools

### Highlights

- local daily token ledger
- unified reports across multiple tools
- model, terminal, source, and client breakdowns
- automatic hourly scans and daily reports
- shell-first `tok` workflow for Kaku and zsh users

### Known limits

- Codex currently exposes provider but not exact model name in local logs
- Warp historical backfill is conversation-based, so older day splits are approximate
- Some clients are still untracked or estimated
