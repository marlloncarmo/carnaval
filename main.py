from flask import Flask, render_template, request, jsonify, send_from_directory
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
    eventos = []
    try:
        response = requests.get(SHEET_CSV_URL)
        response.encoding = 'utf-8'
        
        if response.status_code != 200:
            return []

        csv_file = io.StringIO(response.text)
        reader = csv.DictReader(csv_file)
        
        for row in reader:
            titulo = row.get("NOME DO BLOCO", "Bloco sem nome").strip()
            bairro = row.get("Bairro", "").strip()
            endereco = row.get("LOCAL DA CONCENTRAÇÃO", "").strip()
            categoria = row.get("ESTILO MUSICAL", "Outros").strip()
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
                        data_formatada = dt_obj.strftime('%d/%m - %H:%M')
                    else:
                        dt_obj = datetime.strptime(data_clean, '%d/%m/%Y')
                        data_formatada = dt_obj.strftime('%d/%m')
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
                "categoria": categoria,
                "descricao": clean_desc,
                "tamanho": tamanho_score,
                "lat": lat,
                "lon": lon,
                "status": "futuro", 
                "is_kids": is_kids,
                "is_lgbt": is_lgbt,
                "is_pet": is_pet
            })
            
    except Exception as e:
        print(f"Error processing CSV: {e}")

    return events_status_logic(eventos)

def events_status_logic(eventos):
    now = datetime.now()
    # now = datetime(2025, 3, 3, 13, 0) # Testing

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
    filtro_data = args.get('data_filtro')
    filtro_periodo = args.get('periodo_dia')
    filtro_bairro = args.get('bairro')
    filtro_estilo = args.get('categoria')
    filtro_status = args.get('status_filter')
    
    # 4. UPDATED: Get list for multiple checkboxes
    quick_filters = args.getlist('quick_filter') 
    
    busca = args.get('q', '').lower()
    ne_lat = args.get('ne_lat')
    ne_lng = args.get('ne_lng')
    sw_lat = args.get('sw_lat')
    sw_lng = args.get('sw_lng')

    eventos_filtrados = eventos_todos
    now = datetime.now()

    # 1. Filter by Status Dropdown
    if filtro_status:
        if filtro_status == 'hoje':
            eventos_filtrados = [e for e in eventos_filtrados if e['_dt_obj'] and e['_dt_obj'].date() == now.date()]
        else:
            eventos_filtrados = [e for e in eventos_filtrados if e['status'] == filtro_status]

    # 2. UPDATED Quick Filters Logic (Multi-select)
    if quick_filters:
        target_dates = []
        target_sizes = []
        
        # Parse filters
        if 'hoje' in quick_filters:
            target_dates.append(now.date())
        if 'amanha' in quick_filters:
            target_dates.append(now.date() + timedelta(days=1))
            
        if 'grande' in quick_filters: target_sizes.append(3)
        if 'medio' in quick_filters: target_sizes.append(2)
        if 'pequeno' in quick_filters: target_sizes.append(1)
        
        # Apply Date Filter (OR logic between selected days)
        if target_dates:
            eventos_filtrados = [e for e in eventos_filtrados if e['_dt_obj'] and e['_dt_obj'].date() in target_dates]
            
        # Apply Size Filter (OR logic between selected sizes)
        if target_sizes:
            eventos_filtrados = [e for e in eventos_filtrados if e['tamanho'] in target_sizes]

    # Standard Filters
    if filtro_data:
        try:
            target = datetime.strptime(filtro_data, '%Y-%m-%d').date()
            eventos_filtrados = [e for e in eventos_filtrados if e['_dt_obj'] and e['_dt_obj'].date() == target]
        except: pass

    if filtro_periodo:
        def check_p(dt):
            h = dt.hour
            if filtro_periodo == 'manha': return 5 <= h < 12
            if filtro_periodo == 'tarde': return 12 <= h < 18
            if filtro_periodo == 'noite': return 18 <= h or h < 5
            return True
        eventos_filtrados = [e for e in eventos_filtrados if e['_dt_obj'] and check_p(e['_dt_obj'])]

    if filtro_bairro:
        eventos_filtrados = [e for e in eventos_filtrados if e['local'] == filtro_bairro]

    if filtro_estilo:
        eventos_filtrados = [e for e in eventos_filtrados if e['categoria'] == filtro_estilo]

    if busca:
        eventos_filtrados = [e for e in eventos_filtrados if busca in e['titulo'].lower() or busca in e['endereco'].lower()]
        
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
    
    return eventos_filtrados

@app.route('/')
def mostrar_eventos():
    eventos_todos = fetch_carnival_data()
    eventos_filtrados = filtrar_eventos(eventos_todos, request.args)

    bairros = sorted(list(set([e['local'] for e in eventos_todos if e['local']])))
    estilos = sorted(list(set([e['categoria'] for e in eventos_todos if e['categoria']])))

    return render_template('index.html', 
                           eventos=eventos_filtrados,
                           bairros=bairros,
                           estilos=estilos,
                           total=len(eventos_filtrados),
                           google_maps_api_key=GOOGLE_MAPS_API_KEY)

@app.route('/api/eventos')
def api_eventos():
    eventos_todos = fetch_carnival_data()
    eventos_filtrados = filtrar_eventos(eventos_todos, request.args)
    geocoded = [e for e in eventos_filtrados if e['lat'] and e['lon']]
    for e in geocoded:
        if '_dt_obj' in e: del e['_dt_obj']
    return jsonify(geocoded)

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

if __name__ == '__main__':
    app.run(debug=True, port=5000)