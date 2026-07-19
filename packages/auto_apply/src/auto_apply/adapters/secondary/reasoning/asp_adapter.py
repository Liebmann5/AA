"""Deterministic logic solver using Answer Set Programming (ASP).

This module wraps the `clingo` library. It translates the browser's AOM
into logical facts, applies our semantic rules, and derives the exact
elements we need to interact with.
"""

import logging
from pathlib import Path

import clingo

from auto_apply.domain.ports.accessibility_port import IAccessibilityNode
from auto_apply.domain.ports.reasoning_port import ILogicSolver

logger = logging.getLogger(__name__)

class ClingoFormSolver(ILogicSolver):
    """Executes declarative logic programs to solve UI ambiguity."""

    def __init__(self, rules_file_path: Path):
        """
        Args:
            rules_file_path (Path): Path to the `form_semantics.lp` file.
        """
        self.rules_file_path = rules_file_path

    def solve(self, aom_nodes: list[IAccessibilityNode]) -> dict[str, str]:
        """Translates AOM into facts, runs the solver, and parses the results.

        Args:
            aom_nodes (List[IAccessibilityNode]): The semantic tree from the scanner.

        Returns:
            Dict[str, str]: A mapping of { "logical_field_name": "node_id" }.
                            Example: {"first_name": "84729", "submit_button": "99312"}
        """
        if not self.rules_file_path.exists():
            logger.error(f"Logic rules file missing at {self.rules_file_path}")
            return {}

        # 1. Initialize the Clingo control object
        # "0" means compute all possible stable models
        ctl = clingo.Control(["0"])

        # 2. Load our mathematical rules
        ctl.load(str(self.rules_file_path))

        # 3. Translate Python AOM Nodes into ASP Facts
        # We dynamically generate a string of facts: node("id", "role", "name").
        facts =[]
        for node in aom_nodes:
            # Clean the text to prevent syntax errors in Clingo
            clean_name = node.name.replace('"', '').replace('\n', ' ').strip()
            fact = f'node("{node.node_id}", "{node.role}", "{clean_name}").'
            facts.append(fact)

        facts_program = "\n".join(facts)
        ctl.add("base",[], facts_program)

        # 4. Ground the program (Clingo compiles the variables into logic)
        ctl.ground([("base", [])])

        # 5. Solve the logic puzzle
        targets = {}

        def _on_model(model: clingo.Model):
            """Callback triggered when Clingo finds a valid logical solution."""
            for symbol in model.symbols(shown=True):
                if symbol.name == "target":
                    # symbol looks like: target(first_name, "84729")
                    logical_field = str(symbol.arguments[0])
                    node_id = str(symbol.arguments[1]).strip('"')
                    targets[logical_field] = node_id

        result = ctl.solve(on_model=_on_model)

        if result.satisfiable:
            logger.info(f"ASP Solver found {len(targets)} form targets.")
            logger.debug(f"ASP Targets: {targets}")
        else:
            logger.warning("ASP Solver could not satisfy the logic program.")

        return targets