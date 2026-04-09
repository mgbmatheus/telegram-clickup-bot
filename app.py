"""
Servidor Webhook Telegram → AssemblyAI (Transcrição) → Claude → ClickUp
VERSÃO FINAL COM ASSEMBLYAI FUNCIONANDO 100%
"""

import os
import json
import requests
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from io import BytesIO
import time

app = Flask(__name__)

# ==================== CONFIGURAÇÕES ====================
TELEGRAM_TOKEN = "8070425563:AAHohccqjyZ9nBTiJ4OtczjHo6-OKRobYjg"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ClickUp
CLICKUP_TOKEN = os.environ.get("CLICKUP_TOKEN", "")
CLICKUP_LIST_ID = "901113530854"
CLICKUP_API = "https://api.clickup.com/api/v2"

# Claude API
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"

# AssemblyAI
ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")
ASSEMBLYAI_URL = "https://api.assemblyai.com/v2"

# Webhook URL
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

# ==================== ROTAS ====================

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "🟢 OK",
        "service": "Telegram → AssemblyAI → Claude → ClickUp",
        "timestamp": datetime.now().isoformat()
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
        
        # Processa texto
        if "text" in message:
            texto = message["text"]
            print(f"📝 [{user_name}] Texto: {texto}")
            task_data = process_with_claude(texto, "text")
        
        # Processa áudio
        elif "voice" in message or "audio" in message:
            print(f"🎤 [{user_name}] Áudio")
            send_message(chat_id, "🎤 Transcrevendo áudio com AssemblyAI... aguarde...")
            
            # Obtém arquivo
            file_id = message.get("voice", {}).get("file_id") or message.get("audio", {}).get("file_id")
            
            # Transcreve com AssemblyAI
            transcription = transcribe_with_assemblyai(file_id, chat_id)
            
            if transcription and transcription.strip():
                print(f"✅ Transcrição: {transcription}")
                task_data = process_with_claude(transcription, "voice")
            else:
                send_message(chat_id, "❌ Erro ao transcrever áudio. Tente novamente!")
                return jsonify({"ok": True})
        else:
            return jsonify({"ok": True})
        
        # Cria tarefa
        if task_data:
            try:
                task_id = create_clickup_task(task_data)
                
                response_text = f"✅ Tarefa criada!\n\n📌 {task_data['name']}"
                if task_data.get("due_date"):
                    response_text += f"\n⏰ Prazo: {task_data['due_date']}"
                if task_data.get("priority"):
                    priority_emoji = {"urgent": "🔴", "high": "🟠"}.get(task_data["priority"], "")
                    response_text += f"\n{priority_emoji} Prioridade: {task_data['priority'].upper()}"
                
                send_message(chat_id, response_text)
                print(f"✅ Tarefa criada: {task_id}")
            
            except Exception as e:
                print(f"❌ Erro: {str(e)}")
                send_message(chat_id, f"❌ Erro: {str(e)}")
        
        return jsonify({"ok": True})
    
    except Exception as e:
        print(f"❌ Erro no webhook: {str(e)}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/setup_webhook", methods=["GET"])
def setup_webhook():
    try:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        url = f"{TELEGRAM_API}/setWebhook"
        response = requests.post(url, json={"url": webhook_url})
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== FUNÇÕES ====================

def transcribe_with_assemblyai(file_id, chat_id):
    """Transcreve áudio com AssemblyAI"""
    try:
        if not ASSEMBLYAI_API_KEY:
            print("❌ AssemblyAI API key não configurada!")
            return None
        
        # Obtém arquivo do Telegram
        file_info_url = f"{TELEGRAM_API}/getFile"
        response = requests.post(file_info_url, data={"file_id": file_id})
        file_info = response.json()
        
        if not file_info.get("ok"):
            print("Erro ao obter arquivo do Telegram")
            return None
        
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        
        # Baixa o arquivo de áudio
        print(f"📥 Baixando áudio de: {file_url}")
        audio_response = requests.get(file_url)
        
        # Upload para AssemblyAI
        print("📤 Enviando para AssemblyAI...")
        headers = {"Authorization": ASSEMBLYAI_API_KEY}
        
        upload_response = requests.post(
            f"{ASSEMBLYAI_URL}/upload",
            headers=headers,
            data=audio_response.content
        )
        
        if upload_response.status_code != 200:
            print(f"Erro ao fazer upload: {upload_response.text}")
            return None
        
        audio_url = upload_response.json()["upload_url"]
        print(f"✅ Upload concluído: {audio_url}")
        
        # Submete transcrição
        print("🎙️ Submetendo para transcrição...")
        transcription_response = requests.post(
            f"{ASSEMBLYAI_URL}/transcript",
            headers=headers,
            json={"audio_url": audio_url, "language_code": "pt"}
        )
        
        if transcription_response.status_code != 200:
            print(f"Erro ao submeter: {transcription_response.text}")
            return None
        
        transcript_id = transcription_response.json()["id"]
        print(f"📝 ID da transcrição: {transcript_id}")
        
        # Aguarda transcrição
        print("⏳ Aguardando transcrição...")
        max_attempts = 60  # 2 minutos
        attempt = 0
        
        while attempt < max_attempts:
            result_response = requests.get(
                f"{ASSEMBLYAI_URL}/transcript/{transcript_id}",
                headers=headers
            )
            
            result = result_response.json()
            status = result.get("status")
            
            print(f"Status: {status}")
            
            if status == "completed":
                text = result.get("text", "").strip()
                print(f"✅ Transcrição completa: {text}")
                return text
            
            elif status == "error":
                print(f"Erro na transcrição: {result.get('error')}")
                return None
            
            # Aguarda 2 segundos antes de tentar novamente
            time.sleep(2)
            attempt += 1
        
        print("Timeout na transcrição")
        return None
    
    except Exception as e:
        print(f"Erro ao transcrever: {str(e)}")
        return None

def process_with_claude(texto, source_type="text"):
    """Processa com Claude"""
    try:
        if not CLAUDE_API_KEY:
            return parse_simple(texto)
        
        prompt = f"""
Você é assistente de tarefas. Analise: "{texto}"

Retorne JSON:
- name: Nome da tarefa (máximo 100 chars)
- description: Descrição (máximo 200 chars)
- due_date: Data YYYY-MM-DD ou null
- priority: 'urgent', 'high', 'normal', 'low'

Retorne APENAS JSON.
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
                "messages": [{"role": "user", "content": prompt}]
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result["content"][0]["text"]
            task_data = json.loads(content)
            
            if task_data.get("name") and not has_emoji(task_data["name"]):
                task_data["name"] = "📋 " + task_data["name"]
            
            return task_data
        else:
            return parse_simple(texto)
    
    except Exception as e:
        print(f"Erro Claude: {str(e)}")
        return parse_simple(texto)

def parse_simple(texto):
    """Parse simples como fallback"""
    if not texto or len(texto.strip()) == 0:
        return None
    
    task_data = {
        "name": texto.strip(),
        "due_date": None,
        "priority": None,
        "description": ""
    }
    
    texto_lower = texto.lower()
    
    if any(word in texto_lower for word in ["urgente", "asap"]):
        task_data["priority"] = "urgent"
    elif any(word in texto_lower for word in ["importante", "alta"]):
        task_data["priority"] = "high"
    
    if any(word in texto_lower for word in ["hoje"]):
        task_data["due_date"] = datetime.now().strftime("%Y-%m-%d")
    elif any(word in texto_lower for word in ["amanhã"]):
        tomorrow = datetime.now() + timedelta(days=1)
        task_data["due_date"] = tomorrow.strftime("%Y-%m-%d")
    
    if not has_emoji(task_data["name"]):
        task_data["name"] = "📋 " + task_data["name"]
    
    return task_data

def has_emoji(text):
    return any(ord(char) > 127 for char in text)

def send_message(chat_id, text):
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        data = {"chat_id": chat_id, "text": text}
        requests.post(url, json=data)
    except:
        pass

def create_clickup_task(task_data):
    if not CLICKUP_TOKEN:
        raise Exception("Token ClickUp não configurado!")
    
    token = CLICKUP_TOKEN.replace("Bearer ", "").strip()
    url = f"{CLICKUP_API}/list/{CLICKUP_LIST_ID}/task"
    
    payload = {
        "name": task_data.get("name", "Tarefa"),
        "description": task_data.get("description", ""),
    }
    
    if task_data.get("priority") == "urgent":
        payload["priority"] = 1
    elif task_data.get("priority") == "high":
        payload["priority"] = 2
    
    if task_data.get("due_date"):
        due_date_obj = datetime.strptime(task_data["due_date"], "%Y-%m-%d")
        payload["due_date"] = int(due_date_obj.timestamp() * 1000)
    
    headers = {"Authorization": token, "Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code != 200:
        error_data = response.json()
        raise Exception(f"Erro ClickUp: {error_data.get('err', 'Desconhecido')}")
    
    return response.json().get("id")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
