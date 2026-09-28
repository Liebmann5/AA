# Getting Help

AutoApply is pre-alpha software maintained by one person. Please read
[STATUS.md](packages/auto_apply/docs/STATUS.md) before reporting that something
does not work — it may be a known gap rather than a bug.

## Where to go

| You want to… | Use |
| --- | --- |
| Solve a common error | [FAQ](packages/auto_apply/docs/faq.md) |
| Learn how to do something | [User Guide](packages/auto_apply/docs/user_guide/index.md) |
| Report a bug | [Bug report](https://github.com/Liebmann5/AA/issues/new?template=bug_report.yml) |
| Request a feature | [Feature request](https://github.com/Liebmann5/AA/issues/new?template=feature_request.yml) |
| Report a documentation problem | [Documentation issue](https://github.com/Liebmann5/AA/issues/new?template=documentation.yml) |
| Ask a question or discuss an idea | [Discussions](https://github.com/Liebmann5/AA/discussions) |
| Report a vulnerability | [SECURITY.md](SECURITY.md) — **privately, never an issue** |

## Before you file

Run the four gates and paste the result. It turns "it broke" into a report
somebody can act on:

```bash
cd packages/auto_apply
uv run pytest tests -q -p no:cacheprovider -rs
uv run ruff check src --select F821 --output-format concise
uv run mypy --config-file ../../pyproject.toml src/auto_apply
uv run mypy --config-file ../../pyproject.toml --explicit-package-bases tests
```

## Redact before you attach

AA's logs, screenshots and session reports routinely contain a real name,
address, email, phone number and employment history. **Do not attach them
without reading them first.** The bug report template asks you to confirm you
have.

## Response expectations

One maintainer, no funding. Bugs that block a first run come first; everything
else may take a while. Silence means a backlog, not disinterest.
