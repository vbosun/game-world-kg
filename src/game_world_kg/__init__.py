"""Game World KG local MVP."""

from . import worldspec as _worldspec
from .worldspec_runtime import (
    WorldSpecGenerator as _RuntimeWorldSpecGenerator,
    WorldSpecNormalizer as _RuntimeWorldSpecNormalizer,
    WorldSpecRepairer as _RuntimeWorldSpecRepairer,
    sample_world_spec as _runtime_sample_world_spec,
)

__all__ = ["__version__"]

__version__ = "0.1.0"

# Runtime hardening for LLM-generated WorldSpec candidates.
# Keep the strict schema in worldspec.py, but route generation/repair/sample fallback
# through normalization and genre-aware samples so raw LLM aliases do not 500 and
# ocean worlds do not get polluted by cultivation fallback content.
_worldspec.WorldSpecGenerator = _RuntimeWorldSpecGenerator
_worldspec.WorldSpecRepairer = _RuntimeWorldSpecRepairer
_worldspec.WorldSpecNormalizer = _RuntimeWorldSpecNormalizer
_worldspec.sample_world_spec = _runtime_sample_world_spec
