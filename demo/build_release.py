"""Build a clean synthetic release from an explicit source-file allowlist."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

CODE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CODE))


def build():
    output=CODE/'release'/('Prime_Synthetic_Dashboard_1_1_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir(parents=True)
    singles=['pyproject.toml','uv.lock','.python-version','.gitignore','.streamlit/config.toml',
        'prime_dashboard.py','prime_structure.py','prime_workbench.py','prime_review.py','prime_details.py','prime_lab.py','prime_audit.py']
    dirs=['analytics','dashboard','review','sql','tests','docs','powerbi','powerplatform','Jobs_Prime_Release']
    selected=[CODE/p for p in singles]
    for directory in dirs:
        selected += [p for p in (CODE/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.sql','.md','.json','.dax','.pq')]
    selected += [p for p in (CODE/'demo').glob('*.py')]
    selected += [p for p in (CODE/'evidence').rglob('*') if p.is_file() and p.suffix in ('.json','.png','.md')]
    for source in selected:
        destination=output/source.relative_to(CODE);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
    (output/'README.md').write_text('''# Prime synthetic dashboard and local review desk

Independent fictional demonstration. No private records are included. AI-assisted implementation.

```bash
uv sync --frozen
.venv/bin/python prime_dashboard.py demo
.venv/bin/python prime_dashboard.py serve
```

Open http://127.0.0.1:8501. Python 3.13 and Poppler are required; Chromium is needed only for the optional browser test. See docs/DASHBOARD_GUIDE.md for setup, four screens, backup/restore and supported review actions. Run `.venv/bin/python -m unittest discover -s tests -q` for the acceptance suite.

The Linux interface and controlled nonfinancial review writer are demonstrated. Full historical financial reconciliation, Power BI Desktop and the Microsoft cloud workflow remain incomplete/pending. No GitHub publication or commit is claimed.
''')
    files={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file()}
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'spec_revision':'1.1','synthetic_only':True,'private_files_included':False,'selection':'explicit source/doc/synthetic-evidence allowlist; no runtime folders','git_commit':None,'publication':'not published','files':files}
    (output/'release_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=output.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.rglob('*')):
            if p.is_file():z.write(p,output.name+'/'+str(p.relative_to(output)))
    (CODE/'release/latest.json').write_text(json.dumps({'directory':str(output),'zip':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2)+'\n')
    print(output);print(archive)
    return output


if __name__=='__main__':build()
