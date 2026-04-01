"""
Prompts Service - Legacy Compatibility Wrapper

This module provides backwards compatibility for the renamed workorders service.
All functionality has been moved to workorders_service.py.

For new code, use:
    from csc_services.workorders_service import workorders

For legacy code, this still works:
    from csc_services.prompts_service import prompts
"""

from csc_services.workorders_service import workorders

# Legacy alias for backwards compatibility
prompts = workorders

__all__ = ["prompts", "workorders"]
