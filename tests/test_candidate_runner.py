from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.evaluate_candidate import load_candidate


class CandidateRunnerTest(unittest.TestCase):
    def test_entrypoint_builds_the_isolated_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "candidate_impl.py").write_text(
                """
class Candidate:
    marker = "isolated-candidate"

    def reset(self, session_id, user_profile):
        pass

    def respond(self, session_id, user_message, turn, top_k):
        return {"message": "", "ask_attribute": None, "recommendations": []}
""".lstrip(),
                encoding="utf-8",
            )
            entrypoint = root / "entrypoint.py"
            entrypoint.write_text(
                "from candidate_impl import Candidate\n\n"
                "def build_agent(catalog_path):\n"
                "    return Candidate()\n",
                encoding="utf-8",
            )

            candidate, loaded_path = load_candidate(entrypoint, "unused-catalog.jsonl")

            self.assertEqual(candidate.marker, "isolated-candidate")
            self.assertEqual(loaded_path, entrypoint.resolve())


if __name__ == "__main__":
    unittest.main()
