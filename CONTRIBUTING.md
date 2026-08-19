# Cómo trabajar en pdfsum (repo local)

Este proyecto vive en un **repositorio git local** (sin remoto: no hay
GitHub/GitLab, no hay Pull Requests). La disciplina se mantiene igual, adaptada
al entorno local.

## Flujo de trabajo (EDD local)

```
1. eval-spec  → definir criterios ejecutables ANTES de codificar
                (evals/eval-spec-<fase>.yaml, validado con yamllint)
2. rama       → git checkout -b feat/<algo>   (nunca commitear en master)
3. tests      → escribir tests que mapean 1:1 a los criterios del eval-spec
4. código     → implementar hasta que los tests pasen
5. verificar  → make check   (ruff + unittest, todo verde, sin regresión)
6. integrar   → git checkout master && git merge --no-ff feat/<algo>
7. versionar  → actualizar CHANGELOG + __version__ + git tag vX.Y.Z
8. limpiar    → git branch -d feat/<algo>
```

> **Por qué rama + merge y no commit directo a master:** un hook global
> (`~/.git-hooks`) prohíbe commits directos a `master`/`main`. La integración se
> hace por *merge* de una rama de feature (equivalente local a un PR).

## Reglas

- **Spec antes que código.** Toda fase arranca por su `eval-spec-*.yaml`.
- **Dominio sin adaptadores.** `src/pdfsum/*.py` (salvo `adapters/`, `cli.py`)
  no importa Ollama/Tesseract/HTTP/subprocess. Verificado por
  `tests/test_architecture.py`.
- **El contrato JSON es frontera estable.** Cambios incompatibles suben
  `CONTRACT_VERSION` y versión mayor.
- **Sin regresión.** `make check` debe pasar completo antes de integrar.
- **Idioma del documento.** Toda salida va en el idioma detectado y preserva
  los abstracts de origen verbatim.

## Comandos

```bash
make lint     # ruff
make test     # unittest (criterios de los eval-specs)
make check    # lint + test (gate de integración)
```

## Versionado

- `MAJOR`: cambia el contrato JSON de forma incompatible.
- `MINOR`: nueva fase/capacidad compatible (p. ej. 0.1 → 0.2 = Fase 1).
- `PATCH`: correcciones sin cambio de contrato.
- Cada versión integrada se marca: `git tag -a vX.Y.Z -m "..."`.
