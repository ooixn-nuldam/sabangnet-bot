# 1. Playwright 공식 파이썬 이미지 사용 (브라우저 설치 환경 최적화)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 브라우저 엔진(Chromium) 수동 설치 (빌드 시 미리 설치)
RUN playwright install chromium

# 5. 소스 코드 복사
COPY . .

# 6. 포트 설정 및 실행
ENV PORT=8080
EXPOSE 8080

CMD ["python", "sabangnet_collector.py"]
