# 구현 결과

## 변경한 파일과 내용

`docs/requirements.md`의 FR-01·FR-04 및 `docs/next-task.md`의 계획 범위 안에서 구현했다. 작업 시작 시 기존 수정 파일은 없었다.

| 파일 | 변경 내용 |
| --- | --- |
| `main.py` | 미사용 시황 수집기 import·호출 제거. 거시 일정은 항상, 관심종목 위치·펀더멘털은 종목이 있을 때만 수집하며 거시 일정 내부 오류와 수집기 예외를 `_errors`에 유지한다. 지정된 컨텍스트 키 상수를 추가하고 신호에 뉴스 최대 3건, 위치·펀더멘털을 첨부한다. `None` 지표와 오류 데이터를 제외하며 기존 2인자 호출을 지원한다. `build_email`에서 LLM과 리포트로 데이터를 연결한다. |
| `report.py` | `format_position_summary` 추가. 유효한 지표만 지정된 순서·소수점·부호로 출력한다. 기존 호출과 호환되는 선택 인자를 추가하고 빨강·노랑 신호 바로 아래에 공백 4칸과 `└ `로 요약을 출력한다. 유효 지표가 없으면 기존 출력을 유지한다. |
| `summarizer/openrouter_client.py` | `position`·`fundamentals` 수치를 인용하여 중장기 맥락을 설명하고, 없는 숫자는 계산하거나 창작하지 않도록 프롬프트를 보강한다. |
| `tests/test_main.py` | 활성 수집기만 호출, 빈 관심종목, 오류 병합, LLM 컨텍스트 및 리포트 연결, 뉴스 개수 제한, 키 필터링, 0 유지, `None` 제외, 입력 보존, 오류 데이터·기존 호출 호환성을 검증한다. |
| `tests/test_report.py` | 전체·부분 지표 포맷, 빈 값·오류·0, 데이터 소스별 독립 처리, 빨강·노랑 신호 요약, 컨텍스트 없는 기존 출력 호환성을 검증한다. |
| `docs/implementation-result.md` | 변경 내용, 검증 결과, 남은 제한을 기록한다. |

보조 수집기 파일과 해당 단위 테스트는 보존했다. 신호 0건 시 LLM을 호출하지 않는 기존 동작도 유지했다.

## 실행한 테스트와 결과

- 변경 전 `python3 -m pytest tests/ -q`: **80 passed, 1 warning**.
- 변경 후 `python3 -m pytest tests/ -q`: **94 passed, 1 warning** (1.44초).
- `PYTHONPYCACHEPREFIX=/private/tmp/tai-stock-pycache python3 -m compileall -q main.py report.py summarizer/openrouter_client.py tests/test_main.py tests/test_report.py`: 성공. 기본 캐시 경로 쓰기는 샌드박스 권한으로 실패하여 캐시 출력을 허용된 임시 디렉터리로 지정해 재검증했다.
- `git diff --check`: 통과.

이 환경에는 `python` 명령이 없어 명세의 `python -m pytest tests/ -q`를 동일한 모듈 실행 방식인 `python3 -m pytest tests/ -q`로 실행했다. 별도 lint·typecheck 설정은 저장소에 없어 구문 컴파일과 diff 검사를 수행했다.

## 미해결 사항

- 계획된 기능의 미해결 사항은 없다.
- 기존 환경 경고 1건: Python 3.9.6의 LibreSSL 2.8.3에 대해 urllib3 v2가 `NotOpenSSLWarning`을 출력한다. 변경 전·후 동일하며 테스트 실패는 없다. 환경 변경은 이번 범위에서 제외했다.
- 외부 데이터 API·실제 OpenRouter 응답·SMTP 발송은 실연동하지 않았다. 테스트에서는 해당 외부 호출을 모킹해 기능과 회귀 동작을 검증했다.

## 추가 장애 대응: 무료 LLM 모델 404

사용자가 제공한 GitHub Actions 오류 로그에서 `interpret_signals`의 모든 모델 시도 실패가 `build_email` 밖으로 전파되어 정상 브리핑 대신 오류 알림을 발송하는 경로를 확인했다. 마지막 모델 `openai/gpt-oss-20b:free`의 무료 제공 중단이 404로 보고되었다. 앞선 모델의 개별 실패 원인은 제공된 로그만으로 확정할 수 없다.

이 변경은 최초 next-task 계획 밖의 장애 대응이며, 수정 전 대화에서 범위와 처리 방식을 설명했다. 앞선 구현 변경을 보존했다.

- `summarizer/openrouter_client.py`: 고정 무료 모델 목록을 `openrouter/free`로 교체했다. [OpenRouter 공식 문서](https://openrouter.ai/docs/guides/routing/routers/free-router)에 따라 현재 이용 가능한 무료 모델로 라우팅한다. 유료 모델로 자동 전환하지 않는다.
- `main.py`: LLM 해설 호출 예외를 해당 호출 경계에서 기록하고, AI 해설 생략 안내와 기존 결정론적 신호·위치 요약·일정·면책문을 포함한 브리핑을 계속 생성한다. 수집·저장·SMTP 오류 처리 경로는 유지한다.
- `tests/test_main.py`: 전체 모델 실패 시에도 리포트 내용이 보존되고 원본 오류는 로그에만 기록되는 테스트, `main()`이 오류 알림 대신 정상 브리핑을 발송 함수로 전달하는 통합 테스트를 추가했다.
- `tests/summarizer/test_openrouter_client.py`: 운영 모델 목록 개수와 무관하게 폴백 순회 테스트가 의미를 유지하도록 테스트용 모델 2개를 주입했다.

검증:

- 수정 전 추가한 실패 재현 테스트: **1 failed, 15 passed**. 원래의 `RuntimeError` 전파를 재현했다.
- 수정 후 `python3 -m pytest tests/ -q`: **96 passed, 1 warning**, 1.33초.
- 변경 Python 파일의 `compileall` 검사 및 `git diff --check`: 통과.

남은 제한: 무료 라우터도 가용성·한도에 따라 실패할 수 있으나 이 경우 해설 없이 브리핑을 생성한다. 실제 API·SMTP는 모킹했으며 실발송을 검증하지 않았다. GitHub Actions에 반영하려면 이번 로컬 변경을 커밋·푸시해야 한다. 이번 작업에서 원격 반영이나 워크플로 실행은 수행하지 않았다. 기존 LibreSSL 경고는 동일하다.
