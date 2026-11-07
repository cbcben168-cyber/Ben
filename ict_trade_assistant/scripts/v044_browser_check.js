async (page) => {
  const result = { url: page.url(), checks: [], layouts: [] };
  const check = (condition, message) => {
    if (!condition) throw new Error(message);
    result.checks.push(message);
  };
  const lab = () => page.locator('details').filter({hasText:'调整分析因子 · v0.4.4'});
  const openLab = async () => {
    const panel = lab();
    if (!(await panel.getByRole('slider',{name:/EMA短期周期/}).isVisible())) await panel.locator('summary').click();
    await panel.getByRole('slider',{name:/EMA短期周期/}).waitFor({state:'visible'});
    await page.waitForFunction(() => [...document.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent.includes('调整分析因子'))?.getBoundingClientRect().height>1000);
  };
  const closeLab = async () => {
    const panel=lab();
    if (await panel.getByRole('slider',{name:/EMA短期周期/}).isVisible()) await panel.locator('summary').click();
    await panel.getByRole('slider',{name:/EMA短期周期/}).waitFor({state:'hidden'});
    await page.waitForFunction(() => [...document.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent.includes('调整分析因子'))?.getBoundingClientRect().height<100);
  };
  const select = async (label,value) => {
    const input=page.getByRole('combobox',{name:label,exact:true});
    if (await input.inputValue() === value) return;
    await input.fill(value);
    await input.press('ArrowDown');
    await input.press('Enter');
  };
  await page.keyboard.press('Escape');
  await page.getByText('Top5 · 观察名单', {exact:true}).waitFor();
  await openLab();
  await select('数据模式','历史回放');
  await select('历史交易日期（纽约）','2026-10-28');
  await page.waitForFunction(() => document.querySelector('main').innerText.includes('历史回放 · 富途原生日K归档 · 日K · 数据截至 2026-10-28'));
  check(true, '网页日期切换到2026-10-28');
  const short = page.getByRole('slider', {name:/EMA短期周期/});
  await page.getByRole('button', {name:'恢复默认', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('input[type=range][aria-label="EMA短期周期"]').value === '20');
  const original = await lab().locator('table').nth(1).innerText();
  await short.focus();
  await short.press('Home');
  await page.waitForFunction(() => document.querySelector('input[type=range][aria-label="EMA短期周期"]').value === '5');
  await page.waitForFunction(() => document.querySelector('main').innerText.includes('EMA短期周期：20 → 5'));
  const changed = await lab().locator('table').nth(1).innerText();
  check(original !== changed, 'EMA20改为5后计算数值变化');
  const name = '浏览器验收_短期5';
  await page.getByRole('textbox', {name:'实验组合名称', exact:true}).fill(name);
  await page.getByRole('button', {name:'保存组合', exact:true}).click();
  await page.getByText('实验组合已保存，重新打开仍可载入。', {exact:true}).waitFor();
  check(true, '浏览器保存成功');
  await page.getByRole('textbox', {name:'实验组合名称', exact:true}).fill('Baseline');
  await page.getByRole('button', {name:'保存组合', exact:true}).click();
  await page.getByText('请使用1–60字的实验名称；Baseline不可覆盖。', {exact:true}).waitFor();
  check(true, '网页拒绝覆盖Baseline');
  await page.getByRole('button', {name:'恢复默认', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('main').innerText.includes('当前使用默认参数，与Baseline一致。'));
  check(await lab().locator('table').nth(1).innerText() === original, '恢复默认后数值恢复');
  await page.reload();
  await page.getByText('Top5 · 观察名单', {exact:true}).waitFor();
  await openLab();
  const preset = page.getByRole('combobox', {name:'参数组合', exact:true});
  await select('参数组合',name);
  check(await preset.inputValue()===name, '保存的组合出现在参数列表');
  await page.getByRole('button', {name:'载入组合', exact:true}).click();
  await page.waitForFunction(() => document.querySelector('input[type=range][aria-label="EMA短期周期"]').value === '5');
  check(true, '重开页面后载入持久化参数');
  await page.getByRole('button', {name:'恢复默认', exact:true}).click();
  for (const [width,height,label] of [[2560,1440,'landscape'],[1440,2560,'portrait']]) {
    await page.setViewportSize({width,height});
    await closeLab();
    await page.locator('main').evaluate(el => el.scrollTop = 0);
    await page.locator('.st-key-answer-chart').scrollIntoViewIfNeeded();
    await page.locator('main').evaluate(el => el.scrollTop = 0);
    const geometry = await page.evaluate(() => {
      const box = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
      return {width:innerWidth,height:innerHeight,scale:visualViewport.scale,
              chart:box('.st-key-answer-chart'),action:box('.st-key-answer-action'),
              overflow:document.documentElement.scrollWidth>innerWidth};
    });
    check(geometry.width===width && geometry.height===height && geometry.scale===1, label+'精确尺寸及100%缩放');
    check(geometry.chart.width>0 && geometry.action.width>0 && geometry.chart.right<=geometry.action.left+1, label+'图表与行动卡无重叠');
    check(!geometry.overflow, label+'无横向溢出');
    result.layouts.push(geometry);
    await page.screenshot({path:'output/playwright/v044-'+label+'-main.png',animations:'disabled'});
    await openLab();
    check((await lab().boundingBox()).height>800,label+'因子区完整展开');
    await lab().screenshot({path:'output/playwright/v044-'+label+'-factors.png',animations:'disabled'});
  }
  check(await page.locator('[data-testid=stException]').count()===0, '验收结束无页面异常');
  return result;
}
