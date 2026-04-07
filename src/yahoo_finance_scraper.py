from __future__ import annotations

import argparse
import csv
import random
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

# ------ CONSTANTES ------

SCREENER_URL = (
    "https://finance.yahoo.com/research-hub/screener/"
    "sec-ind_sec-largest-equities_technology/?start=0&count=100"
)
QUOTE_URL_TEMPLATE = "https://finance.yahoo.com/quote/{symbol}/"
QUOTE_SUMMARY_URL_TEMPLATE = (
    "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=assetProfile"
)
CHART_API_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_LIMIT = None
DEFAULT_RANGE = "1y"
DEFAULT_INTERVAL = "1wk"
DEFAULT_MIN_MARKET_CAP = 100_000_000_000
FIXED_SECTOR = "Technology"
DEFAULT_REQUEST_DELAY = 1.0
DEFAULT_REQUEST_JITTER = 0.5
DEFAULT_MAX_RETRIES = 3
OUTPUT_DIR = Path("csv")


# ------ MODELOS ------

@dataclass
class Company:
    symbol: str
    name: str
    market_cap: int


@dataclass
class CompanyProfile:
    sector: str
    industry: str


# ------ ARGUMENTOS ------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extrae las empresas del screener de tecnologia de Yahoo Finance tal y como "
            "Yahoo lo devuelve, filtra por market cap, anade sector e industry y "
            "descarga el historico."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Numero maximo de companias a procesar despues del filtro por market cap.",
    )
    parser.add_argument(
        "--min-market-cap",
        type=int,
        default=DEFAULT_MIN_MARKET_CAP,
        help="Capitalizacion minima en dolares. Por defecto 100000000000.",
    )
    parser.add_argument(
        "--sectors",
        nargs="*",
        default=[],
        help="Lista de sectores a conservar. Ejemplo: --sectors Technology Healthcare",
    )
    parser.add_argument(
        "--range",
        default=DEFAULT_RANGE,
        help="Rango historico de Yahoo Finance. Por defecto 1y.",
    )
    parser.add_argument(
        "--interval",
        default=DEFAULT_INTERVAL,
        help="Intervalo historico de Yahoo Finance. Por defecto 1wk.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Ruta completa del CSV de salida. Si no se indica, se guarda en csv/.",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY,
        help="Pausa base en segundos entre peticiones HTTP. Por defecto 1.0.",
    )
    parser.add_argument(
        "--request-jitter",
        type=float,
        default=DEFAULT_REQUEST_JITTER,
        help="Variacion aleatoria maxima en segundos sobre la pausa base. Por defecto 0.5.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Numero maximo de reintentos ante errores temporales HTTP. Por defecto 3.",
    )
    return parser.parse_args()


# ------ UTILIDADES ------

def build_session() -> requests.Session:
    # Session compartida para reutilizar cabeceras y evitar repetir configuracion.
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def clean_text(value: str | None) -> str:
    # Normaliza espacios para que el parser no dependa del formato visual exacto.
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def log_step(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def log_user_agent(session: requests.Session) -> None:
    # Se registra siempre el User-Agent efectivo que sale por requests. Asi queda
    # documentado en logs y se puede comprobar en ejecuciones reales.
    user_agent = session.headers.get("User-Agent", "")
    log_step(f"User-Agent configurado: {user_agent}")


def sleep_with_jitter(base_delay: float, jitter: float, reason: str) -> None:
    # Pausas pequenas entre peticiones para reducir carga sobre el servidor y evitar
    # lanzar muchas solicitudes consecutivas a alta velocidad.
    total_delay = max(0.0, base_delay) + random.uniform(0.0, max(0.0, jitter))
    if total_delay <= 0:
        return
    log_step(f"Pausa responsable: {total_delay:.2f}s motivo={reason}")
    time.sleep(total_delay)


def request_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, str] | None = None,
    timeout: int = 30,
    request_delay: float,
    request_jitter: float,
    max_retries: int,
    request_label: str,
) -> requests.Response:
    # Punto unico de salida HTTP del scraper.
    # Implementa:
    # - pausas entre peticiones
    # - respeto de Retry-After cuando el servidor lo devuelve
    # - reintentos con backoff ante 429 y errores 5xx
    # No implementa tecnicas de evasión ni cambios dinamicos de identidad.
    last_exception: requests.RequestException | None = None

    for attempt in range(1, max_retries + 1):
        sleep_with_jitter(request_delay, request_jitter, f"{request_label} intento={attempt}")
        log_step(f"HTTP GET: {request_label} url={url} intento={attempt}")
        try:
            response = session.get(url, params=params, timeout=timeout)
            status_code = response.status_code
            log_step(f"HTTP status: {request_label} status={status_code}")

            if status_code == 429 or 500 <= status_code < 600:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_seconds = max(0.0, float(retry_after))
                    except ValueError:
                        wait_seconds = request_delay * attempt
                else:
                    wait_seconds = request_delay * attempt

                if attempt >= max_retries:
                    response.raise_for_status()

                log_step(
                    f"Respuesta temporal {status_code} en {request_label}. "
                    f"Esperando {wait_seconds:.2f}s antes de reintentar."
                )
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exception = exc
            if attempt >= max_retries:
                raise
            backoff_seconds = request_delay * attempt
            log_step(
                f"Error HTTP en {request_label}: {exc.__class__.__name__}. "
                f"Backoff {backoff_seconds:.2f}s antes de reintentar."
            )
            time.sleep(backoff_seconds)

    if last_exception is not None:
        raise last_exception
    raise RuntimeError(f"No se pudo completar la peticion: {request_label}")


def normalize_symbol(symbol: str | None) -> str:
    # Yahoo puede devolver tickers con sufijos de mercado como NVDA.BA o AAPL.MX.
    # El scraper trabaja con el ticker base para construir quote/{symbol}/ e history.
    clean_symbol = clean_text(symbol)
    if not clean_symbol:
        return ""
    if "." in clean_symbol:
        clean_symbol = clean_symbol.split(".", 1)[0]
    return clean_symbol


def extract_symbol_from_href(href: str) -> str:
    match = re.search(r"/quote/([^/?]+)", href)
    return normalize_symbol(match.group(1) if match else "")


def choose_best_symbol(candidates: list[str]) -> str:
    # Si una celda contiene varios enlaces, nos quedamos con el ticker base mas largo
    # porque suele ser el simbolo mas informativo despues de normalizar sufijos.
    unique_candidates: list[str] = []
    for candidate in candidates:
        clean_candidate = normalize_symbol(candidate)
        if clean_candidate and clean_candidate not in unique_candidates:
            unique_candidates.append(clean_candidate)

    if not unique_candidates:
        return ""

    return max(unique_candidates, key=lambda symbol: (len(symbol), symbol))


def extract_symbol_from_cell_text(cell_text: str) -> str:
    # Fallback cuando no hay enlaces utilizables en la celda Symbol.
    # Extrae tokens con forma de ticker y aplica la misma normalizacion.
    tokens = [token.strip("()[]{}:,;") for token in re.split(r"\s+", cell_text) if token]
    candidates: list[str] = []
    for token in tokens:
        if re.fullmatch(r"[A-Z0-9]{1,12}(?:[.\-][A-Z0-9]{1,12})*", token):
            normalized = normalize_symbol(token)
            if normalized:
                candidates.append(normalized)

    if not candidates:
        return ""

    return max(candidates, key=lambda symbol: (len(symbol), symbol))


def normalize_header_map(headers: list[str]) -> dict[str, int]:
    # Convierte cabeceras a un mapa robusto frente a mayusculas/minusculas y espacios.
    normalized_map: dict[str, int] = {}
    for index, header in enumerate(headers):
        normalized = clean_text(header).casefold()
        if normalized and normalized not in normalized_map:
            normalized_map[normalized] = index
    return normalized_map


def parse_market_cap(value: str | int | float | None) -> int:
    # Convierte formatos compactos de Yahoo como 420.996B a enteros en dolares.
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    compact = clean_text(value).replace(",", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KMBT]?)", compact, flags=re.IGNORECASE)
    if not match:
        return 0

    number = float(match.group(1))
    suffix = match.group(2).upper()
    multiplier = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "T": 1_000_000_000_000,
    }[suffix]
    return int(number * multiplier)


def format_numeric(value: object) -> object:
    # Limita floats a 3 decimales para que el CSV sea mas estable al abrirse en hojas de calculo.
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        rounded = round(value, 3)
        if rounded.is_integer():
            return int(rounded)
        return rounded
    return value


def normalize_sector_list(raw_values: list[str]) -> set[str]:
    # Permite pasar varios sectores separados por espacios o por comas.
    normalized: set[str] = set()
    for raw_value in raw_values:
        for chunk in raw_value.split(","):
            value = clean_text(chunk)
            if value:
                normalized.add(value.casefold())
    return normalized


def log_company_symbols(title: str, companies: list[Company]) -> None:
    if not companies:
        log_step(f"{title}: []")
        return
    symbols = ", ".join(company.symbol for company in companies)
    log_step(f"{title}: {symbols}")


# ------ SCREENER ------

def fetch_screener_html(
    session: requests.Session,
    request_delay: float,
    request_jitter: float,
    max_retries: int,
) -> str:
    # Se descarga el screener tal y como Yahoo lo sirve, sin automatizar filtros UI.
    log_step(f"Descargando screener: {SCREENER_URL}")
    response = request_with_retry(
        session,
        SCREENER_URL,
        timeout=30,
        request_delay=request_delay,
        request_jitter=request_jitter,
        max_retries=max_retries,
        request_label="screener",
    )
    return response.text


def parse_companies_from_html(html: str) -> list[Company]:
    # El screener es la fuente inicial de tickers y market cap actuales.
    # A partir de ahi se construyen las llamadas de perfil e historico por empresa.
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        log_step("No se encontró la tabla en el HTML del screener")
        return []

    headers = [clean_text(cell.get_text(" ", strip=True)) for cell in table.select("thead th")]
    header_map = normalize_header_map(headers)
    symbol_index = header_map.get("symbol")
    name_index = header_map.get("name")
    market_cap_index = header_map.get("market cap")
    if symbol_index is None or market_cap_index is None:
        log_step(f"Cabeceras detectadas: {headers}")
        return []

    companies: list[Company] = []
    for row_index, row in enumerate(table.select("tbody tr"), start=1):
        cells = row.find_all("td")
        if not cells or symbol_index >= len(cells) or market_cap_index >= len(cells):
            continue

        symbol_cell = cells[symbol_index]
        symbol_text = clean_text(symbol_cell.get_text(" ", strip=True))
        # Se priorizan enlaces /quote/... de la propia celda Symbol, porque suelen ser
        # mas fiables que el texto visible cuando Yahoo mezcla variantes regionales.
        links = symbol_cell.select("a[href*='/quote/']")
        symbol_candidates = [extract_symbol_from_href(link.get("href", "")) for link in links]
        symbol_candidates = [candidate for candidate in symbol_candidates if candidate]
        symbol = choose_best_symbol(symbol_candidates)

        if symbol_candidates:
            log_step(
                f"Symbol links in row {row_index}: cell_text={symbol_text!r} "
                f"candidates={symbol_candidates} -> selected={symbol}"
            )

        if not symbol:
            symbol = extract_symbol_from_cell_text(symbol_text)

        if symbol_text and symbol and symbol_text != symbol:
            log_step(f"Symbol cell text={symbol_text!r} -> selected={symbol}")

        if not symbol:
            log_step(f"No se pudo extraer symbol de la fila {row_index}: symbol_text={symbol_text!r}")
            continue

        name = symbol
        if name_index is not None and name_index < len(cells):
            name = clean_text(cells[name_index].get_text(" ", strip=True)) or symbol

        market_cap_text = clean_text(cells[market_cap_index].get_text(" ", strip=True))
        companies.append(
            Company(
                symbol=symbol,
                name=name,
                market_cap=parse_market_cap(market_cap_text),
            )
        )

    log_step(f"Companias parseadas del screener: {len(companies)}")
    return companies


# ------ PERFIL DE COMPANIAS ------

def build_quote_url(symbol: str) -> str:
    return QUOTE_URL_TEMPLATE.format(symbol=symbol)


def fetch_profile_from_api(
    session: requests.Session,
    symbol: str,
    request_delay: float,
    request_jitter: float,
    max_retries: int,
) -> CompanyProfile | None:
    # Primera via: endpoint estructurado de Yahoo para sector e industria.
    url = QUOTE_SUMMARY_URL_TEMPLATE.format(symbol=quote_plus(symbol))
    log_step(f"Perfil API: {symbol} url={url}")
    response = request_with_retry(
        session,
        url,
        timeout=30,
        request_delay=request_delay,
        request_jitter=request_jitter,
        max_retries=max_retries,
        request_label=f"profile_api:{symbol}",
    )
    payload = response.json()

    result = payload.get("quoteSummary", {}).get("result", [])
    if not result:
        return None

    asset_profile = result[0].get("assetProfile", {})
    industry = clean_text(asset_profile.get("industry"))
    if not industry:
        return None
    return CompanyProfile(sector=FIXED_SECTOR, industry=industry)


def extract_profile_value_from_html(html: str, label: str) -> str:
    # Segunda via: buscar Sector / Industry en el HTML cuando falla la API.
    patterns = [
        rf"{label}\s*</dt>\s*<dd[^>]*>\s*<a[^>]*>([^<]+)</a>",
        rf"{label}\s*</span>\s*<span[^>]*>([^<]+)</span>",
        rf'"{label.lower()}"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return ""


def fetch_profile_from_quote_page(
    session: requests.Session,
    symbol: str,
    request_delay: float,
    request_jitter: float,
    max_retries: int,
) -> CompanyProfile | None:
    # Fallback HTML para mantener el scraper funcional aunque quoteSummary falle.
    quote_url = build_quote_url(symbol)
    log_step(f"Perfil HTML: {symbol} url={quote_url}")
    response = request_with_retry(
        session,
        quote_url,
        timeout=30,
        request_delay=request_delay,
        request_jitter=request_jitter,
        max_retries=max_retries,
        request_label=f"profile_html:{symbol}",
    )
    html = response.text
    industry = extract_profile_value_from_html(html, "Industry")
    if not industry:
        return None
    return CompanyProfile(sector=FIXED_SECTOR, industry=industry)


def fetch_company_profile(
    session: requests.Session,
    symbol: str,
    request_delay: float,
    request_jitter: float,
    max_retries: int,
) -> CompanyProfile:
    # La logica intenta primero API y luego HTML para reducir fragilidad.
    try:
        profile = fetch_profile_from_api(session, symbol, request_delay, request_jitter, max_retries)
        if profile:
            log_step(f"Perfil obtenido por API: {symbol} sector={profile.sector} industry={profile.industry}")
            return profile
    except requests.RequestException:
        log_step(f"Fallo perfil API: {symbol}")

    try:
        profile = fetch_profile_from_quote_page(session, symbol, request_delay, request_jitter, max_retries)
        if profile:
            log_step(f"Perfil obtenido por HTML: {symbol} sector={profile.sector} industry={profile.industry}")
            return profile
    except requests.RequestException:
        log_step(f"Fallo perfil HTML: {symbol}")

    log_step(f"Perfil vacio: {symbol}")
    return CompanyProfile(sector=FIXED_SECTOR, industry="")


def filter_profiles_by_sector(
    enriched_companies: list[tuple[Company, CompanyProfile]],
    sectors: set[str],
) -> list[tuple[Company, CompanyProfile]]:
    # El filtrado por sector se hace despues de enriquecer, porque el screener base
    # ya esta acotado a tecnologia pero el usuario puede querer afinar aun mas.
    if not sectors:
        return enriched_companies

    return [
        (company, profile)
        for company, profile in enriched_companies
        if FIXED_SECTOR.casefold() in sectors
    ]


# ------ DESCARGA DE HISTORICOS ------

def build_history_rows(
    session: requests.Session,
    company: Company,
    profile: CompanyProfile,
    period_range: str,
    interval: str,
    request_delay: float,
    request_jitter: float,
    max_retries: int,
) -> list[dict[str, object]]:
    # El historico se descarga desde el endpoint chart y se aplana a filas CSV.
    # market_cap_today, sector e industry se repiten para cada fecha porque no son
    # series historicas en este proyecto, sino metadatos actuales de la empresa.
    history_url = CHART_API_URL.format(symbol=quote_plus(company.symbol))
    log_step(
        f"Descargando historico: {company.symbol} "
        f"url={history_url} range={period_range} interval={interval}"
    )
    response = request_with_retry(
        session,
        history_url,
        params={
            "range": period_range,
            "interval": interval,
            "includePrePost": "false",
            "events": "div,splits",
        },
        timeout=30,
        request_delay=request_delay,
        request_jitter=request_jitter,
        max_retries=max_retries,
        request_label=f"history:{company.symbol}",
    )
    payload = response.json()

    result = payload.get("chart", {}).get("result", [])
    if not result:
        error = payload.get("chart", {}).get("error")
        raise RuntimeError(f"No hay historico para {company.symbol}: {error}")

    result_item = result[0]
    timestamps = result_item.get("timestamp", [])
    quotes = result_item.get("indicators", {}).get("quote", [])
    adjclose_rows = result_item.get("indicators", {}).get("adjclose", [{}])
    if not timestamps or not quotes:
        return []

    quote = quotes[0]
    adj_close = adjclose_rows[0].get("adjclose", [])
    if len(adj_close) != len(timestamps):
        adj_close = [None] * len(timestamps)

    opens = quote.get("open", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])

    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(timestamps):
        open_value = opens[index] if index < len(opens) else None
        high_value = highs[index] if index < len(highs) else None
        low_value = lows[index] if index < len(lows) else None
        close_value = closes[index] if index < len(closes) else None
        adj_close_value = adj_close[index] if index < len(adj_close) else None
        volume_value = volumes[index] if index < len(volumes) else None

        if None in {open_value, high_value, low_value, close_value}:
            # Yahoo puede devolver huecos en semanas sin negociacion o series incompletas.
            continue

        rows.append(
            {
                "symbol": company.symbol,
                "company_name": company.name,
                "sector": profile.sector,
                "industry": profile.industry,
                "market_cap_today": company.market_cap,
                "date": datetime.fromtimestamp(timestamp, UTC).replace(tzinfo=None).isoformat(sep=" "),
                "open": format_numeric(open_value),
                "high": format_numeric(high_value),
                "low": format_numeric(low_value),
                "close": format_numeric(close_value),
                "adj_close": format_numeric(adj_close_value),
                "volume": format_numeric(volume_value),
            }
        )

    return rows


# ------ SALIDA A CSV ------

def build_output_path(explicit_path: Path | None) -> Path:
    # Si el usuario no indica ruta, se genera un nombre con timestamp para no pisar salidas previas.
    if explicit_path:
        explicit_path.parent.mkdir(parents=True, exist_ok=True)
        return explicit_path

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"yahoo_finance_technology_top100_{timestamp}.csv"


def save_to_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    # Se fija el orden de columnas para que el CSV sea estable entre ejecuciones.
    ordered_columns = [
        "symbol",
        "company_name",
        "sector",
        "industry",
        "market_cap_today",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ordered_columns, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)


# ------ EJECUCION PRINCIPAL ------

def main() -> None:
    # Flujo completo:
    # 1. descargar screener
    # 2. extraer companias
    # 3. filtrar por market cap
    # 4. enriquecer con sector/industry
    # 5. descargar historico
    # 6. guardar CSV
    args = parse_args()
    session = build_session()
    sectors = normalize_sector_list(args.sectors)
    log_user_agent(session)
    log_step(
        "Inicio scraper "
        "min_market_cap="
        f"{args.min_market_cap} limit={args.limit} sectors={sorted(sectors) if sectors else 'ALL'} "
        f"request_delay={args.request_delay} request_jitter={args.request_jitter} max_retries={args.max_retries}"
    )

    screener_html = fetch_screener_html(
        session,
        request_delay=args.request_delay,
        request_jitter=args.request_jitter,
        max_retries=args.max_retries,
    )
    screener_companies = parse_companies_from_html(screener_html)
    if not screener_companies:
        raise RuntimeError("No se han encontrado companias en el screener.")
    log_company_symbols("Simbolos extraidos del screener", screener_companies)

    companies = [company for company in screener_companies if company.market_cap >= args.min_market_cap]
    companies.sort(key=lambda company: company.market_cap, reverse=True)
    log_step(f"Companias tras filtro market cap: {len(companies)}")
    log_company_symbols("Simbolos tras filtro market cap", companies)
    if args.limit is not None:
        companies = companies[: args.limit]
        log_step(f"Companias tras aplicar limit={args.limit}: {len(companies)}")
        log_company_symbols("Simbolos tras aplicar limit", companies)
    if not companies:
        raise RuntimeError("No se han encontrado compañías que cumplan el filtro de capitalización.")

    enriched_companies = [
        (
            company,
            fetch_company_profile(
                session,
                company.symbol,
                request_delay=args.request_delay,
                request_jitter=args.request_jitter,
                max_retries=args.max_retries,
            ),
        )
        for company in companies
    ]
    enriched_companies = filter_profiles_by_sector(enriched_companies, sectors)
    log_step(f"Companias tras filtro sector: {len(enriched_companies)}")
    if not enriched_companies:
        raise RuntimeError("No hay companias que cumplan el filtro de sector.")

    historical_batches = [
        build_history_rows(
            session,
            company,
            profile,
            args.range,
            args.interval,
            request_delay=args.request_delay,
            request_jitter=args.request_jitter,
            max_retries=args.max_retries,
        )
        for company, profile in enriched_companies
    ]
    output_rows = [row for batch in historical_batches for row in batch]
    if not output_rows:
        raise RuntimeError("No se han obtenido series históricas.")

    output_rows.sort(key=lambda row: (str(row["symbol"]), str(row["date"])))
    output_path = build_output_path(args.output)
    save_to_csv(output_rows, output_path)
    log_step("CSV guardado correctamente")

    print(f"Compañías en el screener: {len(screener_companies)}")
    print(f"Compañías tras market cap: {len(companies)}")
    print(f"Compañías tras sector: {len(enriched_companies)}")
    print(f"Filas históricas guardadas: {len(output_rows)}")
    print(f"CSV generado: {output_path}")
    print(f"Screener usado: {SCREENER_URL}")


if __name__ == "__main__":
    main()
