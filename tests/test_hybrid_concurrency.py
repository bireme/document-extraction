"""Concurrencia controlada sin depender de la duración del OCR real."""

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from pdfsum.adapters.hybrid_ocr import HybridOcrTranscriber


def make_transcriber(**kwargs):
    with patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/bin/x"):
        return HybridOcrTranscriber(**kwargs)


class TestPageConcurrency(unittest.TestCase):
    def test_limite_orden_y_temporales(self):
        tx = make_transcriber(ocr_workers=2)
        barrier = threading.Barrier(2, timeout=5)
        second_finished = threading.Event()
        lock = threading.Lock()
        active = peak = 0
        paths = []
        completed = []

        def page(path, p, total, td):
            nonlocal active, peak
            directory = Path(td)
            with lock:
                active += 1
                peak = max(peak, active)
                paths.append(directory)
            region = directory / "_reg_0_0.png"
            region.write_text(str(p))
            barrier.wait()
            if p == 1:
                self.assertTrue(second_finished.wait(5))
            self.assertEqual(region.read_text(), str(p))
            with lock:
                completed.append(p)
                active -= 1
            if p == 2:
                second_finished.set()
            return f"texto {p}", {"page": p, "source": "tesseract"}

        with patch.object(tx, "_ocr_single_page", side_effect=page):
            text, details = tx._ocr_hybrid("doc.pdf", 6)
        self.assertEqual(peak, 2)
        self.assertEqual(completed[:2], [2, 1])
        self.assertEqual(
            text, "\n".join(f"=== pág {p} ===\ntexto {p}" for p in range(1, 7))
        )
        self.assertEqual([d["page"] for d in details], list(range(1, 7)))
        self.assertEqual(len(set(paths)), 6)
        self.assertTrue(all(not p.exists() for p in paths))

    def test_un_worker_secuencial_y_una_pagina(self):
        for pages in (1, 3):
            with self.subTest(pages=pages):
                tx = make_transcriber(ocr_workers=1)
                seen = []
                caller = threading.get_ident()

                def page(path, p, total, td, caller=caller, seen=seen):
                    self.assertEqual(threading.get_ident(), caller)
                    seen.append(p)
                    return str(p), {"page": p, "source": "tesseract"}

                with patch.object(tx, "_ocr_single_page", side_effect=page):
                    _, details = tx._ocr_hybrid("doc.pdf", pages)
                self.assertEqual(seen, list(range(1, pages + 1)))
                self.assertEqual([d["page"] for d in details], seen)

    def test_excepcion_limpia_temporales_y_permite_reutilizar(self):
        tx = make_transcriber(ocr_workers=2)
        barrier = threading.Barrier(2, timeout=5)
        paths = []

        def page(path, p, total, td):
            paths.append(Path(td))
            barrier.wait()
            if p == 1:
                raise RuntimeError("fallo de página")
            return "dos", {"page": p, "source": "tesseract"}

        with (
            patch.object(tx, "_ocr_single_page", side_effect=page),
            self.assertRaisesRegex(RuntimeError, "fallo de página"),
        ):
            tx._ocr_hybrid("doc.pdf", 2)
        self.assertTrue(all(not p.exists() for p in paths))
        with patch.object(
            tx,
            "_ocr_single_page",
            return_value=("bien", {"page": 1, "source": "tesseract"}),
        ):
            text, _ = tx._ocr_hybrid("doc.pdf", 1)
        self.assertIn("bien", text)

    def test_mixto_concurrente_solo_paginas_pobres(self):
        tx = make_transcriber(ocr_workers=2)
        barrier = threading.Barrier(2, timeout=5)
        seen = []
        native = "Texto nativo abundante. " * 30

        def page(path, p, total, td):
            seen.append(p)
            barrier.wait()
            return str(p), {"page": p, "source": "tesseract"}

        with (
            patch("pdfsum.adapters.hybrid_ocr.shutil.which", return_value="/bin/x"),
            patch("pdfsum.adapters.hybrid_ocr._pdfinfo_pages", return_value=4),
            patch(
                "pdfsum.adapters.hybrid_ocr._run",
                return_value=f"{native}\f\f{native}\f\f",
            ),
            patch.object(tx, "_ocr_single_page", side_effect=page),
        ):
            result = tx.transcribe("doc.pdf")
        self.assertEqual(sorted(seen), [2, 4])
        self.assertEqual([d["page"] for d in result.pages_detail], [1, 2, 3, 4])
        self.assertEqual(
            result.text,
            f"=== pág 1 ===\n{native}\n=== pág 2 ===\n2\n=== pág 3 ===\n{native}\n=== pág 4 ===\n4",
        )

    def test_eventos_y_metadatos_con_render_y_rechazo_concurrentes(self):
        from PIL import Image

        from pdfsum.segment import Region

        barrier = threading.Barrier(2, timeout=5)
        third_completed = threading.Event()
        events = []

        def sink(event, **fields):
            events.append((event, fields))
            if event == "ocr_pagina_completada" and fields["pagina"] == 3:
                third_completed.set()

        class RejectedVlm:
            calls = 0

            def ocr_image(inner, path, lang):
                inner.calls += 1
                return ""

        vlm = RejectedVlm()
        tx = make_transcriber(ocr_workers=3, vlm=vlm, event_sink=sink)

        def run(cmd, timeout=120):
            if cmd[0] == "pdftoppm":
                p = int(cmd[cmd.index("-f") + 1])
                if p != 1:
                    with Image.new("L", (30, 30), 255) as im:
                        im.save(cmd[-1] + f"-{p}.pgm", format="PPM")
                return ""
            p = 2 if "pdfsum-p2-" in cmd[1] else 3
            if "tsv" in cmd:
                barrier.wait()
                confidence = 95 if p == 2 else 30
                return "level\tconf\ttext\n" + f"5\t{confidence}\tpalabra\n" * 20
            self.assertTrue(third_completed.wait(5))
            return "texto dos"

        def regions(im, timings):
            timings.update(
                dict.fromkeys(
                    (
                        "mascara_segundos",
                        "columnas_segundos",
                        "regiones_segundos",
                        "segmentacion_segundos",
                    ),
                    0.0,
                )
            )
            return [Region(0, 0, 30, 30)]

        with (
            patch("pdfsum.adapters.hybrid_ocr._run", side_effect=run),
            patch("pdfsum.adapters.hybrid_ocr.detect_regions", side_effect=regions),
            patch.object(tx, "_preprocess_page", side_effect=lambda img: (img, 0.0)),
        ):
            text, details = tx._ocr_hybrid("doc.pdf", 3)
        self.assertEqual([d["page"] for d in details], [1, 2, 3])
        self.assertEqual(details[0]["source"], "sin_imagen")
        self.assertNotIn("=== pág 1 ===", text)
        self.assertLess(text.index("=== pág 2 ==="), text.index("=== pág 3 ==="))
        self.assertTrue(details[2]["vlm_rejected"])
        self.assertEqual(vlm.calls, 2)
        self.assertEqual(
            [f["pagina"] for e, f in events if e == "ocr_pagina_completada"], [3, 2]
        )
        self.assertEqual(
            sorted(f["pagina"] for e, f in events if e == "ocr_pagina_iniciada"),
            [1, 2, 3],
        )
        self.assertEqual(
            [f["pagina"] for e, f in events if e == "ocr_pagina_sin_imagen"], [1]
        )
        self.assertEqual([f["pagina"] for e, f in events if e == "vlm_rechazado"], [3])

    def test_limites_invalidos(self):
        for name in ("ocr_workers", "vlm_workers"):
            for value in (0, -1, True, 1.5, "2"):
                with (
                    self.subTest(name=name, value=value),
                    self.assertRaisesRegex(ValueError, name),
                ):
                    make_transcriber(**{name: value})


class TestVlmConcurrency(unittest.TestCase):
    def test_limite_independiente_y_excepcion_libera_permiso(self):
        for limit in (1, 2):
            with self.subTest(limit=limit):
                self.check_limit(limit)

    def check_limit(self, limit):
        lock = threading.Lock()
        release = threading.Event()
        saturated = threading.Event()
        all_attempted = threading.Event()
        active = peak = attempts = 0
        calls = {}

        class Vlm:
            def ocr_image(inner, path, lang):
                nonlocal active, peak
                with lock:
                    calls[path] = calls.get(path, 0) + 1
                    first = calls[path] == 1
                    active += 1
                    peak = max(peak, active)
                    if active == limit:
                        saturated.set()
                try:
                    if not release.wait(5):
                        raise AssertionError("no se liberó el VLM")
                    if first:
                        raise RuntimeError("fallo simulado de Ollama")
                    return "texto válido"
                finally:
                    with lock:
                        active -= 1

        tx = make_transcriber(ocr_workers=4, vlm_workers=limit, vlm=Vlm())
        semaphore = tx._vlm_slots

        class ObservedSemaphore:
            def __enter__(inner):
                nonlocal attempts
                with lock:
                    attempts += 1
                    if attempts == 4:
                        all_attempted.set()
                return semaphore.__enter__()

            def __exit__(inner, *args):
                return semaphore.__exit__(*args)

        tx._vlm_slots = ObservedSemaphore()
        with (
            patch(
                "pdfsum.adapters.hybrid_ocr._run",
                return_value="level\tconf\ttext\n5\t30\tx",
            ),
            ThreadPoolExecutor(max_workers=4) as executor,
        ):
            futures = [
                executor.submit(tx._ocr_page, Path(f"reg{i}.png")) for i in range(4)
            ]
            try:
                self.assertTrue(all_attempted.wait(5))
                self.assertTrue(saturated.wait(5))
                self.assertEqual(peak, limit)
            finally:
                release.set()
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(peak, limit)
        self.assertEqual(list(calls.values()), [2] * 4)
        self.assertTrue(all(info["vlm"] for _, _, _, info in results))
        self.assertEqual(tx.vlm_used_pages, 4)
