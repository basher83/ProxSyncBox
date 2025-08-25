# Development Priorities

## Immediate Fixes (This Week)

These are critical issues that affect basic functionality:

### 1. **Auto-create Custom Fields** 🔴

- **Problem:** First-time users hit errors immediately
- **Solution:** Check and create fields on startup
- **Effort:** 2-3 hours
- **Files:** `netbox_handler.py`, `gui_app.py`

### 2. **Fix MAC Address Detection** 🔴

- **Problem:** MAC addresses showing as `None` for some interfaces
- **Solution:** Parse Proxmox config correctly
- **Effort:** 1-2 hours
- **Files:** `proxmox_handler.py`

### 3. **Input Validation** 🟡

- **Problem:** Invalid characters crash the sync (e.g., parentheses in
  manufacturer)
- **Solution:** Validate and sanitize all NetBox inputs
- **Effort:** 2-3 hours
- **Files:** `sync_orchestrator.py`, `netbox_handler.py`

## Short Term (Next Month)

### Documentation Sprint

1. **Installation Guide** - Step-by-step with screenshots
2. **API Token Setup** - Clear permission requirements
3. **Troubleshooting Guide** - Common issues and solutions
4. **Architecture Diagram** - Visual representation of data flow

### Testing Framework

1. **Unit Tests** - At least 50% coverage
   - Start with `proxmox_handler.py`
   - Then `netbox_handler.py`
   - Finally `sync_orchestrator.py`
2. **Mock API Responses** - For offline testing
3. **CI Pipeline** - GitHub Actions for PRs

### UI Polish

1. **Progress Indicators** - Show sync progress
2. **Better Error Dialogs** - Actionable error messages
3. **Connection Test** - In settings dialog
4. **VM Search/Filter** - For large environments

## Medium Term (Next Quarter)

### Performance

1. **Parallel Processing** - Sync multiple VMs simultaneously
2. **Incremental Sync** - Only update changed items
3. **Batch API Calls** - Reduce API requests

### Features

1. **Dry Run Mode** - Preview changes before applying
2. **CLI Mode** - For automation/scripting
3. **Scheduling** - Built-in scheduler for periodic sync

### Code Quality

1. **Type Hints** - Add throughout codebase
2. **Refactor Long Functions** - Max 50 lines per function
3. **Error Recovery** - Graceful handling of partial failures

## Long Term (Next 6 Months)

### Major Features

1. **Multi-NetBox Support** - Sync to multiple instances
2. **Webhook Integration** - Real-time sync triggers
3. **Docker Container** - Easy deployment
4. **REST API Mode** - Run as a service

### Community

1. **Plugin System** - Allow extensions
2. **Contribution Guide** - Make it easy to contribute
3. **Release Process** - Regular versioned releases
4. **Documentation Site** - Proper docs with search

## Technical Debt to Address

### High Priority

- [ ] Remove hardcoded values
- [ ] Centralize configuration validation
- [ ] Consistent error handling pattern
- [ ] Logging levels review

### Medium Priority

- [ ] Reduce code duplication
- [ ] Improve separation of concerns
- [ ] Add data models/schemas
- [ ] Upgrade to latest PyQt6 patterns

### Low Priority

- [ ] Code formatting (Black/Ruff)
- [ ] Docstring standards
- [ ] Remove unused imports
- [ ] Optimize imports

## Resource Requirements

### For Core Team

- **Maintainer:** 10-15 hours/week
- **Testing:** 5 hours/week
- **Documentation:** 3-5 hours/week

### Community Contributions Welcome

- Bug fixes
- Documentation improvements
- Test cases
- Feature requests with PRs
- Translations

## Success Metrics

- Zero crash reports for basic operations
- < 5 minutes setup time for new users
- 90% test coverage
- < 10 open bugs
- Response to issues within 48 hours
- Monthly release cycle
