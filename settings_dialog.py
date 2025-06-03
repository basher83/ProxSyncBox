import sys
import logging
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QSizePolicy,
    QMessageBox, QCheckBox, QDialogButtonBox, QLabel, QScrollArea
)
from PyQt6.QtCore import Qt
from typing import Optional, List, Tuple, cast, Type # Added cast and Type for better type hinting

from config_models import GlobalSettings, ProxmoxNodeConfig # Para type hinting e defaults
from dataclasses import fields, asdict

logger = logging.getLogger(__name__)

class NodeEditDialog(QDialog):
    def __init__(self, node_config: Optional[ProxmoxNodeConfig] = None, existing_node_ids: list = None, parent=None):
        """
        Dialog for adding or editing a ProxmoxNodeConfig.
        Dynamically generates form fields based on the ProxmoxNodeConfig dataclass.

        Args:
            node_config: The ProxmoxNodeConfig to edit, or None to add a new one.
            existing_node_ids: A list of existing node ID names to prevent duplicates.
            parent: The parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Edit Proxmox Node" if node_config else "Add Proxmox Node") 
        self.setMinimumWidth(500)

        self.existing_node_ids = existing_node_ids or []
        self.original_id_name = node_config.id_name if node_config else None
        self.node_data = node_config if node_config else ProxmoxNodeConfig(
            id_name="", host="", node_name="", user="", token_name="", token_secret="", netbox_cluster_name=""
        ) # Provide default values for mandatory fields
        
        self.fields_widgets = {}
        self.ssh_related_widgets_names = [
            "ssh_host",
            "ssh_port",
            "ssh_user",
            "ssh_password",
            "ssh_key_path"
        ]

        main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        # Explicitly set how fields should grow
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Iterate over the fields of the ProxmoxNodeConfig dataclass to create form inputs
        for field_info in fields(ProxmoxNodeConfig):
            label = field_info.name.replace("_", " ").title()
            label_widget = QLabel(label + ":")
            current_value = getattr(self.node_data, field_info.name, field_info.default)
            tooltip_text = ""

            if field_info.type == bool:
                widget = QCheckBox()
                widget.setChecked(bool(current_value) if current_value is not None else False)
                if field_info.name == "enable_ssh_mac_fetch":
                    tooltip_text = "Enable fetching MAC addresses via SSH if Proxmox API doesn't provide them. Requires SSH fields below to be configured."
                    widget.stateChanged.connect(self._toggle_ssh_fields_enabled)
                elif field_info.name == "verify_ssl":
                    tooltip_text = "Check this box to enable SSL certificate verification for the Proxmox API connection. Uncheck for self-signed certificates (less secure)."
            else:
                widget = QLineEdit()
                widget.setText(str(current_value) if current_value is not None else "")
                if field_info.name == "id_name" and self.original_id_name:
                    widget.setReadOnly(True) # Make id_name non-editable for existing nodes
                    tooltip_text = "Unique identifier for this configuration. Cannot be changed for existing nodes."
                # Allow QLineEdit to expand horizontally
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                if field_info.name == "id_name":
                    tooltip_text = "A unique identifier for this Proxmox node configuration (e.g., 'pve-cluster-main', 'lab-node1'). Cannot be changed after creation through this edit dialog if it's an existing node."
                elif field_info.name == "host":
                    tooltip_text = "The hostname or IP address of the Proxmox VE server (e.g., 'proxmox.example.com' or '192.168.1.100')."
                elif field_info.name == "node_name":
                    tooltip_text = "The actual node name as defined in Proxmox (e.g., 'pve1', 'nodexyz'). This is used in API calls."
                elif field_info.name == "user":
                    tooltip_text = "Proxmox user for API authentication (e.g., 'root@pam' or 'apiuser@pve')."
                elif field_info.name == "token_name":
                    tooltip_text = "The name of the API token created in Proxmox for this user."
                elif field_info.name == "token_secret":
                    tooltip_text = "The secret value of the API token."
                elif field_info.name == "netbox_cluster_name":
                    tooltip_text = "The name of the NetBox Cluster where VMs/LXCs from this Proxmox node will be grouped. If left empty, defaults to the Proxmox 'Node Name'."
                elif "netbox_node_" in field_info.name: # Tooltips for node-as-device fields
                    tooltip_text = f"NetBox {label.replace('Netbox Node ', '')} for representing this Proxmox node as a Device in NetBox."
                elif field_info.name == "ssh_host":
                    tooltip_text = "Hostname or IP for SSH connection. Defaults to Proxmox API host if empty."
                elif field_info.name == "ssh_port":
                    tooltip_text = "SSH port for the Proxmox node (default: 22)."
                elif field_info.name == "ssh_user":
                    tooltip_text = "Username for SSH connection to the Proxmox node (e.g., 'root')."
            
            self.fields_widgets[field_info.name] = widget
            if tooltip_text:
                widget.setToolTip(tooltip_text)
                label_widget.setToolTip(tooltip_text) # Also set tooltip on label for better discoverability
            form_layout.addRow(label_widget, widget)
        
        # Add a QScrollArea for the form if it's too large
        scroll_area = QScrollArea()
        scroll_content = QWidget()
        scroll_content.setLayout(form_layout)
        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept_data)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)
        self._toggle_ssh_fields_enabled() # Set initial state of SSH fields

    def _toggle_ssh_fields_enabled(self):
        """
        Enables or disables SSH-related input fields based on the
        'enable_ssh_mac_fetch' checkbox.
        """
        enable_ssh_cb = self.fields_widgets.get("enable_ssh_mac_fetch")
        if not isinstance(enable_ssh_cb, QCheckBox): return

        is_enabled = enable_ssh_cb.isChecked()
        for field_name in self.ssh_related_widgets_names:
            widget = self.fields_widgets.get(field_name)
            if widget:
                widget.setEnabled(is_enabled)
    def accept_data(self):
        """
        Validates the form data and, if valid, updates self.node_data and accepts the dialog.
        """
        # Basic validation: id_name cannot be empty and must be unique if new, or same as original if editing.
        id_name_widget = self.fields_widgets.get("id_name")
        if id_name_widget:
            new_id_name = id_name_widget.text().strip()
            if not new_id_name:
                QMessageBox.warning(self, "Validation Error", "Node ID Name cannot be empty.") 
                return
            # Only check for uniqueness if it's a new node or if the ID name has been changed (which is now disallowed for existing)
            if not self.original_id_name and new_id_name in self.existing_node_ids:
                QMessageBox.warning(self, "Validation Error", f"Node ID Name '{new_id_name}' already exists.") 
                return
        
        # Collect data from widgets
        updated_data = {}
        for field_name, widget in self.fields_widgets.items():
            if isinstance(widget, QCheckBox):
                updated_data[field_name] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                text_value = widget.text()
                
                # Get the type hint for the field
                field_type_hint = ProxmoxNodeConfig.__annotations__.get(field_name)

                # Convert to int if the field type is int (e.g. ssh_port)
                if (str(field_type_hint) == "typing.Optional[int]" or str(field_type_hint) == "Optional[int]" or str(field_type_hint) == "int") and text_value:
                    try: updated_data[field_name] = int(text_value); continue
                    except ValueError: QMessageBox.warning(self, "Validation Error", f"Invalid integer value for {field_name.replace('_', ' ').title()}: {text_value}"); return
                
                # Handle empty strings for optional fields
                is_optional_str = (str(field_type_hint).startswith("typing.Optional[str]") or \
                                   str(field_type_hint).startswith("Optional[str]"))

                if text_value == "":
                    if is_optional_str:
                        updated_data[field_name] = None # Set to None for empty optional strings
                    else:
                        # For non-string optional fields or mandatory fields, an empty string might be an issue
                        # or might need to be converted to a default (e.g., 0 for int if applicable).
                        # For simplicity, we'll pass the empty string; dataclass validation might catch it
                        # or it might be implicitly converted if the type allows (e.g. bool('') is False).
                        # If a field is mandatory and not bool, ProxmoxNodeConfig instantiation will fail if empty.
                        updated_data[field_name] = text_value 
                else:
                    updated_data[field_name] = text_value

        try:
            self.node_data = ProxmoxNodeConfig(**updated_data)
            self.accept()
        except TypeError as e:
            QMessageBox.critical(self, "Configuration Error", f"Error creating node configuration: {e}\nData: {updated_data}")
        except Exception as e_gen:
            QMessageBox.critical(self, "Unexpected Error", f"An unexpected error occurred: {e_gen}")


    def get_node_data(self) -> Optional[ProxmoxNodeConfig]:
        """Returns the ProxmoxNodeConfig object created or edited by the dialog."""
        return self.node_data


class SettingsDialog(QDialog):
    def __init__(self, global_settings: GlobalSettings, node_configs: List[ProxmoxNodeConfig], parent=None):
        """
        Main settings dialog with tabs for Global settings and Proxmox Node management.

        Args:
            global_settings: The current GlobalSettings object.
            node_configs: A list of current ProxmoxNodeConfig objects.
            parent: The parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Application Settings") 
        self.setMinimumSize(700, 500)

        self.current_global_settings = global_settings
        self.current_node_configs = {node.id_name: node for node in node_configs} # Usar dict para fácil acesso/modificação

        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        # Ensure QTabWidget can expand
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # --- Global Settings Tab ---
        self.global_tab = QWidget()
        global_layout = QFormLayout(self.global_tab)
        self.global_widgets = {}
        # Explicitly set how fields should grow in the form layout
        global_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.global_widgets["netbox_url"] = QLineEdit(self.current_global_settings.netbox_url)
        self.global_widgets["netbox_url"].setToolTip("The base URL of your NetBox instance (e.g., http://netbox.example.com or https://netbox.example.com:8000).")
        self.global_widgets["netbox_url"].setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        netbox_url_label = QLabel("NetBox URL:")
        netbox_url_label.setToolTip("The base URL of your NetBox instance (e.g., http://netbox.example.com or https://netbox.example.com:8000).")
        global_layout.addRow(netbox_url_label, self.global_widgets["netbox_url"])

        self.global_widgets["netbox_token"] = QLineEdit(self.current_global_settings.netbox_token)
        self.global_widgets["netbox_token"].setEchoMode(QLineEdit.EchoMode.Password)
        self.global_widgets["netbox_token"].setToolTip("Your NetBox API token. Ensure it has the necessary permissions to create/update/delete virtualization and DCIM objects.")
        self.global_widgets["netbox_token"].setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        netbox_token_label = QLabel("NetBox Token:")
        netbox_token_label.setToolTip("Your NetBox API token. Ensure it has the necessary permissions to create/update/delete virtualization and DCIM objects.")
        global_layout.addRow(netbox_token_label, self.global_widgets["netbox_token"])

        self.global_widgets["netbox_cluster_type_name"] = QLineEdit(self.current_global_settings.netbox_cluster_type_name)
        self.global_widgets["netbox_cluster_type_name"].setToolTip("The name of the NetBox Cluster Type to use for Proxmox clusters (e.g., 'Proxmox VE', 'oVirt'). This type will be created if it doesn't exist.")
        self.global_widgets["netbox_cluster_type_name"].setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        netbox_cluster_type_label = QLabel("NetBox Default Cluster Type Name:")
        netbox_cluster_type_label.setToolTip("The name of the NetBox Cluster Type to use for Proxmox clusters (e.g., 'Proxmox VE', 'oVirt'). This type will be created if it doesn't exist.")
        global_layout.addRow(netbox_cluster_type_label, self.global_widgets["netbox_cluster_type_name"])

        self.tab_widget.addTab(self.global_tab, "Global Settings")

        # --- Proxmox Nodes Tab ---
        self.proxmox_tab = QWidget()
        proxmox_layout = QHBoxLayout(self.proxmox_tab)
        
        self.node_list_widget = QListWidget()
        self.node_list_widget.setToolTip("List of configured Proxmox nodes. Select a node to edit or remove it.")
        self.populate_node_list()
        proxmox_layout.addWidget(self.node_list_widget)

        # Buttons for node management
        node_buttons_layout = QVBoxLayout()
        add_node_button = QPushButton("Add Node") 
        add_node_button.setToolTip("Add a new Proxmox node configuration.")
        add_node_button.clicked.connect(self.add_node)
        node_buttons_layout.addWidget(add_node_button)

        edit_node_button = QPushButton("Edit Node") 
        edit_node_button.setToolTip("Edit the selected Proxmox node configuration.")
        edit_node_button.clicked.connect(self.edit_node)
        node_buttons_layout.addWidget(edit_node_button)

        remove_node_button = QPushButton("Remove Node") 
        remove_node_button.setToolTip("Remove the selected Proxmox node configuration.")
        remove_node_button.clicked.connect(self.remove_node)
        node_buttons_layout.addWidget(remove_node_button)
        node_buttons_layout.addStretch()
        proxmox_layout.addLayout(node_buttons_layout)
        self.tab_widget.addTab(self.proxmox_tab, "Proxmox Nodes")

        # Save/Cancel buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.button(QDialogButtonBox.StandardButton.Save).setToolTip("Save all changes made in the settings dialog.")
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setToolTip("Discard all changes and close the dialog.")
        self.button_box.accepted.connect(self.save_settings)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def populate_node_list(self):
        """Clears and repopulates the list widget with Proxmox node IDs."""
        self.node_list_widget.clear()
        for node_id in sorted(self.current_node_configs.keys()):
            self.node_list_widget.addItem(QListWidgetItem(node_id))


    def add_node(self):
        dialog = NodeEditDialog(existing_node_ids=list(self.current_node_configs.keys()), parent=self)
        if dialog.exec():
            new_node_data = dialog.get_node_data()
            if new_node_data:
                self.current_node_configs[new_node_data.id_name] = new_node_data
                self.populate_node_list()

    def edit_node(self):
        selected_item = self.node_list_widget.currentItem()
        if not selected_item:
            QMessageBox.information(self, "No Selection", "Please select a node to edit.")
            return
        
        node_id_to_edit = selected_item.text()
        node_to_edit = self.current_node_configs.get(node_id_to_edit)
        if not node_to_edit: return

        dialog = NodeEditDialog(node_config=node_to_edit, existing_node_ids=list(self.current_node_configs.keys()), parent=self)
        if dialog.exec():
            updated_node_data = dialog.get_node_data()
            if updated_node_data:
                # If the ID changed, need to remove the old one and add the new one
                if node_id_to_edit != updated_node_data.id_name and node_id_to_edit in self.current_node_configs:
                    del self.current_node_configs[node_id_to_edit]
                self.current_node_configs[updated_node_data.id_name] = updated_node_data
                self.populate_node_list()

    def remove_node(self):
        selected_item = self.node_list_widget.currentItem()
        if not selected_item:
            QMessageBox.information(self, "No Selection", "Please select a node to remove.")
            return
        
        node_id_to_remove = selected_item.text()
        reply = QMessageBox.question(self, "Confirm Removal", 
                                     f"Are you sure you want to remove the node configuration for '{node_id_to_remove}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if node_id_to_remove in self.current_node_configs:
                del self.current_node_configs[node_id_to_remove]
                self.populate_node_list()

    def save_settings(self):
        """Collects data from global settings widgets and accepts the dialog."""
        # Update global_settings from widgets
        self.current_global_settings.netbox_url = self.global_widgets["netbox_url"].text()
        self.current_global_settings.netbox_token = self.global_widgets["netbox_token"].text()
        self.current_global_settings.netbox_cluster_type_name = self.global_widgets["netbox_cluster_type_name"].text()
        self.accept()

    def get_settings(self) -> Tuple[GlobalSettings, List[ProxmoxNodeConfig]]:
        """Returns the updated global settings and list of node configurations."""
        return self.current_global_settings, list(self.current_node_configs.values())

# Example of how to use (for independent test):
if __name__ == '__main__':
    app = QApplication(sys.argv)
    # Mock data for test
    mock_global_settings = GlobalSettings(netbox_url="http://localhost:8000", netbox_token="testtoken")
    mock_node_configs = [
        ProxmoxNodeConfig(id_name="pve1", host="192.168.1.10", node_name="pve1", user="root@pam", token_name="api", token_secret="secret1", netbox_cluster_name="cluster1"),
        ProxmoxNodeConfig(id_name="pve2", host="192.168.1.11", node_name="pve2", user="root@pam", token_name="api", token_secret="secret2", netbox_cluster_name="cluster2", netbox_node_site_name="SiteA")
    ]
    dialog = SettingsDialog(mock_global_settings, mock_node_configs)
    if dialog.exec():
        gs, ncs = dialog.get_settings()
        print("Global Settings:", gs)
        for nc in ncs:
            print("Node Config:", asdict(nc))
    sys.exit(app.exec())
