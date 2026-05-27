"""Game World KG local MVP."""

from . import worldspec as _worldspec
from .worldspec_safe import WorldSpecGenerator as _SafeWorldSpecGenerator

__all__ = ["__version__"]

__version__ = "0.1.0"

# Route world generation through the hardened generator only.
# Do not patch WorldSpecRepairer here; runtime repairer delegates to the original
# repairer and patching it would create recursive construction.
_worldspec.WorldSpecGenerator = _SafeWorldSpecGenerator
