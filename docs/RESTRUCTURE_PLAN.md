# Project Restructuring Plan

## Executive Summary

Transform ProxSyncBox from a flat-file script collection into a modern, well-structured Python
package following 2025 best practices. This is a complete modernization effort with no backwards
compatibility concerns.

## Philosophy

> "If people wanna use my way then cool but no harm no foul"

This fork diverges intentionally from the original to embrace:

- Modern Python packaging standards (PEP 517/518/621)
- Professional project structure
- Comprehensive tooling and automation
- Clear separation of concerns
- Developer experience first

## Current State Analysis

### Problems with Current Structure

```
ProxSyncBox/
├── gui_app.py              # 😬 Everything in root
├── netbox_handler.py       # 😬 No package structure
├── proxmox_handler.py      # 😬 No namespacing
├── sync_orchestrator.py    # 😬 Hard to navigate
├── config_loader.py        # 😬 No clear organization
├── config_manager.py       # 😬 Mixed concerns
├── config_models.py        # 😬 No module boundaries
├── settings_dialog.py      # 😬 GUI mixed with logic
├── utils.py                # 😬 Vague naming
└── requirements.txt        # 😬 Old-style deps
```

### Issues

- **No package structure** - Can't `pip install` properly
- **No namespacing** - Everything is global
- **Poor discoverability** - Where is what?
- **Testing nightmare** - No clear boundaries
- **Import hell** - Relative imports everywhere
- **Not scalable** - Where do new features go?

## Proposed Modern Structure

```
ProxSyncBox/
├── src/
│   └── proxsyncbox/                    # Main package namespace
│       ├── __init__.py                 # Package initialization
│       ├── __version__.py              # Single source of version truth
│       ├── __main__.py                 # Entry: python -m proxsyncbox
│       ├── cli.py                      # CLI argument parsing
│       │
│       ├── gui/                        # GUI Layer
│       │   ├── __init__.py
│       │   ├── app.py                  # Main QT application
│       │   ├── main_window.py          # Primary window
│       │   ├── dialogs/                # Dialog components
│       │   │   ├── __init__.py
│       │   │   ├── settings.py         # Settings dialog
│       │   │   └── about.py            # About dialog
│       │   ├── widgets/                # Custom widgets
│       │   │   ├── __init__.py
│       │   │   ├── log_viewer.py       # Log display widget
│       │   │   └── progress.py         # Progress indicators
│       │   └── resources/              # GUI resources
│       │       ├── icons/
│       │       └── styles/
│       │
│       ├── core/                       # Business Logic
│       │   ├── __init__.py
│       │   ├── models.py               # Data models
│       │   ├── sync.py                 # Sync orchestration
│       │   ├── mapper.py               # Data mapping logic
│       │   └── validators.py           # Business validations
│       │
│       ├── api/                        # External APIs
│       │   ├── __init__.py
│       │   ├── base.py                 # Base API client
│       │   ├── netbox/                 # NetBox integration
│       │   │   ├── __init__.py
│       │   │   ├── client.py           # NetBox API client
│       │   │   ├── models.py           # NetBox data models
│       │   │   └── handlers.py         # NetBox operations
│       │   └── proxmox/                # Proxmox integration
│       │       ├── __init__.py
│       │       ├── client.py           # Proxmox API client
│       │       ├── models.py           # Proxmox data models
│       │       └── handlers.py         # Proxmox operations
│       │
│       ├── config/                     # Configuration Management
│       │   ├── __init__.py
│       │   ├── loader.py               # Config loading
│       │   ├── models.py               # Config data models
│       │   ├── manager.py              # Config management
│       │   ├── validators.py           # Config validation
│       │   └── defaults.py             # Default values
│       │
│       ├── utils/                      # Utilities
│       │   ├── __init__.py
│       │   ├── logging.py              # Logging configuration
│       │   ├── network.py              # Network helpers
│       │   ├── formatting.py           # Data formatters
│       │   └── exceptions.py           # Custom exceptions
│       │
│       └── plugins/                    # Plugin system (future)
│           ├── __init__.py
│           └── base.py                 # Plugin interface
│
├── tests/                              # Test Suite
│   ├── __init__.py
│   ├── conftest.py                     # Pytest configuration
│   ├── unit/                           # Unit tests
│   │   ├── test_models.py
│   │   ├── test_sync.py
│   │   ├── test_config.py
│   │   └── api/
│   │       ├── test_netbox.py
│   │       └── test_proxmox.py
│   ├── integration/                    # Integration tests
│   │   ├── test_sync_flow.py
│   │   └── test_api_integration.py
│   ├── e2e/                            # End-to-end tests
│   │   └── test_full_sync.py
│   └── fixtures/                       # Test data
│       ├── netbox_responses.json
│       └── proxmox_responses.json
│
├── scripts/                            # Utility scripts
│   ├── migrate_config.py               # Config migration helper
│   ├── test_connection.py              # Connection tester
│   └── import_custom_fields.py         # NetBox field importer
│
├── docs/                               # Documentation (already good!)
├── .github/                            # GitHub configs
├── .vscode/                            # Editor configs
├── .mise.toml                          # Task runner
├── pyproject.toml                      # Package configuration
├── uv.lock                             # Dependency lock
├── CHANGELOG.md                        # Release history
├── README.md                           # Project overview
└── LICENSE                             # MIT License
```

## Migration Steps

### Phase 1: Structure Creation

```bash
# Create new structure
mkdir -p src/proxsyncbox/{gui,core,api,config,utils,plugins}
mkdir -p src/proxsyncbox/gui/{dialogs,widgets,resources}
mkdir -p src/proxsyncbox/api/{netbox,proxmox}
mkdir -p tests/{unit,integration,e2e,fixtures}
mkdir -p scripts
```

### Phase 2: File Migration Map

| Current File           | New Location                                    | Notes                 |
| ---------------------- | ----------------------------------------------- | --------------------- |
| `gui_app.py`           | `src/proxsyncbox/gui/app.py` + `main_window.py` | Split into components |
| `settings_dialog.py`   | `src/proxsyncbox/gui/dialogs/settings.py`       | Move to dialogs       |
| `config_loader.py`     | `src/proxsyncbox/config/loader.py`              | Config subsystem      |
| `config_manager.py`    | `src/proxsyncbox/config/manager.py`             | Config subsystem      |
| `config_models.py`     | `src/proxsyncbox/config/models.py`              | Config subsystem      |
| `netbox_handler.py`    | `src/proxsyncbox/api/netbox/handlers.py`        | API layer             |
| `proxmox_handler.py`   | `src/proxsyncbox/api/proxmox/handlers.py`       | API layer             |
| `sync_orchestrator.py` | `src/proxsyncbox/core/sync.py`                  | Core logic            |
| `utils.py`             | `src/proxsyncbox/utils/`                        | Split by function     |
| `testing/*.py`         | `scripts/`                                      | Utility scripts       |

### Phase 3: Import Updates

#### Before

```python
from config_loader import load_config
from netbox_handler import NetBoxHandler
import utils
```

#### After

```python
from proxsyncbox.config import load_config
from proxsyncbox.api.netbox import NetBoxHandler
from proxsyncbox.utils import format_data
```

### Phase 4: Package Configuration

Update `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "proxsyncbox"
version = "2.0.0"  # Major version bump for restructure
description = "Modern Proxmox to NetBox synchronization tool"

[tool.setuptools]
package-dir = {"" = "src"}
packages = ["proxsyncbox"]

[tool.setuptools.packages.find]
where = ["src"]
include = ["proxsyncbox*"]

[project.scripts]
proxsyncbox = "proxsyncbox.cli:main"
proxsyncbox-gui = "proxsyncbox.gui.app:main"
```

### Phase 5: Entry Points

Create proper entry points:

`src/proxsyncbox/__main__.py`:

```python
"""Main entry point for python -m proxsyncbox."""
from proxsyncbox.cli import main

if __name__ == "__main__":
    main()
```

`src/proxsyncbox/cli.py`:

```python
"""CLI interface for ProxSyncBox."""
import argparse
import sys

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true", help="Launch GUI")
    parser.add_argument("--sync", action="store_true", help="Run sync")
    args = parser.parse_args()

    if args.gui:
        from proxsyncbox.gui.app import launch_gui
        launch_gui()
    elif args.sync:
        from proxsyncbox.core.sync import run_sync
        run_sync()
```

## Benefits After Restructuring

### Developer Experience

- ✅ **Clear navigation** - "Where's the NetBox code?" → `api/netbox/`
- ✅ **Proper imports** - `from proxsyncbox.api import NetBoxClient`
- ✅ **Easy testing** - Mirror structure in tests
- ✅ **Plugin ready** - Extension points built in
- ✅ **IDE friendly** - Auto-completion works properly

### Code Quality

- ✅ **Separation of concerns** - GUI, API, Core logic separated
- ✅ **Single responsibility** - Each module has one job
- ✅ **Dependency injection** - Easier to mock and test
- ✅ **Type hints** - Proper package structure enables better typing

### Maintenance

- ✅ **Easy to extend** - Clear where new features go
- ✅ **Easy to refactor** - Isolated components
- ✅ **Easy to document** - Clear module boundaries
- ✅ **Easy to version** - Semantic versioning makes sense

## Implementation Checklist

- [ ] Create new directory structure
- [ ] Move files to new locations
- [ ] Update all imports
- [ ] Create **init**.py files with proper exports
- [ ] Update pyproject.toml
- [ ] Create entry point scripts
- [ ] Update mise tasks
- [ ] Run all tests
- [ ] Update documentation
- [ ] Update CHANGELOG
- [ ] Tag as v2.0.0

## Commit Strategy

```bash
# Single atomic commit for the restructure
git checkout -b feature/modern-package-structure
# ... do all the work ...
git add -A
git commit -m "refactor: restructure project to modern Python package layout

BREAKING CHANGE: Complete project restructure to follow modern Python packaging standards.

- Migrate from flat file structure to src-layout package structure
- Organize code into logical modules (gui, core, api, config, utils)
- Update all imports to use package namespace
- Add proper entry points for CLI and GUI
- Prepare for plugin system architecture
- Improve testability with clear module boundaries

This is a breaking change that modernizes the entire project structure.
No backwards compatibility is maintained with v1.x.

Part of the modernization initiative to bring the project to 2025 standards."
```

## Post-Restructure Tasks

1. **Update CI/CD** - Adjust paths in GitHub Actions
2. **Update Documentation** - New import examples
3. **Create Migration Guide** - For any existing users
4. **Update README** - New installation instructions
5. **Create Developer Guide** - How to contribute with new structure

## Success Criteria

- [ ] All tests pass
- [ ] GUI launches correctly
- [ ] Sync operations work
- [ ] Can install with `pip install -e .`
- [ ] Imports are clean and logical
- [ ] No files in root except configs and docs
- [ ] Clear separation of concerns

## Timeline

- **Day 1**: Structure creation and file migration
- **Day 2**: Import updates and testing
- **Day 3**: Documentation and final polish

## Notes

This restructure is about **doing it right** not **keeping it compatible**. We're building for the
future, not maintaining the past. The goal is a clean, modern, maintainable codebase that follows
Python best practices and makes development a joy.

---

_"Modern tooling, lots of docs, and plenty of tools and helpers to streamline things and put it all
in a nice order of operations with standards enforced"_ - This restructure embodies this philosophy.
