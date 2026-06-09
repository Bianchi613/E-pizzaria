import requests

r = requests.post(
    "http://localhost:8080/message/sendText/pizzaria2",
    headers={
        "apikey": "34A88695-0670-40D3-8EB5-BAEAAF4AF2C4"
    },
    json={
        "number": "188102505140309@lid",
        "text": "teste"
    }
)

print(r.status_code)
print(r.text)