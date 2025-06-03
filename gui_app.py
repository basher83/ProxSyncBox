import sys
import logging
import threading

from PyQt6.QtGui import QAction # Para menu
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QPushButton, QLabel, QScrollArea, QCheckBox, QTextEdit,
    QGroupBox, QMessageBox, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QObject, pyqtSlot as Slot, QThread, pyqtSignal as Signal

from config_loader import load_app_config, save_app_config # Config loader functions
from config_models import ProxmoxNodeConfig, GlobalSettings # Config models
from proxmox_handler import get_proxmox_api_client, fetch_vms_and_lxc, fetch_proxmox_node_details
from netbox_handler import get_netbox_api_client
from sync_orchestrator import sync_to_netbox, mark_orphaned_vms_as_deleted, sync_proxmox_node_to_netbox_device
from utils import QtLogHandler # Changed from TextHandler to QtLogHandler
from settings_dialog import SettingsDialog # Import the settings dialog

class WorkerSignals(QObject):
    finished = Signal()
    error = Signal(str)
    progress = Signal(str) # Para mensagens de progresso/log
    vm_list_ready = Signal(list)
    node_sync_complete = Signal(str)
    sync_complete = Signal(str) # Mensagem de sucesso/falha da sincronização

class ProxmoxToNetboxApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Proxmox to NetBox Sync")
        self.setGeometry(100, 100, 850, 750) # x, y, width, height

        self.global_settings: GlobalSettings | None = None
        self.proxmox_configs: dict[str, ProxmoxNodeConfig] = {}
        self.selected_node_config: ProxmoxNodeConfig | None = None
        self.proxmox_api = None
        self.netbox_api = None
        self.all_proxmox_vms = [] # Stores all VMs/LXCs fetched from the selected Proxmox node

        self.vm_checkboxes_map = {} # Maps VM ID to its QCheckBox widget in the UI

        self._setup_logging()
        self._setup_menu() # Add application menu
        self._setup_ui()
        self._load_initial_configs()

    def _setup_logging(self):
        self.logger = logging.getLogger() # Root logger
        self.logger.setLevel(logging.INFO) # Set base level
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        # GUI log handler that emits Qt signals
        self.qt_log_handler = QtLogHandler()
        self.qt_log_handler.setFormatter(formatter)
        self.logger.addHandler(self.qt_log_handler)
        self.qt_log_handler.new_log_message.connect(self.append_log_message)

    @Slot(str)
    def append_log_message(self, message):
        """Appends a log message to the QTextEdit in the GUI."""
        # This slot is connected to the QtLogHandler's new_log_message signal
        self.log_text_edit.append(message)

    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        settings_action = QAction("&Settings", self)
        settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action)

    def _setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # --- Node Selection Frame ---
        node_groupbox = QGroupBox("Proxmox Node Selection")
        node_layout = QHBoxLayout()
        node_groupbox.setLayout(node_layout)

        select_node_label = QLabel("Select Node:")
        select_node_label.setToolTip("Select a configured Proxmox node to load VMs/LXCs from or sync as a NetBox Device.")
        node_layout.addWidget(select_node_label)
        self.node_combobox = QComboBox()
        self.node_combobox.setFixedWidth(250)
        self.node_combobox.setToolTip("Select a configured Proxmox node from the list.")
        self.node_combobox.currentIndexChanged.connect(self.on_node_selected)
        node_layout.addWidget(self.node_combobox)

        self.edit_node_settings_button = QPushButton("Node Settings")
        self.edit_node_settings_button.setToolTip("Open settings to add/edit/remove Proxmox nodes")
        self.edit_node_settings_button.clicked.connect(self.open_settings_dialog_for_nodes)
        node_layout.addWidget(self.edit_node_settings_button)

        self.load_vms_button = QPushButton("Load VMs/LXCs")
        self.load_vms_button.setEnabled(False)
        self.load_vms_button.setToolTip("Fetch the list of Virtual Machines and LXC Containers from the selected Proxmox node.")
        self.load_vms_button.clicked.connect(self.start_load_vms_thread)
        node_layout.addWidget(self.load_vms_button)

        self.sync_node_to_device_button = QPushButton("Sync Node to NetBox Device")
        self.sync_node_to_device_button.setEnabled(False)
        self.sync_node_to_device_button.setToolTip("Synchronize the selected Proxmox node itself as a Device in NetBox, including its interfaces.")
        self.sync_node_to_device_button.clicked.connect(self.start_sync_node_to_device_thread)
        node_layout.addWidget(self.sync_node_to_device_button)

        node_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)) # Spacer
        main_layout.addWidget(node_groupbox)

        # --- VM/LXC Selection Frame ---
        vm_groupbox = QGroupBox("VM/LXC Selection")
        vm_main_layout = QHBoxLayout() # Layout principal para o grupo de VMs
        vm_groupbox.setToolTip("Select the VMs and LXC Containers you want to synchronize to NetBox.")
        vm_groupbox.setLayout(vm_main_layout)

        self.vm_scroll_area = QScrollArea()
        self.vm_scroll_area.setWidgetResizable(True)
        self.vm_scroll_content_widget = QWidget()
        self.vm_list_layout = QVBoxLayout(self.vm_scroll_content_widget) # Layout for VM checkboxes
        self.vm_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.vm_scroll_area.setWidget(self.vm_scroll_content_widget)
        vm_main_layout.addWidget(self.vm_scroll_area)

        vm_buttons_layout = QVBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.setToolTip("Select all listed VMs/LXCs for synchronization.")
        self.select_all_button.clicked.connect(self.select_all_vms)
        vm_buttons_layout.addWidget(self.select_all_button)

        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.clicked.connect(self.deselect_all_vms)
        self.deselect_all_button.setToolTip("Deselect all listed VMs/LXCs.")
        vm_buttons_layout.addWidget(self.deselect_all_button)
        vm_buttons_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)) # Spacer
        vm_main_layout.addLayout(vm_buttons_layout)
        main_layout.addWidget(vm_groupbox)

        # --- Action Frame ---
        action_groupbox = QGroupBox("Actions")
        action_layout = QHBoxLayout()
        action_groupbox.setToolTip("Perform synchronization actions.")
        action_groupbox.setLayout(action_layout)
        self.sync_button = QPushButton("Sync Selected to NetBox")
        self.sync_button.setEnabled(False)
        self.sync_button.clicked.connect(self.start_sync_thread)
        action_layout.addWidget(self.sync_button)
        main_layout.addWidget(action_groupbox)

        # --- Log Frame ---
        log_groupbox = QGroupBox("Logs")
        log_layout = QVBoxLayout()
        log_groupbox.setToolTip("View application logs, progress, and errors here.")
        # Allow the log groupbox to expand vertically
        log_groupbox.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        log_groupbox.setLayout(log_layout)
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        # Allow the QTextEdit to expand in both directions
        self.log_text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_layout.addWidget(self.log_text_edit)
        main_layout.addWidget(log_groupbox)

    def clear_vm_list_display(self):
        """Removes all VM/LXC checkboxes from the UI and clears the internal map."""
        while self.vm_list_layout.count():
            child = self.vm_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.vm_checkboxes_map.clear()

    def _load_initial_configs(self):
        """
        Loads application configurations (global and Proxmox nodes) from the .env file.
        Initializes NetBox and Proxmox API clients based on the loaded configurations.
        Populates the node selection combobox.
        Attempts to re-select the previously selected node.
        """
        # Store the ID of the currently selected node to try to re-select it after reload
        previously_selected_id_name = None
        if self.selected_node_config:
            previously_selected_id_name = self.selected_node_config.id_name

        self.global_settings, self.proxmox_configs = load_app_config()

        # Resetar e tentar reconectar ao NetBox
        self.netbox_api = None # Clear existing NetBox API client

        if not self.global_settings.netbox_url:
            QMessageBox.warning(self, "Config Incomplete", 
                                 "NetBox URL is not configured. Please set it via File > Settings.")
            self.logger.warning("NetBox URL not configured.")
        else: # Attempt to connect to NetBox
            self.netbox_api = get_netbox_api_client(self.global_settings.netbox_url, self.global_settings.netbox_token)
            if not self.netbox_api:
                QMessageBox.critical(self, "NetBox Error", f"Failed to connect to NetBox at {self.global_settings.netbox_url}.")
                self.logger.error(f"Failed to connect to NetBox at {self.global_settings.netbox_url}.")
        
        self.node_combobox.clear() # Limpar antes de adicionar
        # Resetar seleção de nó e API Proxmox antes de repopular
        self.selected_node_config = None # Clear selected node config
        self.proxmox_api = None # Clear Proxmox API client
        self.clear_vm_list_display() # Clear VMs, as the connection/node might change
        
        if not self.proxmox_configs:
            QMessageBox.information(self, "Config Info", 
                                  "No Proxmox node configurations found. Please add them via File > Settings.")
            self.logger.info("No Proxmox node configurations found.")
        else:
            node_display_names = sorted(list(self.proxmox_configs.keys()))
            self.node_combobox.addItems(node_display_names)

            current_index_to_select = -1
            if previously_selected_id_name and previously_selected_id_name in node_display_names:
                current_index_to_select = node_display_names.index(previously_selected_id_name)
                self.logger.info(f"Attempting to re-select node: {previously_selected_id_name}")
            elif node_display_names: # If previous not found or no selection, select the first available
                current_index_to_select = 0
                self.logger.info(f"Selecting the first available node: {node_display_names[0]}")
            
            if current_index_to_select != -1:
                # Temporarily block signals to avoid multiple calls to on_node_selected
                # if the index is already what we want (though clear() should reset the index)
                self.node_combobox.blockSignals(True)
                self.node_combobox.setCurrentIndex(current_index_to_select)
                self.node_combobox.blockSignals(False)
                self.on_node_selected(current_index_to_select) # Call manually to ensure connection logic runs
            
        self._update_button_states()

    def open_settings_dialog(self, select_tab_index=0):
        """
        Opens the settings dialog.

        Args:
            select_tab_index (int): The index of the tab to select upon opening (0 for Global, 1 for Proxmox Nodes).
        """
        # Ensure we have the latest configurations before opening the dialog
        current_gs, current_nodes_dict = load_app_config()
        dialog = SettingsDialog(current_gs, list(current_nodes_dict.values()), self)
        
        # Select the desired tab
        if dialog.tab_widget.count() > select_tab_index:
            dialog.tab_widget.setCurrentIndex(select_tab_index)
        
        if dialog.exec():
            new_gs, new_node_list = dialog.get_settings()
            save_app_config(new_gs, new_node_list)
            QMessageBox.information(self, "Settings Saved", 
                                     "Settings have been saved and reloaded.\n"
                                     "NetBox and Proxmox connections will be re-established based on the new settings.")
            self._load_initial_configs() # Recarregar configurações na GUI            
        # _load_initial_configs already calls _update_button_states at the end

    def open_settings_dialog_for_nodes(self):
        """Opens the settings dialog with the Proxmox Nodes tab pre-selected."""
        self.open_settings_dialog(select_tab_index=1) # 1 é o índice da aba "Proxmox Nodes"

    def _update_button_states(self):
        """Updates the enabled state of main action buttons based on API client readiness."""
        proxmox_ready = bool(self.selected_node_config and self.proxmox_api)
        netbox_ready = bool(self.netbox_api and self.global_settings and self.global_settings.netbox_url)

        # Enable/disable buttons based on whether Proxmox and NetBox APIs are ready
        self.load_vms_button.setEnabled(proxmox_ready)
        self.sync_node_to_device_button.setEnabled(proxmox_ready and netbox_ready)

        # O botão de sincronia de VMs (self.sync_button) depende também da lista de VMs estar carregada
        # e do NetBox estar pronto.
        # Seu estado é mais especificamente gerenciado em populate_vm_list_display e on_load_vms_finished.
        # No entanto, se o NetBox não estiver pronto, ele definitivamente deve estar desabilitado.
        if not netbox_ready:
            self.sync_button.setEnabled(False)

    @Slot(int)
    def on_node_selected(self, index):
        """
        Handles the selection of a Proxmox node from the combobox.
        Updates the selected_node_config and attempts to initialize the Proxmox API client.
        """
        if index < 0 or not self.proxmox_configs: return # No selection or no configs
        selected_id_name = self.node_combobox.itemText(index)
        self.selected_node_config = next((cfg for cfg in self.proxmox_configs.values() if cfg.id_name == selected_id_name), None)
        
        self.proxmox_api = None # Reset Proxmox API connection
        if self.selected_node_config:
            self.logger.info(f"Node '{self.selected_node_config.id_name}' selected. Host: {self.selected_node_config.host}")
            self.proxmox_api = get_proxmox_api_client(self.selected_node_config)
            # Don't show a critical error here if the node can't be contacted immediately,
            # the user might just be configuring. The error will appear when trying to load VMs.
            # Show an error if the selection was a direct user interaction and the connection failed.
            if not self.proxmox_api and self.sender() == self.node_combobox and self.node_combobox.hasFocus():
                QMessageBox.critical(self, "Proxmox Error", f"Failed to connect to Proxmox node: {self.selected_node_config.host}")

        # Clear the VM list and disable sync button as the node has changed
        self.clear_vm_list_display()
        self.all_proxmox_vms = []
        self.sync_button.setEnabled(False) # Disable until VMs are loaded
        self._update_button_states()

    def start_load_vms_thread(self):
        """
        Initiates a background thread to load VMs/LXCs from the selected Proxmox node.
        """
        if not self.proxmox_api or not self.selected_node_config or not self.selected_node_config.node_name:
            QMessageBox.critical(self, "Error", "Proxmox API not initialized or node not selected.")
            self._update_button_states(); return 
        
        # Disable buttons during loading
        self.load_vms_button.setEnabled(False)
        self.sync_button.setEnabled(False)
        self.clear_vm_list_display()
        self.logger.info(f"Loading VMs/LXCs from {self.selected_node_config.node_name}...")
        
        self.thread = QThread()
        self.worker = LoadVMsWorker(self.proxmox_api, self.selected_node_config.node_name)
        self.worker.moveToThread(self.thread)

        # Connect worker signals to slots
        self.worker.signals.vm_list_ready.connect(self.populate_vm_list_display)
        self.worker.signals.error.connect(self.on_worker_error)
        self.worker.signals.finished.connect(self.on_load_vms_finished)
        
        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.thread.deleteLater) # Clean up thread
        self.worker.signals.finished.connect(self.thread.quit) # Ensure thread quits
        self.worker.signals.finished.connect(self.worker.deleteLater) # Clean up worker
        self.thread.start()

    @Slot(list)
    def populate_vm_list_display(self, vms_data):
        """
        Populates the scroll area with checkboxes for each fetched VM/LXC.

        Args:
            vms_data (list): A list of dictionaries, each representing a VM/LXC.
        """
        self.all_proxmox_vms = vms_data
        self.clear_vm_list_display()

        if not vms_data:
            self.logger.info("No VMs/LXCs found on the selected Proxmox node.")
            no_vms_label = QLabel("No VMs/LXCs found on this node.")
            self.vm_list_layout.addWidget(no_vms_label)
            return

        # Sort VMs by ID for consistent display
        sorted_vms = sorted(vms_data, key=lambda x: x.get('vmid', 0))
        for vm_data_item in sorted_vms:
            vm_id = vm_data_item.get('vmid', 'N/A')
            vm_name = vm_data_item.get('name', 'N/A')
            vm_type = vm_data_item.get('type', 'N/A')
            checkbox_text = f"{vm_id} - {vm_name} ({vm_type})"
            
            checkbox = QCheckBox(checkbox_text)
            checkbox.setToolTip(f"Select this {vm_type} ({vm_name}) to synchronize it to NetBox.")
            self.vm_list_layout.addWidget(checkbox)
            self.vm_checkboxes_map[vm_id] = checkbox

        self.logger.info(f"Found {len(vms_data)} VMs/LXCs.")
        # Enable sync button if NetBox is ready
        self.sync_button.setEnabled(bool(self.netbox_api and self.global_settings and self.global_settings.netbox_url))

    @Slot()
    def on_load_vms_finished(self):
        """Handles completion of the LoadVMsWorker thread."""
        self.load_vms_button.setEnabled(True)
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

    def select_all_vms(self):
        """Checks all VM/LXC checkboxes."""
        for checkbox in self.vm_checkboxes_map.values():
            checkbox.setChecked(True)

    def deselect_all_vms(self):
        """Unchecks all VM/LXC checkboxes."""
        for checkbox in self.vm_checkboxes_map.values():
            checkbox.setChecked(False)

    def start_sync_thread(self):
        """
        Initiates a background thread to synchronize selected VMs/LXCs to NetBox.
        Also handles marking orphaned VMs in NetBox.
        """
        selected_vm_ids = [vm_id for vm_id, cb in self.vm_checkboxes_map.items() if cb.isChecked()]
        
        if not selected_vm_ids:
            QMessageBox.warning(self, "Selection", "No VMs/LXCs selected for synchronization.")
            return

        if not self.netbox_api or not self.global_settings or not self.global_settings.netbox_url:
            QMessageBox.critical(self, "NetBox Error", "NetBox API client not available. Cannot sync.")
            return
        if not self.selected_node_config:
             QMessageBox.critical(self, "Error", "No Proxmox node selected.")
             return

        vms_to_sync_data = [vm for vm in self.all_proxmox_vms if vm.get('vmid') in selected_vm_ids]

        # Disable buttons during sync
        self.sync_button.setEnabled(False)
        self.load_vms_button.setEnabled(False)
        self.logger.info(f"Starting synchronization for {len(vms_to_sync_data)} selected VM(s)/LXC(s)...")

        self.sync_thread = QThread()
        self.sync_worker_obj = SyncWorker(
            self.netbox_api, vms_to_sync_data, self.selected_node_config.netbox_cluster_name,
            self.all_proxmox_vms # Pass all VMs for orphan check
        )
        self.sync_worker_obj.moveToThread(self.sync_thread)

        # Connect worker signals
        self.sync_worker_obj.signals.sync_complete.connect(self.on_sync_completed)
        self.sync_worker_obj.signals.error.connect(self.on_worker_error)
        self.sync_worker_obj.signals.finished.connect(self.on_sync_worker_finished)

        self.sync_thread.started.connect(self.sync_worker_obj.run)
        self.sync_thread.finished.connect(self.sync_thread.deleteLater)
        self.sync_worker_obj.signals.finished.connect(self.sync_thread.quit)
        self.sync_worker_obj.signals.finished.connect(self.sync_worker_obj.deleteLater)
        self.sync_thread.start()

    def start_sync_node_to_device_thread(self):
        """
        Initiates a background thread to synchronize the selected Proxmox node itself as a Device in NetBox.
        """
        if not self.netbox_api or not self.global_settings or not self.global_settings.netbox_url:
            QMessageBox.critical(self, "NetBox Error", "NetBox API client not available.")
            return
        if not self.proxmox_api:
            QMessageBox.critical(self, "Proxmox Error", "Proxmox API client not available.")
            return
        if not self.selected_node_config or not self.selected_node_config.node_name:
            QMessageBox.critical(self, "Error", "No Proxmox node selected or node_name missing in config.")
            self._update_button_states(); return

        # Disable buttons during node sync
        self.sync_node_to_device_button.setEnabled(False)
        self.load_vms_button.setEnabled(False) # Disable other actions
        self.sync_button.setEnabled(False)
        self.logger.info(f"Starting synchronization of Proxmox node '{self.selected_node_config.node_name}' to NetBox Device...")

        self.node_sync_thread = QThread()
        self.node_sync_worker = NodeSyncWorker(
            self.netbox_api,
            self.proxmox_api,
            self.selected_node_config, # Pass the full config
            self.selected_node_config.node_name
        )
        self.node_sync_worker.moveToThread(self.node_sync_thread)

        # Connect worker signals
        self.node_sync_worker.signals.node_sync_complete.connect(self.on_node_sync_completed)
        self.node_sync_worker.signals.error.connect(self.on_worker_error) # Re-use general error handler
        self.node_sync_worker.signals.finished.connect(self.on_node_sync_worker_finished)

        self.node_sync_thread.started.connect(self.node_sync_worker.run)
        self.node_sync_thread.finished.connect(self.node_sync_thread.deleteLater)
        self.node_sync_worker.signals.finished.connect(self.node_sync_thread.quit)
        self.node_sync_worker.signals.finished.connect(self.node_sync_worker.deleteLater)
        self.node_sync_thread.start()

    @Slot(str)
    def on_sync_completed(self, message):
        """Handles the completion signal from the SyncWorker."""
        self.logger.info(message)
        if "successfully" in message.lower():
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.warning(self, "Sync Issue", message)

    @Slot(str)
    def on_node_sync_completed(self, message):
        """Handles the completion signal from the NodeSyncWorker."""
        self.logger.info(message)
        if "successfully" in message.lower() or "completed" in message.lower() or "concluída" in message.lower(): # Support for existing Portuguese messages
            QMessageBox.information(self, "Node Sync Success", message)
        else:
            QMessageBox.warning(self, "Node Sync Issue", message)

    @Slot()
    def on_sync_worker_finished(self):
        """Handles the finished signal from SyncWorker, re-enabling buttons."""
        self.sync_button.setEnabled(True)
        self.load_vms_button.setEnabled(True)
        self.sync_node_to_device_button.setEnabled(True) # Re-enable node sync button
        if self.sync_thread and self.sync_thread.isRunning():
            self.sync_thread.quit()
            self.sync_thread.wait()
    
    @Slot()
    def on_node_sync_worker_finished(self):
        """Handles the finished signal from NodeSyncWorker, re-enabling buttons."""
        self.sync_node_to_device_button.setEnabled(True)
        self.load_vms_button.setEnabled(True)
        self.sync_button.setEnabled(True) # Re-enable VM sync button
        if self.node_sync_thread and self.node_sync_thread.isRunning():
            self.node_sync_thread.quit()
            self.node_sync_thread.wait()

    @Slot(str)
    def on_worker_error(self, error_message):
        """Handles error signals from any worker thread."""
        self.logger.error(f"Worker Error: {error_message}")
        QMessageBox.critical(self, "Worker Error", error_message)
        # Re-enable buttons if a worker fails
        self.load_vms_button.setEnabled(True)
        self.sync_button.setEnabled(True)
        self.sync_node_to_device_button.setEnabled(True)

class LoadVMsWorker(QObject):
    """
    Worker QObject to fetch VMs/LXCs from Proxmox in a separate thread.
    """
    def __init__(self, proxmox_api, proxmox_node_name):
        super().__init__()
        self.proxmox_api = proxmox_api
        self.proxmox_node_name = proxmox_node_name
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            vms = fetch_vms_and_lxc(self.proxmox_api, self.proxmox_node_name)
            self.signals.vm_list_ready.emit(vms)
        except Exception as e:
            self.signals.error.emit(f"Failed to load VMs: {str(e)}")
        finally:
            self.signals.finished.emit()

class SyncWorker(QObject):
    """
    Worker QObject to synchronize VMs/LXCs to NetBox in a separate thread.
    """
    def __init__(self, netbox_api, vms_to_sync, cluster_name, all_proxmox_vms_for_orphan_check):
        super().__init__()
        self.netbox_api = netbox_api
        self.vms_to_sync = vms_to_sync
        self.cluster_name = cluster_name
        self.all_proxmox_vms_for_orphan_check = all_proxmox_vms_for_orphan_check
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            sync_to_netbox(self.netbox_api, self.vms_to_sync, self.cluster_name)
            active_proxmox_vm_names_set = {vm['name'] for vm in self.all_proxmox_vms_for_orphan_check}
            mark_orphaned_vms_as_deleted(self.netbox_api, self.cluster_name, active_proxmox_vm_names_set)
            self.signals.sync_complete.emit("Synchronization process completed successfully!")
        except Exception as e:
            self.signals.error.emit(f"Synchronization failed: {str(e)}")
        finally:
            self.signals.finished.emit()

class NodeSyncWorker(QObject):
    """
    Worker QObject to synchronize a Proxmox node to a NetBox Device in a separate thread.
    """
    def __init__(self, netbox_api, proxmox_api, node_config: ProxmoxNodeConfig, proxmox_node_name: str):
        super().__init__()
        self.netbox_api = netbox_api
        self.proxmox_api = proxmox_api
        self.node_config = node_config
        self.proxmox_node_name = proxmox_node_name
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            node_details = fetch_proxmox_node_details(self.proxmox_api, self.proxmox_node_name)
            if node_details:
                sync_proxmox_node_to_netbox_device(self.netbox_api, self.node_config, node_details)
                self.signals.node_sync_complete.emit(f"Synchronization of node '{self.proxmox_node_name}' to NetBox Device completed successfully!")
            else:
                self.signals.error.emit(f"Failed to get Proxmox node details for '{self.proxmox_node_name}'.")
        except Exception as e:
            self.signals.error.emit(f"Node synchronization for '{self.proxmox_node_name}' failed: {str(e)}")
        finally:
            self.signals.finished.emit()

def excepthook(exc_type, exc_value, exc_tb):
    """Log unhandled exceptions."""
    logging.getLogger().critical("Unhandled exception:", exc_info=(exc_type, exc_value, exc_tb))
    QApplication.quit() # Or show a more user-friendly error message

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # For macOS, might be useful for better menu integration, etc.
    # app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True) # PyQt6 usa ApplicationAttribute
    # app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    sys.excepthook = excepthook # Catch unhandled exceptions

    window = ProxmoxToNetboxApp()

    # Center the window on the screen
    screen = QApplication.primaryScreen()
    if screen:
        screen_geometry = screen.availableGeometry() # Geometria disponível (exclui barras de tarefas, etc.)
        window_geometry = window.frameGeometry() # Geometria da janela incluindo a moldura
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        window.move(window_geometry.topLeft())

    window.show()
    sys.exit(app.exec())