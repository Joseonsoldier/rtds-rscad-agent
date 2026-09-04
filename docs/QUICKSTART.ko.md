# 한국어 시작 안내

이 프로젝트는 RTDS/RSCAD용 비공식 로컬 MCP 에이전트 도구입니다. 다른 사람의 Vector Store·API 키·실행 승인은 포함하지 않습니다. Windows, RSCAD FX 2.7.3, Python API 1.1, Python 3.12를 대상으로 한 초기 알파 버전입니다.

## 설치와 문서 검색

1. 저장소를 내려받고 Python 3.12 가상환경을 만듭니다. 실행 정책을 바꾸지 않아도 가상환경의 exe를 직접 사용할 수 있습니다.
2. `python -m pip install .`로 설치하고 `rtds-agent demo`로 합성 데모를 확인합니다. 이 데모는 실제 시뮬레이션이 아닙니다.
3. `rtds-agent init --rscad-home "자신의 RSCAD 절대 경로"`로 설정합니다. 기본 작업 데이터는 `%LOCALAPPDATA%\rtds-agent`에 저장됩니다.
4. `rtds-agent doctor`로 설치 파일과 API 호환성을 확인합니다. 장비 연결은 하지 않습니다.
5. `rtds-agent knowledge index`로 자신의 문서를 로컬 검색 DB로 만듭니다. Python API 문서는 init의 `--document-root`를 추가하거나 config.json의 document_roots에 해당 디렉터리를 지정합니다.
6. `rtds-agent mcp-config` 출력 내용을 MCP 호스트 설정에 추가합니다. 다른 서버 설정을 덮어쓰지 마세요.

각 명령은 가상환경을 활성화하지 않은 경우 `.\.venv\Scripts\rtds-agent.exe`로 실행합니다. 로컬 검색에는 API 키가 필요 없습니다. 클라우드 검색은 본인의 `OPENAI_API_KEY`와 `OPENAI_VECTOR_STORE_ID`를 MCP 호스트 환경변수에 전달한 경우에만 사용합니다.

## 자동 실행 설정

처음에는 Compile·Runtime이 비활성 상태입니다. 운영자가 허용 rack과 자동 실행 범위를 한 번 선택합니다.

```powershell
.\.venv\Scripts\rtds-agent.exe policy enable --actions compile offline_test runtime_start_stop runtime_controls --racks 1 2 --operator "운영자 이름" --acknowledge-simulation-control
```

위 rack 번호는 예시입니다. 사용 허가를 받은 번호로 바꾸세요. 이후 허용 범위 안에서는 실행마다 프로그램 내부 승인이나 CMD 확인을 요구하지 않습니다. 단, MCP 호스트나 운영체제의 보안 승인은 별개입니다.

스위치·슬라이더·다이얼·Runtime 입력·지원되는 LockFree 제어에는 정확한 대상과 초깃값이 필요합니다. 변경값 확인, 원상복구, 정지와 정리 결과를 기록합니다. 외부 장비 I/O, 배포, rack 구성, 원본 덮어쓰기는 허용되지 않습니다. 실제 장비와 연결된 환경은 기관의 별도 안전 절차를 따라야 합니다.

권한 철회: `rtds-agent policy disable --operator "운영자 이름"`. 이 명령은 긴급 정지 명령이 아닙니다. 실행 중에는 정책 변경보다 [수동 중지·복구 절차](SAFETY.md)를 따르세요.

## 에이전트에게 요청하는 예

- “로컬 문서에서 이 Runtime 오류 문구를 찾고 원문 페이지와 함께 설명해줘.”
- “설정된 source_root 안의 이 RTFX를 검사하고 파라미터와 연결 구조를 요약해줘.”
- “테스트 목적에 맞는 문서 근거와 측정 채널을 확인한 뒤 작업 사본을 준비해줘.”
- “허용된 rack으로 컴파일하고, 준비한 요청으로 Runtime을 실행해서 원시 데이터를 확인해줘.”

원하는 파라미터를 편집하기 전 `rtds-agent knowledge parameters --project "프로젝트의 절대 경로.rtfx"`로 해당 프로젝트에서 사용한 component의 정의 DB를 만듭니다. 이 절차는 로컬 정의를 파싱한 것이며 시뮬레이션 검증을 대신하지 않습니다.

최초 실제 실행 전에는 분리된 시험 환경에서 사용자가 검증해야 합니다. 이전 개발자의 실험 통과 기록은 공개본에 포함되거나 자동 승계되지 않습니다. 상세한 Runtime 입력 형식은 [WORKFLOWS.md](WORKFLOWS.md)를 참고하세요.
