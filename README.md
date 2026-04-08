# Yahoo Finance Technology Screener Scraper

Este proyecto contiene un pequeño script en Python para construir un dataset financiero a partir del screener de tecnología de Yahoo Finance. El script toma como punto de partida la página del screener, extrae las empresas visibles, selecciona las de mayor capitalización y, para cada ticker, descarga su histórico semanal del último año junto con algunos metadatos básicos. El resultado es un CSV pensado para análisis exploratorio, prácticas de scraping y ejercicios de tratamiento de series temporales.

La lógica del proyecto es intencionadamente sencilla. Primero se descarga el HTML del screener y se localizan las columnas principales de la tabla. Después se normalizan los símbolos bursátiles para evitar variantes regionales como `NVDA.BA` o `AAPL.MX`, conservando solo el ticker base. A continuación se aplica el filtro por capitalización, se recupera la industria de cada empresa y se consulta el endpoint histórico de Yahoo Finance. Finalmente, todo se combina en un único fichero CSV con columnas como `symbol`, `company_name`, `sector`, `industry`, `market_cap_today`, `date`, `open`, `high`, `low`, `close`, `adj_close` y `volume`.

El script trabaja con el screener tal y como Yahoo lo devuelve, sin intentar modificar filtros desde la interfaz. Por diseño, el campo `sector` se fija a `Technology`, porque el universo inicial ya procede del screener sectorial de tecnología. En cambio, `industry` se intenta recuperar dinámicamente para cada empresa. También conviene tener en cuenta que `market_cap_today` no es un dato histórico: es una capitalización actual que se repite en todas las filas temporales de una misma compañía.

Se han incluido medidas básicas de uso responsable del scraping. El código usa una sesión HTTP compartida, introduce pausas entre peticiones con una ligera variación aleatoria, registra el `User-Agent`, respeta `Retry-After` cuando aparece y solo reintenta ante errores temporales como `429` o `5xx`. No se emplean técnicas de evasión ni automatización agresiva. Aun así, sigue siendo importante usar la herramienta con moderación y revisar las condiciones de uso del sitio fuente.

Para instalar el entorno basta con ejecutar:

```bash
uv sync
```

La ejecución más simple es:

```bash
uv run python src/yahoo_finance_scraper.py
```

Si necesitas ajustar el tamaño del universo o el comportamiento de las peticiones, puedes usar parámetros como `--min-market-cap`, `--limit`, `--range`, `--interval`, `--request-delay`, `--request-jitter` y `--max-retries`. El script guarda el CSV en la carpeta `csv/` si no se indica otra ruta.

El repositorio incluye también un informe extenso en PDF y un diagrama SVG del flujo del scraping dentro de la carpeta `pdf/`. La sintaxis del código puede validarse con:

```bash
.\.venv\Scripts\python.exe -m compileall src
```
