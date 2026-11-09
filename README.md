# AI Global Pipeline

Claude Code · Gemini CLI · Antigravity(agy) · Codex 4개 AI 코딩 CLI가 **같은 유지보수 절차**를 따르게 하는 규칙·훅·검사 도구 모음이다.

- **5단계 파이프라인(Node 1~5):** 문서 스캔 → 작업 브랜치 → 수정·검증 루프(최대 3회) → 사람 승인 게이트 → rebase + fast-forward 반영
- **Node 4 승인 게이트:** bypass/yolo 모드에서도 `git push`·`merge`·`rebase`·파일 삭제 같은 명령이 사람의 승인 없이 실행되지 않게 도구마다 훅·정책으로 막는다
- **[Handoff]:** Claude가 계획하고 agy가 구현한 뒤 Claude가 리뷰·테스트하는 무인 분담 흐름
- **프롬프트 스킬 5개:** `/vc-investigate` · `/vc-bugfix` · `/vc-feature` · `/vc-review` · `/vc-perf`
- **동기화 테스트:** 도구마다 흩어진 훅·설정·규칙 사본이 서로 어긋나지 않는지 검사하고, 어긋나면 사용 중인 에이전트에게 알린다

> 개인 환경(Windows + Orca 다중 계정)에서 쓰는 설정을 그대로 정리한 것이다. 경로와 계정 ID는 자리표시자로 바꿨으므로 쓰려면 아래 "실제 설치 위치"에 맞춰 직접 배치한다.
>
> **필요 조건:** Windows(경로를 `~\.claude`처럼 역슬래시로 쓴다), PATH에서 실행되는 `python`(Python 3, 3.12.10으로 확인). 모든 훅과 스크립트는 표준 라이브러리만 쓴다.

## 구성

| 경로 | 내용 | 실제 설치 위치 |
|---|---|---|
| `pipeline/ai-global-pipeline.md` | 파이프라인 규칙 마스터 | `~/.ai-global-pipeline.md` → 각 도구 전역 규칙 파일(`~/.claude/CLAUDE.md`, `~/.gemini/GEMINI.md`, `~/.codex/AGENTS.md`, Orca Codex 홈 `AGENTS.md`) 뒷부분에 `sync_pipeline_rules.py`가 복사 |
| `ai-gate/` | 동기화 테스트·사후 훅·스크립트, 자세한 설명은 [`ai-gate/README.md`](ai-gate/README.md) | `~/.ai-gate/` |
| `ai-gate/prompt-skills/` | 프롬프트 스킬 마스터 | `~/.ai-gate/prompt-skills/` → `sync_prompt_skills.py`가 `~/.claude/skills`, `~/.codex/skills`, Orca Codex 홈 `skills`로 복사 |
| `hooks/claude/node4-approval-gate.py` | Claude PreToolUse 게이트(`ask`) | `~/.claude/hooks/` |
| `hooks/agy/node4-approval-gate-agy.py` | agy PreToolUse 게이트(`deny`) | `~/.gemini/config/hooks/` |
| `hooks/codex/node4-approval-gate-codex.py` | Codex 기록 전용 훅 | `~/.codex/hooks/` |
| `config/claude/settings.gate-snippet.json` | Claude `settings.json`의 `permissions.ask/deny`·`hooks` 부분 | `~/.claude/settings.json`에 병합 |
| `config/gemini/ai-global-pipeline.toml` | Gemini 정책(`ask_user`) | `~/.gemini/policies/` |
| `config/gemini/settings.hooks-snippet.json` | Gemini `settings.json`의 `hooks` 부분 | `~/.gemini/settings.json`에 병합 |
| `config/agy/hooks.json` | agy 훅 등록 | `~/.gemini/config/hooks.json` |
| `config/agy/settings.deny-snippet.json` | agy deny 정규식(훅과 별개인 두 번째 방어선) | `~/.gemini/antigravity-cli/settings.json`에 병합 |
| `config/codex/default.rules`, `config/codex/hooks.json` | Codex execpolicy 규칙(`prompt`)·훅 등록 | `~/.codex/rules/`, `~/.codex/` |

## 자리표시자

| 자리표시자 | 바꿀 값 |
|---|---|
| `C:/Users/<you>/` (JSON 설정) | 본인 홈 경로 |
| `ORCA_CODEX_ACCOUNT_ID` 환경변수 (`<orca-codex-account-id>`) | Orca를 쓰는 경우 `%APPDATA%\orca\codex-accounts\<id>`의 id. Orca를 쓰지 않으면 아래 "Orca 없이 쓰기"를 따른다 |
| `.orca/agent-hooks/*` 훅 항목 | Orca 상태 표시용. Orca를 쓰지 않으면 지운다 |

## 처음 설치할 때

`sync_pipeline_rules.py`는 대상 파일마다 줄 머리의 `# Global Maintenance Pipeline` 제목이 **정확히 1개** 있어야 그 제목부터
파일 끝까지를 마스터로 바꾼다. 파일이 없거나 제목이 없으면 고치지 않고 오류로 보고한다.
그래서 처음에는 각 대상 파일(없으면 새로 만든다) 끝에 아래 한 줄을 넣은 뒤 실행한다. 제목 앞에 있던 내용은 그대로 남는다.

```markdown
# Global Maintenance Pipeline
```

```powershell
python $HOME/.ai-gate/sync_pipeline_rules.py --check   # 쓰지 않고 검사만. 다르면 종료 코드 1
python $HOME/.ai-gate/sync_pipeline_rules.py          # 다른 사본만 갱신
python $HOME/.ai-gate/sync_prompt_skills.py           # 프롬프트 스킬 사본 갱신
```

## Orca 없이 쓰기

검사·동기화 스크립트는 Orca 경로(Claude 프로필 `settings.json`, Codex 홈의 `hooks.json`·`rules`·`AGENTS.md`·`skills`)를
기본 대상으로 삼고, 없으면 건너뛰지 않고 실패한다. Orca를 쓰지 않으면 아래 사용자 환경변수로 대상을 바꾼다.
훅도 이 값을 읽어야 하므로 셸에서만 두지 말고 `setx`로 사용자 환경변수에 넣은 뒤 CLI를 다시 띄운다.

```powershell
setx NODE4_ORCA_CLAUDE_SETTINGS "$HOME\.claude\settings.json"   # Orca 프로필 대신 전역 settings 와 비교
setx NODE4_ORCA_CODEX_HOME "$HOME\.codex"                        # Orca Codex 홈 대신 전역 ~/.codex 와 비교
setx NODE4_PIPELINE_TARGETS "$HOME\.claude\CLAUDE.md;$HOME\.gemini\GEMINI.md;$HOME\.codex\AGENTS.md"
setx NODE4_PROMPT_SKILLS_TARGETS "$HOME\.claude\skills;$HOME\.codex\skills"
```

이렇게 해도 `CodexHomeInSyncTest.test_rules_mirrored` 1개는 실패한다. Orca가 `~/.codex/rules/*.rules`를
`_orca-global-<이름>`으로 복사해 둔 파일을 찾는 검사라서다. `ai-gate/test_gate_hooks_in_sync.py`에서 이 메서드를 지우고,
`ai-gate/README.md`의 테스트 개수("동기화 테스트(N개)")를 하나 줄인다(`ReadmeInSyncTest`가 개수를 대조한다).
위 설정으로 실행하면 이 1개 말고는 모두 통과하는 것을 확인했다(2026-11-10, 29개 중 28개 통과).

## 확인

```powershell
python $HOME/.ai-gate/test_gate_hooks_in_sync.py -v   # 설치한 ~/.ai-gate 사본으로 실행. 실제 설치 위치의 훅·설정을 검사한다
```

## 알려진 한계

- `python -c`, `node -e`, 변수, git alias로 감싼 명령은 게이트가 문자열로 감지하지 못한다(규칙 문서로만 금지).
- Codex는 `git -C <경로> merge`처럼 옵션이 앞에 붙은 명령을 prefix 규칙으로 막지 못한다.
- agy는 `--dangerously-skip-permissions`에서 settings의 `ask`를 무시한다(`deny`는 지킨다).

## 라이선스

[MIT](LICENSE)
