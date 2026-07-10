# YupiTech Website

Sitio estatico para YupiTech basado en el contenido publico de https://yupitechnologies.com/.

Dominio de deploy inicial: https://yupitech.mutechlabs.com/.

## Estructura

- `index.html`: pagina principal.
- `assets/styles/styles.css`: estilos responsivos.
- `assets/scripts/main.js`: menu movil y cotizacion por WhatsApp.
- `assets/images/`: logo e iconos reales descargados del sitio actual.
- `robots.txt`, `sitemap.xml`, `llms.txt`: archivos de descubrimiento para buscadores y crawlers.

## Ejecutar localmente

```bash
python3 -m http.server 8000
```

Abrir http://localhost:8000.

## Configurar deploy FTP

El deploy usa FTP/FTPS y lee credenciales desde `.deploy.env`.

```bash
cp .deploy.env.example .deploy.env
```

Completar `FTP_PASSWORD` cuando toque desplegar. Si queda vacio, el script lo pedira de forma segura en terminal.

Antes del primer deploy, listar la raiz del FTP para confirmar el directorio correcto del subdominio:

```bash
python3 scripts/deploy_ftp.py --list-root
```

El document root confirmado para este subdominio es `/yupitech.mutechlabs.com/public_html`. Luego desplegar:

```bash
python3 scripts/deploy_ftp.py
```

Para subir todo aunque los tamanos no hayan cambiado:

```bash
python3 scripts/deploy_ftp.py --force
```
