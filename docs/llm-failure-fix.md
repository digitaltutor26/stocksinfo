# LLM 장애 대응 결과

## 문제와 변경

고정 무료 모델의 제공 중단으로 `interpret_signals`가 실패하면 `build_email`이 중단되고 정상 브리핑 대신 오류 알림이 발송되었다.

- `summarizer/openrouter_client.py`: 고정 모델 목록 대신 `openrouter/free`를 사용한다. 현재 이용 가능한 무료 모델로 라우팅하며 유료 모델로 전환하지 않는다. 기존 뉴스 기반 종목 발굴 함수와 import 시 API 키 방어 처리는 보존한다.
- `main.py`: 해설 호출 경계에서 예외를 로그에 기록하고, 해설 생략 안내를 포함한 결정론적 브리핑을 생성한다. 스냅샷·대시보드 저장과 발송 경로를 유지한다.
- `tests/test_main.py`: LLM 전체 실패 시 리포트 보존 및 main 파이프라인의 발송·저장 지속을 검증한다.
- `tests/summarizer/test_openrouter_client.py`: 폴백 순회 테스트에 테스트용 모델 목록을 주입한다.

참고: https://openrouter.ai/docs/guides/routing/routers/free-router

## 검증

기준 원본 커밋: `9859b5edb7826f35dde0ec767331a77125d7e13d`.

- 수정 전 장애 재현 테스트: 2 failed, 32 passed. 기존 RuntimeError 전파 확인.
- 수정 후 `python3 -m pytest tests/ -q`: **184 passed, 1 warning** (1.76초).
- `git diff --check`: 통과.
- 기존 LibreSSL/urllib3 환경 경고 1건. 실제 API 및 SMTP는 모킹했으며 실발송하지 않았다.

## 운영 적용과 남은 사항

이 기록은 PR 검증 결과이며 운영 해결 완료를 의미하지 않는다. 원본 저장소 main에 병합한 뒤 해당 커밋으로 Actions를 실행하고 정상 브리핑 수신을 확인해야 한다. 무료 라우터도 한도·가용성 문제로 실패할 수 있으나 이 경우 해설 없이 브리핑을 생성한다. 데이터 수집·SMTP 등 별도 장애는 이번 수정 대상이 아니다.
