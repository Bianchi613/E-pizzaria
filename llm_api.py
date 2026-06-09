import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv


load_dotenv()


API_BASE_URL = os.getenv("CHAT_API_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
API_KEY = os.getenv("CHAT_API_KEY", os.getenv("OPENAI_API_KEY", ""))
API_MODEL = os.getenv("CHAT_API_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
API_TIMEOUT = int(os.getenv("CHAT_API_TIMEOUT", 120))
API_MAX_TOKENS = int(os.getenv("CHAT_API_MAX_TOKENS", os.getenv("OLLAMA_NUM_PREDICT", 1200)))
API_TEMPERATURE = float(os.getenv("CHAT_API_TEMPERATURE", 0.75))
API_TOP_P = float(os.getenv("CHAT_API_TOP_P", 0.9))


def generate_chat_response(messages):
    if not API_KEY:
        raise RuntimeError(
            "Defina CHAT_API_KEY ou OPENAI_API_KEY no .env para usar LLM_PROVIDER=api."
        )

    payload = {
        "model": API_MODEL,
        "messages": messages,
        "temperature": API_TEMPERATURE,
        "top_p": API_TOP_P,
        "max_tokens": API_MAX_TOKENS,
    }

    request = urllib.request.Request(
        f"{API_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro da API ({error.code}): {body}") from error
    except (urllib.error.URLError, ConnectionResetError, TimeoutError) as error:
        raise RuntimeError(f"Erro ao conectar na API: {error}. Verifique se a API está disponível e se sua chave é válida.") from error

    return data["choices"][0]["message"]["content"]


def _headers():
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    referer = os.getenv("CHAT_API_HTTP_REFERER")
    title = os.getenv("CHAT_API_APP_TITLE")

    if referer:
        headers["HTTP-Referer"] = referer

    if title:
        headers["X-Title"] = title

    return headers
