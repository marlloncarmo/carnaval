from flask import Flask, render_template, request, jsonify, send_from_directory, make_response, url_for
import os
import json
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
import database

app = Flask(__name__)
app.secret_key = 'carnaval_secret_key'

load_dotenv()

@app.context_processor
def inject_ga():
    return dict(ga_measurement_id=os.environ.get("GA_MEASUREMENT_ID"))

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

CACHE_TIMEOUT = 300 
DATA_CACHE = {
    'eventos': [],
    'estilos': [],
    'last_update': 0
}

def dated_url_for(endpoint, **values):
    if endpoint == 'static':
        filename = values.get('filename', None)
        if filename:
            file_path = os.path.join(app.root_path, endpoint, filename)
            try:
                values['q'] = int(os.path.getmtime(file_path))
            except OSError: pass
    return url_for(endpoint, **values)

@app.context_processor
def override_url_for():
    return dict(url_for=dated_url_for)

def get_brasilia_time():
    utc_now = datetime.utcnow()
    return utc_now - timedelta(hours=3)

def events_status_logic(eventos_raw):
    eventos = [e.copy() for e in eventos_raw]
    now = get_brasilia_time()
    
    for e in eventos:
        if not e.get('_dt_obj'): 
            e['status'] = 'futuro'; e['status_label'] = ''; e['sort_weight'] = 3
            continue
            
        dt = e['_dt_obj']
        diff = (dt - now).total_seconds() / 3600
        
        if 0 < diff <= 2:
            e['status'] = 'em-breve'; e['status_label'] = 'Em Breve'; e['sort_weight'] = 0
        elif -3 <= diff <= 0:
            e['status'] = 'em-andamento'; e['status_label'] = 'Em Andamento'; e['sort_weight'] = 0
        elif -5 <= diff < -3:
            e['status'] = 'encerrando'; e['status_label'] = 'Encerrando'; e['sort_weight'] = 1
        elif diff < -5:
            e['status'] = 'encerrado'; e['status_label'] = 'Encerrado'; e['sort_weight'] = 4
        elif dt.date() == now.date():
            e['status'] = 'hoje'; e['status_label'] = 'Hoje'; e['sort_weight'] = 2
        else:
            e['status'] = 'futuro'; e['status_label'] = ''; e['sort_weight'] = 3
            
    eventos.sort(key=lambda x: (x['sort_weight'], x['_dt_obj'] if x['_dt_obj'] else datetime.max))
    return eventos

def load_raw_data_cached():
    global DATA_CACHE
    now_ts = time.time()

    if DATA_CACHE['eventos'] and (now_ts - DATA_CACHE['last_update'] < CACHE_TIMEOUT):
        return DATA_CACHE['eventos'], DATA_CACHE['estilos']

    todos_eventos = []
    estilos_set = set()

    if os.path.exists('eventos.json'):
        try:
            with open('eventos.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                todos_eventos.extend(data.get('eventos', []))
                for est in data.get('estilos', []): estilos_set.add(est)
        except: pass

    if os.path.exists('ensaios.json'):
        try:
            with open('ensaios.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                todos_eventos.extend(data.get('eventos', []))
        except: pass

    for e in todos_eventos:
        if e.get('dt_iso'): e['_dt_obj'] = datetime.fromisoformat(e['dt_iso'])
        else: e['_dt_obj'] = None

    try:
        likes_map = database.get_all_likes()
        for e in todos_eventos:
            eid = e['id']
            e['likes'] = likes_map.get(eid, 0)
    except: pass 

    DATA_CACHE['eventos'] = todos_eventos
    DATA_CACHE['estilos'] = sorted(list(estilos_set))
    DATA_CACHE['last_update'] = now_ts
    return DATA_CACHE['eventos'], DATA_CACHE['estilos']

def fetch_carnival_data():
    eventos_raw, estilos = load_raw_data_cached()
    return events_status_logic(eventos_raw), estilos

def filtrar_eventos(eventos_todos, args):
    has_active_filters = False
    filtro_data = args.get('data_filtro')
    filtro_bairro = args.get('bairro')
    filtro_estilo = args.get('categoria')
    quick_filters = args.getlist('quick_filter') 
    busca = args.get('q', '').lower()
    ne_lat = args.get('ne_lat')
    
    if filtro_data or filtro_bairro or filtro_estilo or quick_filters or busca or ne_lat: has_active_filters = True
    eventos_filtrados = eventos_todos
    now = get_brasilia_time()

    if quick_filters:
        target_dates = []
        target_sizes = []
        target_periods = []
        if 'sab_oficial' in quick_filters: target_dates.append(datetime(2026, 2, 14).date())
        if 'dom_oficial' in quick_filters: target_dates.append(datetime(2026, 2, 15).date())
        if 'seg_oficial' in quick_filters: target_dates.append(datetime(2026, 2, 16).date())
        if 'ter_oficial' in quick_filters: target_dates.append(datetime(2026, 2, 17).date())
        if 'hoje' in quick_filters: target_dates.append(now.date())
        if 'amanha' in quick_filters: target_dates.append(now.date() + timedelta(days=1))
        
        target_statuses = [s for s in ['em-andamento', 'em-breve', 'encerrando'] if s in quick_filters]
        if 'grande' in quick_filters: target_sizes.append(3)
        if 'medio' in quick_filters: target_sizes.append(2)
        if 'pequeno' in quick_filters: target_sizes.append(1)
        if 'manha' in quick_filters: target_periods.append('manha')
        if 'tarde' in quick_filters: target_periods.append('tarde')
        if 'noite' in quick_filters: target_periods.append('noite')
        
        if target_dates: eventos_filtrados = [e for e in eventos_filtrados if e['_dt_obj'] and e['_dt_obj'].date() in target_dates]
        if target_statuses: eventos_filtrados = [e for e in eventos_filtrados if e['status'] in target_statuses]
        if target_sizes: eventos_filtrados = [e for e in eventos_filtrados if e['tamanho'] in target_sizes]
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

    if filtro_bairro: eventos_filtrados = [e for e in eventos_filtrados if e['local'] == filtro_bairro]
    if filtro_estilo: eventos_filtrados = [e for e in eventos_filtrados if filtro_estilo.lower() in e['categoria'].lower()]
    if busca: eventos_filtrados = [e for e in eventos_filtrados if busca in e['titulo'].lower() or busca in e['endereco'].lower()]
        
    ne_lng = args.get('ne_lng')
    sw_lat = args.get('sw_lat')
    sw_lng = args.get('sw_lng')

    if ne_lat and ne_lng and sw_lat and sw_lng:
        try:
            n_lat = float(ne_lat); n_lng = float(ne_lng); s_lat = float(sw_lat); s_lng = float(sw_lng)
            eventos_filtrados = [e for e in eventos_filtrados if e['lat'] and e['lon'] and s_lat <= e['lat'] <= n_lat and s_lng <= e['lon'] <= n_lng]
        except ValueError: pass
    
    return eventos_filtrados, has_active_filters

@app.route('/')
def mostrar_eventos():
    eventos_todos, estilos = fetch_carnival_data()
    eventos_filtrados, has_filters = filtrar_eventos(eventos_todos, request.args)
    bairros = sorted(list(set([e['local'] for e in eventos_todos if e['local']])))
    total_ativos = len([e for e in eventos_filtrados if e.get('status') != 'encerrado'])

    response = make_response(render_template('index.html', 
                           eventos=eventos_filtrados, bairros=bairros, estilos=estilos,
                           total=total_ativos, has_filters=has_filters,
                           google_maps_api_key=GOOGLE_MAPS_API_KEY))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@app.route('/api/eventos')
def api_eventos():
    eventos_todos, _ = fetch_carnival_data()
    eventos_filtrados, _ = filtrar_eventos(eventos_todos, request.args)
    geocoded = [e for e in eventos_filtrados if e['lat'] and e['lon']]
    for e in geocoded: 
        if '_dt_obj' in e: del e['_dt_obj']
    return jsonify(geocoded)

@app.route('/api/like/<id>', methods=['POST'])
def api_like(id):
    try:
        payload = request.json or {}
        acao = payload.get('acao', 'add')
        user_id = payload.get('user_id')

        # Captura o IP real (considerando proxies como Vercel/Cloudflare)
        if request.headers.getlist("X-Forwarded-For"):
            ip_address = request.headers.getlist("X-Forwarded-For")[0]
        else:
            ip_address = request.remote_addr

        if not user_id:
            return jsonify({'status': 'error', 'msg': 'UUID missing'}), 400

        # Chama o DB com todas as informações
        if database.update_like(id, user_id, ip_address, acao):
            return jsonify({'status': 'ok'}), 200
        else:
            # Retorna OK mesmo se falhar (ignorado) para não alertar o spammer
            return jsonify({'status': 'ignored'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)}), 500

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

if __name__ == '__main__':
    app.run(debug=True, port=5000)