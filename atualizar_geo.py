import os
import json
import requests
import csv
import io
import time
from dotenv import load_dotenv

# Carrega variáveis de ambiente (.env) para pegar a API KEY
load_dotenv()

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1s_Vm7BCW1ZYtCf79CKZ7clFdeRvEzqNbCQOhq6ZeG_U/export?format=csv&gid=1903941151"
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
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=4)

def get_google_coords(address, neighborhood):
    if not GOOGLE_MAPS_API_KEY:
        print("ERRO: GOOGLE_MAPS_API_KEY não encontrada no .env")
        return None, None

    search_query = f"{address}, {neighborhood}, Belo Horizonte, MG" if address else f"{neighborhood}, Belo Horizonte, MG"
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={search_query}&key={GOOGLE_MAPS_API_KEY}"
    
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            return location['lat'], location['lng']
        else:
            print(f"API retornou status: {data['status']} para '{search_query}'")
    except Exception as e:
        print(f"Erro na requisição: {e}")
    
    return None, None

def main():
    print(">>> Iniciando atualização de Geocoding...")
    
    cache = load_cache()
    alteracoes = 0
    
    print(">>> Baixando planilha...")
    response = requests.get(SHEET_CSV_URL)
    response.encoding = 'utf-8'
    csv_file = io.StringIO(response.text)
    reader = csv.DictReader(csv_file)
    
    for row in reader:
        bairro = row.get("Bairro", "").strip()
        endereco = row.get("LOCAL DA CONCENTRAÇÃO", "").strip()
        nome = row.get("NOME DO BLOCO", "Bloco").strip()
        
        key = f"{endereco} - {bairro}".strip()
        
        if not key:
            continue

        # Se NÃO estiver no cache, buscamos na API
        if key not in cache:
            print(f"Nova localização encontrada: {nome} ({key})")
            lat, lon = get_google_coords(endereco, bairro)
            
            if lat and lon:
                cache[key] = {'lat': lat, 'lon': lon}
                alteracoes += 1
                print(f"   -> Sucesso: {lat}, {lon}")
                # Salva a cada sucesso para não perder dados se der crash
                save_cache(cache) 
                # Importante: Pausa curta para não estourar limite de taxa da API (opcional mas boa prática)
                time.sleep(0.2) 
            else:
                print("   -> Falha ao obter coordenadas.")
    
    if alteracoes > 0:
        print(f"\n>>> Processo finalizado! {alteracoes} novos endereços adicionados ao 'latlon_cache.json'.")
    else:
        print("\n>>> Processo finalizado! Nenhuma nova localização necessária.")

if __name__ == "__main__":
    main()