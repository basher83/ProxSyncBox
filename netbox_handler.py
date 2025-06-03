import logging
import pynetbox
import requests
from typing import List, Dict, Any, Optional

from utils import (
    NETBOX_OBJECT_TYPE_VMINTERFACE,  # For Virtual Machine Interfaces
    NETBOX_OBJECT_TYPE_DCIM_INTERFACE  # For Device (physical) Interfaces
)

logger = logging.getLogger(__name__)

def get_netbox_api_client(netbox_url: Optional[str], netbox_token: Optional[str]) -> Optional[pynetbox.api]:
    """Creates and returns a pynetbox API client."""
    if not netbox_url or not netbox_token:
        logger.error("NetBox URL or Token not configured.")
        return None

    # You should handle SSL verification according to your environment's security requirements
    
    session = requests.Session()
    session.verify = False # Ajuste conforme sua necessidade de SSL
    if not session.verify:
        if hasattr(requests.packages, 'urllib3'): # Check if urllib3 is part of requests
            requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    
    try:
        nb = pynetbox.api(netbox_url, token=str(netbox_token))
        nb.http_session = session
        return nb
    except Exception as e:
        logger.error(f"Failed to connect to the NetBox API at {netbox_url}: {e}")
        return None

def get_existing_vms(nb: pynetbox.api) -> Dict[str, Any]:
    """Fetches all existing virtual machines from NetBox."""
    if not nb: return {}
    try:
        return {vm.name: vm for vm in nb.virtualization.virtual_machines.all()}
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error while fetching existing VMs from NetBox: {e}")
        return {}

def get_or_create_netbox_tags(nb: pynetbox.api, tag_names: List[str]) -> List[Dict[str, int]]:
    if not nb: return []
    tag_ids = []
    for name in tag_names:
        tag = nb.extras.tags.get(name=name)
        if not tag:
            simple_slug = name.lower().replace(" ", "-")
            tag = nb.extras.tags.get(slug=simple_slug)
        if not tag: # If neither name nor slug match, create the tag
            logger.info(f"Creating tag in NetBox: {name}")
            try:
                tag = nb.extras.tags.create(name=name, slug=name.lower().replace(" ", "-")) # Also create slug
            except pynetbox.core.query.RequestError as e:
                logger.error(f"Erro ao criar tag '{name}': {e.error if hasattr(e, 'error') else e}")
                continue
        if tag:
            tag_ids.append({"id": tag.id})
    return tag_ids

def get_or_create_cluster(nb: pynetbox.api, cluster_name: str, cluster_type_name: str) -> Optional[Any]:
    if not nb: return None
    cluster = nb.virtualization.clusters.get(name=cluster_name)
    if cluster: # Cluster found
        logger.info(f"Cluster '{cluster_name}' found with ID: {cluster.id}")
        return cluster
    else: # Cluster not found, try to create it
        logger.info(f"Cluster '{cluster_name}' not found. Attempting to create...")
        cluster_type = nb.virtualization.cluster_types.get(name=cluster_type_name)
        if not cluster_type: # If cluster type doesn't exist, create it
            logger.info(f"Cluster type '{cluster_type_name}' not found. Creating...")
            try:
                cluster_type = nb.virtualization.cluster_types.create(name=cluster_type_name, slug=cluster_type_name.lower().replace(" ", "-"))
            except pynetbox.core.query.RequestError as e:
                logger.error(f"Error creating cluster type '{cluster_type_name}': {e.error if hasattr(e, 'error') else e}")
                return None
        try:
            cluster = nb.virtualization.clusters.create(name=cluster_name, type=cluster_type.id)
            logger.info(f"Cluster '{cluster_name}' criado com ID: {cluster.id}")
            return cluster
        except pynetbox.core.query.RequestError as e:
            logger.error(f"Erro ao criar cluster '{cluster_name}': {e.error if hasattr(e, 'error') else e}")
            return None

def get_or_create_cluster_type(nb: pynetbox.api, cluster_type_name: str) -> Optional[Any]:
    """
    Retrieves or creates a cluster type in NetBox.

    Args:
        nb: The pynetbox API client.
        cluster_type_name: The name of the cluster type.

    Returns:
        The NetBox cluster type object if found or created, otherwise None.
    """
    if not nb or not cluster_type_name: return None
    cluster_type = nb.virtualization.cluster_types.get(name=cluster_type_name)
    if cluster_type:
        logger.info(f"Cluster type '{cluster_type_name}' found with ID: {cluster_type.id}")
        return cluster_type
    logger.info(f"Cluster type '{cluster_type_name}' not found. Creating...")
    try:
        return nb.virtualization.cluster_types.create(name=cluster_type_name, slug=cluster_type_name.lower().replace(" ", "-"))
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error creating cluster type '{cluster_type_name}': {e.error if hasattr(e, 'error') else e}")
        return None

def get_or_create_netbox_platform(nb: pynetbox.api, platform_name: str) -> Optional[int]:
    if not nb or not platform_name: return None
    platform = nb.dcim.platforms.get(name=platform_name)
    if platform: return platform.id

    generated_slug = platform_name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    platform_by_slug = nb.dcim.platforms.get(slug=generated_slug)
    if platform_by_slug: return platform_by_slug.id
    
    logger.info(f"Plataforma '{platform_name}' não encontrada. Criando com slug '{generated_slug}'...")
    try:
        created_platform = nb.dcim.platforms.create(name=platform_name, slug=generated_slug)
        return created_platform.id
    except pynetbox.core.query.RequestError as e:
        error_message = str(e.error if hasattr(e, 'error') else e)
        if "unique constraint" in error_message.lower() or "already exists" in error_message.lower():
            logger.warning(f"Conflito ao criar plataforma '{platform_name}'. Tentando buscar novamente.")
            platform_after_conflict = nb.dcim.platforms.get(name=platform_name) or nb.dcim.platforms.get(slug=generated_slug)
            if platform_after_conflict: return platform_after_conflict.id
            else: logger.error(f"Erro ao criar/buscar plataforma '{platform_name}' pós-conflito: {error_message}")
        else: logger.error(f"Erro ao criar plataforma '{platform_name}': {error_message}")
        return None
    except Exception as e_gen:
        logger.error(f"Erro inesperado ao criar plataforma '{platform_name}': {e_gen}", exc_info=True)
        return None

def get_or_create_netbox_vlan(nb: pynetbox.api, vlan_id: int, vlan_name_prefix: str = "VLAN_") -> Optional[int]:
    if not nb or not vlan_id: return None
    vlan_name = f"{vlan_name_prefix}{vlan_id}"
    vlans = nb.ipam.vlans.filter(vid=vlan_id)
    if vlans: return vlans[0].id

    logger.info(f"VLAN VID {vlan_id} (nome: {vlan_name}) não encontrada. Criando...")
    try:
        # Considere adicionar 'site': site_id se necessário para sua configuração NetBox
        created_vlan = nb.ipam.vlans.create(name=vlan_name, vid=vlan_id)
        return created_vlan.id
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Erro ao criar VLAN VID {vlan_id}: {e.error if hasattr(e, 'error') else e}")
        return None

def get_or_create_and_assign_netbox_mac_address(
    nb: pynetbox.api, 
    mac_str: str, 
    assign_to_interface_id: Optional[int] = None
) -> Optional[pynetbox.core.response.Record]:
    if not nb or not mac_str: return None
    mac_str_upper = mac_str.upper()
    try:
        mac_objects = nb.dcim.mac_addresses.filter(address=mac_str_upper)
        found_mac_obj = next((obj for obj in mac_objects if hasattr(obj, 'address') and obj.address.upper() == mac_str_upper), None)
        
        if not found_mac_obj:
            logger.info(f"MAC Address '{mac_str_upper}' não encontrado. Criando...")
            created_mac_obj_temp = nb.dcim.mac_addresses.create(mac_address=mac_str_upper) # 'mac_address' for creation
            if created_mac_obj_temp:
                found_mac_obj = nb.dcim.mac_addresses.get(created_mac_obj_temp.id) # Re-fetch
            if not found_mac_obj:
                logger.error(f"Falha ao criar/recarregar MAC Address {mac_str_upper}.")
                return None

        if found_mac_obj and assign_to_interface_id:
            current_assignment = getattr(found_mac_obj, 'interface', None)
            needs_assignment_update = not (current_assignment and isinstance(current_assignment, dict) and current_assignment.get('id') == assign_to_interface_id)
            
            if needs_assignment_update:
                log_mac_val = getattr(found_mac_obj, 'address', mac_str_upper) # Fallback to original MAC if not on object (shouldn't happen)
                logger.info(f"Atribuindo MAC {log_mac_val} (ID: {found_mac_obj.id}) à interface ID: {assign_to_interface_id}")
                update_payload = {
                    "assigned_object_type": NETBOX_OBJECT_TYPE_VMINTERFACE,
                    "assigned_object_id": assign_to_interface_id
                }
                try:
                    if not found_mac_obj.update(update_payload):
                        logger.warning(f"Falha ao atribuir MAC {log_mac_val} à interface {assign_to_interface_id} (update() retornou False).")
                except pynetbox.core.query.RequestError as e_assign:
                    logger.error(f"Error assigning MAC {log_mac_val} to interface {assign_to_interface_id}: {e_assign.error if hasattr(e_assign, 'error') else e_assign}")
        return found_mac_obj
    except pynetbox.core.query.RequestError as e:
        logger.error(f"GENERAL error obtaining/creating MAC '{mac_str_upper}': {e.error if hasattr(e, 'error') else e}")
        return None

def get_or_create_site(nb: pynetbox.api, site_name: str, site_slug: Optional[str] = None) -> Optional[Any]:
    if not nb or not site_name: return None
    site = nb.dcim.sites.get(name=site_name)
    if site: return site

    slug = site_slug or site_name.lower().replace(" ", "-")
    site_by_slug = nb.dcim.sites.get(slug=slug)
    if site_by_slug: return site_by_slug

    logger.info(f"Site '{site_name}' não encontrado. Criando com slug '{slug}'...")
    try:
        return nb.dcim.sites.create(name=site_name, slug=slug, status="active") # status pode ser configurável
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Erro ao criar site '{site_name}': {e.error if hasattr(e, 'error') else e}")
        return None

def get_or_create_manufacturer(nb: pynetbox.api, manu_name: str, manu_slug: Optional[str] = None) -> Optional[Any]:
    if not nb or not manu_name: return None
    manufacturer = nb.dcim.manufacturers.get(name=manu_name)
    if manufacturer: return manufacturer

    slug = manu_slug or manu_name.lower().replace(" ", "-").replace(".", "")
    manu_by_slug = nb.dcim.manufacturers.get(slug=slug)
    if manu_by_slug: return manu_by_slug
    
    logger.info(f"Fabricante '{manu_name}' não encontrado. Criando com slug '{slug}'...")
    try:
        return nb.dcim.manufacturers.create(name=manu_name, slug=slug)
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Erro ao criar fabricante '{manu_name}': {e.error if hasattr(e, 'error') else e}")
        return None

def get_or_create_device_type(nb: pynetbox.api, model_name: str, manufacturer_id: int, dt_slug: Optional[str] = None, u_height: int = 1) -> Optional[Any]:
    if not nb or not model_name or not manufacturer_id: return None
    # NetBox DeviceType é único por manufacturer E (model OU slug)
    device_type = nb.dcim.device_types.get(model=model_name, manufacturer_id=manufacturer_id)
    if device_type: return device_type

    slug = dt_slug or model_name.lower().replace(" ", "-")
    dt_by_slug = nb.dcim.device_types.get(slug=slug, manufacturer_id=manufacturer_id)
    if dt_by_slug: return dt_by_slug

    logger.info(f"Tipo de Dispositivo '{model_name}' (Fabricante ID: {manufacturer_id}) não encontrado. Criando com slug '{slug}'...")
    try:
        return nb.dcim.device_types.create(
            model=model_name,
            slug=slug,
            manufacturer=manufacturer_id,
            u_height=u_height, # Default para 1U, pode ser configurável
            is_full_depth=True # Default, pode ser configurável
        )
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Erro ao criar Tipo de Dispositivo '{model_name}': {e.error if hasattr(e, 'error') else e}")
        return None

def get_or_create_device_role(nb: pynetbox.api, role_name: str, role_slug: Optional[str] = None, color_hex: str = "00bcd4") -> Optional[Any]:
    if not nb or not role_name: return None
    device_role = nb.dcim.device_roles.get(name=role_name)
    if device_role: return device_role

    slug = role_slug or role_name.lower().replace(" ", "-")
    role_by_slug = nb.dcim.device_roles.get(slug=slug)
    if role_by_slug: return role_by_slug

    logger.info(f"Papel de Dispositivo '{role_name}' não encontrado. Criando com slug '{slug}'...")
    try:
        return nb.dcim.device_roles.create(name=role_name, slug=slug, color=color_hex, vm_role=False) # vm_role=False para papéis de dispositivo físico/virtual
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Erro ao criar Papel de Dispositivo '{role_name}': {e.error if hasattr(e, 'error') else e}")
        return None

def get_or_create_device_interface(
    nb: pynetbox.api, 
    device_id: int, 
    iface_name: str, 
    iface_type: str, # ex: '1000base-t', 'lag', 'bridge', 'virtual'
    mac_address: Optional[str] = None,
    enabled: bool = True,
    mtu: Optional[int] = None,
    description: Optional[str] = None,
    custom_fields: Optional[Dict[str, Any]] = None
) -> Optional[Any]:
    if not nb or not device_id or not iface_name or not iface_type: return None
    
    # Tenta buscar por nome e device_id
    existing_iface = nb.dcim.interfaces.get(device_id=device_id, name=iface_name)
    if existing_iface:
        # Atualizar se necessário (ex: MAC, tipo, enabled, custom_fields)
        update_payload = {}
        if mac_address and existing_iface.mac_address != mac_address.upper(): update_payload["mac_address"] = mac_address.upper()
        if existing_iface.type != iface_type: update_payload["type"] = iface_type
        if existing_iface.enabled != enabled: update_payload["enabled"] = enabled
        if description and existing_iface.description != description: update_payload["description"] = description
        if custom_fields and existing_iface.custom_fields != custom_fields: update_payload["custom_fields"] = custom_fields
        # Adicionar mais campos se necessário (mtu, etc.)
        if update_payload:
            logger.info(f"Atualizando interface '{iface_name}' (ID: {existing_iface.id}) no dispositivo ID {device_id}.")
            try: existing_iface.update(update_payload)
            except pynetbox.core.query.RequestError as e: logger.error(f"Erro ao atualizar interface '{iface_name}': {e.error}")
        return existing_iface

    logger.info(f"Interface '{iface_name}' não encontrada no dispositivo ID {device_id}. Criando...")
    create_payload = {"device": device_id, "name": iface_name, "type": iface_type, "enabled": enabled}
    if mac_address: create_payload["mac_address"] = mac_address.upper()
    if mtu: create_payload["mtu"] = mtu
    if description: create_payload["description"] = description
    if custom_fields: create_payload["custom_fields"] = custom_fields
    try:
        return nb.dcim.interfaces.create(**create_payload)
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Erro ao criar interface '{iface_name}' para dispositivo ID {device_id}: {e.error if hasattr(e, 'error') else e}")
        return None