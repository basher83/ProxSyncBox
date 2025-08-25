# 🚀 Contributing to ProxSyncBox

Welcome, infrastructure explorer! We're thrilled that you want to contribute to
ProxSyncBox. This guide will help you navigate the contribution process and
ensure your efforts align with our mission to seamlessly sync Proxmox and
NetBox.

## 🎯 Mission Values

ProxSyncBox operates under these core principles:

- **🌟 Excellence in Execution** - Quality code and documentation
- **🤝 Collaborative Spirit** - Open communication and mutual respect
- **🔒 Infrastructure Security** - Safe handling of credentials and data
- **📚 Knowledge Sharing** - Clear documentation and learning
- **🚀 Continuous Improvement** - Always evolving and growing

## 🛰️ Getting Started

### 1. Mission Briefing

Before contributing, familiarize yourself with:

- [Project README](README.md) and core functionality
- [Development Setup](docs/MODERN_DEV_SETUP.md)
- [Roadmap](docs/ROADMAP.md) and [Priorities](docs/DEVELOPMENT_PRIORITIES.md)
- [Testing Guide](docs/TESTING_SETUP.md)
- Existing issues and discussions

### 2. Setting Up Your Development Environment

```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/ProxSyncBox.git
cd ProxSyncBox

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL_OWNER/ProxSyncBox.git

# Install mise for toolchain management
curl https://mise.run | sh

# Set up development environment
mise install
mise run setup

# Run tests to ensure everything works
mise run test
```

### 3. Choosing Your Mission

Look for issues labeled with:

- 🟢 `good-first-issue` - Perfect for new contributors
- 🤝 `help-wanted` - We need assistance with these
- 📚 `documentation` - Help improve our docs
- 🐛 `bug` - Fix sync anomalies
- ✨ `enhancement` - Add new features
- 🎨 `ui/ux` - Improve the GUI

## 🚀 Contribution Workflow

### Step 1: Mission Planning

1. **Find or create an issue** describing what you want to work on
2. **Comment on the issue** to let others know you're working on it
3. **Get confirmation** from maintainers for larger changes

### Step 2: Development Phase

1. **Create a feature branch** from the main branch:

   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-number-description
   ```

2. **Follow our coding standards:**
   - Python code formatted with `ruff` (automatic via pre-commit)
   - Type hints where practical
   - Docstrings for public functions
   - Follow existing architectural patterns

3. **Write tests** for new functionality:

   ```bash
   # Run tests frequently during development
   mise run test

   # Check test coverage
   mise run test:cov

   # Run specific test
   pytest tests/test_specific.py::TestClass::test_method
   ```

4. **Commit your changes** using conventional commits:

   ```bash
   git commit -m "feat(sync): add support for custom field mapping

   Implement configurable field mapping between Proxmox and NetBox
   custom fields. Includes validation and error handling.

   Closes: #123"
   ```

   Commit types:
   - `feat:` New feature
   - `fix:` Bug fix
   - `docs:` Documentation changes
   - `style:` Code style changes (formatting, etc.)
   - `refactor:` Code refactoring
   - `test:` Test additions or changes
   - `chore:` Maintenance tasks

### Step 3: Pre-Launch Checks

1. **Run all quality checks:**

   ```bash
   # Auto-fix any issues
   mise run fix

   # Run all checks
   mise run check

   # Ensure pre-commit hooks pass
   mise run check:pre-commit
   ```

2. **Update documentation** if needed:
   - Update README for new features
   - Add/update docstrings
   - Update relevant docs in `/docs`

3. **Test your changes:**
   - Manual testing with real/mock Proxmox and NetBox
   - Unit tests for new code
   - Integration tests if applicable

### Step 4: Mission Launch

1. **Push your branch:**

   ```bash
   git push origin feature/your-feature-name
   ```

2. **Create a Pull Request:**
   - Use a clear, descriptive title
   - Reference the issue it closes
   - Include screenshots for UI changes
   - List testing performed

3. **PR Template:**

   ```markdown
   ## Description

   Brief description of changes

   ## Related Issue

   Closes #(issue number)

   ## Type of Change

   - [ ] Bug fix
   - [ ] New feature
   - [ ] Documentation update
   - [ ] Performance improvement

   ## Testing

   - [ ] Manual testing completed
   - [ ] Unit tests pass
   - [ ] Integration tests pass

   ## Screenshots (if applicable)
   ```

## 🌐 Contribution Types

### 🐛 Bug Reports

When reporting bugs, include:

- ProxSyncBox version
- Python version
- Proxmox and NetBox versions
- Steps to reproduce
- Expected vs actual behavior
- Error messages/logs

### ✨ Feature Requests

For new features, provide:

- Use case description
- Expected behavior
- Mockups/examples if applicable
- Impact on existing functionality

### 📚 Documentation

Help us improve:

- Installation guides
- API documentation
- Troubleshooting guides
- Code comments
- Example configurations

### 🧪 Testing

Contribute by:

- Writing unit tests
- Creating integration tests
- Testing on different platforms
- Testing with various Proxmox/NetBox versions

## 📏 Quality Standards

### Code Quality

- **Linting:** Code must pass `ruff` checks
- **Type Checking:** No `mypy` errors
- **Testing:** Maintain or improve test coverage
- **Documentation:** Public APIs must be documented

### Performance

- Sync operations should be efficient
- API calls should be batched when possible
- Memory usage should be reasonable
- UI should remain responsive

### Security

- Never commit credentials or tokens
- Validate all user inputs
- Use secure API communication
- Follow NetBox and Proxmox security best practices

## 🎖️ Recognition

Contributors are recognized in:

- GitHub contributors page
- Release notes for significant contributions
- Special mentions for exceptional work

## 🆘 Getting Help

- **Discord/Slack:** [Join our community](#)
- **Discussions:** Use GitHub Discussions for questions
- **Issues:** Report bugs or request features
- **Email:** maintainers@proxsyncbox.dev

## 📚 Resources

- [Development Setup](docs/MODERN_DEV_SETUP.md)
- [Architecture Overview](docs/README.md)
- [Testing Guide](docs/TESTING_SETUP.md)
- [Proxmox API Docs](https://pve.proxmox.com/wiki/Proxmox_VE_API)
- [NetBox API Docs](https://docs.netbox.dev/en/stable/rest-api/overview/)

## 📜 License

By contributing, you agree that your contributions will be licensed under the
same license as the project (MIT).

---

Thank you for contributing to ProxSyncBox! Together, we're building the best
Proxmox-NetBox synchronization tool in the galaxy! 🚀✨
