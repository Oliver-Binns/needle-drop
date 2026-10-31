# Contributing to needle-drop

Thank you for your interest in contributing! This guide covers our workflow for submitting changes.

## Pull Request Process

All changes to `needle-drop` go through pull requests. Here's what we need:

### Before You Start

- Check the [issues](https://github.com/Oliver-Binns/needle-drop/issues) to see if your work is already tracked
- Each PR should address a single issue or concern — don't mix unrelated changes

### Commit Messages

Use clear, descriptive commit messages. If your change resolves a GitHub issue, reference it:

```
Add status page endpoint

- Implement /status HTTP endpoint
- Return gate state, audio level, and undelivered-audio counter
- Add health check that requires HiFiBerry and OwnTone to respond

Closes: #3
```

Include the `Closes: #X` trailer at the end of the commit message (where X is the issue number). This automatically closes the issue when the PR is merged.

### Pull Request Description

When creating your PR, include:

1. **What this does** — a brief summary of the change
2. **Why** — the problem it solves or feature it adds
3. **Closes** — the issue number(s) it resolves (if any)

Use `Closes: #X` in the PR description as well to link it to the issue:

```
## Summary
Implements status page endpoint for monitoring gate state and audio levels.

## Details
- Listens on port 8099 (configurable)
- Returns JSON with current gate state, sound level, thresholds
- Health check ensures HiFiBerry and OwnTone are responsive

Closes: #3
```

### Automated Checks

Every PR runs:

- **Lint (ruff)** — code style checks
- **Tests (pytest)** — unit tests

Both must pass before merging. If a check fails:

1. Read the error message
2. Fix the issue locally
3. Commit and push — the check runs automatically on the new commit

### Merging

- At least one review approval before merge (automated for trusted contributors)
- All checks must pass
- Squash or rebase at merge time to keep history clean

Once merged to `main`, the changes automatically deploy to the Pi via the update timer.

## Code Style

- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) for Python code
- Use `ruff` for automated style checks: `ruff check . && ruff format .`
- Write clear comments only where intent isn't obvious

## Testing

- Add tests for any new behavior
- Run tests locally: `pytest`
- Tests are required for all feature PRs

## Questions?

Open an issue or ask in the PR — we're happy to help!
