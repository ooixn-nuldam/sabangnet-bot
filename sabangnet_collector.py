import os
import asyncio
import pandas as pd
from datetime import datetime
from playwright.async_api import async_playwright
from supabase import create_client, Client
import requests

# 1. 환경 변수 로드 (Railway 설정값)
SABANGNET_ID = os.environ.get("SABANGNET_ID")
SABANGNET_PW = os.environ.get("SABANGNET_PW")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")

# Supabase 클라이언트 초기화
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_discord_log(message):
    if DISCORD_WEBHOOK:
        requests.post(DISCORD_WEBHOOK, json={"content": message})

async def run_collector():
    async with async_playwright() as p:
        # 브라우저 실행 (Railway 환경에 맞게 headless 모드)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()

        try:
            print(f"[{datetime.now()}] 사방넷 접속 중...")
            # 사방넷 로그인 페이지 (URL은 실제 로그인 주소로 확인 필요)
            await page.goto("https://www.sabangnet.co.kr/login.html") 

            # Step 1: 로그인
            await page.fill('input[placeholder="아이디를 입력해주세요."]', SABANGNET_ID)
            await page.fill('input[placeholder="비밀번호를 입력해주세요."]', SABANGNET_PW)
            await page.click('button:has-text("로그인")')
            await page.wait_for_load_state("networkidle")
            print("로그인 성공")

            # Step 2: 문의 수집 메뉴 이동 및 수집 클릭 (예시 선택자)
            # ※ 실제 사방넷 메뉴 구조에 따라 selector 수정이 필요할 수 있습니다.
            await page.goto("https://www.sabangnet.co.kr/admin/inquiry/collect") # 가상 경로
            await page.click("#all_check_box") # 전체 선택
            await page.click("button:has-text('쇼핑몰 문의수집')")
            
            print("문의 수집 시작... 5분 대기")
            await asyncio.sleep(300) # 수집 완료까지 대기

            # Step 3: 엑셀 다운로드 및 데이터 읽기
            # (실제 환경에서는 다운로드 이벤트를 캡처해야 함)
            async with page.expect_download() as download_info:
                await page.click("button:has-text('다운로드')")
            download = await download_info.value
            path = f"./temp_inquiries_{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
            await download.save_as(path)

            # Step 4: Pandas로 엑셀 분석 및 Supabase 저장
            df = pd.read_excel(path)
            new_items_count = 0

            for index, row in df.iterrows():
                # 중복 확인 (주문번호 기준 등)
                check = supabase.table("inquiries").select("id").eq("order_number", str(row['주문번호'])).execute()
                
                if not check.data:
                    data = {
                        "site_name": row.get('쇼핑몰명'),
                        "seller_id": row.get('판매자ID'),
                        "order_number": str(row.get('주문번호')),
                        "inquiry_type": row.get('문의제목'),
                        "product_name": row.get('상품명'),
                        "content": row.get('문의내용'),
                        "customer_name": row.get('작성자'),
                        "status": "대기",
                        "created_at": str(row.get('고객등록일자')),
                        "collected_at": datetime.now().isoformat()
                    }
                    supabase.table("inquiries").insert(data).execute()
                    new_items_count += 1

            send_discord_log(f"✅ 수집 완료: 신규 문의 {new_items_count}건 등록되었습니다.")
            
        except Exception as e:
            error_msg = f"❌ 에러 발생: {str(e)}"
            print(error_msg)
            send_discord_log(error_msg)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_collector())