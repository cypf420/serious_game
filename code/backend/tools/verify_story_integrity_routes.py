"""Run the unchanged 95-route assertions, retaining failures and snapshot identity."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

from tools import run_story_routes_v3_isolated as runner

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args()
    if args.output.exists(): raise ValueError('Evidence output already exists')
    backend=Path(__file__).resolve().parents[1]
    repo=backend.parents[1]
    before=runner.current_workspace_fingerprint(repo,backend)
    evidence={}
    original=runner.finalize_summary
    def retaining_finalizer(**kwargs):
        evidence.update(kwargs)
        return original(**kwargs)  # Preserve all original assertions, including mismatches.
    try:
        with patch.object(runner,'finalize_summary',side_effect=retaining_finalizer):
            summary=runner.run_isolated(args.workers)
        evidence['summary']=summary
        evidence['status']='passed'
    except Exception as exc:
        evidence['status']='failed'
        evidence['error']={'type':type(exc).__name__,'message':str(exc)}
    after=runner.current_workspace_fingerprint(repo,backend)
    evidence['workspace_before']=before
    evidence['workspace_after']=after
    evidence['stable_snapshot']=before==after
    if before!=after: evidence['status']='unstable'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as stream:
        json.dump(evidence,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'status':evidence['status'],'stable_snapshot':before==after,'output':str(args.output),'error':evidence.get('error')},ensure_ascii=False))
    return int(evidence['status']!='passed')

if __name__=='__main__': raise SystemExit(main())
