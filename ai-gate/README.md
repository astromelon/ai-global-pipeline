# ~/.ai-gate — AI CLI 공용 게이트·규칙 동기화 도구

Claude Code·Gemini CLI·Antigravity(agy)·Codex 4개 CLI가 같은 **글로벌 유지보수 파이프라인**(Node 1~5)과
**Node 4 승인 게이트**를 지키도록 하는 스크립트와 테스트를 모아 둔 폴더다.
bypass/yolo 모드에서도 push·merge·rebase·삭제 같은 명령이 승인 없이 실행되지 않게 막는 장치가 도구마다 흩어져 있다.
이 폴더의 스크립트는 그 장치들이 서로 어긋나지 않는지 검사하고, 어긋나면 알린다.

## 파일

| 파일 | 역할 |
|---|---|
| `test_gate_hooks_in_sync.py` | 동기화 테스트(31개). 게이트 훅·설정·규칙·스킬 사본이 서로 맞는지 검사한다 |
| `sync_test_hook.py` | 4개 CLI 공용 사후 훅. 감시 파일이 바뀌면 테스트를 돌리고, 실패나 자동 갱신을 에이전트에게 알린다 |
| `sync_pipeline_rules.py` | 마스터 규칙을 각 도구의 전역 규칙 파일 뒷부분에 반영한다 |
| `prompt-skills/<이름>/SKILL.md` | 프롬프트 스킬 마스터 5개(`vc-investigate` 조사만, `vc-bugfix` 원인+회귀 테스트, `vc-feature` 범위 정한 구현, `vc-review` 합치기 전 검토, `vc-perf` 측정 기반 성능). 사용자 호출 전용(`disable-model-invocation: true`). Claude는 `/vc-bugfix <설명>`, Codex는 `$vc-bugfix <설명>`(또는 `/skills`)로 부른다. 고칠 때는 이 마스터만 고친다 |
| `export_public_repo.py` | 실제 설정을 공개 저장소(기본 `C:\dev\ai-global-pipeline`)로 내보낸다. 홈 경로·Orca 계정 ID는 자리표시자로, 사내 고유 값은 비공개 `export-private.json`의 치환표로 바꾸고, 결과에 그런 값이 남으면 쓰지 않고 실패한다. `export-private.json`이 없으면 실패한다(`--no-private`로만 생략 가능). `--check` 차이만 보기(저장소에만 있는 파일도 종료 코드 1), `--test` 저장소 사본의 훅·정책으로 테스트까지. 스니펫에는 게이트·동기화 훅만 담는다. 커밋·push·삭제는 하지 않는다 |
| `export-private.json` | 내보내기용 사내 고유 값 치환표와 금지어. 내보내지 않는다 |
| `sync_prompt_skills.py` | 프롬프트 스킬 마스터를 `~/.claude/skills`(Orca Claude 프로필은 이 폴더 링크), `~/.codex/skills`, Orca Codex 홈 `skills`에 복사한다. `--check`는 검사만 |
| `gate_report.py` | Claude·agy·Codex 게이트 로그를 합쳐 최근 차단 내역을 보여 준다 |
| `scan_allow_overlap.py` | Claude settings(전역·Orca 프로필·`C:\workspace`·`C:\dev` 저장소)의 `allow` 규칙 중 게이트 대상 명령(push·merge·삭제·`checkout --` 등)까지 허용하는 것을 찾는다. `--fix`는 지우고 원본을 `allow-backups/`에 백업한다. "항상 허용"으로 쌓이기 쉬우니 가끔 돌린다 |
| `bench_sync_hook.py` | 동기화 훅이 변경 없을 때 호출마다 쓰는 시간을 잰다(아래 "성능") |
| `.sync-test-mtimes.json` | 감시 파일 수정 시각 상태(도구끼리 공유). 지워도 된다. 다음 호출 때 기록만 하고 넘어간다 |
| `.sync-events.json` / `.sync-sessions/` / `.sync-test.lock` | 테스트 결과 이벤트, 세션별 마지막 수신 번호, 동시 실행 잠금(아래 "동기화 훅") |
| `sync-test-hook.log` | 동기화 훅이 테스트를 실제로 돌린 기록(JSONL) |
| `bak-archive-20261109.zip` | 2026-11-09에 정리한 옛 `.bak*` 설정 백업 37개(사용자 폴더 기준 경로) |

## 자주 쓰는 명령

```powershell
# 동기화 테스트 전체 / 한 묶음만
python $HOME/.ai-gate/test_gate_hooks_in_sync.py -v
python $HOME/.ai-gate/test_gate_hooks_in_sync.py ClaudeSettingsInSyncTest

# 최근 게이트 차단 내역
python $HOME/.ai-gate/gate_report.py                  # 최근 20건
python $HOME/.ai-gate/gate_report.py --since 24h --tool agy
python $HOME/.ai-gate/gate_report.py -n 100 --json

# 파이프라인 규칙 사본 검사 / 갱신
python $HOME/.ai-gate/sync_pipeline_rules.py --check  # 쓰지 않음. 다르면 종료 코드 1
python $HOME/.ai-gate/sync_pipeline_rules.py          # 다른 사본만 갱신

# 프롬프트 스킬 사본 검사 / 갱신
python $HOME/.ai-gate/sync_prompt_skills.py --check
python $HOME/.ai-gate/sync_prompt_skills.py

# 공개 저장소로 내보내기 (차이 확인 → 반영 + 저장소 사본 테스트). 커밋·push 는 따로
python $HOME/.ai-gate/export_public_repo.py --check
python $HOME/.ai-gate/export_public_repo.py --test
```

## 게이트 장치 위치

| 도구 | 장치 | bypass 모드 동작 |
|---|---|---|
| Claude | `~/.claude/hooks/node4-approval-gate.py`(PreToolUse `ask`) + `permissions.ask`. 전역 `~/.claude/settings.json`과 Orca 프로필 `settings.json` 양쪽에 등록 | 확인창이 뜬다 |
| Gemini | `~/.gemini/policies/ai-global-pipeline.toml`(`ask_user`, priority 900) | "denied by policy" |
| Codex | `~/.codex/rules/default.rules`(`prompt`) + 기록 전용 훅 `~/.codex/hooks/node4-approval-gate-codex.py` | 거부. 단 `git -C . merge`처럼 옵션이 앞에 붙으면 비켜 간다 |
| agy | `~/.gemini/config/hooks/node4-approval-gate-agy.py`(PreToolUse `deny`) + `antigravity-cli/settings.json`의 deny 정규식 12개(두 번째 방어선. 훅이 빠지거나 실패해도 막는다) | 거부. settings의 `ask`는 skip-permissions에서 무시되지만 `deny`는 지켜진다 |

게이트 대상(2026-11-09 보강): 기존 목록에 `git.exe`, 경로를 붙인 `rm`, PowerShell 별칭 `ri`·`erase`, `[IO.File]`/`[IO.Directory]::Delete`, `Start-Process git`, `git switch --discard-changes`/`-f`, `glab api` 쓰기 요청(-X PUT/POST/PATCH/DELETE), `gh pr merge`를 더했다. `python -c`·`node -e`·변수·git alias를 거치는 우회는 문자열로 확실히 잡을 수 없어 규칙 문서의 "차단 우회 금지"에 맡긴다.
훅 자체가 오류를 내면 입력에 게이트 관련 단어가 있을 때만 막는다(Claude는 확인창, agy는 거부). agy 훅은 모든 도구 호출에 걸리므로, 오류 때 무조건 막으면 훅 버그 하나로 agy 전체가 멈출 수 있기 때문이다.

게이트 로그는 각 훅 옆의 `*.log`(JSONL, 1MB 회전, 자격증명 가림)에 남는다. `gate_report.py`가 이를 합쳐 보여 준다.

## 동기화 테스트가 검사하는 것

| 묶음 | 검사 내용 |
|---|---|
| `GateHooksInSyncTest` | 세 훅(Claude·agy·Codex)의 `GATED`·따옴표 처리·`REDACTIONS`·로그 한도가 같은지. 표본 명령 약 100개를 같게 판정하는지(`merge-base` 오탐, 따옴표 속 문자열, `bash -lc`·`git "push"`·`xargs rm` 같은 우회 변형 등). 자격증명을 가리는지 |
| `GeminiPolicySafetyTest` | Gemini 정책 TOML 문법, 정규식 컴파일 여부, 중첩 반복자(Gemini가 ReDoS로 거부), 한 규칙에 `commandPrefix`와 `commandRegex`를 함께 썼는지 |
| `HookOutputEncodingTest` | Claude·agy 훅 stdout이 ASCII JSON인지. cp949 한글 때문에 agy가 `invalid UTF-8`로 멈춘 장애의 재발 방지 |
| `ClaudeSettingsInSyncTest` | Claude 전역 `settings.json`과 Orca의 모든 Claude 프로필(계정마다 1개) `settings.json`의 권한과 훅이 같은지(순서 무관). 게이트 훅과 동기화 훅이 등록돼 있는지 |
| `CodexHomeInSyncTest` | 전역 `~/.codex`와 Orca Codex 홈의 `hooks.json`(Orca 상태 훅은 예외), `rules/*.rules`와 Orca `_orca-global-*` 복사본이 같은지 |
| `AgyGeminiHooksRegisteredTest` | agy `config/hooks.json`에 게이트 훅(PreToolUse, matcher `*`)과 동기화 훅(PostInvocation)이, Gemini `settings.json`에 동기화 훅(AfterTool)이 등록돼 있는지. Orca가 파일을 다시 써서 훅이 빠지는 경우를 잡는다 |
| `AgyDenyRulesTest` | agy `settings.json`의 deny 정규식(훅과 별개인 두 번째 방어선)이 표본 명령을 의도대로 판정하는지, RE2에서 못 쓰는 전후방 탐색이 없는지 |
| `PipelineRulesInSyncTest` | 파이프라인 규칙 사본 4개가 마스터와 같은지 |
| `PromptSkillsInSyncTest` | 프롬프트 스킬 사본(Claude·Codex·Orca Codex)이 마스터와 같은지. frontmatter의 `name`이 폴더 이름과 같고 `description`(1024자 이하)·`disable-model-invocation: true`·`$ARGUMENTS`가 있는지 |
| `ReadmeInSyncTest` | 이 README의 테스트 묶음 표와 테스트 개수가 실제 코드와 같은지. 묶음이나 테스트를 추가하면 이 표와 파일 표의 개수를 함께 고친다 |

경로 덮어쓰기용 환경변수(검증용): `NODE4_CLAUDE_HOOK`, `NODE4_AGY_HOOK`, `NODE4_CODEX_HOOK`,
`NODE4_GEMINI_POLICY_DIR`, `NODE4_CLAUDE_SETTINGS`, `NODE4_ORCA_CLAUDE_SETTINGS`, `NODE4_CODEX_HOME`,
`NODE4_ORCA_CODEX_HOME`, `NODE4_PIPELINE_MASTER`, `NODE4_PIPELINE_TARGETS`(`;` 구분), `NODE4_AI_GATE_README`,
`NODE4_PROMPT_SKILLS_MASTER`, `NODE4_PROMPT_SKILLS_TARGETS`(`;` 구분).
동기화 훅을 실제 세션과 섞이지 않게 시험하려면 `NODE4_SYNC_STATE_DIR`로 상태·이벤트·세션·잠금·로그 위치를 임시 폴더로 바꾼다.

## 동기화 훅 (`sync_test_hook.py`)

도구 호출이 끝날 때마다 감시 파일의 수정 시각을 확인한다. 바뀐 것이 없으면 아무것도 하지 않는다.

- **감시 대상:**
  - 게이트 훅 3개, 이 폴더의 테스트·스크립트·README
  - Gemini 정책 `*.toml`
  - Claude settings(전역 + Orca의 모든 Claude 프로필), Codex `hooks.json` 2개
  - Codex rules(전역 `*.rules`, Orca `_orca-global-*.rules`)
  - 마스터 규칙과 그 사본 4개
  - 프롬프트 스킬 마스터(`prompt-skills/*/SKILL.md`)와 사본
- **마스터가 바뀌면:** 먼저 `sync_pipeline_rules.py`로 사본을 갱신한 뒤 테스트를 돌린다. 프롬프트 스킬 마스터가 바뀌거나 사본이 없어지면 `sync_prompt_skills.py`로 같은 방식으로 갱신한다.
- **한 번만 실행:** 감지·갱신·테스트는 전체에서 한 번만 한다. 여러 세션이 같은 변경을 동시에 봐도 잠금 파일(`.sync-test.lock`)로 한 프로세스만 돌린다. 결과는 이벤트(`.sync-events.json`, 최근 100건)로 남는다.
- **알림은 세션마다 한 번:** 세션 키는 형식과 훅 입력의 세션 id를 합친 것이다(Claude·Codex·Gemini는 `session_id`, agy는 `conversationId`). 세션마다 마지막으로 받은 이벤트 번호를 `.sync-sessions/<키>.json`에 둔다(7일 쓰지 않으면 정리).

  | 세션 | 받는 것 |
  |---|---|
  | 이미 알던 세션 | 마지막으로 받은 뒤 생긴 이벤트. 최신이 실패면 실패 알림, 아니면 그사이 자동 갱신 알림. 실패 뒤 통과로 이미 풀린 실패는 받지 않는다 |
  | 처음 보는 세션 | 지난 이벤트는 건너뛴다(시작할 때 최신 규칙을 읽었으므로). 단 지금 실패 상태면 받고, 이번 호출이 직접 만든 이벤트도 받는다 |
  | 세션 id 없는 입력 | 이번 호출이 직접 만든 이벤트만 받는다 |

- **결과별 알림:**

  | 결과 | 알림 |
  |---|---|
  | 통과, 갱신 없음 | 출력 없음 |
  | 통과, 사본 자동 갱신 | 막지 않는 알림(갱신 목록, "새 세션부터 적용") |
  | 실패 | 실패 요약으로 알림(Claude·Codex는 `decision: block`) |

- **도구별 등록과 출력 형식:**

  | 도구 | 등록 위치 | 실패 | 자동 갱신 알림 |
  |---|---|---|---|
  | Claude | 전역·Orca 프로필 `settings.json`의 PostToolUse, `--format claude` | `decision: block` + `additionalContext` | `additionalContext` + `systemMessage` |
  | Codex | 두 `hooks.json`의 PostToolUse, `--format codex` | Claude와 같음 | Claude와 같음 |
  | Gemini | `~/.gemini/settings.json`의 AfterTool, `--format gemini` | `additionalContext` + `systemMessage` | 같음 |
  | agy | `~/.gemini/config/hooks.json`의 PostInvocation, `--format agy` | `injectSteps[].ephemeralMessage` | 같음 |

- 훅 자체 오류는 삼켜서 일반 작업을 막지 않는다. Codex 훅은 Codex 화면의 `/hooks`에서 신뢰 승인을 해야 실행된다.

## 운영 절차

**파이프라인 규칙을 고칠 때**
마스터 `~/.ai-global-pipeline.md`만 고친다. 다음 도구 호출 때 훅이 아래 4곳의 `# Global Maintenance Pipeline` 제목부터 끝까지를 바꾸고 알린다.
- `~/.claude/CLAUDE.md`
- `~/.gemini/GEMINI.md`
- `~/.codex/AGENTS.md`
- Orca Codex `AGENTS.md`

제목 앞부분(CLAUDE.md의 기존 규칙, Orca AGENTS.md의 DDIA)은 보존한다. 갱신 전 상태는 `<파일>.bak-pipeline-sync`에 1개 남는다. 실행 중인 세션은 새 규칙을 다시 읽지 않는다.

**게이트 대상 명령을 바꿀 때**
아래를 같은 내용으로 함께 고친 뒤 테스트를 돌린다.
- 세 훅의 `GATED`
- Claude `permissions.ask`(settings 두 곳)
- Gemini 정책 toml
- Codex `default.rules`
- agy `settings.json`의 `deny` 정규식

`SAMPLE_COMMANDS`에 새 표본도 넣는다. Gemini 정규식에는 중첩 반복자를 쓰지 말고 단순 정규식 여러 개로 나눈다.

**Codex rules를 고칠 때**
`~/.codex/rules/default.rules`를 고친 뒤 Orca에서 Codex를 한 번 띄우면 `_orca-global-default.rules`가 바로(약 1초) 갱신된다. Orca 재시작은 필요 없다. 그 전까지는 `CodexHomeInSyncTest`가 불일치를 알린다.

**Orca Codex 홈의 다른 파일**
- `hooks.json`은 Orca가 Codex를 띄울 때 다시 쓰지만 우리 훅은 유지된다.
- `AGENTS.md`는 출처 기록(`.orca-resource-copies/AGENTS.md.json`)이 없는 사용자 파일이라 Orca가 덮어쓰지 않는다.
- 자체 `default.rules`("항상 허용"으로 쌓인 규칙)는 비교 대상이 아니다. 가끔 직접 점검한다.

## 성능 (동기화 훅, 감시 파일 변경 없음)

동기화 훅은 도구 호출마다 실행된다. 그래서 바뀐 것이 없을 때의 비용이 곧 호출당 추가 지연이다.
다시 재려면 `python $HOME/.ai-gate/bench_sync_hook.py`를 실행한다. 출력과 상태 파일은 바뀌지 않고, 테스트 실행 로그도 남지 않는다.

**2026-11-09 측정** (Windows 11, Python 3.12.10, 감시 파일 17개, 40회)

| 항목 | 중앙값 | 평균 | p95 | 최대 |
|---|---|---|---|---|
| 훅 1회(프로세스 기동 포함, 변경 없음) | 60.3ms | 62.0ms | 72.2ms | 87.0ms |
| 참고: 빈 Python 기동(`python -I -c pass`) | 33.6ms | 35.1ms | 45.4ms | 55.7ms |
| 참고: 프로세스 안 `current_mtimes()` | 1.4ms | | | |

- 훅 고유 비용은 약 27ms다. 대부분 모듈 import이고(`json` 약 15ms, `subprocess` 약 8ms, `glob` 약 1.5ms), 파일 수정 시각 확인은 1.4ms다.
- 세션별 알림으로 바꾼 뒤 다시 쟀다(같은 날, 다른 세션 부하로 기동 자체가 느린 시점). 빈 Python 기동이 64.8ms, 훅 1회가 83.2ms(중앙값)였다. 훅 고유 비용이 약 18ms로 이전과 비슷해, 세션 파일 확인에 따른 추가 비용은 측정 오차 안이었다. 측정 스크립트는 세션 id를 넣어 실제 호출과 같은 경로를 잰다.
- 줄일 여지는 두 가지다. `subprocess`를 변경이 있을 때만 import하거나, 상태 비교를 `json` 없이 하면 된다. 다만 합쳐도 호출당 20ms 안팎이라 지금은 그대로 둔다.
- 감시 파일이 바뀐 호출은 동기화 테스트 실행(1초 미만)이 더해진다. 마스터가 바뀐 호출은 사본 갱신까지 더해진다.

## 알려진 한계

- Codex `prefix_rule`은 `git -C . merge`처럼 옵션이 앞에 붙은 변형을 막지 못한다. Codex 훅은 기록만 한다.
- agy 터미널 샌드박스에서는 Java(surefire) 테스트가 멈춘다. Java 프로젝트의 Node 3 검증은 Claude나 Codex에서 한다.
- Claude 설정이나 훅을 바꾸면 이미 열린 세션에는 적용되지 않는다. 새 세션부터 적용된다.
