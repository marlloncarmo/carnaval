import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
# Use a SERVICE_ROLE_KEY aqui para ter permissão de alterar tabelas
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") 

if not URL or not KEY:
    print("ERRO: Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no .env")
    exit()

print("Copie e rode o SQL abaixo no 'SQL Editor' do Supabase:")
print("-" * 50)
print("""
-- 1. Tabela de Votos (Segura e Auditável)
CREATE TABLE IF NOT EXISTS votos (
  user_id UUID NOT NULL,
  bloco_id TEXT NOT NULL,
  ip_address TEXT,  -- Nova coluna para controle de spam
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
  PRIMARY KEY (user_id, bloco_id) -- Garante 1 voto por UUID
);

-- 2. Tabela de Contagem Rápida (Cache)
CREATE TABLE IF NOT EXISTS likes (
  id TEXT PRIMARY KEY,
  count INTEGER DEFAULT 0
);

-- 3. Habilitar Segurança (RLS)
ALTER TABLE votos ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public Insert" ON votos FOR INSERT WITH CHECK (true);
CREATE POLICY "Public Delete" ON votos FOR DELETE USING (true);
CREATE POLICY "Public Read" ON votos FOR SELECT USING (true);

-- 4. Gatilho (Trigger) para atualizar a contagem automaticamente
CREATE OR REPLACE FUNCTION atualizar_contador() RETURNS TRIGGER AS $$
BEGIN
  IF (TG_OP = 'INSERT') THEN
    INSERT INTO likes (id, count) VALUES (NEW.bloco_id, 1)
    ON CONFLICT (id) DO UPDATE SET count = likes.count + 1;
    RETURN NEW;
  ELSIF (TG_OP = 'DELETE') THEN
    UPDATE likes SET count = GREATEST(0, likes.count - 1) WHERE id = OLD.bloco_id;
    RETURN OLD;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_contar_voto ON votos;
CREATE TRIGGER trigger_contar_voto
AFTER INSERT OR DELETE ON votos
FOR EACH ROW EXECUTE FUNCTION atualizar_contador();
""")
print("-" * 50)