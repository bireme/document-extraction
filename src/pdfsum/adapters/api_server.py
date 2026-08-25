"""API de consulta de solo lectura sobre un directorio de lote (adaptador).

Sirve, con http.server (stdlib, sin dependencias), los resúmenes y el reporte
generados por `pdfsum batch`. Es local y de solo lectura. El dominio no importa
este módulo; es un adaptador de entrada.

Endpoints:
  GET /api/summaries           -> lista [{doc_id,tipo,idioma,qa_ok}]
  GET /api/summaries/<doc_id>  -> resumen completo (con _qa) | 404
  GET /api/report              -> report.json del lote | 404
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def _load_summaries(batch_dir: Path) -> list[dict]:
    out = []
    for f in sorted(batch_dir.glob("*.json")):
        if f.name in ("report.json", "_jobs.json"):
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        qa = d.get("_qa", {})
        out.append(
            {
                "doc_id": d.get("doc_id"),
                "tipo": d.get("tipo_documento"),
                "idioma": d.get("idioma_principal"),
                "qa_ok": qa.get("passed", None),
            }
        )
    return out


def make_handler(batch_dir: str):
    base = Path(batch_dir)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict | list) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *args) -> None:  # silenciar logs de stdlib
            pass

        def do_GET(self) -> None:
            path = self.path.rstrip("/")
            if path == "/api/summaries":
                self._send(200, _load_summaries(base))
            elif path.startswith("/api/summaries/"):
                doc_id = path.rsplit("/", 1)[-1]
                f = base / f"{doc_id}.json"
                if f.exists():
                    self._send(200, json.loads(f.read_text(encoding="utf-8")))
                else:
                    self._send(404, {"error": "not found", "doc_id": doc_id})
            elif path == "/api/report":
                f = base / "report.json"
                if f.exists():
                    self._send(200, json.loads(f.read_text(encoding="utf-8")))
                else:
                    self._send(404, {"error": "no report"})
            else:
                self._send(404, {"error": "unknown endpoint", "path": path})

    return Handler


def serve(batch_dir: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = HTTPServer((host, port), make_handler(batch_dir))
    print(f"pdfsum API en http://{host}:{port}  (Ctrl+C para parar)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
