import os
import uuid
import hmac
import hashlib
import base64
import time
import requests
from datetime import datetime, timedelta


# ============================================================
# CONFIGURAÇÕES
# ============================================================

BASE_URL = "https://api.apsystemsema.com:9282"

APP_ID = os.getenv("APSYSTEMS_APP_ID")
APP_SECRET = os.getenv("APSYSTEMS_APP_SECRET")
SYSTEM_ID = os.getenv("APSYSTEMS_SID")

WAHA_URL = os.getenv(
    "WAHA_URL",
    "https://waha-melo-waha.w4t5db.easypanel.host"
).rstrip("/")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "").strip()
WAHA_SESSION = os.getenv("WAHA_SESSION", "MeloRobo")
WAHA_PHONE = os.getenv("WAHA_PHONE", "5534999214369")

SIGNATURE_METHOD = "HmacSHA256"


# ============================================================
# VALIDAR CREDENCIAIS
# ============================================================

if not APP_ID:
    raise RuntimeError(
        "APSYSTEMS_APP_ID não configurado.\n\n"
        'Execute:\nexport APSYSTEMS_APP_ID="SEU_APP_ID"'
    )

if not APP_SECRET:
    raise RuntimeError(
        "APSYSTEMS_APP_SECRET não configurado.\n\n"
        'Execute:\nexport APSYSTEMS_APP_SECRET="SEU_APP_SECRET"'
    )

if not SYSTEM_ID:
    raise RuntimeError(
        "APSYSTEMS_SID não configurado.\n\n"
        'Execute:\nexport APSYSTEMS_SID="SEU_SID"'
    )

if SYSTEM_ID == APP_ID:
    raise RuntimeError(
        "APSYSTEMS_SID está igual a APSYSTEMS_APP_ID.\n\n"
        "O SID é o identificador do sistema no portal EMA, não o App ID.\n"
        'Execute:\nexport APSYSTEMS_SID="SID_DO_SISTEMA"'
    )


# ============================================================
# GERAR ASSINATURA
# ============================================================

def gerar_headers(method, request_path):

    timestamp = str(int(time.time() * 1000))

    # UUID de 32 caracteres
    nonce = uuid.uuid4().hex

    # A APsystems chama de RequestPath o último componente da URL,
    # e não o caminho completo. Exemplo:
    # /user/api/v2/systems/energy/ABC123 -> ABC123
    request_name = request_path.rstrip("/").rsplit("/", 1)[-1]

    # Formato definido no manual APsystems:
    #
    # timestamp/nonce/appId/requestPath/method/signatureMethod

    string_to_sign = (
        f"{timestamp}/"
        f"{nonce}/"
        f"{APP_ID}/"
        f"{request_name}/"
        f"{method.upper()}/"
        f"{SIGNATURE_METHOD}"
    )

    digest = hmac.new(
        APP_SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256
    ).digest()

    signature = base64.b64encode(digest).decode("utf-8")

    return {
        "X-CA-AppId": APP_ID,
        "X-CA-Timestamp": timestamp,
        "X-CA-Nonce": nonce,
        "X-CA-Signature-Method": SIGNATURE_METHOD,
        "X-CA-Signature": signature,
        "Accept": "application/json"
    }


# ============================================================
# REQUISIÇÃO
# ============================================================

def requisicao(method, path, params=None, json_body=None):

    url = BASE_URL + path

    headers = gerar_headers(method, path)

    kwargs = {
        "method": method,
        "url": url,
        "headers": headers,
        "timeout": 30
    }

    # Só adicionamos parâmetros se realmente existirem.
    if params is not None:
        kwargs["params"] = params

    # Só adicionamos JSON se realmente existir.
    if json_body is not None:
        kwargs["json"] = json_body

    print("\n-------------------------------------------------------")
    print(f"→ {method.upper()} {url}")

    if params:
        print(f"Query params: {params}")

    response = requests.request(**kwargs)

    print(f"HTTP Status: {response.status_code}")

    # --------------------------------------------------------
    # Tentar interpretar resposta
    # --------------------------------------------------------

    try:

        dados = response.json()

    except ValueError:

        print("\n❌ A resposta da APsystems não é JSON.")
        print("\nResposta:")
        print(response.text[:2000])

        raise RuntimeError(
            f"Resposta HTTP inesperada: {response.status_code}"
        )

    print(f"Resposta API: {dados}")

    # --------------------------------------------------------
    # HTTP
    # --------------------------------------------------------

    if response.status_code != 200:

        raise RuntimeError(
            f"Erro HTTP {response.status_code}: {dados}"
        )

    # --------------------------------------------------------
    # Código interno APsystems
    # --------------------------------------------------------

    codigo = dados.get("code")

    if codigo != 0:

        erros = {

            1000: "Data exception",
            1001: "No data",

            2000: "Application account exception",
            2001: "Invalid application account",
            2002: "Application account not authorized",
            2003: "Application authorization expired",
            2004: "Application account has no permission",
            2005: "Application access limit exceeded",

            3000: "Access token exception",
            3001: "Missing access token",
            3002: "Unable to verify access token",
            3003: "Access token timeout",
            3004: "Refresh token timeout",

            4000: "Request parameter exception",
            4001: "Invalid request parameter",

            5000: "Internal server exception",
            6000: "Communication exception",

            7000: "Server access restriction",
            7001: "Server access limit exceeded",
            7002: "Too many requests",
            7003: "System busy"
        }

        descricao = erros.get(
            codigo,
            "Erro desconhecido"
        )

        complemento = ""

        if codigo == 2004:
            complemento = (
                " Verifique se APSYSTEMS_SID contém o SID do sistema "
                "no portal EMA (e não o App ID) e se esse sistema está "
                "liberado para a conta OpenAPI."
            )

        raise RuntimeError(
            f"APsystems retornou erro {codigo}: {descricao}."
            f"{complemento}"
        )

    return dados


# ============================================================
# LISTAR SISTEMAS
# ============================================================

def listar_sistemas():

    # A OpenAPI de usuário não oferece uma operação para descobrir
    # sistemas. O SID deve ser obtido no portal EMA e configurado na
    # variável de ambiente APSYSTEMS_SID.
    path = f"/user/api/v2/systems/details/{SYSTEM_ID}"

    resposta = requisicao(
        method="GET",
        path=path
    )

    sistema = resposta.get("data")

    if not isinstance(sistema, dict):
        raise RuntimeError(
            "A API não retornou os detalhes do sistema esperado."
        )

    return [sistema]


# ============================================================
# CONSULTAR ENERGIA DO MÊS
# ============================================================

def consultar_energia_mes(sid, ano, mes):

    path = f"/user/api/v2/systems/energy/{sid}"

    params = {
        "energy_level": "daily",
        "date_range": f"{ano:04d}-{mes:02d}"
    }

    resposta = requisicao(
        method="GET",
        path=path,
        params=params
    )

    return resposta.get("data", [])


# ============================================================
# CONSULTAR GERAÇÃO DE ONTEM
# ============================================================

def consultar_ontem(sid):

    ontem = datetime.now().date() - timedelta(days=1)

    print("\n=======================================================")
    print("⚡ CONSULTANDO GERAÇÃO")
    print("=======================================================")

    print(f"\nData desejada: {ontem:%d/%m/%Y}")

    valores = consultar_energia_mes(
        sid,
        ontem.year,
        ontem.month
    )

    indice = ontem.day - 1

    if indice >= len(valores):

        raise RuntimeError(
            "A API não retornou dados suficientes para "
            f"{ontem:%d/%m/%Y}."
        )

    valor = valores[indice]

    try:

        energia = float(valor)

    except (TypeError, ValueError):

        raise RuntimeError(
            f"Valor de energia inválido: {valor}"
        )

    return ontem, energia


# ============================================================
# STATUS DO SISTEMA
# ============================================================

def status_sistema(light):

    status = {
        1: "🟢 Normal",
        2: "🟡 Alerta em microinversor",
        3: "🔴 Problema de comunicação da ECU",
        4: "⚪ Sem dados"
    }

    return status.get(
        light,
        f"Desconhecido ({light})"
    )


# ============================================================
# ENVIAR RELATÓRIO PELO WHATSAPP (WAHA)
# ============================================================

def enviar_whatsapp(mensagem):

    if not WAHA_API_KEY:
        raise RuntimeError(
            "WAHA_API_KEY não configurada.\n\n"
            'Execute:\nexport WAHA_API_KEY="SUA_CHAVE_WAHA"'
        )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Api-Key": WAHA_API_KEY
    }

    print("\n=======================================================")
    print("📱 ENVIANDO RELATÓRIO PELO WHATSAPP")
    print("=======================================================")
    print(f"\nVerificando o número {WAHA_PHONE}...")

    try:
        response = requests.get(
            f"{WAHA_URL}/api/contacts/check-exists",
            params={
                "phone": WAHA_PHONE,
                "session": WAHA_SESSION
            },
            headers=headers,
            timeout=30
        )
    except requests.RequestException as erro:
        raise RuntimeError(
            f"Não foi possível conectar ao WAHA: {erro}"
        ) from erro

    if response.status_code == 403:
        # Chaves WAHA vinculadas a uma sessão podem ter permissão de
        # envio sem permissão de leitura. Nesse caso, não é possível
        # consultar o contato, mas ainda podemos enviar pelo chatId.
        chat_id = (
            WAHA_PHONE
            if "@" in WAHA_PHONE
            else f"{WAHA_PHONE}@c.us"
        )
        print(
            "A chave não permite consultar contatos (HTTP 403). "
            "Usando o Chat ID diretamente."
        )

    elif response.status_code != 200:
        if response.status_code == 401:
            raise RuntimeError(
                "O WAHA recusou a autenticação (HTTP 401). "
                "A variável WAHA_API_KEY não corresponde à chave "
                "configurada no servidor WAHA. Atualize a variável no "
                "terminal e execute o script novamente."
            )

        raise RuntimeError(
            "Erro ao verificar o número no WAHA "
            f"(HTTP {response.status_code}): {response.text[:500]}"
        )

    else:
        try:
            contato = response.json()
        except ValueError as erro:
            raise RuntimeError(
                f"O WAHA retornou uma resposta inválida: {response.text[:500]}"
            ) from erro

        if not contato.get("numberExists"):
            raise RuntimeError(
                f"O número {WAHA_PHONE} não foi encontrado no WhatsApp."
            )

        chat_id = contato.get("chatId")

        if not chat_id:
            raise RuntimeError(
                "O WAHA confirmou o número, mas não retornou o chatId."
            )

        print(f"Número encontrado. Chat ID: {chat_id}")

    print("Enviando mensagem...")

    try:
        response = requests.post(
            f"{WAHA_URL}/api/sendText",
            json={
                "chatId": chat_id,
                "text": mensagem,
                "session": WAHA_SESSION
            },
            headers=headers,
            timeout=30
        )
    except requests.RequestException as erro:
        raise RuntimeError(
            f"Não foi possível enviar a mensagem pelo WAHA: {erro}"
        ) from erro

    if response.status_code not in (200, 201):
        if response.status_code == 403:
            raise RuntimeError(
                "O WAHA recusou o envio (HTTP 403). A chave precisa ter "
                f"permissão 'send' para a sessão '{WAHA_SESSION}'."
            )

        raise RuntimeError(
            "Erro ao enviar mensagem pelo WAHA "
            f"(HTTP {response.status_code}): {response.text[:500]}"
        )

    print("✅ Relatório enviado pelo WhatsApp.")

    return response


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():

    print("=======================================================")
    print("☀️  APsystems OpenAPI")
    print("=======================================================")

    print(f"\nBuscando o sistema {SYSTEM_ID}...")

    # --------------------------------------------------------
    # DESCOBRIR SISTEMA
    # --------------------------------------------------------

    sistemas = listar_sistemas()

    if not sistemas:

        print("\n❌ Sistema não encontrado.")

        return

    print(
        "\n✅ Sistema encontrado."
    )

    # --------------------------------------------------------
    # MOSTRAR SISTEMAS
    # --------------------------------------------------------

    for numero, sistema in enumerate(
        sistemas,
        start=1
    ):

        print("\n-------------------------------------------------------")
        print(f"☀️ SISTEMA {numero}")
        print("-------------------------------------------------------")

        sid = sistema.get("sid")

        capacidade = sistema.get(
            "capacity",
            "N/D"
        )

        timezone = sistema.get(
            "timezone",
            "N/D"
        )

        ecu = sistema.get(
            "ecu",
            []
        )

        light = sistema.get("light")

        print(f"SID:        {sid}")
        print(f"Capacidade: {capacidade} kW")

        if ecu:

            print(
                f"ECU:        {', '.join(ecu)}"
            )

        else:

            print("ECU:        N/D")

        print(f"Timezone:   {timezone}")

        print(
            f"Status:     {status_sistema(light)}"
        )

    # --------------------------------------------------------
    # UTILIZAR PRIMEIRO SISTEMA
    # --------------------------------------------------------

    sistema = sistemas[0]

    sid = sistema.get("sid")

    if not sid:

        raise RuntimeError(
            "O sistema retornado não possui SID."
        )

    # --------------------------------------------------------
    # CONSULTAR ONTEM
    # --------------------------------------------------------

    data, energia = consultar_ontem(sid)

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    print("\n=======================================================")
    print("☀️ RELATÓRIO SOLAR")
    print("=======================================================")

    print(f"\n📅 Data:    {data:%d/%m/%Y}")
    print(f"⚡ Geração: {energia:.2f} kWh")

    mensagem = (
        "☀️ *RELATÓRIO SOLAR*\n\n"
        f"📅 Data: {data:%d/%m/%Y}\n"
        f"⚡ Geração: {energia:.2f} kWh\n"
        f"🏭 Capacidade instalada: {sistema.get('capacity', 'N/D')} kW\n"
        f"📊 Status: {status_sistema(sistema.get('light'))}\n"
        f"🔌 ECU: {', '.join(sistema.get('ecu', [])) or 'N/D'}"
    )

    enviar_whatsapp(mensagem)

    print("\n=======================================================")
    print("✅ Consulta concluída.")
    print("=======================================================")


# ============================================================
# EXECUTAR
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print("\n\nExecução cancelada.")

    except Exception as erro:

        print("\n=======================================================")
        print("❌ ERRO")
        print("=======================================================")

        print(f"\n{erro}")

        print("\n=======================================================")
