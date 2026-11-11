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


class SafeCleanupTests(unittest.TestCase):
    def test_removes_files_and_nested_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.tmp").write_bytes(b"x" * 10)
            Path(tmp, "pasta", "sub").mkdir(parents=True)
            Path(tmp, "pasta", "sub", "b.tmp").write_bytes(b"y" * 5)
            removed, failed, freed = kt.clean_folder_safely(tmp)
            self.assertEqual((removed, failed, freed), (2, 0, 15))
            self.assertEqual(os.listdir(tmp), [])

    @unittest.skipUnless(sys.platform == "win32", "Junções são do Windows")
    def test_never_follows_a_junction_out_of_the_folder(self):
        import subprocess
        with tempfile.TemporaryDirectory() as alvo, tempfile.TemporaryDirectory() as limpeza:
            protegido = Path(alvo, "importante.txt")
            protegido.write_text("não pode sumir", encoding="utf-8")
            juncao = Path(limpeza, "link-malicioso")
            subprocess.run(["cmd", "/c", "mklink", "/J", str(juncao), alvo], check=True, capture_output=True)
            Path(limpeza, "lixo.tmp").write_bytes(b"z")

            removed, failed, _ = kt.clean_folder_safely(limpeza)

            self.assertTrue(protegido.exists(), "a limpeza atravessou a junção")
            self.assertEqual(removed, 1)
            self.assertEqual(failed, 1)
            self.assertTrue(kt.is_reparse_point(str(juncao)))
            os.rmdir(juncao)  # remove só a junção, não o destino

    def test_missing_folder_is_noop(self):
        self.assertEqual(kt.clean_folder_safely(os.path.join(tempfile.gettempdir(), "kaizen-nao-existe-456")), (0, 0, 0))


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
