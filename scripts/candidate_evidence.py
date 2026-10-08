#!/usr/bin/env python3
"""Run or reuse expensive verification evidence bound to one exact candidate."""
from __future__ import annotations

import argparse
import fcntl
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
RUNTIME_ENV_NAMES=(
    "PATH","VIRTUAL_ENV","PYTHONPATH","NODE_OPTIONS","NODE_ENV","CI",
    "PLAYWRIGHT_BROWSERS_PATH","npm_config_userconfig",
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
        if path.is_symlink():
            if not path.is_file():
                raise ValueError(f"bound verification input symlink is not a regular file: {path}")
            # Link text alone does not track mutations of an external ignored input.
            # Include the bytes actually read when the command follows the link.
            row["linked_content_sha256"]=hash_file(path)
        try:
            # Candidate/cache identity must be independent of the task's worktree
            # mount path. Otherwise identical Reviewer/Implementer views cannot share
            # a 16-minute suite result. External bound files keep absolute identity.
            row["relative"]=path.relative_to(root).as_posix()
            row.pop("path",None)
        except ValueError:
            row["relative"]=str(path.resolve())
            row.pop("path",None)
        rows.append(row)
    payload=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
    return {"sha256":sha(payload),"files":rows}


def _tracked_modes(root:Path)->dict[str,str]:
    raw=run_bytes(["git","ls-files","--stage","-z","--",".",":(exclude)TBag/**",":(exclude)AnalystAndGrunt/**"],root)
    modes={}
    for item in raw.split(b"\0"):
        if not item: continue
        meta,sep,path_raw=item.partition(b"\t")
        if not sep: continue
        fields=meta.decode("ascii",errors="replace").split()
        if len(fields)<3 or fields[2]!="0": continue
        modes[path_raw.decode("utf-8",errors="surrogateescape")]=fields[0]
    return modes


def _submodule_manifest(path:Path)->dict[str,Any]:
    nested=candidate_fingerprint(path)
    # Only the canonical nested bytes belong to the parent cache key.
    # A nested checkpoint commit can change HEAD without changing content.
    return {
        "tree_sha256":nested["sha256"],
        "entry_count":nested["entry_count"],
    }


def candidate_fingerprint(root:Path)->dict[str,Any]:
    """Canonical current candidate tree, independent of checkpoint/HEAD representation."""
    pathspec=[".",":(exclude)TBag/**",":(exclude)AnalystAndGrunt/**"]
    raw=run_bytes(["git","ls-files","-z","--cached","--others","--exclude-standard","--",*pathspec],root)
    modes=_tracked_modes(root)
    rows=[]
    for item in sorted({x for x in raw.split(b"\0") if x}):
        rel=item.decode("utf-8",errors="surrogateescape"); path=root/rel
        mode=modes.get(rel)
        if mode=="160000":
            if path.is_dir():
                rows.append({"relative":rel,"kind":"submodule","mode":mode,**_submodule_manifest(path)})
            # Missing gitlink is a deletion and therefore absent from the current tree.
            continue
        if not (path.is_file() or path.is_symlink()):
            # A tracked path missing from disk is deleted from the current candidate.
            continue
        row=path_digest(path); row["relative"]=rel; row.pop("path",None)
        if path.is_symlink(): row["mode"]="120000"
        else: row["mode"]="100755" if (path.stat().st_mode & 0o111) else "100644"
        rows.append(row)
    payload=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
    head=run_bytes(["git","rev-parse","HEAD"],root).decode().strip()
    return {"sha256":sha(payload),"head_observed":head,"entry_count":len(rows),"entries":rows}


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
        "environment":{name:os.environ.get(name) for name in RUNTIME_ENV_NAMES},
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


def record_attempt_reference(*,record_path:Path,key:str,label:str|None,reused:bool,result:dict[str,Any])->None:
    raw=os.environ.get("TBAG_ATTEMPT_DIR")
    if not raw: return
    attempt=Path(raw).resolve()
    if not attempt.is_dir(): return
    index=attempt/"candidate-evidence.jsonl"
    entry={
        "format":"tbag-candidate-evidence-reference-v1","key":key,"label":label,
        "record":str(record_path),"reused":reused,
        "exit_code":result.get("exit_code"),"duration_seconds":result.get("duration_seconds"),
    }
    with index.open("a",encoding="utf-8") as handle:
        handle.write(json.dumps(entry,sort_keys=True,separators=(",",":"))+"\n")


def resolve_path(raw:str|None,env_name:str,flag_name:str)->Path:
    value=raw or os.environ.get(env_name)
    if not value: raise ValueError(f"missing --{flag_name} and {env_name}")
    return Path(value).resolve()


def valid_cached_result(record_path:Path, key:str, bound:dict[str,Any])->dict[str,Any]|None:
    """Refuse incomplete/stale cache records, especially missing exit-code evidence."""
    try: record=json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError,ValueError,json.JSONDecodeError): return None
    if not isinstance(record,dict) or record.get("format")!=FORMAT or record.get("key")!=key:
        return None
    for name,value in bound.items():
        actual=record.get(name)
        if name=="candidate":
            # Snapshot commits can change without changing candidate bytes.
            if not isinstance(actual,dict) or actual.get("sha256")!=value["sha256"]:
                return None
        elif actual!=value:
            return None
    result=record.get("result")
    if not isinstance(result,dict) or type(result.get("exit_code")) is not int: return None
    for stream in ("stdout","stderr"):
        item=result.get(stream)
        if not isinstance(item,dict) or not isinstance(item.get("sha256"),str) or type(item.get("bytes")) is not int or not isinstance(item.get("tail"),str):
            return None
    if not isinstance(result.get("duration_seconds"),(int,float)): return None
    return result


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
    # A fixed set of advisory locks bounds disk growth while serializing each
    # candidate key across worker processes and Git worktrees. Check the cache
    # again *after* acquiring the lock; otherwise parallel Reviewers execute the
    # same expensive suite and race to publish its .json.tmp record.
    with (cache/f".lock-{key[:2]}").open("a+b") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        if args.reuse and record_path.is_file():
            result=valid_cached_result(record_path,key,{
                "candidate":candidate,"dependencies":dependencies,
                "installed_dependencies":installed,"configuration":configuration,
                "runtime":runtime,"command":command,
            })
            if result is not None:
                exit_code=result["exit_code"]
                record_attempt_reference(record_path=record_path,key=key,label=args.label,reused=True,result=result)
                print(json.dumps({"reused":True,"key":key,"record":str(record_path),"exit_code":exit_code,"duration_seconds":result.get("duration_seconds")},sort_keys=True))
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
        record_attempt_reference(record_path=record_path,key=key,label=args.label,reused=False,result=result)
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
