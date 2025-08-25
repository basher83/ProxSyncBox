# Modern Development Setup

## 🚀 Quick Start

```bash
# Install mise (if not already installed)
curl https://mise.run | sh

# Install all tools and dependencies
mise install
mise run setup

# You're ready to go!
mise run dev
```

## 🛠️ Toolchain

### Core Tools (managed by mise)

- **uv** - Lightning-fast Python package manager
- **ruff** - All-in-one Python linter and formatter
- **mypy** - Static type checker
- **pre-commit** - Git hooks for code quality
- **prettier** - Markdown/JSON/YAML formatter
- **markdownlint-cli2** - Markdown linter

### Why This Stack?

- **uv** - 10-100x faster than pip, better dependency resolution
- **ruff** - Replaces flake8, black, isort, and more in one tool
- **mise** - Modern task runner, replaces Makefile, manages tool versions
- **autofix.ci** - Automatic fixes on PRs, no local setup needed

## 📋 Common Tasks

```bash
# Development
mise run dev              # Run the GUI app
mise run test             # Run tests
mise run test:watch       # Run tests in watch mode
mise run test:cov         # Run tests with coverage

# Code Quality
mise run lint             # Run all linters
mise run format           # Format all code
mise run fix              # Auto-fix all issues
mise run check            # Run all checks (CI simulation)
mise run security         # Security scan

# Maintenance
mise run clean            # Clean generated files
mise run upgrade          # Upgrade all dependencies
mise run deps             # Show dependency tree
mise run outdated         # Check for updates
```

## 🎯 Pre-commit Hooks

Pre-commit runs automatically on `git commit`:

- Python formatting (ruff)
- Python linting (ruff)
- Type checking (mypy)
- Markdown formatting (prettier)
- Markdown linting (markdownlint)
- Security checks (bandit)
- Secret detection

Manual run:

```bash
mise run check:pre-commit  # Run on all files
pre-commit run --all-files # Alternative
```

## 🤖 CI/CD

### GitHub Actions

- **CI Pipeline** - Lint, type check, test on multiple Python versions
- **autofix.ci** - Automatically fixes and commits formatting issues
- **Security Scans** - Bandit and Safety checks
- **Cross-platform** - Tests on Linux, macOS, Windows

### Local CI Testing

```bash
mise run ci  # Run all CI checks locally
```

## 📦 Package Management

### Adding Dependencies

```bash
# Production dependency
uv pip install package-name
# Then add to pyproject.toml dependencies

# Development dependency
uv pip install --dev package-name
# Then add to pyproject.toml optional-dependencies.dev
```

### Updating Dependencies

```bash
mise run upgrade          # Upgrade all
uv pip install -U package # Upgrade specific
```

## 🔧 IDE Setup

### VS Code

Install extensions:

- Python
- Ruff
- mypy
- Prettier
- markdownlint

Settings (`.vscode/settings.json`):

```json
{
  "python.linting.enabled": false,
  "python.formatting.provider": "none",
  "[python]": {
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": true,
      "source.organizeImports.ruff": true
    },
    "editor.defaultFormatter": "charliermarsh.ruff"
  },
  "[markdown]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  }
}
```

### PyCharm

- Enable Ruff plugin
- Set Ruff as formatter
- Configure mypy as external tool

## 🐛 Troubleshooting

### mise not found

```bash
curl https://mise.run | sh
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc
```

### uv not installing packages

```bash
mise run clean
rm -rf .venv
mise run setup
```

### Pre-commit failing

```bash
pre-commit clean
pre-commit install --install-hooks
pre-commit run --all-files
```

## 📚 Learn More

- [uv Documentation](https://github.com/astral-sh/uv)
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [mise Documentation](https://mise.jdx.dev/)
- [autofix.ci](https://autofix.ci/)

## 🎉 Benefits

- **Fast** - uv installs in seconds, not minutes
- **Consistent** - Same tools, same versions for everyone
- **Automated** - Pre-commit and autofix.ci handle formatting
- **Modern** - Latest Python tooling best practices
- **Simple** - One command to set up everything: `mise run setup`

---

_Welcome to the future of Python development! 🚀_
