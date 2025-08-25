import ipaddress  # For IP address validation and classification from agent
import json
import logging
import os  # For os.path.exists and os.path.splitext
import re  # For parsing disk configurations
from typing import Any, Dict, List, Optional, Union

# For SSH MAC address fetching (workaround)
import paramiko
from proxmoxer import ProxmoxAPI
from proxmoxer import core as proxmoxer_core

from config_models import ProxmoxNodeConfig  # For type hinting

logger = logging.getLogger(__name__)


def get_proxmox_api_client(config) -> Optional[ProxmoxAPI]:  # config is ProxmoxNodeConfig
    """Creates and returns a ProxmoxAPI client."""
    try:
        return ProxmoxAPI(
            config.host,
            user=config.user,
            token_name=config.token_name,
            token_value=config.token_secret,
            verify_ssl=config.verify_ssl,
        )
    except Exception as e:
        logger.error(f"Failed to connect to Proxmox host {config.host}: {e}")
        return None


def get_proxmox_vm_status(proxmox_api: ProxmoxAPI, proxmox_node_name: str, vm_info: Dict[str, Any]) -> Optional[str]:
    """
    Gets the current status of a VM/LXC in Proxmox.

    Args:
        proxmox_api: The ProxmoxAPI client instance.
        proxmox_node_name: The name of the Proxmox node.
        vm_info: A dictionary containing VM information, must include 'vmid' and 'type'.

    Returns:
        The status string (e.g., "running", "stopped") or None if an error occurs.
    """
    node_api = proxmox_api.nodes(proxmox_node_name)
    vm_id = vm_info.get("vmid")
    vm_name = vm_info.get("name", "Unknown")  # Default to 'Unknown' if name is not present
    vm_type = vm_info.get("type")
    if vm_id is None:
        logger.warning(f"VMID not found for VM: {vm_name}")
        return None

    try:
        status_endpoint_data = None
        if vm_type == "qemu":
            status_endpoint_data = node_api.qemu(vm_id).status.get("current")
        elif vm_type == "lxc":
            status_endpoint_data = node_api.lxc(vm_id).status.get("current")
        else:
            logger.warning(f"Unknown VM type '{vm_type}' for {vm_name}.")
            return None

        if status_endpoint_data:
            return status_endpoint_data.get("status")
        else:
            logger.warning(
                f"Could not retrieve status data for {vm_name} (vmid: {vm_id}). Response: {status_endpoint_data}"
            )
            return None
    except proxmoxer_core.ResourceException as e:
        logger.error(f"Proxmox API error (retrieving status) for {vm_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error (retrieving status) for {vm_name}: {e}", exc_info=True)
        return None


def _parse_size_to_mb(size_str: Optional[str]) -> Optional[int]:
    """
    Converts a Proxmox size string (e.g., "32G", "10240M", "2T") to Megabytes (MB).
    Handles units K, M, G, T (Kilo, Mega, Giga, Tera).
    If no unit is provided, it assumes Gigabytes for disk sizes as per Proxmox common usage.
    """
    if not size_str or not isinstance(size_str, str):
        return None

    size_str_upper = size_str.upper()

    # Try to extract the numeric part and the unit
    match = re.match(r"(\d+\.?\d*)\s*([KMGT])?B?", size_str_upper)
    if not match:
        # If it's just a number, assume it's bytes (less common for individual disk config)
        # This case is less likely for Proxmox disk 'size=' parameters which usually have units or imply GB.
        try:
            return round(int(size_str) / (1024 * 1024))
        except ValueError:
            logger.warning(f"Could not parse disk size string: '{size_str}'")
            return None

    num_part_str = match.group(1)
    unit = match.group(2)

    try:
        num = float(num_part_str)
    except ValueError:
        logger.warning(f"Could not convert numeric part of disk size: '{num_part_str}' from '{size_str}'")
        return None

    if unit == "T":
        return round(num * 1024 * 1024)
    elif unit == "G":
        return round(num * 1024)
    elif unit == "M":
        return round(num)
    elif unit == "K":
        return round(num / 1024)  # Converting KBytes to MBytes
    elif unit is None:  # No unit, Proxmox usually implies Gigabytes for 'size=' in disk config, convert to MB
        return round(num * 1024)
    else:  # Assume bytes if no known unit (or if it was just a number already handled)
        return round(num / (1024 * 1024))


def _get_format_from_filename(filename_or_path: Optional[str]) -> Optional[str]:
    """
    Infers the disk format from its filename extension.
    """
    if not filename_or_path:
        return None

    # In case the filename_or_path includes parameters like ',size=XG' for LXC mp
    # e.g. "local:backup/myimage.raw,size=10G" -> we only want "local:backup/myimage.raw"
    # However, the volume_name_or_path passed to this function should already be cleaned.
    # This is more of a safeguard if raw config parts are passed.
    # For now, assume volume_name_or_path is just the path.

    name, ext = os.path.splitext(filename_or_path)
    ext_lower = ext.lower()

    if ext_lower == ".qcow2":
        return "qcow2"
    elif ext_lower == ".raw":
        return "raw"
    elif ext_lower == ".vmdk":
        return "vmdk"
    elif ext_lower == ".img":  # .img is often raw
        return "raw"
    elif ext_lower == ".iso":  # For CD-ROM images
        return "iso"
    # For LXC templates/backups, if they are treated as disks
    elif ext_lower == ".tar":
        return "tar"
    elif ext_lower == ".gz" and name.lower().endswith(".tar"):
        return "tar.gz"
    elif ext_lower == ".zst" and name.lower().endswith(".tar"):
        return "tar.zst"
    return None


def _extract_virtual_disks(
    config: Dict[str, Any], resource_type: str, vm_id: int, qemu_boot_disk_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Extracts virtual disk information from a VM/LXC configuration.

    Args:
        config: The configuration dictionary for the VM/LXC.
        resource_type: 'qemu' or 'lxc'.
        vm_id: The ID of the VM/LXC for logging purposes.
        qemu_boot_disk_key: For QEMU, the key of the boot disk (e.g., "scsi0").

    Returns:
        A list of dictionaries, each representing a virtual disk.
    """
    virtual_disks: List[Dict[str, Any]] = []
    qemu_disk_regex = re.compile(r"^(ide|sata|scsi|virtio)(\d+)$")

    if resource_type == "qemu":
        for key, value in config.items():
            match = qemu_disk_regex.match(key)
            if match and isinstance(value, str):
                disk_name = key
                is_boot = qemu_boot_disk_key == disk_name

                # Skip CD-ROM drives as they are not persistent storage to sync
                if "media=cdrom" in value.lower():
                    logger.debug(f"QEMU {vm_id}: Skipping CD-ROM drive {disk_name}: {value}")
                    continue

                parts = value.split(",")
                storage_and_volume_part = parts[0]  # e.g., "local-lvm:vm-100-disk-0" or "mystorage:path/disk.qcow2"

                storage_id = None
                volume_name_or_path = storage_and_volume_part  # Default to the whole part if no colon
                if ":" in storage_and_volume_part:
                    split_storage_parts = storage_and_volume_part.split(":", 1)
                    storage_id = split_storage_parts[0]
                    if len(split_storage_parts) > 1:
                        volume_name_or_path = split_storage_parts[1]
                    else:  # Case like "local:" which is unlikely for a disk definition but handle defensively
                        volume_name_or_path = None

                if storage_id and storage_id.lower() == "none":
                    storage_id = None

                disk_params = {k.strip(): v.strip() for p in parts[1:] if "=" in p for k, v in [p.split("=", 1)]}

                size_mb = _parse_size_to_mb(disk_params.get("size"))
                disk_format = disk_params.get("format")  # Explicit format parameter

                if not disk_format and volume_name_or_path:  # If explicit format is missing, try to infer from filename
                    inferred_format = _get_format_from_filename(volume_name_or_path)
                    if inferred_format:
                        disk_format = inferred_format
                        logger.debug(
                            f"QEMU {vm_id}, Disk {disk_name}: Inferred format '{disk_format}' from volume/path '{volume_name_or_path}'."
                        )

                virtual_disks.append(
                    {
                        "name": disk_name,
                        "size_mb": size_mb,
                        "storage_id": storage_id,
                        "format": disk_format,
                        "is_boot_disk": is_boot,
                        "proxmox_raw_config": value,
                        "volume_name_or_path": volume_name_or_path,
                    }
                )

    elif resource_type == "lxc":
        # Handle LXC rootfs
        rootfs_config_str = config.get("rootfs")
        if rootfs_config_str and isinstance(rootfs_config_str, str):
            parts = rootfs_config_str.split(",")
            storage_and_volume_part = parts[0]  # e.g., "local-lvm:subvol-101-disk-0" or "local:100/vm-100-disk-0.raw"

            storage_id = None
            volume_name_or_path = storage_and_volume_part
            if ":" in storage_and_volume_part:
                split_storage_parts = storage_and_volume_part.split(":", 1)
                storage_id = split_storage_parts[0]
                volume_name_or_path = split_storage_parts[1] if len(split_storage_parts) > 1 else None

            disk_params = {k.strip(): v.strip() for p in parts[1:] if "=" in p for k, v in [p.split("=", 1)]}
            size_mb = _parse_size_to_mb(disk_params.get("size"))

            lxc_rootfs_format = None
            if volume_name_or_path:
                lxc_rootfs_format = _get_format_from_filename(volume_name_or_path)
                if lxc_rootfs_format:
                    logger.debug(
                        f"LXC {vm_id}, rootfs: Inferred format '{lxc_rootfs_format}' from volume/path '{volume_name_or_path}'."
                    )

            if (
                not lxc_rootfs_format
                and volume_name_or_path
                and (
                    "." not in volume_name_or_path
                    and (
                        "subvol-" in volume_name_or_path
                        or ("vm-" in volume_name_or_path and "-disk-" in volume_name_or_path)
                    )
                )
            ):
                lxc_rootfs_format = "raw"  # Assume raw for typical Proxmox LVM/ZFS volume names without extensions
                logger.debug(f"LXC {vm_id}, rootfs: Assuming format 'raw' for volume/path '{volume_name_or_path}'.")

            virtual_disks.append(
                {
                    "name": "rootfs",
                    "size_mb": size_mb,
                    "storage_id": storage_id,
                    "format": lxc_rootfs_format,
                    "is_boot_disk": True,
                    "mount_point": "/",
                    "proxmox_raw_config": rootfs_config_str,
                    "volume_name_or_path": volume_name_or_path,
                }
            )
        # Handle LXC mount points (mpX)
        for key, value in config.items():
            if key.startswith("mp") and isinstance(value, str):
                parts = value.split(",")
                storage_and_volume_part = parts[0]  # e.g., "local:102/vm-102-disk-1.raw"

                storage_id = None
                volume_name_or_path = storage_and_volume_part
                if ":" in storage_and_volume_part:
                    split_storage_parts = storage_and_volume_part.split(":", 1)
                    storage_id = split_storage_parts[0]
                    volume_name_or_path = split_storage_parts[1] if len(split_storage_parts) > 1 else None

                disk_params = {k.strip(): v.strip() for p in parts[1:] if "=" in p for k, v in [p.split("=", 1)]}
                size_mb = _parse_size_to_mb(disk_params.get("size"))
                lxc_mp_format = _get_format_from_filename(volume_name_or_path) if volume_name_or_path else None
                if lxc_mp_format:
                    logger.debug(
                        f"LXC {vm_id}, Mountpoint {key}: Inferred format '{lxc_mp_format}' from volume/path '{volume_name_or_path}'."
                    )
                elif (
                    not lxc_mp_format
                    and volume_name_or_path
                    and (
                        "." not in volume_name_or_path
                        and (
                            "subvol-" in volume_name_or_path
                            or ("vm-" in volume_name_or_path and "-disk-" in volume_name_or_path)
                        )
                    )
                ):
                    lxc_mp_format = "raw"
                    logger.debug(
                        f"LXC {vm_id}, Mountpoint {key}: Assuming format 'raw' for volume/path '{volume_name_or_path}'."
                    )

                virtual_disks.append(
                    {
                        "name": key,
                        "size_mb": size_mb,
                        "storage_id": storage_id,
                        "format": lxc_mp_format,
                        "is_boot_disk": False,
                        "mount_point": disk_params.get("mp"),
                        "proxmox_raw_config": value,
                        "volume_name_or_path": volume_name_or_path,
                    }
                )

    # Sort disks, putting the boot disk first, then by name
    virtual_disks.sort(key=lambda x: (not x.get("is_boot_disk", False), x["name"]))
    return virtual_disks


def _process_resource_config(
    proxmox_api: ProxmoxAPI, proxmox_node_name: str, resource_summary: Dict[str, Any], resource_type: str
) -> Optional[Dict[str, Any]]:
    """
    Fetches and processes the full configuration for a single Proxmox resource (VM or LXC).

    Args:
        proxmox_api: The ProxmoxAPI client.
        proxmox_node_name: The name of the Proxmox node.
        resource_summary: Basic information about the resource (from /nodes/{node}/qemu or /lxc).
        resource_type: 'qemu' or 'lxc'.

    Returns:
        A dictionary with detailed information for the resource, or None on error.
    """
    node_api = proxmox_api.nodes(proxmox_node_name)
    vm_id = resource_summary["vmid"]
    try:
        if resource_type == "qemu":
            config = node_api.qemu(vm_id).config.get()
            vcpus = config.get("cpus", 1)
        elif resource_type == "lxc":
            config = node_api.lxc(vm_id).config.get()
            vcpus = config.get("cores", config.get("cpu", 1))
        else:
            return None

        # Merge summary data with detailed config data
        full_data = {**resource_summary, **config}
        full_data["type"] = resource_type
        full_data["actual_status"] = get_proxmox_vm_status(proxmox_api, proxmox_node_name, full_data)
        full_data["proxmox_description"] = config.get("description", "")
        full_data["proxmox_ostype"] = config.get("ostype")
        full_data["proxmox_tags"] = config.get("tags", "")

        agent_network_data: Optional[List[Dict[str, Any]]] = None
        if resource_type == "qemu" and full_data.get("actual_status") == "running":
            try:
                logger.debug(f"QEMU VM {vm_id} is running. Attempting to fetch network interfaces via QEMU agent.")
                # The agent command might not exist or might fail if agent is not configured/running
                agent_raw_data = node_api.qemu(vm_id).agent.get("network-get-interfaces")

                if isinstance(agent_raw_data, list):
                    agent_network_data = agent_raw_data
                    logger.info(
                        f"QEMU VM {vm_id}: Successfully fetched {len(agent_network_data)} interface(s) from QEMU agent."
                    )
                elif (
                    isinstance(agent_raw_data, dict)
                    and "result" in agent_raw_data
                    and isinstance(agent_raw_data["result"], list)
                ):
                    agent_network_data = agent_raw_data["result"]
                    logger.info(
                        f"QEMU VM {vm_id}: Successfully fetched {len(agent_network_data)} interface(s) from QEMU agent (from 'result' key)."
                    )
                elif (
                    agent_raw_data is not None
                ):  # Agent might return non-list if command partially fails or has no data
                    # Log only a portion of the data if it's very large to avoid flooding logs
                    log_data_sample = (
                        str(agent_raw_data)[:200] + "..." if len(str(agent_raw_data)) > 200 else str(agent_raw_data)
                    )
                    logger.warning(
                        f"QEMU VM {vm_id}: QEMU agent 'network-get-interfaces' returned unexpected data structure: {log_data_sample}. Treating as no data."
                    )
            except proxmoxer_core.ResourceException as e_agent:
                # Log the specific error code and message if available
                # Common errors: 500 if agent not running, or command not found.
                logger.info(
                    f"QEMU VM {vm_id}: Could not retrieve network interfaces from QEMU agent (may not be running or installed): {e_agent}"
                )
            except Exception as e_agent_unexpected:
                logger.warning(
                    f"QEMU VM {vm_id}: Unexpected error fetching network interfaces from QEMU agent: {e_agent_unexpected}",
                    exc_info=True,
                )

        full_data["proxmox_network_interfaces"] = extract_network_interfaces_from_config(
            config,
            resource_type,
            vm_id,
            agent_network_data=agent_network_data,  # Pass agent data
        )

        if resource_type == "qemu":
            full_data["proxmox_cpu_sockets"] = config.get("sockets")
            # Handle memory: minmem (explicit minimum) or balloon (current dynamic minimum)
            min_mem_explicit_mb = config.get("minmem")
            current_balloon_val_mb = config.get("balloon")
            min_memory_to_sync_mb = None
            if isinstance(min_mem_explicit_mb, (int, float)) and min_mem_explicit_mb > 0:
                min_memory_to_sync_mb = int(min_mem_explicit_mb)
            elif isinstance(current_balloon_val_mb, (int, float)) and current_balloon_val_mb > 0:
                min_memory_to_sync_mb = int(current_balloon_val_mb)
            full_data["proxmox_min_memory_mb"] = min_memory_to_sync_mb

            # Determine boot_disk_key for QEMU
            qemu_boot_disk_key: Optional[str] = None
            boot_config = config.get("boot", "")
            full_data["proxmox_qemu_boot_order"] = boot_config

            if "order=" in boot_config:
                try:
                    order_str = boot_config.split("order=")[1].split(";")[0]
                    # Get the first disk device in the order (excluding network devices)
                    potential_boot_keys = [bk for bk in order_str.split(";") if not bk.startswith("net")]
                    if potential_boot_keys:
                        qemu_boot_disk_key = potential_boot_keys[0]
                except IndexError:
                    logger.warning(f"QEMU VM {vm_id}: Malformed boot order string: '{boot_config}'")
            elif boot_config and not any(c in boot_config for c in ["=", ";"]):  # ex: boot: scsi0
                if not boot_config.startswith("net"):
                    qemu_boot_disk_key = boot_config

            if not qemu_boot_disk_key and config.get("bootdisk"):  # Fallback para bootdisk (mais antigo)
                bootdisk_val = str(config.get("bootdisk"))
                if not bootdisk_val.startswith("net"):
                    qemu_boot_disk_key = bootdisk_val

            full_data["proxmox_virtual_disks"] = _extract_virtual_disks(
                config, resource_type, vm_id, qemu_boot_disk_key
            )

            full_data["proxmox_qemu_cpu_type"] = config.get("cpu")
            full_data["proxmox_qemu_bios_type"] = config.get("bios") or "SeaBIOS"
            full_data["proxmox_qemu_machine_type"] = config.get("machine")
            full_data["proxmox_qemu_numa_enabled"] = bool(int(config.get("numa", 0)))

            # Use Proxmox 'cores' field directly for 'cores per socket'
            # Proxmox define 'cores' como o número de cores por soquete.
            # O valor de 'cpus' (total vCPUs) é geralmente 'cores * sockets'.
            cores_per_socket_from_config = config.get("cores")
            if cores_per_socket_from_config is not None:
                full_data["proxmox_qemu_cores_per_socket"] = int(cores_per_socket_from_config)
            else:
                # Fallback to 1 if 'cores' is not present (Proxmox usually defaults to 1)
                full_data["proxmox_qemu_cores_per_socket"] = 1

            # Infer machine type if not explicitly set
            machine_type = config.get("machine")
            if not machine_type:  # Se None ou string vazia
                os_type_str = str(config.get("ostype", "")).lower()
                # Simplified logic to determine Proxmox default (q35 for Linux/Win, i440fx for others)
                is_linux_like = os_type_str.startswith("l") or any(
                    k_word in os_type_str for k_word in ["ubuntu", "debian", "centos", "fedora", "rhel", "arch"]
                )
                is_windows_like = os_type_str.startswith("win") or os_type_str.startswith("w")  # ex: w2k8, win10
                machine_type = "q35" if is_linux_like or is_windows_like else "i440fx"
            full_data["proxmox_qemu_machine_type"] = machine_type
        elif resource_type == "lxc":
            full_data["proxmox_lxc_arch"] = config.get("arch")
            full_data["proxmox_lxc_unprivileged"] = bool(int(config.get("unprivileged", 0)))
            full_data["proxmox_lxc_features"] = config.get("features")
            full_data["proxmox_virtual_disks"] = _extract_virtual_disks(config, resource_type, vm_id)
        full_data["vcpus_count"] = vcpus
        return full_data
    except proxmoxer_core.ResourceException as e:
        logger.error(
            f"Error retrieving configuration for {resource_type.upper()} {vm_id} ({resource_summary.get('name', 'N/A')}): {e}"
        )
        return None


def extract_network_interfaces_from_config(
    config: Dict[str, Any], resource_type: str, vm_id: int, agent_network_data: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Extracts network interface details from a VM/LXC configuration.

    If resource_type is 'qemu' and agent_network_data is provided, it will attempt
    to use IPs from the agent if static IPs are not configured.

    Args:
        config: The configuration dictionary for the VM/LXC.
        resource_type: 'qemu' or 'lxc'.
        vm_id: The ID of the VM/LXC for logging purposes.

    Returns:
        A list of dictionaries, each representing a network interface.
    """
    interfaces = []
    for key, value in config.items():
        if key.startswith("net") and isinstance(value, str):
            mac, ip_cidr, iface_name, bridge, model, vlan_tag = None, None, key, None, None, None
            try:
                parts = dict(item.split("=", 1) for item in value.split(",") if "=" in item)
                if "name" in parts:
                    iface_name = parts["name"]
                # Bridge is common for both QEMU and LXC
                if "bridge" in parts:
                    bridge = parts["bridge"]
                if "tag" in parts:
                    try:
                        vlan_tag = int(parts["tag"])
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid VLAN tag for interface {key}: {parts['tag']}")

                # MAC address extraction
                if "hwaddr" in parts:
                    mac = parts["hwaddr"]
                if not mac:
                    # Sometimes MAC is part of the device model string for QEMU (e.g., virtio=XX:YY:...)
                    device_part = value.split(",")[0]
                    if "=" in device_part:
                        _potential_model, mac_candidate = device_part.split("=", 1)
                        if len(mac_candidate) == 17 and mac_candidate.count(":") == 5:
                            mac = mac_candidate

                if mac:
                    if resource_type == "qemu":
                        model_candidate = value.split("=")[0].split(",")[0]
                        # List of known QEMU network models
                        known_qemu_models = [
                            "virtio",
                            "e1000",
                            "rtl8139",
                            "vmxnet3",
                            "i82551",
                            "i82557b",
                            "i82559er",
                            "pcnet",
                            "ne2k_pci",
                            "ne2k_isa",
                        ]
                        if model_candidate in known_qemu_models:
                            model = model_candidate
                    elif resource_type == "lxc":
                        model = "veth"
                    mac = mac.upper()
                else:
                    logger.warning(
                        f"VM {vm_id}, Interface {key}: No MAC address parsed. Configuration: {value}"
                    )  # continue

                if "ip" in parts:
                    # Extract IP/CIDR if statically configured (e.g. ip=192.168.1.10/24)
                    ip_value = parts["ip"]
                    if "/" in ip_value and ip_value.lower() != "dhcp":
                        ip_cidr = ip_value

            except ValueError as e:
                logger.warning(f"Cannot parse net config for VM {vm_id}, Iface {key}: '{value}'. Error: {e}")
                continue

            if mac:
                agent_ips_for_this_iface: List[Dict[str, str]] = []
                derived_ip_cidr_from_agent: Optional[str] = None

                # Populate agent_ips_for_this_iface if agent data is available for this MAC
                if resource_type == "qemu" and agent_network_data:  # Agent data only relevant for QEMU
                    logger.debug(f"VM {vm_id}, Interface {key} (MAC: {mac}): Processing QEMU agent data.")
                    found_agent_iface_for_all_ips = None
                    for agent_iface_info_scan in agent_network_data:
                        agent_mac_scan = agent_iface_info_scan.get("hardware-address")
                        if agent_mac_scan and agent_mac_scan.upper() == mac.upper():
                            found_agent_iface_for_all_ips = agent_iface_info_scan
                            break

                    if found_agent_iface_for_all_ips:
                        logger.debug(
                            f"VM {vm_id}, Interface {key}: Matched agent interface: {found_agent_iface_for_all_ips.get('name')} for collecting all agent IPs."
                        )
                        agent_ip_list_scan = found_agent_iface_for_all_ips.get("ip-addresses", [])
                        for agent_ip_obj_scan in agent_ip_list_scan:
                            addr_scan = agent_ip_obj_scan.get("ip-address")
                            prefix_scan = agent_ip_obj_scan.get("prefix")
                            addr_type_scan = agent_ip_obj_scan.get("ip-address-type")  # "ipv4" or "ipv6"
                            if addr_scan and prefix_scan is not None and addr_type_scan:
                                try:
                                    ip_obj_scan = ipaddress.ip_interface(f"{addr_scan}/{prefix_scan}")
                                    agent_ips_for_this_iface.append(
                                        {
                                            "address": str(ip_obj_scan),  # Store in CIDR format
                                            "family": addr_type_scan,
                                        }
                                    )
                                except ValueError:
                                    logger.warning(
                                        f"VM {vm_id}, Interface {key}: Invalid IP/prefix from agent (for agent_ips list): {addr_scan}/{prefix_scan}"
                                    )
                        logger.debug(f"VM {vm_id}, Interface {key}: Collected agent_ips: {agent_ips_for_this_iface}")

                # If static ip_cidr (from config's "ip=" field) is not set, try to derive one from agent_ips_for_this_iface
                if not ip_cidr and agent_ips_for_this_iface:
                    logger.debug(
                        f"VM {vm_id}, Interface {key} (MAC: {mac}): No static IP. Attempting to derive primary IP from collected agent IPs."
                    )

                    selected_ip_for_ip_cidr_field: Optional[Union[ipaddress.IPv4Interface, ipaddress.IPv6Interface]] = (
                        None
                    )

                    # Priority 1: Non-link-local, non-loopback, non-multicast IPv4
                    for ip_info in agent_ips_for_this_iface:
                        if ip_info["family"] == "ipv4":
                            ip_obj = ipaddress.ip_interface(ip_info["address"])
                            if not ip_obj.is_link_local and not ip_obj.is_loopback and not ip_obj.is_multicast:
                                selected_ip_for_ip_cidr_field = ip_obj
                                break

                    # Priority 2: Non-link-local, non-loopback, non-multicast IPv6
                    if not selected_ip_for_ip_cidr_field:
                        for ip_info in agent_ips_for_this_iface:
                            if ip_info["family"] == "ipv6":
                                ip_obj = ipaddress.ip_interface(ip_info["address"])
                                if not ip_obj.is_link_local and not ip_obj.is_loopback and not ip_obj.is_multicast:
                                    selected_ip_for_ip_cidr_field = ip_obj
                                    break

                    # Fallback: Any other IP (first one that's not loopback/multicast)
                    if not selected_ip_for_ip_cidr_field:
                        for ip_info in agent_ips_for_this_iface:
                            ip_obj = ipaddress.ip_interface(ip_info["address"])
                            if not ip_obj.is_loopback and not ip_obj.is_multicast:  # Ensure it's assignable
                                selected_ip_for_ip_cidr_field = ip_obj
                                break

                    if selected_ip_for_ip_cidr_field:
                        derived_ip_cidr_from_agent = str(selected_ip_for_ip_cidr_field)
                        logger.info(
                            f"VM {vm_id}, Interface {key}: Using IP '{derived_ip_cidr_from_agent}' from QEMU agent for 'ip_cidr' field."
                        )
                    else:
                        logger.debug(
                            f"VM {vm_id}, Interface {key}: Could not derive a suitable primary IP from agent IPs for 'ip_cidr' field."
                        )

                interfaces.append(
                    {
                        "name": iface_name,
                        "mac_address": mac,
                        "ip_cidr": ip_cidr or derived_ip_cidr_from_agent,  # Use derived if static ip_cidr is None
                        "bridge": bridge,
                        "model": model,
                        "vlan_tag": vlan_tag,
                        "agent_ips": agent_ips_for_this_iface,  # Store all IPs reported by agent for this MAC
                    }
                )
            elif key.startswith("net"):
                logger.warning(f"Interface {key} skipped, no MAC address found. Configuration: {value}")
    return interfaces


def fetch_vms_and_lxc(proxmox_api: ProxmoxAPI, proxmox_node_name: str) -> List[Dict[str, Any]]:
    """
    Fetches all VMs and LXC containers from a specified Proxmox node.

    Args:
        proxmox_api: The ProxmoxAPI client.
        proxmox_node_name: The name of the Proxmox node.

    Returns:
        A list of dictionaries, each containing detailed information for a VM or LXC.
    """
    all_resources: List[Dict[str, Any]] = []
    if not proxmox_api:
        logger.error("Proxmox API client not initialized.")
        return all_resources

    node_api = proxmox_api.nodes(proxmox_node_name)
    try:
        resource_getters = {"qemu": lambda: node_api.qemu.get(), "lxc": lambda: node_api.lxc.get()}
        for resource_type, getter in resource_getters.items():
            raw_resources = getter()
            for resource_summary in raw_resources:
                processed_data = _process_resource_config(
                    proxmox_api, proxmox_node_name, resource_summary, resource_type
                )
                if processed_data:
                    all_resources.append(processed_data)
    except proxmoxer_core.ResourceException as e:
        logger.error(f"Error fetching VMs/LXCs from Proxmox node '{proxmox_node_name}': {e}")
    except Exception as e:
        logger.error(
            f"An unexpected error occurred while fetching VMs/LXCs from node '{proxmox_node_name}': {e}", exc_info=True
        )
    return all_resources


def fetch_proxmox_node_details(
    proxmox_api: ProxmoxAPI,
    node_config: ProxmoxNodeConfig,  # Changed from proxmox_node_name to full node_config
) -> Optional[Dict[str, Any]]:
    """
    Fetches comprehensive details for a specific Proxmox node.
    This includes CPU, memory, PVE version, and network interface information.

    Args:
        proxmox_api: The ProxmoxAPI client.
        node_config: The ProxmoxNodeConfig object for the node.

    Returns:
        A dictionary containing node details, or None on error.
    """
    if not proxmox_api:
        logger.error("Proxmox API client not initialized for fetch_proxmox_node_details.")
        return None

    proxmox_node_name = node_config.node_name  # Get node_name from config
    node_api = proxmox_api.nodes(proxmox_node_name)  # Use the actual node name for API calls
    details: Dict[str, Any] = {"name": proxmox_node_name}

    try:
        # Status Information (CPU, Memory, Root Disk)
        status_info = node_api.status.get()
        if status_info:
            cpu_info = status_info.get("cpuinfo", {})
            details["cpu_model"] = cpu_info.get("model")
            details["cpu_sockets"] = cpu_info.get("sockets")
            details["cpu_cores_total"] = cpu_info.get("cpus")  # Total de cores lógicos

            memory_info = status_info.get("memory", {})
            details["memory_total_bytes"] = memory_info.get("total")
            details["memory_used_bytes"] = memory_info.get("used")

            rootfs_info = status_info.get("rootfs", {})
            details["rootfs_total_bytes"] = rootfs_info.get("total")
            details["rootfs_used_bytes"] = rootfs_info.get("used")

        # Proxmox VE Version
        version_info = proxmox_api.version.get()
        if version_info:
            details["pve_version"] = version_info.get("version")

        # Node Network Interfaces
        network_interfaces_raw = node_api.network.get()
        # Optional: Log the entire raw response for deep inspection if needed
        # logger.debug(f"Node {proxmox_node_name} raw network interfaces: {network_interfaces_raw}")
        parsed_interfaces_from_api = []
        for if_raw in network_interfaces_raw:
            # Log details for each specific interface being processed
            logger.debug(f"Node {proxmox_node_name}, processing raw interface from API: {if_raw}")
            mac_address_from_api = if_raw.get("mac")
            iface_name_from_api = if_raw.get("iface")
            logger.debug(
                f"Node {proxmox_node_name}, Interface '{iface_name_from_api}': MAC from API is '{mac_address_from_api}' (type: {type(mac_address_from_api)})"
            )

            if_details = {
                "name": iface_name_from_api,
                "type_proxmox": if_raw.get("type"),  # bridge, eth, bond, vlan
                "active": bool(if_raw.get("active")),
                "mac_address": mac_address_from_api,  # Use the logged variable
                "ip_address": if_raw.get("address"),  # May not be CIDR
                "netmask": if_raw.get("netmask"),
                "gateway": if_raw.get("gateway"),  # Usually on one interface
                "comments": if_raw.get("comments"),
                "slaves": if_raw.get("slaves"),  # For bonds
                "bridge_ports": if_raw.get("bridge_ports"),  # For bridges
                "vlan_id": if_raw.get("vlan-id"),
                "vlan_raw_device": if_raw.get("vlan-raw-device"),
            }
            # Construct CIDR if possible
            # Note: For robust CIDR construction from IP and netmask, ipaddress module is recommended.
            # This is handled in the sync_orchestrator when assigning IPs.
            if if_details["ip_address"] and if_details["netmask"]:
                # For now, just store separately. Conversion to prefixlen happens later if needed.
                pass
            parsed_interfaces_from_api.append(if_details)

        # --- SSH MAC Address Enhancement ---
        ssh_mac_map: Dict[str, str] = {}
        ssh_host_to_use = node_config.ssh_host or node_config.host  # Default to API host if ssh_host not set

        if node_config.enable_ssh_mac_fetch:
            if ssh_host_to_use and node_config.ssh_user:
                logger.info(
                    f"Node {proxmox_node_name}: SSH MAC fetch enabled. Attempting connection to {ssh_host_to_use}."
                )
                ssh_client = None  # Ensure ssh_client is defined for finally block
                try:
                    ssh_client = paramiko.SSHClient()
                    ssh_client.set_missing_host_key_policy(
                        paramiko.AutoAddPolicy()
                    )  # Consider a more secure policy for production

                    connect_params = {
                        "hostname": ssh_host_to_use,
                        "port": node_config.ssh_port or 22,
                        "username": node_config.ssh_user,
                        "timeout": 10,  # Connection timeout in seconds
                    }
                    if node_config.ssh_password:
                        connect_params["password"] = node_config.ssh_password
                    elif node_config.ssh_key_path and os.path.exists(node_config.ssh_key_path):
                        connect_params["key_filename"] = node_config.ssh_key_path
                    else:  # No password and no valid key path
                        logger.warning(
                            f"Node {proxmox_node_name}: SSH MAC fetch enabled, but no password or valid SSH key path provided for user {node_config.ssh_user}. Skipping SSH."
                        )
                        raise paramiko.AuthenticationException(
                            "No valid SSH credentials provided."
                        )  # Raise to skip to finally

                    ssh_client.connect(**connect_params)

                    stdin, stdout, stderr = ssh_client.exec_command("ip -j link show")
                    exit_status = stdout.channel.recv_exit_status()

                    if exit_status == 0:
                        ip_link_json_output = stdout.read().decode()
                        ip_link_data = json.loads(ip_link_json_output)
                        for if_data_ssh in ip_link_data:
                            if_name_ssh = if_data_ssh.get("ifname")
                            mac_ssh = if_data_ssh.get("address")
                            if if_name_ssh and mac_ssh and mac_ssh != "00:00:00:00:00:00":
                                ssh_mac_map[if_name_ssh] = mac_ssh.upper()
                        logger.info(
                            f"Node {proxmox_node_name}: Successfully fetched MACs via SSH for {len(ssh_mac_map)} interfaces."
                        )
                    else:
                        error_output = stderr.read().decode().strip()
                        logger.error(
                            f"Node {proxmox_node_name}: SSH command 'ip -j link show' failed (status {exit_status}). Error: {error_output}"
                        )
                except paramiko.AuthenticationException:
                    logger.error(
                        f"Node {proxmox_node_name}: SSH authentication failed for {node_config.ssh_user}@{ssh_host_to_use}."
                    )
                except paramiko.SSHException as ssh_ex:  # Covers various SSH connection issues
                    logger.error(f"Node {proxmox_node_name}: SSH connection error to {ssh_host_to_use}: {ssh_ex}")
                except json.JSONDecodeError:
                    logger.error(f"Node {proxmox_node_name}: Failed to parse JSON from 'ip -j link show'.")
                except Exception as e_ssh:
                    logger.error(
                        f"Node {proxmox_node_name}: Unexpected error during SSH MAC fetching: {e_ssh}", exc_info=True
                    )
                finally:
                    if ssh_client:
                        ssh_client.close()
            else:
                logger.info(
                    f"Node {proxmox_node_name}: SSH MAC fetch enabled, but SSH host or user not configured; MAC enhancement via SSH skipped."
                )
        else:
            logger.info(f"Node {proxmox_node_name}: SSH MAC fetch is disabled by configuration.")

        # Merge API data with SSH MACs
        final_parsed_interfaces = []
        for if_api_details in parsed_interfaces_from_api:
            iface_name_api = if_api_details.get("name")
            current_mac_api = if_api_details.get("mac_address")
            if (not current_mac_api or current_mac_api == "00:00:00:00:00:00") and iface_name_api in ssh_mac_map:
                ssh_found_mac = ssh_mac_map[iface_name_api]
                logger.info(
                    f"Node {proxmox_node_name}, Interface '{iface_name_api}': Using MAC '{ssh_found_mac}' from SSH (API MAC was '{current_mac_api}')."
                )
                if_api_details["mac_address"] = ssh_found_mac
            final_parsed_interfaces.append(if_api_details)
        details["network_interfaces"] = final_parsed_interfaces
        logger.info(
            f"Node details for {proxmox_node_name} fetched: CPU Sockets: {details.get('cpu_sockets')}, PVE Ver: {details.get('pve_version')}"
        )
        return details

    except proxmoxer_core.ResourceException as e:
        logger.error(f"Proxmox API error while fetching node details for {proxmox_node_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while fetching node details for {proxmox_node_name}: {e}", exc_info=True)
        return None
