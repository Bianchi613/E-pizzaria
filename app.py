
import json
import os
import re

import psycopg2
from psycopg2.extras import Json

from dotenv import load_dotenv

load_dotenv()

PIZZARIA_PATH = "prompts/pizzaria.json"
SYSTEM_PROMPT_PATH = "prompts/system_prompt.txt"
EXTRACTION_PROMPT_PATH = "prompts/extraction_prompt.txt"
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
            "itens": [],
            "bebidas": [],
            "observacoes": [],
            "endereco_entrega": "",
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


def _significativo(valor):
    """True se o valor deve sobrescrever o que já existe. Booleanos e números
    sempre valem; strings/listas só quando não estão vazios. Isso evita que a
    IA apague o carrinho ao mandar campos vazios na mensagem de confirmação."""

    if isinstance(valor, bool):
        return True
    if isinstance(valor, (int, float)):
        return True
    return bool(valor)


def aplicar_dados(memory, dados):
    """Atualiza cliente/pedido_atual na memória com o que a IA coletou,
    sem sobrescrever dados já preenchidos por valores vazios."""

    cliente = dados.get("cliente") or {}
    for campo in ("nome", "endereco"):
        if _significativo(cliente.get(campo)):
            memory["cliente"][campo] = cliente[campo]

    pedido = dados.get("pedido") or {}
    for campo, valor in pedido.items():
        if _significativo(valor):
            memory["pedido_atual"][campo] = valor


def _eh_borda_paga(borda):
    """Borda só é cobrada quando é recheada (não tradicional/normal/vazia)."""

    valor = (borda or "").strip().lower()

    return valor not in ("", "tradicional", "normal", "sem", "sem borda", "nao")


def calcular_total(pedido, precos):
    """Calcula os valores do pedido de forma determinística (o LLM não faz
    a conta). Soma todos os itens (pizzas), bebidas e taxa de entrega."""

    precos_tam = precos.get("tamanhos", {})
    precos_beb = precos.get("bebidas", {})
    preco_borda = precos.get("borda", 0)
    taxa = precos.get("taxa_entrega", 0)

    itens_valores = []
    valor_pizzas = 0

    for item in pedido.get("itens", []):
        qtd = item.get("quantidade") or 1
        tamanho = (item.get("tamanho") or "").strip().lower()

        v_pizza = precos_tam.get(tamanho, 0) * qtd
        v_borda = preco_borda * qtd if _eh_borda_paga(item.get("borda")) else 0
        subtotal_item = v_pizza + v_borda

        valor_pizzas += subtotal_item
        itens_valores.append({
            "tamanho": item.get("tamanho", ""),
            "quantidade": qtd,
            "valor_pizza": v_pizza,
            "valor_borda": v_borda,
            "subtotal": subtotal_item,
        })

    valor_bebidas = sum(
        precos_beb.get(str(b).strip().lower(), 0)
        for b in pedido.get("bebidas", [])
    )

    subtotal = valor_pizzas + valor_bebidas
    taxa_entrega = taxa if subtotal > 0 else 0
    total = subtotal + taxa_entrega

    return {
        "itens": itens_valores,
        "valor_pizzas": valor_pizzas,
        "valor_bebidas": valor_bebidas,
        "taxa_entrega": taxa_entrega,
        "total": total,
    }


def formatar_resumo_valores(valores):
    """Bloco de valores que o CÓDIGO anexa ao resumo (a IA não escreve preços),
    garantindo que o total exibido seja sempre igual ao gravado no banco.
    Mostra o preço de CADA pizza e o total."""

    linhas = []

    for item in valores.get("itens", []):
        extra = f" (+ borda R$ {item['valor_borda']})" if item["valor_borda"] else ""
        linhas.append(
            f"🍕 {item['quantidade']}x {item['tamanho']}"
            f"{extra} — R$ {item['subtotal']}"
        )

    if valores["valor_bebidas"]:
        linhas.append(f"🥤 Bebidas — R$ {valores['valor_bebidas']}")

    linhas.append(f"🚚 Taxa de entrega — R$ {valores['taxa_entrega']}")
    linhas.append(f"💰 *TOTAL: R$ {valores['total']}*")

    return "—————————————\n" + "\n".join(linhas)


def pedido_completo(pedido):
    """Garante que o pedido tem o mínimo obrigatório antes de finalizar:
    pelo menos uma pizza (com tamanho e sabores) e forma de pagamento."""

    itens = pedido.get("itens", [])

    if not itens:
        return False

    todos_validos = all(
        item.get("tamanho") and item.get("sabores")
        for item in itens
    )

    return bool(todos_validos and pedido.get("pagamento"))


def persistir(memory, status, conn, precos=None):
    """Cadastra o cliente novo (se ainda não existe) e salva o pedido
    quando o cliente confirma. Retorna True se algo foi gravado."""

    if conn is None:
        return False

    precos = precos or {}
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
        # Garante o endereço de entrega no pedido (snapshot); se a IA não
        # preencheu endereco_entrega, usa o endereço do cadastro.
        if not memory["pedido_atual"].get("endereco_entrega"):
            memory["pedido_atual"]["endereco_entrega"] = cliente.get("endereco", "")

        # Anexa os valores calculados ao pedido antes de gravar
        memory["pedido_atual"]["valores"] = calcular_total(
            memory["pedido_atual"],
            precos
        )

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


def load_system_template():

    with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


# Placeholder no template: [[CHAVE]] ou [[CHAVE:estilo]]
PLACEHOLDER_RE = re.compile(r"\[\[([A-Z_]+)(?::(\w+))?\]\]")


def _render_inline(valor):
    if isinstance(valor, dict):
        return ", ".join(f"{k}: {v}" for k, v in valor.items())
    if isinstance(valor, list):
        return ", ".join(str(item) for item in valor)
    return str(valor)


def _render(valor, estilo="bloco"):
    """Formata um valor genérico para o prompt, sem conhecer o domínio.
    - listas: bullets (ou inline se estilo='inline')
    - dicts: uma linha 'chave: valor' por item
    - escalares: o próprio texto
    """

    if isinstance(valor, dict):
        return "\n".join(f"- {k}: {_render_inline(v)}" for k, v in valor.items())

    if isinstance(valor, list):
        if estilo == "inline":
            return _render_inline(valor)
        return "\n".join(f"- {_render_inline(item)}" for item in valor)

    return str(valor)


def montar_system_prompt(config, memory):
    """Motor de template genérico (independente do domínio): para cada
    placeholder [[CHAVE]] no template, busca a chave em `config` (arquivo de
    negócio) ou nos dados de runtime, e formata. Trocar de negócio = trocar
    os arquivos em prompts/, sem mexer no código."""

    cadastrado = memory.get("cliente_cadastrado", False)

    # Dados que vêm do estado da conversa (não do arquivo de negócio)
    runtime = {
        "RECONHECIMENTO": config.get(
            "reconhecimento_cadastrado" if cadastrado else "reconhecimento_novo",
            ""
        ),
        "CLIENTE": json.dumps(memory.get("cliente", {}), ensure_ascii=False),
        "ULTIMOS_PEDIDOS": json.dumps(
            memory.get("ultimos_pedidos", []), ensure_ascii=False
        ),
        "PEDIDO_ATUAL": json.dumps(
            memory.get("pedido_atual", {}), ensure_ascii=False
        ),
    }

    def resolver(match):
        chave, estilo = match.group(1), match.group(2) or "bloco"

        if chave in runtime:
            return runtime[chave]

        return _render(config.get(chave.lower(), ""), estilo)

    return PLACEHOLDER_RE.sub(resolver, load_system_template())


# =========================================
# EXTRAÇÃO DE ESTADO (chamada dedicada)
# Em vez de depender do modelo de chat anexar o bloco <<<DADOS>>>, uma 2ª
# chamada focada lê a conversa e devolve SEMPRE o JSON do estado do pedido.
# =========================================

JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def montar_extraction_prompt(config):

    with open(EXTRACTION_PROMPT_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    def resolver(match):
        chave, estilo = match.group(1), match.group(2) or "bloco"
        return _render(config.get(chave.lower(), ""), estilo)

    return PLACEHOLDER_RE.sub(resolver, template)


def _parse_json_estado(texto):

    match = JSON_OBJ_RE.search(texto or "")

    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def extrair_estado(historico, config):
    """Chamada dedicada: lê a conversa e devolve o JSON do estado do pedido.
    Não depende de o modelo de chat ter emitido qualquer bloco."""

    conversa = "\n".join(
        f"{'Cliente' if m['role'] == 'user' else 'Atendente'}: {m['content']}"
        for m in historico
    )

    messages = [
        {"role": "system", "content": montar_extraction_prompt(config)},
        {
            "role": "user",
            "content": f"CONVERSA:\n{conversa}\n\nDevolva APENAS o JSON do estado atual."
        },
    ]

    return _parse_json_estado(chat(messages))


def processar_mensagem(telefone, mensagem, push_name=""):
    """Processa uma mensagem do cliente mantendo memória/histórico por telefone
    e retorna a resposta da IA."""

    telefone = normalizar_telefone(telefone)

    pizzaria = load_pizzaria()
    memory = load_memory(telefone)

    memory.setdefault("cliente", {})
    memory["cliente"]["telefone"] = telefone

    # Migra carrinhos no formato antigo (1 pizza) para o novo (lista de itens)
    if "itens" not in memory.get("pedido_atual", {}):
        memory["pedido_atual"] = _memoria_padrao()["pedido_atual"]

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

        print("\n===== SYSTEM PROMPT =====")
        print(messages[0]["content"])
        print("=========================\n")

        resposta_bruta = chat(messages).strip()
        print("\n===== RESPOSTA BRUTA =====")
        print(resposta_bruta)
        print("=========================\n")

        # Limpa qualquer bloco técnico que o chat tenha emitido por engano
        texto, _ = extrair_dados_estruturados(resposta_bruta)

        # Estado do pedido vem de uma chamada DEDICADA (não depende do chat).
        historico_para_extracao = historico + [
            {"role": "assistant", "content": texto}
        ]
        dados = extrair_estado(
            historico_para_extracao[-HISTORICO_JANELA:],
            pizzaria
        )
        print("DADOS EXTRAIDOS =", dados)

        if dados:
            aplicar_dados(memory, dados)
            persistir(
                memory,
                dados.get("status", ""),
                conn,
                pizzaria.get("precos", {})
            )

            # No resumo, o CÓDIGO anexa o preço de cada pizza e o total
            # (a IA não escreve preços) — o que o cliente vê = o que é gravado.
            if dados.get("status") == "aguardando_confirmacao":
                valores = calcular_total(
                    memory["pedido_atual"],
                    pizzaria.get("precos", {})
                )
                texto = f"{texto}\n\n{formatar_resumo_valores(valores)}"

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
