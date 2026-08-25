# Arquitectura de Modelos — Estado Actual y Extensibilidad

**Documento de referencia**: Qué adaptadores están implementados, cuál es la arquitectura, y cómo agregar soporte para nuevos servicios (OpenRouter, OpenAI, Anthropic, etc).

---

## 📋 Estado Actual (v0.11.0)

### ✅ Adaptadores Implementados

| Adaptador | Ubicación | Estado | Modelo |
|-----------|-----------|--------|--------|
| **OllamaSummarizer** | `src/pdfsum/adapters/ollama_summarizer.py` | ✅ Completo | Ollama local (cualquier modelo) |
| **FakeSummarizer** | `src/pdfsum/adapters/fake_summarizer.py` | ✅ Tests only | Dummy (para testing/CI sin modelos) |
| **HybridOCR** | `src/pdfsum/adapters/hybrid_ocr.py` | ✅ Completo | Tesseract + Ollama VLM (fallback) |

### ❌ Adaptadores NO Implementados (Pero Posibles)

| Servicio | Soporte | Razón | Esfuerzo |
|----------|---------|-------|----------|
| **OpenAI API** | ❌ No | No está implementado | 🟡 Medio (HTTP + parsing) |
| **OpenRouter** | ❌ No | No está implementado | 🟡 Medio (HTTP compatible con OpenAI) |
| **Anthropic** | ❌ No | No está implementado | 🟡 Medio (HTTP + parsing distinto) |
| **HuggingFace** | ❌ No | No está implementado | 🟡 Medio (API REST) |
| **Replicate** | ❌ No | No está implementado | 🟡 Medio (webhooks async) |
| **AWS Bedrock** | ❌ No | No está implementado | 🟠 Alto (AWS SDK + auth) |

---

## 🏗️ Arquitectura Hexagonal — Por Qué Es Extensible

### Patrón: Protocol-Based Dependency

```python
# DOMINIO (contract.py) — Define la interfaz
@runtime_checkable
class Summarizer(Protocol):
    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        """Resume un texto, retorna {seccion: contenido}"""
        ...

# PIPELINE (pipeline.py) — Depende del Protocol, no de implementación
def summarize_document(
    doc_id: str,
    text: str,
    summarizer: Summarizer,  # ← Recibe cualquier cosa que implemente Protocol
    lang: str,
) -> SummaryResult:
    # El pipeline NO sabe si es Ollama, OpenAI, fake, etc.
    # Solo llama a summarizer.summarize(req)
    pass

# ADAPTADOR A (adapters/ollama_summarizer.py)
class OllamaSummarizer:
    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        # Lógica específica de Ollama HTTP
        pass

# ADAPTADOR B (sería adapters/openai_summarizer.py si existiera)
class OpenAISummarizer:
    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        # Lógica específica de OpenAI API
        pass
```

**Beneficio**: El dominio NO IMPORTA adaptadores. Cambiar de Ollama a OpenAI = cambiar 1 línea en la CLI, no tocar la pipeline.

---

## 🔌 Cómo Agregar un Nuevo Adaptador (OpenAI, OpenRouter, etc)

### Paso 1: Crear el Adaptador

**Archivo**: `src/pdfsum/adapters/openai_summarizer.py`

```python
"""Adaptador OpenAI del puerto Summarizer."""
import json
import os
import re
from ..contract import SummarizeRequest
from ..templates import section_names, section_keys

class OpenAISummarizer:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4-turbo",
        base_url: str = "https://api.openai.com/v1"
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY required")
        self.model = model
        self.base_url = base_url

    def _prompt(self, req: SummarizeRequest) -> str:
        """Construir prompt como OllamaSummarizer hace."""
        names = section_names(req.template, req.lang)
        schema = "\n".join(f"## {n}" for n in names)
        text = req.text[:42000]
        # Mismo formato de prompt que Ollama para consistencia
        return f"... prompt aquí ..."

    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        """Llamar OpenAI API, parsear respuesta, retornar secciones."""
        # 1. Construir prompt
        prompt = self._prompt(req)
        
        # 2. Llamar OpenAI (usar requests o urllib)
        import urllib.request
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Eres un catalogador..."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
        }).encode("utf-8")
        
        r = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )
        
        with urllib.request.urlopen(r, timeout=600) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            response_text = result["choices"][0]["message"]["content"]
        
        # 3. Parsear como OllamaSummarizer hace
        from ..adapters.ollama_summarizer import _parse_sections
        return _parse_sections(response_text, req.template, req.lang)
```

### Paso 2: Actualizar CLI para Soportar el Nuevo Adaptador

**Archivo**: `src/pdfsum/cli.py`

```python
def _build_summarizer(dry_run: bool, model: str, backend: str = "ollama"):
    if dry_run:
        from .adapters.fake_summarizer import FakeSummarizer
        return FakeSummarizer()
    
    if backend == "ollama":
        from .adapters.ollama_summarizer import OllamaSummarizer
        return OllamaSummarizer(model=model)
    
    elif backend == "openai":
        from .adapters.openai_summarizer import OpenAISummarizer
        return OpenAISummarizer(model=model)
    
    elif backend == "openrouter":
        from .adapters.openrouter_summarizer import OpenRouterSummarizer
        return OpenRouterSummarizer(model=model)
    
    else:
        raise ValueError(f"Unknown backend: {backend}")
```

### Paso 3: Actualizar Config.py para Especificar Backend

**Archivo**: `src/pdfsum/config.py`

```python
def get_summarizer_backend() -> str:
    """Obtener backend de summarizer desde config o env."""
    config = load_config()
    # CLI flag > config file > env var > default
    return config.get("summarizer_backend", "ollama")

def get_summarizer_model() -> str:
    """Obtener model de summarizer."""
    config = load_config()
    return config.get("model", "qwen2.5:7b")

def get_summarizer_api_key() -> str | None:
    """Obtener API key (OpenAI, Anthropic, etc)."""
    config = load_config()
    return config.get("api_key") or os.getenv("OPENAI_API_KEY")
```

### Paso 4: Actualizar CLI Arguments

**En cli.py**, agregar flag `--backend`:

```python
parser.add_argument(
    "--backend",
    choices=["ollama", "openai", "openrouter", "anthropic"],
    default="ollama",
    help="Modelo backend (ollama, openai, etc)"
)
```

### Paso 5: Usar en la Config

**Archivo**: `.pdfsum-config.json`

```json
{
  "summarizer_backend": "openai",
  "model": "gpt-4-turbo",
  "openai_api_key": "sk-...",
  "long_strategy": "hierarchical"
}
```

---

## ✅ ¿Puedes Usar OpenRouter Hoy?

### Respuesta Corta

**NO, no está implementado out-of-the-box.** Pero:
- ✅ La arquitectura LO PERMITE (Protocol-based)
- ✅ Agregar OpenRouter tomaría ~2-3 horas de desarrollo
- ✅ OpenRouter es compatible con OpenAI API (simple adapter)

### Respuesta Larga

**Opción A: Usar Ollama (recomendado hoy)**
```bash
ollama serve
ollama pull qwen2.5:7b
uv run pdfsum run --in ./pdfs --workspace ./data
```

**Opción B: Agregar OpenRouter (desarrollo necesario)**
1. Crear `src/pdfsum/adapters/openrouter_summarizer.py`
2. Actualizar `cli.py` para cargar el adaptador
3. Configurar API key en `~/.pdfsum-config.json`
4. `uv run pdfsum run --backend openrouter --model mistralai/mistral-7b`

**Opción C: Contribuir al Proyecto**
- Fork el repo en GitHub
- Crea rama `feat/openrouter-adapter`
- Envía PR
- ¡Bienvenido al proyecto!

---

## 📐 Comparativa: Esfuerzo de Agregar Cada Adaptador

| Servicio | Complejidad | Tiempo | Notas |
|----------|-------------|--------|-------|
| **OpenAI** | 🟡 Medio | 2-3h | API chat estándar, requiere API key |
| **OpenRouter** | 🟡 Medio | 1-2h | Compatible con OpenAI API (wrapper) |
| **Anthropic** | 🟡 Medio | 2-3h | API distinta (messages format), requiere key |
| **HuggingFace Inference** | 🟡 Medio | 2-3h | API REST simple, requiere token |
| **Replicate** | 🟠 Alto | 3-4h | Webhooks async, más complejo |
| **AWS Bedrock** | 🟠 Alto | 4-5h | SDK AWS + IAM auth, distinto |

---

## 🎯 Recomendación Arquitectónica

**Para Fase 12 (Distribución Moderna):**

Propongo implementar adaptadores para los 3 servicios más populares:

1. **OpenAI** (gpt-4-turbo, gpt-4o) — muy popular
2. **Anthropic** (claude-3-opus) — alta calidad
3. **OpenRouter** (cualquier modelo via proxy) — máxima flexibilidad

Esto tomaría ~1-2 sprints (2-3 semanas) y haría que pdfsum sea usar-able por 80% de usuarios sin GPU.

**Diseño propuesto:**
```
config.get_summarizer_backend()
  ├─ "ollama"     → OllamaSummarizer (local)
  ├─ "openai"     → OpenAISummarizer (gpt-4-turbo)
  ├─ "anthropic"  → AnthropicSummarizer (claude-3)
  └─ "openrouter" → OpenRouterSummarizer (proxy)

CLI: pdfsum run --backend openai --in ./pdfs
Config: echo '{"summarizer_backend": "openai"}' > ~/.pdfsum-config.json
```

---

## 🔐 Seguridad: Cómo Pasar API Keys

### ❌ Mala Práctica
```bash
pdfsum run --api-key "sk-..." --in ./pdfs  # NO: la key en historial bash
```

### ✅ Buena Práctica A: Variable de Entorno
```bash
export OPENAI_API_KEY="sk-..."
uv run pdfsum run --backend openai --in ./pdfs
```

### ✅ Buena Práctica B: Config File (privada)
```bash
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "openai",
  "openai_api_key": "sk-..."
}
EOF
chmod 600 ~/.pdfsum-config.json
uv run pdfsum run --in ./pdfs
```

### ✅ Buena Práctica C: .env (git-ignored)
```bash
echo 'OPENAI_API_KEY=sk-...' > .env.local
echo '.env.local' >> .gitignore
python -c "from dotenv import load_dotenv; load_dotenv('.env.local')"
```

---

## 📝 Resumen: Hoja de Ruta

| Fase | Adaptadores | Estado |
|------|-------------|--------|
| **v0.11.0 (actual)** | Ollama | ✅ Completo |
| **v0.12.0 (próx)** | Ollama + OpenAI | 📋 Planeado |
| **v0.13.0 (futuro)** | Ollama + OpenAI + Anthropic + OpenRouter | 📋 Planeado |

---

## 🙋 FAQs

**P: ¿Puedo usar OpenRouter HOY?**

R: No, no está implementado. Pero OpenRouter es compatible con OpenAI API, así que un adaptador OpenAI funcionaría. Contribuir al proyecto es bienvenido.

**P: ¿Es complicado agregar un nuevo adaptador?**

R: No mucho. 2-3 horas si ya entiendes el Protocol `Summarizer`. La arquitectura hexagonal hace que sea cambio mínimo.

**P: ¿El dominio se cambia cuando agrego nuevo adaptador?**

R: No, jamás. El dominio (`pipeline.py`, `contract.py`) no se toca. Solo la CLI y adaptadores.

**P: ¿Se puede cachivar/fallback entre adaptadores?**

R: SÍ, es teóricamente posible: si Ollama falla, caer a OpenAI. Pero actualmente no está implementado.

---

**Última actualización**: 2026-08-25  
**Versión**: v0.11.0  
**Autor**: PI Agent
