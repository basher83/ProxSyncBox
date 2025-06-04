import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Union, Tuple
import ipaddress  # For IP address and network manipulation
from collections import Counter # Import Counter for potential future use or debugging
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
from config_models import GlobalSettings, ProxmoxNodeConfig # Import models for type hinting # type: ignore

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
            try: nb.virtualization.virtual_disks.create(**disk_payload) # "Creating new virtual disk"
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
    Synchronizes network interfaces of a NetBox VM with data from Proxmox. # type: ignore
    Creates, updates interfaces, assigns MACs, VLANs, and IP addresses.

    Args:
        nb: The pynetbox API client.
        netbox_vm_obj: The NetBox VM record object.
        proxmox_ifaces_data: A list of dictionaries, each representing a network interface from Proxmox.
    """
    if not nb or not netbox_vm_obj: return
    logger.info(f"Synchronizing interfaces for VM: {netbox_vm_obj.name}")

    for p_iface_data in proxmox_ifaces_data: # Iterate through Proxmox VM interfaces
        p_name = p_iface_data.get("name", "net_unnamed")
        p_mac = p_iface_data.get("mac_address")
        p_ip_cidr = p_iface_data.get("ip_cidr")
        p_bridge = p_iface_data.get("bridge")
        p_model = p_iface_data.get("model")
        p_vlan_tag = p_iface_data.get("vlan_tag")

        if not p_mac:
            logger.warning(f"VM {netbox_vm_obj.name}, Interface '{p_name}': Skipping interface (no MAC address found in Proxmox data).")
            continue
        
        # Prepare custom fields for the interface
        interface_custom_fields = {}
        # These custom field names ('bridge', 'interface_model') must exist in your NetBox setup.
        if p_bridge: interface_custom_fields["bridge"] = p_bridge
        if p_model: interface_custom_fields["interface_model"] = p_model
        
        netbox_vlan_id: Optional[int] = None
        nb_iface_obj: Optional[pynetbox.core.response.Record] = None
        mac_object_for_primary_link: Optional[pynetbox.core.response.Record] = None # Initialize


        # Step 2: Try to find an existing NetBox interface by name for the current VM.
        # (Finding by MAC string on interface directly is less reliable than using MACAddress objects)
        existing_by_name = list(nb.virtualization.interfaces.filter(virtual_machine_id=netbox_vm_obj.id, name=p_name))
        if existing_by_name: # Corrected condition to use existing_by_name
            nb_iface_obj = existing_by_name[0]
            logger.info(f"VM {netbox_vm_obj.name}: Interface found by name '{p_name}': (ID: {nb_iface_obj.id})")

            if p_mac: # Only if Proxmox provides a MAC
                mac_object_for_primary_link = get_or_create_and_assign_netbox_mac_address(
                    nb, p_mac,
                    assign_to_interface_id=nb_iface_obj.id, # Pass existing interface ID
                    assigned_object_type=NETBOX_OBJECT_TYPE_VMINTERFACE
                )
                if not mac_object_for_primary_link:
                    logger.error(f"VM {netbox_vm_obj.name}, Interface '{p_name}': Failed to get/create MACAddress object for {p_mac} for existing interface. MAC will not be updated/linked.")
            else: # Proxmox does not provide a MAC for this interface
                mac_object_for_primary_link = None
                logger.warning(f"VM {netbox_vm_obj.name}, Interface '{p_name}': No MAC address from Proxmox. Will attempt to clear primary_mac_address if set.")

            # Prepare payload for potential update
            iface_update_payload = {}
            if nb_iface_obj.name != p_name: iface_update_payload["name"] = p_name
            if not nb_iface_obj.enabled: iface_update_payload["enabled"] = True # Assuming we want synced interfaces to be enabled
            
            current_cf = nb_iface_obj.custom_fields or {}
            if interface_custom_fields != current_cf:
                 iface_update_payload["custom_fields"] = interface_custom_fields
            
            vlan_payload_for_iface_update = {}
            if p_vlan_tag:
                netbox_vlan_id = get_or_create_netbox_vlan(nb, p_vlan_tag)
                if netbox_vlan_id:
                    current_mode_val = getattr(nb_iface_obj.mode, 'value', None) if nb_iface_obj.mode else None
                    current_untagged_vlan_id = getattr(nb_iface_obj.untagged_vlan, 'id', None) if nb_iface_obj.untagged_vlan else None
                    if current_mode_val != "access" or current_untagged_vlan_id != netbox_vlan_id:
                        vlan_payload_for_iface_update = {"mode": "access", "untagged_vlan": netbox_vlan_id}
            else: # No VLAN tag from Proxmox, clear VLAN settings on NetBox interface if they exist
                if nb_iface_obj.untagged_vlan or (nb_iface_obj.mode and nb_iface_obj.mode.value == "access"):
                    vlan_payload_for_iface_update = {"untagged_vlan": None, "mode": None}
            if vlan_payload_for_iface_update:
                iface_update_payload.update(vlan_payload_for_iface_update)

            # Ensure the correct MACAddress object is linked as primary
            current_primary_mac_id = getattr(nb_iface_obj.primary_mac_address, 'id', None) if nb_iface_obj.primary_mac_address else None
            desired_primary_mac_id = mac_object_for_primary_link.id if mac_object_for_primary_link else None
            if current_primary_mac_id != desired_primary_mac_id:
                iface_update_payload["primary_mac_address"] = desired_primary_mac_id
            
            if iface_update_payload:
                logger.info(f"VM {netbox_vm_obj.name}: Updating interface '{p_name}' (ID: {nb_iface_obj.id}). Payload: {iface_update_payload}")
                try: nb_iface_obj.update(iface_update_payload)
                except pynetbox.core.query.RequestError as e: logger.error(f"VM {netbox_vm_obj.name}: Error updating interface ID {nb_iface_obj.id}: {e.error if hasattr(e, 'error') else e}")
            else:
                logger.debug(f"VM {netbox_vm_obj.name}: Interface '{p_name}' (ID: {nb_iface_obj.id}) no changes needed for main fields. Verifying primary MAC link.")
                # The primary_mac_address link is handled by the main iface_update_payload now.
        else: # Interface not found by name, create a new one.
            logger.info(f"VM {netbox_vm_obj.name}: Creating new interface '{p_name}' (MAC: {p_mac})")
            
            # Prepare payload for new interface creation WITHOUT primary_mac_address initially
            create_payload = {
                "virtual_machine": netbox_vm_obj.id, "name": p_name,
                "enabled": True,
                "type": NETBOX_INTERFACE_TYPE_VIRTUAL,
                "custom_fields": interface_custom_fields if interface_custom_fields else None,
            }
            vlan_payload_for_iface_create = {}
            if p_vlan_tag:
                netbox_vlan_id = get_or_create_netbox_vlan(nb, p_vlan_tag)
                if netbox_vlan_id: vlan_payload_for_iface_create = {"mode": "access", "untagged_vlan": netbox_vlan_id}
            if vlan_payload_for_iface_create:
                create_payload.update(vlan_payload_for_iface_create)

            # Remove None values from payload as pynetbox might not handle them well for all fields
            create_payload = {k:v for k,v in create_payload.items() if v is not None}
            try:
                nb_iface_obj = nb.virtualization.interfaces.create(**create_payload)
                if nb_iface_obj and p_mac: # If interface created and we have a MAC
                    logger.info(f"VM {netbox_vm_obj.name}, Interface '{p_name}' (ID: {nb_iface_obj.id}) created. Now processing MAC {p_mac}.")
                    # Now, get/create and assign the MACAddress object to this newly created interface
                    mac_object_for_primary_link = get_or_create_and_assign_netbox_mac_address(
                        nb, p_mac,
                        assign_to_interface_id=nb_iface_obj.id, # Pass the new interface ID
                        assigned_object_type=NETBOX_OBJECT_TYPE_VMINTERFACE
                    )
                    if mac_object_for_primary_link:
                        # Now link this MAC object to the interface's primary_mac_address field
                        logger.info(f"VM {netbox_vm_obj.name}, Interface '{p_name}': Linking MAC object ID {mac_object_for_primary_link.id} as primary_mac_address.")
                        try:
                            nb_iface_obj.update({"primary_mac_address": mac_object_for_primary_link.id})
                        except pynetbox.core.query.RequestError as e_link_mac:
                            logger.error(f"VM {netbox_vm_obj.name}: Error linking primary MAC for interface '{p_name}': {e_link_mac.error if hasattr(e_link_mac, 'error') else e_link_mac}")
                    else:
                        logger.warning(f"VM {netbox_vm_obj.name}, Interface '{p_name}': Could not get/create/assign MAC object for {p_mac} after interface creation.")
                elif not nb_iface_obj:
                    logger.error(f"VM {netbox_vm_obj.name}: Failed to create interface '{p_name}', pynetbox object not returned.")
                    continue # Skip IP assignment if interface creation failed

            except pynetbox.core.query.RequestError as e: # Error during interface creation
                logger.error(f"VM {netbox_vm_obj.name}: Error creating interface '{p_name}' (MAC: {p_mac}): {e.error if hasattr(e, 'error') else e}")
                continue # Skip IP assignment if interface creation failed

        # Step 3: Assign IP address to the interface (whether it was found or newly created).
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
                logger.error(f"VM {netbox_vm_obj.name}, Interface {nb_iface_obj.name}: NetBox API error processing IP {p_ip_cidr}: {e.error if hasattr(e, 'error') else e}")
            except Exception as e: 
                logger.error(f"Unexpected error processing IP {p_ip_cidr} for interface {nb_iface_obj.name}: {e}", exc_info=True)

def sync_to_netbox(
    nb: pynetbox.api,
    vm_data_list: List[Dict[str, Any]],
    netbox_cluster_name_for_sync: str,
    global_settings: GlobalSettings # Add global_settings parameter
):
    if not nb:
        logger.error("NetBox API client not available. Synchronization aborted.")
        return

    existing_netbox_vms = get_existing_vms(nb)
    
    # Ensure the cluster type exists or is created
    cluster_type_obj = get_or_create_cluster_type(nb, global_settings.netbox_cluster_type_name)
    if not cluster_type_obj:
        logger.error(f"Could not get or create cluster type '{global_settings.netbox_cluster_type_name}'. VMs cannot be assigned to a cluster.")
        # Decide if you want to proceed without cluster assignment or abort
        # For now, we'll try to get/create the cluster which will also fail if type is missing,
        # but this makes the dependency explicit.

    netbox_cluster = get_or_create_cluster(nb, netbox_cluster_name_for_sync, global_settings.netbox_cluster_type_name) # Pass name directly

    # Build a map of existing NetBox VMs in the target cluster (or globally if no cluster) by name and vmid
    # existing_nb_vms_in_scope_by_name_and_vmid: {netbox_name: {netbox_vmid_cf: nb_vm_obj}}
    existing_nb_vms_in_scope_by_name_and_vmid: Dict[str, Dict[Optional[int], Any]] = {} # {name: {vmid: nb_vm_obj}}
    existing_netbox_vms_by_vmid_cf_in_scope: Dict[int, Any] = {} # {netbox_vmid_cf: nb_vm_obj}

    for nb_vm in existing_netbox_vms.values():
        is_in_scope = False
        # Check if the NetBox VM is in the target cluster (if a cluster is defined for sync)
        if netbox_cluster is not None:
            if hasattr(nb_vm, 'cluster') and nb_vm.cluster and nb_vm.cluster.id == netbox_cluster.id:
                 is_in_scope = True
        else:
            # If no target cluster is defined for sync, all existing VMs are in scope for global uniqueness check
            is_in_scope = True

        if is_in_scope:
            nb_vm_name = nb_vm.name
            # Get vmid from custom fields, handle potential None or missing field
            nb_vm_vmid_cf = nb_vm.custom_fields.get("vmid")
            nb_vm_vmid: Optional[int] = None
            if isinstance(nb_vm_vmid_cf, (int, float)):
                 nb_vm_vmid = int(nb_vm_vmid_cf)
            elif isinstance(nb_vm_vmid_cf, str) and nb_vm_vmid_cf.isdigit():
                 nb_vm_vmid = int(nb_vm_vmid_cf)

            if nb_vm_name not in existing_nb_vms_in_scope_by_name_and_vmid:
                existing_nb_vms_in_scope_by_name_and_vmid[nb_vm_name] = {}
            # This line is crucial to actually store the VM object by its vmid for conflict checking
            existing_nb_vms_in_scope_by_name_and_vmid[nb_vm_name][nb_vm_vmid] = nb_vm # type: ignore

            if nb_vm_vmid is not None:
                if nb_vm_vmid in existing_netbox_vms_by_vmid_cf_in_scope:
                    logger.warning(
                        f"NetBox data integrity issue: Multiple VMs in scope found with the same vmid custom field value '{nb_vm_vmid}'. "
                        f"VM1: '{nb_vm.name}' (ID: {nb_vm.id}), "
                        f"VM2: '{existing_netbox_vms_by_vmid_cf_in_scope[nb_vm_vmid].name}' (ID: {existing_netbox_vms_by_vmid_cf_in_scope[nb_vm_vmid].id}). "
                        "Using the last one encountered for VMID-based matching for this vmid.")
                existing_netbox_vms_by_vmid_cf_in_scope[nb_vm_vmid] = nb_vm
    cluster_id = netbox_cluster.id if netbox_cluster else None
    if not cluster_id:
        logger.error(f"Cluster '{netbox_cluster_name_for_sync}' (type: {global_settings.netbox_cluster_type_name}) not obtained/created. VMs will not be associated with a cluster.")
        # Depending on requirements, you might want to stop here or allow VMs to be created without a cluster.
        # For this implementation, we proceed but VMs won't be linked to a cluster.

    # --- Initialize counters for sync summary ---
    total_processed_vms = 0
    successfully_synced_vms = 0
    vms_with_warnings = set()
    vms_with_errors = set()
    # --- End of counter initialization ---

    for vm_data in vm_data_list:
        total_processed_vms += 1
        proxmox_name: str = vm_data["name"]
        proxmox_vmid: int = vm_data["vmid"]

        netbox_vm_to_update = existing_netbox_vms_by_vmid_cf_in_scope.get(proxmox_vmid)
        operation_is_update = bool(netbox_vm_to_update)

        # final_target_name_for_netbox_payload is the name that will be used in the NetBox create/update payload.
        # It starts as the current Proxmox name.
        final_target_name_for_netbox_payload = proxmox_name

        # Check if the Proxmox name (proxmox_name) is already used in NetBox by a *different* VMID.
        is_proxmox_name_taken_by_other_vmid = False
        if proxmox_name in existing_nb_vms_in_scope_by_name_and_vmid:
            for nb_vmid_key_conflict, _ in existing_nb_vms_in_scope_by_name_and_vmid[proxmox_name].items():
                if nb_vmid_key_conflict != proxmox_vmid: # Name is taken by a VM with a different vmid (or no vmid)
                    is_proxmox_name_taken_by_other_vmid = True
                    break
        
        if is_proxmox_name_taken_by_other_vmid:
            # The current Proxmox VM must use an appended name in NetBox.
            final_target_name_for_netbox_payload = f"{proxmox_name} ({proxmox_vmid})"
            logger.info(f"Proxmox VM '{proxmox_name}' (vmid {proxmox_vmid}): Will use name '{final_target_name_for_netbox_payload}' in NetBox because base name '{proxmox_name}' is used by another VM.")

            # Now, rename the *other* NetBox VMs that are currently using the simple 'proxmox_name'.
            if proxmox_name in existing_nb_vms_in_scope_by_name_and_vmid:
                vms_to_rename_in_netbox = []
                for other_vmid_cf, conflicting_nb_vm_object_loop in existing_nb_vms_in_scope_by_name_and_vmid[proxmox_name].items():
                    # Condition: other VM's vmid_cf is different AND its current NetBox name is the simple proxmox_name
                    if other_vmid_cf != proxmox_vmid and conflicting_nb_vm_object_loop.name == proxmox_name:
                        vms_to_rename_in_netbox.append(conflicting_nb_vm_object_loop)
                
                for conflicting_nb_vm_object in vms_to_rename_in_netbox:
                    other_nb_vmid_val = conflicting_nb_vm_object.custom_fields.get('vmid')
                    if other_nb_vmid_val is None:
                        logger.warning(f"Skipping rename for existing NetBox VM '{conflicting_nb_vm_object.name}' (ID: {conflicting_nb_vm_object.id}) as its VMID custom field is missing.")
                        continue

                    new_name_for_other_vm = f"{proxmox_name} ({other_nb_vmid_val})"
                    logger.info(f"Renaming conflicting NetBox VM '{conflicting_nb_vm_object.name}' (ID: {conflicting_nb_vm_object.id}, VMID CF: {other_nb_vmid_val}) to '{new_name_for_other_vm}'.")
                    try:
                        if conflicting_nb_vm_object.update({"name": new_name_for_other_vm}):
                            # Update local caches to reflect the rename
                            old_name_of_conflicting_vm = conflicting_nb_vm_object.name # Should be proxmox_name
                            conflicting_nb_vm_object.name = new_name_for_other_vm # Update in-memory object

                            if old_name_of_conflicting_vm in existing_netbox_vms and existing_netbox_vms[old_name_of_conflicting_vm].id == conflicting_nb_vm_object.id:
                                del existing_netbox_vms[old_name_of_conflicting_vm]
                            existing_netbox_vms[new_name_for_other_vm] = conflicting_nb_vm_object

                            if old_name_of_conflicting_vm in existing_nb_vms_in_scope_by_name_and_vmid and other_nb_vmid_val in existing_nb_vms_in_scope_by_name_and_vmid[old_name_of_conflicting_vm]:
                                del existing_nb_vms_in_scope_by_name_and_vmid[old_name_of_conflicting_vm][other_nb_vmid_val]
                                if not existing_nb_vms_in_scope_by_name_and_vmid[old_name_of_conflicting_vm]:
                                    del existing_nb_vms_in_scope_by_name_and_vmid[old_name_of_conflicting_vm]
                            if new_name_for_other_vm not in existing_nb_vms_in_scope_by_name_and_vmid:
                                existing_nb_vms_in_scope_by_name_and_vmid[new_name_for_other_vm] = {}
                            existing_nb_vms_in_scope_by_name_and_vmid[new_name_for_other_vm][other_nb_vmid_val] = conflicting_nb_vm_object
                        else:
                            logger.error(f"Failed to rename conflicting NetBox VM '{conflicting_nb_vm_object.name}' (ID: {conflicting_nb_vm_object.id}) via API (update returned False).")
                    except pynetbox.core.query.RequestError as e_rename:
                        logger.error(f"Error renaming conflicting NetBox VM '{conflicting_nb_vm_object.name}' (ID: {conflicting_nb_vm_object.id}): {e_rename.error if hasattr(e_rename, 'error') else e_rename}")
        else:
            logger.debug(f"Proxmox VM '{proxmox_name}' (vmid {proxmox_vmid}): Base name '{proxmox_name}' is not taken by other VMs, or this is the only VM with this name. Target NetBox name will be '{final_target_name_for_netbox_payload}'.")

        # Convert memory from bytes (Proxmox) to MB (NetBox)
        ram_mb: Optional[int] = int(vm_data["maxmem"] // BYTES_IN_MB) if vm_data.get("maxmem") else None
        
        cpu_count_from_data: Optional[Union[float, int]] = vm_data.get("vcpus_count") # Use a different variable name
        vcpus_int = int(float(cpu_count_from_data)) if cpu_count_from_data is not None else 1

        # Calculate total disk size from individual virtual disks to ensure consistency with NetBox
        individual_disks_data = vm_data.get("proxmox_virtual_disks", [])
        calculated_disk_mb_sum = 0
        has_any_valid_individual_disk = False

        if individual_disks_data:
            for disk_item in individual_disks_data:
                size_val = disk_item.get("size_mb")
                # Ensure size_val is a positive number before adding
                if isinstance(size_val, (int, float)) and size_val > 0:
                    calculated_disk_mb_sum += int(size_val)
                    has_any_valid_individual_disk = True
        
        disk_mb: Optional[int] = None
        if individual_disks_data:
            disk_mb = calculated_disk_mb_sum # Use the sum, even if it's 0
            if not has_any_valid_individual_disk and calculated_disk_mb_sum == 0:
                 logger.warning(f"VM {final_target_name_for_netbox_payload}: Contained disk entries, but none had a valid positive size. Sum is 0. NetBox VM 'disk' field set to 0MB.")
                 vms_with_warnings.add(final_target_name_for_netbox_payload)
        else:
            disk_mb = None # Omit 'disk' field for the VM in NetBox if no individual disks
            logger.info(f"VM {final_target_name_for_netbox_payload}: No 'proxmox_virtual_disks' data. NetBox VM 'disk' field will be omitted.")
        
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
                    potential_os_name = line[value_start_index:].strip() # type: ignore
                    if potential_os_name:
                        platform_name_for_netbox = potential_os_name
                        logger.info(f"VM {final_target_name_for_netbox_payload}: Platform defined by description: '{platform_name_for_netbox}'")
                        break # Encontrado, parar de procurar

        # 2. If not found in description, use proxmox_ostype as fallback.
        if not platform_name_for_netbox and proxmox_ostype:
            platform_name_for_netbox = proxmox_ostype # type: ignore
            logger.info(f"VM {final_target_name_for_netbox_payload}: Platform set by proxmox_ostype: '{platform_name_for_netbox}' (no override in description)")
        elif not platform_name_for_netbox:
            logger.info(f"VM {proxmox_name}: No platform information found in description or proxmox_ostype.")

        if platform_name_for_netbox: # Use the determined name
            platform_id = get_or_create_netbox_platform(nb, platform_name_for_netbox)

        current_timestamp_iso = datetime.now(timezone.utc).isoformat()
        # Prepare custom fields payload. These custom fields must exist in NetBox. # type: ignore
        custom_fields_payload = {
            # Always include vmid for identification
            "vmid": proxmox_vmid,
            # Other custom fields
            "vm_status": "Deployed", # Custom field to track sync status
            "vm_last_sync": current_timestamp_iso, # Custom field for last sync timestamp
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

        # The duplicated block for custom_fields_payload and an initial payload_for_netbox_vm
        # has been removed. The custom_fields_payload above is correct.

        # Main payload for creating/updating the NetBox VM
        payload_for_netbox_vm = {
            "name": final_target_name_for_netbox_payload,
            "status": netbox_status, "memory": ram_mb,
            "vcpus": vcpus_int, "disk": disk_mb, "cluster": cluster_id,
            "comments": comments,
            "tags": netbox_tags_payload if netbox_tags_payload else None,
            "platform": platform_id,
            "custom_fields": {k: v for k, v in custom_fields_payload.items() if v is not None}
        }
        # Remove None values from the main payload
        payload_for_netbox_vm = {k: v for k, v in payload_for_netbox_vm.items() if v is not None}

        synced_netbox_vm_object_for_children: Optional[Any] = None
        if operation_is_update and netbox_vm_to_update: # Should always be true if operation_is_update
            logger.debug(f"VM {final_target_name_for_netbox_payload} (Proxmox VMID {proxmox_vmid}): Matched existing NetBox VM '{netbox_vm_to_update.name}' (ID: {netbox_vm_to_update.id}).")
            logger.debug(f"Current NetBox VM status CF: {netbox_vm_to_update.custom_fields.get('vm_status')}")
            logger.debug(f"Desired NetBox VM status CF from payload: {payload_for_netbox_vm.get('custom_fields', {}).get('vm_status')}")

            has_changes = False

            # Check if the NetBox VM is marked as "Deleted" and should be "Deployed"
            current_nb_vm_status_cf = netbox_vm_to_update.custom_fields.get("vm_status")
            # The payload_for_netbox_vm is already prepared with the desired state, including "Deployed"
            desired_vm_status_cf = payload_for_netbox_vm.get("custom_fields", {}).get("vm_status")
            if current_nb_vm_status_cf == "Deleted" and desired_vm_status_cf == "Deployed":
                logger.info(f"VM {final_target_name_for_netbox_payload} (NetBox ID: {netbox_vm_to_update.id}): Correcting status from 'Deleted' to 'Deployed' in NetBox.")
                has_changes = True # Ensure an update is triggered for this specific correction

            # Basic change detection to see if an update is needed.
            # If not already flagged for update by the status correction, perform general change detection.
            # Only perform general check if 'has_changes' is not already True from status correction
            if not has_changes: # Check if status correction already flagged changes
                 current_serialized = netbox_vm_to_update.serialize()
                 # Compare relevant fields from the payload with the serialized NetBox object
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
                     elif str(current_value) != str(new_value): # General comparison (handles None vs "")
                         has_changes = True; break
            
            if not has_changes:
                logger.info(f"VM {final_target_name_for_netbox_payload}: No changes detected in the main VM object (NetBox ID: {netbox_vm_to_update.id}).")
                synced_netbox_vm_object_for_children = netbox_vm_to_update
                successfully_synced_vms +=1
            else:
                logger.info(f"Updating existing VM: {final_target_name_for_netbox_payload} (NetBox ID: {netbox_vm_to_update.id})")
                try:
                    update_success = netbox_vm_to_update.update(payload_for_netbox_vm)
                    if update_success:
                        synced_netbox_vm_object_for_children = netbox_vm_to_update
                        successfully_synced_vms +=1
                    else: # Update failed, but the VM object still exists
                        logger.error(f"VM {final_target_name_for_netbox_payload}: FAILED to update (update() returned False). Attempting to sync sub-components anyway.")
                        vms_with_errors.add(final_target_name_for_netbox_payload)
                        synced_netbox_vm_object_for_children = netbox_vm_to_update
                except pynetbox.core.query.RequestError as e:
                    logger.error(f"Error updating VM {final_target_name_for_netbox_payload}: {e.error if hasattr(e, 'error') else e}") # type: ignore
                    vms_with_errors.add(final_target_name_for_netbox_payload)
                    synced_netbox_vm_object_for_children = netbox_vm_to_update # Try with the object as it was
                except Exception as e_unexpected: # type: ignore
                    logger.error(f"Unexpected error (update VM {final_target_name_for_netbox_payload}): {e_unexpected}", exc_info=True) # type: ignore
                    vms_with_errors.add(final_target_name_for_netbox_payload)
                    synced_netbox_vm_object_for_children = netbox_vm_to_update # Try with the object as it was
        else: # Create new VM
            logger.info(f"Creating new VM in NetBox with name: {final_target_name_for_netbox_payload} (Proxmox VMID {proxmox_vmid})")
            try:
                new_netbox_vm_obj = nb.virtualization.virtual_machines.create(payload_for_netbox_vm)
                if new_netbox_vm_obj:
                    logger.info(f"VM {final_target_name_for_netbox_payload} created with ID: {new_netbox_vm_obj.id}.")
                    synced_netbox_vm_object_for_children = new_netbox_vm_obj
                    successfully_synced_vms +=1
                    # Add the newly created VM to our local caches so it can be found by subsequent operations if needed
                    existing_netbox_vms[new_netbox_vm_obj.name] = new_netbox_vm_obj
                    if new_netbox_vm_obj.name not in existing_nb_vms_in_scope_by_name_and_vmid:
                        existing_nb_vms_in_scope_by_name_and_vmid[new_netbox_vm_obj.name] = {}
                    existing_nb_vms_in_scope_by_name_and_vmid[new_netbox_vm_obj.name][proxmox_vmid] = new_netbox_vm_obj
                    existing_netbox_vms_by_vmid_cf_in_scope[proxmox_vmid] = new_netbox_vm_obj
                else:
                    logger.error(f"Failed to create VM {final_target_name_for_netbox_payload}, pynetbox object not returned.")
                    vms_with_errors.add(final_target_name_for_netbox_payload)
            except pynetbox.core.query.RequestError as e:
                logger.error(f"Error creating VM {final_target_name_for_netbox_payload}: {e.error if hasattr(e, 'error') else e}") # type: ignore
                vms_with_errors.add(final_target_name_for_netbox_payload)

        # Synchronize interfaces and disks if we have a NetBox VM object
        if synced_netbox_vm_object_for_children:
            sync_vm_interfaces(nb, synced_netbox_vm_object_for_children, vm_data.get("proxmox_network_interfaces", []))
            sync_vm_virtual_disks(nb, synced_netbox_vm_object_for_children, vm_data.get("proxmox_virtual_disks", []))
        else:
            logger.warning(f"VM {final_target_name_for_netbox_payload}: Could not obtain a NetBox VM object to synchronize interfaces/disks.")
            vms_with_warnings.add(final_target_name_for_netbox_payload) # This is a warning because the main VM object might have failed

    return total_processed_vms, successfully_synced_vms, len(vms_with_warnings), len(vms_with_errors)

def mark_orphaned_vms_as_deleted(
    nb: pynetbox.api,
    cluster_name: str,
    active_proxmox_vm_identities: Set[Tuple[str, int]] # Set of (name, vmid)
):
    """
    Marks NetBox VMs as 'Deleted' (via a custom field 'vm_status') if they exist in the specified
    NetBox cluster but are not present in the list of active Proxmox VMs.

    Args:
        nb: The pynetbox API client.
        cluster_name: The name of the NetBox cluster to check.
        active_proxmox_vm_identities: A set of (name, vmid) tuples for VMs currently active in Proxmox.
    """
    if not nb: return
    logger.info(f"Checking for orphaned VMs in NetBox cluster '{cluster_name}'...")
    logger.debug(f"Active Proxmox VM identities provided for orphan check: {active_proxmox_vm_identities}")
    orphans_marked_count = 0
    orphan_errors_count = 0

    cluster_obj = nb.virtualization.clusters.get(name=cluster_name)
    if not cluster_obj:
        logger.error(f"Cluster '{cluster_name}' not found in NetBox. Cannot check for orphans.")
        return

    # Get all VMs in NetBox associated with this cluster
    netbox_vms_in_cluster = list(nb.virtualization.virtual_machines.filter(cluster_id=cluster_obj.id))
    if not netbox_vms_in_cluster:
        logger.info(f"No VMs found in NetBox for cluster '{cluster_name}'.")
        return orphans_marked_count, orphan_errors_count

    current_timestamp_iso = datetime.now(timezone.utc).isoformat()

    for nb_vm in netbox_vms_in_cluster:
        is_orphaned = True # Assume orphaned until proven otherwise
        nb_vm_name = nb_vm.name
        nb_vm_vmid_cf = nb_vm.custom_fields.get("vmid")
        nb_vm_vmid: Optional[int] = None
        if isinstance(nb_vm_vmid_cf, (int, float)): nb_vm_vmid = int(nb_vm_vmid_cf)
        elif isinstance(nb_vm_vmid_cf, str) and nb_vm_vmid_cf.isdigit(): nb_vm_vmid = int(nb_vm_vmid_cf)

        # Check if the NetBox VM (name, vmid) is in the active Proxmox set
        logger.debug(f"Checking NetBox VM '{nb_vm_name}' (ID: {nb_vm.id}, VMID CF: {nb_vm_vmid}) against active Proxmox identities.")
        if nb_vm_vmid is not None and (nb_vm_name, nb_vm_vmid) in active_proxmox_vm_identities:
            is_orphaned = False
            logger.debug(f"Match found by (name, vmid): ('{nb_vm_name}', {nb_vm_vmid}) is in active set.")
        # Check if the NetBox VM (original_name_candidate, vmid) is in the active Proxmox set
        # This handles cases where the NetBox VM name might have already been "Name (vmid)"
        elif nb_vm_vmid is not None: # Only perform this check if we have a VMID from NetBox
            original_name_candidate = nb_vm_name.removesuffix(f" ({nb_vm_vmid})").strip()
            if (original_name_candidate, nb_vm_vmid) in active_proxmox_vm_identities:
                is_orphaned = False
        
        if is_orphaned:
            current_vm_status_cf = nb_vm.custom_fields.get("vm_status")
            if current_vm_status_cf != "Deleted": # Only mark if not already deleted
                logger.info(f"NetBox VM '{nb_vm_name}' (ID: {nb_vm.id}, VMID CF: {nb_vm_vmid}) is orphaned. Marking as 'Deleted'.")
                try:
                    nb_vm.update({
                        "custom_fields": {"vm_status": "Deleted", "vm_last_sync": current_timestamp_iso}
                    })
                    orphans_marked_count += 1
                except pynetbox.core.query.RequestError as e:
                    logger.error(f"Error marking NetBox VM '{nb_vm_name}' as 'Deleted': {e.error if hasattr(e, 'error') else e}")
                    orphan_errors_count +=1
    logger.info(f"Orphan check completed. {orphans_marked_count} VM(s) marked as 'Deleted'. {orphan_errors_count} errors during marking.")
    return orphans_marked_count, orphan_errors_count


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
    return "other" # Default to 'other' if type is unknown

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
        netbox_preserve_iface_custom_field: The name of the custom field used to mark interfaces for preservation.
    """
    if not nb or not netbox_device_obj: return
    device_name_log = netbox_device_obj.name
    logger.info(f"Synchronizing network interfaces for NetBox Device: {device_name_log}")

    try:
        existing_nb_device_interfaces = list(nb.dcim.interfaces.filter(device_id=netbox_device_obj.id))
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Device {device_name_log}: Error fetching existing interfaces from NetBox: {e.error if hasattr(e, 'error') else e}")
        return
    
    netbox_ifaces_map = {iface.name: iface for iface in existing_nb_device_interfaces}
    processed_proxmox_iface_names = set() # To track which Proxmox interfaces were processed

    for p_iface in proxmox_node_ifaces_data:
        logger.debug(f"Processing Proxmox node interface data: {p_iface}")
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

        # Prepare custom fields for the device interface. These must exist in NetBox.
        iface_custom_fields = {
            "proxmox_interface_type": p_type_proxmox,
            "proxmox_interface_ports": p_slaves or p_bridge_ports
        }
        # Remove null custom fields
        iface_custom_fields = {k: v for k, v in iface_custom_fields.items() if v is not None}

        # Define netbox_iface_type using the helper function
        netbox_iface_type = _map_proxmox_iface_type_to_netbox(p_type_proxmox, p_name)

        # Get or create the device interface in NetBox
        nb_iface_obj = get_or_create_device_interface( # Call the helper function
            nb, netbox_device_obj.id, p_name, netbox_iface_type,
            mac_address=p_mac, enabled=p_active, description=p_comments,
            custom_fields=iface_custom_fields if iface_custom_fields else None
        )

        # --- MAC Address and Primary MAC Assignment ---
        # This logic should run if the interface object was obtained/created AND we have a MAC address from Proxmox.
        # It should NOT be conditional on the presence of an IP address.
        mac_object = None # Initialize mac_object outside the if
        if nb_iface_obj and p_mac:
            # nb_iface_obj is guaranteed to be non-None here.
            # p_mac is guaranteed to be non-None here.
            mac_object = get_or_create_and_assign_netbox_mac_address(
                nb, p_mac,
                assign_to_interface_id=nb_iface_obj.id,
                assigned_object_type=NETBOX_OBJECT_TYPE_DCIM_INTERFACE
            )
            
            # --- Add logic to set primary_mac_address on the interface ---
            # This links the MACAddress object to the interface's primary_mac_address field if the MAC object was successfully obtained/created.
            if mac_object and (getattr(nb_iface_obj, 'primary_mac_address', None) is None or getattr(nb_iface_obj, 'primary_mac_address').id != mac_object.id):
                 logger.info(f"Device {device_name_log}, Interface '{p_name}': Setting primary_mac_address to MAC object ID {mac_object.id}.")
                 try:
                     # Update the interface object to set its primary_mac_address field
                     # Note: This is a separate update call from the one in get_or_create_device_interface
                     # which updates the mac_address *string* field.
                     nb_iface_obj.update({"primary_mac_address": mac_object.id})
                 except pynetbox.core.query.RequestError as e_prime:
                     logger.error(f"Error setting primary MAC for interface {nb_iface_obj.id}: {e_prime.error if hasattr(e_prime, 'error') else e_prime}")
            # --- End of added logic ---
            
        if nb_iface_obj and p_ip and p_netmask: # This block remains for IP processing
            try:
                # Use ipaddress module for robust IP/netmask handling and CIDR conversion
                ip_interface_obj = ipaddress.ip_interface(f"{p_ip}/{p_netmask}")

                # Check if the interface IP is a network or broadcast address, which are usually not assignable
                if ip_interface_obj.ip == ip_interface_obj.network.network_address:
                    logger.warning(f"Device {device_name_log}, Interface '{p_name}': Configured IP '{p_ip}' is the network address. Will not be assigned in NetBox.")
                elif ip_interface_obj.ip == ip_interface_obj.network.broadcast_address:
                    logger.warning(f"Device {device_name_log}, Interface '{p_name}': Configured IP '{p_ip}' is the broadcast address. Will not be assigned in NetBox.")
                else:
                    # Only proceed if IP is not network or broadcast
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
                logger.error(f"Device {device_name_log}, Interface '{p_name}': Invalid IP/Netmask '{p_ip}/{p_netmask}'. Error: {e_ip}")
            except pynetbox.core.query.RequestError as e_nb_ip: 
                logger.error(f"Device {device_name_log}, Interface '{p_name}': NetBox error processing IP {p_ip}: {e_nb_ip.error if hasattr(e_nb_ip, 'error') else e_nb_ip}")

        # The get_or_create_device_interface helper already handles creation/updates.
        # The block below was redundant and could cause issues (e.g. assigning mac_object.id to mac_address string field).
        # It has been removed.

    # Delete orphaned interfaces from NetBox (those that were not processed from Proxmox data)
    for iface_name_to_delete, nb_iface_to_delete in netbox_ifaces_map.items():
        if iface_name_to_delete not in processed_proxmox_iface_names:
            # Check if the standard 'mgmt_only' field is True
            # The pynetbox library should make this attribute directly accessible if it exists
            if hasattr(nb_iface_to_delete, 'mgmt_only') and nb_iface_to_delete.mgmt_only is True:
                logger.info(f"Device {device_name_log}: Preserving interface '{iface_name_to_delete}' (ID: {nb_iface_to_delete.id}) as its 'mgmt_only' flag is true.")
                continue # Skip deletion
            elif hasattr(nb_iface_to_delete, 'mgmt_only') and str(nb_iface_to_delete.mgmt_only).upper() == "YES": # Fallback for string "YES"
                logger.info(f"Device {device_name_log}: Preserving interface '{iface_name_to_delete}' (ID: {nb_iface_to_delete.id}) as its 'mgmt_only' flag is 'YES'.")
                continue

            logger.info(f"Device {device_name_log}: Deleting orphaned interface '{iface_name_to_delete}' (ID: {nb_iface_to_delete.id}) from NetBox.")
            try: nb_iface_to_delete.delete()
            except pynetbox.core.query.RequestError as e:
                logger.error(f"Error deleting orphaned interface '{iface_name_to_delete}': {e.error if hasattr(e, 'error') else e}")

def sync_proxmox_node_to_netbox_device(
    nb: pynetbox.api,
    node_config: ProxmoxNodeConfig,
    node_details_from_proxmox: Dict[str, Any],
    global_settings: GlobalSettings # Add global_settings parameter
):
    """
    Synchronizes a Proxmox node to a NetBox Device.
    Creates or updates the Device in NetBox with details from Proxmox and the application's node configuration.

    Args:
        nb: The pynetbox API client.
        node_config: The ProxmoxNodeConfig object for the node being synced.
        node_details_from_proxmox: A dictionary of details fetched from the Proxmox node API. # type: ignore
        global_settings: The GlobalSettings object.
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
    dev_type = get_or_create_device_type(nb, node_config.netbox_node_device_type_name, manu.id if manu else None) if node_config.netbox_node_device_type_name and manu else None # Device Type requires Manufacturer ID
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
        "site": site.id if site else None, # site is an object, use .id
        "platform": platform, # platform is already an ID (int) or None
        "status": "active", # Assuming the node is active if we can fetch details
        "custom_fields": custom_fields
    }
    # Remove None values from the main payload
    device_payload = {k:v for k,v in device_payload.items() if v is not None}

    # Step 4: Get, create, or update the NetBox Device
    netbox_device_obj = nb.dcim.devices.get(name=node_name)
    if netbox_device_obj:
        logger.info(f"Updating existing NetBox Device: {node_name} (ID: {netbox_device_obj.id})")
        try: 
            if not netbox_device_obj.update(device_payload):
                logger.warning(f"NetBox Device '{node_name}' update call returned False. Check NetBox logs for details.")
        except pynetbox.core.query.RequestError as e: 
            logger.error(f"Error updating NetBox Device '{node_name}': {e.error if hasattr(e, 'error') else e}")
    else:
        logger.info(f"Creating new NetBox Device: {node_name}")
        try: netbox_device_obj = nb.dcim.devices.create(**device_payload)
        except pynetbox.core.query.RequestError as e: 
            logger.error(f"Error creating NetBox Device '{node_name}': {e.error if hasattr(e, 'error') else e}")

    # Step 5: Synchronize Node Interfaces and IPs
    if netbox_device_obj:
        proxmox_ifaces = node_details_from_proxmox.get("network_interfaces", [])
        sync_node_interfaces_and_ips(
            nb,
            netbox_device_obj,
            proxmox_ifaces
        )
    else: # type: ignore
        logger.warning(f"Could not get/create NetBox Device for '{node_name}'. Interfaces will not be synchronized.")
    logger.info(f"Synchronization of Proxmox node '{node_name}' to NetBox Device completed.")