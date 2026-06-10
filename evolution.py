
from collections import deque, defaultdict
from threading import Lock
import json
import os
import re

from flask import Flask, request
import requests

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
# =========================================

_ids_processados = deque(maxlen=1000)
_ids_set = set()

dedupe_lock = Lock()
cliente_locks = defaultdict(Lock)

def ja_processado(message_id):
    if not message_id:
        return False

    with dedupe_lock:
        if message_id in _ids_set:
            return True

        _ids_processados.append(message_id)
        _ids_set.add(message_id)

        while len(_ids_set) > len(_ids_processados):
            _ids_set.intersection_update(_ids_processados)

        return False

def limpar_numero(valor):
    if not valor:
        return ""

    return (
        str(valor)
        .split("@")[0]
        .split(":")[0]
        .strip()
    )


def extrair_numero(data, payload, chave):
    """A identidade do cliente é o key.remoteJid (o OUTRO lado do chat)."""
    remote = chave.get("remoteJid", "") or ""

    print("\n===== DEBUG NUMERO =====")
    print("remoteJid (cliente) =", remote)
    print("sender (ignorado)   =", data.get("sender"))
    print("========================\n")

    if remote.endswith("@g.us"):   # grupos não são atendidos
        return ""

    return limpar_numero(remote)


# Telefone real costuma aparecer como <dígitos>@s.whatsapp.net no payload.
TELEFONE_RE = re.compile(r"(\d{12,15})@s\.whatsapp\.net")


def telefone_resposta(data, payload, chave):
    """O Evolution entrega para números reais (@s.whatsapp.net). Caso o remoteJid use
    a máscara @lid, tentamos buscar o número real no payload ou no sender do root."""
    remote = chave.get("remoteJid", "") or ""

    # 1. Se o remoteJid já for um telefone real, limpamos apenas os prefixos extras
    if remote.endswith("@s.whatsapp.net"):
        return limpar_numero(remote)

    # 2. Varre campos onde o telefone real costuma vir quando o remoteJid vem como @lid
    for valor in (
        payload.get("senderPn"),
        payload.get("participantPn"),
        chave.get("senderPn"),
        chave.get("participantPn"),
        chave.get("participant"),
    ):
        if valor and "@lid" not in str(valor):
            num = limpar_numero(valor)
            if num:
                return num

    # 3. Varre todo o payload por um telefone@s.whatsapp.net
    for achado in TELEFONE_RE.findall(json.dumps(data)):
        return achado

    # 4. Fallback crítico para testes com o próprio número: busca a identidade real no remetente root
    sender_root = data.get("sender", "")
    if sender_root and sender_root.endswith("@s.whatsapp.net"):
        return limpar_numero(sender_root)

    return ""


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
    payload_texto = json.dumps(data, indent=2, ensure_ascii=False)

    with open("payload_debug.txt", "w", encoding="utf-8") as f:
        f.write(payload_texto)

    with open("ultimo_payload.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    try:
        if data.get("event") != "messages.upsert":
            return {"status": "ignored"}

        payload = data.get("data", {})
        chave = payload.get("key", {})
        mensagem_obj = payload.get("message", {}) or {}

        message_id = chave.get("id")
        from_me = chave.get("fromMe", False)
        push_name = payload.get("pushName", "") or ""

        print("ROOT SENDER =", data.get("sender"))
        print("PAYLOAD SENDER =", payload.get("sender"))
        print("REMOTE JID =", chave.get("remoteJid"))

        numero = extrair_numero(data, payload, chave)
        remote_jid = chave.get("remoteJid", "")

        if "@g.us" in remote_jid:
            return {"status": "ignored_group"}

        if not numero:
            return {"status": "no_number"}
            
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

        with cliente_locks[numero]:
            resposta = processar_mensagem(
                numero,
                mensagem,
                push_name
            )

        print("\nRESPOSTA:")
        print(resposta)

        # Localiza o número de destino real convertido
        destino = telefone_resposta(data, payload, chave)
        print("TELEFONE RESPOSTA EXTRAÍDO =", destino)

        # Garante que o target_number use sempre a terminação correta aceita pela API
        if destino:
            target_number = f"{destino}@s.whatsapp.net"
        else:
            # Fallback definitivo: limpa e força o formato no remote_jid se nada mais funcionar
            target_number = f"{limpar_numero(remote_jid)}@s.whatsapp.net"

        print(f"DISPARANDO PARA O DESTINO CORRETO: {target_number}")

        envio = requests.post(
            f"{EVOLUTION_URL}/message/sendText/{INSTANCE_NAME}",
            headers={"apikey": API_KEY},
            json={
                "number": target_number,
                "text": resposta
            }
        )

        print("\nSTATUS ENVIO:")
        print(envio.status_code)
        print(envio.text)

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
    port=5000,
    threaded=True
)

