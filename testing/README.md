# Testing Directory

This directory contains all test scripts, fixtures, and integration tests for ProxSyncBox.

## ⚠️ Note
This entire directory is gitignored to keep test data and experimental scripts out of the main repository.

## 📂 Structure

```
testing/
├── scripts/           # Diagnostic and test scripts
│   ├── test_basic.py              # Basic import and functionality tests
│   ├── test_connection.py         # API connection testing
│   ├── test_single_vm_sync.py     # Single VM sync testing
│   ├── check_vm_ips.py            # IP discovery diagnostics
│   └── debug_agent_check.py       # QEMU Guest Agent debugging
│
├── fixtures/          # Test data and mock responses
│   └── (create mock JSON files here)
│
└── integration/       # Integration tests
    └── (future integration test suites)
```

## 🧪 Running Tests

### Basic Tests
```bash
# Test all imports and basic functionality
python testing/scripts/test_basic.py

# Test API connections
python testing/scripts/test_connection.py

# Check VM IP discovery
python testing/scripts/check_vm_ips.py <node_name>

# Debug QEMU Guest Agent
python testing/scripts/debug_agent_check.py <node_name> <vm_filter>
```

### Single VM Testing
```bash
# Test syncing a specific VM
python testing/scripts/test_single_vm_sync.py
```

## 🎭 Mock Data

Create mock fixtures for testing without real infrastructure:

### Example Proxmox VM Response
`fixtures/proxmox_vms.example.json`:
```json
{
  "vms": [
    {
      "vmid": 100,
      "name": "test-vm-1",
      "status": "running",
      "mem": 2147483648,
      "cpus": 2
    }
  ]
}
```

### Example NetBox Response
`fixtures/netbox_cluster.example.json`:
```json
{
  "id": 1,
  "name": "TestCluster",
  "type": {
    "id": 1,
    "name": "Proxmox VE"
  }
}
```

## 🔧 Test Utilities

### Connection Testing
Use `test_connection.py` to verify:
- NetBox API connectivity
- Proxmox API connectivity
- Token permissions
- Custom field existence

### IP Discovery Testing
Use `check_vm_ips.py` to verify:
- QEMU Guest Agent status
- IP address retrieval
- Network interface detection

### Debug Utilities
Use `debug_agent_check.py` for:
- Raw agent configuration inspection
- Agent query testing
- Network interface debugging

## 📝 Creating New Tests

### Template for New Test Script
```python
#!/usr/bin/env python3
"""
Test description here
"""

import sys
import os
# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config_loader import load_app_config
# Other imports...

def test_something():
    """Test specific functionality"""
    pass

if __name__ == "__main__":
    test_something()
```

## 🚀 Future Plans

### Unit Tests (Coming Soon)
- `test_proxmox_handler.py`
- `test_netbox_handler.py`
- `test_sync_orchestrator.py`

### Integration Tests
- Full sync workflow tests
- Error recovery tests
- Performance benchmarks

### CI/CD Integration
- GitHub Actions workflow
- Automated testing on PR
- Coverage reporting

## ⚡ Quick Test Commands

```bash
# Run all basic tests
for test in testing/scripts/test_*.py; do
    echo "Running $test..."
    python "$test"
done

# Check all connections
python testing/scripts/test_connection.py

# Full diagnostic check
python testing/scripts/check_vm_ips.py holly
python testing/scripts/debug_agent_check.py holly vault
```

## 🐛 Debugging Tips

1. **Enable debug logging**: Set `LOG_LEVEL=DEBUG` in `.env`
2. **Use mock data**: Create fixtures to test without infrastructure
3. **Isolate issues**: Test one component at a time
4. **Check permissions**: Use `test_connection.py` first

---

*Note: Remember to activate your virtual environment before running tests:*
```bash
source venv/bin/activate  # Linux/macOS
# or
.\venv\Scripts\activate  # Windows
```