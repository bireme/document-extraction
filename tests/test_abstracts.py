"""Tests de extracción de abstracts (criterios C6, C7)."""

import unittest

import pytest

from pdfsum.abstracts import _find_abstract_headers, abstract_langs, extract_abstracts

_TRILINGUAL = """
RESUMO: A reorientação da assistência psiquiátrica possibilitou serviços
alternativos e cuidado mais humanizado, analisando a percepção de
profissionais de um CAPS sobre acolhimento.
Palavras-chave: Saúde Mental. Acolhimento.
ABSTRACT: The reorientation of psychiatric assistance made possible
alternative services and more humanized care, analyzing the perception of
professionals of a CAPS about reception.
Keywords: Mental Health. Embracement.
RESUMEN: La reorientación de la asistencia psiquiátrica posibilitó servicios
alternativos y cuidado más humanizado, analizando la percepción de
profesionales de un CAPS sobre la acogida.
"""

_NO_ABSTRACT = "Deixe de fumar. Ligue Disque Saúde. Ministério da Saúde."

_BODY = "Objetivo: evaluar la percepción del personal sobre la atención comunitaria."


@pytest.mark.parametrize(
    "header,lang",
    [
        ("RESUMO", "pt"),
        ("RESUMO:", "pt"),
        ("RESUMO.", "pt"),
        ("RESUMO -", "pt"),
        ("RESUMO-", "pt"),
        ("ABSTRACT", "en"),
        ("RESUMEN", "es"),
        ("RÉSUMÉ", "fr"),
        ("RIASSUNTO", "it"),
        ("ZUSAMMENFASSUNG", "de"),
        ("  RESUMO :  ", "pt"),
        ("\tRESUMO\t—\t", "pt"),
        ("\u00a0resumo\u00a0–\u00a0", "pt"),
    ],
)
def test_headers_estructurales(header, lang):
    text = header + "\r\n" + _BODY
    assert len(_find_abstract_headers(text)) == 1
    blocks = extract_abstracts(text)
    assert len(blocks) == 1
    assert blocks[0].lang == lang
    assert blocks[0].text == _BODY


@pytest.mark.parametrize("header", ["RESUMO:", "ABSTRACT.", "RESUMEN -"])
def test_header_y_texto_en_la_misma_linea(header):
    blocks = extract_abstracts(header + " " + _BODY)
    assert len(blocks) == 1
    assert blocks[0].text == _BODY


@pytest.mark.parametrize(
    "line",
    [
        "BASE DE DADOS DE RESUMOS DE REVISÕES SOBRE EFETIVIDADE",
        "INCLUI TAMBÉM RESUMOS",
        "RESUMOS DE REVISÕES SISTEMÁTICAS PUBLICADAS NA LITERATURA",
        "This database contains abstracts of systematic reviews",
        "Os resumos foram selecionados...",
        "Este resumo describe los resultados de la búsqueda.",
        "El término abstract aparece dentro de esta oración.",
        "RESUMO de las revisiones publicadas en la literatura",
        "ABSTRACT describes a section of an academic paper",
        "ABSTRACTS: revisiones de la literatura",
        "RESUMOS: revisiones de la literatura",
        "RESUMENES de la literatura",
        "ABSTRACT-based",
        "RESUMO_EDITORIAL",
    ],
)
def test_palabras_normales_no_generan_headers(line):
    text = line + "\n" + _BODY
    assert _find_abstract_headers(text) == []
    assert extract_abstracts(text) == []


def test_regresion_documento_56335_10006001043():
    # Fragmentos originales: las menciones describen bases de datos.
    text = (
        "PREPARADAS PELA COLABORAÇÃO COCHRANE. INCLUI TAMBÉM RESUMOS\n"
        "BASE DE DADOS DE RESUMOS DE REVISÕES SOBRE EFETIVIDADE\n"
        "RESUMOS DE REVISÕES SISTEMATICAS PUBLICADAS NA LITERATURA\n"
    ) * 30
    assert _find_abstract_headers(text) == []
    assert extract_abstracts(text) == []


def test_mencion_plural_no_corta_un_bloque_valido():
    body = _BODY + "\nRESUMOS DE REVISÕES SISTEMÁTICAS PUBLICADAS NA LITERATURA"
    blocks = extract_abstracts("RESUMO\n" + body + "\nABSTRACT\n" + _BODY)
    assert [block.lang for block in blocks] == ["pt", "en"]
    assert blocks[0].text == body.replace("\n", " ")


def test_header_ambiguo_aislado_con_contexto():
    # El comienzo en minúscula de la línea siguiente pertenece al cuerpo.
    body = "se evaluó la percepción del personal sobre la atención comunitaria."
    blocks = extract_abstracts("RESUME\n" + body + "\nMots-clés: salud")
    assert len(blocks) == 1
    assert blocks[0].lang == "fr"
    assert blocks[0].text == body


@pytest.mark.parametrize(
    "text",
    [
        "RESUME\n" + _BODY,
        "RESUME: se evaluó la atención comunitaria.\nMots-clés: salud",
        "Introduction\nRESUME\n" + _BODY + "\nMots-clés: salud",
        "La estrategia se\nresume a reorganizar la atención.\nMots-clés: salud",
    ],
)
def test_header_ambiguo_conserva_filtros_de_contexto(text):
    assert _find_abstract_headers(text) == []


class TestAbstracts(unittest.TestCase):
    def test_trilingual(self):
        """C6: RESUMO+ABSTRACT+RESUMEN -> 3 bloques por idioma, verbatim."""
        blocks = extract_abstracts(_TRILINGUAL)
        self.assertEqual([b.lang for b in blocks], ["pt", "en", "es"])
        self.assertEqual(abstract_langs(blocks), ["pt", "en", "es"])
        # verbatim: contiene texto original, no traducido
        pt = blocks[0]
        self.assertIn("reorientação da assistência", pt.text)
        self.assertIn("Saúde Mental", pt.keywords)
        en = blocks[1]
        self.assertIn("reorientation of psychiatric", en.text)

    def test_no_abstract(self):
        """C7: sin bloques de resumen -> lista vacía (no inventa)."""
        self.assertEqual(extract_abstracts(_NO_ABSTRACT), [])
        self.assertEqual(abstract_langs([]), [])


if __name__ == "__main__":
    unittest.main()


def test_encabezado_desplazado_sigue_siendo_una_pista():
    texto = (
        "Texto previo del resumen con extensión suficiente para la extracción.\n"
        "Keywords: salud.\nAbstract\n343\nOriginal Paper\nAutor Uno\n"
        "INTRODUCTION\nTexto del cuerpo con extensión suficiente para el candidato."
    )
    assert len(_find_abstract_headers(texto)) == 1
    # El candidato no certifica los límites: la revisión decide su ubicación.
    assert extract_abstracts(texto)[0].header == "ABSTRACT"


def test_estructura_no_se_confunde_con_introduccion_del_articulo():
    from pdfsum.abstracts import article_body_ranges

    texto = (
        "Abstract\nIntroduction\nTexto introductorio del resumen.\n"
        "Methods: Se analizaron los datos.\nResults: Se observaron mejoras.\n"
        "Keywords: salud.\nINTRODUCTION\nTexto del cuerpo del artículo."
    )
    limites = article_body_ranges(texto)
    assert len(limites) == 1
    assert texto[limites[0][0] :].startswith("INTRODUCTION")


def test_metodos_del_articulo_no_validan_encabezado_desplazado():
    from pdfsum.abstracts import article_body_ranges

    texto = (
        "Abstract\n343\nOriginal Paper\nAutor Uno\nINTRODUCTION\n"
        "Texto del cuerpo del artículo.\nMethods: Se analizaron los datos."
    )
    assert article_body_ranges(texto)
