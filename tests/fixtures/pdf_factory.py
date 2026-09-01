"""Genera PDFs mínimos y controlados sin depender de servicios externos."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_native_pdf(path: Path, lines: list[str]) -> Path:
    """Escribe un PDF de una página con texto embebido y xref válido."""
    commands = ["BT", "/F1 18 Tf", "50 750 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -25 Td")
        commands.append(f"({_escape_pdf_text(line)}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode("ascii"))
        document.extend(obj)
        document.extend(b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(document)
    return path


def _font(size: int = 28):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def build_scanned_image(kind: str, size: tuple[int, int] = (900, 700)) -> Image.Image:
    """Construye imágenes representativas con invariantes visuales estables."""
    background = 238 if kind == "ocr_malo" else 255
    foreground = 185 if kind == "ocr_malo" else 0
    image = Image.new("RGB", size, (background, background, background))
    draw = ImageDraw.Draw(image)
    font = _font()
    if kind in {"escaneado", "ocr_malo", "multilingue", "largo"}:
        lines = [
            "DOCUMENTO DE SALUD PUBLICA",
            "Objetivo metodos resultados conclusiones",
            "Health study methods and results",
            "Saude publica resultados e conclusoes",
        ]
        if kind == "largo":
            lines *= 8
        for index, line in enumerate(lines):
            draw.text((45, 35 + index * 42), line, fill=foreground, font=font)
    elif kind == "multicolumna":
        for index in range(12):
            draw.text(
                (35, 30 + index * 48), f"Izquierda {index} salud", fill=0, font=font
            )
            draw.text(
                (485, 30 + index * 48), f"Derecha {index} datos", fill=0, font=font
            )
    elif kind == "tabla":
        for x in range(60, 841, 195):
            draw.line((x, 80, x, 500), fill=0, width=3)
        for y in range(80, 501, 84):
            draw.line((60, y, 840, y), fill=0, width=3)
        draw.text((80, 25), "TABLA DE RESULTADOS", fill=0, font=font)
    elif kind == "grafico":
        draw.line((90, 600, 820, 600), fill=0, width=4)
        draw.line((90, 100, 90, 600), fill=0, width=4)
        for index, height in enumerate((120, 260, 180, 360)):
            left = 170 + index * 150
            draw.rectangle((left, 600 - height, left + 80, 600), fill=0)
        draw.text((180, 35), "GRAFICO DE INDICADORES", fill=0, font=font)
    else:
        raise ValueError(f"tipo de fixture desconocido: {kind}")
    return image


def write_scanned_pdf(path: Path, kind: str) -> Path:
    """Guarda una imagen sintética como PDF escaneado de una página."""
    image = build_scanned_image(kind)
    image.save(path, "PDF", resolution=150.0)
    image.close()
    return path


def write_corrupt_pdf(path: Path) -> Path:
    """Escribe una firma PDF truncada para ejercitar recuperación."""
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog")
    return path
