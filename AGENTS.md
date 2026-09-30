# AGENTS.md

## Proyecto

Este repositorio contiene `pdfsum`, una aplicación Python para extracción, OCR, procesamiento y generación de datos estructurados a partir de documentos PDF.

Antes de modificar código:

1. examina la implementación existente;
2. revisa los tests relacionados;
3. consulta la documentación pertinente;
4. sigue los patrones ya utilizados en el repositorio.

No deduzcas la arquitectura o el comportamiento solamente a partir de la tarea recibida.

## Fuentes de verdad

Consulta cuando corresponda:

- `CONTRIBUTING.md`: flujo de desarrollo y reglas de contribución;
- `README.md`: arquitectura, funcionalidades y uso;
- `INSTALL.md`: instalación y configuración;
- `CHANGELOG.md`: historial de cambios;
- `pyproject.toml`: dependencias y configuración de herramientas;
- `Makefile`: comandos oficiales de validación;
- `tests/`: comportamiento esperado y regresiones;
- `docs/` y `evals/`: especificaciones adicionales cuando sean aplicables.

Si existe una instrucción más específica en otro `AGENTS.md` dentro del árbol de directorios, respétala dentro de su alcance.

## Alcance de los cambios

- Implementa solamente lo solicitado.
- Evita refactorizaciones no relacionadas con la tarea.
- Reutiliza patrones, módulos y abstracciones existentes antes de introducir otros nuevos.
- Mantén los cambios pequeños y enfocados siempre que sea posible.
- No cambies interfaces públicas, contratos, CLI ni configuración sin necesidad.
- Si descubres un problema fuera del alcance de la tarea, repórtalo en lugar de corregirlo silenciosamente.
- No hagas `commit`, `push`, `merge`, tags ni operaciones destructivas de Git salvo que el usuario lo solicite explícitamente.

Antes de una modificación grande o estructural, analiza primero la implementación actual y define un plan.

## Idioma

Toda cadena nueva o modificada visible al usuario y todo comentario nuevo o modificado en el código debe escribirse en español cubano, siguiendo el estilo existente en el proyecto.

Los términos técnicos habitualmente utilizados en inglés pueden permanecer en inglés.

Esta regla no altera el idioma del contenido procesado por la aplicación. Los resultados derivados de documentos deben continuar respetando el idioma correspondiente y los abstracts de origen deben preservarse verbatim cuando así lo establezca el comportamiento existente.

## Arquitectura

Respeta las fronteras arquitectónicas existentes.

En particular:

- el dominio de `src/pdfsum/` no debe depender de detalles de infraestructura;
- Ollama, OCR, Tesseract, HTTP, subprocess y otras integraciones externas deben permanecer detrás de los adaptadores correspondientes;
- respeta las restricciones verificadas por `tests/test_architecture.py`;
- el contrato JSON es una frontera estable;
- evita cambios incompatibles salvo que la tarea los requiera explícitamente;
- preserva compatibilidad hacia atrás siempre que sea posible.

Antes de crear una nueva abstracción, busca cómo se resuelven problemas equivalentes en el código existente.

## Desarrollo con Git

Sigue las reglas definidas en `CONTRIBUTING.md`.

En particular:

- no trabajes directamente sobre `master`;
- utiliza una branch/worktree dedicada cuando lo exija el flujo existente;
- no sobrescribas trabajo de otras sesiones;
- evita comandos destructivos de Git;
- antes de modificar archivos, comprueba el estado del repositorio y cualquier cambio existente que deba preservarse.

No reviertas cambios que no pertenezcan a la tarea actual.

## Tests y calidad

Cuando cambie el comportamiento:

1. actualiza o añade tests que cubran el cambio;
2. ejecuta primero los tests específicos relacionados;
3. ejecuta lint y comprobación de formato;
4. ejecuta la suite completa cuando sea razonable.

Comandos de referencia:

```bash
make lint
make format-check
make test
make check
```

También pueden utilizarse comandos específicos con `uv` cuando sean más adecuados para la tarea.

No declares que una validación pasó si no fue ejecutada.

Si una prueba no puede ejecutarse debido a limitaciones del entorno, indícalo claramente.

No debilites, elimines o ignores tests solamente para hacer que una implementación pase.

## Dependencias

Antes de añadir una dependencia:

- comprueba si el problema puede resolverse con las dependencias existentes o la biblioteca estándar;
- confirma si es una dependencia de runtime, desarrollo u opcional;
- actualiza los archivos de configuración correspondientes;
- considera el impacto sobre instalación y Docker.

No añadas dependencias sin una justificación técnica relacionada con la tarea.

## CLI y configuración

Si modificas:

- comandos;
- argumentos;
- variables de entorno;
- archivos de configuración;
- defaults;
- modelos;
- rutas;
- puertos;
- requisitos de ejecución;

verifica el impacto sobre todos los puntos de entrada y formas de instalación soportadas por el proyecto.

Mantén compatibilidad con el comportamiento existente salvo que la tarea defina expresamente un cambio.

## Docker

Cuando una modificación afecte runtime, dependencias del sistema, CLI, variables de entorno, paths, modelos o proceso de inicialización, revisa también los archivos Docker y Compose versionados en el repositorio.

Informa claramente cualquier impacto en despliegue, configuración o validación que pueda requerir acciones adicionales fuera del código.

No introduzcas configuraciones específicas de una organización, servidor o instalación particular en los archivos públicos del proyecto.

La configuración versionada debe permanecer reutilizable por otros usuarios e instalaciones.

## Documentación

Actualiza la documentación cuando el cambio afecte de forma observable:

- CLI;
- configuración;
- instalación;
- Docker;
- arquitectura;
- contratos públicos;
- comportamiento para el usuario.

Evita modificar documentación no relacionada con la tarea.

Mantén ejemplos y comandos sincronizados con el comportamiento real.

## Seguridad y datos

- No incorpores credenciales, tokens, secrets o información privada al repositorio.
- No añadas rutas, hosts, nombres de servidores o configuraciones internas de una instalación específica salvo que formen parte explícita del software
- No incluyas datos reales sensibles en fixtures o tests.
- Utiliza datos sintéticos o muestras existentes cuando sea posible.

## Finalización de una tarea

Antes de dar una tarea por terminada:

1. revisa el diff;
2. comprueba que los cambios pertenecen al alcance solicitado;
3. ejecuta las validaciones disponibles;
4. revisa si tests y documentación necesitan actualización;
5. verifica si el cambio afecta instalación, Docker o configuración.

Al responder al usuario, informa de forma concisa:

- qué cambió;
- qué archivos fueron modificados;
- qué tests o verificaciones fueron ejecutados;
- qué no pudo validarse;
- si hay impacto en documentación, configuración, instalación o Docker;
- qué pasos adicionales de validación son recomendables.

No presentes como verificado aquello que solamente fue inferido.
