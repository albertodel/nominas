# Nóminas — app para la Raspberry Pi

Sube la nómina en PDF (A3) o métela a mano (la de papel), revisa los datos y
consúltalos por mes, por año y por empresa. Todo se procesa en la Pi: sin IA, sin
nube, y sin guardar datos personales (nombre, DNI, NSS e IBAN no se extraen).

- **Stack**: Python 3.12 · Starlette (la base de FastAPI) · Jinja2 · SQLite · Chart.js (incluido, sin CDN)
- **Recursos**: ~60 MB de RAM, CPU despreciable
- **Puerto**: 8087 → `nominas.pi`
- **Datos**: volumen `nominas_data` (`/data`): `nominas.db`, `archivo/<año>/*.pdf`, `.secret_key`

## Despliegue (GitHub → GHCR → Watchtower)

Cada push a `main` pasa el test del parser y, si va bien, GitHub Actions publica
`ghcr.io/<usuario>/nominas:latest` para arm64. Watchtower la actualiza en la Pi como
el resto de imágenes. El repositorio no contiene datos personales: la nómina de
prueba es sintética y las credenciales van en variables del stack, no en el código.

### 1. Subir el código a GitHub

Crea un repositorio vacío llamado `nominas` (sin README) y, dentro de esta carpeta:

```bash
git init -b main
git add .
git commit -m "Nóminas v0.1"
git remote add origin https://github.com/TU_USUARIO/nominas.git
git push -u origin main
```

En la pestaña **Actions** verás el workflow «Imagen» (unos 3–5 minutos la primera vez).
Cuando termine en verde: tu perfil → **Packages** → `nominas` → *Package settings* →
**Change visibility → Public** (solo la primera vez; así la Pi y Watchtower la descargan sin credenciales).

### 2. Generar el hash de la contraseña (en la Pi)

```bash
docker run --rm -it ghcr.io/TU_USUARIO/nominas:latest python -m app.hashpw
docker run --rm ghcr.io/TU_USUARIO/nominas:latest python -m tests.test_parser   # opcional
```

### 3. Stack en Portainer

Stacks → Add stack → nombre **`nominas`** → Web editor → pega `docker-compose.yml`
cambiando `TU_USUARIO`. Abajo, en **Environment variables**, añade:

| Nombre | Valor |
|---|---|
| `APP_USER` | tu usuario para entrar |
| `APP_PASSWORD_HASH` | la línea `scrypt:...` del paso 2 |

Deploy. El volumen real se llamará `nominas_nominas_data` (Portainer antepone el nombre
del stack); al ser un volumen con nombre, **Backrest lo incluye solo** en el plan `pi_gdrive`.

### 4. Integración con el lab

| Pieza | Configuración |
|---|---|
| Pi-hole (Local DNS) | `nominas.pi` → `192.168.1.10` |
| Nginx Proxy Manager | `nominas.pi` → `http` · `192.168.1.10` · `8087` · **Websockets ON** (mismo nombre exacto que en Pi-hole) |
| Uptime Kuma | HTTP a `http://192.168.1.10:8087/health` (por IP, sin login) |
| Homepage | entrada de abajo, grupo Herramientas |
| Backrest | automático (volumen con nombre) |

```yaml
- Herramientas:
    - Nóminas:
        icon: mdi-cash-multiple
        href: http://nominas.pi
        description: Nóminas y retenciones
        ping: 192.168.1.10:8087
```

## Actualizar

- **Automático**: haz push a `main` → Actions construye `:latest` → Watchtower la recoge
  en su siguiente pasada. Si el test falla, no se publica imagen y la Pi sigue con la anterior.
- **Versiones**: `git tag v0.2.0 && git push --tags` publica también `:0.2.0` y `:0.2`.
  Para volver atrás, cambia `:latest` por una versión en el stack (o por `sha-xxxxxxx`).
- **Sin GitHub** (pruebas rápidas en la Pi): `docker build -t nominas:local .` y cambia
  la imagen del stack a `nominas:local`.

## Uso

1. **Subir PDF** (A3): la app extrae empresa, periodo, todas las líneas, bases, % IRPF,
   líquido y coste empresa, y te enseña un formulario editable.
2. **Entrada manual** (nómina en papel): arranca con una plantilla de líneas típicas;
   «Calcular desde líneas» rellena los totales.
3. **Comprobaciones en vivo**: suma de devengos = total devengado, suma de deducciones =
   total a deducir, devengado − deducciones = líquido, base IRPF × % = retención.
   Si algo no cuadra no se guarda, salvo que marques «Guardar aunque no cuadre».
4. **Panel**: totales del año, «a dónde va el bruto» mes a mes, % de IRPF por empresa,
   totales por pagador (para cuadrar los certificados de retenciones en la Renta) y CSV
   (separador `;` y coma decimal, se abre directo en Excel).

Si subes dos veces el mismo mes de la misma empresa, avisa y te pide «Sobrescribir».

## Dónde personalizar

| Quiero cambiar… | Archivo |
|---|---|
| Colores, tipografía, tema claro/oscuro | `app/static/style.css` (tokens en `:root`) |
| Gráficas | `app/static/panel.js` + datos en `panel()` de `app/main.py` |
| Categorías de líneas (salarial, S.S., IRPF…) | `CATEGORIAS` en `app/calculos.py` |
| Comprobaciones aritméticas | `app/calculos.py` y su gemela `app/static/editor.js` |
| Lectura de los PDF de A3 | `app/parser_a3.py` (prueba: `tests/test_parser.py`) |
| Base de datos | `app/db.py` (importes en céntimos) |

Probar en local sin Docker (Linux/WSL con `pdftotext` instalado):

```bash
pip install -r requirements.txt
DATA_DIR=./data APP_USER=yo APP_PASSWORD_HASH='scrypt:...' uvicorn app.main:app --reload --port 8087
```

## Hoja de ruta

- **Fase 2**: OCR (Tesseract) para la nómina en papel con plantilla propia de esa empresa.
- **Fase 3 (opcional)**: botón «Leer con Claude» vía API (de pago aparte; la nómina saldría de casa).

## Seguridad

- Login obligatorio (hash scrypt, sesión firmada de 30 días). `/health` es lo único público.
- La clave de sesión se genera sola en `/data/.secret_key` (o fija una con `SECRET_KEY`).
- Solo LAN + WireGuard; no exponer a internet. Funciona por HTTP: cuando haya HTTPS en NPM, mejor.
