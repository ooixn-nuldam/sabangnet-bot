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

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================
# 2. Supabase 저장 로직 (엑셀 파싱)
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
# 3. 사방넷 수집 자동화 메인 로직 (로그인 대응 강화)
# ================================================
async def collect_sabangnet_logic():
    print(f"[{datetime.now()}] 사방넷 수집 프로세스 가동")
    Path(EXCEL_SAVE_PATH).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        # 세션 유지를 위해 context 설정 및 타임아웃 연장
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()
        page.set_default_timeout(60000) # 타임아웃 60초로 상향

        try:
            # --- 1. 로그인 상태 확인 ---
            print("로그인 상태 확인 중...")
            # 대시보드 주소로 먼저 접속 시도
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/dashboard", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # 현재 URL이나 특정 요소를 보고 로그인이 필요한지 판단
            if "login" in page.url or await page.locator('input[name="admin_id"]').is_visible():
                print("로그인이 필요합니다. 로그인 페이지로 이동...")
                await page.goto("https://www.sabangnet.co.kr/login.html", wait_until="networkidle")
                await page.fill('input[name="admin_id"]', SABANGNET_ID)
                await page.fill('input[name="admin_pwd"]', SABANGNET_PW)
                
                # 엔터 대신 '접속하기' 버튼 직접 클릭 시도
                login_btn = page.locator("button:has-text('접속하기'), input[type='submit'], .btn_login")
                if await login_btn.count() > 0:
                    await login_btn.first.click()
                else:
                    await page.keyboard.press("Enter")
                
                # 로그인 후 대시보드 로딩 대기
                await page.wait_for_url("**/dashboard", timeout=60000)
                print("✅ 로그인 성공!")
            else:
                print("✅ 기존 세션이 유효합니다. 로그인을 건너뜁니다.")

            # --- 2. 문의 수집 실행 ---
            print("문의사항 수집 페이지 이동...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/customer-service/ask-collect", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            print("전체 선택 및 수집 시작...")
            # 체크박스 로딩 대기 후 첫 번째(전체선택) 클릭
            await page.wait_for_selector("input[type='checkbox']")
            await page.locator("input[type='checkbox']").first.click()
            
            # '쇼핑몰 문의수집' 버튼 클릭
            await page.click("button:has-text('쇼핑몰 문의수집')")
            
            print("서버 수집 대기 중 (5분)...")
            await asyncio.sleep(300) # 서버 부하 고려 5분 대기

            # --- 3. 문의 답변 페이지 이동 및 엑셀 다운로드 ---
            print("문의사항 답변 페이지로 이동...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/customer-service/ask-answer", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            excel_filename = f"sabangnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            excel_filepath = os.path.join(EXCEL_SAVE_PATH, excel_filename)

            print("엑셀 다운로드 시도...")
            async with page.expect_download() as download_info:
                await page.click("button:has-text('다운로드')")
            
            download = await download_info.value
            await download.save_as(excel_filepath)
            print(f"엑셀 다운로드 완료: {excel_filepath}")

            # --- 4. Supabase 저장 호출 ---
            await save_to_supabase(excel_filepath)

        except Exception as e:
            print(f"🔴 수집 프로세스 중 오류 발생: {str(e)}")
        finally:
            await browser.close()
            print("브라우저 종료")

# ================================================
# 4. API 서버 엔드포인트
# ================================================
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
