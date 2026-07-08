#!/usr/bin/env python3
"""
parsear_texto.py
================
Convierte el texto plano del Código Penal Paraguayo (Ley 1160/97)
en el JSON estructurado que usa index.html.

USO:
  1. Copiá el texto del PDF (OAS, DINAPI, PJ, etc.) en un archivo .txt
  2. Ejecutá:  python parsear_texto.py codigo_penal.txt
  3. El script produce:  codigo_penal_completo.json

El script combina el texto extraído con la estructura de capítulos
existente en el JSON, emparejando por número de artículo.
"""

import re
import json
import sys
import unicodedata
from pathlib import Path

# ────────────────────────────────────────────────────────────────
# PATRONES DE RECONOCIMIENTO
# ────────────────────────────────────────────────────────────────

# Encabezado de artículo. Variantes reales encontradas en distintas versiones:
#   Artículo 1.- Principio de legalidad
#   Artículo. 1.- Principio
#   Art. 1° Principio
#   ARTICULO 1°.-
#   Artculo 1.- (typo comun en scans)
ART_HEADER = re.compile(
    r'^\s*Art[ií]culo\.?\s*(\d+)[\u00b0\.\-º]*\s*[-.]?\s*(.*)',
    re.IGNORECASE
)

# Líneas que son ruido (encabezados de sección, números de página, etc.)
NOISE = re.compile(
    r'^(Título|TITULO|Capítulo|CAPITULO|Libro|LIBRO|\d+\s*$|'
    r'Ley N|CODIGO PENAL|CÓDIGO PENAL|República del Paraguay|'
    r'Modificado por|Regulado por|Ver también|\[|www\.|https?:)',
    re.IGNORECASE
)

# Inciso / numeral: 1°, 2º, 1., 2., a), b), i), ii)
INCISO = re.compile(r'^(\d+[\u00b0\u00ba\.]|[a-z]\)|[ivx]+\))\s+', re.IGNORECASE)

# Palabras de alta frecuencia jurídica para excluir de palabrasClave
STOPWORDS = {
    'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'en', 'con',
    'por', 'para', 'que', 'se', 'al', 'su', 'sus', 'o', 'u', 'y', 'e',
    'a', 'no', 'le', 'lo', 'cuando', 'si', 'ser', 'será', 'serán',
    'haya', 'este', 'esta', 'esto', 'como', 'más', 'entre', 'sobre',
    'sin', 'hasta', 'desde', 'todo', 'toda', 'todos', 'todas', 'dicho',
    'dicha', 'mismo', 'misma', 'puede', 'podrá', 'podrán', 'inc',
    'num', 'art', 'artículo', 'inciso', 'numeral', 'disposición',
}

# ────────────────────────────────────────────────────────────────
# LIMPIEZA DE TEXTO
# ────────────────────────────────────────────────────────────────

def clean_line(line: str) -> str:
    """Normaliza espacios y caracteres Unicode raros del copy-paste de PDF."""
    # Reemplazar guiones de no-separación, espacios especiales, etc.
    line = line.replace('\u00ad', '-')   # guion suave
    line = line.replace('\u2013', '-')   # en-dash
    line = line.replace('\u2014', '-')   # em-dash
    line = line.replace('\u00a0', ' ')   # espacio de no-separación
    line = line.replace('\u2019', "'")   # comilla curva
    line = line.replace('\u201c', '"').replace('\u201d', '"')
    # Colapsar múltiples espacios
    line = re.sub(r'[ \t]+', ' ', line)
    return line.strip()


def normalize_str(s: str) -> str:
    """Minusculas sin tildes para comparaciones."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s.lower())
        if unicodedata.category(c) != 'Mn'
    )


# ────────────────────────────────────────────────────────────────
# PARSEO DEL TEXTO PLANO  →  LISTA DE ARTÍCULOS
# ────────────────────────────────────────────────────────────────

def parse_text(raw_text: str) -> dict:
    """
    Recorre el texto línea a línea y construye un diccionario:
      { numero_articulo (int): { 'epigrafe': str, 'parrafos': [str] } }
    """
    articles = {}
    current_num = None
    current_epigrafe = ''
    current_parrafos = []
    buffer = ''

    def flush_buffer():
        nonlocal buffer
        b = buffer.strip()
        buffer = ''
        if b and current_num is not None:
            current_parrafos.append(b)

    def save_article():
        if current_num is not None:
            flush_buffer()
            # Fusionar párrafos partidos (líneas cortas que continuan en la siguiente)
            merged = merge_paragraphs(current_parrafos)
            articles[current_num] = {
                'epigrafe': current_epigrafe,
                'parrafos': merged
            }

    lines = raw_text.splitlines()

    for raw_line in lines:
        line = clean_line(raw_line)

        if not line:
            # Línea en blanco: posible separador de párrafo
            flush_buffer()
            continue

        # Detectar encabezado de artículo
        m = ART_HEADER.match(line)
        if m:
            save_article()
            current_num = int(m.group(1))
            raw_epigrafe = m.group(2).strip().rstrip('.-').strip()
            current_epigrafe = raw_epigrafe
            current_parrafos = []
            buffer = ''
            continue

        if current_num is None:
            continue

        # Filtrar ruido
        if NOISE.match(line):
            continue

        # Si la línea empieza un inciso nuevo, flush el buffer y comenzar nuevo
        if INCISO.match(line):
            flush_buffer()
            buffer = line
        else:
            # Si la línea parece continuación (no empieza con mayúscula o inciso),
            # concatenarla al buffer actual
            if buffer and not line[0].isupper():
                buffer += ' ' + line
            else:
                flush_buffer()
                buffer = line

    save_article()  # guardar el último artículo
    return articles


def merge_paragraphs(parrafos: list) -> list:
    """
    Intenta unir párrafos muy cortos (< 60 chars) que probablemente
    son continuación de la línea anterior por ruptura de PDF.
    """
    merged = []
    for p in parrafos:
        if merged and len(merged[-1]) < 60 and not merged[-1].endswith('.'):
            merged[-1] += ' ' + p
        else:
            merged.append(p)
    return merged


# ────────────────────────────────────────────────────────────────
# EXTRACTOR DE PALABRAS CLAVE
# ────────────────────────────────────────────────────────────────

def extract_keywords(epigrafe: str, parrafos: list, top_n: int = 8) -> list:
    """
    Extrae las palabras más relevantes del epígrafe y los párrafos.
    Prioriza palabras del epígrafe (peso x5) vs texto.
    Excluye stopwords, números y palabras de menos de 4 letras.
    """
    from collections import Counter

    token_re = re.compile(r'[a-záéíóúüñ]+', re.IGNORECASE)
    freq = Counter()

    # Epígrafe con peso mayor
    for tok in token_re.findall(epigrafe):
        w = normalize_str(tok)
        if len(w) >= 4 and w not in STOPWORDS:
            freq[tok.lower()] += 5

    for parr in parrafos:
        for tok in token_re.findall(parr):
            w = normalize_str(tok)
            if len(w) >= 4 and w not in STOPWORDS:
                freq[tok.lower()] += 1

    return [word for word, _ in freq.most_common(top_n)]


# ────────────────────────────────────────────────────────────────
# INYECCIÓN EN JSON EXISTENTE
# ────────────────────────────────────────────────────────────────

def inject_into_json(json_path: Path, parsed_articles: dict) -> dict:
    """
    Abre el JSON estructurado existente e inyecta el texto parseado
    en cada artículo, emparejando por numero.
    Respeta el texto ya existente (no sobreescribe si ya tiene contenido).
    Retorna el JSON modificado y un reporte de cobertura.
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = 0
    filled = 0
    skipped = 0
    not_found = []

    for libro in data.get('libros', []):
        for titulo in libro.get('titulos', []):
            for capitulo in titulo.get('capitulos', []):
                for art in capitulo.get('articulos', []):
                    total += 1
                    num = art['numero']
                    parsed = parsed_articles.get(num)

                    if parsed is None:
                        not_found.append(num)
                        continue

                    # No sobreescribir si ya tiene texto
                    if art.get('texto') and any(t.strip() for t in art['texto']):
                        skipped += 1
                        continue

                    art['epigrafe'] = parsed['epigrafe']
                    art['texto'] = parsed['parrafos']
                    art['palabrasClave'] = extract_keywords(
                        parsed['epigrafe'], parsed['parrafos']
                    )
                    filled += 1

    report = {
        'total_en_json': total,
        'rellenados': filled,
        'ya_tenian_texto': skipped,
        'no_encontrados_en_txt': not_found,
        'articulos_parseados_del_txt': len(parsed_articles),
    }
    return data, report


# ────────────────────────────────────────────────────────────────
# MODO: GENERAR JSON DESDE CERO (sin estructura previa)
# ────────────────────────────────────────────────────────────────

def build_flat_json(parsed_articles: dict) -> dict:
    """
    Si no existe un JSON base, construye uno plano con todos
    los artículos extraídos, sin jerarquía de libros/títulos/capítulos.
    Útil como punto de partida para agregar la estructura manualmente.
    """
    articulos = []
    for num in sorted(parsed_articles.keys()):
        p = parsed_articles[num]
        articulos.append({
            'numero': num,
            'epigrafe': p['epigrafe'],
            'texto': p['parrafos'],
            'palabrasClave': extract_keywords(p['epigrafe'], p['parrafos']),
            'rutasRelacionadas': [],
            'notas': []
        })
    return {
        'codigo': 'Código Penal de la República del Paraguay',
        'ley': 'Ley Nº 1160/1997',
        'version': {'fuente': 'parseado automaticamente', 'actualizado': '2025'},
        '_nota': 'JSON plano generado por parsear_texto.py. Agrégale estructura libros/titulos/capitulos.',
        'articulos': articulos
    }


# ────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────

HELP = """
USO:
  python parsear_texto.py <archivo_texto.txt> [--json <codigo_penal_completo.json>] [--salida <output.json>]

ARGUMENTOS:
  <archivo_texto.txt>        Texto plano del Código Penal (copiá del PDF o exportá con pdftotext)
  --json <archivo.json>      JSON estructurado base (por defecto: codigo_penal_completo.json).
                             Si existe, inyecta el texto en la estructura existente.
                             Si no existe o se omite --json, genera un JSON plano nuevo.
  --salida <archivo.json>    Archivo de salida (por defecto: codigo_penal_completo.json)
  --forzar                   Sobreescribe artículos que ya tengan texto en el JSON.
  --solo-reporte             No escribe nada, solo muestra el reporte de cobertura.

EJEMPLOS:
  # Extraer texto del PDF y parsear (requiere pdftotext, parte de poppler):
  pdftotext -layout codigo_penal.pdf codigo_penal.txt
  python parsear_texto.py codigo_penal.txt

  # Inyectar en el JSON estructurado existente:
  python parsear_texto.py codigo_penal.txt --json codigo_penal_completo.json

  # Ver cobertura sin escribir nada:
  python parsear_texto.py codigo_penal.txt --json codigo_penal_completo.json --solo-reporte
"""


def main():
    args = sys.argv[1:]

    if not args or '--help' in args or '-h' in args:
        print(HELP)
        sys.exit(0)

    txt_path = Path(args[0])
    if not txt_path.exists():
        print(f'[ERROR] No se encuentra el archivo: {txt_path}')
        sys.exit(1)

    json_path = None
    salida_path = Path('codigo_penal_completo.json')
    forzar = '--forzar' in args
    solo_reporte = '--solo-reporte' in args

    for i, a in enumerate(args):
        if a == '--json' and i + 1 < len(args):
            json_path = Path(args[i + 1])
        if a == '--salida' and i + 1 < len(args):
            salida_path = Path(args[i + 1])

    # Si no se especificó --json, buscar el default en el mismo directorio
    if json_path is None:
        default = Path('codigo_penal_completo.json')
        if default.exists():
            json_path = default
            print(f'[INFO] Usando JSON base: {json_path}')

    # ── Leer y parsear el texto ──
    print(f'[PASO 1] Leyendo texto de: {txt_path}')
    raw = txt_path.read_text(encoding='utf-8', errors='replace')
    parsed = parse_text(raw)
    print(f'         {len(parsed)} artículos detectados en el texto.')

    if not parsed:
        print('[ERROR] No se detectó ningún artículo. Verificá el formato del archivo.')
        print('        El texto debe contener líneas como: "Artículo 1.- Principio de legalidad"')
        sys.exit(1)

    # Mostrar preview de los primeros 3 artículos
    print('\n[PREVIEW] Primeros 3 artículos detectados:')
    for num in sorted(parsed.keys())[:3]:
        p = parsed[num]
        preview = (p['parrafos'][0][:80] + '…') if p['parrafos'] else '(sin texto)'
        print(f'  Art. {num}: "{p["epigrafe"]}"')
        print(f'           {preview}')
    print()

    # ── Inyectar en JSON o generar plano ──
    if json_path and json_path.exists():
        print(f'[PASO 2] Inyectando en JSON estructurado: {json_path}')

        # Si se especificó --forzar, temporalmente limpiar el flag de no-sobreescritura
        if forzar:
            # Leer JSON y vaciar todos los textos para forzar sobreescritura
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for libro in data.get('libros', []):
                for titulo in libro.get('titulos', []):
                    for cap in titulo.get('capitulos', []):
                        for art in cap.get('articulos', []):
                            art['texto'] = []
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)

        result_data, report = inject_into_json(json_path, parsed)
    else:
        print('[PASO 2] No se encontró JSON base. Generando JSON plano...')
        result_data = build_flat_json(parsed)
        report = {
            'total_en_json': len(parsed),
            'rellenados': len(parsed),
            'ya_tenian_texto': 0,
            'no_encontrados_en_txt': [],
            'articulos_parseados_del_txt': len(parsed),
        }

    # ── Reporte ──
    print('[REPORTE DE COBERTURA]')
    print(f'  Artículos en el JSON base:         {report["total_en_json"]}')
    print(f'  Artículos rellenos ahora:          {report["rellenados"]}')
    print(f'  Ya tenían texto (no tocados):      {report["ya_tenian_texto"]}')
    print(f'  Artículos parseados del .txt:      {report["articulos_parseados_del_txt"]}')
    if report['no_encontrados_en_txt']:
        print(f'  [AVISO] Art. en JSON sin match en .txt: {report["no_encontrados_en_txt"]}')

    cobertura = (
        (report['rellenados'] + report['ya_tenian_texto']) / report['total_en_json'] * 100
        if report['total_en_json'] else 0
    )
    print(f'  Cobertura total: {cobertura:.1f}%')

    if solo_reporte:
        print('\n[--solo-reporte] No se escribió ningún archivo.')
        return

    # ── Guardar ──
    print(f'\n[PASO 3] Guardando resultado en: {salida_path}')
    with open(salida_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    size_kb = salida_path.stat().st_size / 1024
    print(f'         ✔ Guardado correctamente ({size_kb:.1f} KB)')
    print('\nListo. Recargá el index.html en tu navegador para ver los cambios.')


if __name__ == '__main__':
    main()
