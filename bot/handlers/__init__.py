"""Handlers package."""
from .start import router as start_router
from .items import router as items_router
from .stats import router as stats_router

__all__ = ["start_router", "items_router", "stats_router"]
