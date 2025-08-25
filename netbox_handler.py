import logging
from typing import Any, Dict, List, Optional

import pynetbox
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Ensure DEBUG messages from this module are processed


def get_netbox_api_client(netbox_url: Optional[str], netbox_token: Optional[str]) -> Optional[pynetbox.api]:
    """Creates and returns a pynetbox API client."""
    if not netbox_url or not netbox_token:
        logger.error("NetBox URL or Token not configured.")
        return None

    # You should handle SSL verification according to your environment's security requirements

    session = requests.Session()
    session.verify = False  # Ajuste conforme sua necessidade de SSL
    if not session.verify and hasattr(requests.packages, "urllib3"):  # Check if urllib3 is part of requests
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
    if not nb:
        return {}
    try:
        return {vm.name: vm for vm in nb.virtualization.virtual_machines.all()}
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error while fetching existing VMs from NetBox: {e}")
        return {}


def get_or_create_netbox_tags(nb: pynetbox.api, tag_names: List[str]) -> List[Dict[str, int]]:
    if not nb:
        return []
    tag_ids = []
    for name in tag_names:
        tag = nb.extras.tags.get(name=name)
        if not tag:
            simple_slug = name.lower().replace(" ", "-")
            tag = nb.extras.tags.get(slug=simple_slug)
        if not tag:  # If neither name nor slug match, create the tag
            logger.info(f"Creating tag in NetBox: {name}")
            try:
                tag = nb.extras.tags.create(name=name, slug=name.lower().replace(" ", "-"))
            except pynetbox.core.query.RequestError as e:
                logger.error(f"Error creating tag '{name}': {e.error if hasattr(e, 'error') else e}")
                continue
        if tag:
            tag_ids.append({"id": tag.id})
    return tag_ids


def get_or_create_cluster(nb: pynetbox.api, cluster_name: str, cluster_type_name: str) -> Optional[Any]:
    if not nb or not cluster_type_name:
        return None  # Added check for cluster_type_name
    cluster = nb.virtualization.clusters.get(name=cluster_name)
    if cluster:  # Cluster found
        logger.info(f"Cluster '{cluster_name}' found with ID: {cluster.id}")
        return cluster
    else:  # Cluster not found, try to create it
        logger.info(f"Cluster '{cluster_name}' not found. Attempting to create it...")
        cluster_type = nb.virtualization.cluster_types.get(name=cluster_type_name)
        if not cluster_type:  # If cluster type doesn't exist, create it
            logger.info(f"Cluster type '{cluster_type_name}' not found. Creating...")
            try:
                cluster_type = nb.virtualization.cluster_types.create(
                    name=cluster_type_name, slug=cluster_type_name.lower().replace(" ", "-")
                )
            except pynetbox.core.query.RequestError as e:
                logger.error(
                    f"Error creating cluster type '{cluster_type_name}': {e.error if hasattr(e, 'error') else e}"
                )
                return None
        try:
            cluster = nb.virtualization.clusters.create(name=cluster_name, type=cluster_type.id)  # Use cluster type ID
            logger.info(f"Cluster '{cluster_name}' created with ID: {cluster.id}")
            return cluster
        except pynetbox.core.query.RequestError as e:
            logger.error(f"Error creating cluster '{cluster_name}': {e.error if hasattr(e, 'error') else e}")
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
    if not nb or not cluster_type_name:
        return None
    cluster_type = nb.virtualization.cluster_types.get(name=cluster_type_name)
    if cluster_type:
        logger.info(f"Cluster type '{cluster_type_name}' found with ID: {cluster_type.id}")
        return cluster_type
    logger.info(f"Cluster type '{cluster_type_name}' not found. Creating...")
    try:  # "Creating..."
        return nb.virtualization.cluster_types.create(
            name=cluster_type_name, slug=cluster_type_name.lower().replace(" ", "-")
        )  # Create slug from name
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error creating cluster type '{cluster_type_name}': {e.error if hasattr(e, 'error') else e}")
        return None


def get_or_create_netbox_platform(nb: pynetbox.api, platform_name: str) -> Optional[int]:
    if not nb or not platform_name:
        return None
    platform = nb.dcim.platforms.get(name=platform_name)
    if platform:
        return platform.id

    generated_slug = platform_name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    platform_by_slug = nb.dcim.platforms.get(slug=generated_slug)
    if platform_by_slug:
        return platform_by_slug.id

    logger.info(f"Platform '{platform_name}' not found. Creating with slug '{generated_slug}'...")
    try:
        created_platform = nb.dcim.platforms.create(name=platform_name, slug=generated_slug)
        return created_platform.id
    except pynetbox.core.query.RequestError as e:
        error_message = str(e.error if hasattr(e, "error") else e)
        if "unique constraint" in error_message.lower() or "already exists" in error_message.lower():
            logger.warning(f"Conflict creating platform '{platform_name}'. Attempting to fetch again.")
            platform_after_conflict = nb.dcim.platforms.get(name=platform_name) or nb.dcim.platforms.get(
                slug=generated_slug
            )
            if platform_after_conflict:
                return platform_after_conflict.id
            else:
                logger.error(f"Error creating/fetching platform '{platform_name}' post-conflict: {error_message}")
        else:
            logger.error(f"Error creating platform '{platform_name}': {error_message}")
        return None
    except Exception as e_gen:
        logger.error(f"Unexpected error creating platform '{platform_name}': {e_gen}", exc_info=True)
        return None


def get_or_create_netbox_vlan(nb: pynetbox.api, vlan_id: int, vlan_name_prefix: str = "VLAN_") -> Optional[int]:
    if not nb or not vlan_id:
        return None
    vlan_name = f"{vlan_name_prefix}{vlan_id}"
    vlans = nb.ipam.vlans.filter(vid=vlan_id)
    if vlans:
        return vlans[0].id

    logger.info(f"VLAN VID {vlan_id} (name: {vlan_name}) not found. Creating...")
    try:
        # Considere adicionar 'site': site_id se necessário para sua configuração NetBox
        created_vlan = nb.ipam.vlans.create(name=vlan_name, vid=vlan_id)
        return created_vlan.id
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error creating VLAN VID {vlan_id}: {e.error if hasattr(e, 'error') else e}")
        return None


def get_or_create_and_assign_netbox_mac_address(
    nb: pynetbox.api,
    mac_str: str,
    assign_to_interface_id: Optional[int] = None,
    assigned_object_type: Optional[str] = None,  # Added parameter for object type
) -> Optional[pynetbox.core.response.Record]:
    if not nb or not mac_str:
        return None
    mac_str_upper = mac_str.upper()

    try:
        # Step 1: Find all MAC objects with this string.
        # We cannot filter by assignment directly due to the API error observed.
        mac_objects_from_filter = list(nb.dcim.mac_addresses.filter(mac_address=mac_str_upper))
        logger.debug(
            f"Searching for MAC '{mac_str_upper}'. Filter (by mac_address only) returned {len(mac_objects_from_filter)} objects."
        )

        # Step 2: Iterate through found object summaries and fetch full object to check assignment.
        if assign_to_interface_id and assigned_object_type:
            target_assigned_object_type_lower = assigned_object_type.lower() if assigned_object_type else ""

            for obj_summary_idx, obj_summary in enumerate(mac_objects_from_filter):
                logger.debug(
                    f"  Fetching full MAC Obj {obj_summary_idx + 1}/{len(mac_objects_from_filter)} (Summary ID: {obj_summary.id}) for assignment check to Interface ID {assign_to_interface_id}"
                )
                try:
                    obj = nb.dcim.mac_addresses.get(obj_summary.id)  # Fetch the full object
                    if not obj:
                        logger.warning(f"    Failed to fetch full MAC object for ID {obj_summary.id}. Skipping.")
                        continue
                except pynetbox.core.query.RequestError as e_get:
                    logger.warning(f"    Error fetching full MAC object for ID {obj_summary.id}: {e_get}. Skipping.")
                    continue

                logger.debug(f"    Inspecting FULL MAC Obj (ID: {obj.id}, MAC: {getattr(obj, 'mac_address', 'N/A')})")

                # Check the mac_address string itself (on the full object)
                if not (hasattr(obj, "mac_address") and obj.mac_address and obj.mac_address.upper() == mac_str_upper):
                    logger.warning(
                        f"    FULL MAC Object ID {obj.id} has mismatching mac_address '{getattr(obj, 'mac_address', 'N/A')}' (expected '{mac_str_upper}'). Skipping."
                    )
                    continue

                # Now, use the direct assigned_object_id and assigned_object_type fields from the full 'obj'
                if (
                    hasattr(obj, "assigned_object_id")
                    and obj.assigned_object_id is not None
                    and hasattr(obj, "assigned_object_type")
                    and obj.assigned_object_type is not None
                ):
                    assigned_obj_id = obj.assigned_object_id
                    # obj.assigned_object_type is already the content type string, e.g., "dcim.interface"
                    assigned_obj_content_type_from_mac_obj = str(obj.assigned_object_type).lower()

                    logger.debug(
                        f"    FULL MAC Obj ID {obj.id} direct assignment fields: assigned_object_id={assigned_obj_id}, assigned_object_type='{assigned_obj_content_type_from_mac_obj}'"
                    )
                    if target_assigned_object_type_lower:  # Ensure we have a target type to compare against
                        logger.debug(
                            f"    Comparing with target: interface_id={assign_to_interface_id}, type='{target_assigned_object_type_lower}'"
                        )

                        if (
                            assigned_obj_id == assign_to_interface_id
                            and assigned_obj_content_type_from_mac_obj == target_assigned_object_type_lower
                        ):
                            logger.info(
                                f"MAC Address '{mac_str_upper}' (ID: {obj.id}) is already correctly assigned to interface ID {assign_to_interface_id} (Type: {assigned_object_type}) using direct fields from full object. Reusing."
                            )
                            return obj
                    else:
                        logger.debug(
                            f"    FULL MAC Obj ID {obj.id}: Target assigned_object_type is not specified for comparison, cannot confirm assignment."
                        )
                else:
                    logger.debug(
                        f"    FULL MAC Obj ID {obj.id}: Missing assigned_object_id or assigned_object_type on full object."
                    )

            # If the loop finishes, no correctly assigned MAC object was found.
            logger.debug(
                f"No existing MAC Address object for '{mac_str_upper}' found already assigned to interface ID {assign_to_interface_id} after checking {len(mac_objects_from_filter)} full objects."
            )

        # Step 3 (was Step 3): If no MAC object with this string is currently assigned to THIS interface, create a new one.
        # This is true even if other MACAddress objects with the same string exist but are for other interfaces.
        log_interface_info = (
            f"interface ID {assign_to_interface_id} (Type: {assigned_object_type})"
            if assign_to_interface_id
            else "an unassigned context"
        )
        logger.info(
            f"MAC Address '{mac_str_upper}' is not currently assigned to {log_interface_info}. Creating a new MACAddress object for this assignment."
        )

        # Attempt to create the new MACAddress object
        try:
            created_mac_obj = nb.dcim.mac_addresses.create(mac_address=mac_str_upper)
            if not created_mac_obj:
                logger.error(
                    f"Failed to create new MAC Address object for '{mac_str_upper}'. Create call returned None/False."
                )
                return None

            logger.info(
                f"Successfully created new MAC Address object ID: {created_mac_obj.id} for MAC: {mac_str_upper}."
            )

            # Step 4 (was Step 4): Assign the newly created MACAddress object to the interface, if an interface ID is provided.
            if assign_to_interface_id and assigned_object_type:
                obj_type_to_assign = assigned_object_type  # Should be correctly passed by caller
                logger.info(
                    f"Assigning newly created MAC {mac_str_upper} (ID: {created_mac_obj.id}) to interface ID: {assign_to_interface_id} (Type: {obj_type_to_assign})"
                )
                update_payload = {
                    "assigned_object_type": obj_type_to_assign,
                    "assigned_object_id": assign_to_interface_id,
                }
                try:
                    if not created_mac_obj.update(update_payload):
                        logger.warning(
                            f"Failed to assign newly created MAC {mac_str_upper} (ID: {created_mac_obj.id}) to interface {assign_to_interface_id} (update() returned False)."
                        )
                        # The MAC object is created but not assigned. The caller might still try to use it.
                except pynetbox.core.query.RequestError as e_assign:
                    err_msg_assign = e_assign.error if hasattr(e_assign, "error") else str(e_assign)
                    logger.error(
                        f"Error assigning newly created MAC {mac_str_upper} (ID: {created_mac_obj.id}) to interface {assign_to_interface_id}: {err_msg_assign}"
                    )
                    # If assignment fails, we might not want to return the MAC object as it's not in the desired state.
                    return None

            return created_mac_obj  # Return the newly created (and possibly assigned) MAC object.

        except pynetbox.core.query.RequestError as e_create:
            # This handles errors from the nb.dcim.mac_addresses.create() call itself.
            error_str = str(e_create.error if hasattr(e_create, "error") else e_create).lower()
            logger.error(
                f"NetBox API error during CREATION of new MACAddress object for '{mac_str_upper}': {error_str}"
            )
            # If creation failed due to unique constraint, it means filter failed to find it,
            # but creation says it exists. This is a data inconsistency or filter issue.
            # We should try to find it again by MAC string only and log a warning.
            if (
                "unique constraint" in error_str
                or "already exists" in error_str
                or "mac address with this address already exists" in error_str
            ):
                logger.warning(
                    f"Creation of MAC '{mac_str_upper}' failed due to uniqueness. Attempting to re-fetch by MAC string only."
                )
                mac_objects_retry_filter = list(nb.dcim.mac_addresses.filter(mac_address=mac_str_upper))
                if mac_objects_retry_filter:
                    found_mac_obj_on_retry = mac_objects_retry_filter[0]
                    if len(mac_objects_retry_filter) > 1:
                        logger.warning(
                            f"MAC Address '{mac_str_upper}' has multiple objects in NetBox ({len(mac_objects_retry_filter)} found on re-fetch). Using the first one (ID: {found_mac_obj_on_retry.id})."
                        )
                    logger.info(
                        f"Re-fetch successful after unique constraint error. Found existing MAC '{mac_str_upper}' with ID: {found_mac_obj_on_retry.id}."
                    )
                    # Note: This object is NOT assigned to the target interface based on the initial check.
                    # The most reliable path is to fail this MAC assignment for this interface if creation fails due to uniqueness
                    # and the initial filter didn't find a correctly assigned one.
                    logger.error(
                        f"MAC '{mac_str_upper}' exists (ID: {found_mac_obj_on_retry.id}) but is not assigned to interface ID {assign_to_interface_id} (as per initial check). Cannot create a new one due to uniqueness. Skipping MAC assignment for this interface."
                    )
                    return None  # Indicate failure to get/create/assign the MAC object for this interface.
                else:
                    logger.error(
                        f"Re-fetch for MAC '{mac_str_upper}' failed to find an exact match even after unique constraint error on create. NetBox data might be inconsistent or filter is unreliable. Skipping MAC assignment for this interface."
                    )
                    return None
            else:  # Other creation error not related to uniqueness
                return None
        except Exception as e_generic_create:
            logger.error(
                f"Unexpected error during MAC creation block for '{mac_str_upper}': {e_generic_create}", exc_info=True
            )
            return None

    except Exception as e_outer:
        logger.error(
            f"Unexpected error in get_or_create_and_assign_netbox_mac_address (outer block) for '{mac_str_upper}': {e_outer}",
            exc_info=True,
        )
        return None


def get_or_create_site(
    nb: pynetbox.api, site_name: str, site_slug: Optional[str] = None
) -> Optional[pynetbox.core.response.Record]:
    if not nb or not site_name:
        return None
    site = nb.dcim.sites.get(name=site_name)
    if site:
        return site

    slug = site_slug or site_name.lower().replace(" ", "-")
    site_by_slug = nb.dcim.sites.get(slug=slug)
    if site_by_slug:
        return site_by_slug

    logger.info(f"Site '{site_name}' not found. Creating with slug '{slug}'...")
    try:
        return nb.dcim.sites.create(name=site_name, slug=slug, status="active")  # status pode ser configurável
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error creating site '{site_name}': {e.error if hasattr(e, 'error') else e}")
        return None


def get_or_create_manufacturer(
    nb: pynetbox.api, manu_name: str, manu_slug: Optional[str] = None
) -> Optional[pynetbox.core.response.Record]:
    if not nb or not manu_name:
        return None
    manufacturer = nb.dcim.manufacturers.get(name=manu_name)
    if manufacturer:
        return manufacturer

    slug = manu_slug or manu_name.lower().replace(" ", "-").replace(".", "")
    manu_by_slug = nb.dcim.manufacturers.get(slug=slug)
    if manu_by_slug:
        return manu_by_slug

    logger.info(f"Manufacturer '{manu_name}' not found. Creating with slug '{slug}'...")  # "Creating..."
    try:
        return nb.dcim.manufacturers.create(name=manu_name, slug=slug)
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error creating manufacturer '{manu_name}': {e.error if hasattr(e, 'error') else e}")
        return None


def get_or_create_device_type(
    nb: pynetbox.api, model_name: str, manufacturer_id: int, dt_slug: Optional[str] = None, u_height: int = 1
) -> Optional[pynetbox.core.response.Record]:
    if not nb or not model_name or not manufacturer_id:
        return None
    # NetBox DeviceType é único por manufacturer E (model OU slug)
    device_type = nb.dcim.device_types.get(model=model_name, manufacturer_id=manufacturer_id)
    if device_type:
        return device_type

    slug = dt_slug or model_name.lower().replace(" ", "-")
    dt_by_slug = nb.dcim.device_types.get(slug=slug, manufacturer_id=manufacturer_id)
    if dt_by_slug:
        return dt_by_slug

    logger.info(
        f"Device Type '{model_name}' (Manufacturer ID: {manufacturer_id}) not found. Creating with slug '{slug}'..."
    )  # "Creating..."
    try:
        return nb.dcim.device_types.create(
            model=model_name,
            slug=slug,
            manufacturer=manufacturer_id,
            u_height=u_height,  # Default para 1U, pode ser configurável
            is_full_depth=True,  # Default, pode ser configurável
        )
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error creating Device Type '{model_name}': {e.error if hasattr(e, 'error') else e}")
        return None


def get_or_create_device_role(
    nb: pynetbox.api, role_name: str, role_slug: Optional[str] = None, color_hex: str = "00bcd4"
) -> Optional[pynetbox.core.response.Record]:
    if not nb or not role_name:
        return None
    device_role = nb.dcim.device_roles.get(name=role_name)
    if device_role:
        return device_role

    slug = role_slug or role_name.lower().replace(" ", "-")
    role_by_slug = nb.dcim.device_roles.get(slug=slug)
    if role_by_slug:
        return role_by_slug

    logger.info(f"Device Role '{role_name}' not found. Creating with slug '{slug}'...")  # "Creating..."
    try:
        return nb.dcim.device_roles.create(
            name=role_name, slug=slug, color=color_hex, vm_role=False
        )  # vm_role=False para papéis de dispositivo físico/virtual
    except pynetbox.core.query.RequestError as e:
        logger.error(f"Error creating Device Role '{role_name}': {e.error if hasattr(e, 'error') else e}")
        return None


def get_or_create_device_interface(
    nb: pynetbox.api,
    device_id: int,
    iface_name: str,
    iface_type: str,  # ex: '1000base-t', 'lag', 'bridge', 'virtual'
    mac_address: Optional[str] = None,
    enabled: bool = True,
    mtu: Optional[int] = None,
    description: Optional[str] = None,
    custom_fields: Optional[Dict[str, Any]] = None,
) -> Optional[pynetbox.core.response.Record]:
    if not nb or not device_id or not iface_name or not iface_type:
        return None

    # Tenta buscar por nome e device_id
    existing_iface = nb.dcim.interfaces.get(device_id=device_id, name=iface_name)
    if existing_iface:
        # Atualizar se necessário (ex: MAC, tipo, enabled, custom_fields)
        update_payload = {}

        # Do NOT set mac_address string field directly here.
        # It will be populated by NetBox when primary_mac_address (MACAddress object) is linked.
        # logger.debug(f"Interface '{iface_name}': MAC string field will be set by NetBox upon primary_mac_address link.")

        if existing_iface.type != iface_type:
            update_payload["type"] = iface_type
        if existing_iface.enabled != enabled:
            update_payload["enabled"] = enabled
        if description and existing_iface.description != description:
            update_payload["description"] = description
        if custom_fields and existing_iface.custom_fields != custom_fields:
            update_payload["custom_fields"] = custom_fields
        # Adicionar mais campos se necessário (mtu, etc.)
        if update_payload:  # If there are changes, update the interface
            logger.info(
                f"Updating interface '{iface_name}' (ID: {existing_iface.id}) on device ID {device_id}. Payload: {update_payload}"
            )

            # Log the state before the update attempt
            logger.debug(
                f"Interface '{iface_name}' (ID: {existing_iface.id}) before update (excluding MAC string): Type='{existing_iface.type}', Enabled={existing_iface.enabled}, Desc='{existing_iface.description}', CF={existing_iface.custom_fields}"
            )

            try:
                existing_iface.update(update_payload)

                # Re-fetch the interface to check its state immediately after update
                try:  # Inner try for re-fetching
                    refetched_iface = nb.dcim.interfaces.get(existing_iface.id)  # Re-fetch to get the latest state
                    if refetched_iface:
                        logger.debug(
                            f"Interface '{iface_name}' (ID: {existing_iface.id}) after update (excluding MAC string): Type='{refetched_iface.type}', Enabled={refetched_iface.enabled}, Desc='{existing_iface.description}', CF={existing_iface.custom_fields}. MAC string should be set by primary_mac_address link."
                        )
                    else:
                        logger.warning(f"Could not re-fetch interface {existing_iface.id} after update.")
                except pynetbox.core.query.RequestError as e_refetch:
                    logger.warning(f"Error re-fetching interface {existing_iface.id} after update: {e_refetch}")

            except pynetbox.core.query.RequestError as e:  # Handles errors from existing_iface.update()
                error_message = e.error if hasattr(e, "error") else str(e)
                logger.error(
                    f"Error updating interface '{iface_name}' (ID: {existing_iface.id}) for device ID {device_id}: {error_message}"
                )
        return existing_iface

    logger.info(f"Interface '{iface_name}' not found on device ID {device_id}. Creating...")
    create_payload = {"device": device_id, "name": iface_name, "type": iface_type, "enabled": enabled}
    # Do NOT set mac_address string field directly here.
    # It will be populated by NetBox when primary_mac_address (MACAddress object) is linked.

    if mtu:
        create_payload["mtu"] = mtu
    if description:
        create_payload["description"] = description
    if custom_fields:
        create_payload["custom_fields"] = custom_fields
    try:
        return nb.dcim.interfaces.create(**create_payload)
    except pynetbox.core.query.RequestError as e:
        logger.error(
            f"Error creating interface '{iface_name}' for device ID {device_id}: {e.error if hasattr(e, 'error') else e}"
        )
        return None
