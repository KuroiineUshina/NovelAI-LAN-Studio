# NovelAI LAN Studio

> NovelAI와 관계없는 비공식 앱입니다. 본인의 NovelAI 계정과 Persistent API Token이 필요하며, 생성 비용(Anlas)과 이용약관은 NovelAI 기준을 따릅니다.

https://github.com/user-attachments/assets/e6d918dc-c084-46cc-9dc3-d415d66978c9

Windows PC와 승인된 Android 기기에서 NovelAI 이미지 생성과 갤러리를 사용하는 개인용 로컬 앱입니다. 생성은 항상 PC 서버를 거치고, Android 앱은 PC에 연결해 쓰며 PC가 꺼져 있을 때는 읽기 전용 오프라인 갤러리를 엽니다.

## 주요 기능

- 텍스트→이미지, 이미지→이미지, 인페인트, 업스케일
- 디렉터 툴: 표정 바꾸기(24종·세기 6단계), 채색, 선화, 스케치, 배경 제거, 정리
- 캐릭터 레퍼런스(Precise Reference, V4.5)와 바이브 트랜스퍼(V4·V4.5), 바이브 인코딩은 이미지·모델·정보량별로 PC에 캐시해 Anlas 재소모 방지
- 갤러리 결과의 부드러운 등장 애니메이션, 시스템 모션 감소 설정 지원
- PC 웹·Android 오프라인 갤러리에서 한 번 눌러 바꾸고 기기별로 기억하는 다크·라이트 테마
- V5 및 V4.5 네이티브 다중 인물 프롬프트와 자동 이미지 태그
- 여러 인물을 순서대로 묶어 한 번에 선택하는 공유 인물 세트
- 품질·묘사 탭마다 포지티브·네거티브 입력을 함께 두고 네 필드를 각각 저장해 PC·모바일에서 실시간 공유
- SQLite에 저장해 PC·모바일에서 함께 쓰는 품질 프롬프트 프리셋
- 설정 화면의 Claude 연동 상태(MCP 등록 여부, 최근 MCP 요청), 번들 NovelAI V5 프롬프트 스킬을 `~/.claude/skills`에 설치·업데이트
- Claude(Claude Code·데스크톱 앱)에서 이미지 묘사 P·N, 명시적으로 요청한 품질 P·N과 NSFW 상태를 적용하는 루프백 전용 MCP
- `품질 → nsfw, uncensored → 묘사 → NSFW 프롬프트` 순서로 조합되는 NSFW 옵션, NSFW 전용 프롬프트는 꺼 둬도 저장되고 켰을 때만 반영
- 정사각·세로·가로·긴 화면·대형 이미지 크기 프리셋과 가로/세로 전환
- 생성 화면 하단 고정 실행 버튼과 `Ctrl+Enter` 생성 단축키, Prompt Guidance Rescale, 설정별 예상 ANLAS·계정 잔액·Opus V5 무료 사용 한도와 1% 충전 속도·완충 예상 표시
- 생성 이미지 7일 임시보관, 즐겨찾기 영구보관, 해제 시점부터 7일 유예
- 갤러리 상세 보기의 기본 접힘 정보 패널, 접힌 상태 즐겨찾기, 핀치 확대·이동, 화면맞춤 상태 좌우 넘김, 아래 스와이프 닫기
- iPad Air 4 및 Galaxy Z Fold7 커버·내부 화면 전용 반응형 레이아웃
- 갤러리 이미지에서 품질·묘사 P/N·NSFW 옵션·인물·모델·세부 생성 설정을 체크박스로 골라 생성 초안에 가져오기
- 갤러리 이미지를 생성정보 포함/제거 두 가지로 클립보드에 복사 (PC는 원본 파일 그대로, Android 앱은 파일로 복사)
- 샘플러 6종(DPM++ 2M·2M SDE·2S Ancestral·SDE, Euler·Euler Ancestral)과 노이즈 스케줄(Karras·Exponential·Polyexponential) 선택, 기본값은 결과가 안정적인 DPM++ 2M + Karras
- 품질 프롬프트 프리셋에 품질 네거티브까지 함께 저장
- PC에서 이름별 Discord 웹훅을 안전하게 등록하고, 갤러리 원본을 선택한 대상에 태그·선택적 JSON 메타데이터와 함께 전송
- 즐겨찾기 태그 AND 필터와 ZIP·`manifest.json` 내보내기
- 전체·오늘·최근 7일·임시·즐겨찾기 생성 통계
- 단일 FIFO 대기열, 자동 재시도·자동 재개 없음
- Windows 자격 증명 관리자에 NovelAI 영구 API 토큰 보관
- Discord 웹훅 URL도 SQLite나 브라우저 응답에 남기지 않고 Windows 자격 증명 관리자에 보관
- 같은 Wi-Fi가 아니어도 포트포워딩 없이 연결하는 Tailscale 전용 `100.64.0.0/10` 원격 접속
- 모바일 기기별 데스크탑 연결 승인과 승인 해제, 승인 후 자동 로그인
- Android 내부 저장소에 PC의 임시·즐겨찾기 원본과 태그를 캐시하는 읽기 전용 오프라인 갤러리
- 오프라인 갤러리의 임시·즐겨찾기 전환, 태그 열람, 핀치 확대·좌우 넘김·아래 스와이프 닫기와 다운로드
- PC 설정에서 이미지 저장 폴더를 변경하고 기존 임시·즐겨찾기·편집 파일을 안전하게 함께 이동

## 실행 파일 사용

[Releases](../../releases)에서 Windows용 `NovelAI-LAN-Studio.exe`와 Android용 APK를 받을 수 있습니다. 함께 올린 `SHA256SUMS.txt`로 파일을 확인하세요.

1. `NovelAI-LAN-Studio.exe`를 실행합니다.
2. Windows 방화벽 창이 나타나면 **개인 네트워크**만 허용합니다.
3. PC 브라우저의 설정에서 NovelAI `Persistent API Token`을 저장하고 연결을 테스트합니다.
4. 같은 네트워크의 모바일은 앱에 표시되는 `http://사설-IP:8787` 주소로 접속합니다.
5. 모바일에서 연결 승인을 요청한 뒤 PC의 **설정 → 연결 기기 승인**에서 해당 기기를 승인합니다.

PC 화면 열기는 사용 가능한 경우 이 PC의 LAN 주소를 우선 사용합니다. 다른 로컬 개발 서버가 같은 포트의 `127.0.0.1`을 뒤늦게 점유하더라도 트레이 메뉴가 엉뚱한 서버를 열지 않게 하기 위한 동작입니다.

Claude에서 프롬프트를 다루려면 Claude Code에 MCP를 한 번 등록합니다.

```bash
claude mcp add --transport http --scope user novelaiLANStudio http://127.0.0.1:8787/mcp/
```

**설정 → Claude**에서 등록 여부를 확인하고, 앱에 포함된 `novelai-v5-scene-prompter` 스킬을 `~/.claude/skills`에 설치하거나 업데이트할 수 있습니다.

서로 다른 인터넷 회선에서 접속하려면 PC와 Android에 Tailscale을 설치해 연결한 뒤 PC 앱을 다시 실행합니다. 설정 또는 트레이에 표시되는 `http://100.x.x.x:8787` 주소를 Android 앱에 입력하세요. Tailscale의 기기 공유 기능을 사용하면 다른 계정의 친구에게 이 PC 한 대만 공유할 수 있습니다.

Windows 네트워크 프로필이 `공용`이면 일반 LAN 접속은 자동으로 꺼집니다. Tailscale이 연결돼 있으면 Tailscale 주소만 허용하며, 일반 LAN은 다시 열지 않습니다. 앱 종료는 시스템 트레이의 **종료**를 사용합니다.

> 모바일은 PC에서 승인된 기기만 이미지와 생성 기능에 접근할 수 있습니다. 승인된 기기는 HttpOnly 인증 쿠키로 자동 로그인되며 PC 설정에서 언제든 승인을 해제할 수 있습니다. 인터넷 포트포워딩과 Tailscale Funnel에 사용하지 마세요.

## Android 앱 사용

1. PC에서 `NovelAI-LAN-Studio.exe`를 먼저 실행합니다.
2. Android 기기에 현재 버전의 `NovelAI-LAN-Studio-Android-v*.apk`를 설치합니다.
3. 같은 네트워크라면 LAN 주소를, 다른 회선이라면 PC와 Android의 Tailscale 연결 후 표시되는 `100.x.x.x` 주소를 입력합니다.
4. Android 뒤로가기를 누르면 서버 주소를 변경할 수 있습니다.
5. 최초 연결 시 Android 화면에서 승인을 요청하고 PC 설정에서 승인합니다.

Android 앱은 마지막 연결 주소를 기억하고 PC가 발급한 기기 인증 쿠키는 WebView 쿠키 저장소에 보관하며, 사설 IPv4 또는 Tailscale 전용 `100.64.0.0/10` PC에만 접속합니다. 연결된 PC와 다른 origin으로의 WebView 요청과 다운로드는 차단하며, 저장소 설정은 Android에서 변경할 수 없습니다.

### Android 오프라인 갤러리

- 승인된 PC에 연결하면 임시보관과 즐겨찾기의 원본 이미지·보관 구분·태그를 Android 앱 내부 저장소에 주기적으로 동기화합니다.
- 프롬프트, 시드, 모델과 생성 설정은 오프라인 캐시 API가 반환하지 않으며 기기에도 저장하지 않습니다.
- PC에 연결할 수 없을 때 캐시가 있으면 읽기 전용 오프라인 갤러리가 자동으로 열립니다. 연결 화면의 **오프라인 갤러리 열기**로 직접 들어갈 수도 있습니다.
- 오프라인에서는 임시보관·즐겨찾기 전환과 태그 열람만 제공하며, 이미지 동작은 기기 다운로드만 허용합니다.
- 상세 이미지는 핀치 확대와 확대 상태 이동을 지원합니다. 화면맞춤 상태에서는 좌우 스와이프로 이미지를 넘기고 아래로 내리면 닫습니다.
- 서버에서 삭제되거나 만료된 이미지는 다음 전체 동기화가 성공하면 기기 캐시에서도 정리됩니다.

## 개발 실행

Python 3.10 이상과 Node.js 22.18 이상이 필요합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
cd frontend
npm install
npm run build
cd ..
.\.venv\Scripts\python -m backend.app.launcher --no-tray
```

브라우저 개발 서버가 필요하면 `scripts\dev.ps1 -Python .\.venv\Scripts\python.exe`를 실행합니다.

## 테스트

```powershell
.\.venv\Scripts\python -m pytest backend\tests -q
cd frontend
npm run build
cd ..\android
.\gradlew.bat testDebugUnitTest lintSideload assembleSideload
```

테스트는 NovelAI 호출을 모의 처리하므로 Anlas를 사용하지 않습니다. 실제 API 검증은 앱에서 사용자가 직접 저비용 생성 버튼을 눌러 수행해야 합니다.

## Windows EXE 빌드

```powershell
.\scripts\build.ps1 -Python .\.venv\Scripts\python.exe
```

결과는 `dist\NovelAI-LAN-Studio.exe`에 생성됩니다.

이 명령은 테스트, EXE 빌드, Windows ZIP과 체크섬 생성까지만 수행하며 외부 전송은 하지 않습니다. 검증이 모두 끝난 뒤 `python scripts\publish_distribution.py`를 별도로 실행해 기존 산출물을 Discord로 전송합니다. 전송이 실패해도 빌드는 다시 수행하지 않습니다. Discord에는 ZIP 대신 Windows EXE를 보내며, EXE가 업로드 제한보다 크면 전송할 때만 `.001` 등의 조각으로 나누고 EXE 합치기 파일을 함께 보냅니다.

## Android APK 빌드

실행 중인 기존 EXE를 유지하려면 Android·Windows 빌드에 같은 절대 경로의 `-OutputDirectory`를 지정해 후보 산출물을 별도 폴더에 만들 수 있습니다. 이 옵션은 앱을 종료·교체하거나 외부에 전송하지 않습니다.

JDK 17과 Android SDK Platform 36이 준비된 환경에서 실행합니다.

```powershell
.\scripts\build_android.ps1 -JavaHome 'C:\path\to\jdk-17' -AndroidSdkRoot 'C:\path\to\Android\Sdk'
```

단위 테스트와 Lint를 통과하고 디버깅 기능을 끈 개인 설치용 APK가 `dist\NovelAI-LAN-Studio-Android-v<현재 버전>.apk`에 생성됩니다. 이 APK는 로컬 디버그 키로 서명되며, Play Store 배포용 릴리스 APK/AAB에는 사용자가 관리하는 별도의 서명 키가 필요합니다.

## 데이터 위치

기본 데이터는 `%LOCALAPPDATA%\NovelAI-LAN-Studio\`에 저장됩니다.

- `data\app.db`: SQLite 메타데이터와 통계
- `data\assets\temporary`: 7일 임시 생성물
- `data\assets\favorites`: 영구 즐겨찾기
- `data\assets\uploads`: 7일 편집 원본
- `logs\app.log`: API 토큰을 포함하지 않는 실행 로그

이미지 저장 폴더는 PC의 **설정 → 로컬 서버 정보**에서 빈 로컬 폴더로 변경할 수 있습니다. SQLite와 로그는 기존 앱 데이터 폴더에 유지되며, 이미지·썸네일·업로드·마스크만 새 폴더로 이동합니다. 생성 대기 또는 실행 중인 작업이 있으면 폴더 변경이 차단됩니다.

“영구”는 앱의 자동 삭제 대상이 아니라는 뜻입니다. 디스크 장애에 대비하려면 즐겨찾기 ZIP을 별도로 백업하세요.

## API 및 안전 원칙

- PC의 NovelAI 영구 API 토큰은 브라우저 응답, SQLite, 로그에 기록하지 않고 Windows 자격 증명 관리자에 저장합니다. 토큰은 Android 기기로 보내지 않으며 평문 토큰 조회 API를 제공하지 않습니다.
- Claude 연동 상태는 로컬 설정 파일(`~/.claude.json`)에서 이 앱의 MCP 주소가 등록됐는지만 읽으며, NovelAI 토큰과 Discord 웹훅 URL을 Claude에 전달하지 않습니다.
- MCP는 `127.0.0.1`에서만 접근할 수 있습니다. 이미지 묘사·품질 초안을 읽고 저장할 수 있지만 토큰·웹훅·설정·삭제·일반 이미지 생성 도구는 노출하지 않습니다.
- MCP의 이미지 묘사·품질 수정은 먼저 읽은 리비전이 일치할 때만 적용되어 PC·모바일의 더 최신 입력을 덮어쓰지 않습니다.
- Discord 웹훅 URL은 PC에서만 등록·수정할 수 있고, 모바일에는 저장된 이름만 제공됩니다.
- Discord 전송은 버튼을 누른 한 번만 시도하며 연결 오류나 제한 응답을 자동 재시도하지 않습니다.
- 생성 요청은 사용자의 버튼 동작으로만 만들며 예약·무한 생성 기능은 없습니다.
- 응답이 불확실한 네트워크 오류도 자동 재시도하지 않아 중복 과금을 막습니다.
- PC 전용 `/api/admin/*`는 루프백 또는 이 PC가 직접 소유한 LAN 주소의 요청만 허용합니다.
- 승인 전 모바일은 상태 확인과 승인 요청 API만 사용할 수 있으며, 이미지·생성·프리셋 API는 `401`로 차단합니다.
- 모든 앱 요청은 루프백·사설 IP로 제한하며 CORS를 개방하지 않습니다.
- Tailscale 원격 요청은 공식 CGNAT 범위 `100.64.0.0/10`과 PC 시작 시 확인된 Tailscale 연결에만 허용하며 관리자 API는 계속 차단합니다.

## 라이선스

[MIT](LICENSE). 앱에 포함된 글꼴과 라이브러리의 라이선스는 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)를 참고하세요.
