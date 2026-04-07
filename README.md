# Yahoo Finance Technology Screener Scraper

Mini aplicacion en Python para extraer empresas desde el screener de tecnologia de Yahoo Finance, tal y como Yahoo lo devuelve en la URL base, y descargar su historico de precios en CSV.

## Objetivo

La aplicacion sigue este flujo:

1. Descarga el screener de tecnologia de Yahoo Finance con `start=0&count=100`.
2. Extrae las empresas visibles de la tabla sin intentar quitar filtros de Yahoo.
3. Filtra por `market_cap_today >= umbral`.
4. Recupera `sector` e `industry` de cada ticker.
5. Permite filtrar por uno o varios sectores.
6. Descarga el historico de precios y genera un CSV plano.

## Como funciona internamente

El script esta pensado para ser sencillo y trazable:

1. Lee el HTML del screener sin usar navegador automatizado.
2. Busca la tabla principal y localiza las columnas `Symbol`, `Name` y `Market Cap`.
3. Intenta extraer el ticker desde los enlaces `/quote/...` de la celda `Symbol`.
4. Si Yahoo devuelve variantes regionales como `NVDA.BA` o `AAPL.MX`, se conserva solo el ticker base:
   - `NVDA.BA` -> `NVDA`
   - `AAPL.MX` -> `AAPL`
5. Para cada ticker, consulta:
   - `quoteSummary` para `industry`
   - la ficha HTML como respaldo si falla la API
   - el endpoint `chart` para el historico de precios

Esto mantiene la logica del proyecto en tres bloques claros:

- screener para descubrir empresas
- perfil para enriquecer cada empresa
- historico para construir el CSV final

## Uso responsable del scraping

El codigo incorpora medidas para reducir el impacto sobre el sitio y hacer el flujo mas transparente:

- usa una `requests.Session()` compartida para no abrir conexiones nuevas innecesarias
- introduce pausas entre peticiones con una pequena variacion aleatoria
- reintenta solo cuando hay errores temporales como `429` o `5xx`
- respeta `Retry-After` cuando el servidor lo devuelve
- registra en logs el `User-Agent` realmente configurado en la sesion HTTP
- no implementa tecnicas avanzadas de evasión ni mecanismos para saltarse protecciones del sitio

En la version actual no se usa `WebDriver`. Si en una version futura se anadiera un navegador automatizado, habria que comprobar tambien el `User-Agent` efectivo del navegador, no solo el de `requests`.

## Fuente de datos

- Screener base:
  [Yahoo Finance Technology Screener](https://finance.yahoo.com/research-hub/screener/sec-ind_sec-largest-equities_technology/?start=0&count=100)
- Ejemplo de ficha:
  [Yahoo Finance NVDA](https://finance.yahoo.com/quote/NVDA/)
- Ejemplo de historico:
  [Yahoo Finance NVDA History](https://finance.yahoo.com/quote/NVDA/history/?frequency=1wk)

## Script principal

El script principal es [yahoo_finance_scraper.py](/C:/Users/USUARIO/Master%20Ciencia%20de%20Datos/Topolog%C3%ADa%20y%20Ciclo%20de%20vida%20de%20los%20Datos/Bloque%202/idealista_scrap/src/yahoo_finance_scraper.py).

## Requisitos

- Python `>= 3.14`
- Dependencias definidas en [pyproject.toml](/C:/Users/USUARIO/Master%20Ciencia%20de%20Datos/Topolog%C3%ADa%20y%20Ciclo%20de%20vida%20de%20los%20Datos/Bloque%202/idealista_scrap/pyproject.toml)

Instalacion recomendada:

```bash
uv sync
```

## Uso

Ejecucion por defecto:

```bash
uv run python src/yahoo_finance_scraper.py
```

Con los valores por defecto:

- descarga el screener sectorial de tecnologia
- no intenta modificar filtros de Yahoo
- trabaja sobre las hasta 100 filas devueltas por la tabla
- filtra companias con `market_cap_today >= 100000000000`
- descarga el historico del ultimo ano con frecuencia semanal

## Parametros disponibles

- `--min-market-cap`
  capitalizacion minima en dolares. Por defecto `100000000000`
- `--sectors`
  lista de sectores a conservar. Ejemplo:
  `--sectors Technology Healthcare "Communication Services"`
- `--limit`
  numero maximo de companias a procesar despues del filtro por capitalizacion
- `--range`
  rango historico de Yahoo Finance. Por defecto `1y`
- `--interval`
  granularidad del historico. Por defecto `1wk`
- `--output`
  ruta completa del CSV de salida
- `--request-delay`
  pausa base en segundos entre peticiones HTTP. Por defecto `1.0`
- `--request-jitter`
  variacion aleatoria maxima en segundos sobre la pausa base. Por defecto `0.5`
- `--max-retries`
  numero maximo de reintentos ante errores temporales HTTP. Por defecto `3`

## Ejemplos

Companias del screener de tecnologia por encima de 100B:

```bash
uv run python src/yahoo_finance_scraper.py --min-market-cap 100000000000
```

Companias del screener de tecnologia por encima de 100B del sector Technology:

```bash
uv run python src/yahoo_finance_scraper.py --min-market-cap 100000000000 --sectors Technology
```

## Formato del CSV

El CSV generado contiene estas columnas:

- `symbol`
- `company_name`
- `sector`
- `industry`
- `market_cap_today`
- `date`
- `open`
- `high`
- `low`
- `close`
- `adj_close`
- `volume`

## Estructura del proyecto

- [yahoo_finance_scraper.py](/C:/Users/USUARIO/Master%20Ciencia%20de%20Datos/Topolog%C3%ADa%20y%20Ciclo%20de%20vida%20de%20los%20Datos/Bloque%202/idealista_scrap/src/yahoo_finance_scraper.py)
  script principal con comentarios por bloques y funciones separadas para screener, perfil, historico y salida
- [pyproject.toml](/C:/Users/USUARIO/Master%20Ciencia%20de%20Datos/Topolog%C3%ADa%20y%20Ciclo%20de%20vida%20de%20los%20Datos/Bloque%202/idealista_scrap/pyproject.toml)
  dependencias del proyecto
- `csv/`
  carpeta de salida para los ficheros generados

## Significado de las columnas

- `market_cap_today`
  no es un dato historico por fecha. Es la capitalizacion recuperada en el momento del scraping y se repite para todas las filas historicas de una misma empresa.
- `sector`
  valor fijo `Technology`, porque el universo de partida es el screener sectorial de tecnologia.
- `industry`
  industria actual de la empresa segun Yahoo Finance.

## Precision numerica

- Los precios (`open`, `high`, `low`, `close`, `adj_close`) se guardan con un maximo de 3 decimales.
- `volume` y `market_cap_today` se mantienen como enteros cuando corresponde.

## Logs y depuracion

El script imprime:

- el `User-Agent` configurado en la sesion HTTP
- la URL del screener descargado
- los simbolos extraidos del screener
- los simbolos tras el filtro de capitalizacion
- la URL usada para `profile` e `history` de cada empresa
- mensajes intermedios cuando una celda `Symbol` no coincide exactamente con el ticker final usado
- pausas aplicadas, codigos HTTP y reintentos cuando hay respuestas temporales

Ademas, cualquier simbolo con sufijo de mercado se normaliza cortando lo que venga tras el punto:

- `NVDA.BA` -> `NVDA`
- `AAPL.MX` -> `AAPL`
- `005930.KS` -> `005930`

## Limitaciones y notas

- El script no intenta quitar filtros de Yahoo. Trabaja exactamente con las filas que Yahoo devuelve en el screener indicado.
- Si Yahoo cambia el DOM de la tabla o deja de renderizarla en el HTML descargado, puede hacer falta reajustar el parser.
- `sector` e `industry` se intentan obtener primero por una via estructurada y, si falla, desde el HTML de la ficha.
- `sector` se fija a `Technology` para todas las filas; solo `industry` se recupera dinamicamente por empresa.
- El historico se obtiene desde el endpoint JSON del grafico de Yahoo Finance.
- En entornos con red restringida o proxies rotos, la ejecucion puede fallar aunque el script sea valido.
- `market_cap_today` es un dato actual y no una serie temporal; por eso se repite para cada fecha historica de la misma empresa.
- Aunque haya reintentos y pausas, el uso del script debe seguir ajustandose a las condiciones de uso del sitio objetivo.

## Verificacion local

La sintaxis del script puede validarse con:

```bash
.\.venv\Scripts\python.exe -m compileall src
```
