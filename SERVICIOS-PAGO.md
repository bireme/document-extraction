# Servicios de Pago para LLMs — Guía de Integración con pdf-summarizer

**Documento de referencia**: Cómo usar OpenRouter, Anthropic, OpenAI y DeepSeek con pdf-summarizer. Comparativa de precios, calidad y configuración.

---

## 📋 Tabla Comparativa Rápida

| Proveedor | Precio | Modelos | Velocidad | Calidad | Uptime | Ideal Para |
|-----------|--------|---------|-----------|---------|--------|-----------|
| **OpenRouter** | $0.0002-0.001/1K | 100+ (cualquiera) | 1-3s | Variable | 95% | Flexibilidad máxima |
| **OpenAI** | $0.003-0.015/1K | GPT-4, GPT-4o | 1-2s | Excelente | 99.9% | Máxima calidad |
| **Anthropic** | $0.003-0.015/1K | Claude 3 | 1-2s | Excelente | 99.9% | Seguridad + calidad |
| **DeepSeek** | $0.00014/1K | DeepSeek-Chat | 2-3s | Bueno | 95% | Mejor precio |
| **Groq** | $0.005/1M | Llama, Mixtral | <1s | Bueno | 95% | Máxima velocidad |
| **Together.ai** | $0.002/1M | Llama, Mistral | 1-3s | Bueno | 90% | Balance costo/calidad |

---

## 🎯 1. OpenRouter (Proxy/Agregador)

**URL**: https://openrouter.ai  
**Descripción**: Proxy que permite acceder a 100+ modelos con una sola API key

### ✅ Ventajas
- 100+ modelos disponibles (OpenAI, Anthropic, Meta, Mistral, etc.)
- Una sola API key, múltiples modelos
- Excelente para probar diferentes modelos
- Interfaz compatible con OpenAI API
- Buen soporte técnico

### 💰 Precios (estimado por 1M tokens)

```
Modelos económicos:
  • Mistral 7B:         $0.00014/1K tokens
  • Llama 2 70B:        $0.0007/1K tokens
  • Qwen 72B:           $0.0009/1K tokens

Modelos mid-range:
  • Claude 3 Haiku:     $0.00025/1K tokens
  • GPT-3.5 Turbo:      $0.0005/1K tokens

Modelos premium:
  • Claude 3 Opus:      $0.015/1K tokens
  • GPT-4 Turbo:        $0.01/1K tokens
  • GPT-4o:             $0.005/1K tokens
```

### 📊 Costo estimado para pdf-summarizer

```
100 documentos × 300 tokens c/u = 30K tokens
Con Mistral 7B:  30K × $0.00014 = $0.0042 (extremadamente barato)
Con Llama 2 70B: 30K × $0.0007  = $0.021
Con GPT-4 Turbo: 30K × $0.01    = $0.30
```

### 🔧 Configuración

**Paso 1: Obtener API Key**
```bash
# Ir a https://openrouter.ai
# Sign up → Create API key
# Copiar la key: sk-or-...
```

**Paso 2: Configurar pdfsum**
```bash
# Opción A: Variable de entorno
export OPENROUTER_API_KEY="sk-or-..."

# Opción B: Config file (~/.pdfsum-config.json)
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "openai",
  "openai_api_key": "sk-or-...",
  "openai_base_url": "https://openrouter.ai/api/v1",
  "model": "mistralai/mistral-7b-instruct"
}
EOF
```

**Paso 3: Usar (después de crear adaptador)**
```bash
# Cuando el adaptador OpenRouter esté implementado:
uv run pdfsum run --backend openrouter --model mistralai/mistral-7b \
  --in ./pdfs --workspace ./data
```

### 📋 Modelos Recomendados en OpenRouter

```
ECONÓMICOS (< $0.001/1K):
  mistralai/mistral-7b-instruct    $0.00014
  qwen/qwen-72b-chat               $0.0009
  meta-llama/llama-2-70b-chat      $0.0007

MID-RANGE ($0.001-0.005/1K):
  anthropic/claude-3-haiku         $0.00025
  openai/gpt-3.5-turbo             $0.0005
  microsoft/phi-3-mini             $0.00004

PREMIUM ($0.005-0.015/1K):
  openai/gpt-4-turbo               $0.01
  openai/gpt-4o                    $0.005
  anthropic/claude-3-opus          $0.015
```

### ⚡ Ventaja Clave
OpenRouter permite **cambiar de modelo sin cambiar código**:
```bash
# Probar con Mistral (barato)
uv run pdfsum run --model mistralai/mistral-7b --in ./pdfs

# Probar con GPT-4 (premium)
uv run pdfsum run --model openai/gpt-4-turbo --in ./pdfs

# Probar con Claude 3 Opus (excelente)
uv run pdfsum run --model anthropic/claude-3-opus --in ./pdfs
```

---

## 🎯 2. OpenAI (API Oficial)

**URL**: https://platform.openai.com  
**Descripción**: API oficial de OpenAI (GPT-4, GPT-4o, etc.)

### ✅ Ventajas
- Mejor calidad de modelos (GPT-4 es superior)
- SLA garantizado (99.9% uptime)
- Soporte técnico prioritario
- Documentación excelente
- Mayor rate limit

### ⚠️ Desventajas
- Más caro que OpenRouter
- No puedes elegir entre múltiples proveedores
- Requiere tarjeta de crédito verificada

### 💰 Precios Oficiales (2026)

```
GPT-3.5 Turbo:
  Input:  $0.0005/1K tokens
  Output: $0.0015/1K tokens

GPT-4 Turbo:
  Input:  $0.01/1K tokens
  Output: $0.03/1K tokens

GPT-4o (recommended):
  Input:  $0.005/1K tokens
  Output: $0.015/1K tokens
```

### 📊 Costo para pdf-summarizer

```
Suposición: 300 tokens input, 200 tokens output
Costo por documento:
  GPT-3.5:  (300×0.0005 + 200×0.0015) = $0.00045
  GPT-4o:   (300×0.005 + 200×0.015)   = $0.0045
  GPT-4T:   (300×0.01 + 200×0.03)     = $0.009

100 documentos/mes:
  GPT-3.5:  $0.045 (muy barato)
  GPT-4o:   $0.45  (muy bueno)
  GPT-4T:   $0.90  (premium)
```

### 🔧 Configuración

**Paso 1: Crear Cuenta y API Key**
```bash
# 1. Ir a https://platform.openai.com
# 2. Sign up (necesita verificación)
# 3. Agregar tarjeta de crédito
# 4. Ir a API keys → Create new secret key
# 5. Copiar: sk-proj-...
```

**Paso 2: Establecer Budget (recomendado)**
```bash
# En platform.openai.com → Billing → Usage limits
# Establecer límite máximo (ej: $10/mes)
```

**Paso 3: Configurar pdfsum**
```bash
# Variable de entorno
export OPENAI_API_KEY="sk-proj-..."

# O config file (~/.pdfsum-config.json)
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "openai",
  "openai_api_key": "sk-proj-...",
  "model": "gpt-4o"
}
EOF
```

**Paso 4: Usar**
```bash
# Cuando el adaptador esté implementado:
uv run pdfsum run --backend openai --model gpt-4o \
  --in ./pdfs --workspace ./data
```

### ✨ Modelos Recomendados

```
MEJOR RELACIÓN COSTO/CALIDAD:
  gpt-4o (recomendado)
  • Precio: $0.005 input, $0.015 output
  • Velocidad: 1-2s
  • Calidad: Excelente
  
MÁXIMA CALIDAD:
  gpt-4-turbo
  • Precio: $0.01 input, $0.03 output (2x más caro)
  • Velocidad: 1-2s
  • Calidad: Ligeramente mejor (marginal)

PRESUPUESTO LIMITADO:
  gpt-3.5-turbo
  • Precio: $0.0005 input, $0.0015 output
  • Velocidad: <1s
  • Calidad: Buena (no excelente)
```

---

## 🎯 3. Anthropic (Claude)

**URL**: https://console.anthropic.com  
**Descripción**: API oficial de Anthropic (modelos Claude)

### ✅ Ventajas
- Mejor en reasoning y análisis de texto largo
- Excelente para tareas complejas
- Modelo más "seguro" (menos hallucinations)
- Soporte a contexto muy largo (200K tokens)
- Documentación clara

### ⚠️ Desventajas
- Más caro que OpenAI para la mayoría de casos
- Menos puntos de presencia global (un poco más lento)
- Menos integrable (menos herramientas)

### 💰 Precios (Claude 3)

```
Claude 3 Haiku (económico):
  Input:  $0.00025/1K tokens
  Output: $0.00125/1K tokens

Claude 3 Sonnet (balance):
  Input:  $0.003/1K tokens
  Output: $0.015/1K tokens

Claude 3 Opus (premium):
  Input:  $0.015/1K tokens
  Output: $0.075/1K tokens
```

### 📊 Costo para pdf-summarizer

```
100 documentos × (300 input + 200 output):

Claude 3 Haiku:  (300×0.00025 + 200×0.00125) = $0.000325  ← BARATO
Claude 3 Sonnet: (300×0.003 + 200×0.015)     = $0.0039
Claude 3 Opus:   (300×0.015 + 200×0.075)     = $0.019    ← PREMIUM

Mes (100 docs):
  Haiku:  $0.0325 (extremadamente barato)
  Sonnet: $0.39   (muy bueno)
  Opus:   $1.90   (calidad máxima)
```

### 🔧 Configuración

**Paso 1: Crear Cuenta y API Key**
```bash
# 1. Ir a https://console.anthropic.com
# 2. Sign up
# 3. Agregar tarjeta de crédito
# 4. Ir a API keys → Create key
# 5. Copiar: sk-ant-...
```

**Paso 2: Configurar pdfsum**
```bash
# Variable de entorno
export ANTHROPIC_API_KEY="sk-ant-..."

# O config file
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "anthropic",
  "anthropic_api_key": "sk-ant-...",
  "model": "claude-3-5-sonnet-20241022"
}
EOF
```

**Paso 3: Usar**
```bash
uv run pdfsum run --backend anthropic --model claude-3-opus \
  --in ./pdfs --workspace ./data
```

### ✨ Modelos Recomendados

```
MEJOR RELACIÓN COSTO/CALIDAD:
  claude-3-5-sonnet (RECOMENDADO 2026)
  • Precio: $0.003 input, $0.015 output
  • Velocidad: 1-2s
  • Calidad: Excelente (mejor que GPT-4 en muchos casos)

MÁXIMA CALIDAD (si el presupuesto lo permite):
  claude-3-opus
  • Precio: $0.015 input, $0.075 output
  • Velocidad: 1-3s
  • Calidad: Máxima (mejor reasoning)

PRESUPUESTO LIMITADO:
  claude-3-haiku
  • Precio: $0.00025 input, $0.00125 output
  • Velocidad: <1s
  • Calidad: Buena (suficiente para resúmenes)
```

---

## 🎯 4. DeepSeek (China, Muy Económico)

**URL**: https://platform.deepseek.com  
**Descripción**: API de DeepSeek (modelo chino, extremadamente económico)

### ✅ Ventajas
- **PRECIO EXTREMADAMENTE BAJO** ($0.00014/1K tokens, igual que Mistral)
- Excelente relación costo/rendimiento
- Modelo open source disponible
- Bueno para tareas de codificación
- Velocidad razonable

### ⚠️ Desventajas
- Documentación limitada (en chino)
- Uptime menos garantizado
- Modelo no tan pulido como GPT-4 o Claude
- Disponibilidad en algunas regiones limitada

### 💰 Precios

```
DeepSeek-Chat:
  Input:  $0.00014/1K tokens
  Output: $0.00028/1K tokens

(Precio más bajo del mercado)
```

### 📊 Costo para pdf-summarizer

```
100 documentos × (300 input + 200 output):
  DeepSeek: (300×0.00014 + 200×0.00028) = $0.000098

Mes (100 docs): $0.0098 (menos de 1 centavo!)
Año (1200 docs): $0.12 (MUY BARATO)
```

### 🔧 Configuración

**Paso 1: Obtener API Key**
```bash
# 1. Ir a https://platform.deepseek.com
# 2. Sign up
# 3. Agregar tarjeta de crédito
# 4. Crear API key
# 5. Copiar: sk-...
```

**Paso 2: Configurar pdfsum**
```bash
# Variable de entorno
export DEEPSEEK_API_KEY="sk-..."

# O config file
cat > ~/.pdfsum-config.json << 'EOF'
{
  "summarizer_backend": "openai",
  "openai_api_key": "sk-...",
  "openai_base_url": "https://api.deepseek.com",
  "model": "deepseek-chat"
}
EOF
```

**Paso 3: Usar**
```bash
# Compatible con OpenAI API
uv run pdfsum run --backend openai --model deepseek-chat \
  --in ./pdfs --workspace ./data
```

### ✨ Cuando Usar DeepSeek

```
✅ Perfecto para:
  • Presupuesto MUY limitado (<$1/mes)
  • Testing masivo (miles de documentos)
  • Producción sensible al costo
  • Desarrollo/POC (calidad no crítica)

❌ NO use para:
  • Máxima calidad requerida
  • Documentos muy complejos
  • Análisis de texto crítico
```

---

## 📊 Tabla Comparativa Completa

```
┌─────────────────┬──────────────┬────────┬────────┬────────┐
│ Proveedor       │ Precio       │ Calidad│Velocidad│Uptime │
├─────────────────┼──────────────┼────────┼────────┼────────┤
│ DeepSeek        │ $0.00014/1K  │ Bueno  │ 2-3s   │ 95%    │
│ OpenRouter      │ $0.0002-0.015│ Variable│1-3s   │ 95%    │
│ Together.ai     │ $0.002/1M    │ Bueno  │ 1-3s   │ 90%    │
│ Groq            │ $0.005/1M    │ Bueno  │ <1s    │ 95%    │
│ Claude 3 Haiku  │ $0.00025/1K  │ Bueno  │ 1-2s   │ 99.9%  │
│ GPT-3.5         │ $0.0005/1K   │ Bueno  │ <1s    │ 99.9%  │
│ Claude 3 Sonnet │ $0.003/1K    │ Excelente│1-2s  │ 99.9%  │
│ GPT-4o          │ $0.005/1K    │ Excelente│1-2s  │ 99.9%  │
│ GPT-4 Turbo     │ $0.01/1K     │ Excelente│1-2s  │ 99.9%  │
│ Claude 3 Opus   │ $0.015/1K    │ Máxima │ 1-3s   │ 99.9%  │
└─────────────────┴──────────────┴────────┴────────┴────────┘

Para pdf-summarizer (100 docs/mes × 500 tokens promedio):
DeepSeek:       $0.01/mes
OpenRouter+MIS: $0.02/mes
GPT-3.5:        $0.03/mes
Claude Haiku:   $0.03/mes
GPT-4o:         $0.25/mes
Claude Sonnet:  $0.25/mes
Claude Opus:    $1.50/mes
```

---

## 🎯 Recomendaciones por Caso de Uso

### Caso 1: "Presupuesto Mínimo (<$1/mes)"
**Mejor opción**: **DeepSeek** o **OpenRouter + Mistral 7B**
```bash
export DEEPSEEK_API_KEY="sk-..."
uv run pdfsum run --backend openai --model deepseek-chat \
  --in ./pdfs --workspace ./data

# Costo: ~$0.01/mes para 100 docs
```

### Caso 2: "Balance Costo/Calidad"
**Mejor opción**: **OpenRouter + Claude 3.5 Sonnet** o **GPT-4o**
```bash
export OPENROUTER_API_KEY="sk-or-..."
uv run pdfsum run --backend openrouter --model anthropic/claude-3.5-sonnet \
  --in ./pdfs --workspace ./data

# Costo: ~$0.20/mes para 100 docs
```

### Caso 3: "Máxima Velocidad + Calidad"
**Mejor opción**: **OpenRouter + GPT-4o** o **Groq**
```bash
export OPENROUTER_API_KEY="sk-or-..."
uv run pdfsum run --backend openrouter --model openai/gpt-4o \
  --in ./pdfs --workspace ./data

# Costo: ~$0.25/mes, velocidad <2s
```

### Caso 4: "Máxima Calidad Sin Límite"
**Mejor opción**: **OpenAI GPT-4 Turbo** o **Claude 3 Opus**
```bash
export OPENAI_API_KEY="sk-proj-..."
uv run pdfsum run --backend openai --model gpt-4-turbo \
  --in ./pdfs --workspace ./data

# Costo: ~$0.50/mes, máxima calidad
```

### Caso 5: "Flexibilidad (Probar Todos)"
**Mejor opción**: **OpenRouter**
```bash
export OPENROUTER_API_KEY="sk-or-..."

# Probar Mistral barato:
uv run pdfsum run --backend openrouter --model mistralai/mistral-7b ...

# Cambiar a Claude sin reconfigura:
uv run pdfsum run --backend openrouter --model anthropic/claude-3-opus ...

# Cambiar a GPT-4:
uv run pdfsum run --backend openrouter --model openai/gpt-4-turbo ...
```

---

## 🔧 Implementación: Crear Adaptadores

### Adaptador Genérico OpenAI-Compatible

Todos estos servicios son **compatibles con OpenAI API**:
- OpenRouter
- DeepSeek
- Mistral API
- Together.ai

Esto significa: **Un solo adaptador funciona para todos ellos**

```python
# src/pdfsum/adapters/openai_compatible_summarizer.py
class OpenAICompatibleSummarizer:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str = "https://api.openai.com/v1"
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        # Compatible con OpenAI, OpenRouter, DeepSeek, etc.
    
    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        import urllib.request
        import json
        
        prompt = self._prompt(req)  # Mismo que OllamaSummarizer
        
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
        
        # Parsear como OllamaSummarizer
        from .ollama_summarizer import _parse_sections
        return _parse_sections(response_text, req.template, req.lang)
```

### CLI Actualizada

```python
# En cli.py
def _build_summarizer(
    dry_run: bool,
    backend: str = "ollama",
    model: str = "qwen2.5:7b",
    api_key: str = None
):
    if dry_run:
        from .adapters.fake_summarizer import FakeSummarizer
        return FakeSummarizer()
    
    if backend == "ollama":
        from .adapters.ollama_summarizer import OllamaSummarizer
        return OllamaSummarizer(model=model)
    
    elif backend in ["openai", "openrouter", "deepseek", "together"]:
        from .adapters.openai_compatible_summarizer import OpenAICompatibleSummarizer
        
        base_urls = {
            "openai": "https://api.openai.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "deepseek": "https://api.deepseek.com",
            "together": "https://api.together.xyz/v1"
        }
        
        return OpenAICompatibleSummarizer(
            api_key=api_key or os.getenv(f"{backend.upper()}_API_KEY"),
            model=model,
            base_url=base_urls[backend]
        )
    
    elif backend == "anthropic":
        from .adapters.anthropic_summarizer import AnthropicSummarizer
        return AnthropicSummarizer(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            model=model
        )
    
    else:
        raise ValueError(f"Unknown backend: {backend}")
```

---

## 💡 Configuración Recomendada (Config File)

**Para máxima flexibilidad**: Crear config con un modelo base, cambiar via CLI

```json
{
  "summarizer_backend": "openrouter",
  "openrouter_api_key": "sk-or-...",
  "model": "anthropic/claude-3.5-sonnet-20241022",
  "long_strategy": "hierarchical",
  "max_chars": 40000
}
```

Luego cambiar vía CLI:
```bash
# Cambiar a DeepSeek (barato)
uv run pdfsum run --backend deepseek --model deepseek-chat \
  --in ./pdfs --workspace ./data

# Cambiar a GPT-4 (premium)
uv run pdfsum run --backend openai --model gpt-4-turbo \
  --in ./pdfs --workspace ./data
```

---

## 📋 Checklist: Setup por Proveedor

### OpenRouter
- [ ] Crear cuenta en https://openrouter.ai
- [ ] Obtener API key
- [ ] Establecer budget límite (recomendado)
- [ ] Probar: `curl https://openrouter.ai/api/v1/models -H "Authorization: Bearer sk-or-..."`
- [ ] Crear adaptador OpenAI-compatible
- [ ] Configurar en ~/.pdfsum-config.json

### OpenAI
- [ ] Crear cuenta en https://platform.openai.com
- [ ] Agregar tarjeta de crédito
- [ ] Obtener API key
- [ ] Establecer budget límite en Billing
- [ ] Probar: `curl https://api.openai.com/v1/models -H "Authorization: Bearer sk-proj-..."`
- [ ] Configurar en ~/.pdfsum-config.json

### Anthropic (Claude)
- [ ] Crear cuenta en https://console.anthropic.com
- [ ] Agregar tarjeta de crédito
- [ ] Obtener API key
- [ ] Crear adaptador Anthropic (distinto a OpenAI)
- [ ] Configurar en ~/.pdfsum-config.json

### DeepSeek
- [ ] Crear cuenta en https://platform.deepseek.com
- [ ] Agregar tarjeta de crédito
- [ ] Obtener API key
- [ ] Usar adaptador OpenAI-compatible (DeepSeek implementa su API)
- [ ] Configurar base_url: https://api.deepseek.com
- [ ] Configurar en ~/.pdfsum-config.json

---

## 🎓 Guía de Decisión (Árbol de Selección)

```
¿Cuál es tu presupuesto mensual?
├─ <$0.50/mes
│  └─ DeepSeek ($0.00014/1K)
│     o OpenRouter + Mistral 7B
│
├─ $0.50-2/mes
│  └─ OpenRouter + Claude 3 Haiku
│     o Claude 3 Sonnet
│     o GPT-3.5 Turbo
│
├─ $2-10/mes
│  └─ OpenRouter + Claude 3.5 Sonnet (recomendado)
│     o GPT-4o
│     o Groq + Mistral
│
└─ $10+/mes (sin límite)
   └─ OpenAI GPT-4 Turbo
      o Claude 3 Opus
      o Múltiples modelos en paralelo (A/B testing)
```

---

## 📚 Enlaces Útiles

| Servicio | URL | Documentación |
|----------|-----|---------------|
| OpenRouter | https://openrouter.ai | https://openrouter.ai/docs |
| OpenAI | https://openai.com | https://platform.openai.com/docs |
| Anthropic | https://anthropic.com | https://docs.anthropic.com |
| DeepSeek | https://deepseek.com | https://platform.deepseek.com/docs |
| Groq | https://groq.com | https://console.groq.com/docs |

---

## ✅ Resumen: Comparativa Final

```
OBJETIVO:     Presupuesto             Calidad            Uptime
────────────────────────────────────────────────────────────────
DeepSeek      🏆 Mínimo ($0.01/mes)   Bueno              95%
OpenRouter    🏆 Flexible             Variable           95%
GPT-3.5       🏆 Barato ($0.03/mes)   Bueno              99.9%
Claude Haiku  🏆 Barato ($0.03/mes)   Bueno              99.9%
Groq          🏆 Rápido (<1s)         Bueno              95%
GPT-4o        🏆 Balance ($0.25/mes)  Excelente          99.9%
Claude Sonnet 🏆 Balance ($0.25/mes)  Excelente          99.9%
Claude Opus   🏆 Premium ($1.50/mes)  Máxima             99.9%
GPT-4 Turbo   🏆 Premium ($0.50/mes)  Excelente          99.9%
```

**RECOMENDACIÓN PERSONAL**: 
Para la mayoría de equipos: **OpenRouter + Claude 3.5 Sonnet**
- Precio: ~$0.20-0.30/mes (100-200 docs)
- Calidad: Excelente
- Flexibilidad: Máxima (100+ modelos disponibles)
- Uptime: 95%+ (suficiente)

---

**Última actualización**: 2026-08-25  
**Versión**: v0.11.0
