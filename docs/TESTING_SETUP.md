# ProxSyncBox Testing Setup Guide

## Setup Completed

### 1. Environment Setup

- ✅ Python 3.13.7 confirmed
- ✅ Virtual environment created
- ✅ Dependencies installed from requirements.txt
- ✅ Fixed missing `paramiko` dependency (added to requirements.txt)
- ✅ GUI launches successfully

### 2. Issues Found & Fixed

**Issue 1: Missing paramiko dependency**

- The application imports `paramiko` in `proxmox_handler.py` for SSH
  functionality
- Not listed in original `requirements.txt`
- **Fix**: Added `paramiko` to requirements.txt

**Issue 2: Invalid manufacturer name format**

- Manufacturer name "Micro Computer (HK) Tech Limited" contained parentheses
- NetBox slugs don't allow parentheses
- **Fix**: Changed to "Micro Computer HK Tech Limited" in .env

**Issue 3: Missing NetBox custom fields**

- ProxSyncBox requires 28 custom fields in NetBox for Proxmox metadata
- Fields must be created before first sync
- **Fix**: Created import script `import_custom_fields.py` and imported all
  fields

**Issue 4: Token permissions for IP discovery**

- IP addresses weren't being discovered from VMs
- Required `VM.Monitor` permission for QEMU Guest Agent queries
- **Fix**: Added `VM.Monitor` permission to Proxmox API token

### 3. Testing Without Real Infrastructure

To test the application without actual Proxmox/NetBox instances:

#### Option 1: Mock Testing (Quick)

1. GUI launches and shows the main window
2. Settings dialog is accessible via File > Settings
3. Can add/edit node configurations (they save to .env)
4. UI elements are responsive

#### Option 2: Local Test Environment (Comprehensive)

Set up test instances:

**NetBox** (easiest with Docker):

```bash
git clone https://github.com/netbox-community/netbox-docker.git
cd netbox-docker
docker-compose up -d
# Default: http://localhost:8000
# Create admin user: docker-compose exec netbox python manage.py createsuperuser
```

**Proxmox VE** (requires more setup):

- Use nested virtualization in VMware/VirtualBox
- Or use Proxmox VE ISO: https://www.proxmox.com/en/downloads
- Minimum: 2GB RAM, 20GB disk

### 4. Configuration Template

Use this `.env` configuration for testing:

```env
# NetBox (local Docker instance)
NETBOX_URL=http://localhost:8000
NETBOX_TOKEN=[generate from NetBox admin panel]
NETBOX_CLUSTER_TYPE_NAME=Proxmox VE

# Test Proxmox Node
PROXMOX_NODE_TEST-NODE_ID_NAME=test-node
PROXMOX_NODE_TEST-NODE_HOST=192.168.1.100
PROXMOX_NODE_TEST-NODE_NODE_NAME=pve
PROXMOX_NODE_TEST-NODE_USER=root@pam
PROXMOX_NODE_TEST-NODE_TOKEN_NAME=test_token
PROXMOX_NODE_TEST-NODE_TOKEN_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PROXMOX_NODE_TEST-NODE_NETBOX_CLUSTER_NAME=TestCluster
PROXMOX_NODE_TEST-NODE_VERIFY_SSL=false
```

### 5. Functional Testing Checklist

With real/test infrastructure:

- [x] Configure NetBox connection in Settings
- [x] Add Proxmox node configuration
- [x] Test "Load VMs/LXCs" button
- [x] Select VMs and test sync to NetBox
- [x] Verify VM details in NetBox (interfaces, IPs, tags)
- [x] Test "Sync Node to NetBox Device"
- [x] Check NetBox custom fields are created
- [x] Test orphan VM detection (confirmed working - marks VMs as "Deleted" in
      custom field)
- [x] Verify logs display correctly

**Successfully Tested Configuration:**

- NetBox v4.3.5
- Proxmox VE v8.4.9
- 3-node cluster ("doggos": lloyd, holly, mable)
- IP discovery via QEMU Guest Agent working
- All custom fields properly syncing

### 6. Potential Improvements Identified

1. **Dependency Management**
   - Add `paramiko` to requirements.txt ✅
   - Consider using `requirements-dev.txt` for optional dependencies
   - Add version pinning for stability

2. **Error Handling**
   - No validation when .env is empty
   - Should show helpful message on first launch
   - Need better error messages for missing config

3. **Testing**
   - No unit tests present
   - Could add pytest with mock Proxmox/NetBox responses
   - Integration test suite would be valuable

4. **Documentation**
   - Missing info about paramiko SSH requirements
   - Could add troubleshooting section
   - Screenshots would help new users

5. **Code Structure**
   - Consider async/await for API calls
   - Could benefit from type hints throughout
   - Configuration validation could be stronger

## Next Steps for Testing

1. **Basic UI Test** (no infrastructure needed):

   ```bash
   source venv/bin/activate
   python gui_app.py
   ```

   - Navigate through Settings dialog
   - Add dummy node configurations
   - Verify they save to .env

2. **Mock API Test** (intermediate):
   - Create mock Proxmox/NetBox servers with Flask/FastAPI
   - Test full sync workflow with fake data

3. **Full Integration Test** (requires setup):
   - Set up NetBox Docker instance
   - Set up Proxmox VE in VM or physical server
   - Run through complete workflow

## Commands for Development

```bash
# Activate virtual environment
source venv/bin/activate  # macOS/Linux
# or
.\venv\Scripts\activate  # Windows

# Run the application
python gui_app.py

# Test settings dialog standalone
python settings_dialog.py

# Check for import errors
python -c "from gui_app import ProxmoxToNetboxApp"

# Import NetBox custom fields
python import_custom_fields.py

# Test connections to both APIs
python test_connection.py

# Check VM IP discovery
python check_vm_ips.py <node_name>

# Test single VM sync
python test_single_vm_sync.py
```

## Required Proxmox Token Permissions

For full functionality, the Proxmox API token needs:

- `Sys.Audit` - Read node information
- `VM.Audit` - Read VM configuration
- `VM.Monitor` - **Critical for IP discovery via QEMU Guest Agent**

## IP Address Discovery

ProxSyncBox discovers IP addresses through two methods:

1. **Static IPs** - Rarely used, configured directly in Proxmox VM settings
2. **QEMU Guest Agent** - Primary method for DHCP-assigned IPs

### Requirements for IP Discovery:

1. Install guest agent in VM: `apt install qemu-guest-agent`
2. Enable in Proxmox: VM → Options → QEMU Guest Agent → Enable
3. Ensure token has `VM.Monitor` permission
4. VM must be running for agent queries to work

## Orphan Detection

ProxSyncBox automatically detects and marks "orphaned" resources:

**For VMs:**

- Compares all VMs in NetBox cluster against active Proxmox VMs
- VMs that no longer exist in Proxmox are marked with `vm_status = "Deleted"`
- Matches by both VM name and VMID to handle renames

**For Interfaces:**

- When syncing nodes: Removes interfaces that no longer exist on the Proxmox
  node
- Exception: Interfaces with `mgmt_only = True` are preserved (for OOB
  management)
- Log example: "Deleting orphaned interface 'net1' (ID: 74) from NetBox"

**For Virtual Disks:**

- Removes disks from NetBox VMs that no longer exist in Proxmox configuration
