"""The application step engine runs on the standard library and pagecomp.

Its own modules may not pull in a third-party package or AA's configuration
module (which creates data folders when imported): the engine must work
from a flash drive, inside a future task kernel, or in another project,
with nothing but Python. Measured in a fresh interpreter so other tests'
imports cannot hide a regression.
"""

from __future__ import annotations

import json
import subprocess
import sys

ENGINE_MODULES = (
    "auto_apply.application.services.form_engine",
    "auto_apply.application.services.form_actuator",
    "auto_apply.adapters.secondary.perception.pagecomp_form",
    "auto_apply.domain.applications.answers",
    "auto_apply.domain.applications.answer_review",
    "auto_apply.domain.applications.form_localization",
)

_PROBE = """
import json, sys
for m in {mods!r}:
    __import__(m)
std = set(sys.stdlib_module_names)
own = ("auto_apply", "pagecomp")
third = sorted({{n.split(".")[0] for n in sys.modules
                if n.split(".")[0] not in std and not n.startswith(own)
                and not n.startswith(("_sysconfigdata", "_virtualenv", "_distutils_hack", "__main__"))}})
print(json.dumps({{"third": third, "config": "auto_apply.domain.config" in sys.modules}}))
"""


def test_the_engine_imports_no_third_party_package_and_not_aa_configuration() -> None:
    out = subprocess.run([sys.executable, "-c", _PROBE.format(mods=ENGINE_MODULES)],
                         capture_output=True, text=True, check=True).stdout
    found = json.loads(out.strip().splitlines()[-1])
    assert found == {"third": [], "config": False}, found
