"""Toolset package — explicit registration of all available toolsets.

Adding a new toolset requires (REQ-03-16):
1. Creating a new file in toolsets/ with a class extending BaseToolset.
2. Importing the class here.
3. Appending it to ALL_TOOLSETS.

No core framework changes are needed.
"""

from .core import CoreToolset

# After merge with Group 5, add workflow toolsets:
# from .sales import SalesToolset
# from .accounting import AccountingToolset
# from .inventory import InventoryToolset
# from .crm import CrmToolset
# from .helpdesk import HelpdeskToolset
# from .project import ProjectToolset
# from .chatter import ChatterToolset
# from .attachments import AttachmentsToolset
# from .reports import ReportsToolset

ALL_TOOLSETS: list[type] = [
    CoreToolset,
    # SalesToolset,        # Added by Group 5 merge
    # AccountingToolset,   # Added by Group 5 merge
    # InventoryToolset,    # Added by Group 5 merge
    # CrmToolset,          # Added by Group 5 merge
    # HelpdeskToolset,     # Added by Group 5 merge
    # ProjectToolset,      # Added by Group 5 merge
    # ChatterToolset,      # Added by Group 5 merge
    # AttachmentsToolset,  # Added by Group 5 merge
    # ReportsToolset,      # Added by Group 5 merge
]

__all__ = ["ALL_TOOLSETS", "CoreToolset"]
