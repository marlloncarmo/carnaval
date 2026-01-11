import os
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")

supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Erro Supabase: {e}")

def get_all_likes():
    """Retorna contagem total para o cache"""
    if not supabase: return {}
    try:
        response = supabase.table('likes').select('id, count').execute()
        return {item['id']: item['count'] for item in response.data}
    except: return {}

def update_like(bloco_id, user_id, ip_address, action='add'):
    """
    Controla o Like com regras rígidas:
    1. Unicidade de UUID (Database constraint)
    2. Limite de 20 votos por IP neste bloco (Lógica Python)
    """
    if not supabase: return False

    try:
        if action == 'add':
            # --- REGRA DO IP ---
            # Verifica quantos votos este IP já deu NESTE bloco específico
            # Se quiser limitar 20 votos no site todo, tire o .eq('bloco_id', bloco_id)
            check_ip = supabase.table('votos') \
                .select('*', count='exact') \
                .eq('ip_address', ip_address) \
                .eq('bloco_id', bloco_id) \
                .execute()
            
            # Se já tem 20 ou mais, rejeita silenciosamente
            if check_ip.count >= 20:
                print(f"[Anti-Spam] IP {ip_address} atingiu limite para bloco {bloco_id}")
                return False 

            # --- INSERÇÃO ---
            # Tenta inserir. Se o user_id já votou, o banco lança erro (Unique Violation)
            supabase.table('votos').insert({
                'user_id': user_id, 
                'bloco_id': bloco_id,
                'ip_address': ip_address
            }).execute()
            
        elif action == 'remove':
            # Remove o voto daquele UUID
            supabase.table('votos').delete().match({
                'user_id': user_id, 
                'bloco_id': bloco_id
            }).execute()
            
        return True
    except Exception as e:
        # Erros normais (duplicidade de UUID) são ignorados
        # print(f"Log Database: {e}")
        return False