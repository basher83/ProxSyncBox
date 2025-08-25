# ProxSyncBox Roadmap

## Vision

Transform ProxSyncBox from a functional sync tool into a polished,
enterprise-ready solution for Proxmox-NetBox integration.

## Current State (v1.0 - Foundation)

✅ Core sync functionality working ✅ Multi-node support ✅ IP discovery via
QEMU Guest Agent ✅ Orphan detection ✅ GUI with real-time logging

## Phase 1: Polish & Stability (v1.1)

**Goal:** Fix known issues and improve reliability

### High Priority

- [ ] Auto-create NetBox custom fields on first run
- [ ] Add input validation for manufacturer names (slug-safe)
- [ ] Better error messages with suggested fixes
- [ ] Add retry logic for transient API failures
- [ ] Fix MAC address detection for interfaces

### Documentation

- [ ] Comprehensive installation guide
- [ ] Token permission requirements upfront
- [ ] Troubleshooting guide with common issues
- [ ] Video tutorial/demo

### Testing

- [ ] Unit tests for core functions
- [ ] Integration tests with mock APIs
- [ ] GitHub Actions CI/CD pipeline

## Phase 2: Quality of Life (v1.2)

**Goal:** Make the tool easier and more pleasant to use

### UI/UX Improvements

- [ ] Progress bar for sync operations
- [ ] Dry-run mode to preview changes
- [ ] Filter/search for VMs in the list
- [ ] Save VM selection between runs
- [ ] Dark mode theme
- [ ] System tray integration

### Configuration

- [ ] Configuration wizard for first-time setup
- [ ] Test connection button in settings
- [ ] Import/export configuration profiles
- [ ] Environment variable support (in addition to .env)

### Performance

- [ ] Parallel VM processing
- [ ] Incremental sync (only changed VMs)
- [ ] Caching for unchanged data
- [ ] Batch API operations

## Phase 3: Advanced Features (v2.0)

**Goal:** Enterprise features and automation

### Automation

- [ ] Scheduled sync via cron/systemd
- [ ] CLI mode for headless operation
- [ ] Webhook support for real-time sync
- [ ] Docker container deployment
- [ ] Kubernetes operator

### Advanced Sync

- [ ] Bidirectional sync (NetBox → Proxmox)
- [ ] Custom field mapping configuration
- [ ] VM template support
- [ ] Backup/snapshot tracking
- [ ] Resource pool synchronization
- [ ] Storage synchronization

### Filtering & Rules

- [ ] Include/exclude VMs by regex
- [ ] Tag-based filtering
- [ ] Custom sync rules engine
- [ ] Conditional field mapping

### Monitoring & Reporting

- [ ] Sync history with rollback
- [ ] Email notifications
- [ ] Slack/Teams integration
- [ ] Metrics export (Prometheus)
- [ ] Audit logging

## Phase 4: Ecosystem Integration (v3.0)

**Goal:** Become the standard Proxmox-NetBox bridge

### Integrations

- [ ] Ansible collection
- [ ] Terraform provider
- [ ] REST API server mode
- [ ] GitOps support
- [ ] ServiceNow integration

### Multi-Environment

- [ ] Multiple NetBox instance support
- [ ] Cross-cluster synchronization
- [ ] Proxmox Backup Server integration
- [ ] Ceph storage mapping

### Enterprise Features

- [ ] RBAC for multi-user access
- [ ] SAML/OIDC authentication
- [ ] Compliance reporting
- [ ] Change approval workflow

## Community & Contribution

- [ ] Comprehensive developer documentation
- [ ] Plugin architecture for extensions
- [ ] Community module marketplace
- [ ] Regular release cycle
- [ ] Security vulnerability process

## Long-term Vision

- Become the official/recommended Proxmox-NetBox integration
- Support for other hypervisors (VMware, Hyper-V)
- SaaS offering for managed sync
- Professional support options
