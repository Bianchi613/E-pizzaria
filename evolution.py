from flask import Flask, request
import requests
import os

from dotenv import load_dotenv

# =========================================
# LOAD ENV
# =========================================

load_dotenv()

# =========================================
# IMPORTA SUA E-pizzaria ONLINE
# =========================================

from app import generate_response, SYSTEM_PROMPT

# =========================================
# APP
# =========================================

app = Flask(__name__)

# =========================================
# CONFIG
# =========================================

EVOLUTION_URL = os.getenv("EVOLUTION_URL")

INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE")

API_KEY = os.getenv("EVOLUTION_API_KEY")

# =========================================
# GERAR RESPOSTA
# =========================================

def responder(mensagem_usuario):

    resposta = generate_response(
        [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": mensagem_usuario,
            },
        ]
    )

    return resposta.strip()

# =========================================
# WEBHOOK
# =========================================

@app.route("/webhook/messages-upsert", methods=["POST"])
def webhook():

    data = request.json

    try:

        print("\n==============================")
        print("DADOS RECEBIDOS")
        print("==============================")
        print(data)

        mensagem = (
            data["data"]["message"]["conversation"]
        )

        mensagem_lower = mensagem.lower()

        numero = data.get("sender", "")
        
        numero = (
            numero
            .replace("@s.whatsapp.net", "")
        )

        from_me = data["data"]["key"].get("fromMe")

        # =========================================
        # IGNORA MENSAGENS DA E-pizzaria ONLINE
        # MAS PERMITE TESTE MANUAL
        # =========================================

        if from_me and "E-pizzaria ONLINE" not in mensagem_lower:

            print("\nMensagem automática ignorada.\n")

            return {
                "status": "ignored"
            }

        # =========================================
        # RESPONDE APENAS QUANDO CHAMADA
        # =========================================

        if "E-pizzaria ONLINE" not in mensagem_lower:

            print("\nMensagem ignorada (sem chamar E-pizzaria ONLINE).\n")

            return {
                "status": "ignored"
            }

        # REMOVE "E-pizzaria ONLINE" DA FRASE
        mensagem = (
            mensagem
            .replace("E-pizzaria ONLINE", "")
            .replace("E-pizzaria ONLINE", "")
            .strip()
        )

        # EVITA MENSAGEM VAZIA
        if not mensagem:

            mensagem = "Oi"

        print(f"\nMensagem de {numero}")
        print(f"Texto: {mensagem}")

        resposta = responder(mensagem)

        print(f"\nE-pizzaria ONLINE:")
        print(resposta)

        # =========================================
        # ENVIA RESPOSTA
        # =========================================

        response = requests.post(
            f"{EVOLUTION_URL}/message/sendText/{INSTANCE_NAME}",
            headers={
                "apikey": API_KEY
            },
            json={
                "number": numero,
                "text": resposta
            }
        )

        print("\nSTATUS ENVIO:")
        print(response.status_code)
        print(response.text)

        return {
            "status": "ok"
        }

    except Exception as erro:

        print("\nERRO:")
        print(erro)

        return {
            "erro": str(erro)
        }

# =========================================
# START
# =========================================

print("\n===================================")
print("E-pizzaria ONLINE")
print("===================================\n")

app.run(
    host="0.0.0.0",
    port=5000
)