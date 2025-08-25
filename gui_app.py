import logging
import sys
from typing import Optional  # Import Optional # type: ignore

from PyQt6.QtCore import QObject, Qt, QThread
from PyQt6.QtCore import pyqtSignal as Signal
from PyQt6.QtCore import pyqtSlot as Slot
from PyQt6.QtGui import QAction  # Para menu
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config_loader import load_app_config, save_app_config  # Config loader functions
from config_models import GlobalSettings, ProxmoxNodeConfig  # Config models
from netbox_handler import get_netbox_api_client
from proxmox_handler import fetch_proxmox_node_details, fetch_vms_and_lxc, get_proxmox_api_client
from settings_dialog import SettingsDialog  # Import the settings dialog
from sync_orchestrator import (  # type: ignore
    mark_orphaned_vms_as_deleted,
    sync_proxmox_node_to_netbox_device,
    sync_to_netbox,
)
from utils import QtLogHandler


class WorkerSignals(QObject):
    finished = Signal()
    error = Signal(str)
    progress = Signal(str)  # Para mensagens de progresso/log
    vm_list_ready = Signal(list)
    node_sync_complete = Signal(str)
    sync_complete = Signal(str)  # Mensagem de sucesso/falha da sincronização


class ProxmoxToNetboxApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProxSyncBox")
        self.setGeometry(100, 100, 850, 750)  # x, y, width, height

        self.global_settings: GlobalSettings | None = None
        self.proxmox_configs: dict[str, ProxmoxNodeConfig] = {}
        self.selected_node_config: ProxmoxNodeConfig | None = None
        self.proxmox_api = None
        self.netbox_api = None
        self.all_proxmox_vms = []  # Stores all VMs/LXCs fetched from the selected Proxmox node
        self.all_log_messages = []  # Stores all incoming log messages for filtering/clearing

        self._setup_ui()  # Setup UI first so log widgets exist
        self.vm_checkboxes_map = {}  # Maps VM ID to its QCheckBox widget in the UI
        self._setup_logging()  # Setup logging after UI
        self._setup_menu()  # Add application menu
        self._load_initial_configs()

    def _setup_logging(self):
        self.logger = logging.getLogger()  # Get the root logger
        self.logger.setLevel(logging.DEBUG)  # Set root logger level to DEBUG to allow all messages to pass to handlers
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        # GUI log handler that emits Qt signals
        self.qt_log_handler = QtLogHandler()
        self.qt_log_handler.setFormatter(formatter)
        self.qt_log_handler.setLevel(logging.DEBUG)  # Ensure QtLogHandler processes DEBUG messages
        self.logger.addHandler(self.qt_log_handler)
        self.qt_log_handler.new_log_message.connect(self.append_log_message)

    def _apply_log_filter(self):
        """Filters the stored log messages and displays matching ones."""
        # Ensure log_filter_input and log_text_edit are created before calling this
        if not hasattr(self, "log_filter_input") or not hasattr(self, "log_text_edit"):
            return  # Skip if UI is not fully set up yet

        filter_text = self.log_filter_input.text().lower()
        self.log_text_edit.clear()  # Clear current display

        for message in self.all_log_messages:
            if filter_text in message.lower():
                self.log_text_edit.append(message)

    @Slot()
    def clear_log(self):
        """Clears all stored log messages and the display."""
        self.all_log_messages.clear()
        self.log_text_edit.clear()

    @Slot(str)
    def append_log_message(self, message):
        """Appends a log message to the QTextEdit in the GUI."""
        self.all_log_messages.append(message)  # Store the message first
        self._apply_log_filter()  # Re-apply filter whenever a new message arrives (will check if widgets exist)

    def _setup_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        settings_action = QAction("&Settings", self)
        settings_action.setToolTip("Open application settings to configure NetBox, Proxmox nodes, and other options.")
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
        select_node_label.setToolTip(
            "Select a configured Proxmox node to load VMs/LXCs from or sync as a NetBox Device."
        )
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
        self.load_vms_button.setToolTip(
            "Fetch the list of Virtual Machines and LXC Containers from the selected Proxmox node."
        )
        self.load_vms_button.clicked.connect(self.start_load_vms_thread)
        node_layout.addWidget(self.load_vms_button)

        self.sync_node_to_device_button = QPushButton("Sync Node to NetBox Device")
        self.sync_node_to_device_button.setEnabled(False)
        self.sync_node_to_device_button.setToolTip(
            "Synchronize the selected Proxmox node itself as a Device in NetBox, including its interfaces."
        )
        self.sync_node_to_device_button.clicked.connect(self.start_sync_node_to_device_thread)
        node_layout.addWidget(self.sync_node_to_device_button)

        node_layout.addSpacerItem(
            QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )  # Spacer
        main_layout.addWidget(node_groupbox)

        # --- VM/LXC Selection Frame ---
        vm_groupbox = QGroupBox("VM/LXC Selection")
        vm_main_layout = QHBoxLayout()  # Layout principal para o grupo de VMs
        vm_groupbox.setToolTip("Select the VMs and LXC Containers you want to synchronize to NetBox.")
        vm_groupbox.setLayout(vm_main_layout)

        self.vm_scroll_area = QScrollArea()
        self.vm_scroll_area.setWidgetResizable(True)
        self.vm_scroll_content_widget = QWidget()
        self.vm_list_layout = QVBoxLayout(self.vm_scroll_content_widget)  # Layout for VM checkboxes
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
        vm_buttons_layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )  # Spacer
        vm_main_layout.addLayout(vm_buttons_layout)
        main_layout.addWidget(vm_groupbox)

        # --- Action Frame ---
        action_groupbox = QGroupBox("Actions")
        action_layout = QHBoxLayout()
        action_groupbox.setToolTip("Perform synchronization actions.")
        action_groupbox.setLayout(action_layout)
        self.sync_button = QPushButton("Sync Selected to NetBox")
        self.sync_button.setEnabled(False)
        self.sync_button.setToolTip(
            "Synchronize the selected VMs/LXCs to NetBox. Requires NetBox connection and loaded VMs."
        )
        self.sync_button.clicked.connect(self.start_sync_thread)
        action_layout.addWidget(self.sync_button)
        main_layout.addWidget(action_groupbox)

        # --- Log Area (Controls + Display) ---
        log_area_groupbox = QGroupBox("Application Log")
        log_area_main_layout = QVBoxLayout()  # Main layout for the log area groupbox
        log_area_groupbox.setLayout(log_area_main_layout)

        # Layout for log controls (level, filter, clear)
        log_controls_widgets_layout = QHBoxLayout()

        # Log Level control
        log_level_label = QLabel("Level:")
        log_controls_widgets_layout.addWidget(log_level_label)
        self.log_level_combobox = QComboBox()
        self.log_level_combobox.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])  # Standard log levels
        self.log_level_combobox.setToolTip("Select the minimum level of log messages to display.")
        self.log_level_combobox.currentIndexChanged.connect(self.on_log_level_changed)
        log_controls_widgets_layout.addWidget(self.log_level_combobox)

        # Add Filter control
        log_filter_label = QLabel("Filter:")
        log_controls_widgets_layout.addWidget(log_filter_label)
        self.log_filter_input = QLineEdit()
        self.log_filter_input.setPlaceholderText("Enter text to filter logs...")
        self.log_filter_input.setToolTip("Type here to filter log messages (case-insensitive).")
        self.log_filter_input.textChanged.connect(self._apply_log_filter)
        log_controls_widgets_layout.addWidget(self.log_filter_input)

        # Add Clear button
        self.clear_log_button = QPushButton("Clear Log")
        self.clear_log_button.setToolTip("Clear all log messages from the display.")
        self.clear_log_button.clicked.connect(self.clear_log)
        log_controls_widgets_layout.addWidget(self.clear_log_button)
        log_controls_widgets_layout.addStretch()  # Push controls to the left

        log_area_main_layout.addLayout(log_controls_widgets_layout)  # Add controls to the groupbox

        self.log_text_edit = QTextEdit()  # Create the log display area
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)  # Optional: for better readability
        log_area_main_layout.addWidget(self.log_text_edit)  # Add log display to the groupbox

        main_layout.addWidget(log_area_groupbox)  # Add the entire log area to the main window layout

    @Slot(int)
    def on_log_level_changed(self, index):
        """
        Changes the logging level of the QtLogHandler based on the combobox selection.
        """
        selected_level_str = self.log_level_combobox.currentText()
        level = logging.getLevelName(selected_level_str.upper())
        self.qt_log_handler.setLevel(level)
        self.logger.info(f"Log display level changed to {selected_level_str}")
        # Optionally save the new level to settings immediately
        # self.global_settings.log_level = selected_level_str # Update the object

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

        # Load configurations first to populate self.global_settings and self.proxmox_configs
        self.global_settings, self.proxmox_configs = load_app_config()

        self.netbox_api = None  # Clear existing NetBox API client

        if not self.global_settings.netbox_url:
            QMessageBox.warning(
                self, "Configuration Incomplete", "NetBox URL is not configured. Please set it via File > Settings."
            )
            self.logger.warning("NetBox URL not configured.")
        else:  # Attempt to connect to NetBox
            self.netbox_api = get_netbox_api_client(self.global_settings.netbox_url, self.global_settings.netbox_token)
            if not self.netbox_api:
                QMessageBox.critical(
                    self,
                    "NetBox Connection Error",
                    f"Failed to connect to NetBox at {self.global_settings.netbox_url}.",
                )
                self.logger.error(f"Failed to connect to NetBox at {self.global_settings.netbox_url}.")

        # Apply loaded log level from global settings
        loaded_log_level_str = self.global_settings.log_level.upper()
        try:
            loaded_log_level = logging.getLevelName(loaded_log_level_str)
            # Set the handler level, not the logger's main level, which is already DEBUG
            if hasattr(self, "qt_log_handler"):  # Ensure handler exists
                self.qt_log_handler.setLevel(loaded_log_level)
            # Update combobox to reflect the loaded setting
            self.log_level_combobox.setCurrentText(loaded_log_level_str)  # Update combobox display
        except ValueError:
            self.logger.warning(f"Invalid log level '{loaded_log_level_str}' loaded from config. Defaulting to INFO.")

        self.node_combobox.clear()  # Limpar antes de adicionar
        # Resetar seleção de nó e API Proxmox antes de repopular
        self.selected_node_config = None  # Clear selected node config
        self.proxmox_api = None  # Clear Proxmox API client
        self.clear_vm_list_display()  # Clear VMs, as the connection/node might change

        if not self.proxmox_configs:
            QMessageBox.information(
                self, "Config Info", "No Proxmox node configurations found. Please add them via File > Settings."
            )
            self.logger.info("No Proxmox node configurations found.")
        else:
            node_display_names = sorted(self.proxmox_configs.keys())
            self.node_combobox.addItems(node_display_names)

            current_index_to_select = -1
            if previously_selected_id_name and previously_selected_id_name in node_display_names:
                current_index_to_select = node_display_names.index(previously_selected_id_name)
                self.logger.info(f"Attempting to re-select node: {previously_selected_id_name}")
            elif node_display_names:  # If previous not found or no selection, select the first available
                current_index_to_select = 0
                self.logger.info(f"Selecting the first available node: {node_display_names[0]}")

            if current_index_to_select != -1:
                # Temporarily block signals to avoid multiple calls to on_node_selected
                # if the index is already what we want (though clear() should reset the index)
                self.node_combobox.blockSignals(True)
                self.node_combobox.setCurrentIndex(current_index_to_select)
                self.node_combobox.blockSignals(False)
                self.on_node_selected(
                    current_index_to_select
                )  # Call manually to ensure connection logic runs for the re-selected node

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
            # The log level is saved as part of global settings
            QMessageBox.information(
                self,
                "Settings Saved",
                "Settings have been saved and reloaded.\n"
                "NetBox and Proxmox connections will be re-established based on the new settings.",
            )
            self._load_initial_configs()  # Recarregar configurações na GUI
        # _load_initial_configs already calls _update_button_states at the end

    def open_settings_dialog_for_nodes(self):
        """Opens the settings dialog with the Proxmox Nodes tab pre-selected."""
        self.open_settings_dialog(select_tab_index=1)  # 1 é o índice da aba "Proxmox Nodes"

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
        if index < 0 or not self.proxmox_configs:
            return  # No selection or no configs
        selected_id_name = self.node_combobox.itemText(index)
        self.selected_node_config = next(
            (cfg for cfg in self.proxmox_configs.values() if cfg.id_name == selected_id_name), None
        )

        self.proxmox_api = None  # Reset Proxmox API connection
        if self.selected_node_config:
            self.logger.info(
                f"Node '{self.selected_node_config.id_name}' selected. Host: {self.selected_node_config.host}"
            )
            self.proxmox_api = get_proxmox_api_client(self.selected_node_config)
            # Don't show a critical error here if the node can't be contacted immediately,
            # the user might just be configuring. The error will appear when trying to load VMs.
            # Show an error if the selection was a direct user interaction and the connection failed.
            if not self.proxmox_api and self.sender() == self.node_combobox and self.node_combobox.hasFocus():
                QMessageBox.critical(
                    self,
                    "Proxmox Connection Error",
                    f"Failed to connect to Proxmox node: {self.selected_node_config.host}",
                )

        # Clear the VM list and disable sync button as the node has changed
        self.clear_vm_list_display()
        self.all_proxmox_vms = []
        self.sync_button.setEnabled(False)  # Disable until VMs are loaded
        self._update_button_states()

    def start_load_vms_thread(self):
        """
        Initiates a background thread to load VMs/LXCs from the selected Proxmox node.
        """
        if not self.proxmox_api or not self.selected_node_config or not self.selected_node_config.node_name:
            QMessageBox.critical(self, "Proxmox Error", "Proxmox API not initialized or node not selected.")
            self._update_button_states()
            return

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
        self.thread.finished.connect(self.thread.deleteLater)  # Clean up thread
        self.worker.signals.finished.connect(self.thread.quit)  # Ensure thread quits
        self.worker.signals.finished.connect(self.worker.deleteLater)  # Clean up worker
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
        sorted_vms = sorted(vms_data, key=lambda x: x.get("vmid", 0))
        for vm_data_item in sorted_vms:
            vm_id = vm_data_item.get("vmid", "N/A")
            vm_name = vm_data_item.get("name", "N/A")
            vm_type = vm_data_item.get("type", "N/A")
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
            QMessageBox.warning(self, "No Selection", "No VMs/LXCs selected for synchronization.")
            return

        if not self.netbox_api or not self.global_settings or not self.global_settings.netbox_url:
            QMessageBox.critical(self, "NetBox Error", "NetBox API client not available. Synchronization aborted.")
            return
        if not self.selected_node_config:
            QMessageBox.critical(self, "Proxmox Error", "No Proxmox node selected.")
            return

        vms_to_sync_data = [vm for vm in self.all_proxmox_vms if vm.get("vmid") in selected_vm_ids]

        # Disable buttons during sync
        self.sync_button.setEnabled(False)
        self.load_vms_button.setEnabled(False)
        self.logger.info(f"Starting synchronization for {len(vms_to_sync_data)} selected VM(s)/LXC(s)...")

        self.sync_thread = QThread()
        self.sync_worker_obj = SyncWorker(
            self.netbox_api,
            vms_to_sync_data,
            self.selected_node_config.netbox_cluster_name,
            self.all_proxmox_vms,  # Pass all VMs for orphan check
            self.global_settings,  # Pass global_settings
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
            QMessageBox.critical(self, "NetBox Error", "NetBox API client not available. Node synchronization aborted.")
            return
        if not self.proxmox_api:
            QMessageBox.critical(
                self, "Proxmox Error", "Proxmox API client not available. Node synchronization aborted."
            )
            return
        if not self.selected_node_config or not self.selected_node_config.node_name:
            QMessageBox.critical(
                self, "Proxmox Error", "No Proxmox node selected or node_name missing in configuration."
            )
            self._update_button_states()
            return

        # Disable buttons during node sync
        self.sync_node_to_device_button.setEnabled(False)
        self.load_vms_button.setEnabled(False)  # Disable other actions
        self.sync_button.setEnabled(False)
        self.logger.info(
            f"Starting synchronization of Proxmox node '{self.selected_node_config.node_name}' to NetBox Device..."
        )

        self.node_sync_thread = QThread()
        self.node_sync_worker = NodeSyncWorker(
            self.netbox_api,
            self.proxmox_api,
            self.selected_node_config,  # Pass the full config
            self.selected_node_config.node_name,
            self.global_settings,  # Pass global settings
        )
        self.node_sync_worker.moveToThread(self.node_sync_thread)

        # Connect worker signals
        self.node_sync_worker.signals.node_sync_complete.connect(self.on_node_sync_completed)
        self.node_sync_worker.signals.error.connect(self.on_worker_error)  # Re-use general error handler
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
            QMessageBox.information(self, "Synchronization Successful", message)
        else:
            QMessageBox.warning(self, "Synchronization Issue", message)

    @Slot(str)
    def on_node_sync_completed(self, message):
        """Handles the completion signal from the NodeSyncWorker."""
        self.logger.info(message)
        if "successfully" in message.lower() or "completed" in message.lower():
            QMessageBox.information(self, "Node Synchronization Successful", message)
        else:
            QMessageBox.warning(self, "Node Synchronization Issue", message)

    @Slot()
    def on_sync_worker_finished(self):
        """Handles the finished signal from SyncWorker, re-enabling buttons."""
        self.sync_button.setEnabled(True)
        self.load_vms_button.setEnabled(True)
        self.sync_node_to_device_button.setEnabled(True)  # Re-enable node sync button
        if self.sync_thread and self.sync_thread.isRunning():
            self.sync_thread.quit()
            self.sync_thread.wait()

    @Slot()
    def on_node_sync_worker_finished(self):
        """Handles the finished signal from NodeSyncWorker, re-enabling buttons."""
        self.sync_node_to_device_button.setEnabled(True)
        self.load_vms_button.setEnabled(True)
        self.sync_button.setEnabled(True)  # Re-enable VM sync button
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
            self.signals.error.emit(f"Failed to load VMs: {e!s}")
        finally:
            self.signals.finished.emit()


class SyncWorker(QObject):
    """
    Worker QObject to synchronize VMs/LXCs to NetBox in a separate thread.
    """

    def __init__(
        self,
        netbox_api,
        vms_to_sync,
        cluster_name,
        all_proxmox_vms_for_orphan_check,
        global_settings: Optional[GlobalSettings],
    ):
        super().__init__()
        self.netbox_api = netbox_api
        self.vms_to_sync = vms_to_sync
        self.global_settings = global_settings
        self.cluster_name = cluster_name
        self.all_proxmox_vms_for_orphan_check = all_proxmox_vms_for_orphan_check
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            if not self.global_settings:
                self.signals.error.emit("Global settings not available for VM synchronization.")
                return

            processed, succeeded, warnings, errors = sync_to_netbox(
                self.netbox_api, self.vms_to_sync, self.cluster_name, self.global_settings
            )

            # Prepare data for orphan check: set of (name, vmid) tuples
            active_proxmox_vm_identities = {
                (vm["name"], vm["vmid"])
                for vm in self.all_proxmox_vms_for_orphan_check
                if "name" in vm and "vmid" in vm
            }
            orphans_marked, orphan_errors = mark_orphaned_vms_as_deleted(
                self.netbox_api,
                self.cluster_name,
                active_proxmox_vm_identities,  # Pass the set of tuples
            )

            summary_parts = [f"VM Sync: {processed} processed, {succeeded} succeeded."]
            if warnings > 0:
                summary_parts.append(f"{warnings} had warnings.")
            if errors > 0:
                summary_parts.append(f"{errors} failed to sync.")
            summary_parts.append(f"Orphan Check: {orphans_marked} marked as deleted.")
            if orphan_errors > 0:
                summary_parts.append(f"{orphan_errors} errors during orphan marking.")

            final_message = "Synchronization process completed. " + " ".join(summary_parts)
            self.signals.sync_complete.emit(final_message)

        except Exception as e:
            self.signals.error.emit(f"Synchronization failed: {e!s}")
        finally:
            self.signals.finished.emit()


class NodeSyncWorker(QObject):
    """
    Worker QObject to synchronize a Proxmox node to a NetBox Device in a separate thread.
    """

    def __init__(
        self,
        netbox_api,
        proxmox_api,
        node_config: ProxmoxNodeConfig,
        proxmox_node_name: str,
        global_settings: Optional[GlobalSettings],
    ):  # type: ignore # type: ignore
        super().__init__()
        self.netbox_api = netbox_api
        self.proxmox_api = proxmox_api
        self.global_settings = global_settings  # Store global_settings
        self.node_config = node_config
        self.proxmox_node_name = proxmox_node_name
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            node_details = fetch_proxmox_node_details(self.proxmox_api, self.node_config)  # Pass full node_config
            if not self.global_settings:
                self.signals.error.emit("Global settings not available for node synchronization.")
                return
            if node_details:  # type: ignore
                sync_proxmox_node_to_netbox_device(
                    self.netbox_api, self.node_config, node_details, self.global_settings
                )
                self.signals.node_sync_complete.emit(
                    f"Synchronization of node '{self.proxmox_node_name}' to NetBox Device completed successfully!"
                )
            else:
                self.signals.error.emit(f"Failed to get Proxmox node details for '{self.proxmox_node_name}'.")
        except Exception as e:
            self.signals.error.emit(f"Node synchronization for '{self.proxmox_node_name}' failed: {e!s}")
        finally:
            self.signals.finished.emit()


def excepthook(exc_type, exc_value, exc_tb):
    """Log unhandled exceptions."""
    logging.getLogger().critical("Unhandled exception:", exc_info=(exc_type, exc_value, exc_tb))
    QApplication.quit()  # Or show a more user-friendly error message


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # For macOS, might be useful for better menu integration, etc.
    # app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True) # PyQt6 uses ApplicationAttribute
    # app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    sys.excepthook = excepthook  # Catch unhandled exceptions

    window = ProxmoxToNetboxApp()

    # Center the window on the screen
    screen = QApplication.primaryScreen()
    if screen:
        screen_geometry = screen.availableGeometry()  # Available geometry (excludes taskbars, etc.)
        window_geometry = window.frameGeometry()  # Window geometry including the frame
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        window.move(window_geometry.topLeft())

    window.show()
    sys.exit(app.exec())
