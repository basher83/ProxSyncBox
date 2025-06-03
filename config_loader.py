import os
import logging
from typing import Dict, Any, Optional, Tuple, List

# Import the new manager
from config_manager import load_all_settings as cm_load_all_settings, \
                           save_all_settings as cm_save_all_settings, GLOBAL_CONFIG_KEYS
# Importar modelos de um novo arquivo para evitar importação circular
from config_models import ProxmoxNodeConfig, GlobalSettings

logger = logging.getLogger(__name__)

# These will now be properties of a global configuration class or loaded dynamically
NETBOX_URL: Optional[str] = None
NETBOX_TOKEN: Optional[str] = None
NETBOX_CLUSTER_TYPE_NAME: str = "Proxmox VE" # Default

def load_app_config() -> Tuple[GlobalSettings, Dict[str, ProxmoxNodeConfig]]:
    """
    Loads all application settings (global and node-specific) from the .env file.

    Returns a tuple containing:
    - A GlobalSettings object with global settings.
    - A dictionary mapping node IDs to ProxmoxNodeConfig objects.
    """
    global_settings_raw, all_node_settings_raw = cm_load_all_settings()

    # Process global settings
    gs = GlobalSettings(
        netbox_url=global_settings_raw.get(GLOBAL_CONFIG_KEYS[0]),
        netbox_token=global_settings_raw.get(GLOBAL_CONFIG_KEYS[1]),
        netbox_cluster_type_name=global_settings_raw.get(GLOBAL_CONFIG_KEYS[2], "Proxmox VE")
    )
    
    # Update global variables in the module for compatibility (optional, it's better to access via the GlobalSettings object)
    global NETBOX_URL, NETBOX_TOKEN, NETBOX_CLUSTER_TYPE_NAME
    NETBOX_URL = gs.netbox_url
    NETBOX_TOKEN = gs.netbox_token
    NETBOX_CLUSTER_TYPE_NAME = gs.netbox_cluster_type_name

    # Process node settings
    valid_node_configs: Dict[str, ProxmoxNodeConfig] = {}
    for node_id, params_raw in all_node_settings_raw.items():
        # Converter params_raw para o formato esperado por ProxmoxNodeConfig
        # (ex: booleanos, defaults)
        params_for_dataclass = {"id_name": node_id, **params_raw}

        # Assegurar que todos os campos esperados pelo dataclass tenham um valor ou default
        # Ensure that all fields expected by the dataclass have a value or default
        # The default logic of the ProxmoxNodeConfig dataclass should already handle this
        # if the parameter names in params_raw correspond (ignoring case)
        
        # Convert 'verify_ssl' to boolean
        if 'verify_ssl' in params_for_dataclass and isinstance(params_for_dataclass['verify_ssl'], str):
            params_for_dataclass['verify_ssl'] = params_for_dataclass['verify_ssl'].lower() in ['true', '1', 'yes']
        
        try:
            # Garantir que todos os campos obrigatórios tenham algum valor (mesmo que default do dataclass)
            # O construtor do dataclass ProxmoxNodeConfig já tem defaults para campos opcionais
            config_obj = ProxmoxNodeConfig(**params_for_dataclass)
            valid_node_configs[node_id] = config_obj
        except TypeError as e:
            logger.warning(f"Error instantiating ProxmoxNodeConfig for node '{node_id}': {e}. Skipping. Params: {params_for_dataclass}")
        except Exception as e_gen:
            logger.error(f"Unexpected error while processing node '{node_id}': {e_gen}", exc_info=True)

    return gs, valid_node_configs

def save_app_config(global_settings: GlobalSettings, node_configs: List[ProxmoxNodeConfig]):
    """
    Saves all application settings to the .env file.
    """
    global_settings_dict = {key.upper(): getattr(global_settings, key.lower()) for key in GLOBAL_CONFIG_KEYS if hasattr(global_settings, key.lower())}
    cm_save_all_settings(global_settings_dict, node_configs)