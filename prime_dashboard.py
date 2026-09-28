"""Prepare reporting snapshots or launch the localhost Linux dashboard."""
import argparse
import os
from pathlib import Path
import sys

CODE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('demo','refresh','serve','backup'))
    p.add_argument('--private',action='store_true',help='Use ~/PrimeData; default is independent synthetic demo')
    p.add_argument('--data-root',type=Path)
    p.add_argument('--port',type=int,default=8501)
    a=p.parse_args();root=(a.data_root or (Path.home()/'PrimeData' if a.private else CODE/'demo/runtime')).expanduser().resolve()
    if a.command=='demo':
        if a.private:p.error('The demo command never uses private data')
        from demo.generate import generate
        generate(root)
    if a.command in ('demo','refresh'):
        from review.service import initialize
        from analytics.reporting import export
        initialize(root);print('Reporting snapshot:',export(root));return
    if a.command=='backup':
        from review.service import backup_journal
        from analytics.storage import backup
        from prime_workbench import locks
        with locks(root):
            ledger=backup(root,'desk_pair');journal=ledger.with_name(ledger.stem+'_review.sqlite');backup_journal(root,journal)
        print('Ledger:',ledger);print('Review journal:',journal);return
    if not (root/'reporting/latest.json').is_file():p.error('Prepare a snapshot first: use demo or refresh with the same root')
    os.environ['PRIME_DASHBOARD_ROOT']=str(root)
    os.chdir(CODE)
    os.execv(sys.executable,[sys.executable,'-m','streamlit','run',str(CODE/'dashboard/app.py'),
        '--server.address=127.0.0.1',f'--server.port={a.port}','--server.headless=true','--browser.gatherUsageStats=false','--server.fileWatcherType=none'])


if __name__=='__main__':main()
