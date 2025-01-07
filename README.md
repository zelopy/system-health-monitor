다수의 서버들의 Daily 점검(시스템 자원 모니터링)을 위한 GUI 프로그램

# 실행 환경
Windows 10 64bit
Python 3.12.3

# 폴더 및 파일 설명
logs/ : 점검 과정 log 파일 저장 폴더
packages/ : 외부망 차단 환경에서 필요한 패키지 파일들
results/ : 점검결과 파일 저장 폴더
requirements.txt : 필수 패키지 목록
servers.yaml : 기본 설정, 점검대상 서버 정보 목록 및 점검할 서비스와 명령어 등(파일명에서 -example 제거 후 사용)
main.py : 서버 접속 및 점검 실행

=======================================================

[세팅 및 실행 방법]

# 가상환경 생성
```
python -m venv venv
```

# 가상환경 활성화
```
venv\Scripts\activate  # Windows
```
# 또는
```
source venv/bin/activate  # Linux/Mac
```

# 패키지 설치
```
pip install -r requirements.txt
```
※ 외부망 차단 환경인 경우 : 다운로드한 패키지들을 로컬에서 설치
```
pip install --no-index --find-links packages -r requirements.txt
```

# 실행
```
python main.py
```
