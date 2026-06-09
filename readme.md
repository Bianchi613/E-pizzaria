# README.md

## E-Pizza 🍕

Sistema de atendimento inteligente para pizzarias utilizando:

* WhatsApp via Evolution API
* IA (Ollama, OpenAI ou Grok)
* PostgreSQL
* Memória persistente em JSON

---

## Como funciona

O cliente envia uma mensagem pelo WhatsApp.

Exemplo:

```text
Oi
```

O sistema recebe a mensagem através da Evolution API e identifica o cliente pelo número do telefone.

Fluxo:

```text
WhatsApp
    ↓
Evolution API
    ↓
Webhook Python
    ↓
PostgreSQL
    ↓
IA
    ↓
Resposta ao Cliente
```

---

# Identificação do Cliente

O principal identificador do cliente é o telefone.

Exemplo:

```text
+55 21 99999-9999
```

Ao receber uma mensagem, o sistema consulta:

```sql
SELECT
    id,
    nome,
    telefone,
    endereco
FROM clientes
WHERE telefone = ?
```

---

## Cliente Encontrado

Se o telefone existir:

```text
Olá Alan 🍕

Encontrei seu cadastro.

Endereço:
Rua das Flores 123

Deseja fazer um novo pedido?
```

O sistema carrega automaticamente:

* Nome
* Telefone
* Endereço
* Histórico de pedidos

---

## Cliente Não Encontrado

Caso o telefone não exista:

```text
Olá!

Ainda não encontrei seu cadastro.

Qual é o seu nome?
```

Depois:

```text
Qual é o endereço para entrega?
```

Após obter os dados:

```sql
INSERT INTO clientes
```

---

# Estrutura do Banco

## clientes

```sql
CREATE TABLE clientes (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100),
    telefone VARCHAR(30) UNIQUE,
    endereco TEXT,
    criado_em TIMESTAMP DEFAULT NOW()
);
```

## pedidos

```sql
CREATE TABLE pedidos (
    id SERIAL PRIMARY KEY,

    cliente_id INTEGER
    REFERENCES clientes(id),

    pedido_json JSONB,

    status VARCHAR(30),

    criado_em TIMESTAMP DEFAULT NOW()
);
```

---

# Memória

Arquivo:

```text
prompts/memoria.json
```

Exemplo:

```json
{
  "cliente": {
    "id": 1,
    "nome": "Alan",
    "telefone": "5521999999999",
    "endereco": "Rua das Flores 123"
  },

  "pedido_atual": {
    "quantidade": 1,
    "tamanho": "grande",
    "sabores": [
      "calabresa",
      "portuguesa"
    ],
    "bebidas": [
      "coca 2l"
    ],
    "pagamento": ""
  },

  "historico_conversa": []
}
```

---

# Configuração da Pizzaria

Arquivo:

```text
prompts/pizzaria.json
```

Exemplo:

```json
{
  "nome": "E-Pizza",

  "system_prompt": "Você é uma atendente virtual de pizzaria.",

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

# Processo de Pedido

A IA deve descobrir:

* Quantidade
* Tamanho
* Sabores
* Meio a meio
* Borda
* Bebidas
* Endereço
* Pagamento

Exemplo:

```text
Cliente:
Quero uma pizza.

IA:
Qual tamanho?

Cliente:
Grande.

IA:
Qual sabor?

Cliente:
Meio calabresa e meio portuguesa.

IA:
Deseja bebida?
```

---

# Finalização

Quando todas as informações estiverem preenchidas:

```text
🍕 PEDIDO

1 Pizza Grande

• Meio Calabresa
• Meio Portuguesa

🥤 Coca-Cola 2L

📍 Rua das Flores 123

💳 PIX

Confirma o pedido?
```

Após confirmação:

```sql
INSERT INTO pedidos
```

---

# Variáveis .env

```env
DB_HOST=localhost
DB_NAME=pizzaria
DB_USER=postgres
DB_PASSWORD=123456

LLM_PROVIDER=ollama

OLLAMA_MODEL=llama3.1:8b
OLLAMA_URL=http://localhost:11434

OPENAI_API_KEY=

XAI_API_KEY=
```
#Estrutura:
pizzaria/

├── app.py
├── llm_api.py
├── llm_ollama.py
├── evolution.py
│
├── prompts/
│   ├── pizzaria.json
│   └── memoria.json
│
├── logs/
│
└── .env
---

# Objetivo

Automatizar completamente o atendimento da pizzaria pelo WhatsApp, utilizando o telefone como identificador principal do cliente, mantendo histórico de pedidos, cadastro e memória da conversa. 🍕🤖📱
