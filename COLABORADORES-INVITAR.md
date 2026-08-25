# Cómo Invitar Colaboradores al Repositorio

**Repositorio**: https://github.com/idourra/pdf-summarizer  
**Propietario**: Jose Andres Urra (@idourra)

---

## 🔗 Opciones para que el Equipo Acceda

### Opción 1️⃣ : Sin Invitación (Recomendado para Open Source)

El repositorio es **PUBLIC**, así que cualquiera puede:
- ✅ Clonar el código
- ✅ Ver issues y pull requests
- ✅ Fork el repositorio para contribuir
- ❌ Pushear directamente a master (requiere invitación)

**Para que colaboradores puedan hacer PR:**
```bash
# En su máquina
git clone https://github.com/idourra/pdf-summarizer.git
cd pdf-summarizer
git checkout -b feat/su-feature
# Hacen cambios, commitean, pushean a su fork
# Luego abren PR en GitHub
```

---

### Opción 2️⃣ : Invitar como Colaborador (Acceso de Push)

Si quieres que alguien del equipo tenga **acceso directo** a pushear:

#### Vía GitHub Web (Visual)

1. Ve a https://github.com/idourra/pdf-summarizer
2. Click en **Settings** (icono engranaje, requiere ser propietario)
3. Click en **Collaborators** (sidebar izquierdo)
4. Click en **Add people**
5. Escribe el username de GitHub del colaborador (ej. `username`)
6. Elige el rol:
   - **Maintain**: Pull requests, issues, manage team
   - **Write**: Pushear código, crear branches
   - **Admin**: Acceso total (cuidado)
7. Click en **Invite**

El colaborador recibirá una notificación y podrá aceptar.

#### Vía GitHub CLI (Terminal)

```bash
# Invitar como "maintain" (recomendado para equipo)
gh repo add-collaborator idourra/pdf-summarizer username --permission maintain

# Invitar como "write" (si solo quieres que pusheen)
gh repo add-collaborator idourra/pdf-summarizer username --permission push

# Invitar como "admin" (acceso total, cuidado)
gh repo add-collaborator idourra/pdf-summarizer username --permission admin

# Ver colaboradores actuales
gh repo view idourra/pdf-summarizer --json collaborators
```

---

### Opción 3️⃣ : Crear Team (Para Equipos Grandes)

Si trabajan en equipo en GitHub organization:

1. Ve a https://github.com/orgs/yourorg/teams
2. Click en **Create a team**
3. Nombre: `pdf-summarizer-dev` (ej)
4. Invita miembros al equipo
5. En Settings del repo, agrega el team con rol "maintain"

---

## 🚀 Pasos para Colaboradores (Después de Invitarlos)

### Si tienen acceso de Push (Opción 2)

```bash
# Clonar
git clone https://github.com/idourra/pdf-summarizer.git
cd pdf-summarizer

# Instalar deps
uv sync

# Crear rama para su feature
git checkout -b feat/nombre-feature

# Hacer cambios, tests
uv run python -m unittest discover tests  # ✓ verde
uv run ruff check src/ tests/              # ✓ sin errores

# Commit
git add ...
git commit -m "feat(modulo): descripción"

# Push (va directamente a la rama, no a origin/master)
git push origin feat/nombre-feature

# Abrir PR en GitHub (para code review)
# URL: https://github.com/idourra/pdf-summarizer/compare/master...feat/nombre-feature
```

### Si NO tienen acceso (Opción 1 - Fork)

```bash
# En su propia cuenta GitHub: Fork en https://github.com/idourra/pdf-summarizer
# Aparece como https://github.com/SUACCOUNT/pdf-summarizer

# Clonar su fork
git clone https://github.com/SUACCOUNT/pdf-summarizer.git
cd pdf-summarizer

# Instalar + cambios + tests (como arriba)
uv sync
git checkout -b feat/nombre-feature
# ... cambios ...

# Pushearse a su fork
git push origin feat/nombre-feature

# Abrir PR desde su fork a idourra/pdf-summarizer (GitHub lo sugiere)
```

---

## 📝 Configuración Recomendada para Equipo

### Política de Rama Protegida (master)

Para evitar que alguien pushee directamente a master sin PR:

1. Ve a Settings → **Branches**
2. Click en **Add rule**
3. Branch name pattern: `master`
4. Activa:
   - ✅ **Require pull request reviews before merging** (recomendado: 1 reviewer)
   - ✅ **Require status checks to pass before merging** (CI: ruff, tests, architecture)
   - ✅ **Require branches to be up to date before merging**
   - ✅ **Dismiss stale PR approvals when new commits are pushed**

Con esto:
- ❌ Nadie puede pushear directamente a master
- ✅ Solo se puede vía PR + CI verde + 1 review

### Configurar GitHub Actions (ya hecho en este repo)

El repo ya tiene:
- `.github/workflows/ci.yml` → Corre en cada PR y push
  - Tests (Python 3.10, 3.11, 3.12)
  - Lint (ruff)
  - Architecture check
  - Docs verification

Esto se verifica automáticamente en PRs. ✓

---

## 📋 Lista de Colaboradores Sugeridos

Si quieres invitar a alguien, necesitas su **username de GitHub**.

**Formato para pedirles que se unan:**

```
Hola, 

He creado un repositorio público para compartir pdf-summarizer:
👉 https://github.com/idourra/pdf-summarizer

Instrucciones para colaborar:
1. Lee GITHUB-TEAM-WELCOME.md (bienvenida + workflow)
2. Clona: git clone https://github.com/idourra/pdf-summarizer.git
3. Instala: uv sync
4. Verifica: uv run pdfsum doctor && uv run pdfsum verify
5. Para contribuir: crea rama feat/tu-feature, tests verde, abre PR

¿Username de GitHub para invitarte como colaborador?
(O si prefieres, puedes hacer fork y enviar PRs)

Saludos,
Jose Andres
```

---

## 🔐 Seguridad & Mejores Prácticas

### Tokens & Secrets

Si necesitas secrets (ej. PyPI token para Fase 12):

1. Ve a Settings → **Secrets and variables** → **Actions**
2. Click en **New repository secret**
3. Nombre: `PYPI_API_TOKEN` (ej)
4. Valor: tu token de PyPI
5. En `.github/workflows/publish.yml` úsalo:
   ```yaml
   - name: Publish to PyPI
     run: |
       uv run twine upload dist/* \
         --username __token__ \
         --password ${{ secrets.PYPI_API_TOKEN }}
   ```

---

## 📞 Más Información

- [GitHub CLI docs](https://cli.github.com/manual/)
- [GitHub Collaborators](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-access-to-your-personal-repositories/inviting-collaborators-to-a-personal-repository)
- [Branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule)

---

**¡Listo para colaborar! 🚀**
