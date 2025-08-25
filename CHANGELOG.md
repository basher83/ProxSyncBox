# Changelog

All notable changes to ProxSyncBox will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Modern development workflow using `mise` task runner for dependency and tool management
- Comprehensive `mise` configuration with 29 pre-defined tasks for common development operations
- `uv` package manager integration for fast Python dependency management
- Prettier configuration for consistent code formatting across all file types
- VSCode/Cursor editor settings for optimal development experience
- Markdownlint configuration for consistent documentation formatting
- Security policy documentation (SECURITY.md)
- Contributing guidelines (CONTRIBUTING.md)
- Organized test structure in `testing/` directory with README and examples
- Development documentation in `docs/` directory:
  - ROADMAP.md with 4-phase development plan
  - DEVELOPMENT_PRIORITIES.md with prioritized enhancement tasks
  - QOL_IMPROVEMENTS.md for quality of life improvements
  - TESTING_SETUP.md with comprehensive testing guide
- Custom field import scripts for NetBox 4.x compatibility
- IP address discovery via QEMU Guest Agent (requires VM.Monitor permission)
- Support for multiple Proxmox nodes in configuration
- Comprehensive logging throughout sync operations

### Changed

- Migrated from Makefile to modern `mise` task runner
- Updated Python package configuration to use `py-modules` instead of `packages`
- Migrated ruff configuration to new `lint` section format in pyproject.toml
- All Python commands now use `uv run` for proper virtual environment activation
- All Node.js tools now use `mise exec` for consistent tool management
- Improved error handling with detailed logging for troubleshooting
- Enhanced NetBox field validation with better error messages

### Fixed

- Missing `paramiko` dependency added to requirements
- Proxmox token authentication format (removed realm/user prefix requirement)
- NetBox manufacturer name validation (removed parentheses for slug compatibility)
- Custom field creation for NetBox 4.x API compatibility
- IP address discovery now works with proper VM.Monitor permissions
- Multiple statements on single line Python code style issues
- Import organization and unused imports cleaned up
- Type comparison issues using `isinstance()` instead of `==`

### Security

- Added comprehensive security policy with vulnerability reporting guidelines
- Configured secret scanning with detect-secrets pre-commit hook
- Added bandit security linting task for Python code analysis
- Improved credential handling in `.env` configuration

## [1.0.0] - 2024-01-01

### Added

- Initial release of ProxSyncBox
- PyQt6 GUI application for syncing Proxmox VE infrastructure to NetBox
- Support for syncing:
  - Virtual machines with full metadata
  - Clusters and cluster types
  - VM network interfaces
  - Custom fields for Proxmox-specific data
- Real-time sync progress indication
- Configurable via `.env` file
- Support for NetBox tags
- Orphan VM detection and management

### Known Issues

- VM templates are skipped during sync (by design)
- Proxmox SDN VNets/Subnets not yet supported
- Container (LXC) synchronization not yet implemented
- No automatic sync scheduling (manual trigger only)

## Future Releases

### [1.1.0] - Planned

- Container (LXC) synchronization support
- Automatic sync scheduling with cron/systemd timers
- Proxmox SDN VNets and Subnets synchronization
- Storage information synchronization
- Backup status tracking

### [1.2.0] - Planned

- Web UI alternative to PyQt6
- REST API for programmatic access
- Multi-cluster support improvements
- Performance optimizations for large environments
- Bulk operations support

### [2.0.0] - Future

- Bi-directional sync (NetBox to Proxmox)
- Terraform provider integration
- Ansible collection for automation
- Kubernetes operator for cloud-native deployments
- Advanced filtering and mapping rules

---

For more details on upcoming features, see [ROADMAP.md](docs/ROADMAP.md)
