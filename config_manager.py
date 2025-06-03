import os
import sys # To determine the application directory
import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import fields, is_dataclass # To iterate over dataclass fields
from dotenv import dotenv_values, set_key, unset_key # Using set_key/unset_key for initial simplicity

# Import ProxmoxNodeConfig to know its fields
from config_models import ProxmoxNodeConfig # Import from the new models file


logger = logging.getLogger(__name__)

# Determine the application directory path
# If running as a script, __file__ works.
# If packaged with PyInstaller, sys.executable is more reliable.
if getattr(sys, 'frozen', False):
    # Application is packaged
    APP_DIR = os.path.dirname(sys.executable)
else:
    # Application is running as a script
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

DOTENV_PATH = os.path.join(APP_DIR, ".env")
logger.debug(f".env file path determined: {DOTENV_PATH}")


# Expected global keys in .env
GLOBAL_CONFIG_KEYS = ["NETBOX_URL", "NETBOX_TOKEN", "NETBOX_CLUSTER_TYPE_NAME", "LOG_LEVEL"] # Added LOG_LEVEL
PROXMOX_NODE_PREFIX = "PROXMOX_NODE_"

def load_all_settings() -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """
    Loads all settings from the .env file.
    Returns a tuple: (global_settings, all_node_settings_raw)
    """
    if not os.path.exists(DOTENV_PATH):
        logger.warning(f".env file not found at '{DOTENV_PATH}'. Creating an empty one.")
        open(DOTENV_PATH, 'a').close() # Create the file if it doesn't exist

    env_values = dotenv_values(DOTENV_PATH)
    
    global_settings: Dict[str, Any] = {}
    all_node_settings_raw: Dict[str, Dict[str, Any]] = {}

    for key, value in env_values.items():
        if key in GLOBAL_CONFIG_KEYS:
            global_settings[key] = value
        elif key.startswith(PROXMOX_NODE_PREFIX):
            try:
                parts = key[len(PROXMOX_NODE_PREFIX):].split('_', 1)
                if len(parts) == 2:
                    node_id_key = parts[0]
                    param_name = parts[1].lower() # Node parameters are stored in lowercase internally

                    if node_id_key not in all_node_settings_raw:
                        all_node_settings_raw[node_id_key] = {}
                    all_node_settings_raw[node_id_key][param_name] = value
            except Exception as e:
                logger.error(f"Error parsing Proxmox node configuration key '{key}': {e}")
                
    return global_settings, all_node_settings_raw

def save_setting(key: str, value: Optional[str]):
    """Saves or removes a single setting in the .env file."""
    if value is None or value == "":
        logger.debug(f"Removing key '{key}' from .env file.")
        unset_key(DOTENV_PATH, key, quote_mode="never")
    else:
        logger.debug(f"Saving key '{key}' with value '{value}' in .env file.")
        set_key(DOTENV_PATH, key, value, quote_mode="never")

def save_all_settings(global_settings: Dict[str, Any], node_configs: List[ProxmoxNodeConfig]):
    """
    Saves all provided settings to the .env file, overwriting it.
    This method is more robust for removing nodes or node parameters that no longer exist.
    """
    logger.info(f"Rewriting the .env file at: {DOTENV_PATH}")
    lines_to_write = []

    # Save global settings
    for key in GLOBAL_CONFIG_KEYS:
        value = global_settings.get(key)
        if value is not None and value != "": # Do not save empty global keys explicitly
            lines_to_write.append(f"{key}={value}")
    
    lines_to_write.append("\n# Proxmox Node Configurations")
    # Save node configurations
    for node_config in node_configs:
        node_id = node_config.id_name
        lines_to_write.append(f"\n# Node: {node_id}")
        for f_field in fields(node_config):
            param_name_env = f_field.name.upper()
            env_key = f"{PROXMOX_NODE_PREFIX}{node_id}_{param_name_env}"
            value = getattr(node_config, f_field.name)

            if isinstance(value, bool):
                value_str = str(value).lower() # 'true' or 'false'
            elif value is None:
                value_str = "" # Write as an empty key to be ignored on load or removed
            else:
                value_str = str(value)
            
            # Only write if the value is not None (or an empty string for non-booleans)
            # Booleans are always written.
            if value is not None:
                 if not isinstance(value, bool) and value_str == "" and f_field.default is None:
                    # Do not write optional fields that are empty and whose default is None
                    pass
                 else:
                    lines_to_write.append(f"{env_key}={value_str}")


    try:
        with open(DOTENV_PATH, "w") as f:
            for line in lines_to_write:
                f.write(line + "\n")
        logger.info(f".env file saved successfully at '{DOTENV_PATH}'.")
    except IOError as e:
        logger.error(f"Error writing to .env file at '{DOTENV_PATH}': {e}")
