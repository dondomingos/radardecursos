"""
Scraper - Radar de Cursos
=========================
Usa a API oficial do Senac EAD em vez de scraping HTML.
Muito mais estável e rápido.

API descoberta: https://www.ead.senac.br/cms/api/cursos/cursos-gratuitos/

Campos relevantes do JSON:
  - titulo        → nome do curso
  - cursoAberto   → True se inscrições abertas
  - inscricaoPSG  → True se é curso gratuito PSG
  - path          → slug da URL do curso
  - modalidade    → tipo (Técnico, Livre, etc.)
"""

import json
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import time

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# ══════════════════════════════════════════════════════
# CONFIGURAÇÕES DE E-MAIL
# ══════════════════════════════════════════════════════
EMAIL_REMETENTE    = os.environ.get("EMAIL_REMETENTE",    "seuemail@gmail.com")
SENHA_APP          = os.environ.get("SENHA_APP",          "xxxx xxxx xxxx xxxx")
EMAIL_DESTINATARIO = os.environ.get("EMAIL_DESTINATARIO", "seuemail@gmail.com")

# ══════════════════════════════════════════════════════
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CURSOS = os.path.join(BASE_DIR, "data", "courses.json")
ARQUIVO_ESTADO = os.path.join(BASE_DIR, "estado.json")

BASE_URL = "https://www.ead.senac.br/gratuito"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://www.ead.senac.br/gratuito",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.ead.senac.br",
}

DEBUG = False  # Mude para False após confirmar que está funcionando


# ══════════════════════════════════════════════════════
# BUSCAR CURSOS VIA API
# ══════════════════════════════════════════════════════

def buscar_cursos_senac() -> list[dict]:
    print("[Senac EAD] Iniciando navegador...")

    # Configura Chrome invisível (headless)
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    cursos = []
    try:
        print("[Senac EAD] Abrindo página de cursos gratuitos...")
        driver.get("https://www.ead.senac.br/gratuito")

        # Aguarda a seção de cursos técnicos carregar (até 20 segundos)
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn.inscricoes")))

        print("[Senac EAD] Página carregada. Extraindo cursos técnicos...")
        time.sleep(2)  # Aguarda renderização completa do AngularJS

        agora = datetime.now(timezone.utc).isoformat()

        # Busca todas as linhas de cursos (tr com ng-repeat)
        linhas = driver.find_elements(By.CSS_SELECTOR, "tr.ng-scope")

        for linha in linhas:
            try:
                # Nome do curso (link principal)
                link_nome = linha.find_elements(By.CSS_SELECTOR, "a.ng-binding")
                if not link_nome:
                    continue
                titulo = link_nome[0].text.strip()
                if not titulo or ("técnico" not in titulo.lower() and "tecnico" not in titulo.lower()):
                    continue

                # URL do curso
                url_curso = link_nome[0].get_attribute("href") or BASE_URL

                # Verifica se tem botão "Inscrições abertas"
                botoes = linha.find_elements(By.CSS_SELECTOR, "a.btn.inscricoes")
                aberto = len(botoes) > 0

                cursos.append({
                    "nome":               titulo,
                    "status":             "Inscrições abertas" if aberto else "Encerrado",
                    "aberto":             aberto,
                    "instituicao":        "Senac EAD",
                    "url":                url_curso,
                    "ultima_atualizacao": agora,
                })

            except Exception:
                continue

    finally:
        driver.quit()

    print(f"[Senac EAD] {len(cursos)} cursos técnicos encontrados.")
    if DEBUG:
        for c in cursos:
            print(f"   {'✅' if c['aberto'] else '❌'} {c['nome']}")

    return cursos


# ══════════════════════════════════════════════════════
# SALVAR JSON DO SITE
# ══════════════════════════════════════════════════════

def salvar_courses_json(cursos: list[dict]):
    os.makedirs(os.path.dirname(ARQUIVO_CURSOS), exist_ok=True)
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "courses": cursos
    }
    with open(ARQUIVO_CURSOS, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[OK] data/courses.json salvo com {len(cursos)} cursos.")


# ══════════════════════════════════════════════════════
# ESTADO — controla notificações já enviadas
# ══════════════════════════════════════════════════════

def carregar_estado() -> dict:
    if os.path.exists(ARQUIVO_ESTADO):
        try:
            with open(ARQUIVO_ESTADO, encoding="utf-8") as f:
                conteudo = f.read().strip()
                if not conteudo:
                    return {}
                return json.loads(conteudo)
        except json.JSONDecodeError:
            print("[Aviso] estado.json inválido, iniciando do zero.")
            return {}
    return {}


def salvar_estado(estado: dict):
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════
# E-MAIL
# ══════════════════════════════════════════════════════

def enviar_email(cursos_novos: list[dict]):
    if EMAIL_REMETENTE == "seuemail@gmail.com":
        print("[E-mail] Credenciais não configuradas. Pulando envio.")
        return

    assunto = f"🎓 {len(cursos_novos)} novo(s) curso(s) com inscrições abertas!"
    linhas  = "\n".join(f"  • {c['nome']}" for c in cursos_novos)
    corpo   = (
        "Novos cursos técnicos Senac EAD com inscrições abertas:\n\n"
        f"{linhas}\n\n"
        f"Acesse: {BASE_URL}\n"
    )
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_REMETENTE
    msg["To"]      = EMAIL_DESTINATARIO
    msg["Subject"] = assunto
    msg.attach(MIMEText(corpo, "plain", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls()
        s.login(EMAIL_REMETENTE, SENHA_APP)
        s.send_message(msg)

    print(f"[E-mail] Enviado com {len(cursos_novos)} curso(s).")


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════

def main():
    todos_cursos = buscar_cursos_senac()
    salvar_courses_json(todos_cursos)

    estado = carregar_estado()
    novos  = []

    for curso in todos_cursos:
        chave    = f"Senac EAD::{curso['nome']}"
        anterior = estado.get(chave, {})

        if curso["aberto"] and not anterior.get("notificado_aberto", False):
            novos.append(curso)
            estado[chave] = {"aberto": True, "notificado_aberto": True}
        elif not curso["aberto"]:
            estado[chave] = {"aberto": False, "notificado_aberto": False}
        else:
            estado[chave] = {"aberto": True, "notificado_aberto": True}

    if novos:
        print(f"[Info] {len(novos)} curso(s) novo(s) para notificar.")
        if not DEBUG:
            enviar_email(novos)
        else:
            print("[DEBUG] E-mail não enviado (DEBUG=True). Mude para False para ativar.")
    else:
        print("[Info] Nenhum curso novo. Nada a notificar.")

    salvar_estado(estado)


if __name__ == "__main__":
    main()
