import os

import ollama
from dotenv import load_dotenv


load_dotenv()


MODEL_NAME = os.getenv("OLLAMA_MODEL", "nous-hermes")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", 8192))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", 1200))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", 0.75))
OLLAMA_TOP_P = float(os.getenv("OLLAMA_TOP_P", 0.9))


def generate_chat_response(messages):
    response = ollama.chat(
        model=MODEL_NAME,
        messages=messages,
        options={
            "temperature": OLLAMA_TEMPERATURE,
            "top_p": OLLAMA_TOP_P,
            "num_ctx": OLLAMA_NUM_CTX,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    )

    return response["message"]["content"]
