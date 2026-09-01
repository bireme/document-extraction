"""Contrato mínimo y consistencia de las especificaciones de evaluación."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class TestEvalSpecs(unittest.TestCase):
    def test_specs_yaml_son_parseables_y_tienen_criterios_validos(self):
        """Cada spec posee identidad, criterios no vacíos e IDs locales únicos."""
        paths = sorted((ROOT / "evals").glob("eval-spec-*.yaml"))
        self.assertTrue(paths)
        spec_ids: set[str] = set()
        for path in paths:
            with self.subTest(spec=path.name):
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)
                spec_id = payload.get("id")
                self.assertIsInstance(spec_id, str)
                self.assertTrue(spec_id.strip())
                self.assertNotIn(spec_id, spec_ids)
                spec_ids.add(spec_id)
                criteria = payload.get("criterios")
                self.assertIsInstance(criteria, list)
                self.assertTrue(criteria)
                criterion_ids = []
                for criterion in criteria:
                    self.assertIsInstance(criterion, dict)
                    criterion_id = criterion.get("id")
                    description = criterion.get("descripcion")
                    self.assertIsInstance(criterion_id, str)
                    self.assertTrue(criterion_id.strip())
                    self.assertIsInstance(description, str)
                    self.assertTrue(description.strip())
                    criterion_ids.append(criterion_id)
                self.assertEqual(len(criterion_ids), len(set(criterion_ids)))


if __name__ == "__main__":
    unittest.main()
