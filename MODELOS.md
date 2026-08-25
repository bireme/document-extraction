# Configuración de Modelos — Ollama Local vs. Servicios Remotos

**Documento de referencia**: Cómo elegir, instalar y configurar el backend de modelos para pdf-summarizer.

---

## 📋 Tabla de Decisión Rápida

| Tengo... | Recomendación | Costo | Privacidad | Complejidad |
|---|---|---|---|---|
| **GPU RTX/GTX ≥ 8 GB** | Ollama local (qwen2.5:7b) | $0 | ✅✅✅ | Media |
| **GPU RTX/GTX < 8 GB** | Servicios remotos | $0.01-0.10/doc | ⚠️ | Baja |
| **Sin GPU** | Servicios remotos | $0.01-0.10/doc | ⚠️ | Baja |
| **Laptop pobre** | CPU local (lento) O remotos | $0 O $0.01+ | ✅✅ O ⚠️ | Media O Baja |

---

## ✅ OPCIÓN A: Modelos Locales con Ollama

### ¿Qué es Ollama?

Ollama es un runtime que:
- Descarga modelos LLM preentrenados (ej: Llama 2, Qwen, Mistral)
- Los carga en GPU/CPU y expone una API REST local
- Todo corre en tu máquina (sin internet después de descargar modelos)
- Gratis, sin costos por uso

### Requisitos Hardware

| Componente | Mínimo | Recomendado |
|---|---|---|
| **GPU VRAM** | 8 GB (tight) | 12+ GB (confortable) |
| **GPU compatible** | NVIDIA (CUDA 11.8+), AMD (ROCm) | NVIDIA RTX serie reciente |
| **RAM del sistema** | 16 GB | 32 GB |
| **Disco para modelos** | 10 GB (dos modelos) | 20 GB (para futuras versiones) |

**GPUs probadas:**
- ✅ RTX 5060 Laptop (8 GB VRAM) — ajustado pero funciona
- ✅ RTX 4070 (12 GB) — cómodo
- ✅ RTX 4090 (24 GB) — sobrado

**GPUs no recomendadas:**
- ❌ RTX 3050 (6 GB) — demasiado chica
- ❌ Intel Arc < 8 GB — soporte limitado
- ❌ MacBook M1/M2 (CPU only) — muy lento

### Instalación

#### 1️⃣ Instalar Ollama

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
# O descargar desde https://ollama.ai/download
```

**macOS:**
```bash
# Descargar .dmg desde https://ollama.ai/download
# O vía Homebrew:
brew install ollama
```

**Windows:**
```bash
# Descargar installer desde https://ollama.ai/download
# O vía WSL2 + Linux steps arriba
```

#### 2️⃣ Verificar Ollama

```bash
ollama --version
# → ollama version 0.x.x

# Verificar que la GPU es detectada
ollama info
# Debe mostrar GPUs disponibles
```

#### 3️⃣ Descargar Modelos

```bash
# Esencial (6.3 GB, requerido para pdfsum)
ollama pull qwen2.5:7b

# Opcional (8.8 GB, para OCR avanzado de escaneos difíciles)
ollama pull qwen3-vl:8b-instruct

# Ver modelos instalados
ollama list
# → NAME              ID              SIZE      MODIFIED
#   qwen2.5:7b        1234567890ab    6.3 GB    2 minutes ago
```

#### 4️⃣ Ejecutar Ollama (IMPORTANTE: dejar corriendo)

```bash
# Terminal separada, dejar ejecutándose
ollama serve

# → listening on 127.0.0.1:11434
```

**Verificar que está corriendo:**
```bash
# En otra terminal
curl http://localhost:11434/api/tags
# Debe retornar JSON con lista de modelos
```

### Configurar pdfsum para Ollama

**Opción 1: Automático (default)**
```bash
# pdfsum busca Ollama en localhost:11434
uv run pdfsum doctor
# Si ves "OK ollama: corriendo" → listo ✓
```

**Opción 2: Configurar explícitamente**
```bash
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "ollama",
  "ollama_base_url": "http://localhost:11434",
  "ollama_model": "qwen2.5:7b"
}
EOF
```

### Ventajas y Desventajas

✅ **Ventajas:**
- Sin costo recurrente (solo inversión GPU inicial)
- Privacidad: datos NO salen de tu máquina
- Velocidad: GPU local es rápida (después de cargar modelo)
- Sin dependencia de internet después de descargar
- Control total sobre qué modelo usar

❌ **Desventajas:**
- Requiere GPU potente (≥ 8 GB VRAM)
- Modelos ocupan 6-9 GB en disco
- Tiempo de descarga inicial (30+ minutos depende ISP)
- Tiempo de carga en memoria (5-10s primera invocación)
- Mantenimiento (actualizar modelos periódicamente)

---

## ⚠️ OPCIÓN B: Servicios Remotos (OpenAI, Anthropic, HuggingFace)

### ¿Cuándo usar Servicios Remotos?

- ✅ No tienes GPU (o GPU < 8 GB)
- ✅ Quieres máxima calidad (GPT-4, Claude 3)
- ✅ Procesamiento ocasional (pocos docs al mes)
- ✅ Máxima privacidad NO es requisito
- ✅ No quieres mantener modelos locales

### Requisitos

- API key de proveedor (OpenAI, Anthropic, etc.)
- Suscripción pagada o créditos
- Conexión a internet durante procesamiento

### Proveedores Recomendados

| Proveedor | Modelo Recomendado | Costo* | Velocidad | Calidad |
|---|---|---|---|---|
| **OpenAI** | gpt-4-turbo | $0.01-0.03/doc | Rápido | Excelente |
| **Anthropic** | claude-3-opus | $0.015-0.05/doc | Medio | Excelente |
| **HuggingFace** | mistral-medium | $0.0007/doc | Rápido | Bueno |
| **Replicate** | Llama 2 70B | $0.005/doc | Medio | Bueno |

*Estimación por documento de 10K caracteres (puede variar)

### Configuración

#### OpenAI

```bash
# 1. Obtén API key en https://platform.openai.com/account/api-keys
export OPENAI_API_KEY="sk-..."

# 2. O configura en ~/.pdfsum-config.json
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "openai",
  "openai_api_key": "sk-...",
  "openai_model": "gpt-4-turbo",
  "transcriber_backend": "openai"
}
EOF

# 3. Verificar
uv run pdfsum doctor
# Debe mostrar "OK openai: api key configured"
```

#### Anthropic (Claude 3)

```bash
# 1. Obtén API key en https://console.anthropic.com/account/keys
export ANTHROPIC_API_KEY="sk-ant-..."

# 2. O configura en ~/.pdfsum-config.json
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "anthropic",
  "anthropic_api_key": "sk-ant-...",
  "anthropic_model": "claude-3-opus-20240229"
}
EOF

# 3. Verificar
uv run pdfsum doctor
# Debe mostrar "OK anthropic: api key configured"
```

#### HuggingFace

```bash
# 1. Obtén token en https://huggingface.co/settings/tokens
export HF_API_KEY="hf_..."

# 2. Configura en ~/.pdfsum-config.json
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "huggingface",
  "hf_api_key": "hf_...",
  "hf_model": "mistralai/Mistral-7B"
}
EOF
```

### Ventajas y Desventajas

✅ **Ventajas:**
- No requiere GPU local
- Modelos de última generación (GPT-4, Claude 3)
- Escalable: procesa lo que necesites sin límite local
- Bajo mantenimiento (actualizaciones automáticas)
- Acceso a múltiples modelos

❌ **Desventajas:**
- Costo recurrente por uso ($0.01-0.10 por documento)
- Datos enviados a servidores externos (privacidad)
- Dependencia de internet
- Latencia de red (más lento que local)
- Limitaciones de rate limiting (100+ req/min en OpenAI)

---

## 🔀 Comparativa: Ollama vs. Servicios Remotos

```
OLLAMA LOCAL                           SERVICIOS REMOTOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Costo:       $0/mes (GPU init)        $0.01-0.10/doc
Privacidad:  🔒 Datos locales         🌐 Datos en cloud
Calidad:     Bueno (Qwen 7B)          Excelente (GPT-4, Claude 3)
Velocidad:   Rápido (GPU)             Medio (red)
Setup:       Media (descargar, 30min) Baja (API key, 5min)
GPU:         Requiere ≥8 GB           No requiere GPU
Escalabilidad: Limitada (GPU local)   Ilimitada
Offline:     ✓ Después de descargar   ✗ Requiere internet
Mantenimiento: Manual (actualizaciones) Automático
```

---

## 🐛 Troubleshooting

### Ollama

**Problema**: `curl: (7) Failed to connect to localhost port 11434`

**Solución**:
```bash
# Verificar que Ollama está corriendo
ollama serve
# En otra terminal, probar:
curl http://localhost:11434/api/tags
```

**Problema**: `qwen2.5:7b: out of memory`

**Solución**:
- Reducir tamaño de batch: `--batch-size 4` en pdfsum
- O cambiar a modelo más pequeño: `ollama pull qwen2.5:3b`
- O usar servicios remotos

**Problema**: `qwen2.5:7b: not downloaded`

**Solución**:
```bash
ollama pull qwen2.5:7b
# Esperar descarga completa (20-40 minutos)
```

### Servicios Remotos

**Problema**: `401 Unauthorized`

**Solución**:
```bash
# Verificar que API key es correcta
echo $OPENAI_API_KEY
# Debe empezar con "sk-"

# Revisar permisos de API key en https://platform.openai.com/account/api-keys
```

**Problema**: `429 Too many requests`

**Solución**:
- Reducir rate de procesamiento
- O esperar a que se levante el límite

---

## 📊 Costo Estimado

### Ollama Local

```
Inversión inicial: GPU RTX 4070 (~$500-700 USD)
Costo operativo: $0 (solo electricidad, ~$0.005 por doc si GPU 5 años)
Payback: ~50-100 documentos (1-2 semanas de trabajo)
```

### Servicios Remotos (OpenAI GPT-4 Turbo)

```
Inversión inicial: $0
Costo por documento (10K chars): ~$0.03
100 documentos: $3
1000 documentos: $30
10000 documentos: $300
```

---

## 🎯 Recomendación Final

| Perfil | Elección | Razón |
|---|---|---|
| Investigador con GPU | **Ollama** | Privacidad + bajo costo |
| Desarrollador sin GPU | **OpenAI/Anthropic** | Simplicidad + calidad |
| Producción a gran escala | **Ollama** + GPU potente | ROI en 2-3 meses |
| Procesamiento ocasional | **Servicios remotos** | Sin costos fijos |
| Máxima privacidad | **Ollama** | Datos nunca salen de casa |
| Máxima calidad (GPT-4) | **Servicios remotos** | Mejor modelo disponible |

---

## 📚 Referencias

- [Ollama Official Docs](https://ollama.ai)
- [OpenAI API Docs](https://platform.openai.com/docs)
- [Anthropic Claude Docs](https://docs.anthropic.com)
- [HuggingFace Hub](https://huggingface.co)

---

**Última actualización**: 2026-08-25  
**Versión**: v0.11.0
