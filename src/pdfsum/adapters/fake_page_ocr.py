"""Adaptador FAKE del puerto PageOCR (para tests).

Devuelve texto fijo sin invocar ningún modelo; cuenta invocaciones para
verificar cuándo el transcriptor híbrido escala al VLM.
"""
from __future__ import annotations


class FakePageOCR:
    def __init__(self, text: str = "texto vlm fake"):
        self.text = text
        self.calls = 0

    def ocr_image(self, image_path: str, lang: str) -> str:
        self.calls += 1
        return self.text
