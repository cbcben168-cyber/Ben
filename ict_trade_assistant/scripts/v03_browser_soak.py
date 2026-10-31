"""对本次独立Playwright会话作有界双窗口检查，不创建计划任务。"""
from pathlib import Path
import subprocess
import time
import json

ROOT=Path(__file__).resolve().parents[1]


def main():
    began=time.monotonic()
    output=ROOT/'data/v03_acceptance/browser-soak.jsonl'
    with output.open('w',encoding='utf-8',buffering=1) as stream:
        while True:
            elapsed=round(time.monotonic()-began,3)
            try:
                done=subprocess.run(['npx.cmd','--yes','--package','@playwright/cli','playwright-cli','-s=ictv03','run-code',
                                     '--filename','scripts/v03_browser_checkpoint.js'],
                                    cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=55)
                row=dict(elapsed_seconds=elapsed,exit_code=done.returncode,output=done.stdout,error=done.stderr)
            except subprocess.TimeoutExpired:
                row=dict(elapsed_seconds=elapsed,error='检查超过55秒；未终止浏览器或服务')
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            if time.monotonic()-began>=3600:break
            time.sleep(30)
    print(str(output))


if __name__=='__main__':main()
