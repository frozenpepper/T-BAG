#!/usr/bin/env python3
"""Launch one configured worker attempt and record plain path-based lifecycle evidence."""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _contract import role_writes_project, validate_role_contract
from _roles import ROLE_NAMES
from _rules_snapshot import verify_snapshot

PLACEHOLDER = "DSD_WORKER_REPORT_PLACEHOLDER_V2_1"
DEFAULT_LAUNCH_START_INTERVAL_SECONDS = 3.0
OPENCODE_DB_LOCK_RETRY_DELAYS_SECONDS = (4.0, 8.0, 16.0)


def classify_report_text(text: str) -> str:
    """Classify the launcher report without treating a partial running log as absent.

    Workers are encouraged to replace/extend the placeholder before mutating project
    state. A report that still contains the marker but also contains substantive lines
    is an in-progress report: not semantically complete, but sufficient to prefer a
    same-session continuation over cold Recovery after a transport drop.
    """
    # The launcher marker has meaning only as the exact standalone marker line
    # near the placeholder header. A completed report may legitimately mention the
    # marker token in prose (for example while explaining that it was removed).
    # Substring matching would incorrectly keep such reports in report-resume.
    lines=[raw.strip() for raw in text.splitlines()]
    if PLACEHOLDER not in lines[:8]:
        return "present"
    boilerplate = (
        "# T-BAG worker report placeholder",
        PLACEHOLDER,
        "Append running status below while working. Keep the marker until the report is complete; remove the marker only when the final self-contained report is ready.",
    )
    extra=[]
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line in boilerplate or line.startswith("Attempt:"):
            continue
        extra.append(line)
    return "in-progress" if extra else "launcher-placeholder"


def now() -> str: return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(tmp,path)


def launch_gate_root() -> Path:
    """Machine-global admission state for the brief CLI bootstrap window.

    The collision being protected can live in user-global CLI state, so this must not
    be scoped to one T-BAG run or project. The files contain only timing metadata.
    """
    return (Path.home()/".cache"/"t-bag"/"launch-start-gate").resolve()


def _finite_interval(value: Any, *, default: float = 0.0) -> float:
    try: interval=float(value)
    except (TypeError,ValueError): return default
    return interval if math.isfinite(interval) and interval >= 0 else default


def launch_start_delay(state: dict[str,Any], requested_interval: float, monotonic_now: float) -> float:
    """Return the delay needed before the next CLI process may start.

    Respect both the previous launcher's requested interval and this launcher's. This
    prevents two runs with different settings from weakening one another. Monotonic
    time avoids wall-clock corrections; a stored monotonic value greater than the
    current clock is treated as stale (for example after reboot), never as a huge wait.
    """
    requested=_finite_interval(requested_interval)
    previous=_finite_interval(state.get("interval_seconds"))
    required=max(requested,previous)
    try: last=float(state.get("started_monotonic"))
    except (TypeError,ValueError): return 0.0
    if not math.isfinite(last) or last < 0 or last > monotonic_now: return 0.0
    return max(0.0,required-(monotonic_now-last))


def staggered_popen(cmd: list[str], *, interval_seconds: float, gate_root: Path | None = None, **kwargs: Any) -> subprocess.Popen:
    """Start one worker CLI under a machine-global, process-safe admission gate.

    Detached T-BAG monitors may all exist concurrently. Only the instant of spawning
    their underlying CLI processes is serialized/spaced; after Popen returns every
    worker executes concurrently as normal.
    """
    interval=_finite_interval(interval_seconds,default=-1.0)
    if interval < 0: raise ValueError("launch start interval must be a finite number >= 0")
    root=(gate_root or launch_gate_root()).resolve(); root.mkdir(parents=True,exist_ok=True)
    lock_path=root/"admission.lock"; state_path=root/"last-start.json"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
        try:
            state: dict[str,Any] = {}
            if state_path.is_file():
                try:
                    loaded=json.loads(state_path.read_text(encoding="utf-8"))
                    if isinstance(loaded,dict): state=loaded
                except (OSError,json.JSONDecodeError):
                    state={}
            before=time.monotonic(); delay=launch_start_delay(state,interval,before)
            if delay > 0: time.sleep(delay)
            # Make the admission durable *before* spawning. If this write fails, no
            # worker exists to become an unsupervised orphan. The post-spawn rewrite
            # below only refines the timestamp and may safely degrade to this record.
            admitted=time.monotonic()
            gate_state={"format":"tbag-launch-start-gate-v1","started_monotonic":admitted,"started_at":now(),"interval_seconds":interval}
            atomic_json(state_path,gate_state)
            proc=subprocess.Popen(cmd,**kwargs)
            started=time.monotonic()
            if started != admitted:
                gate_state={**gate_state,"started_monotonic":started,"started_at":now()}
                try:
                    atomic_json(state_path,gate_state)
                except Exception as exc:
                    print(f"T-BAG launch gate warning: post-spawn timing refinement failed: {exc}",file=sys.stderr)
            return proc
        finally:
            fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def _read_process_slice(path: Path, start: int, *, max_bytes: int = 65536) -> str:
    """Read only output emitted by one child-process incarnation.

    A T-BAG attempt may restart the OpenCode process after a transient bootstrap
    lock. Offsets keep an older lock message from making a later unrelated exit
    look retryable.
    """
    if not path.is_file(): return ""
    try:
        size=path.stat().st_size
        begin=max(start, size-max_bytes)
        with path.open("rb") as handle:
            handle.seek(begin)
            return handle.read(max_bytes).decode("utf-8",errors="replace")
    except OSError:
        return ""


def current_scope_change_count(p: dict[str,Path]) -> int | None:
    """Return current task-authored project movement without writing terminal evidence."""
    cp=subprocess.run(
        [sys.executable,str(Path(__file__).resolve().parent/"scope_snapshot.py"),"compare",
         "--root",str(p["project_root"]),"--baseline",str(p["baseline"])],
        text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,
    )
    if cp.returncode!=0: return None
    try:
        data=json.loads(cp.stdout)
        return int(data.get("changed_count"))
    except (json.JSONDecodeError,TypeError,ValueError):
        return None


def retryable_opencode_db_lock(
    args: argparse.Namespace,
    p: dict[str,Path],
    *,
    exit_code: int,
    session_id: str | None,
    log_start: int,
    stderr_path: Path | None,
    stderr_start: int,
) -> str | None:
    """Classify one narrow, non-semantic OpenCode bootstrap failure.

    Retrying is legal only when the child exited unsuccessfully, emitted the exact
    SQLite lock signature, never established a resumable session, left the worker
    report untouched, and authored no project delta. The same DB/worktree/prompt are
    then reused; this function never deletes runtime state.
    """
    if args.driver not in {"opencode","opencode2"} or exit_code==0 or session_id:
        return None
    if report_state(p["report"])!="launcher-placeholder":
        return None
    output=_read_process_slice(p["log"],log_start)
    if stderr_path is not None:
        output += "\n" + _read_process_slice(stderr_path,stderr_start)
    if "database is locked" not in output.lower():
        return None
    if current_scope_change_count(p)!=0:
        return None
    return "opencode-database-locked"


def opencode_json_session_id(log: Path)->tuple[str|None,str|None]:
    """Recover an OpenCode JSON-event session id without querying shared host state."""
    if not log.is_file(): return None,"OpenCode JSONL log missing"
    found=[]
    for raw in log.read_text(encoding="utf-8",errors="replace").splitlines():
        try: item=json.loads(raw)
        except json.JSONDecodeError: continue
        if not isinstance(item,dict): continue
        candidates=[item.get("sessionID"),item.get("sessionId"),item.get("session_id")]
        part=item.get("part")
        if isinstance(part,dict): candidates += [part.get("sessionID"),part.get("sessionId"),part.get("session_id")]
        for ident in candidates:
            if ident: found.append(str(ident))
    found=list(dict.fromkeys(found))
    if len(found)==1: return found[0],None
    if len(found)>1: return None,f"multiple OpenCode session ids found in JSONL log: {found[:3]}"
    return None,"no OpenCode session id found in JSONL log"




def capture_live_session_id(args: argparse.Namespace, log: Path, proc: subprocess.Popen, *, attempts: int = 4, delay_seconds: float = 0.5) -> tuple[str|None,str|None]:
    """Best-effort early session capture while the worker is still alive.

    A killed process may never write terminal.json. Persisting the host session ID in
    attempt.json makes same-session continuation possible without querying private host
    databases. Failure is advisory; terminal-time discovery remains a fallback.
    """
    if args.resume_session: return args.resume_session,None
    last_error=None
    for index in range(max(1,attempts)):
        if index: time.sleep(delay_seconds)
        if args.driver in {"opencode","opencode2"}: sid,error=opencode_json_session_id(log)
        elif args.driver=="claude": sid,error=claude_session_id(log)
        else: sid,error=codex_session_id(log)
        if sid: return sid,None
        last_error=error
        if proc.poll() is not None: break
    return None,last_error


def codex_session_id(log: Path)->tuple[str|None,str|None]:
    """Recover the Codex thread id from `codex exec --json` JSONL output."""
    if not log.is_file(): return None,"codex JSONL log missing"
    found=[]
    for raw in log.read_text(encoding="utf-8",errors="replace").splitlines():
        try: item=json.loads(raw)
        except json.JSONDecodeError: continue
        if isinstance(item,dict) and item.get("type")=="thread.started":
            ident=item.get("thread_id") or item.get("threadId") or item.get("id")
            if ident: found.append(str(ident))
    found=list(dict.fromkeys(found))
    if len(found)==1: return found[0],None
    if len(found)>1: return None,f"multiple Codex thread ids found in JSONL log: {found[:3]}"
    return None,"no Codex thread.started event found in JSONL log"


def claude_session_id(log: Path)->tuple[str|None,str|None]:
    """Recover Claude Code's session id from stream-json output."""
    if not log.is_file(): return None,"Claude stream-json log missing"
    found=[]
    for raw in log.read_text(encoding="utf-8",errors="replace").splitlines():
        try: item=json.loads(raw)
        except json.JSONDecodeError: continue
        if not isinstance(item,dict): continue
        ident=item.get("session_id") or item.get("sessionId")
        if ident: found.append(str(ident))
    found=list(dict.fromkeys(found))
    if len(found)==1: return found[0],None
    if len(found)>1: return None,f"multiple Claude session ids found in stream log: {found[:3]}"
    return None,"no Claude session_id found in stream-json log"


def worker_command(args: argparse.Namespace,p:dict[str,Path],env:dict[str,str])->tuple[list[str],dict[str,str],str,Path]:
    """Build a lifecycle-safe command for one mechanically wired worker driver."""
    prompt=p["prompt"].read_text(encoding="utf-8")
    effort=str(getattr(args,"effort",None) or "").strip().lower()
    title=args.title or f"dsd:{args.task_id}:{args.role}:{args.attempt}"
    if args.driver=="opencode":
        if effort: raise ValueError("OpenCode worker effort has no provider-independent CLI contract; choose effort through the configured model/profile endpoint instead")
        if not shutil.which("opencode"): raise FileNotFoundError("opencode executable not found")
        p["db"].parent.mkdir(parents=True,exist_ok=True); env=dict(env); env["OPENCODE_DB"]=str(p["db"])
        cmd=["opencode","run","--format","json","--model",args.model]
        if args.auto_flag: cmd.append(args.auto_flag)
        cmd += ["--title",title,"--dir",str(p["project_root"])]
        if args.resume_session: cmd += ["--session",args.resume_session]
        cmd.append(prompt)
        return cmd,env,title,p["project_root"]
    if args.driver=="opencode2":
        if not shutil.which("opencode2"): raise FileNotFoundError("opencode2 executable not found")
        p["db"].parent.mkdir(parents=True,exist_ok=True); env=dict(env); env["OPENCODE_DB"]=str(p["db"])
        cmd=["opencode2","--standalone","run","--format","json","--model",args.model]
        if args.auto_flag: cmd.append(args.auto_flag)
        cmd += ["--title",title,"--dir",str(p["project_root"])]
        if effort: cmd += ["--variant",effort]
        if args.resume_session: cmd += ["--session",args.resume_session]
        cmd.append(prompt)
        return cmd,env,title,p["project_root"]
    if args.driver=="codex":
        if not shutil.which("codex"): raise FileNotFoundError("codex executable not found")
        task_text=p["task"].read_text(encoding="utf-8",errors="replace")
        writes=False if args.force_read_only else role_writes_project(args.role,task_text)
        # Codex ignores --add-dir under its read-only profile. Use workspace-write
        # with a different writable cwd instead: read-only roles run from the attempt
        # directory and receive the assigned project view explicitly in the rendered
        # prompt, leaving project state outside the writable root. Mutating roles run
        # from the mutating task worktree and add only the attempt directory for their report.
        cwd=p["project_root"] if writes else p["event_dir"]
        cmd=["codex","exec","--json","--model",args.model,"--sandbox","workspace-write","--cd",str(cwd)]
        if effort: cmd[2:2]=["--config",f'model_reasoning_effort="{effort}"']
        if writes: cmd[2:2]=["--add-dir",str(p["event_dir"])]
        if args.resume_session: cmd += ["resume",args.resume_session,prompt]
        else: cmd.append(prompt)
        return cmd,dict(env),title,cwd
    if args.driver=="claude":
        if not shutil.which("claude"): raise FileNotFoundError("claude executable not found")
        # Claude Code print mode gives us the normal agentic tools without an
        # interactive terminal. stream-json preserves liveness/session evidence while
        # --add-dir grants the attempt report directory alongside the project view.
        # `acceptEdits` + explicit common agent tools works across Claude Code plans
        # more broadly than optional `auto` mode while remaining non-interactive. The
        # assigned project view itself enforces read-only Analyst roles at filesystem
        # level; mutating roles already execute in isolated T-BAG worktrees.
        cmd=["claude","-p","--output-format","stream-json","--verbose","--model",args.model,"--permission-mode","acceptEdits","--allowedTools","Bash,Read,Edit,Write,Glob,Grep","--add-dir",str(p["event_dir"])]
        if effort: cmd += ["--effort",effort]
        if args.resume_session: cmd += ["--resume",args.resume_session]
        cmd.append(prompt)
        return cmd,dict(env),title,p["project_root"]
    if effort:
        raise ValueError(f"worker driver {args.driver!r} has no T-BAG effort adapter; omit effort or use a first-class backend with stable effort control")
    raise ValueError(f"worker driver {args.driver!r} is not wired in this release")

def placeholder_text(event_dir: Path)->str:
    return f"# T-BAG worker report placeholder\n{PLACEHOLDER}\nAttempt: {event_dir}\nAppend running status below while working. Keep the marker until the report is complete; remove the marker only when the final self-contained report is ready.\n"


def preflight(args: argparse.Namespace)->dict[str,Path]:
    raw={"project_root":args.project_root,"run_root":args.run_root,"prompt":args.prompt_file,"task":args.task_contract,"rules":args.worker_rules,"baseline":args.scope_baseline,"report":args.report,"event_dir":args.event_dir,"log":args.log,"db":args.db}
    for name,p in raw.items():
        if not p.is_absolute(): raise ValueError(f"{name} must be absolute: {p}")
    paths={k:v.resolve() for k,v in raw.items()}
    if not paths["project_root"].is_dir(): raise ValueError("assigned project view missing")
    if not paths["run_root"].is_dir(): raise ValueError("run root missing")
    for key in ("prompt","task","rules","baseline"):
        if not paths[key].is_file(): raise ValueError(f"required launch file missing: {paths[key]}")
    verify_snapshot(paths["rules"])
    errors=validate_role_contract(args.role,paths["task"].read_text(encoding="utf-8",errors="replace"))
    if errors: raise ValueError("; ".join(errors))
    db=paths["db"]
    for forbidden in (paths["project_root"],paths["run_root"]):
        try: db.relative_to(forbidden)
        except ValueError: continue
        raise ValueError(f"worker runtime-state path must live outside project/run trees: {db}")
    return paths


def reserve(args: argparse.Namespace, p: dict[str,Path])->str:
    event=p["event_dir"]; event.mkdir(parents=True,exist_ok=True)
    reservation=event/"launch-reservation.json"
    attempt_paths=[reservation,event/"attempt.json",event/"terminal.json",p["report"],p["log"]]
    if args.driver in {"opencode2","codex","claude"}: attempt_paths.append(event/"worker.stderr.log")
    for path in attempt_paths:
        if path.exists(): raise ValueError(f"attempt path already exists: {path}")
    p["report"].write_text(placeholder_text(event),encoding="utf-8")
    task_text=p["task"].read_text(encoding="utf-8",errors="replace")
    data={
        "format":"dsd-worker-launch-reservation-v2.2","task_id":args.task_id,"role":args.role,"tier":args.tier,"driver":args.driver,"model":args.model,"attempt":args.attempt,
        "effort":getattr(args,"effort",None),
        "launch_start_interval_seconds":getattr(args,"launch_start_interval_seconds",DEFAULT_LAUNCH_START_INTERVAL_SECONDS),
        "writes_project":False if args.force_read_only else role_writes_project(args.role,task_text),
        "project_root":str(p["project_root"]),"task_contract":str(p["task"]),"worker_rules":str(p["rules"]),"prompt_file":str(p["prompt"]),
        "scope_baseline":str(p["baseline"]),"report":str(p["report"]),"log":str(p["log"]),"db":str(p["db"]),"reserved_at":now(),
    }
    reservation.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return data["reserved_at"]


def report_state(report: Path)->str:
    if not report.is_file(): return "missing"
    text=report.read_text(encoding="utf-8",errors="replace")
    return classify_report_text(text)


def freeze_scope(p: dict[str,Path])->tuple[str|None,str|None]:
    out=p["event_dir"]/"scope-diff.json"
    cp=subprocess.run([sys.executable,str(Path(__file__).resolve().parent/"scope_snapshot.py"),"compare","--root",str(p["project_root"]),"--baseline",str(p["baseline"]),"--output",str(out)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if cp.returncode not in (0,1) or not out.is_file(): return None,(cp.stderr or cp.stdout).strip()[:500]
    return str(out),None


def terminal_error(args: argparse.Namespace,p:dict[str,Path],error:str,exit_code:int=2,started_at:str|None=None)->int:
    scope,scope_error=freeze_scope(p)
    terminal={"format":"dsd-worker-terminal-v2.2","status":"launcher-error","task_id":args.task_id,"role":args.role,"attempt":args.attempt,"tier":args.tier,"driver":args.driver,"model":args.model,"effort":getattr(args,"effort",None),"exit_code":exit_code,"error":error,"started_at":started_at,"ended_at":now(),"report":str(p["report"]),"report_state":report_state(p["report"]),"scope_diff":scope,"scope_error":scope_error}
    atomic_json(p["event_dir"]/"terminal.json",terminal); return exit_code


def child(args: argparse.Namespace,p:dict[str,Path],reserved_at:str)->int:
    p["log"].parent.mkdir(parents=True,exist_ok=True); env=os.environ.copy(); started=None
    try: cmd,env,title,launch_cwd=worker_command(args,p,env)
    except FileNotFoundError as exc: return terminal_error(args,p,str(exc),127,reserved_at)
    except (OSError,ValueError) as exc: return terminal_error(args,p,str(exc),2,reserved_at)
    stderr_path=p["event_dir"]/"worker.stderr.log" if args.driver in {"opencode2","codex","claude"} else None
    out=None; err=None
    try:
        out=p["log"].open("xb",buffering=0)
        if stderr_path is not None: err=stderr_path.open("xb",buffering=0)
        proc=staggered_popen(cmd,interval_seconds=float(getattr(args,"launch_start_interval_seconds",DEFAULT_LAUNCH_START_INTERVAL_SECONDS)),cwd=launch_cwd,env=env,stdout=out,stderr=err if err is not None else subprocess.STDOUT)
        started=now()
    except Exception as exc:
        if out is not None: out.close()
        if err is not None: err.close()
        return terminal_error(args,p,f"failed to launch {args.driver}: {exc}",2,started)
    attempt={"format":"dsd-worker-attempt-v2.2","task_id":args.task_id,"role":args.role,"tier":args.tier,"driver":args.driver,"model":args.model,"effort":getattr(args,"effort",None),"attempt":args.attempt,"event_dir":str(p["event_dir"]),"project_root":str(p["project_root"]),"worker_pid":proc.pid,"launcher_pid":os.getpid(),"reserved_at":reserved_at,"started_at":started,"resume_session":args.resume_session,"launch_start_interval_seconds":getattr(args,"launch_start_interval_seconds",DEFAULT_LAUNCH_START_INTERVAL_SECONDS)}
    if stderr_path is not None: attempt["stderr_log"]=str(stderr_path)
    atomic_json(p["event_dir"]/"attempt.json",attempt)
    process_retries=[]
    retry_delays=iter(OPENCODE_DB_LOCK_RETRY_DELAYS_SECONDS)
    log_start=0; stderr_start=0
    while True:
        session_id,session_error=capture_live_session_id(args,p["log"],proc)
        if session_id: attempt["session_id"]=session_id
        else: attempt.pop("session_id",None)
        if session_error: attempt["session_lookup_error"]=session_error
        else: attempt.pop("session_lookup_error",None)
        atomic_json(p["event_dir"]/"attempt.json",attempt)
        rc=proc.wait()
        reason=retryable_opencode_db_lock(
            args,p,exit_code=rc,session_id=session_id,log_start=log_start,
            stderr_path=stderr_path,stderr_start=stderr_start,
        )
        if reason is None:
            break
        try:
            delay=next(retry_delays)
        except StopIteration:
            break
        retry={"reason":reason,"delay_seconds":delay,"failed_exit_code":rc,"failed_worker_pid":proc.pid,"recorded_at":now()}
        process_retries.append(retry); attempt["process_retries"]=process_retries
        atomic_json(p["event_dir"]/"attempt.json",attempt)
        time.sleep(delay)
        log_start=out.tell() if out is not None else 0
        stderr_start=err.tell() if err is not None else 0
        try:
            proc=staggered_popen(
                cmd,interval_seconds=float(getattr(args,"launch_start_interval_seconds",DEFAULT_LAUNCH_START_INTERVAL_SECONDS)),
                cwd=launch_cwd,env=env,stdout=out,stderr=err if err is not None else subprocess.STDOUT,
            )
        except Exception as exc:
            out.close()
            if err is not None: err.close()
            return terminal_error(args,p,f"failed to relaunch {args.driver} after {reason}: {exc}",2,started)
        attempt["worker_pid"]=proc.pid; attempt["last_restarted_at"]=now()
        atomic_json(p["event_dir"]/"attempt.json",attempt)
    out.close()
    if err is not None: err.close()
    scope,scope_error=freeze_scope(p)
    if not session_id:
        if args.resume_session: session_id,session_error=args.resume_session,None
        elif args.driver in {"opencode","opencode2"}: session_id,session_error=opencode_json_session_id(p["log"])
        elif args.driver=="claude": session_id,session_error=claude_session_id(p["log"])
        else: session_id,session_error=codex_session_id(p["log"])
    terminal={"format":"dsd-worker-terminal-v2.2","status":"process-exited","task_id":args.task_id,"role":args.role,"tier":args.tier,"driver":args.driver,"model":args.model,"attempt":args.attempt,"exit_code":rc,"worker_pid":proc.pid,"launcher_pid":os.getpid(),"session_id":session_id,"session_lookup_error":session_error,"reserved_at":reserved_at,"started_at":started,"ended_at":now(),"report":str(p["report"]),"report_state":report_state(p["report"]),"scope_diff":scope,"scope_error":scope_error}
    if process_retries: terminal["process_retries"]=process_retries
    if stderr_path is not None: terminal["stderr_log"]=str(stderr_path)
    atomic_json(p["event_dir"]/"terminal.json",terminal); return rc


def parser()->argparse.ArgumentParser:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root",type=Path,required=True); ap.add_argument("--run-root",type=Path,required=True); ap.add_argument("--task-id",required=True); ap.add_argument("--role",choices=sorted(ROLE_NAMES),required=True); ap.add_argument("--attempt",type=int,required=True)
    ap.add_argument("--prompt-file",type=Path,required=True); ap.add_argument("--task-contract",type=Path,required=True); ap.add_argument("--worker-rules",type=Path,required=True); ap.add_argument("--scope-baseline",type=Path,required=True); ap.add_argument("--report",type=Path,required=True); ap.add_argument("--event-dir",type=Path,required=True); ap.add_argument("--log",type=Path,required=True); ap.add_argument("--db",type=Path,required=True)
    ap.add_argument("--driver",required=True); ap.add_argument("--model",required=True); ap.add_argument("--effort"); ap.add_argument("--tier",choices=("analyst","grunt"),required=True); ap.add_argument("--title"); ap.add_argument("--resume-session"); ap.add_argument("--force-read-only",action="store_true"); ap.add_argument("--auto-flag",default="--auto"); ap.add_argument("--launch-start-interval-seconds",type=float,default=DEFAULT_LAUNCH_START_INTERVAL_SECONDS); ap.add_argument("--detach",action="store_true"); ap.add_argument("--_child",action="store_true",help=argparse.SUPPRESS); ap.add_argument("--_reserved_at",help=argparse.SUPPRESS)
    return ap


def main()->int:
    args=parser().parse_args()
    try: p=preflight(args)
    except (OSError,ValueError,json.JSONDecodeError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 2
    if args._child:
        if not args._reserved_at: print("ERROR: internal child missing reservation timestamp",file=sys.stderr); return 2
        return child(args,p,args._reserved_at)
    try: reserved=reserve(args,p)
    except (OSError,ValueError) as exc: print(f"ERROR: {exc}",file=sys.stderr); return 2
    if not args.detach: return child(args,p,reserved)
    child_argv=[sys.executable,str(Path(__file__).resolve())]
    for key,value in vars(args).items():
        if key in {"detach","_child","_reserved_at"} or value is None: continue
        opt="--"+key.replace("_","-")
        if isinstance(value,bool):
            if value: child_argv.append(opt)
        elif key=="auto_flag": child_argv.append(f"{opt}={value}")
        else: child_argv += [opt,str(value)]
    child_argv += ["--_child","--_reserved_at",reserved]
    kwargs={"stdin":subprocess.DEVNULL,"stdout":subprocess.DEVNULL,"stderr":subprocess.DEVNULL}
    if os.name=="nt": kwargs["creationflags"]=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    else: kwargs["start_new_session"]=True
    try: proc=subprocess.Popen(child_argv,**kwargs)
    except Exception as exc: return terminal_error(args,p,f"failed to spawn worker monitor: {exc}",2,reserved)
    print(json.dumps({"status":"launched","monitor_pid":proc.pid,"event_dir":str(p["event_dir"]),"terminal_event":str(p["event_dir"]/"terminal.json"),"reserved_at":reserved},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
