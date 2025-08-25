# Development Utilities

This directory contains utility scripts for development, setup, and maintenance of ProxSyncBox.

## ⚠️ Note
This entire directory is gitignored to keep development utilities out of the main repository.

## 📂 Contents

```
dev_utils/
├── import_custom_fields.py      # Import NetBox custom fields from CSV
├── fix_vm_status_field.py       # Fix vm_status field creation
└── setup_netbox_custom_fields.py # Alternative custom field setup
```

## 🛠️ Setup Utilities

### NetBox Custom Fields Setup
```bash
# Import all custom fields from CSV
python dev_utils/import_custom_fields.py

# Or use the alternative setup script
python dev_utils/setup_netbox_custom_fields.py

# Fix specific field issues
python dev_utils/fix_vm_status_field.py
```

## 🔧 Development Scripts

### Creating New Utilities

Template for development utilities:
```python
#!/usr/bin/env python3
"""
Utility description
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import load_app_config
from netbox_handler import get_netbox_api_client

def main():
    """Main utility function"""
    global_settings, node_configs = load_app_config()
    
    # Utility logic here
    pass

if __name__ == "__main__":
    sys.exit(main())
```

## 📋 Utility Categories

### Setup & Configuration
- `import_custom_fields.py` - First-time NetBox setup
- `fix_vm_status_field.py` - Fix field creation issues

### Data Management (Future)
- `export_config.py` - Export configuration
- `backup_netbox_data.py` - Backup before major changes
- `cleanup_orphans.py` - Remove deleted VMs

### Development Helpers (Future)
- `generate_mock_data.py` - Create test fixtures
- `profile_performance.py` - Performance analysis
- `check_api_limits.py` - API rate limit testing

### Migration Tools (Future)
- `migrate_v1_to_v2.py` - Version migrations
- `convert_config_format.py` - Config format updates

## 🚀 Quick Commands

### Initial Setup
```bash
# Complete NetBox setup
python dev_utils/import_custom_fields.py
```

### Fix Common Issues
```bash
# Fix manufacturer name in .env
sed -i 's/(HK)/HK/g' .env

# Fix custom field issues
python dev_utils/fix_vm_status_field.py
```

### Development Tasks
```bash
# Check what custom fields exist
python -c "
from config_loader import load_app_config
from netbox_handler import get_netbox_api_client
gs, _ = load_app_config()
nb = get_netbox_api_client(gs.netbox_url, gs.netbox_token)
fields = nb.extras.custom_fields.all()
for f in fields:
    print(f'{f.name}: {f.type}')
"
```

## 🔒 Security Notes

**WARNING**: These utilities have direct API access. Always:
1. Test in development environment first
2. Backup NetBox data before bulk operations
3. Never commit utilities with hardcoded credentials
4. Use read-only operations when possible

## 📝 Creating New Utilities

### Checklist for New Utilities
- [ ] Clear docstring explaining purpose
- [ ] Argument parsing for flexibility
- [ ] Dry-run mode by default
- [ ] Confirmation prompts for destructive operations
- [ ] Proper error handling
- [ ] Logging for audit trail
- [ ] Progress indicators for long operations

### Example: Safe Utility Pattern
```python
def dangerous_operation(dry_run=True):
    """Perform potentially destructive operation"""
    
    if dry_run:
        print("DRY RUN - No changes will be made")
    
    items = get_items_to_modify()
    
    if not dry_run:
        response = input(f"About to modify {len(items)} items. Continue? (y/N): ")
        if response.lower() != 'y':
            print("Operation cancelled")
            return
    
    for item in items:
        if dry_run:
            print(f"Would modify: {item}")
        else:
            modify_item(item)
            print(f"Modified: {item}")
```

## 🎯 Planned Utilities

### High Priority
- [ ] `validate_config.py` - Check .env configuration
- [ ] `test_permissions.py` - Verify API permissions
- [ ] `generate_test_data.py` - Create mock data

### Medium Priority
- [ ] `sync_report.py` - Generate sync statistics
- [ ] `diff_environments.py` - Compare Proxmox vs NetBox
- [ ] `cleanup_custom_fields.py` - Remove unused fields

### Low Priority
- [ ] `benchmark_sync.py` - Performance testing
- [ ] `export_to_csv.py` - Export data for analysis
- [ ] `visualize_infrastructure.py` - Generate diagrams

---

*Remember: These utilities modify production systems. Always test first!*