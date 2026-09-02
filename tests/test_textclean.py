"""FASE17 C3/C4/C6: limpieza del transcript (dominio puro)."""

import unittest

from pdfsum.abstracts import extract_abstracts
from pdfsum.excerpt import find_structural_sections
from pdfsum.textclean import clean_text, dehyphenate, remove_headers_footers


class TestDeshifenizacion(unittest.TestCase):
    """C3: des-hifenización de cortes de línea."""

    def test_une_palabra_cortada(self):
        self.assertEqual(dehyphenate("informa-\nción útil"), "información útil")
        self.assertEqual(dehyphenate("saú-\nde pública"), "saúde pública")

    def test_conserva_guion_ante_mayuscula(self):
        self.assertEqual(dehyphenate("Guinea-\nBissau"), "Guinea-Bissau")

    def test_no_toca_guiones_intralinea_ni_rangos(self):
        self.assertEqual(
            dehyphenate("anti-viral 10-20 casos"), "anti-viral 10-20 casos"
        )
        self.assertEqual(dehyphenate("págs. 10-\n20"), "págs. 10-20")

    def test_idempotente(self):
        texto = "informa-\nción y Guinea-\nBissau"
        una = dehyphenate(texto)
        self.assertEqual(dehyphenate(una), una)


def _paginas_con_encabezado(
    n=5, encabezado="Rev. Salud Pública", pie="Ministerio de Salud"
):
    """Fixture: n páginas con encabezado+nº de página y pie repetidos."""
    pages = []
    for i in range(1, n + 1):
        pages.append(
            f"{encabezado} {i}\n"
            f"Contenido único de la página {i} sobre vigilancia.\n"
            f"Otra línea de contenido con datos del estudio {i}.\n"
            f"{i}\n"
            f"{pie}\n"
        )
    return "\f".join(pages)


class TestEncabezadosPies(unittest.TestCase):
    """C4: encabezados/pies repetidos y líneas solo-número."""

    def test_elimina_encabezado_pie_y_numeros(self):
        limpio = remove_headers_footers(_paginas_con_encabezado())
        self.assertNotIn("Rev. Salud Pública", limpio)
        self.assertNotIn("Ministerio de Salud", limpio)
        # números de página sueltos eliminados
        for linea in limpio.splitlines():
            self.assertFalse(linea.strip().isdigit(), f"línea solo-número: {linea!r}")
        # el contenido se conserva
        self.assertIn("Contenido único de la página 3", limpio)

    def test_conserva_titulos_no_repetidos(self):
        texto = _paginas_con_encabezado()
        # un título legítimo que aparece una sola vez en borde de página
        texto = texto.replace(
            "Contenido único de la página 2",
            "INTRODUCCIÓN\nContenido único de la página 2",
        )
        limpio = remove_headers_footers(texto)
        self.assertIn("INTRODUCCIÓN", limpio)

    def test_pocas_paginas_no_juzga(self):
        """Con < 3 páginas no hay evidencia de repetición: intacto."""
        dos = "Encabezado X\ncontenido a\fEncabezado X\ncontenido b"
        self.assertEqual(remove_headers_footers(dos), dos)

    def test_sin_fronteras_intacto_salvo_deshifenizacion(self):
        texto = "Línea 1 sin fronteras\nLínea repe-\ntida sin páginas"
        self.assertEqual(
            clean_text(texto), "Línea 1 sin fronteras\nLínea repetida sin páginas"
        )

    def test_marcadores_ocr_como_frontera(self):
        temas = [
            "vacunación infantil",
            "nutrición materna",
            "control de vectores",
            "salud mental",
        ]
        pages = [
            f"=== pág {i} ===\nBoletín Sanitario\ntexto sobre {temas[i - 1]}\n{i}"
            for i in range(1, 5)
        ]
        limpio = remove_headers_footers("\n".join(pages))
        self.assertNotIn("Boletín Sanitario", limpio)
        self.assertIn("=== pág 2 ===", limpio)  # marcadores preservados
        self.assertIn("texto sobre control de vectores", limpio)


class TestEstructuraMejora(unittest.TestCase):
    """C6: la limpieza mejora extractores estructurales."""

    def test_abstract_con_encabezado_insertado_se_extrae_completo(self):
        frase_a = "Este estudo analisa a vigilância epidemiológica em saúde."
        frase_b = "Os resultados mostram melhoria significativa dos indicadores."
        pages = []
        pages.append("Portada del documento\ncontenido inicial\nRev. Bras. Saúde 1")
        # el bloque RESUMO queda partido por el encabezado de la página 2->3
        pages.append(f"RESUMO\n{frase_a}\nRev. Bras. Saúde 2")
        pages.append(
            f"{frase_b}\nPalavras-chave: vigilância; saúde.\nRev. Bras. Saúde 3"
        )
        pages.append("Introdução\nmais conteúdo\nRev. Bras. Saúde 4")
        # pdftotext real: cada página termina en \n antes del \f
        texto = "\n\f".join(pages) + "\n"

        sucio = extract_abstracts(texto)
        limpio_texto = clean_text(texto)
        limpio = extract_abstracts(limpio_texto)

        self.assertTrue(limpio, "debe extraer el RESUMO")
        cuerpo = limpio[0].text
        self.assertIn(frase_a.split()[2], cuerpo)
        self.assertNotIn("Rev. Bras. Saúde", cuerpo)
        # el sucio arrastraba el encabezado dentro del bloque
        if sucio:
            self.assertIn("Rev. Bras.", sucio[0].text)

    def test_secciones_estructurales_siguen_localizables(self):
        texto = clean_text(_paginas_con_encabezado())
        # inyectar estructura y verificar que sigue encontrándose
        texto = "SUMÁRIO\ncapítulos\n" + texto
        nombres = [s.name for s in find_structural_sections(texto)]
        self.assertIn("sumario", nombres)


if __name__ == "__main__":
    unittest.main()
