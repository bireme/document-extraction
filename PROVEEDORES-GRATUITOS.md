# Proveedores Gratuitos de LLMs en la Nube — Comparativa y Viabilidad

**Documento de referencia**: ¿Existen servicios gratuitos en la nube que permitan correr modelos LLM sin descargar localmente?

---

## 📋 Respuesta Corta

**SÍ, existen opciones gratuitas en la nube**, pero con limitaciones severas:

- ⚠️ **Cuotas muy bajas** (100-1000 requests/mes)
- ⚠️ **Velocidad lenta** (respuestas en 5-30 segundos)
- ⚠️ **Uptime no garantizado** (pausas aleatorias, throttling)
- ⚠️ **Modelos limitados** (no siempre tienes qwen2.5:7b)
- ⚠️ **Sin soporte técnico** (tier gratuito = lowest priority)

**Veredicto**: Adecuadas para **POC/testing**, NO para producción ni uso regular.

---

## 🎯 Tabla Comparativa: Servicios Gratuitos

| Proveedor | Cuota Gratuita | Velocidad | Modelos | Uptime | Ideal Para |
|-----------|---|---|---|---|---|
| **HuggingFace Inference** | 30K tokens/mes | 🟡 Lento (5-30s) | Limitados (Meta Llama2) | 🟡 Inestable | POC/testing |
| **Groq** | 9K requests/mes | 🟢 Muy rápido (<1s) | Llama2, Mixtral | 🟡 Inestable | Testing rápido |
| **Together.ai** | 1M tokens/mes | 🟢 Rápido (1-3s) | Llama2, Mistral | 🟡 Inestable | POC viable |
| **Replicate** | $5 créditos gratis | 🟡 Medio (3-5s) | Muchos modelos | 🟢 Estable | Testing |
| **Google Colab** | 12h sesiones | 🟡 Lento (CPU) | GPU limitada | 🟡 Resetea | Desarrollo local |
| **Modal Labs** | Tier gratuito | 🟡 Lento | Limitados | 🟡 Inestable | Testing |
| **Mistral API** | Sin free tier | - | Mistral models | 🟢 Estable | Pago solo |
| **OpenAI** | Sin free tier | - | GPT-4, etc | 🟢 Estable | Pago solo |
| **Anthropic** | Sin free tier | - | Claude | 🟢 Estable | Pago solo |

---

## 🔍 Análisis Detallado de Opciones Gratuitas

### 1️⃣ HuggingFace Inference API (Gratuito)

**URL**: https://huggingface.co/inference-api  
**Cuota**: 30,000 tokens/mes (≈ 12 documentos de 2.5K chars)

**Modelos disponibles gratis**:
- Meta Llama 2 (7B, 13B, 70B)
- Mistral 7B
- Zephyr 7B

**Pros**:
- ✅ Totalmente gratuito
- ✅ Variedad de modelos open source
- ✅ Acceso vía token (simple)

**Contras**:
- ❌ Cuota muy baja (30K tokens = 12-15 documentos)
- ❌ MUY lento (5-30s por request) — actualiza workers bajo demanda
- ❌ Uptime inestable (reseteos sin aviso)
- ❌ Rate limiting estricto
- ❌ NO hay qwen2.5:7b (tendríamos que usar Llama2 7B, menos bueno)

**Viabilidad para pdf-summarizer**: 🟡 BAJA
```python
# Estimación: 100 documentos/mes
# Cuota: 30K tokens
# Promedio per-doc: 300 tokens
# Alcanza para: ~100 docs ✓
# Pero: Velocidad + uptime hacen inviable en producción
```

**Cómo usaría**: 
```bash
curl https://api-inference.huggingface.co/models/meta-llama/Llama-2-7b \
  -H "Authorization: Bearer hf_..." \
  -X POST \
  -d '{"inputs": "Resume this text..."}'
```

---

### 2️⃣ Groq (Gratuito con créditos)

**URL**: https://console.groq.com  
**Cuota**: 9,000 requests/mes (créditos gratuitos)

**Modelos disponibles gratis**:
- Llama2 70B
- Mixtral 8x7B
- Whisper (transcripción)

**Pros**:
- ✅ MUY RÁPIDO (<1 segundo por request)
- ✅ Modelos potentes disponibles (Llama2 70B, Mixtral 8x7B)
- ✅ API compatible con OpenAI
- ✅ No hay rate limiting penalizado

**Contras**:
- ❌ Cuota baja (9K requests/mes = ~300 docs si cada uno es 1 request)
- ❌ Créditos gratuitos vencen en 30 días
- ❌ Sin garantía de uptime (SLA bajo)
- ❌ NO hay qwen2.5:7b
- ❌ Si necesitas más, es pago ($0.005/1M tokens = costoso)

**Viabilidad para pdf-summarizer**: 🟡 MEDIA (para testing solamente)
```python
# 9,000 requests/mes = 9,000 documentos
# Pero: Solo 30 días de crédito gratuito
# Después: $0.005/1M tokens = $0.001-0.002 por documento
# Mejor que OpenAI pero sigue siendo costo
```

**Cómo usaría** (compatible OpenAI API):
```python
import os
os.environ["GROQ_API_KEY"] = "gsk_..."

# La clase OpenAI adapter funcionaría:
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)
response = client.chat.completions.create(
    model="mixtral-8x7b-32768",
    messages=[...]
)
```

---

### 3️⃣ Together.ai (Gratuito con créditos)

**URL**: https://www.together.ai  
**Cuota**: 1,000,000 tokens/mes (créditos iniciales)

**Modelos disponibles gratis**:
- Llama 2 7B, 13B, 70B
- Mistral 7B
- Mixtral 8x7B
- Code Llama
- NeuralHermes

**Pros**:
- ✅ CUOTA GENEROSA (1M tokens/mes = 100-200 documentos)
- ✅ Modelos variados y potentes
- ✅ API compatible con OpenAI
- ✅ Velocidad razonable (1-3 segundos)
- ✅ Mejor uptime que HuggingFace

**Contras**:
- ❌ Créditos gratis vencen en 30 días
- ❌ Sin garantía de uptime
- ❌ NO hay qwen2.5:7b
- ❌ Después del crédito gratuito: $0.002/1M tokens

**Viabilidad para pdf-summarizer**: 🟡 MEDIA (mejor que HuggingFace para testing)
```python
# 1M tokens/mes = ~100-200 documentos
# 30 días de crédito gratuito
# Después: $0.002/1M tokens = muy barato, pero sigue siendo costo
```

**Cómo usaría** (compatible OpenAI API):
```python
import os
os.environ["TOGETHER_API_KEY"] = "sk-..."

client = OpenAI(
    api_key=os.environ.get("TOGETHER_API_KEY"),
    base_url="https://api.together.xyz/v1"
)
response = client.chat.completions.create(
    model="mistral-7b-instruct",
    messages=[...]
)
```

---

### 4️⃣ Replicate (Freemium)

**URL**: https://replicate.com  
**Cuota**: $5 créditos gratis (renovables con email)

**Modelos disponibles gratis**:
- Llama 2 7B, 13B, 70B
- Mistral
- CodeLlama
- Muchos otros

**Pros**:
- ✅ Créditos renovables cada mes (si completas verificación)
- ✅ Interfaz simple (web + API)
- ✅ Uptime relativamente estable
- ✅ Velocidad razonable (2-5s)

**Contras**:
- ❌ $5 créditos/mes = ~30-50 documentos
- ❌ Requiere email verificado
- ❌ API con formato distinto (no es compatible OpenAI)
- ❌ NO hay qwen2.5:7b

**Viabilidad para pdf-summarizer**: 🟡 BAJA (cuota muy pequeña)

---

### 5️⃣ Google Colab (Gratuito)

**URL**: https://colab.research.google.com  
**Cuota**: 12 horas/día GPU gratuita

**Ventajas**:
- ✅ Totalmente gratis
- ✅ GPU Tesla K80 / T4 gratis
- ✅ Excelente para desarrollo

**Desventajas**:
- ❌ Sesiones se resetean cada 12 horas
- ❌ GPU aleatoria (puede ser CPU solo)
- ❌ No es para producción
- ❌ Hay que ejecutar un notebook cada vez

**Viabilidad**: 🔴 NO VIABLE (solo para testing/desarrollo)

---

### 6️⃣ Modal Labs (Gratuito con limitaciones)

**URL**: https://modal.com  
**Cuota**: Tier gratuito limitado

**Pros**:
- ✅ Puedes desplegar tus propias funciones
- ✅ Soporte para GPU

**Contras**:
- ❌ Documentación compleja
- ❌ Cuota muy limitada
- ❌ Uptime no garantizado

**Viabilidad**: 🔴 NO VIABLE para este caso

---

## 💰 Comparativa de Costo

| Opción | Setup | Costo Mensual | Modelos | Uptime |
|--------|-------|---------------|---------|--------|
| **Ollama Local** | 2h (descargar) | $0 (GPU ya tienes) | Cualquiera | 100% |
| **HuggingFace Free** | 5min | $0 | Llama2 | 50% |
| **Groq Free (30 días)** | 5min | $0 (luego $0.005/1M) | Mixtral | 70% |
| **Together.ai Free (30 días)** | 5min | $0 (luego $0.002/1M) | Llama2 | 70% |
| **Replicate** | 5min | ~$5 | Llama2 | 80% |
| **OpenAI GPT-4** | 5min | $20-100 | GPT-4 | 99% |
| **Groq Pago** | 5min | $5-50 | Mixtral | 95% |

---

## 🎯 Recomendación por Caso de Uso

### Caso A: "Quiero POC/Testing sin costo"
**Mejor opción**: **Together.ai Free Tier**
```bash
# 1M tokens/mes gratuitos = 100-200 documentos
# Suficiente para testing
export TOGETHER_API_KEY="sk-..."
uv run pdfsum run --backend together --in ./pdfs
```

### Caso B: "Quiero MÁS velocidad en testing"
**Mejor opción**: **Groq Free Tier**
```bash
# 9K requests/mes, muy rápido (<1s)
# Ideal si quieres ver qué tal funciona rápido
export GROQ_API_KEY="gsk_..."
uv run pdfsum run --backend groq --in ./pdfs
```

### Caso C: "Quiero 100% gratuito y ESTABLE (local)"
**Mejor opción**: **Ollama + qwen2.5:7b**
```bash
ollama serve &
ollama pull qwen2.5:7b
uv run pdfsum run --in ./pdfs  # Ollama es default
# Gratis, local, privado, 100% uptime en tu máquina
```

### Caso D: "Quiero producción SIN GPU local"
**Mejor opción**: **Groq Pago** ($0.005/1M tokens, MUY rápido)
```bash
# O Together.ai ($0.002/1M tokens, más barato)
# O OpenAI ($0.01/1M tokens, mejor calidad)
```

### Caso E: "Desarrollo en cloud sin GPU"
**Mejor opción**: **Google Colab Free**
```bash
# Desplegar un notebook que corra summarization
# Solo para testing, no producción
```

---

## ⚠️ Limitaciones Críticas de "Gratuito"

### HuggingFace Inference API
```
Realidad: 30K tokens/mes
Documentos/mes: ~12
Velocidad: 5-30 segundos por documento
Uptime: Inestable (reseteos sin aviso)

VEREDICTO: Solo POC, no producción
```

### Groq Free
```
Realidad: 9K requests/mes (30 días)
Documentos/mes: ~300 (pero solo 30 días!)
Velocidad: <1 segundo (excelente)
Uptime: 70% (pausas aleatorias)

VEREDICTO: Bueno para testing rápido, luego pago
```

### Together.ai Free
```
Realidad: 1M tokens/mes (30 días)
Documentos/mes: ~100-200
Velocidad: 1-3 segundos (bueno)
Uptime: 70-80%

VEREDICTO: Mejor opción gratuita para POC
```

---

## 🏆 Conclusión: ¿Vale la Pena lo Gratuito?

### ✅ USAR GRATUITO SI:
- Solo haces **testing/POC** (máximo 30 días)
- Necesitas **<100 documentos/mes**
- La velocidad **no es crítica**
- Tienes **tiempo de esperar** (5-30s por doc)

### ❌ NO USAR GRATUITO SI:
- Necesitas **producción estable**
- Procesas **>100 documentos/mes**
- Necesitas **velocidad** (<5s)
- Requieres **uptime garantizado**

---

## 🎯 La Mejor Opción HOY (Análisis Honesto)

### Para la Mayoría de Equipos:

```
RANKING DE VIABILIDAD:

1. 🥇 OLLAMA LOCAL (GPU ≥ 8 GB)
   ├─ Costo: $0 (inversión GPU inicial)
   ├─ Velocidad: Rápida
   ├─ Uptime: 100% (en tu máquina)
   └─ Producción: ✅ LISTO

2. 🥈 GROQ PAGO (~$5-20/mes)
   ├─ Costo: Bajo ($0.005/1M tokens)
   ├─ Velocidad: Muy rápida (<1s)
   ├─ Uptime: 95%+
   └─ Producción: ✅ LISTO

3. 🥉 TOGETHER.AI PAGO (~$5-20/mes)
   ├─ Costo: Muy bajo ($0.002/1M tokens)
   ├─ Velocidad: Buena (1-3s)
   ├─ Uptime: 80-90%
   └─ Producción: ✅ VIABLE

4. 🟡 TOGETHER.AI GRATUITO (30 días)
   ├─ Costo: $0 (créditos vencen)
   ├─ Velocidad: Buena
   ├─ Uptime: 70%
   └─ Testing: ✅ SOLO POC

5. 🔴 HUGGINGFACE GRATUITO
   ├─ Costo: $0
   ├─ Velocidad: MUY lenta
   ├─ Uptime: Inestable
   └─ Testing: ⚠️ APENAS VIABLE
```

---

## 📊 Tabla Final: Gratuito vs Pago vs Local

```
┌──────────────────┬─────────────┬──────────────┬──────────────┐
│ Característica   │ Gratuito    │ Pago ($5-50) │ Ollama Local │
├──────────────────┼─────────────┼──────────────┼──────────────┤
│ Costo            │ $0 (30d)    │ $5-50/mes    │ $0 (GPU init)│
│ Docs/mes         │ 50-200      │ 1000-10000   │ Ilimitado    │
│ Velocidad        │ 3-30s       │ 1-5s         │ <2s          │
│ Uptime           │ 50-70%      │ 95%+         │ 100%         │
│ Privacidad       │ Nube        │ Nube         │ Local 100%   │
│ Producción       │ ❌ No       │ ✅ Sí        │ ✅ Sí        │
│ Setup            │ 5min        │ 5min         │ 1-2 horas    │
└──────────────────┴─────────────┴──────────────┴──────────────┘
```

---

## 🔗 Enlaces Útiles

- [HuggingFace Inference API](https://huggingface.co/inference-api)
- [Groq Console](https://console.groq.com)
- [Together.ai](https://www.together.ai)
- [Replicate](https://replicate.com)
- [Google Colab](https://colab.research.google.com)
- [Ollama (Local)](https://ollama.ai)

---

## 📝 Recomendación Final

**Para pdf-summarizer v0.11.0:**

1. **Mejor opción hoy**: **Ollama local** (si tienes GPU ≥ 8 GB)
   - Gratis después de inversión GPU
   - Privacidad total
   - 100% uptime
   
2. **Segunda mejor**: **Together.ai pago** ($0.002/1M tokens, muy barato)
   - Sin GPU requerida
   - Estable y rápido
   - Costo negligible

3. **Para testing temporal**: **Together.ai gratuito** (30 días)
   - POC rápido
   - Sin inversión
   - Luego hay que pagar o cambiar estrategia

**Evita**: HuggingFace Free (demasiado lento) + Google Colab (no es producción)

---

**Última actualización**: 2026-08-25  
**Versión**: v0.11.0
