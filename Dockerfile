# 1. Playwright 전용 이미지 사용
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# 2. 환경 변수 설정 (파이썬 로그 출력 및 포트)
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# 3. 작업 디렉토리 설정
WORKDIR /app

# 4. 필수 파일 복사 및 라이브러리 설치
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
    
RUN playwright install --with-deps chromium

# 5. 소스 코드 복사
COPY . .

# 6. 포트 개방 및 실행
EXPOSE 8080
CMD ["python", "sabangnet_collector.py"]
