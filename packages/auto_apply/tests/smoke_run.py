# import logging
# logging.basicConfig(level=logging.DEBUG, format="%(levelname)-8s | %(name)s | %(message)s")

# from auto_apply.infrastructure.registry import CapabilitiesRegistry
# from auto_apply.infrastructure.composition_root import build_orchestrator
# from auto_apply.adapters.secondary.persistence.profile_repository import ProfileRepository

# repo = ProfileRepository()
# profiles = repo.list_profiles()
# profile = repo.load_profile(profiles[0]) if profiles else None

# registry = CapabilitiesRegistry.build(user_profile=profile)

# orchestrator = build_orchestrator(registry)
# print("SUCCESS: build_orchestrator completed")
import logging
logging.basicConfig(level=logging.DEBUG, format="%(levelname)-8s | %(name)s | %(message)s")

from auto_apply.infrastructure.registry import CapabilitiesRegistry
from auto_apply.infrastructure.composition_root import build_orchestrator
from auto_apply.adapters.secondary.persistence.profile_repository import ProfileRepository

repo = ProfileRepository()
profiles = repo.list_profiles()
profile = repo.load_profile(profiles[0]) if profiles else None

registry = CapabilitiesRegistry.build(user_profile=profile)

# Phase 1: confirm wiring completes with no browser (fast, no Chrome needed)
orchestrator = build_orchestrator(registry, driver=None)
print("SUCCESS: build_orchestrator(driver=None) completed")
