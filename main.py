from flask import Flask, render_template, request, jsonify, send_from_directory, make_response
import os
import requests
import csv
import io
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = 'carnaval_secret_key'

load_dotenv()

SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1s_Vm7BCW1ZYtCf79CKZ7clFdeRvEzqNbCQOhq6ZeG_U/export?format=csv&gid=1903941151"
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
CACHE_FILE = 'latlon_cache.json'

# --- 1. GLOBAL CACHE FOR DATA ---
# Cache structure: {'data': [eventos], 'styles': [styles], 'timestamp': datetime}
DATA_CACHE = {
    'data': [],
    'styles': [],
    'timestamp': None
}
CACHE_DURATION_MINUTES = 30  # Refresh CSV every 5 minutes

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cache(cache_data):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Error saving cache: {e}")

geo_cache = load_cache()

# --- 2. BRASILIA TIME HELPER ---
def get_brasilia_time():
    """Returns the current naive datetime in Brasilia Time (UTC-3)."""
    # Get UTC time (naive)
    utc_now = datetime.utcnow()
    # Subtract 3 hours to get Brasilia time
    return utc_now - timedelta(hours=3)

def get_lat_lon(address, neighborhood):
    global geo_cache
    key = f"{address} - {neighborhood}".strip()
    
    if not key:
        return None, None

    if key in geo_cache:
        return geo_cache[key]['lat'], geo_cache[key]['lon']

    if not GOOGLE_MAPS_API_KEY:
        return None, None

    search_query = f"{address}, {neighborhood}, Belo Horizonte, MG" if address else f"{neighborhood}, Belo Horizonte, MG"
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={search_query}&key={GOOGLE_MAPS_API_KEY}"
    
    try:
        response = requests.get(url, timeout=3)
        data = response.json()
        
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            lat, lon = location['lat'], location['lng']
            geo_cache[key] = {'lat': lat, 'lon': lon}
            save_cache(geo_cache)
            return lat, lon
    except Exception as e:
        print(f"Geocoding connection error: {e}")
    
    return None, None

def fetch_carnival_data():
    global DATA_CACHE
    
    # Check if cache is valid
    now_br = get_brasilia_time()
    if DATA_CACHE['timestamp'] and (now_br - DATA_CACHE['timestamp']).total_seconds() < (CACHE_DURATION_MINUTES * 60):
        # Recalculate status logic on cached data (time changes, data stays same)
        return events_status_logic(DATA_CACHE['data']), DATA_CACHE['styles']

    # If cache expired or empty, fetch from Google Sheets
    eventos = []
    unique_styles = set()
    
    dias_semana = {0: 'Seg', 1: 'Ter', 2: 'Qua', 3: 'Qui', 4: 'Sex', 5: 'Sáb', 6: 'Dom'}

    try:
        response = requests.get(SHEET_CSV_URL)
        response.encoding = 'utf-8'
        
        if response.status_code != 200:
            return [], []

        csv_file = io.StringIO(response.text)
        reader = csv.DictReader(csv_file)
        
        for row in reader:
            titulo = row.get("NOME DO BLOCO", "Bloco sem nome").strip()
            bairro = row.get("Bairro", "").strip()
            endereco = row.get("LOCAL DA CONCENTRAÇÃO", "").strip()
            
            raw_categoria = row.get("ESTILO MUSICAL", "Outros").strip()
            
            if len(raw_categoria) > 25 or "," in raw_categoria or " e " in raw_categoria:
                categoria_display = "Variado"
            else:
                categoria_display = raw_categoria

            parts = re.split(r'[;,/]\s*|\s+e\s+', raw_categoria)
            for part in parts:
                clean_part = part.strip().title()
                if len(clean_part) > 1:
                    unique_styles.add(clean_part)

            descricao_orig = row.get("OBS", "").strip()
            desc_lower = descricao_orig.lower()
            
            is_kids = False
            is_lgbt = False
            is_pet = False
            clean_desc = descricao_orig
            
            if "infantil" in desc_lower or "criança" in desc_lower or "baby" in desc_lower or "👶" in descricao_orig:
                is_kids = True
                clean_desc = re.sub(r'(?i)(bloco)?\s*infantil|criança|baby|👶', '', clean_desc)

            if "lgbt" in desc_lower or "gay" in desc_lower or "diversidade" in desc_lower or "🏳" in descricao_orig:
                is_lgbt = True
                clean_desc = re.sub(r'(?i)lgbt\w*|gay|diversidade', '', clean_desc)
                clean_desc = clean_desc.replace('🏳️‍🌈', '').replace('🏳‍🌈', '') 
                clean_desc = re.sub(r'[\U0001F3F3\uFE0F\u200D\U0001F308]', '', clean_desc)

            if "pet" in desc_lower or "cachorro" in desc_lower or "animal" in desc_lower or "🐶" in descricao_orig or "🐕" in descricao_orig:
                is_pet = True
                clean_desc = re.sub(r'(?i)pet|cachorro|animal|🐶|🐕', '', clean_desc)

            clean_desc = re.sub(r'^\W+|\W+$', '', clean_desc) 
            clean_desc = clean_desc.strip()
            
            tamanho_raw = row.get("TAMANHO", "").lower()
            tamanho_score = 1
            if "grande" in tamanho_raw:
                tamanho_score = 3
            elif "médio" in tamanho_raw or "medio" in tamanho_raw:
                tamanho_score = 2

            data_raw = row.get("DATA", "")
            hora_raw = row.get("HORÁRIO DA CONCENTRAÇÃO", "")
            dt_obj = None
            data_formatada = "A definir"
            
            if data_raw:
                try:
                    data_clean = data_raw.split(' ')[0]
                    if hora_raw:
                        dt_obj = datetime.strptime(f"{data_clean} {hora_raw}", '%d/%m/%Y %H:%M')
                        dia_sem = dias_semana[dt_obj.weekday()]
                        data_formatada = f"{dt_obj.strftime('%d/%m')} ({dia_sem}) - {dt_obj.strftime('%H:%M')}"
                    else:
                        dt_obj = datetime.strptime(data_clean, '%d/%m/%Y')
                        dia_sem = dias_semana[dt_obj.weekday()]
                        data_formatada = f"{dt_obj.strftime('%d/%m')} ({dia_sem})"
                except:
                    data_formatada = f"{data_raw} {hora_raw}"

            lat, lon = get_lat_lon(endereco, bairro)

            eventos.append({
                "id": str(hash(titulo + data_formatada)),
                "titulo": titulo,
                "local": bairro,
                "endereco": endereco,
                "data": data_formatada,
                "_dt_obj": dt_obj,
                "categoria": raw_categoria,
                "categoria_display": categoria_display,
                "descricao": clean_desc,
                "tamanho": tamanho_score,
                "lat": lat,
                "lon": lon,
                "status": "futuro", 
                "is_kids": is_kids,
                "is_lgbt": is_lgbt,
                "is_pet": is_pet
            })
            
        # Update Cache
        DATA_CACHE['data'] = events_status_logic(eventos) # Store unsorted initially? No, logic sorts.
        DATA_CACHE['styles'] = sorted(list(unique_styles))
        DATA_CACHE['timestamp'] = now_br
            
    except Exception as e:
        print(f"Error processing CSV: {e}")

    return DATA_CACHE['data'], DATA_CACHE['styles']

def events_status_logic(eventos_raw):
    # Create a shallow copy so we don't mutate the cached list permanently if we re-run logic
    eventos = [e.copy() for e in eventos_raw]
    
    # 3. USE BRASILIA TIME HERE
    now = get_brasilia_time()
    
    # now = datetime(2025, 3, 3, 13, 0) # Testing Override

    for e in eventos:
        if not e['_dt_obj']: 
            e['status'] = 'futuro'
            e['status_label'] = ''
            e['sort_weight'] = 3
            continue
            
        dt = e['_dt_obj']
        diff = (dt - now).total_seconds() / 3600
        
        if 0 < diff <= 2:
            e['status'] = 'em-breve'
            e['status_label'] = 'Em Breve'
            e['sort_weight'] = 0
        elif -3 <= diff <= 0:
            e['status'] = 'em-andamento'
            e['status_label'] = 'Em Andamento'
            e['sort_weight'] = 0
        elif -5 <= diff < -3:
            e['status'] = 'encerrando'
            e['status_label'] = 'Encerrando'
            e['sort_weight'] = 1
        elif diff < -5:
            e['status'] = 'encerrado'
            e['status_label'] = 'Encerrado'
            e['sort_weight'] = 4
        elif dt.date() == now.date():
            e['status'] = 'hoje'
            e['status_label'] = 'Hoje'
            e['sort_weight'] = 2
        else:
            e['status'] = 'futuro'
            e['status_label'] = ''
            e['sort_weight'] = 3
            
    eventos.sort(key=lambda x: (x['sort_weight'], x['_dt_obj'] if x['_dt_obj'] else datetime.max))
    return eventos

def filtrar_eventos(eventos_todos, args):
    has_active_filters = False
    
    filtro_data = args.get('data_filtro')
    filtro_bairro = args.get('bairro')
    filtro_estilo = args.get('categoria')
    quick_filters = args.getlist('quick_filter') 
    busca = args.get('q', '').lower()
    ne_lat = args.get('ne_lat')
    
    if filtro_data or filtro_bairro or filtro_estilo or quick_filters or busca or ne_lat:
        has_active_filters = True

    eventos_filtrados = eventos_todos
    
    # 4. USE BRASILIA TIME FOR FILTERING
    now = get_brasilia_time()

    if quick_filters:
        target_dates = []
        target_sizes = []
        target_periods = []

        if 'hoje' in quick_filters: target_dates.append(now.date())
        if 'amanha' in quick_filters: target_dates.append(now.date() + timedelta(days=1))
        
        target_statuses = [s for s in ['em-andamento', 'em-breve', 'encerrando'] if s in quick_filters]
        
        if 'grande' in quick_filters: target_sizes.append(3)
        if 'medio' in quick_filters: target_sizes.append(2)
        if 'pequeno' in quick_filters: target_sizes.append(1)
        if 'manha' in quick_filters: target_periods.append('manha')
        if 'tarde' in quick_filters: target_periods.append('tarde')
        if 'noite' in quick_filters: target_periods.append('noite')
        
        if target_dates:
            eventos_filtrados = [e for e in eventos_filtrados if e['_dt_obj'] and e['_dt_obj'].date() in target_dates]
        if target_statuses:
            eventos_filtrados = [e for e in eventos_filtrados if e['status'] in target_statuses]
        if target_sizes:
            eventos_filtrados = [e for e in eventos_filtrados if e['tamanho'] in target_sizes]
        if target_periods:
            def check_period(dt):
                h = dt.hour
                matches = []
                if 'manha' in target_periods: matches.append(5 <= h < 12)
                if 'tarde' in target_periods: matches.append(12 <= h < 18)
                if 'noite' in target_periods: matches.append(18 <= h or h < 5)
                return any(matches)
            eventos_filtrados = [e for e in eventos_filtrados if e['_dt_obj'] and check_period(e['_dt_obj'])]

    if filtro_data:
        try:
            target = datetime.strptime(filtro_data, '%Y-%m-%d').date()
            eventos_filtrados = [e for e in eventos_filtrados if e['_dt_obj'] and e['_dt_obj'].date() == target]
        except: pass

    if filtro_bairro:
        eventos_filtrados = [e for e in eventos_filtrados if e['local'] == filtro_bairro]

    if filtro_estilo:
        eventos_filtrados = [e for e in eventos_filtrados if filtro_estilo.lower() in e['categoria'].lower()]

    if busca:
        eventos_filtrados = [e for e in eventos_filtrados if busca in e['titulo'].lower() or busca in e['endereco'].lower()]
        
    ne_lng = args.get('ne_lng')
    sw_lat = args.get('sw_lat')
    sw_lng = args.get('sw_lng')

    if ne_lat and ne_lng and sw_lat and sw_lng:
        try:
            n_lat = float(ne_lat)
            n_lng = float(ne_lng)
            s_lat = float(sw_lat)
            s_lng = float(sw_lng)
            
            eventos_filtrados = [
                e for e in eventos_filtrados 
                if e['lat'] and e['lon'] and 
                s_lat <= e['lat'] <= n_lat and 
                s_lng <= e['lon'] <= n_lng
            ]
        except ValueError:
            pass
    
    return eventos_filtrados, has_active_filters

@app.route('/')
def mostrar_eventos():
    eventos_todos, estilos = fetch_carnival_data()
    eventos_filtrados, has_filters = filtrar_eventos(eventos_todos, request.args)

    bairros = sorted(list(set([e['local'] for e in eventos_todos if e['local']])))
    
    response = make_response(render_template('index.html', 
                           eventos=eventos_filtrados,
                           bairros=bairros,
                           estilos=estilos,
                           total=len(eventos_filtrados),
                           has_filters=has_filters,
                           google_maps_api_key=GOOGLE_MAPS_API_KEY))
    
    # 5. KEEP NO-CACHE FOR HTML (Ensures Status tags update on refresh)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/api/eventos')
def api_eventos():
    eventos_todos, _ = fetch_carnival_data()
    eventos_filtrados, _ = filtrar_eventos(eventos_todos, request.args)
    geocoded = [e for e in eventos_filtrados if e['lat'] and e['lon']]
    for e in geocoded:
        if '_dt_obj' in e: del e['_dt_obj']
    
    # We can allow the API to be cached briefly by the browser if desired, 
    # but for real-time status consistency, keeping it fresh is safer.
    return jsonify(geocoded)

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

if __name__ == '__main__':
    app.run(debug=True, port=5000)