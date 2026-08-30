"""Package initialization for blind_watermark.
Provides lazy imports to avoid heavy dependencies (e.g., OpenCV) at install time.
"""

__version__ = '0.2.1'

def __getattr__(name):
    """Lazily import objects on first access.

    - ``WaterMark`` is imported from ``blind_watermark.blind_watermark``
    - ``WaterMarkCore`` from ``blind_watermark.bwm_core``
    - ``att`` submodule contents are re-exported via ``from .att import *`` when accessed.
    """
    if name == 'WaterMark':
        from .blind_watermark import WaterMark
        return WaterMark
    if name == 'WaterMarkCore':
        from .bwm_core import WaterMarkCore
        return WaterMarkCore
    if name == 'att':
        from . import att
        return att
    raise AttributeError(f"module 'blind_watermark' has no attribute {name!r}")

def __dir__():
    return sorted(['WaterMark', 'WaterMarkCore', '__version__', 'att'])
