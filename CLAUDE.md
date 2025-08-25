# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Overview

ProxSyncBox is a PyQt6 desktop application that synchronizes virtualization
infrastructure between Proxmox VE and NetBox DCIM/IPAM. It handles VMs, LXC
containers, and Proxmox nodes, mapping them to NetBox's virtualization and
device models.

## Development Commands

### Running the Application

```bash
# Install dependencies (in virtual environment)
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate
pip install -r requirements.txt

# Run the main GUI application
python gui_app.py

# Test settings dialog independently (mock mode)
python settings_dialog.py
```

### Dependencies

- PyQt6 - GUI framework
- proxmoxer - Proxmox VE API client
- pynetbox - NetBox API client
- python-dotenv - Environment variable management
- requests - HTTP library

No build system, test framework, or linting tools are configured.

## Architecture

### Core Components

**Configuration Layer** (`config_*.py`)

- `config_models.py`: Dataclasses for `ProxmoxNodeConfig` and `GlobalSettings`
- `config_manager.py`: Low-level `.env` file I/O operations using python-dotenv
- `config_loader.py`: High-level config loading/saving with type conversion
  between strings and dataclass fields

**API Handlers**

- `proxmox_handler.py`: Proxmox API interactions via ProxmoxAPI client
  - VM/LXC fetching with QEMU guest agent support for IP discovery
  - Node hardware details extraction
  - Network interface enumeration (physical, bridges, bonds, VLANs)
  - SSH fallback for MAC address fetching (optional)

- `netbox_handler.py`: NetBox API operations via pynetbox
  - Creates/updates virtualization objects (VMs, clusters, interfaces)
  - Creates/updates DCIM objects (devices, sites, manufacturers)
  - Manages custom fields for Proxmox-specific metadata
  - Handles IP address assignments and VLAN tagging

**Orchestration** (`sync_orchestrator.py`)

- `sync_to_netbox()`: Main VM/LXC sync logic with interface/disk/tag mapping
- `mark_orphaned_vms_as_deleted()`: Marks NetBox VMs as deleted if missing from
  Proxmox
- `sync_proxmox_node_to_netbox_device()`: Maps Proxmox node to NetBox device
  with interfaces

**GUI Layer**

- `gui_app.py`: Main PyQt6 application (`ProxmoxToNetboxApp`)
  - Multi-threaded operations using QThread for API calls
  - Real-time log display via custom `QtLogHandler`
  - VM selection interface with bulk operations
- `settings_dialog.py`: Configuration management UI
  - Global settings tab (NetBox connection)
  - Proxmox nodes tab (add/edit/remove nodes)

### Key Design Patterns

1. **Configuration Management**: Settings stored in `.env` file with
   prefix-based node identification (`PROXMOX_NODE_<ID_NAME>_*`)

2. **Thread Safety**: All API operations run in background threads via `QThread`
   to maintain UI responsiveness

3. **Custom Field Mapping**: Extensive use of NetBox custom fields to store
   Proxmox-specific metadata:
   - VM fields: `vmid`, `cpu_sockets`, `qemu_*`, `lxc_*`, `boot_disk_*`
   - Device fields: `proxmox_*` for hardware specs
   - Interface fields: `bridge`, `interface_model`, `proxmox_interface_*`

4. **Interface Preservation**: NetBox interfaces with `mgmt_only=True` are
   preserved during sync (for OOB management interfaces)

5. **IP Discovery Hierarchy**:
   - Static IPs from Proxmox config (highest priority)
   - QEMU Guest Agent for running VMs (DHCP fallback)
   - SSH MAC address lookup (optional, for network scanning)

## Critical Implementation Details

### NetBox Object Creation Flow

1. Ensure cluster type exists (`Proxmox VE` by default)
2. Get/create cluster for the Proxmox node
3. For each VM/LXC:
   - Create/update VM object with status mapping
   - Sync interfaces with MAC addresses
   - Assign IP addresses (create if needed)
   - Apply VLAN tags
   - Sync virtual disks
   - Apply Proxmox tags as NetBox tags
   - Update custom fields with Proxmox metadata

### Status Mapping

- Proxmox "running" → NetBox "active"
- Proxmox "stopped" → NetBox "offline"
- Others → NetBox "staged"
- Deleted VMs → Custom field `vm_status = "Deleted"`

### Required NetBox Custom Fields

The application expects specific custom fields in NetBox (see
`assets/Custom Fields.csv`). These must be created manually or imported before
first sync.

## Environment Variables

Configuration via `.env` file in application root:

```
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=<api_token>
NETBOX_CLUSTER_TYPE_NAME=Proxmox VE

PROXMOX_NODE_<ID_NAME>_ID_NAME=<unique_id>
PROXMOX_NODE_<ID_NAME>_HOST=<proxmox_host>
PROXMOX_NODE_<ID_NAME>_NODE_NAME=<node_name>
PROXMOX_NODE_<ID_NAME>_USER=<user@realm>
PROXMOX_NODE_<ID_NAME>_TOKEN_NAME=<token_name>
PROXMOX_NODE_<ID_NAME>_TOKEN_SECRET=<token_secret>
PROXMOX_NODE_<ID_NAME>_NETBOX_CLUSTER_NAME=<cluster_name>
PROXMOX_NODE_<ID_NAME>_VERIFY_SSL=true/false
```
