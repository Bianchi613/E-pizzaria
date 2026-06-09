# 🍕 E-Pizza

> Sistema de atendimento automatizado e inteligente para pizzarias integrado ao WhatsApp via IA.

O **E-Pizza** automatiza o fluxo de atendimento de uma pizzaria através do WhatsApp. O sistema usa o **número de telefone do cliente como identificador principal** para reconhecer o cadastro no banco de dados, manter o contexto da conversa por número e conduzir o pedido — do primeiro "oi" até a confirmação e gravação no banco — usando Inteligência Artificial.

---

## 🛠️ Tecnologias Utilizadas

* **Backend / Integração:** Python (Flask)
* **Mensageria:** WhatsApp via [Evolution API](https://github.com/EvolutionAPI/evolution-api)
* **Orquestração de IA:** Ollama (Local), OpenAI API ou xAI (Grok)
* **Banco de Dados:** PostgreSQL (persistência de clientes e pedidos)
* **Gerenciamento de Contexto:** Memória por telefone em JSON + saída estruturada da IA

---

## 🔄 Como Funciona (Fluxo de Atendimento)

```text
       [ Cliente no WhatsApp ]
                  │
                  ▼
         [ Evolution API ]
                  │ (Webhook: messages.upsert)
                  ▼
     [ Webhook Flask / evolution.py ]
          dedupe por key.id
                  │
                  ▼
   [ processar_mensagem() / app.py ]
                  │
        ┌─────────┴───────────────┐
        ▼                         ▼
 [ PostgreSQL ]          [ Memória por telefone ]
 reconhece pelo nº       prompts/memorias/<tel>.json
 últimos pedidos         histórico + pedido_atual
        │                         │
        └────────────┬────────────┘
                     ▼
              [ Camada de IA ]
          (Ollama / OpenAI / xAI)
                     │
        texto visível + bloco <<<DADOS>>>
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
 [ Resposta ao cliente ]   [ Persistência no banco ]
 (bloco removido)          cadastra cliente / salva pedido
```

### 📱 Experiência do Usuário

1. **Identificação primária:** o webhook captura o número (normalizado para apenas dígitos, ex.: `5521999999999`), independente da formatação recebida.
2. **Reconhecimento pelo banco:** a consulta é feita pela coluna `telefone` na tabela `clientes`, **mesmo que a memória local não exista**.
   * **Cliente cadastrado:** a IA recebe nome, endereço e os últimos pedidos, e saúda de forma personalizada — *"Olá Alan 🍕! Deseja repetir seu último pedido?"*
   * **Novo cliente:** a IA faz um onboarding amigável, coletando nome e endereço naturalmente ao longo da conversa. Assim que ambos são informados, o cadastro é **gravado automaticamente** no banco.

---

## 🐛 Correções e melhorias recentes

| Problema | Causa | Correção |
|---|---|---|
| IA com amnésia entre mensagens | Webhook enviava só a mensagem crua ao LLM, sem histórico | `processar_mensagem` monta o prompt com histórico real por telefone |
| Resposta duplicada (2x por mensagem) | Evolution dispara o webhook várias vezes para o mesmo evento (status READ/SERVER_ACK) | Deduplicação por `key.id` no webhook |
| Cliente não reconhecido | Webhook nunca consultava o banco; telefone com formatação variável | Reconhecimento por número normalizado direto no Postgres |
| Cliente novo não era cadastrado | Nenhum código extraía nome/endereço da conversa | Saída estruturada `<<<DADOS>>>` + cadastro automático |
| Pedido finalizado sem confirmar | Não havia etapa de confirmação obrigatória | Resumo completo + status `aguardando_confirmacao` → `confirmado` + trava de pedido completo |

---

## 🗄️ Estrutura do Banco de Dados (PostgreSQL)

As tabelas ficam no banco **`evolution`** (o mesmo Postgres usado pela Evolution API). O esquema está versionado em [`schema.sql`](schema.sql):

```sql
-- Tabela de Clientes (telefone = chave de reconhecimento, apenas dígitos)
CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100),
    telefone VARCHAR(30) UNIQUE NOT NULL,
    endereco TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

-- Tabela de Pedidos (conteúdo flexível em JSONB)
CREATE TABLE IF NOT EXISTS pedidos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
    pedido_json JSONB NOT NULL,
    status VARCHAR(30) DEFAULT 'recebido',
    criado_em TIMESTAMP DEFAULT NOW()
);
```

Aplicar o esquema:

```bash
psql -h localhost -U postgres -d evolution -f schema.sql
```

---

## 🧠 Arquitetura de Prompts e Memória

### 1. Memória por telefone (`prompts/memorias/<telefone>.json`)

Cada cliente tem seu próprio arquivo de estado (criado automaticamente), evitando que conversas se misturem. Guarda o cadastro, o carrinho em andamento e o histórico recente para evitar amnésia da IA.

```json
{
  "cliente": {
    "id": 1,
    "nome": "Alan",
    "telefone": "5521999999999",
    "endereco": "Rua das Flores, 123"
  },
  "pedido_atual": {
    "quantidade": 1,
    "tamanho": "grande",
    "sabores": ["calabresa", "portuguesa"],
    "meio_a_meio": true,
    "borda": "",
    "bebidas": ["coca 2l"],
    "pagamento": ""
  },
  "historico_pedidos": [],
  "historico_conversa": [
    { "role": "user", "content": "quero uma pizza" },
    { "role": "assistant", "content": "Claro! Qual tamanho? 🍕" }
  ]
}
```

### 2. Regras de Negócio e Cardápio (`prompts/pizzaria.json`)

Define a persona, o cardápio e os procedimentos operacionais — incluindo `procedimento_cadastro` (onboarding de cliente novo), `procedimento_confirmacao` (confirmação obrigatória) e o `modelo_resumo`.

---

## 🤝 Saída Estruturada da IA

A IA responde em **texto livre + um bloco técnico JSON** ao final, entre marcas `<<<DADOS>>>`. O código lê esse bloco para preencher a memória e gravar no banco, e **remove o bloco antes de enviar a mensagem ao cliente**.

```text
Perfeito, Alan! Seu pedido está confirmado 🍕

<<<DADOS>>>
{"cliente": {"nome": "Alan", "endereco": "Rua das Flores, 123"},
 "pedido": {"quantidade": 1, "tamanho": "grande", "sabores": ["4 queijos"],
            "meio_a_meio": false, "borda": "", "bebidas": ["coca 2l"], "pagamento": "pix"},
 "status": "confirmado"}
<<<DADOS>>>
```

---

## 📝 Processo de Compra, Confirmação e Fechamento

A IA preenche os slots necessários para um pedido válido:

* Quantidade e tamanho
* Sabores (com suporte a meio a meio)
* Borda e bebidas
* Endereço de entrega e forma de pagamento

### ✅ Confirmação obrigatória antes de finalizar

O pedido **só é gravado** após o cliente confirmar. O campo `status` percorre três estados:

| `status` | Significado | Grava no banco? |
|---|---|---|
| `em_andamento` | Ainda coletando dados | ❌ |
| `aguardando_confirmacao` | Resumo completo apresentado, aguardando o "sim" | ❌ |
| `confirmado` | Cliente confirmou explicitamente | ✅ (se o pedido estiver completo) |

Há ainda uma **trava no código** (`pedido_completo`): mesmo com `status=confirmado`, o pedido só é salvo se tiver tamanho, sabores e pagamento. Antes de finalizar, a IA exibe o resumo:

```text
🍕 *RESUMO DO PEDIDO - E-PIZZA*
1x Pizza Grande
• Meio Calabresa
• Meio Portuguesa

🥤 Bebida: Coca-Cola 2L
📍 Entrega: Rua das Flores, 123
💳 Pagamento: PIX

*Confirma o pedido acima?*
```

---

## 📂 Estrutura do Projeto

```text
E-Pizzaria/
├── app.py             # Lógica de atendimento: memória, banco, IA, persistência
├── evolution.py       # Webhook Flask + envio de mensagens (Evolution API)
├── llm_api.py         # Conector para provedores Cloud (OpenAI / xAI)
├── llm_ollama.py      # Conector para processamento local (Ollama)
├── schema.sql         # Esquema das tabelas (clientes, pedidos)
├── prompts/
│   ├── pizzaria.json  # Persona, cardápio e procedimentos
│   └── memorias/      # Estado por telefone (<telefone>.json) — gerado em runtime
├── logs/              # Registro de logs operacionais
├── .gitignore         # Arquivos ignorados (ex.: .env)
└── .env               # Variáveis de ambiente secretas
```

### Principais funções (`app.py`)

* `processar_mensagem(telefone, mensagem, push_name)` — orquestra reconhecimento, IA, memória e persistência.
* `normalizar_telefone` / `buscar_cliente` / `buscar_ultimos_pedidos` — reconhecimento pelo número.
* `cadastrar_cliente` / `salvar_pedido` — gravação no banco.
* `extrair_dados_estruturados` / `aplicar_dados` / `persistir` — leitura do bloco `<<<DADOS>>>` e atualização de memória/banco.
* `pedido_completo` — trava contra finalização prematura.

---

## ⚙️ Configuração do Ambiente (`.env`)

```env
# =============== BANCO DE DADOS ===============
# As tabelas ficam no banco "evolution" (mesmo Postgres da Evolution API)
DB_HOST=localhost
DB_NAME=evolution
DB_USER=postgres
DB_PASSWORD=sua_senha_aqui

# =============== PROVEDOR DE IA ===============
# Opções: ollama | api  (api cobre OpenAI, xAI e compatíveis com /v1/chat/completions)
LLM_PROVIDER=api

# --- Ollama (local) ---
OLLAMA_MODEL=llama3.1:8b
OLLAMA_URL=http://localhost:11434

# --- API Cloud (OpenAI / xAI / OpenRouter...) ---
CHAT_API_KEY=sua_chave_aqui
CHAT_API_BASE_URL=https://api.x.ai/v1
CHAT_API_MODEL=grok-4-fast

# =============== EVOLUTION API ===============
EVOLUTION_URL=http://localhost:8080
EVOLUTION_INSTANCE=pizzaria2
EVOLUTION_API_KEY=sua_apikey_evolution

# Em produção, ignore mensagens enviadas pelo próprio número (evita loop).
# Durante testes com o próprio WhatsApp, deixe false.
IGNORE_FROM_ME=true
```

---

## ▶️ Como Rodar

```bash
# 1. Instale as dependências
pip install flask requests psycopg2-binary python-dotenv ollama

# 2. Crie as tabelas no Postgres
psql -h localhost -U postgres -d evolution -f schema.sql

# 3. Suba o webhook (porta 5000)
python evolution.py

# (opcional) Teste a lógica de atendimento via terminal, sem WhatsApp:
python app.py
```

Aponte o webhook da sua instância na Evolution API para `http://SEU_IP:5000/webhook/messages-upsert`.
