# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 이 저장소의 정체: "내보내기 결과물"이다

Claude Code·Gemini CLI·agy·Codex 4개 CLI가 같은 5단계 유지보수 파이프라인(Node 1~5)과 Node 4 승인 게이트를
지키게 하는 규칙·훅·검사 도구의 **공개용 사본**이다. 원본은 사용자 홈(`~/.ai-gate`, `~/.claude`, `~/.gemini`,
`~/.codex`, `~/.ai-global-pipeline.md`)에 있고, `ai-gate/export_public_repo.py`가 이 저장소로 복사한다.

- **`pipeline/`, `hooks/`, `config/`, `ai-gate/` 아래 파일을 여기서 직접 고치면 다음 내보내기 때 덮어써진다.**
  고칠 때는 원본을 고친 뒤 내보낸다. 저장소↔원본 대응은 `export_public_repo.py`의 `FILES`, `snippets()`, 그리고
  루트 `README.md`의 "구성" 표에 있다.
- `config/*/*-snippet.json`은 실제 settings 파일에서 게이트 관련 키만 뽑은 것이다(`snippets()`).
- 내보내기가 관리하지 않는 파일: 루트 `README.md`, `LICENSE`, `.gitignore`, 이 `CLAUDE.md`. 이들은 여기서 직접 고친다.
- 내보낼 때 홈 경로·Orca 계정 ID는 자리표시자(`os.path.expanduser(r"~\...")`, `C:/Users/<you>/`,
  `ORCA_CODEX_ACCOUNT_ID`, `<orca-claude-profile-id>`)로 바뀌고, 비공개 `~/.ai-gate/export-private.json`의
  치환표·금지어가 적용된다. 결과에 홈 사용자명·계정 ID·금지어·토큰 형태가 남으면 쓰지 않고 종료 코드 3으로 실패한다.
  공개 저장소이므로 사내 고유 값(사내 저장소명·브랜치명 등)을 새로 넣지 않는다.

## 명령

Windows + Python 3.12, 외부 의존성 없음(표준 라이브러리만). 빌드 단계는 없다.

```powershell
# 내보내기 (원본 → 이 저장소). 커밋·push·삭제는 하지 않는다
python $HOME/.ai-gate/export_public_repo.py --check   # 차이만 보고, 다르면 종료 코드 1
python $HOME/.ai-gate/export_public_repo.py --test    # 반영 + 저장소 사본으로 동기화 테스트

# 동기화 테스트 전체 / 묶음 하나 / 테스트 하나 (unittest)
python ai-gate/test_gate_hooks_in_sync.py -v
python ai-gate/test_gate_hooks_in_sync.py GateHooksInSyncTest
python ai-gate/test_gate_hooks_in_sync.py GateHooksInSyncTest.test_verdict_on_sample_commands
```

테스트는 기본적으로 **설치된 위치**(`~/.claude/hooks/...`, `~/.gemini/...`, `~/.codex/...`)의 파일을 읽는다.
저장소 안의 훅을 대상으로 돌리려면 `NODE4_CLAUDE_HOOK`, `NODE4_AGY_HOOK`, `NODE4_CODEX_HOOK`,
`NODE4_GEMINI_POLICY_DIR` 등 환경변수로 경로를 바꾼다(전체 목록은 `ai-gate/README.md`). Orca 관련 묶음은
`ORCA_CODEX_ACCOUNT_ID`가 필요하다. README 표·스킬 마스터 검사는 스크립트 옆 파일(`__file__` 기준)을 읽는다.

## 큰 그림

- **규칙 마스터 → 사본:** `pipeline/ai-global-pipeline.md`(설치 위치 `~/.ai-global-pipeline.md`)를
  `sync_pipeline_rules.py`가 각 도구 전역 규칙 파일의 `# Global Maintenance Pipeline` 제목부터 끝까지에 복사한다
  (제목이 정확히 1개여야 함, 앞부분은 보존). 프롬프트 스킬 `ai-gate/prompt-skills/*/SKILL.md`도 같은 방식으로
  `sync_prompt_skills.py`가 Claude·Codex 스킬 폴더에 복사한다. 고칠 때는 마스터만 고친다.
- **Node 4 게이트는 도구마다 다른 장치로 같은 명령 목록을 막는다:** Claude 훅(`ask`) + `permissions.ask`,
  agy 훅(`deny`) + settings deny 정규식, Gemini 정책 TOML(`ask_user`), Codex execpolicy `default.rules`(`prompt`) +
  기록 전용 훅. 세 Python 훅은 `GATED`·따옴표 처리·`REDACTIONS`·로그 한도를 **각자 복사본으로** 들고 있다.
- **게이트 대상 명령을 바꿀 때**는 세 훅의 `GATED`, Claude `permissions.ask`, Gemini TOML, Codex `default.rules`,
  agy settings를 함께 고치고 `test_gate_hooks_in_sync.py`의 `SAMPLE_COMMANDS`에 표본을 추가한다.
- **동기화 테스트(`test_gate_hooks_in_sync.py`)** 가 위 사본들이 서로 어긋나지 않는지 검사하고,
  **`sync_test_hook.py`** 가 4개 CLI의 사후 훅으로 매 도구 호출마다 감시 파일 mtime을 보고, 바뀌면 사본 갱신 →
  테스트 → 세션별 1회 알림을 한다(잠금 파일로 한 프로세스만 실행). 이 훅은 호출마다 돌므로 변경이 없을 때의
  비용(import 포함)을 늘리지 않는다 — `bench_sync_hook.py`로 잰다.

## 지켜야 할 제약 (테스트가 강제)

- `ReadmeInSyncTest`: `ai-gate/README.md`의 테스트 묶음 표와 테스트 개수("동기화 테스트(N개)")가 코드와 같아야 한다.
  테스트·묶음을 추가하면 README 두 곳을 함께 고친다.
- Gemini 정책 정규식에 중첩 반복자 금지(Gemini가 ReDoS로 거부), 한 규칙에 `commandPrefix`와 `commandRegex` 동시 사용 금지.
- agy deny 정규식은 RE2라 전후방 탐색(lookaround) 금지.
- Claude·agy 훅 stdout은 ASCII JSON이어야 한다(cp949 한글로 agy가 `invalid UTF-8`로 멈춘 장애 재발 방지).
- 훅 자체 오류 시에는 입력에 게이트 관련 단어가 있을 때만 막는다(무조건 막으면 agy 전체가 멈춤).
- 프롬프트 스킬 frontmatter: `name` = 폴더명, `description` ≤ 1024자, `disable-model-invocation: true`, 본문에 `$ARGUMENTS`.

## 알려진 한계

`python -c`·`node -e`·변수·git alias로 감싼 명령은 문자열 판정으로 못 잡는다(규칙 문서로만 금지).
Codex는 `git -C . merge`처럼 옵션이 앞에 붙은 명령을 prefix 규칙으로 막지 못한다.
agy는 `--dangerously-skip-permissions`에서 settings의 `ask`를 무시한다(`deny`는 지킨다).
