from collections import deque

from flask import Flask, request
import requests
import os

from dotenv import load_dotenv

# =========================================
# LOAD ENV
# =========================================

load_dotenv()

# =========================================
# IMPORTA A LÓGICA DA E-PIZZARIA
# =========================================

from app import processar_mensagem

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

# Em produção o bot NÃO deve responder mensagens enviadas por ele mesmo
# (fromMe=True) para evitar loop. Durante testes com o próprio número,
# defina IGNORE_FROM_ME=false no .env.
IGNORE_FROM_ME = os.getenv("IGNORE_FROM_ME", "false").lower() == "true"

# =========================================
# DEDUPLICAÇÃO DE EVENTOS
# O Evolution dispara o webhook várias vezes para a MESMA mensagem
# (status READ, SERVER_ACK, etc.) com o mesmo key.id. Sem isso, a IA
# responde 2+ vezes para cada mensagem.
# =========================================

_ids_processados = deque(maxlen=1000)
_ids_set = set()


def ja_processado(message_id):

    if not message_id:
        return False

    if message_id in _ids_set:
        return True

    _ids_processados.append(message_id)
    _ids_set.add(message_id)

    # mantém o set alinhado com a janela da deque
    while len(_ids_set) > len(_ids_processados):
        _ids_set.intersection_update(_ids_processados)

    return False


def extrair_numero(data, chave):

    sender = data.get("sender", "")

    if not sender:
        sender = chave.get("remoteJid", "")

    return (
        sender
        .split("@")[0]
        .split(":")[0]
    )


def extrair_mensagem(mensagem_obj):

    if "conversation" in mensagem_obj:
        return mensagem_obj["conversation"]

    if "extendedTextMessage" in mensagem_obj:
        return mensagem_obj["extendedTextMessage"].get("text", "")

    return ""


# =========================================
# WEBHOOK
# =========================================

@app.route("/webhook/messages-upsert", methods=["POST"])
def webhook():

    data = request.json

    try:

        if data.get("event") != "messages.upsert":
            return {"status": "ignored"}

        payload = data.get("data", {})
        chave = payload.get("key", {})
        mensagem_obj = payload.get("message", {}) or {}

        message_id = chave.get("id")
        from_me = chave.get("fromMe", False)
        push_name = payload.get("pushName", "") or ""

        numero = extrair_numero(data, chave)
        mensagem = extrair_mensagem(mensagem_obj)

        # Ignora mensagens próprias (loop) se configurado
        if from_me and IGNORE_FROM_ME:
            return {"status": "ignored_from_me"}

        # Ignora mensagens vazias / sem texto (status updates, mídia, etc.)
        if not mensagem.strip():
            return {"status": "ignored_empty"}

        # Ignora reentregas do MESMO evento (dedupe por id)
        if ja_processado(message_id):
            return {"status": "duplicate"}

        print("\n==============================")
        print(f"NUMERO: {numero}")
        print(f"MENSAGEM: {mensagem}")
        print(f"FROM_ME: {from_me}  ID: {message_id}")
        print("==============================")

        resposta = processar_mensagem(numero, mensagem, push_name)

        print("\nRESPOSTA:")
        print(resposta)

        envio = requests.post(
            f"{EVOLUTION_URL}/message/sendText/{INSTANCE_NAME}",
            headers={"apikey": API_KEY},
            json={
                "number": numero,
                "text": resposta
            }
        )

        print("\nSTATUS ENVIO:")
        print(envio.status_code)

        return {"status": "ok"}

    except Exception as erro:

        print("\nERRO:")
        print(erro)

        return {"erro": str(erro)}


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
