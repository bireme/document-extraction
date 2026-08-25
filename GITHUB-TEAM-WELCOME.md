# 🎉 Bienvenida al Proyecto pdf-summarizer

**Repositorio público**: https://github.com/idourra/pdf-summarizer  
**Propietario**: Jose Andres Urra (@idourra)  
**Licencia**: MIT  
**Versión actual**: v0.11.0

---

## 📖 ¿Qué es pdf-summarizer?

Motor de resúmenes estructurados de documentos PDF con:
- **OCR híbrido**: poppler (texto nativo) + Tesseract (escaneos)
- **Resumen jerárquico**: detección de capítulos + estrategias coexistentes (excerpt/blocks/hierarchical)
- **QA integrado**: verificación de calidad, cobertura de términos clave
- **Export LILACS**: generación de registros para bases de datos biomédicas
- **Local-first**: no depende de APIs externas, todo corre localmente con Ollama

**Arquitectura**: Hexagonal + DDD (dominio puro, sin dependencias de adaptadores)

---

## ⚠️ Requisito Crítico ANTES de Empezar

**pdfsum necesita un modelo LLM**. Elige UNO:

**✅ Opción A: Ollama (local, recomendado)**
- Necesitas GPU con **≥ 8 GB VRAM**
- Instala Ollama: https://ollama.com
- Descargas modelos (6-9 GB): `ollama pull qwen2.5:7b`
- Ejecuta: `ollama serve` (en otra terminal, déjalo corriendo)
- Sin costos de API, privacidad total

**⚠️ Opción B: Servicios Remotos (OpenAI, Anthropic, etc.)**
- Si NO tienes GPU o GPU < 8 GB
- Obtén API key (OpenAI, Anthropic, etc.)
- Configura en `~/.pdfsum-config.json`
- Costo por uso, pero sin hardware

**Ver INSTALL.md Sección 2 para instrucciónes completas**

---

## 🚀 Inicio Rápido

### 1️⃣ Clonar el repo

```bash
git clone https://github.com/idourra/pdf-summarizer.git
cd pdf-summarizer
```

### 2️⃣ Configurar Modelo (Ollama O servicios remotos)

**Si usas Ollama:**
```bash
# Terminal 1: Ejecutar Ollama (dejar corriendo)
ollama serve

# Terminal 2: Descargar modelo
ollama pull qwen2.5:7b
```

**Si usas servicios remotos:**
```bash
echo '{
  "summarizer_backend": "openai",
  "openai_api_key": "sk-YOUR-KEY"
}' > ~/.pdfsum-config.json
```

### 3️⃣ Instalar (recomendado: uv)

```bash
uv sync                  # instala en ~1-2s (determinístico via uv.lock)
uv run pdfsum doctor     # verifica que Ollama/API está configurado ✓
uv run pdfsum verify     # confirma resultados sobre muestra
```

O con venv (legacy):
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 4️⃣ Usar

```bash
# Procesar PDFs desde directorio
uv run pdfsum run --in ./pdfs --workspace ./data --lang por

# Ver ayuda
uv run pdfsum --help
```

**Si ves error "XX ollama: no encontrado" en `pdfsum doctor`:**
- Opción A: Instala Ollama y ejecuta `ollama serve`
- Opción B: Configura API key de OpenAI/Anthropic en `~/.pdfsum-config.json`

**Documentación completa**: [`INSTALL.md`](INSTALL.md) | [`GUIA-USO.md`](GUIA-USO.md)

---

## 📋 Estado del Proyecto

| Fase | Versión | Estado | Cambios |
|------|---------|--------|---------|
| 10 | 0.10.0 | ✅ | Resumen jerárquico (13 capítulos, 100% cobertura) |
| 11 | 0.11.0 | ✅ | Migración a uv (10x más rápido, uv.lock) |
| 12 | Próxima | 📋 | Distribución moderna (wheel + PyPI) |

**Total de tests**: 97/97 OK ✓  
**Arquitectura**: Verificada (test_architecture.py, regla hexagonal) ✓  
**CI/CD**: GitHub Actions (lint, test, architecture) ✓

---

## 🤝 Guía para Colaborar

### Estructura del Repo

```
pdf-summarizer/
├── src/pdfsum/            # CÓDIGO FUENTE (dominio + adaptadores)
│   ├── contract.py        # Tipos + puertos (Summarizer, Transcriber)
│   ├── pipeline.py        # Orquestación
│   ├── chapters.py        # Detección de capítulos (Fase 10)
│   ├── adapters/          # Ollama, OCR, fakes (externos)
│   └── cli.py             # CLI
├── tests/                 # Suite de 97 tests unitarios + integración
├── evals/                 # Eval specs (EDD: Eval-Driven Development)
│   ├── eval-spec-fase10-*.yaml
│   ├── eval-spec-fase11-*.yaml
│   └── eval-spec-fase12-*.yaml
├── samples/               # Muestra de PDFs + control set
├── INSTALL.md             # Guía de instalación (3 opciones)
├── GUIA-USO.md            # Ejemplos de uso + trade-offs
├── README.md              # Intro + API
├── CHANGELOG.md           # Historial de versiones
└── uv.lock                # Lock file determinístico
```

### Workflow de Contribución

**Paso 0**: Asegúrate de tener los requisitos:
```bash
git clone https://github.com/idourra/pdf-summarizer.git
cd pdf-summarizer
uv sync
# Verifica que funciona
uv run pdfsum doctor
```

**Paso 1**: Crea una rama (no commits directo a master)
```bash
git checkout -b feat/tu-feature
# o: fix/tu-bugfix, chore/mantenimiento, docs/documentacion
```

**Paso 2**: Haz cambios + tests
```bash
# Edita código
uv run python -m unittest discover tests     # verifica que pasan
uv run ruff check src/ tests/                # lint
uv run pdfsum verify                         # verificación funcional
```

**Paso 3**: Commit descriptivo
```bash
git add ...
git commit -m "feat(modulo): descripción breve

Descripción larga si es necesario.
- Punto 1
- Punto 2

Refs: FASE-XX o GitHub issue si aplica"
```

**Paso 4**: Push + Pull Request
```bash
git push origin feat/tu-feature
# Abre PR en GitHub con descripción
```

**Paso 5**: Code review + merge
- GitHub Actions corre automáticamente (CI verde)
- Mantainer revisa + merge

---

## 📚 Conceptos Clave

### Eval-Driven Development (EDD)

Cada feature requiere un `eval-spec-*.yaml` antes de código:
```yaml
id: FASE12-DISTRIBUCION
criterios:
  - C1: wheel instalable en env limpio
  - C2: CI/CD publica en PyPI
tests:
  - run: uv run python -m unittest discover tests
  - run: uv build && ls dist/*.whl
```

**Archivo de referencia**: [`evals/eval-spec-fase12-distribucion-moderna-uv.yaml`](evals/eval-spec-fase12-distribucion-moderna-uv.yaml)

### Arquitectura Hexagonal

**Dominio** (puro, testeable) NO importa **Adaptadores** (externos):
- `src/pdfsum/contract.py` → Puertos: `Summarizer`, `Transcriber`
- `src/pdfsum/adapters/` → Implementaciones: Ollama, OCR, fakes
- Tests verifica: dominio ⊥ adaptadores ✓

**Verificación**: `python tests/test_architecture.py`

### Versionado

Semántico: MAJOR.MINOR.PATCH
- v0.10.0 → v0.11.0: MINOR bump (feature nueva: uv)
- v0.11.0 → v0.12.0: MINOR bump (distribución)
- v1.0.0: MAJOR (breaking change en API)

---

## 🛠️ Herramientas

| Herramienta | Para qué | Comando |
|---|---|---|
| `uv` | Gestor de deps (rápido) | `uv sync`, `uv run` |
| `ruff` | Lint + format | `uv run ruff check/format src/` |
| `unittest` | Tests | `uv run python -m unittest discover tests` |
| `gh` | GitHub CLI | `gh repo view`, `gh pr create` |
| `git` | Control de versión | Workflow EDD (rama → PR) |

---

## 📞 Contacto & Preguntas

**Repositorio**: https://github.com/idourra/pdf-summarizer  
**Issues**: [GitHub Issues](https://github.com/idourra/pdf-summarizer/issues)  
**Discussions**: [GitHub Discussions](https://github.com/idourra/pdf-summarizer/discussions) (si aplica)

**Mantainer**: Jose Andres Urra (@idourra)

---

## 📄 Licencia

MIT — Código abierto, uso libre con mención de autoría.

---

## 🎯 Próximos Pasos (Roadmap)

- **Fase 12** (actual): Distribución moderna (wheel + PyPI)
- **Fase 13** (roadmap): API REST / GraphQL público
- **Fase 14** (roadmap): Web UI para procesamiento interactivo
- **Fase 15** (roadmap): Soporte multiidioma mejorado (FR, EN, ES)

---

**¡Bienvenido al equipo! 🚀**

Cualquier duda, abre un issue o contacta al mantainer.
