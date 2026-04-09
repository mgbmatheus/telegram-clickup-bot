"""
Servidor Webhook Telegram → Claude (IA) → ClickUp
Com Transcrição Inteligente de Áudio
"""

import os
import json
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import base64
from io import BytesIO

app = Flask(__name__)

# ==================== CONFIGURAÇÕES ====================
TELEGRAM_TOKEN = "8070425563:AAHohccqjyZ9nBTiJ4OtczjHo6-OKRobYjg"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ClickUp
CLICKUP_TOKEN = os.environ.get("CLICKUP_TOKEN", "")
CLICKUP_WORKSPACE_ID = "9011864477"
CLICKUP_LIST_ID = "901113530854"
CLICKUP_API = "https://api.clickup.com/api/v2"

# Claude API
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"

# OpenAI (para Whisper)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"

# Webhook URL
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

# ==================== ROTAS ====================

@app.route("/", methods=["GET"])
def health():
    """Verificar se o servidor está vivo"""
    return jsonify({
        "status": "🟢 OK",
        "service": "Telegram → Claude → ClickUp (Com IA Avançada)",
        "timestamp": datetime.now().isoformat(),
        "webhook_url": f"{WEBHOOK_URL}/webhook"
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recebe updates do Telegram"""
    try:
        data = request.get_json()
        
        if not data or "message" not in data:
            return jsonify({"ok": True})
        
        message = data["message"]
        chat_id = message.get("chat", {}).get("id")
        user_name = message.get("from", {}).get("first_name", "Usuário")
        
        if not chat_id:
            return jsonify({"ok": True})
        
        # Processa diferentes tipos de mensagem
        task_data = None
        
        if "text" in message:
            texto = message["text"]
            print(f"📝 [{user_name}] Texto: {texto}")
            
            # Processa texto com Claude para melhor compreensão
            task_data = process_with_claude(texto, "text")
        
        elif "voice" in message:
            print(f"🎤 [{user_name}] Áudio de voz")
            send_message(chat_id, "🎤 Processando áudio... (aguarde alguns segundos)")
            
            # Baixa e transcreve o áudio
            audio_file_id = message["voice"]["file_id"]
            transcription = transcribe_telegram_audio(audio_file_id)
            
            if transcription:
                print(f"📝 Transcrição: {transcription}")
                # Processa transcrição com Claude
                task_data = process_with_claude(transcription, "voice")
            else:
                send_message(chat_id, "❌ Erro ao transcrever áudio. Tente enviar texto!")
        
        elif "audio" in message:
            print(f"🎵 [{user_name}] Arquivo de áudio")
            send_message(chat_id, "🎵 Processando arquivo de áudio...")
            
            audio_file_id = message["audio"]["file_id"]
            transcription = transcribe_telegram_audio(audio_file_id)
            
            if transcription:
                task_data = process_with_claude(transcription, "audio")
            else:
                send_message(chat_id, "❌ Erro ao transcrever áudio.")
        
        # Se conseguiu extrair tarefa
        if task_data:
            try:
                task_id = create_clickup_task(task_data)
                
                response_text = f"✅ Tarefa criada com sucesso!\n\n📌 {task_data['name']}"
                if task_data.get("due_date"):
                    response_text += f"\n⏰ Prazo: {task_data['due_date']}"
                if task_data.get("priority"):
                    priority_emoji = {"urgent": "🔴", "high": "🟠", "normal": "🟡", "low": "🟢"}.get(task_data["priority"], "")
                    response_text += f"\n{priority_emoji} Prioridade: {task_data['priority'].upper()}"
                
                send_message(chat_id, response_text)
                print(f"✅ Tarefa criada no ClickUp: {task_id}")
            
            except Exception as e:
                print(f"❌ Erro ao criar tarefa: {str(e)}")
                send_message(chat_id, f"❌ Erro ao criar tarefa: {str(e)}")
        
        return jsonify({"ok": True})
    
    except Exception as e:
        print(f"❌ Erro no webhook: {str(e)}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/setup_webhook", methods=["GET"])
def setup_webhook():
    """Ativa o webhook no Telegram"""
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        url = f"{TELEGRAM_API}/setWebhook"
        
        response = requests.post(url, json={"url": webhook_url})
        data = response.json()
        
        print(f"🔗 Webhook configurado: {webhook_url}")
        return jsonify(data)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_webhook_info", methods=["GET"])
def get_webhook_info():
    """Obtém informações do webhook"""
    try:
        url = f"{TELEGRAM_API}/getWebhookInfo"
        response = requests.get(url)
        return jsonify(response.json())
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== FUNÇÕES ====================

def transcribe_telegram_audio(file_id):
    """Transcreve áudio do Telegram usando Whisper (OpenAI)"""
    try:
        if not OPENAI_API_KEY:
            print("⚠️ OpenAI API key não configurada!")
            return None
        
        # Obtém o arquivo de áudio do Telegram
        file_info_url = f"{TELEGRAM_API}/getFile"
        response = requests.post(file_info_url, data={"file_id": file_id})
        file_info = response.json()
        
        if not file_info.get("ok"):
            print("Erro ao obter arquivo do Telegram")
            return None
        
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        
        # Baixa o arquivo
        audio_response = requests.get(file_url)
        audio_file = BytesIO(audio_response.content)
        audio_file.name = "audio.ogg"
        
        # Envia para Whisper (OpenAI)
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        
        files = {
            "file": ("audio.ogg", audio_file, "audio/ogg"),
            "model": (None, "whisper-1")
        }
        
        whisper_response = requests.post(WHISPER_URL, headers=headers, files=files)
        
        if whisper_response.status_code == 200:
            transcription = whisper_response.json().get("text", "")
            print(f"✅ Áudio transcrito com sucesso: {transcription}")
            return transcription
        else:
            print(f"Erro Whisper: {whisper_response.text}")
            return None
    
    except Exception as e:
        print(f"Erro ao transcrever áudio: {str(e)}")
        return None

def process_with_claude(texto, source_type="text"):
    """Processa o texto com Claude para extrair dados da tarefa"""
    try:
        if not CLAUDE_API_KEY:
            print("⚠️ Claude API key não configurada!")
            return parse_message_simple(texto)
        
        # Prepara o prompt para Claude
        prompt = f"""
Você é um assistente de gerenciamento de tarefas. Analise a seguinte mensagem e extraia as informações da tarefa.

Mensagem (tipo: {source_type}): "{texto}"

Retorne um JSON com os seguintes campos:
- name: Nome/descrição da tarefa (máximo 100 caracteres, sem emojis no início)
- due_date: Data de vencimento em formato YYYY-MM-DD (extraia de "hoje", "amanhã", "próxima segunda", etc. ou deixe null)
- priority: Prioridade ('urgent', 'high', 'normal', 'low' - baseado em palavras como "urgente", "importante", etc.)
- description: Descrição detalhada (máximo 200 caracteres)

Seja inteligente na interpretação. Se o usuário fala "cotar Enscape", entenda como "Cotar Enscape (hardware/software)".

Retorne APENAS o JSON, sem markdown.
"""
        
        response = requests.post(
            CLAUDE_API_URL,
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-opus-4-20250805",
                "max_tokens": 500,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result["content"][0]["text"]
            
            # Parse JSON response
            task_data = json.loads(content)
            
            # Adiciona emoji ao nome se não tiver
            if task_data.get("name") and not has_emoji(task_data["name"]):
                task_data["name"] = "📋 " + task_data["name"]
            
            print(f"✅ Claude processou: {task_data}")
            return task_data
        else:
            print(f"Erro Claude: {response.text}")
            return parse_message_simple(texto)
    
    except Exception as e:
        print(f"Erro ao processar com Claude: {str(e)}")
        return parse_message_simple(texto)

def parse_message_simple(texto):
    """Fallback: Parse simples da mensagem"""
    if not texto or len(texto.strip()) == 0:
        return None
    
    task_data = {
        "name": texto.strip(),
        "due_date": None,
        "priority": None,
        "description": ""
    }
    
    texto_lower = texto.lower()
    
    if any(word in texto_lower for word in ["urgente", "urgencia", "asap"]):
        task_data["priority"] = "urgent"
    elif any(word in texto_lower for word in ["importante", "alta", "high"]):
        task_data["priority"] = "high"
    
    if any(word in texto_lower for word in ["hoje", "today"]):
        task_data["due_date"] = get_today_date()
    elif any(word in texto_lower for word in ["amanhã", "tomorrow"]):
        task_data["due_date"] = get_tomorrow_date()
    elif any(word in texto_lower for word in ["próxima segunda", "segunda", "monday"]):
        task_data["due_date"] = get_next_monday()
    
    if not has_emoji(task_data["name"]):
        task_data["name"] = "📋 " + task_data["name"]
    
    return task_data

def has_emoji(text):
    """Verifica se texto tem emoji"""
    return any(ord(char) > 127 for char in text)

def get_today_date():
    """Retorna data de hoje em YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")

def get_tomorrow_date():
    """Retorna data de amanhã em YYYY-MM-DD"""
    tomorrow = datetime.now() + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")

def get_next_monday():
    """Retorna próxima segunda-feira"""
    today = datetime.now()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_monday = today + timedelta(days=days_ahead)
    return next_monday.strftime("%Y-%m-%d")

def send_message(chat_id, text):
    """Envia mensagem no Telegram"""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=data)
        return response.json()
    except Exception as e:
        print(f"❌ Erro ao enviar mensagem: {str(e)}")
        return None

def create_clickup_task(task_data):
    """Cria tarefa no ClickUp"""
    if not CLICKUP_TOKEN:
        raise Exception("❌ Token ClickUp não configurado!")
    
    # Remove "Bearer" se foi adicionado
    token = CLICKUP_TOKEN.replace("Bearer ", "").strip()
    
    url = f"{CLICKUP_API}/list/{CLICKUP_LIST_ID}/task"
    
    payload = {
        "name": task_data["name"],
        "description": task_data.get("description", ""),
    }
    
    if task_data.get("priority") == "urgent":
        payload["priority"] = 1
    elif task_data.get("priority") == "high":
        payload["priority"] = 2
    
    if task_data.get("due_date"):
        due_date_obj = datetime.strptime(task_data["due_date"], "%Y-%m-%d")
        payload["due_date"] = int(due_date_obj.timestamp() * 1000)
    
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code != 200:
        error_data = response.json()
        raise Exception(f"Erro ClickUp: {error_data.get('err', 'Desconhecido')}")
    
    task = response.json()
    return task.get("id")

# ==================== STARTUP ====================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    print("""
╔════════════════════════════════════════════════════════════╗
║    🤖 AUTOMAÇÃO COM IA AVANÇADA                           ║
║  Telegram → Claude (IA) → ClickUp                         ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  ✨ Transcrição Inteligente (Whisper)                     ║
║  ✨ Análise com Claude (compreensão)                      ║
║  ✨ Tarefas Precisas no ClickUp                           ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
""")
    
    app.run(host="0.0.0.0", port=port, debug=False)
