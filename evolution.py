from collections import deque, defaultdict
from threading import Lock
import json
import os
import re
import traceback

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
# O Evolution dispara o webhook várias vezes para a MESMA mensagem
# (status READ, SERVER_ACK, etc.) com o mesmo key.id. Sem isso, a IA
# responde 2+ vezes para cada mensagem.
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


# Telefone real costuma aparecer como <dígitos>@s.whatsapp.net no payload.
TELEFONE_RE = re.compile(r"(\d{12,15})@s\.whatsapp\.net")


def extrair_telefone(data, payload, chave):
    """Telefone do cliente: usado tanto como IDENTIDADE (memória/banco em
    app.py) quanto como DESTINO do sendText. Antes essas duas coisas vinham
    de funções separadas (extrair_numero / telefone_resposta) e podiam
    divergir quando o remoteJid era @lid: a memória/banco gravava sob o
    @lid, mas a resposta era enviada para o telefone real encontrado em
    outro campo. Isso causou clientes/memórias duplicados (ex: o mesmo
    cliente "Alan Bianchi" com um registro sob "227856655356035" e outro
    sob "5521988138401"). Unificando aqui, os dois usos sempre recebem o
    MESMO valor.

    NUNCA usar 'sender': no Evolution ele é o dono da instância (o próprio
    bot), o que faria TODOS os clientes caírem no mesmo número."""

    remote = chave.get("remoteJid", "") or ""

    print("\n===== DEBUG NUMERO =====")
    print("remoteJid (cliente) =", remote)
    print("sender (ignorado)   =", data.get("sender"))
    print("========================\n")

    if remote.endswith("@g.us"):   # grupos não são atendidos
        return ""

    # Caso comum hoje: o Evolution já entrega o remoteJid como telefone
    # real (<numero>@s.whatsapp.net), mesmo quando addressingMode é "lid".
    # Confirmado em testes com teste/teste.py para dois números diferentes.
    if remote.endswith("@s.whatsapp.net"):
        return limpar_numero(remote)

    # ---- FALLBACK @lid (rede de segurança) ----
    # Mantido para o caso do Evolution voltar a entregar remoteJid como
    # "<id>@lid" puro (não-contato). Lógica original de telefone_resposta(),
    # já testada em produção: tenta achar o telefone real em outros campos
    # do payload antes de desistir.

    # 1. campos onde o telefone real costuma vir quando o remoteJid é @lid
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

    # 2. varre todo o payload por um telefone@s.whatsapp.net que NÃO seja o dono
    dono = limpar_numero(data.get("sender"))
    for achado in TELEFONE_RE.findall(json.dumps(data)):
        if achado != dono:
            return achado

    # 3. último recurso: usa o @lid cru mesmo (mantém o comportamento
    # antigo de extrair_numero(), que sempre retornava algo). A resposta
    # pode não ser entregue pelo Evolution neste caso.
    return limpar_numero(remote)


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

    print(payload_texto)

    with open(
        "ultimo_payload.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

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

        numero = extrair_telefone(data, payload, chave)
        remote_jid = chave.get("remoteJid", "")

        if "@g.us" in remote_jid:
            return {"status": "ignored_group"}

        # Aviso para detectar imediatamente se o Evolution voltar a mandar
        # @lid puro (regressão futura) - hoje remoteJid já vem como
        # <numero>@s.whatsapp.net mesmo com addressingMode "lid".
        if "@lid" in remote_jid:
            print(f"AVISO: remoteJid chegou como @lid ({remote_jid}) - usando fallback")

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

        # numero (identidade no banco/memória) e destino (para onde a
        # resposta é enviada) são hoje o MESMO valor - extrair_telefone()
        # garante isso. Mantidos como variáveis separadas para deixar claro
        # o papel de cada um caso voltem a divergir no futuro.
        destino = numero

        envio = requests.post(
            f"{EVOLUTION_URL}/message/sendText/{INSTANCE_NAME}",
            headers={"apikey": API_KEY},
            json={
                "number": destino,
                "text": resposta
            }
        )

        print("\nSTATUS ENVIO:")
        print(envio.status_code)
        print(envio.text)

        return {"status": "ok"}

    except Exception as erro:

        print("\nERRO:")
        traceback.print_exc()

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