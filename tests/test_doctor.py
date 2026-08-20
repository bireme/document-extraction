"""Tests del verificador de entorno (criterios C3, C4)."""
import unittest

from pdfsum.adapters.doctor import Check, check_environment, environment_ok


class TestDoctor(unittest.TestCase):
    def test_check_environment(self):
        """C3: devuelve checks {name,ok,detail,hard} sin lanzar."""
        checks = check_environment()
        self.assertTrue(checks)
        names = {c.name for c in checks}
        # requisitos duros de poppler presentes en la lista
        self.assertIn("pdftotext", names)
        self.assertIn("pdfinfo", names)
        self.assertIn("pdftoppm", names)
        for c in checks:
            self.assertIsInstance(c.ok, bool)
            self.assertIsInstance(c.detail, str)

    def test_environment_ok(self):
        """C4: environment_ok True solo si los requisitos duros están."""
        all_hard_ok = [
            Check("pdftotext", True, "", hard=True),
            Check("tesseract", False, "", hard=False),  # opcional falla
        ]
        self.assertTrue(environment_ok(all_hard_ok))
        one_hard_missing = [
            Check("pdftotext", False, "", hard=True),
            Check("pdfinfo", True, "", hard=True),
        ]
        self.assertFalse(environment_ok(one_hard_missing))


if __name__ == "__main__":
    unittest.main()
