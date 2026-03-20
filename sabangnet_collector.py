import os
import asyncio
import threading
import pandas as pd
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS
from playwright.async_api import async_playwright
from supabase import create_client, Client
import requests

# Flask 설정 및 CORS 허용 (Next.js 연동용)
app = Flask(__name__)
CORS(app)

# 1. 환경 변수 로드
SABANGNET_ID = os.environ.get("SABANGNET_ID")
SABANGNET_PW = os.environ.get("SABANGNET_PW")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")

# Supabase 클라이언트 초기화
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_discord_log(message):
    if DISCORD_WEBHOOK:
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": message})
        except Exception as e:
            print(f"디스코드 전송 실패: {e}")

async def run_collector_logic():
    """실제 사방넷 수집 핵심 로직"""
    async with async_playwright() as p:
        # 서버 환경 최적화 실행
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()

        try:
            print(f"[{datetime.now()}] 사방넷 수집 시작...")
            
            # Step 1: 로그인
            await page.goto("https://www.sabangnet.co.kr/login.html") 
            await page.fill('input[placeholder="아이디를 입력해주세요."]', SABANGNET_ID)
            await page.fill('input[placeholder="비밀번호를 입력해주세요."]', SABANGNET_PW)
            await page.click('button:has-text("로그인")')
            await page.wait_for_load_state("networkidle")
            
            # TODO: 실제 사방넷 내부 메뉴 클릭 및 엑셀 다운로드 로직 고도화 필요
            # 현재는 연동 확인을 위한 더미 로그를 생성합니다.
            print("로그인 성공 및 메뉴 진입 시도")
            
            # 예시: 완료 후 알림
            send_discord_log("✅ [사방넷 봇] 수집 프로세스가 성공적으로 시작되었습니다. (세부 로직 고도화 대기 중)")

        except Exception as e:
            error_msg = f"❌ [사방넷 봇] 에러 발생: {str(e)}"
            print(error_msg)
            send_discord_log(error_msg)
        finally:
            await browser.close()

# --- API 엔드포인트 ---

@app.route('/collect', methods=['POST'])
def start_collect():
    """Next.js 웹 버튼 클릭 시 호출됨"""
    # 백그라운드 스레드에서 수집기 실행 (웹 응답은 즉시 반환)
    def interrupt_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_collector_logic())
        loop.close()

    thread = threading.Thread(target=interrupt_loop)
    thread.start()
    
    return jsonify({
        "status": "success", 
        "message": "수집 프로세스가 백그라운드에서 시작되었습니다."
    }), 200

@app.route('/health', methods=['GET'])
def health_check():
    return "OK", 200

if __name__ == "__main__":
    # Railway가 부여하는 PORT 번호로 실행
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)