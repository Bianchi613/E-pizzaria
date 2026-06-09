
import json
import os
import re

import psycopg2
from psycopg2.extras import Json

from dotenv import load_dotenv

load_dotenv()

PIZZARIA_PATH = "prompts/pizzaria.json"
MEMORY_DIR = "prompts/memorias"

# Quantas mensagens (user+assistant) manter no histórico enviado ao LLM
HISTORICO_JANELA = 20
# Quantas mensagens persistir em disco
HISTORICO_MAX = 40

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

LLM_PROVIDER = os.getenv(
    "LLM_PROVIDER",
    "ollama"
).lower()


def validate_config():

    required = [
        "DB_HOST",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD"
    ]

    missing = [
        item
        for item in required
        if not os.getenv(item)
    ]

    if missing:

        raise RuntimeError(
            "Variáveis ausentes no .env: "
            + ", ".join(missing)
        )


def load_pizzaria():

    with open(
        PIZZARIA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# =========================================
# MEMÓRIA POR TELEFONE
# =========================================

def _memoria_padrao():

    return {
        "cliente": {
            "id": None,
            "nome": "",
            "telefone": "",
            "endereco": ""
        },
        "pedido_atual": {
            "quantidade": 1,
            "tamanho": "",
            "sabores": [],
            "meio_a_meio": False,
            "borda": "",
            "bebidas": [],
            "pagamento": ""
        },
        "historico_pedidos": [],
        "historico_conversa": []
    }


def memory_path(telefone):

    return os.path.join(
        MEMORY_DIR,
        f"{telefone}.json"
    )


def save_memory(telefone, memory):

    os.makedirs(MEMORY_DIR, exist_ok=True)

    with open(
        memory_path(telefone),
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            memory,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_memory(telefone):

    caminho = memory_path(telefone)

    if not os.path.exists(caminho):

        memory = _memoria_padrao()
        memory["cliente"]["telefone"] = telefone
        save_memory(telefone, memory)

        return memory

    with open(
        caminho,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# =========================================
# BANCO DE DADOS (tolerante a indisponibilidade)
# =========================================

def conectar():

    try:

        return psycopg2.connect(**DB_CONFIG)

    except Exception as erro:

        print(f"[DB] indisponível, seguindo sem banco: {erro}")

        return None


def normalizar_telefone(telefone):
    """Mantém apenas os dígitos para que a busca no banco case
    independente de formatação (+55, espaços, traços, etc.)."""

    if not telefone:
        return ""

    return "".join(c for c in str(telefone) if c.isdigit())


def buscar_cliente(telefone, conn):

    if conn is None:

        return None

    with conn.cursor() as cur:

        cur.execute(
            """
            SELECT
                id,
                nome,
                telefone,
                endereco
            FROM clientes
            WHERE telefone = %s
            LIMIT 1
            """,
            (normalizar_telefone(telefone),)
        )

        return cur.fetchone()


def buscar_ultimos_pedidos(telefone, conn, limite=3):
    """Recupera os últimos pedidos do cliente pelo número, para a IA
    poder oferecer repetir o pedido mesmo sem memória local."""

    if conn is None:

        return []

    with conn.cursor() as cur:

        cur.execute(
            """
            SELECT
                p.pedido_json,
                p.status,
                p.criado_em
            FROM pedidos p
            JOIN clientes c ON c.id = p.cliente_id
            WHERE c.telefone = %s
            ORDER BY p.criado_em DESC
            LIMIT %s
            """,
            (normalizar_telefone(telefone), limite)
        )

        return [
            {
                "pedido": pedido_json,
                "status": status,
                "data": criado_em.isoformat() if criado_em else None,
            }
            for pedido_json, status, criado_em in cur.fetchall()
        ]


def cadastrar_cliente(nome, telefone, endereco, conn):

    if conn is None:

        return None

    with conn.cursor() as cur:

        cur.execute(
            """
            INSERT INTO clientes
            (
                nome,
                telefone,
                endereco
            )
            VALUES
            (%s,%s,%s)
            ON CONFLICT (telefone) DO UPDATE SET
                nome = EXCLUDED.nome,
                endereco = EXCLUDED.endereco
            RETURNING id
            """,
            (
                nome,
                normalizar_telefone(telefone),
                endereco
            )
        )

        cliente_id = cur.fetchone()[0]

    conn.commit()

    return cliente_id


def salvar_pedido(cliente_id, pedido, conn, status="recebido"):

    if conn is None or cliente_id is None:

        return None

    with conn.cursor() as cur:

        cur.execute(
            """
            INSERT INTO pedidos
            (cliente_id, pedido_json, status)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (cliente_id, Json(pedido), status)
        )

        pedido_id = cur.fetchone()[0]

    conn.commit()

    return pedido_id


# =========================================
# SAÍDA ESTRUTURADA DA IA
# A IA anexa um bloco JSON (entre marcas) com os dados coletados.
# O código lê esse bloco para preencher a memória e gravar no banco,
# e o remove antes de enviar o texto ao cliente.
# =========================================

DADOS_RE = re.compile(
    r"<<<DADOS>>>\s*(\{.*?\})\s*<<<DADOS>>>",
    re.DOTALL
)


def extrair_dados_estruturados(resposta):
    """Separa o texto visível ao cliente do bloco de dados técnico.
    Retorna (texto_limpo, dados_dict_ou_None)."""

    match = DADOS_RE.search(resposta)

    if not match:
        return resposta.strip(), None

    texto = (resposta[:match.start()] + resposta[match.end():]).strip()

    try:
        dados = json.loads(match.group(1))
    except json.JSONDecodeError:
        dados = None

    return texto, dados


def aplicar_dados(memory, dados):
    """Atualiza cliente/pedido_atual na memória com o que a IA coletou."""

    cliente = dados.get("cliente") or {}
    for campo in ("nome", "endereco"):
        valor = cliente.get(campo)
        if valor:
            memory["cliente"][campo] = valor

    pedido = dados.get("pedido") or {}
    if pedido:
        memory["pedido_atual"].update(pedido)


def pedido_completo(pedido):
    """Garante que o pedido tem o mínimo obrigatório antes de finalizar,
    evitando gravar um pedido vazio mesmo que a IA mande status=confirmado."""

    return bool(
        pedido.get("tamanho")
        and pedido.get("sabores")
        and pedido.get("pagamento")
    )


def persistir(memory, status, conn):
    """Cadastra o cliente novo (se ainda não existe) e salva o pedido
    quando o cliente confirma. Retorna True se algo foi gravado."""

    if conn is None:
        return False

    cliente = memory["cliente"]
    gravou = False

    # Cadastra cliente novo assim que tivermos nome + endereço
    if (
        cliente.get("nome")
        and cliente.get("endereco")
        and not cliente.get("id")
    ):
        cliente["id"] = cadastrar_cliente(
            cliente["nome"],
            cliente["telefone"],
            cliente["endereco"],
            conn
        )
        memory["cliente_cadastrado"] = True
        gravou = True

    # Salva o pedido apenas após a confirmação explícita do cliente
    # E com o pedido completo (trava contra finalização prematura).
    if (
        status == "confirmado"
        and cliente.get("id")
        and pedido_completo(memory["pedido_atual"])
    ):
        pedido_id = salvar_pedido(
            cliente["id"],
            memory["pedido_atual"],
            conn
        )

        memory.setdefault("historico_pedidos", []).append({
            "pedido_id": pedido_id,
            "pedido": memory["pedido_atual"],
        })

        # Limpa o carrinho para um eventual próximo pedido
        memory["pedido_atual"] = _memoria_padrao()["pedido_atual"]
        gravou = True

    return gravou


# =========================================
# CAMADA DE IA
# =========================================

def chat(messages):

    if LLM_PROVIDER == "ollama":

        from llm_ollama import generate_chat_response

    else:

        from llm_api import generate_chat_response

    return generate_chat_response(messages)


def montar_system_prompt(pizzaria, memory):

    def linhas(itens):
        return "\n".join(f"- {item}" for item in itens)

    cadastrado = memory.get("cliente_cadastrado", False)
    ultimos = memory.get("ultimos_pedidos", [])

    if cadastrado:
        bloco_reconhecimento = (
            "Este cliente JÁ É CADASTRADO. Saúde-o pelo nome e, se houver "
            "pedidos anteriores, ofereça repetir o último pedido."
        )
    else:
        bloco_reconhecimento = (
            "Cliente NÃO cadastrado. Faça o onboarding: pergunte o nome e o "
            "endereço de entrega de forma natural ao longo do atendimento."
        )

    return f"""{pizzaria.get('system_prompt', '')}

REGRAS:
{linhas(pizzaria.get('regras', []))}

FLUXO DE ATENDIMENTO:
{linhas(pizzaria.get('fluxo', []))}

CARDÁPIO (nunca ofereça itens fora desta lista):
Tamanhos: {', '.join(pizzaria.get('tamanhos', []))}
Sabores: {', '.join(pizzaria.get('sabores', []))}
Bebidas: {', '.join(pizzaria.get('bebidas', []))}

DADOS OBRIGATÓRIOS PARA FECHAR O PEDIDO:
{', '.join(pizzaria.get('dados_obrigatorios', []))}

RECONHECIMENTO:
{bloco_reconhecimento}

CLIENTE (dados vindos do cadastro pelo número de telefone):
{json.dumps(memory.get('cliente', {}), ensure_ascii=False)}

ÚLTIMOS PEDIDOS DESTE CLIENTE:
{json.dumps(ultimos, ensure_ascii=False)}

PROCEDIMENTO DE CADASTRO (cliente novo):
{linhas(pizzaria.get('procedimento_cadastro', []))}

PROCEDIMENTO DE CONFIRMAÇÃO (obrigatório antes de finalizar):
{linhas(pizzaria.get('procedimento_confirmacao', []))}

MODELO DE RESUMO (use este formato ao apresentar o pedido completo):
{pizzaria.get('modelo_resumo', '')}

PEDIDO ATUAL (já coletado até agora — NÃO pergunte novamente o que já está preenchido):
{json.dumps(memory.get('pedido_atual', {}), ensure_ascii=False)}

Leia o histórico da conversa antes de responder. Mantenha contexto, não repita perguntas já respondidas e siga avançando o pedido até apresentar o resumo final para confirmação.

REGRA DE OURO DA CONFIRMAÇÃO:
- NUNCA finalize o pedido direto. Quando tiver TODOS os dados obrigatórios, apresente o RESUMO COMPLETO do pedido (todos os itens, endereço e pagamento) e pergunte *Confirma o pedido acima?*.
- Aguarde o cliente responder SIM de forma explícita. Só então o pedido é finalizado.
- Se o cliente pedir mudança, ajuste e mostre o resumo de novo antes de confirmar.

SAÍDA ESTRUTURADA (OBRIGATÓRIA):
Ao FINAL de toda resposta, anexe um bloco técnico com os dados coletados até agora, EXATAMENTE neste formato (entre as marcas <<<DADOS>>>):

<<<DADOS>>>
{{"cliente": {{"nome": "", "endereco": ""}}, "pedido": {{"quantidade": 1, "tamanho": "", "sabores": [], "meio_a_meio": false, "borda": "", "bebidas": [], "pagamento": ""}}, "status": "em_andamento"}}
<<<DADOS>>>

Regras do bloco e do campo "status":
- Preencha SOMENTE o que o cliente já informou; deixe o resto como string vazia ou lista vazia.
- "status": "em_andamento" → ainda coletando dados ou faltam itens obrigatórios.
- "status": "aguardando_confirmacao" → você acabou de apresentar o RESUMO COMPLETO e está esperando o cliente confirmar. Use SEMPRE este status na mensagem em que mostra o resumo.
- "status": "confirmado" → APENAS na mensagem seguinte, depois que o cliente respondeu SIM explicitamente ao resumo. NUNCA pule direto para "confirmado" sem ter passado por "aguardando_confirmacao".
- Esse bloco é técnico, será removido antes de chegar ao cliente. NUNCA o mencione nem o comente na conversa."""


def processar_mensagem(telefone, mensagem, push_name=""):
    """Processa uma mensagem do cliente mantendo memória/histórico por telefone
    e retorna a resposta da IA."""

    telefone = normalizar_telefone(telefone)

    pizzaria = load_pizzaria()
    memory = load_memory(telefone)

    memory.setdefault("cliente", {})
    memory["cliente"]["telefone"] = telefone

    # Mantém a conexão aberta por toda a interação: reconhecer (ler) no
    # início e persistir (gravar) no fim usam a mesma conexão.
    conn = conectar()
    try:
        # Reconhecimento do cliente PELO NÚMERO, direto no banco.
        # Funciona mesmo que a memória local esteja vazia/inexistente.
        cliente = buscar_cliente(telefone, conn)

        if cliente:
            memory["cliente"] = {
                "id": cliente[0],
                "nome": cliente[1],
                "telefone": cliente[2],
                "endereco": cliente[3],
            }
            memory["cliente_cadastrado"] = True
            memory["ultimos_pedidos"] = buscar_ultimos_pedidos(telefone, conn)
        else:
            memory["cliente_cadastrado"] = False
            memory["ultimos_pedidos"] = []
            if push_name and not memory["cliente"].get("nome"):
                memory["cliente"]["nome"] = push_name

        historico = memory.setdefault("historico_conversa", [])
        historico.append({"role": "user", "content": mensagem})

        messages = (
            [{"role": "system", "content": montar_system_prompt(pizzaria, memory)}]
            + historico[-HISTORICO_JANELA:]
        )

        resposta_bruta = chat(messages).strip()

        # Separa o texto visível do bloco técnico e persiste o que foi coletado
        texto, dados = extrair_dados_estruturados(resposta_bruta)

        if dados:
            aplicar_dados(memory, dados)
            persistir(memory, dados.get("status", ""), conn)

        historico.append({"role": "assistant", "content": texto})
        memory["historico_conversa"] = historico[-HISTORICO_MAX:]

        save_memory(telefone, memory)

        return texto

    finally:
        if conn is not None:
            conn.close()


# =========================================
# REPL DE TESTE (linha de comando)
# =========================================

def main():

    validate_config()

    telefone = input("Telefone: ").strip()

    print(
        "\nDigite as mensagens do cliente "
        "(sair/exit/quit para encerrar).\n"
    )

    while True:

        msg = input("Cliente: ").strip()

        if msg.lower() in ("sair", "exit", "quit"):
            break

        resposta = processar_mensagem(telefone, msg)

        print(f"\nE-Pizza:\n{resposta}\n")


if __name__ == "__main__":
    main()
