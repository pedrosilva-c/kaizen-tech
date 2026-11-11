"""Testes das funções auxiliares puras do Kaizen Tech.

Nenhum teste executa ações de manutenção, altera o registro ou pede elevação:
só são exercitadas funções sem efeito colateral e a lista de ações da interface.
Executar: python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaizen_tech as kt  # noqa: E402


class HumanSizeTests(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(kt.human_size(0), "0.0 B")
        self.assertEqual(kt.human_size(1023), "1023.0 B")

    def test_unit_boundaries(self):
        self.assertEqual(kt.human_size(1024), "1.0 KB")
        self.assertEqual(kt.human_size(1024 ** 2), "1.0 MB")
        self.assertEqual(kt.human_size(1024 ** 3), "1.0 GB")
        self.assertEqual(kt.human_size(1024 ** 4), "1.0 TB")

    def test_fraction(self):
        self.assertEqual(kt.human_size(1536), "1.5 KB")


class GetSizeTests(unittest.TestCase):
    def test_file_and_nested_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.bin").write_bytes(b"x" * 100)
            sub = Path(tmp, "sub")
            sub.mkdir()
            Path(sub, "b.bin").write_bytes(b"y" * 50)
            self.assertEqual(kt.get_size(os.path.join(tmp, "a.bin")), 100)
            self.assertEqual(kt.get_size(tmp), 150)

    def test_missing_path_returns_zero(self):
        self.assertEqual(kt.get_size(os.path.join(tempfile.gettempdir(), "kaizen-nao-existe-123")), 0)


class SanitizeTests(unittest.TestCase):
    def test_no_sanitize_keeps_text(self):
        self.assertEqual(kt.KaizenApp._sanitize("Relatório — ação", False), "Relatório — ação")

    def test_sanitize_replaces_non_latin1(self):
        out = kt.KaizenApp._sanitize("Relatório — ação", True)
        self.assertEqual(out, "Relatório ? ação")
        out.encode("latin-1")  # não pode levantar exceção


class ResourcePathTests(unittest.TestCase):
    def test_resolves_next_to_cwd_when_not_frozen(self):
        self.assertFalse(hasattr(sys, "_MEIPASS"))
        self.assertEqual(kt.resource_path("kaizen.ico"), os.path.join(os.path.abspath("."), "kaizen.ico"))


class SystemInfoTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Somente Windows")
    def test_memory_info_is_consistent(self):
        total, avail = kt.get_memory_info()
        self.assertGreater(total, 0)
        self.assertLessEqual(avail, total)

    @unittest.skipUnless(sys.platform == "win32", "Somente Windows")
    def test_cpu_and_windows_version_are_strings(self):
        self.assertTrue(kt.get_cpu_name())
        self.assertTrue(kt.get_windows_version())


if __name__ == "__main__":
    unittest.main()
