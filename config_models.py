from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ProxmoxNodeConfig:
    id_name: str
    host: str
    node_name: str
    user: str
    token_name: str
    token_secret: str
    netbox_cluster_name: str
    # Fields to represent the Proxmox node as a Device in NetBox
    netbox_node_site_name: Optional[str] = field(default=None)
    netbox_node_device_role_name: Optional[str] = field(default="Hypervisor")
    netbox_node_manufacturer_name: Optional[str] = field(default=None)
    netbox_node_device_type_name: Optional[str] = field(default=None)
    netbox_node_platform_name: Optional[str] = field(default=None) # Optional, can be filled by the PVE version
    verify_ssl: bool = field(default=False)
    # SSH settings for fetching MAC addresses directly from the node
    enable_ssh_mac_fetch: bool = field(default=False) # Toggle for SSH MAC fetching
    ssh_host: Optional[str] = field(default=None) # Can be different from API host if needed, otherwise defaults to API host
    ssh_port: Optional[int] = field(default=22)
    ssh_user: Optional[str] = field(default=None)
    ssh_password: Optional[str] = field(default=None) # Store securely or use key-based auth
    ssh_key_path: Optional[str] = field(default=None) # Path to private SSH key

    def __post_init__(self):
        if not self.netbox_cluster_name: # Ensures that netbox_cluster_name has a value
            self.netbox_cluster_name = self.node_name

@dataclass
class GlobalSettings:
    netbox_url: Optional[str] = None
    netbox_token: Optional[str] = None
    netbox_cluster_type_name: str = field(default="Proxmox VE")
    log_level: str = field(default="INFO") # Added log level setting