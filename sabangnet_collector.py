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
# 세션 파일 경로 (이 파일이 깃허브에 업로드되어 있어야 배포 시 유지됩니다)
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
# 2. Supabase 저장 로직
# ================================================
async def save_to_supabase(filepath: str):
    print(f"엑셀 파일 읽기 및 Supabase 저장 시작: {filepath}")
    wb = openpyxl.load_workbook(filepath)
    ws = wb.active
    # 사방넷 엑셀 양식에 맞춰 min_row 조절 (보통 3행부터 데이터)
    rows = list(ws.iter_rows(min_row=3, values_only=True))
    new_count = 0

    for row in rows:
        try:
            if not row or len(row) < 12: continue
            
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
# 3. 사방넷 수집 자동화 메인 로직
# ================================================
async def collect_sabangnet_logic():
    print(f"[{datetime.now()}] 사방넷 수집 프로세스 가동")
    Path(EXCEL_SAVE_PATH).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        
        # 세션 파일 존재 여부 확인 후 컨텍스트 생성
        if os.path.exists(AUTH_STATE_PATH):
            print(f"✅ {AUTH_STATE_PATH} 파일을 발견했습니다. 세션을 주입합니다.")
            context = await browser.new_context(storage_state=AUTH_STATE_PATH)
        else:
            print(f"⚠️ {AUTH_STATE_PATH} 파일이 없습니다. 새로 로그인을 시도합니다.")
            context = await browser.new_context()

        page = await context.new_page()
        page.set_default_timeout(600000) # 10분

        # 팝업 알럿(확인창) 자동 승인
        page.on("dialog", lambda dialog: dialog.accept())

        try:
            # 1. 수집 페이지 접속
            print("STEP 1: 문의사항 수집 페이지 이동...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/customer-service/ask-collect")
            
            # 2. 전체 선택 및 수집 시작
            print("전체 체크박스 선택 및 수집 버튼 클릭...")
            await page.wait_for_selector("thead input[type='checkbox']")
            await page.locator("thead input[type='checkbox']").first.click()
            await page.click("button:has-text('쇼핑몰 문의수집')")
            
            # 3. '닫기' 버튼 감지 (수집 완료 대기)
            print("⏳ 사방넷 수집 진행 중... 완료 대기 (닫기 버튼 감지 중)")
            close_btn_selector = "button:has-text('닫기'), .btn_close, input[value='닫기']"
            
            try:
                # 닫기 버튼이 화면에 나타날 때까지 최대 10분 대기
                close_btn = page.locator(close_btn_selector).last
                await close_btn.wait_for(state="visible", timeout=600000)
                print(f"✅ 수집 완료 확인됨 ({datetime.now().strftime('%H:%M:%S')})")
                
                await close_btn.click()
                await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"⚠️ 닫기 버튼 감지 실패: {e}. 다음 단계 시도.")

            # 4. 문의 답변 페이지 이동 및 엑셀 다운로드
            print("STEP 2: 문의사항 답변 페이지로 이동...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/customer-service/ask-answer")
            
            # [중요] 검색 버튼 클릭해야 데이터가 나옵니다.
            print("검색 버튼 클릭하여 리스트 호출...")
            await page.locator("button:has-text('검색')").first.click()
            await page.wait_for_timeout(3000)

            excel_filename = f"sabangnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            excel_filepath = os.path.join(EXCEL_SAVE_PATH, excel_filename)

            print("엑셀 다운로드 시작...")
            async with page.expect_download() as download_info:
                await page.locator("button:has-text('다운로드')").first.click()
            
            download = await download_info.value
            await download.save_as(excel_filepath)
            print(f"✅ 엑셀 다운로드 성공: {excel_filepath}")

            # 5. Supabase 저장
            await save_to_supabase(excel_filepath)

        except Exception as e:
            print(f"🔴 오류 발생: {str(e)}")
        finally:
            await browser.close()
            print("브라우저 종료")

@app.post("/collect")
async def run_collect(background_tasks: BackgroundTasks):
    background_tasks.add_task(collect_sabangnet_logic)
    return {"message": "수집 프로세스가 백그라운드에서 시작되었습니다."}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
