# Contributing to Repo Agent

Thanks for helping improve Repo Agent.

## Development setup

```powershell
cd repo-agent
py -3 -m pip install -e ".[dev]"
```

## Useful commands

```powershell
py -3 -m compileall repo_agent tests
py -3 -m repo_agent eval
py -3 -m pytest
node --check web/app.js
py -3 -m repo_agent serve
py -3 -m repo_agent ask --repo ".\examples\simple_agent_app" --question "聊天接口在哪里实现？"
```

## Pull request checklist

- Keep changes scoped and explain the motivation.
- Add or update tests for parser, retrieval, cache, safety, or UI behavior when relevant.
- Run `py -3 -m repo_agent eval` before opening a PR.
- Run `py -3 -m pytest` before opening a PR.
- Update `README.md` if behavior or commands changed.
- Do not commit generated content from `logs/`, `reports/`, `runs/`, `.tmp/`, or `.cache/`.

## Community

Please follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). For security-sensitive reports, use [SECURITY.md](SECURITY.md) instead of a public issue.
