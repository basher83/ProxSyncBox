import logging

from PyQt6.QtCore import QObject
from PyQt6.QtCore import pyqtSignal as Signal

# Byte conversion constants
BYTES_IN_MB = 1024 * 1024
BYTES_IN_GB = 1024 * 1024 * 1024

# Constants for NetBox VM Status
NETBOX_VM_STATUS_ACTIVE = "active"
NETBOX_VM_STATUS_OFFLINE = "offline"
NETBOX_VM_STATUS_STAGED = "staged"

# Constants for NetBox Interface
NETBOX_INTERFACE_TYPE_VIRTUAL = "virtual"
NETBOX_OBJECT_TYPE_VMINTERFACE = "virtualization.vminterface"
NETBOX_OBJECT_TYPE_DCIM_INTERFACE = "dcim.interface"

# Constants for NetBox IPAddress
NETBOX_IPADDRESS_STATUS_ACTIVE = "active"


def map_proxmox_status_to_netbox(proxmox_status: str) -> str:
    """Maps Proxmox status to NetBox status."""
    mapping = {
        "running": NETBOX_VM_STATUS_ACTIVE,
        "stopped": NETBOX_VM_STATUS_OFFLINE,
    }
    return mapping.get(proxmox_status, NETBOX_VM_STATUS_STAGED)


class QtLogHandler(logging.Handler, QObject):
    """
    A custom logging handler that emits a Qt signal with log messages.
    This allows log messages from any part of the application (including threads)
    to be displayed in a Qt widget (e.g., QTextEdit).
    """

    new_log_message = Signal(str)

    def __init__(self):
        super().__init__()
        QObject.__init__(self)  # Necessary for QObject to handle signals

    def emit(self, record):
        """
        Formats the log record and emits it via the new_log_message signal.
        """
        msg = self.format(record)
        self.new_log_message.emit(msg)
