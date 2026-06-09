
import json
import os

import psycopg2

from dotenv import load_dotenv

load_dotenv()

PIZZARIA_PATH = "prompts/pizzaria.json"
MEMORY_PATH = "prompts/memoria.json"

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


def save_memory(memory):

    os.makedirs(
        os.path.dirname(MEMORY_PATH),
        exist_ok=True
    )

    with open(
        MEMORY_PATH,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            memory,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_memory():

    if not os.path.exists(MEMORY_PATH):

        memory = {
            "cliente": {},
            "pedido_atual": {},
            "historico_conversa": []
        }

        save_memory(memory)

        return memory

    with open(
        MEMORY_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def conectar():

    return psycopg2.connect(
        **DB_CONFIG
    )


def buscar_cliente(
    telefone,
    conn
):

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
            (telefone,)
        )

        return cur.fetchone()


def cadastrar_cliente(
    nome,
    telefone,
    endereco,
    conn
):

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
            RETURNING id
            """,
            (
                nome,
                telefone,
                endereco
            )
        )

        cliente_id = cur.fetchone()[0]

    conn.commit()

    return cliente_id


def generate_response(
    system_prompt,
    user_prompt
):

    if LLM_PROVIDER == "ollama":

        from llm_ollama import (
            generate_chat_response
        )

    else:

        from llm_api import (
            generate_chat_response
        )

    return generate_chat_response(
        [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]
    )


def main():

    validate_config()

    pizzaria = load_pizzaria()

    memory = load_memory()

    conn = conectar()

    telefone = input(
        "Telefone: "
    ).strip()

    cliente = buscar_cliente(
        telefone,
        conn
    )

    if cliente:

        memory["cliente"] = {
            "id": cliente[0],
            "nome": cliente[1],
            "telefone": cliente[2],
            "endereco": cliente[3]
        }

        print(
            f"\nCliente encontrado: "
            f"{cliente[1]}"
        )

    else:

        print(
            "\nCliente não cadastrado."
        )

        nome = input(
            "Nome: "
        ).strip()

        endereco = input(
            "Endereço: "
        ).strip()

        cliente_id = cadastrar_cliente(
            nome,
            telefone,
            endereco,
            conn
        )

        memory["cliente"] = {
            "id": cliente_id,
            "nome": nome,
            "telefone": telefone,
            "endereco": endereco
        }

        save_memory(memory)

    while True:

        msg = input(
            "\nCliente: "
        ).strip()

        if msg.lower() in (
            "sair",
            "exit",
            "quit"
        ):
            break

        memory[
            "historico_conversa"
        ].append(
            {
                "usuario": msg
            }
        )

        prompt = f"""
CONFIGURAÇÃO DA PIZZARIA

{json.dumps(
    pizzaria,
    ensure_ascii=False,
    indent=2
)}

MEMÓRIA

{json.dumps(
    memory,
    ensure_ascii=False,
    indent=2
)}

MENSAGEM DO CLIENTE

{msg}
"""

        resposta = generate_response(
            pizzaria["system_prompt"],
            prompt
        )

        print(
            f"\nE-Pizza:\n{resposta}"
        )

        memory[
            "historico_conversa"
        ].append(
            {
                "assistente": resposta
            }
        )

        save_memory(memory)

    conn.close()


if __name__ == "__main__":
    main()