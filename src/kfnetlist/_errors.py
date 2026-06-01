from enum import StrEnum


class LvsError(StrEnum):
    INSTANCE_MISSING_IN_LAYOUT = "LVS.instance.missing_in_layout"
    INSTANCE_MISSING_IN_SCHEMATIC = "LVS.instance.missing_in_schematic"
    INSTANCE_COMPONENT_MISMATCH = "LVS.instance.component_mismatch"
    NET_MISSING_IN_LAYOUT = "LVS.net.missing_in_layout"
    NET_MISSING_IN_SCHEMATIC = "LVS.net.missing_in_schematic"
    PORT_MISSING_IN_LAYOUT = "LVS.port.missing_in_layout"
    PORT_MISSING_IN_SCHEMATIC = "LVS.port.missing_in_schematic"
    PORT_MISMATCH = "LVS.port.mismatch"
    OPEN = "LVS.open"
    SHORT = "LVS.short"
