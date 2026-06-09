

```markdown
# 🍕 E-Pizza

> Sistema de atendimento automatizado e inteligente para pizzarias integrado ao WhatsApp via IA.

O **E-Pizza** automatiza completamente o fluxo de atendimento de uma pizzaria através do WhatsApp. O sistema utiliza o número de telefone do cliente como identificador principal para gerenciar cadastros, consultar históricos no banco de dados e manter a persistência do contexto da conversa utilizando Inteligência Artificial.

---

## 🛠️ Tecnologias Utilizadas

* **Backend / Integração:** Python
* **Mensageria:** WhatsApp via [Evolution API](https://github.com/EvolutionAPI/evolution-api)
* **Orquestração de IA:** Ollama (Local), OpenAI API ou xAI (Grok)
* **Banco de Dados:** PostgreSQL (Persistência de clientes e pedidos)
* **Gerenciamento de Contexto:** Memória híbrida estruturada em JSON

---

## 🔄 Como Funciona (Fluxo de Atendimento)

```text
       [ Cliente no WhatsApp ]
                  │
                  ▼
         [ Evolution API ]
                  │ (Webhook)
                  ▼
        [ Webhook Python / App ]
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
 [ PostgreSQL ]      [ Memória JSON ]
(Dados & Histórico)  (Estado do Pedido)
        │                   │
        └─────────┬─────────┘
                  ▼
         [ Camada de IA ]
     (Ollama / OpenAI / xAI)
                  │
                  ▼
     [ Resposta Automatizada ]

```

### 📱 Experiência do Usuário

1. **Identificação Primária:** O sistema intercepta o webhook da Evolution API e captura o número do telefone (ex: `+5521999999999`).
2. **Consulta de Cadastro:**
* **Cliente Cadastrado:** A IA recebe o contexto do cliente (Nome, Endereço e Últimos Pedidos) e faz uma saudação personalizada: *"Olá Alan 🍕! Vi aqui que seu último endereço foi... Deseja repetir o pedido?"*
* **Novo Cliente:** A IA inicia o fluxo de onboarding amigável perguntando o nome e o endereço de entrega, salvando os dados no banco ao final.



---

## 🗄️ Estrutura do Banco de Dados (PostgreSQL)

O banco armazena o cadastro fixo dos clientes e centraliza os pedidos finalizados em um campo flexível `JSONB` para suportar diferentes estruturas de itens.

```sql
-- Tabela de Clientes
CREATE TABLE clientes (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100),
    telefone VARCHAR(30) UNIQUE NOT NULL,
    endereco TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);

-- Tabela de Pedidos
CREATE TABLE pedidos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
    pedido_json JSONB NOT NULL,
    status VARCHAR(30) DEFAULT 'recebido',
    criado_em TIMESTAMP DEFAULT NOW()
);

```

---

## 🧠 Arquitetura de Prompts e Memória

O sistema trabalha com arquivos JSON locais para alimentar o contexto do modelo de linguagem (LLM) em tempo real.

### 1. Estado da Conversa Atual (`prompts/memoria.json`)

Mantém o estado da sessão ativa do cliente, o progresso do carrinho de compras e o histórico recente para evitar amnésia da IA entre as mensagens.

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
    "bebidas": ["coca 2l"],
    "pagamento": ""
  },
  "historico_conversa": []
}

```

### 2. Regras de Negócio e Cardápio (`prompts/pizzaria.json`)

Define o comportamento da persona e os parâmetros operacionais da pizzaria.

```json
{
  "nome": "E-Pizza",
  "system_prompt": "Você é uma atendente virtual prestativa e simpática da pizzaria E-Pizza. Seu objetivo é guiar o cliente de forma rápida e cordial para fechar o pedido, garantindo que todas as informações necessárias sejam coletadas de forma natural.",
  "sabores": [
    "calabresa",
    "portuguesa",
    "frango catupiry",
    "4 queijos"
  ],
  "bebidas": [
    "coca 2l",
    "guarana 2l"
  ]
}

```

---

## 📝 Processo de Compra e Fechamento

A IA atua como um agente conversacional encarregado de preencher os slots necessários para um pedido válido:

* Quantidade e Tamanho
* Sabores (com suporte a meio a meio)
* Adição de borda ou bebidas
* Confirmação de endereço e definição da forma de pagamento

Ao preencher todos os requisitos, a IA monta e exibe o resumo estruturado para validação do cliente antes de persistir no banco de dados:

```text
🍕 *RESUMO DO PEDIDO - E-PIZZA* 1x Pizza Grande
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
pizzaria/
├── app.py             # Ponto de entrada do Webhook e rotas principais
├── evolution.py       # Integração e envio de mensagens via Evolution API
├── llm_api.py         # Conector para provedores Cloud (OpenAI / xAI)
├── llm_ollama.py      # Conector para processamento local (Ollama)
├── prompts/
│   ├── pizzaria.json  # Configurações do sistema e cardápio
│   └── memoria.json   # Cache do estado atual do atendimento
├── logs/              # Registro de logs operacionais
├── .gitignore         # Arquivos ignorados no repositório (ex: .env)
└── .env               # Variáveis de ambiente secretas

```

---

## ⚙️ Configuração do Ambiente (`.env`)

Crie um arquivo `.env` na raiz do projeto com base na estrutura abaixo:

```env
# Configurações do Banco de Dados
DB_HOST=localhost
DB_NAME=pizzaria
DB_USER=postgres
DB_PASSWORD=sua_senha_aqui

# Seleção do Provedor de IA (opções: ollama, openai, xai)
LLM_PROVIDER=ollama

# Configuração Ollama (Local)
OLLAMA_MODEL=llama3.1:8b
OLLAMA_URL=http://localhost:11434

# Credenciais de Nuvem (Se aplicável)
OPENAI_API_KEY=sua_chave_openai
XAI_API_KEY=sua_chave_grok

```

```
