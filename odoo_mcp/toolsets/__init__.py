"""Toolset package — explicit registration of all available toolsets.

Adding a new toolset requires (REQ-03-16):
1. Creating a new file in toolsets/ with a class extending BaseToolset.
2. Importing the class here.
3. Appending it to ALL_TOOLSETS.

No core framework changes are needed.
"""

from .core import CoreToolset
from .sales import SalesToolset
from .accounting import AccountingToolset
from .inventory import InventoryToolset
from .crm import CrmToolset
from .helpdesk import HelpdeskToolset
from .project import ProjectToolset
from .chatter import ChatterToolset
from .attachments import AttachmentsToolset
from .reports import ReportsToolset

ALL_TOOLSETS: list[type] = [
    CoreToolset,
    SalesToolset,
    AccountingToolset,
    InventoryToolset,
    CrmToolset,
    HelpdeskToolset,
    ProjectToolset,
    ChatterToolset,
    AttachmentsToolset,
    ReportsToolset,
]

__all__ = ["ALL_TOOLSETS", "CoreToolset"]
