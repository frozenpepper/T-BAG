#!/usr/bin/env python3
"""Run or reuse expensive verification evidence bound to one exact candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

FORMAT="tbag-candidate-evidence-v1"
MAX_TAIL_BYTES=65536

DEPENDENCY_PATTERNS=(
    "package-lock.json","npm-shrinkwrap.json","pnpm-lock.yaml","yarn.lock","bun.lock","bun.lockb",
    "poetry.lock","uv.lock","requirements.txt","requirements-dev.txt","Pipfile.lock",
    "Cargo.lock","go.sum","composer.lock","Gemfile.lock",
)
CONFIG_PATTERNS=(
    "package.json","pyproject.toml","pytest.ini","tox.ini",".python-version",".npmrc",
    "Cargo.toml","go.mod","tsconfig.json","tsconfig.*.json",
    "jest.config.*","vitest.config.*","playwright.config.*",
)
INSTALLED_METADATA=(
    "node_modules/.package-lock.json","node_modules/.modules.yaml",
    ".venv/pyvenv.cfg","venv/pyvenv.cfg",
)


def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def run_bytes(argv:list[str],cwd:Path)->bytes:
    cp=subprocess.run(argv,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if cp.returncode!=0:
        raise ValueError(f"command failed ({cp.returncode}): {' '.join(argv)}: "+cp.stderr.decode("utf-8",errors="replace")[:800])
    return cp.stdout


def path_digest(path:Path)->dict[str,Any]:
    if path.is_symlink():
        raw=os.readlink(path).encode("utf-8",errors="surrogateescape")
        return {"path":str(path),"kind":"symlink","sha256":sha(raw),"bytes":len(raw)}
    raw=path.read_bytes()
    return {"path":str(path),"kind":"file","sha256":sha(raw),"bytes":len(raw)}


def matching_files(root:Path,patterns:tuple[str,...])->list[Path]:
    out=[]
    for pattern in patterns:
        out.extend(p for p in root.glob(pattern) if p.is_file() or p.is_symlink())
    return sorted(dict.fromkeys(out),key=lambda p:str(p))


def files_fingerprint(root:Path,patterns:tuple[str,...],extra:list[Path]|None=None)->dict[str,Any]:
    files=matching_files(root,patterns)
    for path in extra or []:
        candidate=path if path.is_absolute() else root/path
        if candidate.is_file() or candidate.is_symlink(): files.append(candidate)
        else: raise ValueError(f"bound evidence input missing: {candidate}")
    rows=[]; seen=set()
    for path in files:
        key=str(path)
        if key in seen: continue
        seen.add(key)
        row=path_digest(path)
        try: row["relative"]=path.relative_to(root).as_posix()
        except ValueError: row["relative"]=str(path)
        rows.append(row)
    payload=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
    return {"sha256":sha(payload),"files":rows}


def candidate_fingerprint(root:Path)->dict[str,Any]:
    head=run_bytes(["git","rev-parse","HEAD"],root).decode().strip()
    pathspec=[".",":(exclude)TBag/**",":(exclude)AnalystAndGrunt/**"]
    diff=run_bytes(["git","diff","--binary","--no-ext-diff","HEAD","--",*pathspec],root)
    raw=run_bytes(["git","ls-files","-z","--others","--exclude-standard","--",*pathspec],root)
    untracked=[]
    for item in raw.split(b"\0"):
        if not item: continue
        rel=item.decode("utf-8",errors="surrogateescape"); path=root/rel
        if path.is_file() or path.is_symlink():
            row=path_digest(path); row["relative"]=rel; row.pop("path",None); untracked.append(row)
    payload=json.dumps({"head":head,"diff_sha256":sha(diff),"untracked":untracked},sort_keys=True,separators=(",",":")).encode()
    return {"sha256":sha(payload),"head":head,"diff_sha256":sha(diff),"diff_bytes":len(diff),"untracked":untracked}


def executable_fingerprint(command:list[str])->dict[str,Any]:
    raw=command[0]
    resolved=shutil.which(raw) or (str(Path(raw).resolve()) if Path(raw).exists() else "")
    if not resolved:
        return {"argv0":raw,"resolved":None}
    path=Path(resolved)
    try:
        st=path.stat()
        return {"argv0":raw,"resolved":str(path.resolve()),"size":st.st_size,"mtime_ns":st.st_mtime_ns}
    except OSError:
        return {"argv0":raw,"resolved":resolved}


def runtime_fingerprint(command:list[str])->dict[str,Any]:
    data={
        "python":sys.version.split()[0],"python_executable":sys.executable,
        "platform":platform.platform(),
        "worker_driver":os.environ.get("TBAG_WORKER_DRIVER"),
        "worker_model":os.environ.get("TBAG_WORKER_MODEL"),
        "worker_role":os.environ.get("TBAG_WORKER_ROLE"),
        "virtual_env":os.environ.get("VIRTUAL_ENV"),
        "command_executable":executable_fingerprint(command),
    }
    node=shutil.which("node")
    if node:
        cp=subprocess.run([node,"-p","JSON.stringify({version:process.version,modules:process.versions.modules})"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=False)
        if cp.returncode==0:
            try: data["node"]=json.loads(cp.stdout)
            except json.JSONDecodeError: data["node"]={"raw":cp.stdout.strip()[:200]}
    payload=json.dumps(data,sort_keys=True,separators=(",",":")).encode()
    return {"sha256":sha(payload),"facts":data}


def tail(path:Path,max_bytes:int=MAX_TAIL_BYTES)->str:
    size=path.stat().st_size
    with path.open("rb") as handle:
        if size>max_bytes: handle.seek(-max_bytes,os.SEEK_END)
        return handle.read(max_bytes).decode("utf-8",errors="replace")


def hash_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk=handle.read(1024*1024)
            if not chunk: break
            h.update(chunk)
    return h.hexdigest()


def resolve_path(raw:str|None,env_name:str,flag_name:str)->Path:
    value=raw or os.environ.get(env_name)
    if not value: raise ValueError(f"missing --{flag_name} and {env_name}")
    return Path(value).resolve()


def command_run(args:argparse.Namespace)->int:
    project=resolve_path(args.project_root,"TBAG_PROJECT_VIEW","project-root")
    run_root=resolve_path(args.run_root,"TBAG_RUN_ROOT","run-root")
    if subprocess.run(["git","rev-parse","--is-inside-work-tree"],cwd=project,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0:
        raise ValueError(f"assigned project view is not a Git worktree: {project}")
    info=json.loads((run_root/"run.json").read_text(encoding="utf-8"))
    primary=Path(str(info["project_root"])).resolve()
    cache=(primary/"TBag"/"cache"/"candidate-evidence").resolve()
    cache.mkdir(parents=True,exist_ok=True)

    command=list(args.argv)
    if command and command[0]=="--": command=command[1:]
    if not command: raise ValueError("candidate evidence requires an exact command after --")
    extras=[Path(x) for x in (args.bind or [])]

    candidate=candidate_fingerprint(project)
    dependencies=files_fingerprint(project,DEPENDENCY_PATTERNS)
    installed=files_fingerprint(project,INSTALLED_METADATA)
    configuration=files_fingerprint(project,CONFIG_PATTERNS,extras)
    runtime=runtime_fingerprint(command)
    key_payload={
        "format":FORMAT,"candidate":candidate["sha256"],"dependencies":dependencies["sha256"],
        "installed_dependencies":installed["sha256"],"configuration":configuration["sha256"],
        "runtime":runtime["sha256"],"command":command,
    }
    key=sha(json.dumps(key_payload,sort_keys=True,separators=(",",":")).encode())
    record_path=cache/f"{key}.json"
    if args.reuse and record_path.is_file():
        record=json.loads(record_path.read_text(encoding="utf-8"))
        exit_code=int(record.get("result",{}).get("exit_code") or 0)
        print(json.dumps({"reused":True,"key":key,"record":str(record_path),"exit_code":exit_code,"duration_seconds":record.get("result",{}).get("duration_seconds")},sort_keys=True))
        return exit_code

    started=time.time()
    with tempfile.NamedTemporaryFile(dir=cache,prefix=f".{key}.",suffix=".stdout",delete=False) as out, tempfile.NamedTemporaryFile(dir=cache,prefix=f".{key}.",suffix=".stderr",delete=False) as err:
        out_path=Path(out.name); err_path=Path(err.name)
        cp=subprocess.run(command,cwd=project,stdout=out,stderr=err,check=False)
    duration=round(time.time()-started,3)
    result={
        "exit_code":cp.returncode,"duration_seconds":duration,
        "stdout":{"bytes":out_path.stat().st_size,"sha256":hash_file(out_path),"tail":tail(out_path)},
        "stderr":{"bytes":err_path.stat().st_size,"sha256":hash_file(err_path),"tail":tail(err_path)},
    }
    record={
        "format":FORMAT,"key":key,"label":args.label,"recorded_at":time.time(),
        "project_view":str(project),"run_root":str(run_root),"producer_attempt":os.environ.get("TBAG_ATTEMPT_DIR"),
        "candidate":candidate,"dependencies":dependencies,"installed_dependencies":installed,
        "configuration":configuration,"runtime":runtime,"command":command,"result":result,
        "semantics":"Reusable execution evidence for this exact bound candidate/runtime/command; never an acceptance verdict.",
    }
    tmp=record_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(tmp,record_path)
    try:
        sys.stdout.write(result["stdout"]["tail"])
        if result["stderr"]["tail"]: sys.stderr.write(result["stderr"]["tail"])
    finally:
        out_path.unlink(missing_ok=True); err_path.unlink(missing_ok=True)
    print(json.dumps({"reused":False,"key":key,"record":str(record_path),"exit_code":cp.returncode,"duration_seconds":duration},sort_keys=True))
    return cp.returncode


def parser()->argparse.ArgumentParser:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="command",required=True)
    p=sub.add_parser("run")
    p.add_argument("--run-root"); p.add_argument("--project-root"); p.add_argument("--label")
    p.add_argument("--bind",action="append",default=[])
    mode=p.add_mutually_exclusive_group(); mode.add_argument("--reuse",action="store_true"); mode.add_argument("--fresh",action="store_true")
    p.add_argument("argv",nargs=argparse.REMAINDER)
    return ap


def main()->int:
    args=parser().parse_args()
    try:
        if args.command=="run": return command_run(args)
        raise ValueError(f"unsupported command: {args.command}")
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
        print(f"candidate_evidence error: {exc}",file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
