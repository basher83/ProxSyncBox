import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Union
import ipaddress  # For IP address and network manipulation
import pynetbox

from utils import (
    BYTES_IN_MB, BYTES_IN_GB, map_proxmox_status_to_netbox,
    NETBOX_INTERFACE_TYPE_VIRTUAL, NETBOX_OBJECT_TYPE_VMINTERFACE,
    NETBOX_IPADDRESS_STATUS_ACTIVE, NETBOX_OBJECT_TYPE_DCIM_INTERFACE
)
from netbox_handler import (
    get_existing_vms, get_or_create_cluster, get_or_create_netbox_tags,
    get_or_create_netbox_platform, get_or_create_netbox_vlan,
    get_or_create_and_assign_netbox_mac_address,
    get_or_create_site, get_or_create_manufacturer, get_or_create_device_type,
    get_or_create_device_role, get_or_create_device_interface, get_or_create_cluster_type
)
from config_loader import NETBOX_CLUSTER_TYPE_NAME # Import global config

logger = logging.getLogger(__name__)

def sync_vm_virtual_disks(
    nb: pynetbox.api,
    netbox_vm_obj: Any, # pynetbox.core.response.Record
    proxmox_disks_data: List[Dict[str, Any]]
):
    """
    Synchronizes virtual disks of a NetBox VM with data from Proxmox.
    Creates, updates, or deletes virtual disks in NetBox to match Proxmox.

    Args:
        nb: The pynetbox API client.
        netbox_vm_obj: The NetBox VM record object.
        proxmox_disks_data: A list of dictionaries, each representing a disk from Proxmox.
    """
    if not nb or not netbox_vm_obj: # Validation
        logger.error("NetBox API or VM object not available for disk synchronization.")
        return # Early exit
    
    vm_name_log = netbox_vm_obj.name
    logger.info(f"Synchronizing virtual disks for VM: {vm_name_log}")

    try:
        existing_nb_disks = list(nb.virtualization.virtual_disks.filter(virtual_machine_id=netbox_vm_obj.id))
    except pynetbox.core.query.RequestError as e:
        logger.error(f"VM {vm_name_log}: Error fetching existing virtual disks from NetBox: {e.error if hasattr(e, 'error') else e}")
        return
        
    netbox_disks_map = {disk.name: disk for disk in existing_nb_disks}
    proxmox_disk_names_processed = set() # To track Proxmox disks that have been processed

    for p_disk_data in proxmox_disks_data:
        p_name = p_disk_data.get("name")
        p_size_mb = p_disk_data.get("size_mb")
        p_raw_config = p_disk_data.get("proxmox_raw_config")
        # Fields for potential future use with custom fields in NetBox:
        # p_storage_id = p_disk_data.get("storage_id")
        # p_format = p_disk_data.get("format")
        # p_mount_point = p_disk_data.get("mount_point")

        if not p_name:
            logger.warning(f"VM {vm_name_log}: Proxmox disk without name, skipping. Data: {p_disk_data}")
            continue
        
        proxmox_disk_names_processed.add(p_name)

        if p_size_mb is None or p_size_mb <= 0:
            logger.warning(f"VM {vm_name_log}: Proxmox disk '{p_name}' with invalid size ({p_size_mb}MB). Will not be created/updated in NetBox.")
            # If the disk exists in NetBox with this name, but now has an invalid size,
            # it will be removed from `netbox_disks_map` to avoid undue deletion if it's the only issue.
            if p_name in netbox_disks_map:
                 del netbox_disks_map[p_name] 
            continue

        disk_payload = {
            "virtual_machine": netbox_vm_obj.id,
            "name": p_name,
            "size": int(p_size_mb),
            "description": p_raw_config if p_raw_config else ""
        }

        if p_name in netbox_disks_map:
            nb_disk_obj = netbox_disks_map.pop(p_name) 
            update_payload_disk = {}
            if nb_disk_obj.size != int(p_size_mb):
                update_payload_disk["size"] = int(p_size_mb)
            
            # Update description if it changed or was not set
            if nb_disk_obj.description != p_raw_config:
                update_payload_disk["description"] = p_raw_config if p_raw_config else ""
            
            if update_payload_disk:
                logger.info(f"VM {vm_name_log}: Updating virtual disk '{p_name}' (ID: {nb_disk_obj.id}). Payload: {update_payload_disk}")
                try: nb_disk_obj.update(update_payload_disk)
                except pynetbox.core.query.RequestError as e: logger.error(f"VM {vm_name_log}: Error updating disk '{p_name}': {e.error if hasattr(e, 'error') else e}")
            else:
                logger.debug(f"VM {vm_name_log}: Virtual disk '{p_name}' (ID: {nb_disk_obj.id}) no changes.")
        else:
            logger.info(f"VM {vm_name_log}: Creating new virtual disk '{p_name}'. Payload: {disk_payload}")
            try: nb.virtualization.virtual_disks.create(**disk_payload)
            except pynetbox.core.query.RequestError as e: logger.error(f"VM {vm_name_log}: Error creating disk '{p_name}': {e.error if hasattr(e, 'error') else e}")

    for orphaned_disk_name, orphaned_nb_disk_obj in netbox_disks_map.items():
        # Only delete if the disk was not processed (i.e., no longer in Proxmox or was skipped due to invalid size but no longer exists)
        logger.info(f"VM {vm_name_log}: Deleting orphaned virtual disk '{orphaned_disk_name}' (ID: {orphaned_nb_disk_obj.id}) from NetBox.")
        try: orphaned_nb_disk_obj.delete()
        except pynetbox.core.query.RequestError as e: logger.error(f"VM {vm_name_log}: Error deleting orphaned disk '{orphaned_disk_name}': {e.error if hasattr(e, 'error') else e}")

def sync_vm_interfaces(
    nb: pynetbox.api,
    netbox_vm_obj: Any, # pynetbox.core.response.Record
    proxmox_ifaces_data: List[Dict[str, Any]]
):
    """
    Synchronizes network interfaces of a NetBox VM with data from Proxmox.
    Creates, updates interfaces, assigns MACs, VLANs, and IP addresses.

    Args:
        nb: The pynetbox API client.
        netbox_vm_obj: The NetBox VM record object.
        proxmox_ifaces_data: A list of dictionaries, each representing a network interface from Proxmox.
    """
    if not nb or not netbox_vm_obj: return
    logger.info(f"Sincronizando interfaces para VM: {netbox_vm_obj.name}")

    for p_iface_data in proxmox_ifaces_data:
        p_name = p_iface_data.get("name", "net_unnamed")
        p_mac = p_iface_data.get("mac_address")
        p_ip_cidr = p_iface_data.get("ip_cidr")
        p_bridge = p_iface_data.get("bridge")
        p_model = p_iface_data.get("model")
        p_vlan_tag = p_iface_data.get("vlan_tag")

        if not p_mac:
            logger.warning(f"Skipping interface '{p_name}' for VM {netbox_vm_obj.name} (no MAC address).")
            continue
        
        # Prepare custom fields for the interface
        interface_custom_fields = {}
        # These custom field names ('bridge', 'interface_model') must exist in your NetBox setup.
        if p_bridge: interface_custom_fields["bridge"] = p_bridge
        if p_model: interface_custom_fields["interface_model"] = p_model
        
        vlan_payload_fields = {}
        netbox_vlan_id: Optional[int] = None
        nb_iface_obj = None

        # Step 1: Try to find an existing NetBox interface by MAC address for the current VM.
        existing_by_mac = list(nb.virtualization.interfaces.filter(virtual_machine_id=netbox_vm_obj.id, mac_address=p_mac))
        if existing_by_mac:
            nb_iface_obj = existing_by_mac[0]
            logger.info(f"Interface found by MAC '{p_mac}' for VM {netbox_vm_obj.name}: '{nb_iface_obj.name}' (ID: {nb_iface_obj.id})")
            # Prepare payload for potential update
            iface_update_payload = {}
            if nb_iface_obj.name != p_name: iface_update_payload["name"] = p_name
            if not nb_iface_obj.enabled: iface_update_payload["enabled"] = True
            if interface_custom_fields: iface_update_payload["custom_fields"] = interface_custom_fields
            
            if p_vlan_tag:
                netbox_vlan_id = get_or_create_netbox_vlan(nb, p_vlan_tag)
                if netbox_vlan_id:
                    # Assuming 'access' mode for tagged VLANs on VM interfaces. Adjust if trunking is used.
                    vlan_payload_fields = {"mode": "access", "untagged_vlan": netbox_vlan_id}
                    iface_update_payload.update(vlan_payload_fields)
            
            if iface_update_payload:
                try: nb_iface_obj.update(iface_update_payload)
                except pynetbox.core.query.RequestError as e: logger.error(f"Error updating interface ID {nb_iface_obj.id} (found by MAC): {e.error if hasattr(e, 'error') else e}")

        # Step 2: If not found by MAC, try to find by name. This handles cases where MAC might have changed.
        if not nb_iface_obj:
            existing_by_name = list(nb.virtualization.interfaces.filter(virtual_machine_id=netbox_vm_obj.id, name=p_name))
            if existing_by_name:
                nb_iface_obj = existing_by_name[0]
                logger.info(f"Interface found by name '{p_name}' for VM {netbox_vm_obj.name} (ID: {nb_iface_obj.id}). Updating MAC to {p_mac.upper()}.")
                
                if p_vlan_tag:
                    netbox_vlan_id = get_or_create_netbox_vlan(nb, p_vlan_tag)
                    if netbox_vlan_id: vlan_payload_fields = {"mode": "access", "untagged_vlan": netbox_vlan_id}

                # Get or create the MAC address object and assign it to this interface
                mac_object = get_or_create_and_assign_netbox_mac_address(nb, p_mac, assign_to_interface_id=nb_iface_obj.id)
                
                # Prepare update payload for interface found by name
                update_payload_name_match = {"enabled": True, "mac_address": p_mac.upper()}
                update_payload_name_match.update(vlan_payload_fields)
                if interface_custom_fields: update_payload_name_match["custom_fields"] = interface_custom_fields
                # If MAC object was successfully created/retrieved, link it as primary
                if mac_object: update_payload_name_match["primary_mac_address"] = mac_object.id
                
                try: nb_iface_obj.update(update_payload_name_match)
                except pynetbox.core.query.RequestError as e: logger.error(f"Error updating MAC for interface '{p_name}' (ID: {nb_iface_obj.id}): {e.error if hasattr(e, 'error') else e}")

        # Step 3: If the interface was not found by MAC or name, create a new one.
        if not nb_iface_obj:
            logger.info(f"Creating new iface '{p_name}' (MAC: {p_mac}) for VM {netbox_vm_obj.name}")
            if p_vlan_tag:
                netbox_vlan_id = get_or_create_netbox_vlan(nb, p_vlan_tag)
                if netbox_vlan_id: vlan_payload_fields = {"mode": "access", "untagged_vlan": netbox_vlan_id}

            # Prepare payload for new interface creation
            create_payload = {
                "virtual_machine": netbox_vm_obj.id, "name": p_name,
                "mac_address": p_mac.upper(), "enabled": True,
                "type": NETBOX_INTERFACE_TYPE_VIRTUAL,
                "custom_fields": interface_custom_fields if interface_custom_fields else None,
            }
            create_payload.update(vlan_payload_fields)
            # Remove None values from payload as pynetbox might not handle them well for all fields
            create_payload = {k:v for k,v in create_payload.items() if v is not None}
            try:
                nb_iface_obj = nb.virtualization.interfaces.create(**create_payload)
                if nb_iface_obj:
                    # After creating the interface, create/assign the MAC address object
                    mac_object = get_or_create_and_assign_netbox_mac_address(nb, p_mac, assign_to_interface_id=nb_iface_obj.id)
                    if mac_object:
                        try: nb_iface_obj.update({"primary_mac_address": mac_object.id})
                        except pynetbox.core.query.RequestError as e_prime: logger.error(f"Error setting primary MAC for new interface {nb_iface_obj.id}: {e_prime.error if hasattr(e_prime, 'error') else e_prime}")
            except pynetbox.core.query.RequestError as e:
                logger.error(f"Error creating interface '{p_name}' (MAC: {p_mac}): {e.error if hasattr(e, 'error') else e}")
                continue # Skip IP assignment if interface creation failed

        # Step 4: Assign IP address to the interface (whether it was found or newly created).
        if nb_iface_obj and p_ip_cidr:
            logger.info(f"Processing IP '{p_ip_cidr}' for interface '{nb_iface_obj.name}' (ID: {nb_iface_obj.id})")
            try:
                ip_address_obj = nb.ipam.ip_addresses.get(address=p_ip_cidr)
                if ip_address_obj:
                    # IP exists, check if it needs to be reassigned to this interface
                    if ip_address_obj.assigned_object_id != nb_iface_obj.id or \
                       ip_address_obj.assigned_object_type != NETBOX_OBJECT_TYPE_VMINTERFACE:
                        logger.info(f"IP address {p_ip_cidr} (ID: {ip_address_obj.id}) exists, reassigning to interface {nb_iface_obj.name}.")
                        ip_address_obj.update({
                            "assigned_object_type": NETBOX_OBJECT_TYPE_VMINTERFACE,
                            "assigned_object_id": nb_iface_obj.id,
                            "status": NETBOX_IPADDRESS_STATUS_ACTIVE
                        })
                    else:
                        logger.debug(f"IP address {p_ip_cidr} already assigned correctly to interface {nb_iface_obj.name}.")
                else:
                    # IP does not exist, create it and assign it
                    logger.info(f"Creating and assigning IP address {p_ip_cidr} to interface {nb_iface_obj.name}.")
                    nb.ipam.ip_addresses.create(
                        address=p_ip_cidr, status=NETBOX_IPADDRESS_STATUS_ACTIVE,
                        assigned_object_type=NETBOX_OBJECT_TYPE_VMINTERFACE,
                        assigned_object_id=nb_iface_obj.id
                    )
            except pynetbox.core.query.RequestError as e: 
                logger.error(f"NetBox API error processing IP {p_ip_cidr} for interface {nb_iface_obj.name}: {e.error if hasattr(e, 'error') else e}")
            except Exception as e: 
                logger.error(f"Unexpected error processing IP {p_ip_cidr} for interface {nb_iface_obj.name}: {e}", exc_info=True)

def sync_to_netbox(
    nb: pynetbox.api,
    vm_data_list: List[Dict[str, Any]],
    netbox_cluster_name_for_sync: str
):
    if not nb:
        logger.error("NetBox API client not available. Synchronization aborted.")
        return

    existing_netbox_vms = get_existing_vms(nb)
    
    # Ensure the cluster type exists or is created
    cluster_type_obj = get_or_create_cluster_type(nb, NETBOX_CLUSTER_TYPE_NAME)
    if not cluster_type_obj:
        logger.error(f"Could not get or create cluster type '{NETBOX_CLUSTER_TYPE_NAME}'. VMs cannot be assigned to a cluster.")
        # Decide if you want to proceed without cluster assignment or abort
        # For now, we'll try to get/create the cluster which will also fail if type is missing,
        # but this makes the dependency explicit.

    netbox_cluster = get_or_create_cluster(nb, netbox_cluster_name_for_sync, cluster_type_obj.id if cluster_type_obj else None)
    cluster_id = netbox_cluster.id if netbox_cluster else None
    if not cluster_id:
        logger.error(f"Cluster '{netbox_cluster_name_for_sync}' (type: {NETBOX_CLUSTER_TYPE_NAME}) not obtained/created. VMs will not be associated with a cluster.")
        # Depending on requirements, you might want to stop here or allow VMs to be created without a cluster.
        # For this implementation, we proceed but VMs won't be linked to a cluster.

    for vm_data in vm_data_list:
        name: str = vm_data["name"]
        # Convert memory from bytes (Proxmox) to MB (NetBox)
        ram_mb: Optional[int] = int(vm_data["maxmem"] // BYTES_IN_MB) if vm_data.get("maxmem") else None
        
        cpu_count: Optional[Union[float, int]] = vm_data.get("vcpus_count", 1)
        vcpus_int = int(float(cpu_count)) if cpu_count is not None else 1

        proxmox_disk_bytes = vm_data.get("maxdisk")
        disk_mb: Optional[int] = None
        if proxmox_disk_bytes is not None:
            try: disk_mb = int(float(proxmox_disk_bytes) // BYTES_IN_MB)
            except (TypeError, ValueError): logger.error(f"VM: {name}, error processing maxdisk value: {proxmox_disk_bytes}.")
        
        netbox_status: str = map_proxmox_status_to_netbox(vm_data.get("actual_status"))
        comments = vm_data.get("proxmox_description", "")

        # Process Proxmox tags for NetBox
        proxmox_tags_str = vm_data.get("proxmox_tags", "")
        netbox_tags_payload = []
        if proxmox_tags_str:
            tag_names = [tag.strip() for tag in proxmox_tags_str.split(';') if tag.strip()]
            netbox_tags_payload = get_or_create_netbox_tags(nb, tag_names)

        # Determine NetBox platform
        proxmox_ostype = vm_data.get("proxmox_ostype")
        platform_id: Optional[int] = None
        platform_name_for_netbox: Optional[str] = None

        # 1. Try to get platform name from Proxmox "Notes" (description field).
        # This takes precedence over proxmox_ostype.
        # Looks for a line starting with "os:" (case-insensitive).
        vm_comments_desc = vm_data.get("proxmox_description", "")
        if vm_comments_desc:
            for line in vm_comments_desc.splitlines():
                # Normalize the line for robust detection of the "os:" prefix
                # and extract the value with original capitalization.
                stripped_line_lower = line.strip().lower()
                if stripped_line_lower.startswith("os:"):
                    # Find the index of the start of the actual value after "os:"
                    value_start_index = line.lower().find("os:") + len("os:")
                    potential_os_name = line[value_start_index:].strip()
                    if potential_os_name:
                        platform_name_for_netbox = potential_os_name
                        logger.info(f"VM {name}: Plataforma definida pela descrição: '{platform_name_for_netbox}'")
                        break # Encontrado, parar de procurar
        
        # 2. If not found in description, use proxmox_ostype as fallback.
        if not platform_name_for_netbox and proxmox_ostype:
            platform_name_for_netbox = proxmox_ostype
            logger.info(f"VM {name}: Platform set by proxmox_ostype: '{platform_name_for_netbox}' (no override in description)")
        elif not platform_name_for_netbox:
            logger.info(f"VM {name}: No platform information found in description or proxmox_ostype.")

        if platform_name_for_netbox: # Use the determined name
            platform_id = get_or_create_netbox_platform(nb, platform_name_for_netbox)

        current_timestamp_iso = datetime.now(timezone.utc).isoformat()
        # Prepare custom fields payload. These custom fields must exist in NetBox.
        custom_fields_payload = {
            "vm_status": "Deployed", # Custom field to track sync status
            "vm_last_sync": current_timestamp_iso, # Custom field for last sync timestamp
            "vmid": vm_data.get("vmid"),
            "cpu_sockets": vm_data.get("proxmox_cpu_sockets"), 
            "min_memory_mb": vm_data.get("proxmox_min_memory_mb"), 
            "qemu_cpu_type": vm_data.get("proxmox_qemu_cpu_type"),
            "qemu_bios_type": vm_data.get("proxmox_qemu_bios_type"),
            "qemu_machine_type": vm_data.get("proxmox_qemu_machine_type"),
            "qemu_numa_enabled": vm_data.get("proxmox_qemu_numa_enabled"),
            "qemu_cores_per_socket": vm_data.get("proxmox_qemu_cores_per_socket"),
            "qemu_boot_order": vm_data.get("proxmox_qemu_boot_order"),
            "lxc_architecture": vm_data.get("proxmox_lxc_arch"),
            "lxc_unprivileged": vm_data.get("proxmox_lxc_unprivileged"),
            "lxc_features": vm_data.get("proxmox_lxc_features"),
        }
        # Get boot disk info from the disk list for custom fields
        boot_disk_info = next((d for d in vm_data.get("proxmox_virtual_disks", []) if d.get("is_boot_disk")), None)
        if boot_disk_info:
            custom_fields_payload["boot_disk_storage"] = boot_disk_info.get("storage_id")
            custom_fields_payload["boot_disk_format"] = boot_disk_info.get("format")
            if vm_data.get("type") == "lxc" and boot_disk_info.get("name") == "rootfs":
                 custom_fields_payload["lxc_rootfs_storage"] = boot_disk_info.get("storage_id")

        # Main payload for creating/updating the NetBox VM
        payload_for_netbox_vm = {
            "name": name, "status": netbox_status, "memory": ram_mb,
            "vcpus": vcpus_int, "disk": disk_mb, "cluster": cluster_id,
            "comments": comments,
            "tags": netbox_tags_payload if netbox_tags_payload else None,
            "platform": platform_id,
            "custom_fields": {k: v for k, v in custom_fields_payload.items() if v is not None}
        }
        # Remove None values from the main payload
        payload_for_netbox_vm = {k: v for k, v in payload_for_netbox_vm.items() if v is not None}

        synced_netbox_vm_object_for_children: Optional[Any] = None
        netbox_vm_obj = existing_netbox_vms.get(name)
        if netbox_vm_obj:
            # Basic change detection to see if an update is needed.
            # This can be made more sophisticated.
            has_changes = False
            current_serialized = netbox_vm_obj.serialize()
            for key, new_value in payload_for_netbox_vm.items():
                current_value = current_serialized.get(key)
                if key == "tags":
                    current_tag_ids = {t['id'] for t in (current_value or [])}
                    new_tag_ids = {t['id'] for t in (new_value or [])}
                    if current_tag_ids != new_tag_ids: has_changes = True; break
                elif key in ["cluster", "platform"] and isinstance(current_value, dict):
                    # For linked objects, compare IDs
                    if current_value.get('id') != new_value: has_changes = True; break
                elif key == "custom_fields":
                    if current_value != new_value : has_changes = True; break # Direct dictionary comparison
                elif str(current_value) != str(new_value): # General comparison
                    has_changes = True; break
            
            if not has_changes:
                logger.info(f"VM: {name}, no changes detected in the main VM object.")
                synced_netbox_vm_object_for_children = netbox_vm_obj
            else:
                logger.info(f"Updating existing VM: {name} (ID: {netbox_vm_obj.id})")
                try:
                    update_success = netbox_vm_obj.update(payload_for_netbox_vm)
                    if update_success:
                        synced_netbox_vm_object_for_children = netbox_vm_obj
                    else: # Update failed, but the VM object still exists
                        logger.error(f"VM: {name}, FAILED to update (update() returned False). Attempting to sync sub-components anyway.")
                        synced_netbox_vm_object_for_children = netbox_vm_obj
                except pynetbox.core.query.RequestError as e:
                    logger.error(f"Error updating VM {name}: {e.error if hasattr(e, 'error') else e}")
                    synced_netbox_vm_object_for_children = netbox_vm_obj # Try with the object as it was
                except Exception as e_unexpected:
                    logger.error(f"Unexpected error (update VM {name}): {e_unexpected}", exc_info=True)
                    synced_netbox_vm_object_for_children = netbox_vm_obj # Try with the object as it was
        else:
            logger.info(f"Criando nova VM: {name}")
            try:
                new_netbox_vm_obj = nb.virtualization.virtual_machines.create(payload_for_netbox_vm)
                if new_netbox_vm_obj:
                    logger.info(f"VM {name} criada com ID: {new_netbox_vm_obj.id}.")
                    synced_netbox_vm_object_for_children = new_netbox_vm_obj
                else:
                    logger.error(f"Failed to create VM {name}, pynetbox object not returned.")
            except pynetbox.core.query.RequestError as e:
                logger.error(f"Error creating VM {name}: {e.error if hasattr(e, 'error') else e}")

        # Synchronize interfaces and disks if we have a NetBox VM object
        if synced_netbox_vm_object_for_children:
            sync_vm_interfaces(nb, synced_netbox_vm_object_for_children, vm_data.get("proxmox_network_interfaces", []))
            sync_vm_virtual_disks(nb, synced_netbox_vm_object_for_children, vm_data.get("proxmox_virtual_disks", []))
        else:
            logger.warning(f"VM {name}: Could not obtain a NetBox VM object to synchronize interfaces/disks.")

def mark_orphaned_vms_as_deleted(
    nb: pynetbox.api,
    cluster_name: str,
    active_proxmox_vm_names: Set[str]
):
    """
    Marks NetBox VMs as 'Deleted' (via a custom field 'vm_status') if they exist in the specified
    NetBox cluster but are not present in the list of active Proxmox VMs.

    Args:
        nb: The pynetbox API client.
        cluster_name: The name of the NetBox cluster to check.
        active_proxmox_vm_names: A set of names of VMs currently active in Proxmox for this cluster.
    """
    if not nb: return
    logger.info(f"Checking for orphaned VMs in NetBox cluster '{cluster_name}'...")

    cluster_obj = nb.virtualization.clusters.get(name=cluster_name)
    if not cluster_obj:
        logger.error(f"Cluster '{cluster_name}' not found in NetBox. Cannot check for orphans.")
        return

    # Get all VMs in NetBox associated with this cluster
    netbox_vms_in_cluster = list(nb.virtualization.virtual_machines.filter(cluster_id=cluster_obj.id))
    if not netbox_vms_in_cluster:
        logger.info(f"No VMs found in NetBox for cluster '{cluster_name}'.")
        return

    current_timestamp_iso = datetime.now(timezone.utc).isoformat()
    orphaned_count = 0

    for nb_vm in netbox_vms_in_cluster:
        # If a NetBox VM is not in the active Proxmox list, it's considered orphaned.
        if nb_vm.name not in active_proxmox_vm_names:
            current_vm_status_cf = nb_vm.custom_fields.get("vm_status")
            if current_vm_status_cf != "Deleted":
                logger.info(f"VM '{nb_vm.name}' (ID: {nb_vm.id}) órfã. Marcando como 'Deleted'.")
                try:
                    nb_vm.update({
                        "custom_fields": {"vm_status": "Deleted", "vm_last_sync": current_timestamp_iso}
                    })
                    orphaned_count += 1
                except pynetbox.core.query.RequestError as e:
                    logger.error(f"Error marking VM '{nb_vm.name}' as 'Deleted': {e.error if hasattr(e, 'error') else e}")
    logger.info(f"Orphan check completed. {orphaned_count} VM(s) marked as 'Deleted'.")


def _map_proxmox_iface_type_to_netbox(proxmox_type: Optional[str], iface_name: str) -> str:
    """
    Maps Proxmox interface type string to a NetBox DCIM interface type.
    This is for physical/bridge/bond interfaces on the Proxmox node itself.
    """
    if not proxmox_type: return "other" # Default
    pt = proxmox_type.lower()
    if pt == "bridge": return "bridge"
    if pt == "bond": return "lag" # Link Aggregation Group
    if pt == "vlan": return "virtual" # Or could be the parent interface with tagging
    if pt == "eth": # Physical interface
        # Could be smarter here based on name (e.g., 'xgbe' -> 10gbase-t)
        # For now, a common type. This could be configurable in the future.
        return "1000base-t" 
    if pt == "loopback": return "virtual"
    # Add more mappings as needed (e.g., for Open vSwitch)
    logger.warning(f"Unmapped Proxmox interface type '{proxmox_type}' for interface '{iface_name}'. Using 'other'.")
    return "other"

def sync_node_interfaces_and_ips(
    nb: pynetbox.api,
    netbox_device_obj: Any, # pynetbox.core.response.Record
    proxmox_node_ifaces_data: List[Dict[str, Any]]
):
    """
    Synchronizes network interfaces (and their IPs) of a Proxmox node (represented as a NetBox Device)
    with data fetched from Proxmox.
    Creates, updates, or deletes interfaces on the NetBox Device.

    Args:
        nb: The pynetbox API client.
        netbox_device_obj: The NetBox Device record object representing the Proxmox node.
        proxmox_node_ifaces_data: A list of dictionaries, each representing a network interface from the Proxmox node.
    """
    if not nb or not netbox_device_obj: return
    device_name_log = netbox_device_obj.name
    logger.info(f"Sincronizando interfaces de rede para o Dispositivo NetBox: {device_name_log}")

    try:
        existing_nb_device_interfaces = list(nb.dcim.interfaces.filter(device_id=netbox_device_obj.id))
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Device {device_name_log}: Error fetching existing interfaces from NetBox: {e.error if hasattr(e, 'error') else e}")
        return
    
    netbox_ifaces_map = {iface.name: iface for iface in existing_nb_device_interfaces}
    processed_proxmox_iface_names = set() # To track which Proxmox interfaces were processed for orphan deletion

    for p_iface in proxmox_node_ifaces_data:
        p_name = p_iface.get("name")
        if not p_name:
            logger.warning(f"Device {device_name_log}: Proxmox interface without name, skipping. Data: {p_iface}")
            continue
        
        processed_proxmox_iface_names.add(p_name)
        p_mac = p_iface.get("mac_address")
        p_type_proxmox = p_iface.get("type_proxmox")
        p_active = p_iface.get("active", False)
        p_ip = p_iface.get("ip_address")
        p_netmask = p_iface.get("netmask")
        p_comments = p_iface.get("comments")
        p_slaves = p_iface.get("slaves")
        p_bridge_ports = p_iface.get("bridge_ports")

        netbox_iface_type = _map_proxmox_iface_type_to_netbox(p_type_proxmox, p_name)
        
        # Prepare custom fields for the device interface. These must exist in NetBox.
        iface_custom_fields = {
            "proxmox_interface_type": p_type_proxmox,
            "proxmox_interface_ports": p_slaves or p_bridge_ports
        }
        # Remove null custom fields
        iface_custom_fields = {k: v for k, v in iface_custom_fields.items() if v is not None}

        # Get or create the device interface in NetBox
        nb_iface_obj = get_or_create_device_interface(
            nb, netbox_device_obj.id, p_name, netbox_iface_type,
            mac_address=p_mac, enabled=p_active, description=p_comments,
            custom_fields=iface_custom_fields if iface_custom_fields else None
        )

        if nb_iface_obj and p_ip and p_netmask:
            # If interface exists/created and has IP details, process the IP
            try:
                # Use ipaddress module for robust IP/netmask handling and CIDR conversion
                ip_interface_obj = ipaddress.ip_interface(f"{p_ip}/{p_netmask}")
                
                # Check if the interface IP is a network or broadcast address, which are usually not assignable
                if ip_interface_obj.ip == ip_interface_obj.network.network_address:
                    logger.warning(f"Device {device_name_log}, Interface {p_name}: Configured IP '{p_ip}' is the network address. Will not be assigned in NetBox.")
                    continue # Skip this IP
                if ip_interface_obj.ip == ip_interface_obj.network.broadcast_address:
                    logger.warning(f"Device {device_name_log}, Interface {p_name}: Configured IP '{p_ip}' is the broadcast address. Will not be assigned in NetBox.")
                    continue # Skip this IP

                ip_cidr = str(ip_interface_obj.with_prefixlen) # Ensures correct CIDR format (IP/prefixlen)
                
                # Check if the IP address already exists in NetBox and is correctly assigned
                existing_ip_obj = nb.ipam.ip_addresses.get(address=ip_cidr)
                if existing_ip_obj:
                    # If IP exists but is not assigned to this interface, reassign it
                    if existing_ip_obj.assigned_object_id != nb_iface_obj.id or \
                       existing_ip_obj.assigned_object_type != NETBOX_OBJECT_TYPE_DCIM_INTERFACE:
                        logger.info(f"IP address {ip_cidr} (ID: {existing_ip_obj.id}) exists, reassigning to interface {p_name} of device {device_name_log}.")
                        existing_ip_obj.update({
                            "assigned_object_type": NETBOX_OBJECT_TYPE_DCIM_INTERFACE,
                            "assigned_object_id": nb_iface_obj.id,
                            "status": NETBOX_IPADDRESS_STATUS_ACTIVE
                        })
                    else:
                        logger.debug(f"IP address {ip_cidr} already correctly assigned to interface {p_name} of device {device_name_log}.")
                else:
                    # IP does not exist, create and assign it
                    logger.info(f"Creating/assigning IP address {ip_cidr} to interface {p_name} of device {device_name_log}.")
                    nb.ipam.ip_addresses.create(
                        address=ip_cidr, status=NETBOX_IPADDRESS_STATUS_ACTIVE,
                        assigned_object_type=NETBOX_OBJECT_TYPE_DCIM_INTERFACE,
                        assigned_object_id=nb_iface_obj.id
                    )
            except ValueError as e_ip:
                logger.error(f"Device {device_name_log}, Interface {p_name}: Invalid IP/Netmask '{p_ip}/{p_netmask}'. Error: {e_ip}")
            except pynetbox.core.query.RequestError as e_nb_ip:
                logger.error(f"Device {device_name_log}, Interface {p_name}: NetBox error processing IP {p_ip}: {e_nb_ip.error if hasattr(e_nb_ip, 'error') else e_nb_ip}")

    # Delete orphaned interfaces from NetBox (those that no longer exist in Proxmox)
    for iface_name_to_delete, nb_iface_to_delete in netbox_ifaces_map.items():
        if iface_name_to_delete not in processed_proxmox_iface_names:
            logger.info(f"Device {device_name_log}: Deleting orphaned interface '{iface_name_to_delete}' (ID: {nb_iface_to_delete.id}) from NetBox.")
            try: nb_iface_to_delete.delete()
            except pynetbox.core.query.RequestError as e: 
                logger.error(f"Error deleting orphaned interface '{iface_name_to_delete}': {e.error if hasattr(e, 'error') else e}")

def sync_proxmox_node_to_netbox_device(
    nb: pynetbox.api,
    node_config: Any, # ProxmoxNodeConfig
    node_details_from_proxmox: Dict[str, Any]
):
    """
    Synchronizes a Proxmox node to a NetBox Device.
    Creates or updates the Device in NetBox with details from Proxmox and the application's node configuration.

    Args:
        nb: The pynetbox API client.
        node_config: The ProxmoxNodeConfig object for the node being synced.
        node_details_from_proxmox: A dictionary of details fetched from the Proxmox node API.
    """
    if not nb: 
        logger.error("NetBox API client not available for sync_proxmox_node_to_netbox_device.")
        return
    if not node_details_from_proxmox: 
        logger.error("Proxmox node details not provided for sync_proxmox_node_to_netbox_device.")
        return

    node_name = node_details_from_proxmox.get("name")
    logger.info(f"Starting synchronization of Proxmox node '{node_name}' to NetBox Device.")

    # Step 1: Get or create necessary DCIM objects (Site, Manufacturer, Device Type, Role, Platform)
    # These are based on the user's configuration for this Proxmox node in the application settings.
    site = get_or_create_site(nb, node_config.netbox_node_site_name) if node_config.netbox_node_site_name else None
    manu = get_or_create_manufacturer(nb, node_config.netbox_node_manufacturer_name) if node_config.netbox_node_manufacturer_name else None
    dev_type = get_or_create_device_type(nb, node_config.netbox_node_device_type_name, manu.id if manu else None) if node_config.netbox_node_device_type_name else None
    dev_role = get_or_create_device_role(nb, node_config.netbox_node_device_role_name) if node_config.netbox_node_device_role_name else None
    
    pve_version_str = node_details_from_proxmox.get("pve_version")
    platform_name_to_use = node_config.netbox_node_platform_name or (f"Proxmox VE {pve_version_str}" if pve_version_str else None)
    platform = get_or_create_netbox_platform(nb, platform_name_to_use) if platform_name_to_use else None

    # Step 2: Prepare custom fields payload for the NetBox Device. These must exist in NetBox.
    custom_fields = {
        "proxmox_pve_version": pve_version_str,
        "proxmox_cpu_model": node_details_from_proxmox.get("cpu_model"),
        "proxmox_cpu_sockets": node_details_from_proxmox.get("cpu_sockets"),
        "proxmox_cpu_cores_total": node_details_from_proxmox.get("cpu_cores_total"),
        "proxmox_memory_total_gb": int(node_details_from_proxmox.get("memory_total_bytes", 0) / BYTES_IN_GB),
        "proxmox_rootfs_total_gb": int(node_details_from_proxmox.get("rootfs_total_bytes", 0) / BYTES_IN_GB),
        "proxmox_node_last_sync": datetime.now(timezone.utc).isoformat()
    }
    # Remove None values from custom fields
    custom_fields = {k:v for k,v in custom_fields.items() if v is not None}

    # Step 3: Prepare main payload for the NetBox Device
    device_payload = {
        "name": node_name,
        "role": dev_role.id if dev_role else None, # Corrected key to 'role' (pynetbox handles object or ID)
        "device_type": dev_type.id if dev_type else None,
        "site": site.id if site else None,
        "platform": platform.id if platform else None, # platform from get_or_create is the object, use .id
        "status": "active", # Assuming the node is active if we can fetch details
        "custom_fields": custom_fields
    }
    # Remove None values from the main payload
    device_payload = {k:v for k,v in device_payload.items() if v is not None}

    # Step 4: Get, create, or update the NetBox Device
    netbox_device_obj = nb.dcim.devices.get(name=node_name)
    if netbox_device_obj:
        logger.info(f"Atualizando Dispositivo NetBox existente: {node_name} (ID: {netbox_device_obj.id})")
        try: 
            if not netbox_device_obj.update(device_payload):
                logger.warning(f"NetBox Device '{node_name}' update call returned False. Check NetBox logs for details.")
        except pynetbox.core.query.RequestError as e: 
            logger.error(f"Error updating NetBox Device '{node_name}': {e.error if hasattr(e, 'error') else e}")
    else:
        logger.info(f"Criando novo Dispositivo NetBox: {node_name}")
        try: netbox_device_obj = nb.dcim.devices.create(**device_payload)
        except pynetbox.core.query.RequestError as e: 
            logger.error(f"Error creating NetBox Device '{node_name}': {e.error if hasattr(e, 'error') else e}")

    # Step 5: Synchronize Node Interfaces and IPs
    if netbox_device_obj:
        proxmox_ifaces = node_details_from_proxmox.get("network_interfaces", [])
        sync_node_interfaces_and_ips(nb, netbox_device_obj, proxmox_ifaces)
    else:
        logger.warning(f"Could not get/create NetBox Device for '{node_name}'. Interfaces will not be synchronized.")
    logger.info(f"Synchronization of Proxmox node '{node_name}' to NetBox Device completed.")