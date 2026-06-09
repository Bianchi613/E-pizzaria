-- =========================================
-- E-Pizza :: Esquema do banco
-- Banco alvo: evolution (mesmo Postgres usado pela Evolution API)
-- Aplicar:
--   psql -h localhost -U postgres -d evolution -f schema.sql
-- =========================================

-- Cadastro fixo dos clientes. O telefone (somente dígitos) é a chave
-- de reconhecimento usada pelo webhook.
CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100),
    telefone VARCHAR(30) UNIQUE NOT NULL,
    endereco TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

-- Pedidos finalizados, com o conteúdo flexível em JSONB.
CREATE TABLE IF NOT EXISTS pedidos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
    pedido_json JSONB NOT NULL,
    status VARCHAR(30) DEFAULT 'recebido',
    criado_em TIMESTAMP DEFAULT NOW()
);

-- Acelera a busca dos últimos pedidos por cliente.
CREATE INDEX IF NOT EXISTS idx_pedidos_cliente_id ON pedidos (cliente_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_criado_em ON pedidos (criado_em DESC);
