# Cómo trabajar en pdfsum

> ⚠️ **Actualizado 2026-08-25**: este proyecto **ya tiene remoto** en GitHub
> (`origin` → `https://github.com/idourra/pdf-summarizer`). La sección
> anterior ("repo local sin remoto") quedó obsoleta — se mantiene el flujo
> EDD por rama, pero ahora hay push a `origin/master` y múltiples sesiones
> (humanas o de agentes) pueden trabajar en el repo a la vez.

## ⚠️ Regla obligatoria: el checkout primario NO es workspace

**Incidente real (2026-08-25)**: dos sesiones de agente trabajando a la vez
sobre `~/projects/pdf-summarizer` (el checkout primario) provocaron que un
`git reset --hard` de una sesión borrara el trabajo en curso de la otra a
mitad de ciclo. El commit y el tag `v0.12.0` quedaron inconsistentes entre
local y remoto y hubo que reconstruir el trabajo perdido en un worktree
aislado.

**Por lo tanto, todo ciclo de trabajo (persona o agente) sigue esta regla:**

```bash
# 0. ANTES de tocar nada: comprobar que no hay otra sesión activa aquí
git worktree list
tmux list-windows -a 2>/dev/null   # o preguntar si hay otro pi/claude corriendo
lsof +D . 2>/dev/null | awk '{print $1,$2}' | sort -u   # procesos con cwd en el repo

# 1. Trabajar SIEMPRE en un worktree propio, nunca directo en el checkout primario
git worktree add ~/.worktrees/pdf-summarizer/<tarea> -b feat/<algo> master
cd ~/.worktrees/pdf-summarizer/<tarea>

# 2. ... hacer el ciclo normal (spec -> tests -> código -> verificar) ...

# 3. Commit en el worktree, LUEGO volver al checkout primario solo para integrar
cd ~/projects/pdf-summarizer
git fetch origin && git rev-parse master origin/master   # confirmar que no se movió bajo tus pies
git merge --no-ff feat/<algo>
git push origin master --tags

# 4. Limpiar
git worktree remove ~/.worktrees/pdf-summarizer/<tarea>
git branch -d feat/<algo>
```

El checkout primario (`~/projects/pdf-summarizer`) se reserva **solo** para:
fetch/pull, `git merge --no-ff` de integración, `git push`, y lectura/consulta
(`git log`, `git status`). Nunca para editar archivos ni para `git reset --hard`
/ `git checkout <rama-ajena>` mientras otra sesión pueda estar trabajando ahí.

## Flujo de trabajo (EDD)

```
1. eval-spec  → definir criterios ejecutables ANTES de codificar
                (evals/eval-spec-<fase>.yaml, validado con yamllint)
2. worktree   → git worktree add ~/.worktrees/pdf-summarizer/<algo> -b feat/<algo> master
                (nunca commitear en master; nunca trabajar en el checkout primario)
3. tests      → escribir tests que mapean 1:1 a los criterios del eval-spec
4. código     → implementar hasta que los tests pasen
5. verificar  → make check   (ruff + unittest, todo verde, sin regresión)
6. integrar   → desde el checkout primario: git fetch + confirmar que master
                no se movió + git merge --no-ff feat/<algo>
7. versionar  → actualizar CHANGELOG + __version__ + git tag vX.Y.Z
8. publicar   → git push origin master --tags
9. limpiar    → git worktree remove ... && git branch -d feat/<algo>
```

> **Por qué rama + merge y no commit directo a master:** un hook global
> (`~/.git-hooks`) prohíbe commits directos a `master`/`main`. La integración se
> hace por *merge* de una rama de feature (equivalente local a un Pull Request).

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
- Cada versión integrada se marca: `git tag -a vX.Y.Z -m "..."` y se publica con
  `git push origin master --tags`.
- **Si un tag queda mal apuntado** (p. ej. por un incidente como el de la
  Sección "checkout primario NO es workspace"): corregir el tag local
  (`git tag -d vX.Y.Z && git tag -a vX.Y.Z -m "..." <commit-correcto>`) y pedir
  confirmación explícita a un humano para `git push origin --delete vX.Y.Z`
  seguido de `git push origin vX.Y.Z` — ambos son comandos destructivos
  bloqueados por el guard global de comandos peligrosos y **no deben
  intentarse sortear**; los ejecuta un humano fuera del agente.
