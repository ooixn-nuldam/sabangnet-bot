import os
import asyncio
import threading
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

# Supabase 클라이언트 초기화
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# FastAPI 서버 초기화
app = FastAPI()

# CORS 설정 (Next.js 웹 앱 연동용)
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

    # 1행 타이틀, 2행 헤더 제외하고 3행부터 데이터 읽기
    rows = list(ws.iter_rows(min_row=3, values_only=True))
    new_count = 0

    for row in rows:
        try:
            # 엑셀 컬럼 매핑 (사방넷 표준 양식 기준)
            site_name     = str(row[1])   # 쇼핑몰명
            seller_id     = str(row[2])   # 판매자ID
            created_at    = str(row[3])   # 고객등록일자
            collected_at  = str(row[4])   # 시스템수집일자
            order_number  = str(row[7])   # 주문번호 (고유 식별자)
            inquiry_type  = str(row[8])   # 문의제목/유형
            product_name  = str(row[9])   # 상품명
            content       = str(row[10])  # 문의내용
            answer        = str(row[11])  # 답변 및 안내
            customer_name = str(row[12])  # 작성자

            # 주문번호가 없으면 데이터가 아니므로 스킵
            if not order_number or order_number == "None":
                continue

            # 중복 체크 (주문번호 + 문의제목 기준)
            existing = supabase.table("inquiries") \
                .select("id") \
                .eq("order_number", order_number) \
                .eq("inquiry_type", inquiry_type) \
                .execute()

            if existing.data:
                continue  # 이미 있는 데이터는 건너뜀

            # Supabase Insert
            supabase.table("inquiries").insert({
                "site_name":     site_name,
                "seller_id":     seller_id,
                "order_number":  order_number,
                "inquiry_type":  inquiry_type,
                "product_name":  product_name,
                "content":       content,
                "answer":        answer,
                "customer_name": customer_name,
                "status":        "대기",
                "created_at":    created_at,
                "collected_at":  collected_at,
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
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # --- 1. 로그인 ---
            print("사방넷 로그인 중...")
            await page.goto("https://www.sabangnet.co.kr/login.html", wait_until="networkidle")
            await page.fill('input[name="admin_id"]', SABANGNET_ID)
            await page.fill('input[name="admin_pwd"]', SABANGNET_PW)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(5000)

            # --- 2. 문의 수집 실행 ---
            print("문의사항 수집 페이지 이동...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/customer-service/ask-collect")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            # 전체 선택 및 수집 버튼 (ID나 클래스에 따라 조정 필요)
            print("전체 선택 및 수집 버튼 클릭 시도...")
            await page.locator("input[type='checkbox']").first.click()
            await page.click("button:has-text('쇼핑몰 문의수집')")
            
            print("수집 대기 중 (5분)...")
            await page.wait_for_timeout(300000) # 5분간 서버 수집 대기

            # --- 3. 문의 답변 페이지 이동 및 엑셀 다운로드 ---
            print("문의사항 답변 페이지로 이동...")
            await page.goto("https://sbadmin15.sabangnet.co.kr/#/customer-service/ask-answer")
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            today = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_filename = f"sabangnet_{today}.xlsx"
            excel_filepath = os.path.join(EXCEL_SAVE_PATH, excel_filename)

            print("엑셀 다운로드 시작...")
            async with page.expect_download() as download_info:
                # '다운로드' 버튼 클릭 (사방넷 UI 텍스트에 맞춤)
                await page.click("button:has-text('다운로드')")
            
            download = await download_info.value
            await download.save_as(excel_filepath)
            print(f"엑셀 다운로드 완료: {excel_filepath}")

            # --- 4. Supabase 저장 호출 ---
            await save_to_supabase(excel_filepath)

        except Exception as e:
            print(f"🔴 수집 중 오류 발생: {str(e)}")
        finally:
            await browser.close()
            print("브라우저 종료 및 세션 종료")

# ================================================
# 4. API 서버 엔드포인트
# ================================================

@app.post("/collect")
async def start_collect(background_tasks: BackgroundTasks):
    # 웹 앱 요청 시 즉시 응답하고 로직은 백그라운드에서 실행
    background_tasks.add_task(collect_sabangnet_logic)
    return {"status": "success", "message": "사방넷 수집 로직이 백그라운드에서 실행되었습니다."}

@app.get("/health")
async def health_check():
    return {"status": "running", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
