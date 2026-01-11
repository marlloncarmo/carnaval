import os
import json
import requests
import csv
import io
import re
import time
from datetime import datetime
from dotenv import load_dotenv

# Imports para Retry (Tratamento de Erros de Rede)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Carrega variáveis de ambiente
load_dotenv()

# CONFIGURAÇÕES
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1s_Vm7BCW1ZYtCf79CKZ7clFdeRvEzqNbCQOhq6ZeG_U/export?format=csv&gid=1903941151"
CACHE_FILE = 'latlon_cache.json'
OUTPUT_FILE = 'eventos.json' 

# --- SESSÃO COM RETRY (ROBUSTEZ) ---
def get_retry_session(retries=3, backoff_factor=1, status_forcelist=(500, 502, 503, 504)):
    """Cria uma sessão Requests que tenta novamente em caso de falha."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# 1. FUNÇÕES DE CACHE E GEOCODING
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cache(cache_data):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=4)

def get_google_coords(address, neighborhood, cache, session):
    key = f"{address} - {neighborhood}".strip()
    
    if not key:
        return None, None, False

    # Se já está no cache, retorna
    if key in cache:
        return cache[key]['lat'], cache[key]['lon'], False

    # Se não tem API Key, não faz nada
    if not GOOGLE_MAPS_API_KEY:
        print(f"   [!] Sem API Key. Ignorando coordenadas para: {key}")
        return None, None, False

    # Busca na API
    search_query = f"{address}, {neighborhood}, Belo Horizonte, MG" if address else f"{neighborhood}, Belo Horizonte, MG"
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={search_query}&key={GOOGLE_MAPS_API_KEY}"
    
    try:
        print(f"   >>> Buscando na API: {key}...")
        # Usa a sessão com retry
        response = session.get(url, timeout=10) 
        data = response.json()
        
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            lat, lon = location['lat'], location['lng']
            cache[key] = {'lat': lat, 'lon': lon}
            return lat, lon, True
        elif data['status'] == 'OVER_QUERY_LIMIT':
            print("   [!] Cota de API excedida ou rate limit.")
            return None, None, False
        else:
            print(f"   [x] API retornou status: {data['status']}")
            
    except Exception as e:
        print(f"   [x] Erro Crítico API: {e}")
    
    return None, None, False

# 2. PROCESSAMENTO DE DADOS
def processar_dados():
    print(">>> 1. Iniciando Sessão Segura e Baixando planilha...")
    session = get_retry_session()

    try:
        response = session.get(SHEET_CSV_URL, timeout=15)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            print(f"   [x] Erro ao baixar planilha: Status {response.status_code}")
            return
    except Exception as e:
        print(f"   [x] Erro de conexão fatal: {e}")
        return

    csv_file = io.StringIO(response.text)
    reader = csv.DictReader(csv_file)
    
    cache_geo = load_cache()
    eventos_processados = []
    unique_styles = set()
    api_calls = 0
    dias_semana = {0: 'Seg', 1: 'Ter', 2: 'Qua', 3: 'Qui', 4: 'Sex', 5: 'Sáb', 6: 'Dom'}

    print(">>> 2. Processando linhas e Geocoding...")
    
    for row in reader:
        titulo = row.get("NOME DO BLOCO", "Bloco sem nome").strip()
        bairro = row.get("Bairro", "").strip()
        endereco = row.get("LOCAL DA CONCENTRAÇÃO", "").strip()
        
        # --- Tratamento de Categorias ---
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

        # --- Tratamento de Descrição e Tags ---
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

        clean_desc = re.sub(r'^\W+|\W+$', '', clean_desc).strip()
        
        # --- Tamanho ---
        tamanho_raw = row.get("TAMANHO", "").lower()
        tamanho_score = 1
        if "grande" in tamanho_raw: tamanho_score = 3
        elif "médio" in tamanho_raw or "medio" in tamanho_raw: tamanho_score = 2

        # --- Data e Hora ---
        data_raw = row.get("DATA", "")
        hora_raw = row.get("HORÁRIO DA CONCENTRAÇÃO", "")
        dt_iso = None 
        data_formatada = "A definir"
        
        if data_raw:
            try:
                data_clean = data_raw.split(' ')[0]
                if hora_raw:
                    dt_obj = datetime.strptime(f"{data_clean} {hora_raw}", '%d/%m/%Y %H:%M')
                    dia_sem = dias_semana[dt_obj.weekday()]
                    data_formatada = f"{dt_obj.strftime('%d/%m')} ({dia_sem}) - {dt_obj.strftime('%H:%M')}"
                    dt_iso = dt_obj.isoformat()
                else:
                    dt_obj = datetime.strptime(data_clean, '%d/%m/%Y')
                    dia_sem = dias_semana[dt_obj.weekday()]
                    data_formatada = f"{dt_obj.strftime('%d/%m')} ({dia_sem})"
                    dt_iso = dt_obj.isoformat()
            except:
                data_formatada = f"{data_raw} {hora_raw}"

        # --- GEOCODING (Passando a sessão segura) ---
        lat, lon, used_api = get_google_coords(endereco, bairro, cache_geo, session)
        
        if used_api:
            api_calls += 1
            save_cache(cache_geo) 
            time.sleep(0.2) 

        eventos_processados.append({
            "id": str(hash(titulo + data_formatada)),
            "titulo": titulo,
            "local": bairro,
            "endereco": endereco,
            "data": data_formatada,
            "dt_iso": dt_iso,
            "categoria": raw_categoria,
            "categoria_display": categoria_display,
            "descricao": clean_desc,
            "tamanho": tamanho_score,
            "lat": lat,
            "lon": lon,
            "is_kids": is_kids,
            "is_lgbt": is_lgbt,
            "is_pet": is_pet
        })

    # --- TRAVA DE SEGURANÇA (CRÍTICO) ---
    # Se a planilha veio vazia ou deu erro de parseamento, NÃO sobrescreva o JSON antigo.
    if len(eventos_processados) < 5:
        print(f"\n[!!!] ALERTA: Apenas {len(eventos_processados)} eventos encontrados.")
        print("[!!!] Abortando salvamento para proteger os dados existentes.")
        return

    estilos_finais = sorted(list(unique_styles))
    
    dados_finais = {
        "eventos": eventos_processados,
        "estilos": estilos_finais,
        "atualizado_em": datetime.now().isoformat()
    }
    
    print(f"\n>>> 3. Salvando arquivo final '{OUTPUT_FILE}'...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(dados_finais, f, ensure_ascii=False, indent=4)
        
    print(f"\n>>> SUCESSO! \n    - Blocos processados: {len(eventos_processados)}\n    - Chamadas API Google: {api_calls}")

if __name__ == "__main__":
    processar_dados()