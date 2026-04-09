"""
Servidor Webhook Telegram -> AssemblyAI (Transcricao) -> Claude -> ClickUp
VERSAO FINAL REVISADA
"""

import os
import json
import re
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import time
import threading

app = Flask(__name__)

# ==================== CONFIGURACOES ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

CLICKUP_TOKEN = os.environ.get("CLICKUP_TOKEN", "")
CLICKUP_LIST_ID = os.environ.get("CLICKUP_LIST_ID", "901113530854")
CLICKUP_API = "https://api.clickup.com/api/v2"

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")
ASSEMBLYAI_URL = "https://api.assemblyai.com/v2"

WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

DIAS_SEMANA = {
    0: "segunda-feira",
    1: "terca-feira",
    2: "quarta-feira",
    3: "quinta-feira",
    4: "sexta-feira",
    5: "sabado",
    6: "domingo",
}


# ==================== ROTAS ====================

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "OK",
        "service": "Telegram > AssemblyAI > Claude > ClickUp",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "telegram": "ok" if TELEGRAM_TOKEN else "missing",
            "clickup": "ok" if CLICKUP_TOKEN else "missing",
            "claude": "ok" if CLAUDE_API_KEY else "missing",
            "assemblyai": "ok" if ASSEMBLYAI_API_KEY else "missing",
            "model": CLAUDE_MODEL,
            "clickup_list": CLICKUP_LIST_ID,
        }
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()

        if not data or "message" not in data:
            return jsonify({"ok": True})

        message = data["message"]
        chat_id = message.get("chat", {}).get("id")
        user_name = message.get("from", {}).get("first_name", "Usuario")

        if not chat_id:
            return jsonify({"ok": True})

        thread = threading.Thread(
            target=process_message,
            args=(message, chat_id, user_name),
            daemon=True,
        )
        thread.start()

        return jsonify({"ok": True})

    except Exception as e:
        print(f"[ERRO] webhook: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/setup_webhook", methods=["GET"])
def setup_webhook():
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        response = requests.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": webhook_url, "allowed_updates": ["message"]},
            timeout=10,
        )
        result = response.json()
        print(f"[INFO] Webhook setup: {result}")
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== PROCESSAMENTO ====================

def process_message(message, chat_id, user_name):
    try:
        if "text" in message:
            texto = message["text"].strip()

            if texto.startswith("/"):
                handle_command(texto, chat_id)
                return

            if len(texto) < 3:
                return

            print(f"[TEXT] [{user_name}] {texto}")
            task_data = process_with_claude(texto)

        elif "voice" in message or "audio" in message:
            print(f"[AUDIO] [{user_name}] Audio recebido")
            send_message(chat_id, "Transcrevendo audio... aguarde")

            file_id = (
                message.get("voice", {}).get("file_id")
                or message.get("audio", {}).get("file_id")
            )

            if not file_id:
                send_message(chat_id, "Erro: nao consegui obter o arquivo de audio.")
                return

            transcription = transcribe_with_assemblyai(file_id)

            if not transcription or not transcription.strip():
                send_message(
                    chat_id,
                    "Nao consegui transcrever o audio. Tente novamente ou envie como texto.",
                )
                return

            print(f"[TRANSCRICAO] {transcription}")
            send_message(chat_id, f'Transcricao: "{transcription}"')
            task_data = process_with_claude(transcription)

        else:
            return

        if not task_data:
            send_message(chat_id, "Nao consegui interpretar a mensagem como tarefa.")
            return

        task_id, task_url = create_clickup_task(task_data)

        lines = ["Tarefa criada no ClickUp!", ""]
        lines.append(f"Nome: {task_data['name']}")

        if task_data.get("description"):
            desc = task_data["description"]
            if len(desc) > 120:
                desc = desc[:120] + "..."
            lines.append(f"Descricao: {desc}")

        if task_data.get("due_date"):
            try:
                dt = datetime.strptime(task_data["due_date"], "%Y-%m-%d")
                lines.append(f"Prazo: {dt.strftime('%d/%m/%Y')}")
            except ValueError:
                lines.append(f"Prazo: {task_data['due_date']}")

        if task_data.get("priority"):
            labels = {
                "urgent": "URGENTE",
                "high": "ALTA",
                "normal": "NORMAL",
                "low": "BAIXA",
            }
            lines.append(f"Prioridade: {labels.get(task_data['priority'], task_data['priority'])}")

        if task_url:
            lines.append(f"\nLink: {task_url}")

        send_message(chat_id, "\n".join(lines))
        print(f"[OK] Tarefa criada: {task_id}")

    except Exception as e:
        print(f"[ERRO] process_message: {e}")
        send_message(chat_id, f"Erro ao criar tarefa: {str(e)}")


def handle_command(text, chat_id):
    cmd = text.lower().split()[0]
    if cmd == "/start":
        send_message(
            chat_id,
            "Ola! Eu crio tarefas no ClickUp.\n\n"
            "Envie um texto ou um audio descrevendo a tarefa.\n\n"
            "Exemplos:\n"
            '- "Revisar contrato ate sexta, urgente"\n'
            '- "Criar landing page para o produto novo"\n'
            "- Envie um audio descrevendo a tarefa",
        )
    elif cmd == "/help":
        send_message(
            chat_id,
            "Como usar:\n\n"
            "1. Envie texto ou audio com a tarefa\n"
            "2. Eu interpreto nome, prazo e prioridade\n"
            "3. Crio automaticamente no ClickUp\n\n"
            "Dicas:\n"
            '- Mencione datas: "ate amanha", "para sexta"\n'
            '- Mencione prioridade: "urgente", "importante"\n'
            "- Seja especifico na descricao",
        )
    else:
        send_message(chat_id, "Comando nao reconhecido. Use /start ou /help")


# ==================== TRANSCRICAO ====================

def transcribe_with_assemblyai(file_id):
    try:
        if not ASSEMBLYAI_API_KEY:
            print("[ERRO] ASSEMBLYAI_API_KEY nao configurada")
            return None

        resp = requests.post(
            f"{TELEGRAM_API}/getFile",
            json={"file_id": file_id},
            timeout=10,
        )
        file_info = resp.json()

        if not file_info.get("ok"):
            print(f"[ERRO] getFile: {file_info}")
            return None

        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"

        print("[INFO] Baixando audio do Telegram...")
        audio_resp = requests.get(file_url, timeout=30)
        if audio_resp.status_code != 200:
            print(f"[ERRO] Download audio: HTTP {audio_resp.status_code}")
            return None

        audio_bytes = audio_resp.content
        if len(audio_bytes) == 0:
            print("[ERRO] Audio vazio")
            return None

        print(f"[INFO] Audio baixado: {len(audio_bytes)} bytes")

        print("[INFO] Upload para AssemblyAI...")
        aai_headers = {"Authorization": ASSEMBLYAI_API_KEY}

        upload_resp = requests.post(
            f"{ASSEMBLYAI_URL}/upload",
            headers=aai_headers,
            data=audio_bytes,
            timeout=60,
        )

        if upload_resp.status_code != 200:
            print(f"[ERRO] Upload AssemblyAI: {upload_resp.status_code} {upload_resp.text}")
            return None

        audio_url = upload_resp.json().get("upload_url")
        if not audio_url:
            print("[ERRO] upload_url nao retornado")
            return None

        print("[INFO] Upload OK")

        print("[INFO] Submetendo transcricao...")
        transcript_resp = requests.post(
            f"{ASSEMBLYAI_URL}/transcript",
            headers=aai_headers,
            json={"audio_url": audio_url, "language_code": "pt"},
            timeout=30,
        )

        if transcript_resp.status_code != 200:
            print(f"[ERRO] Submeter transcricao: {transcript_resp.text}")
            return None

        transcript_id = transcript_resp.json().get("id")
        if not transcript_id:
            print("[ERRO] transcript id nao retornado")
            return None

        print(f"[INFO] Transcricao ID: {transcript_id}")

        print("[INFO] Aguardando transcricao...")
        for attempt in range(60):
            result_resp = requests.get(
                f"{ASSEMBLYAI_URL}/transcript/{transcript_id}",
                headers=aai_headers,
                timeout=10,
            )

            if result_resp.status_code != 200:
                print(f"[WARN] Polling HTTP {result_resp.status_code}")
                time.sleep(2)
                continue

            result = result_resp.json()
            status = result.get("status")

            if status == "completed":
                text = result.get("text", "").strip()
                print(f"[OK] Transcricao completa: {len(text)} chars")
                return text if text else None

            elif status == "error":
                error_msg = result.get("error", "desconhecido")
                print(f"[ERRO] Transcricao falhou: {error_msg}")
                return None

            time.sleep(2)

        print("[ERRO] Timeout na transcricao (2 min)")
        return None

    except requests.exceptions.Timeout:
        print("[ERRO] Timeout na requisicao HTTP")
        return None
    except Exception as e:
        print(f"[ERRO] transcribe_with_assemblyai: {e}")
        return None


# ==================== CLAUDE ====================

def extract_json(text):
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block:
        text = code_block.group(1)

    text = text.strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")

    if brace_start == -1 or brace_end == -1 or brace_end <= brace_start:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    text = text[brace_start : brace_end + 1]
    return json.loads(text)


def process_with_claude(texto):
    try:
        if not CLAUDE_API_KEY:
            print("[WARN] CLAUDE_API_KEY ausente, usando parse simples")
            return parse_simple(texto)

        agora = datetime.now()
        hoje = agora.strftime("%Y-%m-%d")
        dia_semana = DIAS_SEMANA.get(agora.weekday(), "")

        prompt = f"""Voce e um assistente que extrai tarefas de mensagens em portugues.
Data de hoje: {hoje} ({dia_semana}).

Analise a mensagem abaixo e extraia as informacoes da tarefa.

Mensagem: "{texto}"

Retorne APENAS um objeto JSON (sem markdown, sem explicacao, sem texto extra) com:
{{
  "name": "nome curto e claro da tarefa (max 80 caracteres)",
  "description": "descricao detalhada se houver contexto extra, senao string vazia",
  "due_date": "YYYY-MM-DD se mencionou prazo, senao null",
  "priority": "urgent ou high ou normal ou low"
}}

Regras para datas:
- "hoje" = {hoje}
- "amanha" = proximo dia
- "sexta", "segunda", etc = proxima ocorrencia a partir de hoje
- "semana que vem" = proxima segunda-feira
- Se nao mencionou data = null

Regras para prioridade:
- "urgente", "asap", "imediato", "agora" = urgent
- "importante", "prioridade alta" = high
- Sem indicacao de urgencia = normal
- "baixa prioridade", "quando puder" = low

Retorne SOMENTE o JSON, nada mais."""

        response = requests.post(
            CLAUDE_API_URL,
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )

        if response.status_code != 200:
            print(f"[WARN] Claude HTTP {response.status_code}: {response.text[:200]}")
            return parse_simple(texto)

        result = response.json()

        content_blocks = result.get("content", [])
        if not content_blocks:
            print("[WARN] Claude retornou content vazio")
            return parse_simple(texto)

        content = content_blocks[0].get("text", "")
        if not content.strip():
            print("[WARN] Claude retornou texto vazio")
            return parse_simple(texto)

        task_data = extract_json(content)

        if not isinstance(task_data, dict):
            print("[WARN] Claude nao retornou um dict")
            return parse_simple(texto)

        if not task_data.get("name"):
            task_data["name"] = texto[:80]

        if len(task_data["name"]) > 100:
            task_data["name"] = task_data["name"][:97] + "..."

        task_data.setdefault("description", "")
        task_data.setdefault("due_date", None)
        task_data.setdefault("priority", "normal")

        valid_priorities = {"urgent", "high", "normal", "low"}
        if task_data.get("priority") not in valid_priorities:
            task_data["priority"] = "normal"

        if task_data.get("due_date"):
            try:
                parsed_date = datetime.strptime(task_data["due_date"], "%Y-%m-%d")
                if parsed_date.date() < datetime.now().date():
                    print(f"[WARN] Data no passado ignorada: {task_data['due_date']}")
                    task_data["due_date"] = None
            except ValueError:
                print(f"[WARN] Data invalida: {task_data['due_date']}")
                task_data["due_date"] = None

        return task_data

    except json.JSONDecodeError as e:
        print(f"[WARN] JSON parse error: {e}")
        return parse_simple(texto)
    except requests.exceptions.Timeout:
        print("[WARN] Claude timeout")
        return parse_simple(texto)
    except Exception as e:
        print(f"[WARN] process_with_claude: {e}")
        return parse_simple(texto)


def parse_simple(texto):
    if not texto or not texto.strip():
        return None

    texto = texto.strip()
    task_data = {
        "name": texto[:80],
        "description": texto if len(texto) > 80 else "",
        "due_date": None,
        "priority": "normal",
    }

    texto_lower = texto.lower()

    if any(w in texto_lower for w in ["urgente", "asap", "imediato", "agora"]):
        task_data["priority"] = "urgent"
    elif any(w in texto_lower for w in ["importante", "alta prioridade", "prioridade alta"]):
        task_data["priority"] = "high"
    elif any(w in texto_lower for w in ["baixa prioridade", "quando puder"]):
        task_data["priority"] = "low"

    hoje = datetime.now()
    if "hoje" in texto_lower:
        task_data["due_date"] = hoje.strftime("%Y-%m-%d")
    elif "amanha" in texto_lower or "amanhã" in texto_lower:
        task_data["due_date"] = (hoje + timedelta(days=1)).strftime("%Y-%m-%d")

    return task_data


# ==================== TELEGRAM ====================

def send_message(chat_id, text):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        print(f"[WARN] send_message: {e}")


# ==================== CLICKUP ====================

PRIORITY_MAP = {
    "urgent": 1,
    "high": 2,
    "normal": 3,
    "low": 4,
}


def create_clickup_task(task_data):
    if not CLICKUP_TOKEN:
        raise Exception("CLICKUP_TOKEN nao configurado!")

    token = CLICKUP_TOKEN.replace("Bearer ", "").strip()
    url = f"{CLICKUP_API}/list/{CLICKUP_LIST_ID}/task"

    payload = {
        "name": task_data.get("name", "Tarefa sem titulo"),
        "description": task_data.get("description", ""),
    }

    priority = task_data.get("priority")
    if priority in PRIORITY_MAP:
        payload["priority"] = PRIORITY_MAP[priority]

    if task_data.get("due_date"):
        try:
            due_dt = datetime.strptime(task_data["due_date"], "%Y-%m-%d")
            due_dt = due_dt.replace(hour=23, minute=59, second=59)
            payload["due_date"] = int(due_dt.timestamp() * 1000)
        except ValueError:
            pass

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }

    response = requests.post(url, json=payload, headers=headers, timeout=15)

    if response.status_code != 200:
        try:
            error_data = response.json()
            err_msg = error_data.get("err", error_data.get("error", "Desconhecido"))
        except Exception:
            err_msg = f"HTTP {response.status_code}"
        raise Exception(f"ClickUp API: {err_msg}")

    result = response.json()
    task_id = result.get("id", "")
    task_url = result.get("url", "")

    return task_id, task_url


# ==================== MAIN ====================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Servidor iniciando na porta {port}")
    print(f"Modelo Claude: {CLAUDE_MODEL}")
    print(f"ClickUp List: {CLICKUP_LIST_ID}")
    app.run(host="0.0.0.0", port=port, debug=False)
```
