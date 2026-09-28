"""Real Chromium navigation and durable-decision smoke test; screenshots are synthetic only."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect


def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8501');p.add_argument('--private',action='store_true');p.add_argument('--output',type=Path,default=Path('evidence/browser'));a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);errors=[];observed=[]
    with sync_playwright() as engine:
        browser=engine.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--disable-dev-shm-usage'])
        page=browser.new_page(viewport={'width':1440,'height':1050});page.on('pageerror',lambda err:errors.append(str(err)))
        page.goto(a.url,wait_until='domcontentloaded');expect(page.get_by_role('heading',name='Business overview')).to_be_visible(timeout=60000)
        if not a.private:expect(page.get_by_text('Synthetic demo',exact=True)).to_be_visible()
        names=['Business Overview','Freight and Lane History','Data Quality and Sources','Settlement Review Desk']
        headings=['Business overview','Freight and lane history','Know what the data can support','Settlement Review Desk']
        for i,(name,heading) in enumerate(zip(names,headings)):
            page.get_by_test_id('stRadio').get_by_text(name,exact=True).click()
            expect(page.get_by_role('heading',name=heading,exact=True)).to_be_visible(timeout=60000)
            if i==0:
                expect(page.get_by_test_id('stMetricValue')).to_have_count(5,timeout=60000)
                if not a.private:expect(page.get_by_test_id('stMetricValue').nth(1)).to_have_text('$1.333')
                expect(page.get_by_test_id('stVegaLiteChart')).to_have_count(2,timeout=30000)
            elif i in (1,2):expect(page.get_by_test_id('stDataFrame').first).to_be_visible(timeout=30000)
            else:
                expect(page.get_by_role('button',name='Record decision',exact=True)).to_be_visible(timeout=30000)
                expect(page.get_by_test_id('stImage').locator('img')).to_be_visible(timeout=30000)
            page.wait_for_timeout(700)
            expect(page.get_by_test_id('stException')).to_have_count(0)
            if not a.private:page.screenshot(path=str(a.output/f'{i+1}_{name.replace(" ","_")}.png'),full_page=True)
            observed.append({'page':name,'rendered':True})
        expect(page.get_by_test_id('stImage').locator('img')).to_be_visible(timeout=30000)
        if not a.private:
            page.get_by_test_id('stImage').screenshot(path=str(a.output/'7_Original_source.png'))
            page.get_by_label('Reason for decision').fill('Synthetic browser test: defer for source review; no financial change.')
            page.get_by_role('button',name='Record decision',exact=True).click()
            expect(page.get_by_text('Recorded: Deferred with a note. The source issue remains unresolved.',exact=True).first).to_be_visible(timeout=30000)
            page.reload();expect(page.get_by_role('heading',name=headings[0],exact=True)).to_be_visible(timeout=30000)
            page.get_by_test_id('stRadio').get_by_text(names[3],exact=True).click()
            expect(page.get_by_text('Recorded: Deferred with a note. The source issue remains unresolved.',exact=True).first).to_be_visible(timeout=30000)
            page.get_by_role('heading',name='Decision and application history').scroll_into_view_if_needed()
            page.screenshot(path=str(a.output/'5_Decision_persisted.png'),full_page=True)
            page.set_viewport_size({'width':430,'height':932});page.screenshot(path=str(a.output/'6_Narrow_screen.png'),full_page=True)
        browser.close()
    result={'dataset':'private' if a.private else 'synthetic','pages':observed,'source_image_rendered':True,'decision_survived_browser_reload':None if a.private else True,'browser_errors':errors}
    (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
