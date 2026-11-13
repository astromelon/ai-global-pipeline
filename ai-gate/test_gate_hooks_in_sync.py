"""Node 4 게이트 훅 동기화·판정 테스트.

Claude·agy·Codex 훅은 같은 판정 목록(GATED), 따옴표 처리 규칙, 자격증명 가림 목록(REDACTIONS)을
각자 들고 있다. 한쪽만 고치면 도구마다 게이트 범위·로그 가림이 조용히 달라지므로 이 테스트로 고정한다.

실행:  python ~/.ai-gate/test_gate_hooks_in_sync.py -v
경로 덮어쓰기(검증용): 환경변수 NODE4_CLAUDE_HOOK, NODE4_AGY_HOOK, NODE4_CODEX_HOOK
"""
import importlib.util
import os
import unittest

HOOKS = {
    "claude": os.environ.get("NODE4_CLAUDE_HOOK", os.path.expanduser(r"~\.claude\hooks\node4-approval-gate.py")),
    "agy": os.environ.get("NODE4_AGY_HOOK", os.path.expanduser(r"~\.gemini\config\hooks\node4-approval-gate-agy.py")),
    "codex": os.environ.get("NODE4_CODEX_HOOK", os.path.expanduser(r"~\.codex\hooks\node4-approval-gate-codex.py")),
}

# 모든 훅이 똑같이 판정해야 하는 명령 (명령, 걸려야 하는 항목 목록)
SAMPLE_COMMANDS = [
    # 기본 판정
    ("git status", []),
    ("git log --grep push", []),
    ("git -C x log", []),
    ("docker run --rm img", []),
    ("./mvnw test -Dtest=A", []),
    ("git branch -d fix/a", []),
    ("git push -u origin HEAD", ["git push"]),
    ("git -C . merge --abort", ["git merge"]),
    ("git --no-pager push", ["git push"]),
    ("git -c a=b rebase origin/main", ["git rebase"]),
    ("git reset --hard HEAD~1", ["git reset --hard"]),
    ("git clean -fd", ["git clean"]),
    ("git branch -D fix/a", ["git branch -D"]),
    ("glab mr merge 1", ["glab mr"]),
    ("rm -rf build", ["rm"]),
    ("Remove-Item foo", ["Remove-Item"]),
    ("del foo.txt", ["del/rmdir"]),
    ("git add a; git push", ["git push"]),
    # 하이픈이 붙은 읽기 전용 git 하위 명령은 게이트 대상이 아니다 (2026-11-09 agy merge-base 오탐)
    ("git merge-base feat/ktcu-attack-alert origin/ktcu", []),
    ("git merge-tree a b", []),
    ("git checkout-index -f -a", []),
    ("git push-certs", []),
    ('$env:LC_ALL="C.UTF-8"; cd C:\\workspace\\redcms; git merge-base a origin/ktcu', []),
    ("git merge-base a b; git merge --ff-only a", ["git merge"]),
    # 커밋 안 된 작업을 지우는 명령: checkout -- / restore / stash drop·clear
    ("git checkout main", []),
    ("git checkout -b fix/a", []),
    ("git checkout -- src/a.java", ["git checkout --"]),
    ("git checkout .", ["git checkout --"]),
    ("git checkout HEAD -- src/a.java", ["git checkout --"]),
    ("git checkout -f main", ["git checkout --"]),
    ("git -C repo checkout --force main", ["git checkout --"]),
    ("git checkout main && git pull --ff-only", []),
    ("git restore src/a.java", ["git restore"]),
    ("git restore .", ["git restore"]),
    ("git restore --staged src/a.java", []),
    ("git restore -S src/a.java", []),
    ("git restore --staged --worktree src/a.java", ["git restore"]),
    ("git stash", []),
    ("git stash pop", []),
    ("git stash list", []),
    ("git stash drop", ["git stash drop/clear"]),
    ("git stash drop stash@{1}", ["git stash drop/clear"]),
    ("git stash clear", ["git stash drop/clear"]),
    ('git commit -m "restore old checkout -- behavior"', []),
    # 오탐 제거: 따옴표 안의 단순 문자열은 판정하지 않는다
    ('git commit -m "fix rm bug"', []),
    ('echo "git push origin main"', []),
    ("$x.Replace('(r\"\\bglab\\s+mr\\b\", \"glab mr\"),','')", []),
    ("python -c \"print('git push')\"", []),
    ('Write-Output "run git merge later"', []),
    # 계속 막아야 함: 셸에 넘기는 따옴표 안 명령
    ('cmd /c "git push origin main"', ["git push"]),
    ('cmd.exe /d /c "git push"', ["git push"]),
    ('pwsh -NoProfile -ExecutionPolicy Bypass -Command "git -C . merge --abort"', ["git merge"]),
    ("bash -c 'rm -rf build'", ["rm"]),
    ('Invoke-Expression "git push"', ["git push"]),
    ('ssh deploy@host "git push origin main"', ["git push"]),
    ("cmd /c \"echo 'git push'\"", []),  # 셸 명령 안의 echo 문자열은 여전히 문자열
    # 계속 막아야 함: 따옴표로 감싼 실행 파일 경로
    ('& "C:\\Program Files\\Git\\cmd\\git.exe" push origin main', ["git push"]),
    # 계속 막아야 함: 따옴표 인자 / 닫히지 않은 따옴표 / 따옴표 뒤 실제 명령
    ('git push "origin" "main"', ["git push"]),
    ('Remove-Item "C:\\tmp\\x"', ["Remove-Item"]),
    ('git push "origin', ["git push"]),
    ('echo "done" && git push', ["git push"]),
    # 2026-11-09 우회 변형 보강: 실행 파일 이름·별칭·.NET 직접 호출·다른 CLI 머지
    ("git.exe push origin main", ["git push"]),
    ("/usr/bin/rm -rf build", ["rm"]),
    ("ri build -Recurse", ["del/rmdir"]),
    ("erase a.txt", ["del/rmdir"]),
    ("[IO.File]::Delete('a.txt')", [".NET Delete"]),
    ("[System.IO.Directory]::Delete('build', $true)", [".NET Delete"]),
    ("Start-Process git -ArgumentList 'push'", ["Start-Process git"]),
    ("Start-Process -FilePath git.exe -ArgumentList @('push','origin')", ["Start-Process git"]),
    ("git switch --discard-changes main", ["git switch --discard-changes"]),
    ("git switch -f main", ["git switch --discard-changes"]),
    ("glab api -X PUT projects/6/merge_requests/1/merge", ["glab api 쓰기"]),
    ("glab api --method POST projects/6/repository/branches", ["glab api 쓰기"]),
    ("gh pr merge 12 --rebase", ["gh pr merge"]),
    # 대조: 막지 않아야 함
    ("git switch main", []),
    ("git switch -c feat/a", []),
    ("glab api projects/6", []),
    ("gh pr view 12", []),
    ("Start-Process notepad", []),
    ("git config --get remote.origin.url", []),
    ("echo prime", []),  # 'ri' 가 단어 중간에 있는 경우
    # 2026-11-10 우회 보강: 결합 셸 옵션(-lc), 따옴표로 쪼갠 단어, 줄 끝 rm, 중괄호·백틱 뒤, cmd 슬래시 옵션, 긴 옵션·축약
    ("bash -lc 'git push'", ["git push"]),
    ('bash -ic "rm -rf build"', ["rm"]),
    ('git "push" origin main', ["git push"]),
    ("git 'reset' --hard", ["git reset --hard"]),
    ('git pu""sh origin main', ["git push"]),
    ('"rm" -rf build', ["rm"]),
    ("find . -name x | xargs rm", ["rm"]),
    ("if ($x) {rm a.txt}", ["rm"]),
    ("&{ri a.txt}", ["del/rmdir"]),
    ("del/q a.txt", ["del/rmdir"]),
    ("rd/s/q build", ["del/rmdir"]),
    ("git branch -Df x", ["git branch -D"]),
    ("git branch --delete --force x", ["git branch -D"]),
    ("git checkout HEAD src/a.java", ["git checkout --"]),
    # 오탐 제거·대조: 막지 않아야 함
    ("docker rm c1", []),
    ("git rm --cached a", []),
    ("echo rm x", []),
    ('git commit -m "rm"', []),
    ('echo "rm"', []),
    ("git branch --delete fix/a", []),
    ("git branch -a", []),
    ("git checkout -b fix/a origin/main", []),
    ("git checkout main 2>&1", []),
    ("cd ri/x", []),
    # 2026-11-13 우회 보강(H1): 따옴표로 감싼 옵션·하위 명령
    ('git reset "--hard" HEAD', ["git reset --hard"]),
    ("git branch '-D' x", ["git branch -D"]),
    ('git checkout "."', ["git checkout --"]),
    ('git stash "drop"', ["git stash drop/clear"]),
    ('glab "mr" merge 1', ["glab mr"]),
    ('gh pr "merge" 1', ["gh pr merge"]),
    ('glab api -X "DELETE" /x', ["glab api 쓰기"]),
    # (H2) 셸별 따옴표·이스케이프·주석·heredoc
    (r'echo "a\\" ; rm -rf build ; echo "b"', ["rm"]),
    (r'echo "C:\tmp\" ; Remove-Item build ; echo "b"', ["Remove-Item"]),
    ("echo hi # don't\nrm -rf build\necho 'done'", ["rm"]),
    ("cat <<EOF\nit's\nEOF\nrm -rf build; echo 'x'", ["rm"]),
    # (H3) 실행 파일 이름 변형
    ("rm.exe -rf build", ["rm"]),
    ('"/bin/rm" -rf build', ["rm"]),
    ('env "rm" -rf build', ["rm"]),
    ('FOO=1 "rm" -rf build', ["rm"]),
    (r'"C:\tools\rm.exe" -rf build', ["rm"]),
    ("gh.exe pr merge 1", ["gh pr merge"]),
    ("glab.exe mr merge 1", ["glab mr"]),
    ("git.cmd push", ["git push"]),
    # (M1) 셸 전달 경로
    ('powershell "Remove-Item build -Recurse"', ["Remove-Item"]),
    ('echo "rm -rf build" | bash', ["rm"]),
    ('bash <<< "rm -rf build"', ["rm"]),
    ('Start-Process cmd -ArgumentList "/c git push"', ["git push"]),
    ('Start-Process pwsh -ArgumentList "-c","rm x"', ["rm"]),
    ('echo "$(git push)"', ["git push"]),
    ("bash <<EOF\ngit push origin main\nEOF", ["git push"]),
    ('iex @"\ngit push\n"@', ["git push"]),
    # (M2) 옵션 약어·묶음, 줄 이음·이스케이프
    ("git reset --har HEAD", ["git reset --hard"]),
    ("git reset --h HEAD", ["git reset --hard"]),
    ("git branch --del --for x", ["git branch -D"]),
    ("git branch -d --force x", ["git branch -D"]),
    ("git branch -d x -f", ["git branch -D"]),
    ("git switch --discard main", ["git switch --discard-changes"]),
    ("git switch --di main", ["git switch --discard-changes"]),
    ("git checkout --fo main", ["git checkout --"]),
    ("git checkout -qf main", ["git checkout --"]),
    ("git restore --staged --w a", ["git restore"]),
    ("git restore -SW a", ["git restore"]),
    ("git \\\npush origin main", ["git push"]),
    (r"git pu\sh origin main", ["git push"]),
    ("git pu`sh origin main", ["git push"]),
    # 오탐 대조(2026-11-13): 막지 않아야 함
    ('git commit -m "fix: git push later"', []),
    ('git log --grep "push"', []),
    ('./build.sh "x"', []),
    ('git commit -m "del"', []),
    ("cat <<EOF > notes.md\nrun git push origin main\nrm -rf build\nEOF", ["git push", "rm"]),  # pwsh 는 heredoc 미인식으로 합집합 오탐(bash 단독은 [])
    ("cat <<'EOF' > notes.md\nrun git push $(x)\nEOF", ["git push"]),  # pwsh 는 heredoc 미인식으로 합집합 오탐(bash 단독은 [])
    ("git commit -m \"$(cat <<'EOF'\nfix: don't git push or rm -rf\nEOF\n)\"", ["git push", "rm"]),  # pwsh 는 heredoc 미인식(bash 단독은 [])
    ("git commit -m @'\nmsg rm and git push\n'@", []),
    ('git branch --format="%(refname:short)"', []),
    ("git branch -a --format x", []),
    ("git branch -d my-feature", []),
    ("git reset --help", []),
    ("git reset --soft HEAD~1", []),
    ("git switch --detach HEAD", []),
    ('echo "rm -rf" | grep x', []),
    ("ssh-keygen -C 'rm x'", []),
    ('git commit -m "use bash" -m "rm old"', []),
    ('$s = @"\ngit push\n"@\nInvoke-Expression $s', []),  # 변수 경유는 알려진 한계(규칙 문서로 금지)
    # 2026-11-13 리뷰 1차 보강(R1~R5)
    ("cat <<EOF$x\nEOF$x\nrm -rf build\nEOF", ["rm"]),
    ("cat <<'EOF'x\nEOFx\ngit push origin main\nEOF", ["git push"]),
    ("cat <<E'OF'\nEOF\nrm -rf build\nE", ["rm"]),
    ("echo $((1<<EOF))\nrm -rf build\nEOF", ["rm"]),
    ("<# <<EOF #>\nRemove-Item -Recurse build\n#\nEOF", ["Remove-Item"]),
    ("where.exe --% <<EOF\nRemove-Item -Recurse build\nEOF", ["Remove-Item"]),
    ('git reset --"hard" HEAD', ["git reset --hard"]),
    ('git reset -""-hard', ["git reset --hard"]),
    ("git branch -'D' x", ["git branch -D"]),
    ('git checkout -"f" main', ["git checkout --"]),
    (r"printf 'git push\n' | bash", ["git push"]),
    ('git -c core.sshCommand="ssh -i k" push origin main', ["git push"]),
]

# 셸을 지정한 판정 (명령, 셸, 걸려야 하는 항목). Claude 훅은 Bash 도구 → "bash", PowerShell 도구 → "pwsh" 로 판정한다.
SHELL_SAMPLE_COMMANDS = [
    (r'echo "C:\tmp\" ; Remove-Item build ; echo "b"', "pwsh", ["Remove-Item"]),  # pwsh 는 \ 가 이스케이프 아님
    (r'echo "C:\tmp\" ; Remove-Item build ; echo "b"', "bash", []),  # bash 에서는 한 문자열(닫히지 않음)
    (r'echo "a\\" ; rm -rf build ; echo "b"', "bash", ["rm"]),
    (r'echo "a\\" ; rm -rf build ; echo "b"', "pwsh", ["rm"]),
    (r"git pu\sh origin main", "bash", ["git push"]),
    (r"git pu\sh origin main", "pwsh", []),
    ("git pu`sh origin main", "pwsh", ["git push"]),
    ("git pu`sh origin main", "bash", []),
    ("git \\\npush origin main", "bash", ["git push"]),
    ("cat <<EOF\nit's\nEOF\nrm -rf build; echo 'x'", "bash", ["rm"]),
    ("cat <<EOF\nit's\nEOF\nrm -rf build; echo 'x'", "pwsh", []),  # pwsh 는 heredoc 미인식(it's~echo ' 가 문자열)
    ('git reset "--hard" HEAD', "pwsh", ["git reset --hard"]),
    ("git status", "bash", []),
    ("x" * 100_001, "bash", ["명령 길이 초과"]),
    # 리뷰 1차 보강(R1, R2, R4)
    ("cat <<EOF$x\nEOF$x\nrm -rf build\nEOF", "bash", ["rm"]),
    ("cat <<'EOF'x\nEOFx\ngit push origin main\nEOF", "bash", ["git push"]),
    ("cat <<E'OF'\nEOF\nrm -rf build\nE", "bash", ["rm"]),
    ("echo $((1<<EOF))\nrm -rf build\nEOF", "bash", ["rm"]),
    ("cat <<EOF > notes.md\nrun git push origin main\nrm -rf build\nEOF", "bash", []),
    ("cat <<'EOF' > notes.md\nrun git push $(x)\nEOF", "bash", []),
    ("git commit -m \"$(cat <<'EOF'\nfix: don't git push or rm -rf\nEOF\n)\"", "bash", []),
    ("<# <<EOF #>\nRemove-Item -Recurse build\n#\nEOF", "pwsh", ["Remove-Item"]),
    ("where.exe --% <<EOF\nRemove-Item -Recurse build\nEOF", "pwsh", ["Remove-Item"]),
    (r"printf 'git push\n' | bash", "bash", ["git push"]),
]

# 세 훅이 글자 그대로 같아야 하는 판정 공통 블록의 시작·끝 표시
COMMON_BLOCK_START = "# ==== 판정 공통 블록 시작"
COMMON_BLOCK_END = "# ==== 판정 공통 블록 끝 ===="

SAMPLE_SECRETS = [
    "git push https://user:glpat-ABCDEFGH12345678@git.example.com/x.git HEAD",
    "GITLAB_TOKEN=supersecret123 glab mr merge --token abcdef123456 1",
    "curl --password=hunter2 -H x",
]


def load(path: str, name: str):
    """훅 파일을 모듈로 불러온다(main()은 실행되지 않는다)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GateHooksInSyncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = {name: load(path, f"{name}_gate") for name, path in HOOKS.items()}
        cls.reference = cls.modules["claude"]

    def others(self):
        return [(name, m) for name, m in self.modules.items() if name != "claude"]

    def test_gated_lists_identical(self):
        # Given 각 훅의 GATED 목록 / When Claude 훅과 비교 / Then 정규식·라벨·순서가 모두 같다
        for name, module in self.others():
            with self.subTest(hook=name):
                self.assertEqual(self.reference.GATED, module.GATED,
                                 f"{name} 훅의 GATED 목록이 Claude 훅과 다릅니다.")

    def test_quote_rules_identical(self):
        for name, module in self.others():
            for attr in ("SHELL_WORD", "PIPE_TO_SHELL", "QUOTED_TOOL", "QUOTED_EXE", "SIMPLE_WORD",
                         "COMMAND_POSITION", "QUOTED_ARG_CONTEXT", "HEREDOC", "HERESTRING"):
                with self.subTest(hook=name, attr=attr):
                    ref, other = getattr(self.reference, attr), getattr(module, attr)
                    self.assertEqual((ref.pattern, ref.flags), (other.pattern, other.flags))
            for mode in self.reference.SHELL_MODES:
                with self.subTest(hook=name, attr="SPECIAL", mode=mode):
                    ref, other = self.reference.SPECIAL[mode], module.SPECIAL[mode]
                    self.assertEqual((ref.pattern, ref.flags), (other.pattern, other.flags))

    def test_redaction_lists_identical(self):
        def spec(module):
            return [(p.pattern, p.flags, r) for p, r in module.REDACTIONS]
        for name, module in self.others():
            with self.subTest(hook=name):
                self.assertEqual(spec(self.reference), spec(module),
                                 f"{name} 훅의 REDACTIONS 목록이 Claude 훅과 다릅니다.")

    def test_log_limits_identical(self):
        for name, module in self.others():
            for attr in ("LOG_MAX_BYTES", "COMMAND_MAX_CHARS", "JUDGE_MAX_CHARS", "OVERSIZE_LABEL",
                         "CONTEXT_MAX_CHARS", "NEST_MAX_DEPTH", "SHELL_MODES", "QUOTED_ARG_TOOLS",
                         "COMMENT_START"):
                with self.subTest(hook=name, attr=attr):
                    self.assertEqual(getattr(self.reference, attr), getattr(module, attr))

    def test_verdict_on_sample_commands(self):
        for name, module in self.modules.items():
            for command, expected in SAMPLE_COMMANDS:
                with self.subTest(hook=name, command=command):
                    self.assertEqual(module.gate_hits(command), expected)

    def test_common_block_identical(self):
        # Given 세 훅 소스 / When 판정 공통 블록(시작~끝 표시 줄)을 잘라 비교 / Then 글자 그대로 같다
        from pathlib import Path

        def block(path):
            text = Path(path).read_text(encoding="utf-8")
            start, end = text.find(COMMON_BLOCK_START), text.find(COMMON_BLOCK_END)
            self.assertTrue(0 <= start < end, f"{path} 에 판정 공통 블록 표시가 없습니다")
            return text[start:end]
        reference = block(HOOKS["claude"])
        for name in ("agy", "codex"):
            with self.subTest(hook=name):
                self.assertEqual(reference, block(HOOKS[name]), f"{name} 훅의 판정 공통 블록이 Claude 훅과 다릅니다")

    def test_verdict_with_shell(self):
        for name, module in self.modules.items():
            for command, shell, expected in SHELL_SAMPLE_COMMANDS:
                with self.subTest(hook=name, shell=shell, command=command[:80]):
                    self.assertEqual(module.gate_hits(command, shell), expected)

    def test_long_input_performance(self):
        # Given 판정 시간을 늘리는 긴 입력(H4) / When 판정 / Then 2초 안에 끝나고 끝의 git push 를 잡는다
        import time
        cases = {
            "16KB": "sh a " * 2500 + '"a b" ' * 600 + "; git push",
            "100KB 직전": "sh a " * 15000 + '"a b" ' * 3990 + "; git push",
            "git 옵션 반복": "git -a " * 14200 + "; git push",
            "git branch 반복": "git branch " * 9000 + "; git push",
        }
        for label, command in cases.items():
            self.assertLessEqual(len(command), self.reference.JUDGE_MAX_CHARS)
            with self.subTest(case=label, size=len(command)):
                started = time.perf_counter()
                hits = self.reference.gate_hits(command)
                elapsed = time.perf_counter() - started
                self.assertIn("git push", hits)
                self.assertLess(elapsed, 2.0, f"{label} 판정에 {elapsed:.2f}초 걸렸습니다(훅 timeout 시 fail-open)")

    def test_same_redaction_on_secrets(self):
        for command in SAMPLE_SECRETS:
            masked = self.reference.redact(command)
            for secret in ("glpat-ABCDEFGH", "supersecret123", "abcdef123456", "hunter2", "user:"):
                with self.subTest(command=command, secret=secret):
                    self.assertNotIn(secret, masked)
            for name, module in self.others():
                with self.subTest(hook=name, command=command):
                    self.assertEqual(masked, module.redact(command))


GEMINI_POLICY_DIR = os.environ.get("NODE4_GEMINI_POLICY_DIR", os.path.expanduser(r"~\.gemini\policies"))
# Gemini 가 ReDoS 위험으로 거부했던 실제 패턴(2026-11-09). 검사기가 이것을 반드시 잡아야 한다.
KNOWN_REJECTED = r"\bgit\s+(?:-\S+(?:\s+[^-\s]\S*)?\s+)*(?:checkout\b)"


def star_height(pattern: str) -> int:
    """정규식의 무한 반복 중첩 깊이(star height). 2 이상이면 중첩 반복자다.

    {0,1}·{2,5} 같은 유한 반복은 세지 않는다. Gemini 정책 엔진은 중첩 반복자 패턴을
    'Unsafe regex pattern (potential ReDoS)' 로 거부하고 그 규칙을 로드하지 않는다.
    """
    try:
        import re._parser as sre_parse  # Python 3.11+
        from re._constants import MAXREPEAT, MAX_REPEAT, MIN_REPEAT, SUBPATTERN, BRANCH, ASSERT, ASSERT_NOT
    except ImportError:  # pragma: no cover
        import sre_parse
        from sre_constants import MAXREPEAT, MAX_REPEAT, MIN_REPEAT, SUBPATTERN, BRANCH, ASSERT, ASSERT_NOT
    repeats = {MAX_REPEAT, MIN_REPEAT}
    try:
        from re._constants import POSSESSIVE_REPEAT
        repeats.add(POSSESSIVE_REPEAT)
    except ImportError:
        pass

    def walk(items) -> int:
        height = 0
        for op, av in items:
            if op in repeats:
                low, high, sub = av
                height = max(height, walk(sub) + (1 if high is MAXREPEAT or high == MAXREPEAT else 0))
            elif op is SUBPATTERN:
                height = max(height, walk(av[-1]))
            elif op is BRANCH:
                height = max(height, *(walk(b) for b in av[1]))
            elif op in (ASSERT, ASSERT_NOT):
                height = max(height, walk(av[1]))
        return height

    return walk(sre_parse.parse(pattern))


class GeminiPolicySafetyTest(unittest.TestCase):
    """Gemini 정책 파일이 로드 가능한 형태인지 검사한다(오류 나면 그 규칙이 조용히 빠진다)."""

    def load_rules(self):
        import glob
        import tomllib
        files = sorted(glob.glob(os.path.join(GEMINI_POLICY_DIR, "*.toml")))
        self.assertTrue(files, f"정책 파일이 없습니다: {GEMINI_POLICY_DIR}")
        rules = []
        for path in files:
            with open(path, "rb") as f:
                data = tomllib.load(f)  # TOML 문법 오류면 여기서 실패
            rules += [(os.path.basename(path), i, r) for i, r in enumerate(data.get("rule", []))]
        return rules

    def test_checker_detects_known_rejected_pattern(self):
        # Given Gemini 가 실제로 거부한 패턴 / When 검사 / Then 중첩 반복자로 판정
        self.assertGreaterEqual(star_height(KNOWN_REJECTED), 2)
        self.assertEqual(star_height(r"\bgit\b[^;&|\n]*\scheckout(?![-\w])[^;&|\n]*\s(?:--|\.)(?:\s|$)"), 1)
        self.assertEqual(star_height(r"(?:ab){2,5}x?"), 0)

    def test_no_nested_quantifiers_in_command_regex(self):
        for name, index, rule in self.load_rules():
            for key in ("commandRegex", "argsPattern"):
                if key in rule:
                    with self.subTest(file=name, rule=index, key=key):
                        self.assertLess(star_height(rule[key]), 2,
                                        f"{name} rule[{index}].{key} 에 중첩 반복자가 있어 Gemini 가 거부합니다: {rule[key]}")

    def test_command_regex_compiles(self):
        import re
        for name, index, rule in self.load_rules():
            for key in ("commandRegex", "argsPattern"):
                if key in rule:
                    with self.subTest(file=name, rule=index, key=key):
                        re.compile(rule[key])

    def test_policy_covers_bypass_patterns(self):
        # Given 훅이 막는 우회 패턴(2026-11-11) / When 정책 규칙(ask_user)을 적용 / Then 걸리고, 정상 명령은 걸리지 않는다
        import re
        rules = [r for _, _, r in self.load_rules() if r.get("decision") == "ask_user"]

        def asks(command):
            return any(any(command.startswith(p) for p in r.get("commandPrefix", []))
                       or ("commandRegex" in r and re.search(r["commandRegex"], command)) for r in rules)
        for command in GEMINI_NEW_GATED:
            with self.subTest(command=command):
                self.assertTrue(asks(command))
        for command in GEMINI_NEW_PASSED:
            with self.subTest(command=command):
                self.assertFalse(asks(command))

    def test_regex_and_prefix_not_combined(self):
        # 문서: commandPrefix 와 commandRegex 는 한 규칙에 함께 쓸 수 없다
        for name, index, rule in self.load_rules():
            with self.subTest(file=name, rule=index):
                self.assertFalse("commandPrefix" in rule and "commandRegex" in rule)


GEMINI_NEW_GATED = ["git branch -Df x", "git branch --delete --force x", "git branch --force --delete x",
                    "git checkout HEAD src/a.java", "find . | xargs rm", "if ($x) {rm a.txt}", "del/q a.txt", "rd/s/q build"]
GEMINI_NEW_PASSED = ["git checkout main && git pull --ff-only origin main", "git checkout -b fix/a origin/main",
                     "git branch -d fix/draft", "git checkout main 2>&1", "cd ri/x", "docker rm c1"]


class HookOutputEncodingTest(unittest.TestCase):
    """훅 stdout 은 어떤 코드 페이지로 읽어도 깨지지 않는 ASCII JSON 이어야 한다.

    agy 는 cp949 로 출력된 한글 사유를 UTF-8 로 읽다가
    'proto: ... string_value contains invalid UTF-8' 로 작업 전체가 중단됐다(2026-11-09).
    """

    LOGS = [
        os.path.expanduser(r"~\.claude\hooks\node4-approval-gate.log"),
        os.path.expanduser(r"~\.gemini\config\hooks\node4-approval-gate-agy.log"),
    ]

    @classmethod
    def setUpClass(cls):
        # 실제 게이트 로그에 시험 기록이 남지 않도록 백업해 두고 끝나면 되돌린다
        import shutil
        cls._saved = {}
        for log in cls.LOGS:
            if os.path.exists(log):
                cls._saved[log] = log + ".unittest-backup"
                shutil.copy2(log, cls._saved[log])

    @classmethod
    def tearDownClass(cls):
        import shutil
        for log in cls.LOGS:
            if log in cls._saved:
                shutil.move(cls._saved[log], log)
            elif os.path.exists(log):
                os.remove(log)

    def run_hook(self, name, payload):
        import json
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        result = subprocess.run([sys.executable, "-I", HOOKS[name]], input=json.dumps(payload).encode("utf-8"),
                                capture_output=True, env=env)
        return result.stdout

    def assert_ascii_json(self, raw: bytes):
        import json
        self.assertTrue(raw.strip(), "게이트 명령인데 출력이 없습니다")
        raw.decode("ascii")  # 비 ASCII 바이트가 있으면 UnicodeDecodeError
        body = json.loads(raw)
        self.assertIn("Node 4", json.dumps(body, ensure_ascii=False))

    def test_claude_output_is_ascii(self):
        self.assert_ascii_json(self.run_hook("claude", {"tool_name": "Bash", "tool_input": {"command": "git push"}}))

    def test_agy_output_is_ascii(self):
        payload = {"toolCall": {"name": "run_command", "args": {"CommandLine": "git push"}}}
        self.assert_ascii_json(self.run_hook("agy", payload))

    def test_agy_ignores_file_content_and_queries(self):
        # Given 파일 쓰기 본문·검색어에 게이트 명령 문구가 든 호출 / When agy 훅 실행 / Then 판정하지 않고 통과
        for args in ({"TargetFile": "README.md", "CodeContent": "배포: git push -u origin HEAD\n"},
                     {"TargetFile": "clean.sh", "CodeContent": "rm -rf build\n"},
                     {"Query": "git merge strategy"}):
            with self.subTest(args=args):
                self.assertEqual(self.run_hook("agy", {"toolCall": {"name": "tool", "args": args}}).strip(), b"")

    def test_agy_checks_command_array(self):
        # Given 명령이 인자 배열로 오는 호출 / When agy 훅 실행 / Then 게이트 대상이면 거부
        payload = {"toolCall": {"name": "run_command", "args": {"command": ["git", "push"]}}}
        self.assert_ascii_json(self.run_hook("agy", payload))

    def test_claude_shell_from_tool_name(self):
        # Given PowerShell 에서만 실행되는 우회 / When tool_name 별로 Claude 훅 실행 / Then PowerShell 은 확인, Bash 는 통과
        command = r'echo "C:\tmp\" ; Remove-Item build ; echo "b"'
        self.assert_ascii_json(self.run_hook("claude", {"tool_name": "PowerShell", "tool_input": {"command": command}}))
        self.assertEqual(self.run_hook("claude", {"tool_name": "Bash", "tool_input": {"command": command}}).strip(), b"")


def _claude_settings_paths() -> dict:
    """전역 + Orca 의 모든 Claude 프로필(계정마다 1개) settings.json. 검증용으로 프로필 1개를 덮어쓸 수 있다."""
    import glob
    paths = {"global": os.environ.get("NODE4_CLAUDE_SETTINGS", os.path.expanduser(r"~\.claude\settings.json"))}
    if os.environ.get("NODE4_ORCA_CLAUDE_SETTINGS"):
        paths["orca"] = os.environ["NODE4_ORCA_CLAUDE_SETTINGS"]
        return paths
    for p in sorted(glob.glob(os.path.expanduser(r"~\AppData\Roaming\orca\claude-profiles\*\home\settings.json"))):
        paths["orca-" + os.path.basename(os.path.dirname(os.path.dirname(p)))[:8]] = p
    return paths


CLAUDE_SETTINGS = _claude_settings_paths()


class ClaudeSettingsInSyncTest(unittest.TestCase):
    """Claude 전역 settings.json 과 Orca 프로필 settings.json(CLAUDE_CONFIG_DIR)의 권한·훅이 같아야 한다.

    Orca 에서 띄운 Claude 는 Orca 프로필 설정만 읽는다. 한쪽에만 ask 규칙이나 게이트 훅을 넣으면
    실행 위치에 따라 Node 4 게이트가 조용히 빠진다. 훅 그룹 순서는 Orca 가 바꿔 쓰므로 비교하지 않는다.
    """

    @classmethod
    def setUpClass(cls):
        import json
        from pathlib import Path
        cls.settings = {name: json.loads(Path(path).read_text(encoding="utf-8"))
                        for name, path in CLAUDE_SETTINGS.items()}

    @staticmethod
    def hook_set(settings: dict) -> list:
        """(이벤트, matcher, 핸들러) 목록을 순서 무관하게 비교할 수 있도록 정렬해 돌려준다."""
        import json
        items = []
        for event, groups in settings.get("hooks", {}).items():
            for group in groups:
                for handler in group.get("hooks", []):
                    items.append((event, group.get("matcher"), json.dumps(handler, sort_keys=True)))
        return sorted(items)

    def profiles(self) -> list:
        names = [n for n in self.settings if n != "global"]
        self.assertTrue(names, "Orca Claude 프로필 settings.json 을 찾지 못했습니다")
        return names

    def test_permission_rules_identical(self):
        g = self.settings["global"].get("permissions", {})
        for name in self.profiles():
            o = self.settings[name].get("permissions", {})
            for key in sorted(set(g) | set(o)):
                with self.subTest(profile=name, key=key):
                    gv, ov = g.get(key), o.get(key)
                    if isinstance(gv, list) or isinstance(ov, list):
                        gs, os_ = set(gv or []), set(ov or [])
                        self.assertEqual(gs, os_, f"permissions.{key} 차이 — 전역에만: {sorted(gs - os_)}, "
                                                  f"{name} 에만: {sorted(os_ - gs)}")
                    else:
                        self.assertEqual(gv, ov, f"permissions.{key} 값이 다릅니다({name})")

    def test_hooks_identical(self):
        g = self.hook_set(self.settings["global"])
        for name in self.profiles():
            o = self.hook_set(self.settings[name])
            only_g = [(e, m, h[:120]) for e, m, h in sorted(set(g) - set(o))]
            only_o = [(e, m, h[:120]) for e, m, h in sorted(set(o) - set(g))]
            with self.subTest(profile=name):
                self.assertTrue(g == o, f"hooks 차이 — 전역에만: {only_g}, {name} 에만: {only_o}"
                                        + ("" if only_g or only_o else " (같은 훅이 한쪽에 중복 등록됨)"))

    def test_gate_hooks_registered(self):
        for name, settings in self.settings.items():
            commands = [(e, m, h) for e, m, h in self.hook_set(settings)]
            with self.subTest(settings=name):
                self.assertTrue(any(e == "PreToolUse" and "node4-approval-gate.py" in h
                                    and m and {"Bash", "PowerShell"} <= set(m.split("|")) for e, m, h in commands),
                                "Node 4 게이트 PreToolUse 훅(Bash|PowerShell)이 없습니다")
                self.assertTrue(any(e == "PostToolUse" and "sync_test_hook.py" in h for e, m, h in commands),
                                "동기화 테스트 PostToolUse 훅이 없습니다")


CODEX_HOMES = {
    "global": os.environ.get("NODE4_CODEX_HOME", os.path.expanduser(r"~\.codex")),
    "orca": os.environ.get(
        "NODE4_ORCA_CODEX_HOME",
        os.path.join(os.path.expanduser(r"~\AppData\Roaming\orca\codex-accounts"), os.environ.get("ORCA_CODEX_ACCOUNT_ID", "<orca-codex-account-id>"), r"home")),
}
ORCA_HOOK_MARK = "/.orca/agent-hooks/"  # Orca 가 자기 상태 표시용으로 넣는 훅(전역에는 없어도 됨)
ORCA_RULES_PREFIX = "_orca-global-"     # Orca 가 ~/.codex/rules/<이름> 을 복사해 두는 파일 이름 접두어


class CodexHomeInSyncTest(unittest.TestCase):
    """전역 ~/.codex 와 Orca Codex 홈(CODEX_HOME)의 hooks.json·rules 가 맞아야 한다.

    Orca 에서 띄운 Codex 는 Orca 홈만 읽는다. hooks.json 은 Orca 가 따로 관리하므로 한쪽에만 게이트 훅을
    넣으면 실행 위치에 따라 훅이 빠진다. rules 는 Orca 가 시작할 때 _orca-global-<이름> 으로 복사하지만,
    Orca 를 다시 띄우기 전까지는 옛 규칙이 남는다(2026-11-09 수동 동기화 사례).
    Orca 홈의 자체 default.rules("항상 허용" 누적분)는 비교하지 않는다.
    """

    @staticmethod
    def hook_items(home: str) -> list:
        import json
        with open(os.path.join(home, "hooks.json"), encoding="utf-8") as f:
            data = json.load(f)
        return sorted((event, group.get("matcher") or "", json.dumps(handler, sort_keys=True, ensure_ascii=False))
                      for event, groups in data.get("hooks", {}).items()
                      for group in groups for handler in group.get("hooks", []))

    def test_global_hooks_present_in_orca(self):
        g, o = (self.hook_items(CODEX_HOMES[n]) for n in ("global", "orca"))
        missing = [item for item in g if item not in o]
        self.assertEqual(missing, [], "전역 hooks.json 의 훅이 Orca 홈 hooks.json 에 없습니다")

    def test_orca_extra_hooks_are_orca_status_only(self):
        g, o = (self.hook_items(CODEX_HOMES[n]) for n in ("global", "orca"))
        extra = [item for item in o if item not in g and ORCA_HOOK_MARK not in item[2]]
        self.assertEqual(extra, [], "Orca 홈 hooks.json 에만 있는 훅입니다. 전역에도 넣거나 지우세요")

    def test_gate_hooks_registered(self):
        for name, home in CODEX_HOMES.items():
            items = self.hook_items(home)
            with self.subTest(home=name):
                self.assertTrue(any(e == "PreToolUse" and "node4-approval-gate-codex.py" in h for e, m, h in items))
                self.assertTrue(any(e == "PostToolUse" and "sync_test_hook.py" in h for e, m, h in items))

    def test_rules_mirrored(self):
        import glob
        g_dir, o_dir = (os.path.join(CODEX_HOMES[n], "rules") for n in ("global", "orca"))
        sources = {os.path.basename(p): p for p in glob.glob(os.path.join(g_dir, "*.rules"))}
        self.assertIn("default.rules", sources)
        for name, src in sorted(sources.items()):
            mirror = os.path.join(o_dir, ORCA_RULES_PREFIX + name)
            with self.subTest(rules=name):
                self.assertTrue(os.path.exists(mirror), f"{mirror} 가 없습니다")
                from pathlib import Path
                self.assertEqual(Path(src).read_bytes(), Path(mirror).read_bytes(),
                                 f"{name} 과 Orca 복사본 내용이 다릅니다. Orca 를 다시 띄우거나 복사본을 맞추세요")
        stale = [os.path.basename(p) for p in glob.glob(os.path.join(o_dir, ORCA_RULES_PREFIX + "*.rules"))
                 if os.path.basename(p)[len(ORCA_RULES_PREFIX):] not in sources]
        self.assertEqual(stale, [], "원본이 없는 Orca 규칙 복사본입니다")


AGY_HOOKS_JSON = os.environ.get("NODE4_AGY_HOOKS_JSON", os.path.expanduser(r"~\.gemini\config\hooks.json"))
GEMINI_SETTINGS = os.environ.get("NODE4_GEMINI_SETTINGS", os.path.expanduser(r"~\.gemini\settings.json"))


class AgyGeminiHooksRegisteredTest(unittest.TestCase):
    """agy 게이트 훅·동기화 훅과 Gemini 동기화 훅이 등록돼 있어야 한다.

    agy hooks.json 에는 Orca 상태 훅 그룹도 함께 있어 Orca 가 파일을 다시 쓸 수 있다. 게이트 훅이 빠지면
    agy 에서는 Node 4 게이트가 사라진다(settings.json 의 ask 는 --dangerously-skip-permissions 에서 무시됨).
    """

    @staticmethod
    def commands(node) -> list:
        """(이벤트, matcher, 명령) 목록. agy 는 {그룹: {이벤트: [...]}} , Gemini 는 {이벤트: [...]} 형식."""
        found = []

        def walk(event, items, matcher=None):
            for item in items or []:
                if "hooks" in item:
                    walk(event, item["hooks"], item.get("matcher"))
                elif item.get("command"):
                    found.append((event, matcher, item["command"]))
        for key, value in (node or {}).items():
            if isinstance(value, dict):  # agy 그룹
                for event, items in value.items():
                    walk(event, items)
            else:
                walk(key, value)
        return found

    def load(self, path):
        import json
        from pathlib import Path
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def test_agy_gate_hook_on_every_tool(self):
        items = self.commands(self.load(AGY_HOOKS_JSON))
        self.assertTrue(any(e == "PreToolUse" and m == "*" and "node4-approval-gate-agy.py" in c for e, m, c in items),
                        "agy hooks.json 에 Node 4 게이트 PreToolUse 훅(matcher '*')이 없습니다")

    def test_agy_sync_hook(self):
        items = self.commands(self.load(AGY_HOOKS_JSON))
        self.assertTrue(any(e == "PostInvocation" and "sync_test_hook.py" in c and "--format agy" in c
                            for e, m, c in items), "agy hooks.json 에 동기화 훅(PostInvocation)이 없습니다")

    def test_gemini_sync_hook(self):
        items = self.commands(self.load(GEMINI_SETTINGS).get("hooks"))
        self.assertTrue(any(e == "AfterTool" and "sync_test_hook.py" in c and "--format gemini" in c
                            for e, m, c in items), "Gemini settings.json 에 동기화 훅(AfterTool)이 없습니다")


AGY_SETTINGS = os.environ.get("NODE4_AGY_SETTINGS", os.path.expanduser(r"~\.gemini\antigravity-cli\settings.json"))
# agy settings deny(두 번째 방어선) 판정 표본: (명령, 거부해야 하나). 명령 맨 앞이나 ; & | 뒤에 오는 직접 실행만 대상.
AGY_DENY_SAMPLES = [
    ("git push", True), ("git push -u origin HEAD", True), ("git -C . merge --abort", True),
    ("git.exe push origin main", True), ("cd C:\\workspace\\redcms; git rebase origin/ktcu", True),
    ("git add a && git push", True), ("git reset HEAD~1 --hard", True), ("git clean -fd", True),
    ("git branch -D fix/a", True), ("git checkout -- a.java", True), ("git checkout .", True),
    ("git checkout -f main", True), ("git stash drop", True), ("git stash clear", True),
    ("git switch --discard-changes main", True), ("glab mr merge 1", True), ("gh pr merge 12", True),
    ("glab api -X PUT projects/6/merge_requests/1/merge", True), ("rm -rf build", True),
    ("Remove-Item foo -Recurse", True), ("Get-ChildItem x | Remove-Item", True), ("del a.txt", True),
    ("rmdir build", True), ("ri build", True), ("[IO.File]::Delete('a')", True),
    ("Start-Process git -ArgumentList 'push'", True),
    # 2026-11-11 우회 보강
    ("git branch -Df x", True), ("git branch --delete --force x", True), ("git checkout HEAD src/a.java", True),
    ("find . | xargs rm", True), ("if ($x) {rm a.txt}", True), ("del/q a.txt", True), ("rd/s/q build", True),
    # 거부하면 안 되는 것
    ("git branch -d fix/draft", False), ("git checkout main && git pull --ff-only", False),
    ("git checkout main 2>&1", False), ("git checkout -b fix/a origin/main", False), ("cd ri/x", False),
    ("docker rm c1", False),
    ("git status", False), ("git merge-base a b", False), ("git push-certs", False),
    ("git checkout main", False), ("git checkout -b feat/a", False), ("git switch main", False),
    ("git stash pop", False), ("git restore --staged a.java", False), ("glab mr list", True),
    ("glab api projects/6", False), ("gh pr view 1", False), ("git branch -d fix/a", False),
    ('git commit -m "fix rm bug"', False), ('echo "git push origin main"', False),
    ("Write-Output 'remove-item later'", False), ("python -m pytest", False), ("./mvnw test", False),
]


class AgyDenyRulesTest(unittest.TestCase):
    """agy settings.json 의 deny 정규식(훅과 별개인 두 번째 방어선)이 의도대로 판정하는지.

    agy 는 --dangerously-skip-permissions 에서 ask 는 무시하지만 deny 는 지킨다(2026-11-09 실측).
    agy 정규식은 RE2 라 전후방 탐색이 없다. 그래서 git restore(--staged 예외)는 훅에만 맡긴다.
    """

    def rules(self) -> list:
        import json
        import re
        from pathlib import Path
        deny = json.loads(Path(AGY_SETTINGS).read_text(encoding="utf-8")).get("permissions", {}).get("deny", [])
        found = [re.compile(r[len("command(regex:"):-1]) for r in deny if r.startswith("command(regex:")]
        self.assertTrue(found, "agy settings.json 에 deny 정규식 규칙이 없습니다")
        return found

    def test_no_lookaround(self):
        import json
        from pathlib import Path
        deny = json.loads(Path(AGY_SETTINGS).read_text(encoding="utf-8")).get("permissions", {}).get("deny", [])
        for rule in deny:
            with self.subTest(rule=rule):
                self.assertNotRegex(rule, r"\(\?<?[=!]", "RE2 는 전후방 탐색((?=, (?!, (?<=, (?<!)을 지원하지 않습니다")

    def test_deny_samples(self):
        rules = self.rules()
        for command, expected in AGY_DENY_SAMPLES:
            with self.subTest(command=command):
                self.assertEqual(any(r.fullmatch(command) for r in rules), expected)


class PipelineRulesInSyncTest(unittest.TestCase):
    """각 도구 전역 규칙 파일의 파이프라인 부분이 마스터(~/.ai-global-pipeline.md)와 같아야 한다.

    다르면 python ~/.ai-gate/sync_pipeline_rules.py 로 맞춘다.
    """

    def test_copies_match_master(self):
        spec = importlib.util.spec_from_file_location(
            "sync_pipeline_rules", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_pipeline_rules.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for target, state, detail in mod.plan(mod.read(mod.MASTER)):
            with self.subTest(target=target):
                self.assertEqual(state, "same", f"{detail if state == 'error' else '마스터와 다릅니다'} "
                                                f"→ sync_pipeline_rules.py 실행")


class PromptSkillsInSyncTest(unittest.TestCase):
    """프롬프트 스킬(~/.ai-gate/prompt-skills/*/SKILL.md)이 Claude·Codex 스킬 폴더 사본과 같고 형식이 맞아야 한다.

    다르면 python ~/.ai-gate/sync_prompt_skills.py 로 맞춘다.
    """

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "sync_prompt_skills", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_prompt_skills.py"))
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_copies_match_master(self):
        self.assertTrue(self.mod.master_files(), f"마스터 스킬이 없습니다: {self.mod.MASTER_DIR}")
        for dst, state, _ in self.mod.plan():
            with self.subTest(target=dst):
                self.assertEqual(state, "same", f"사본이 {'없습니다' if state == 'missing' else '마스터와 다릅니다'} "
                                                f"→ sync_prompt_skills.py 실행")

    def test_frontmatter(self):
        """name = 폴더 이름, description 있음(Codex 한도 1024자), 사용자 호출 전용(disable-model-invocation)."""
        import re
        for path in self.mod.master_files():
            with self.subTest(skill=path):
                text = self.mod.read(path).decode("utf-8")
                m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
                self.assertIsNotNone(m, "YAML frontmatter(--- ... ---)가 없습니다")
                meta = dict(re.findall(r"^([\w-]+):\s*(.*)$", m.group(1), re.MULTILINE))
                self.assertEqual(meta.get("name"), os.path.basename(os.path.dirname(path)))
                self.assertTrue(0 < len(meta.get("description", "")) <= 1024)
                self.assertEqual(meta.get("disable-model-invocation"), "true")
                self.assertIn("$ARGUMENTS", text)


README = os.environ.get("NODE4_AI_GATE_README", os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md"))


class ReadmeInSyncTest(unittest.TestCase):
    """README 의 테스트 묶음 표와 테스트 개수가 이 파일과 맞아야 한다(묶음을 추가하고 문서를 빠뜨리는 것 방지)."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.text = Path(README).read_text(encoding="utf-8")

    def test_suite_table_matches_classes(self):
        import re
        import sys
        section = self.text.split("## 동기화 테스트가 검사하는 것", 1)[1].split("\n## ", 1)[0]
        documented = set(re.findall(r"^\|\s*`(\w+Test)`\s*\|", section, re.MULTILINE))
        module = sys.modules[__name__]
        actual = {name for name, obj in vars(module).items()
                  if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and obj is not unittest.TestCase}
        self.assertEqual(documented, actual, f"README 표에만: {sorted(documented - actual)}, "
                                             f"코드에만: {sorted(actual - documented)}")

    def test_total_count_matches(self):
        import re
        import sys
        m = re.search(r"^\|\s*`test_gate_hooks_in_sync\.py`\s*\|[^|\n]*?\((\d+)개\)", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "README 파일 표의 test_gate_hooks_in_sync.py 행에 '(N개)' 표기가 없습니다")
        total = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]).countTestCases()
        self.assertEqual(int(m.group(1)), total, "README 의 테스트 개수와 실제 개수가 다릅니다")


if __name__ == "__main__":
    import sys
    # 결과(한글 실패 메시지 포함)를 UTF-8 로 고정한다. sync_test_hook.py 가 UTF-8 로 읽어 경고에 싣는다.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main()
