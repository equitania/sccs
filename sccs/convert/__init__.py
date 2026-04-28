# SCCS Conversion Subpackage
# Convert shell configurations between formats (e.g. Fish -> PowerShell).

from sccs.convert.fish_to_pwsh import ConversionReport, FishToPwshConverter

__all__ = [
    "ConversionReport",
    "FishToPwshConverter",
]
