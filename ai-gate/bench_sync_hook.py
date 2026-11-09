"""동기화 훅의 '변경 없음' 경로 소요 시간 측정. 훅이 도구 호출마다 실제로 하는 것(프로세스 기동 + mtime 확인)을 그대로 잰다."""
import json, statistics, subprocess, sys, time, timeit, importlib.util
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HOOK = Path.home() / ".ai-gate" / "sync_test_hook.py"
STATE = HOOK.with_name(".sync-test-mtimes.json")
LOG = HOOK.with_name("sync-test-hook.log")
N = 40


BENCH_SESSION = b'{"session_id": "bench-sync-hook"}'  # 실제 호출처럼 세션 파일 확인까지 포함


def wall(cmd, stdin=BENCH_SESSION):
    t = time.perf_counter()
    r = subprocess.run(cmd, input=stdin, capture_output=True)
    return (time.perf_counter() - t) * 1000, r.stdout


def stats(name, xs):
    xs = sorted(xs)
    p95 = xs[int(len(xs) * 0.95) - 1]
    print(f"{name:<34} 중앙값 {statistics.median(xs):6.1f}ms  평균 {statistics.mean(xs):6.1f}ms  "
          f"p95 {p95:6.1f}ms  최소 {xs[0]:6.1f}ms  최대 {xs[-1]:6.1f}ms")
    return {"median": round(statistics.median(xs), 1), "mean": round(statistics.mean(xs), 1), "p95": round(p95, 1),
            "min": round(xs[0], 1), "max": round(xs[-1], 1)}


log_lines = LOG.read_text(encoding="utf-8").count("\n")
hook_cmd = [sys.executable, "-I", str(HOOK), "--format", "claude"]
wall(hook_cmd)  # 상태를 현재로 맞춤(변경이 있었다면 여기서 한 번 처리)
state_before = STATE.read_text(encoding="utf-8")

for _ in range(3):  # 예열(파일 캐시·pyc)
    wall(hook_cmd); wall([sys.executable, "-I", "-c", "pass"])
res = {}
res["python_startup"] = stats("python -I -c pass (기동만)", [wall([sys.executable, "-I", "-c", "pass"])[0] for _ in range(N)])
outs = []
hook_times = []
for _ in range(N):
    ms, out = wall(hook_cmd); hook_times.append(ms); outs.append(out)
res["hook_no_change"] = stats("sync_test_hook.py (변경 없음)", hook_times)

spec = importlib.util.spec_from_file_location("h", HOOK)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
per = min(timeit.repeat(mod.current_mtimes, number=50, repeat=5)) / 50 * 1000
print(f"{'프로세스 안 current_mtimes()':<34} {per:6.2f}ms  (감시 파일 {len(mod.watched_files())}개)")
res["in_process_mtime_check_ms"] = round(per, 2)
res["watched_files"] = len(mod.watched_files())

print("출력 없음:", all(o == b"" for o in outs), "| 상태 파일 불변:", STATE.read_text(encoding="utf-8") == state_before,
      "| 테스트 실행 로그 추가:", LOG.read_text(encoding="utf-8").count("\n") - log_lines)
print(json.dumps(res, ensure_ascii=False))
try:  # 측정용 세션 파일 정리
    (HOOK.with_name(".sync-sessions") / "claude-bench-sync-hook.json").unlink()
except OSError:
    pass
