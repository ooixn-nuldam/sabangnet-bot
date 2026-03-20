import os
import asyncio
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
import openpyxl
from supabase import create_client, Client
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ================================================
# 1. 환경 설정 및 초기화
# ================================================
SABANGNET_ID    = os.getenv("SABANGNET_ID")
SABANGNET_PW    = os.getenv("SABANGNET_PW")
SUPABASE_URL    = os.getenv("SUPABASE_URL")
SUPABASE_KEY    = os.getenv("SUPABASE_KEY")
EXCEL_SAVE_PATH = "/tmp/sabangnet_excel"
# 세션 파일 경로 (깃허브 루트에 올렸을 경우)
AUTH_STATE_PATH = "auth_state.json"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================
# 2. Supabase 저장 로직 (변동 없음)
# ================================================
async def save_to_supabase(filepath: str):
    print(f"엑셀 파일 읽기 및 Supabase 저장 시작: {filepath}")
    wb = openpyxl.load_workbook(filepath)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=3, values_only=True))
    new_count = 0

    for row in rows:
        try:
            site_name     = str(row[1])
            seller_id     = str(row[2])
            created_at    = str(row[3])
            collected_at  = str(row[4])
            order_number  = str(row[7])
            inquiry_type  = str(row[8])
            product_name  = str(row[9])
            content       = str(row[10])
            answer        = str(row[11])
            customer_name = str(row[12])

            if not order_number or order_number == "None":
                continue

            existing = supabase.table("inquiries") \
                .select("id") \
                .eq("order_number", order_number) \
                .eq("inquiry_type", inquiry_type) \
                .execute()

            if existing.data:
                continue

            supabase.table("inquiries").insert({
                "site_name": site_name,
                "seller_id": seller_id,
                "order_number": order_number,
                "inquiry_type": inquiry_type,
                "product_name": product_name,
                "content": content,
                "answer": answer,
                "customer_name": customer_name,
                "status": "대기",
                "created_at": created_at,
                "collected_at": collected_at,
            }).execute()
            new_count += 1
        except Exception as e:
            print(f"데이터 행 처리 중 에러: {e}")
            continue

    print(f"✅ Supabase 저장 완료! 신규 건수: {new_count}")
    return new_count

# ================================================
# 3. 사방넷 수집 자동화 메인 로직 (세션 주입 적용)
# ================================================
async def collect_sabangnet_logic():
    print(f"[{datetime.now()}] 사방넷 수집 프로세스 가동")
    Path(EXCEL_SAVE_PATH).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        
        # --- [중요] 세션 파일(auth_state.json) 로드 로직 ---
        try:
            if os.path.exists(AUTH_STATE_PATH):
                print(f"✅ {AUTH_STATE_PATH} 파일을 발견했습니다. 세션을 주입합니다.")
                context = await browser.new_context(
                    storage_state=AUTH_STATE_PATH,
                    viewport={'width': 1920, 'height': 1080}
                )
            else:
                print("⚠️ 세션 파일이 없습니다. 일반 컨텍스트를 생성합니다.")
                context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        except Exception as e:
            print(f"🔴 세션 로드 중 오류 발생: {e}")
            context = await browser.new_context(viewport={'width': 1920, 'height': 1080})

        page = await context.new_page()
        page.set_default_timeout(60000)

        try:
            # --- 1. 로그인 상태 확인 및 조건부 로그인 ---
            print("사방넷 접속 및 로그인 상태 확인 중...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/dashboard", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # 세션 주입이 성공했다면 대시보드로 바로 들어가짐. 아니라면 로그인 실행.
            if "login" in page.url or await page.locator('input[name="admin_id"]').is_visible():
                print("로그인이 만료되었거나 세션이 유효하지 않습니다. 재로그인 시도...")
                await page.goto("https://www.sabangnet.co.kr/login.html", wait_until="networkidle")
                await page.fill('input[name="admin_id"]', SABANGNET_ID)
                await page.fill('input[name="admin_pwd"]', SABANGNET_PW)
                
                login_btn = page.locator("button:has-text('접속하기'), input[type='submit'], .btn_login")
                if await login_btn.count() > 0:
                    await login_btn.first.click()
                else:
                    await page.keyboard.press("Enter")
                
                await page.wait_for_url("**/dashboard", timeout=60000)
                print("✅ 재로그인 성공!")
            else:
                print("✅ 세션이 유효합니다. 바로 수집을 시작합니다.")

            # --- 2. 문의 수집 실행 (사용자 요구사항 반영) ---
            print("STEP 2: 문의사항 수집 페이지 이동...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/customer-service/ask-collect", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            print("전체 체크박스 선택 및 수집 버튼 클릭...")
            await page.wait_for_selector("input[type='checkbox']")
            await page.locator("input[type='checkbox']").first.click() # 전체 선택
            await page.click("button:has-text('쇼핑몰 문의수집')")
            
            print("⏳ 서버 수집 대기 중 (5분)...")
            await asyncio.sleep(300) 

            # --- 3. 문의 답변 페이지 이동 및 엑셀 다운로드 ---
            print("STEP 3: 문의사항 답변 페이지로 이동...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/customer-service/ask-answer", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            excel_filename = f"sabangnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            excel_filepath = os.path.join(EXCEL_SAVE_PATH, excel_filename)

            print("우측 상단 다운로드 버튼 클릭 시도...")
            async with page.expect_download() as download_info:
                # 파란색 다운로드 버튼 타겟팅
                await page.click("button:has-text('다운로드')")
            
            download = await download_info.value
            await download.save_as(excel_filepath)
            print(f"✅ 엑셀 다운로드 완료: {excel_filepath}")

            # --- 4. Supabase 저장 호출 ---
            await save_to_supabase(excel_filepath)

        except Exception as e:
            print(f"🔴 수집 프로세스 중 오류 발생: {str(e)}")
        finally:
            await browser.close()
            print("브라우저 종료")

# [API 엔드포인트 및 서버 실행 부분은 이전과 동일]
@app.post("/collect")
async def start_collect(background_tasks: BackgroundTasks):
    background_tasks.add_task(collect_sabangnet_logic)
    return {"status": "success", "message": "사방넷 수집이 백그라운드에서 시작되었습니다."}

@app.get("/health")
async def health_check():
    return {"status": "running", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
