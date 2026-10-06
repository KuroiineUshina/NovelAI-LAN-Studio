# NovelAI LAN Studio Android

같은 사설 네트워크에서 Windows용 NovelAI LAN Studio를 조작하는 Android 동반 앱입니다. 생성 엔진과 API 토큰은 PC에만 있으며 Android 앱은 PC가 제공하는 반응형 UI를 안전한 WebView로 엽니다.

## 동작

- 마지막으로 성공한 PC 주소를 기기에 저장하고 다음 실행 때 자동으로 연결합니다.
- 최초 접속 시 PC에서 기기 승인을 받고, 승인 쿠키를 저장해 이후 자동 로그인합니다.
- `10.x.x.x`, `172.16–31.x.x`, `192.168.x.x`, IPv4 링크 로컬 주소만 허용합니다.
- 연결한 PC와 동일한 origin 이외의 WebView 이동과 다운로드를 차단합니다.
- PNG/JPEG/WebP 파일 선택, 원본 이미지 및 즐겨찾기 ZIP 다운로드를 지원합니다.
- 온라인일 때 임시보관·즐겨찾기 원본과 태그를 앱 내부 저장소에 캐시합니다.
- PC가 꺼지면 프롬프트·시드·설정 없이 이미지·보관 구분·태그만 보여 주는 읽기 전용 오프라인 갤러리를 엽니다.
- 오프라인 상세 보기에서는 다운로드만 허용하고, 핀치 확대·화면맞춤 상태 좌우 넘김·아래 스와이프 닫기를 지원합니다.
- Android 뒤로가기를 누르면 서버 주소를 변경할 수 있습니다.
- PC 전용 토큰·저장소 설정 API는 기존 백엔드 정책에 따라 Android에서 열리지 않습니다.
- PC 설정에서 기기 승인을 해제하면 다음 API 요청부터 다시 승인 화면으로 돌아갑니다.

## 빌드

JDK 17, Android SDK Platform 36, Build Tools 36.0.0이 필요합니다.

```powershell
.\gradlew.bat testDebugUnitTest lintSideload assembleSideload
```

생성된 개인 설치용 APK는 `app/build/outputs/apk/sideload/app-sideload.apk`에 있습니다. 이 빌드는 디버깅 기능이 꺼져 있지만 로컬 디버그 키로 서명되므로 개인 사이드로드용입니다. Play Store 배포에는 사용자가 관리하는 릴리스 서명 키와 스토어 등록이 별도로 필요합니다.
